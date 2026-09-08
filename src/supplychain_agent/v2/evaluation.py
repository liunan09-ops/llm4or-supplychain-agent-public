"""Independent scored cases; no dataset or expected answers enter Agent prompts."""

import argparse
import hashlib
import json
import platform
import tempfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
from pydantic import Field, model_validator

from ..optimizer import validate_solution
from ..schemas import PlanParameters, StrictModel
from .agent import Agent
from .contracts import Outcome, Request, Task, parameters_equal
from .database import BusinessStore
from .retrieval import PolicyRetriever, seed_policies
from .tools import REGISTRY, ToolError, execute
from .trace import TraceStore


class Case(StrictModel):
    id: str
    message: str
    intent: Task
    status: Outcome
    tools: list[str]
    parameters: PlanParameters = Field(default_factory=PlanParameters)
    sku_ids: list[str] = Field(default_factory=list)
    policy_docs: list[str] = Field(default_factory=list)
    fault: str | None = None
    category: str

    @model_validator(mode="after")
    def validate_case(self):
        if not set(self.tools).issubset(REGISTRY):
            raise ValueError("unknown_expected_tool")
        if self.fault not in {None, "inventory_unavailable"}:
            raise ValueError("unsupported_fault")
        return self


class RetrievalCase(StrictModel):
    id: str
    query: str
    relevant_documents: list[str] = Field(min_length=1)


def load_cases(path, schema=Case):
    rows = [
        schema.model_validate_json(line)
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]
    if not rows or len({row.id for row in rows}) != len(rows):
        raise ValueError("empty_or_duplicate_dataset")
    return rows


def assert_disjoint(first, second):
    a, b = load_cases(first), load_cases(second)
    if {r.id for r in a} & {r.id for r in b} or {r.message for r in a} & {r.message for r in b}:
        raise ValueError("development_heldout_overlap")


def source_metadata():
    root = Path(__file__).resolve().parents[1]
    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.suffix in {".py", ".md"}
    }
    return {
        "source_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
        "source_files": files,
        "python": platform.python_version(),
        "dependencies": {
            name: version(name)
            for name in ("scipy", "pydantic", "fastapi", "faiss-cpu", "numpy", "httpx")
        },
    }


def ratio(values):
    return {
        "passed": sum(values),
        "total": len(values),
        "rate": sum(values) / len(values) if values else None,
    }


def score(case, response, snapshot):
    attempts = [e for e in response.trace if e.kind == "tool"]
    selected = {e.name for e in attempts}
    tool_selection = selected == set(case.tools)
    intent_ok = response.intent is not None and response.intent.action == case.intent
    parameters_ok = response.intent is not None and parameters_equal(
        response.intent.parameters, case.parameters
    )
    args_ok = parameters_ok
    plan_ids = {
        e.data["result"]["plan_id"]
        for e in attempts
        if e.name == "replenishment_optimizer" and e.status == "ok"
    }
    for event in attempts:
        name, args = event.name, event.data["arguments"]
        try:
            parsed = REGISTRY[name][0].model_validate(args)
            if name in {"inventory_query", "supplier_query", "order_query"}:
                expected = set(case.sku_ids) or snapshot.ids
                if case.intent in {"optimize", "query_then_optimize"}:
                    expected = snapshot.ids
                args_ok = args_ok and (set(parsed.sku_ids) or snapshot.ids).issubset(expected)
            elif name == "replenishment_optimizer":
                args_ok = args_ok and parameters_equal(parsed.parameters, case.parameters)
            elif name == "solution_validator":
                args_ok = args_ok and parsed.plan_id in plan_ids
        except (ValueError, KeyError, TypeError):
            args_ok = False
    # Check coverage, not just valid individual query subsets.
    query_for_intent = {
        "inventory": "inventory_query",
        "supplier": "supplier_query",
        "orders": "order_query",
    }
    required_queries = (
        ["inventory_query", "supplier_query"]
        if case.intent in {"optimize", "query_then_optimize"}
        else ([query_for_intent[case.intent]] if case.intent in query_for_intent else [])
    )
    if case.fault is None:
        for name in required_queries:
            covered = set()
            for event in attempts:
                if event.name == name and event.status == "ok":
                    covered.update(event.data["arguments"].get("sku_ids") or snapshot.ids)
            args_ok = args_ok and covered == (set(case.sku_ids) or snapshot.ids)
    docs = {c.id.split(":")[0] for c in response.citations}
    retrieval_hit = bool(docs & set(case.policy_docs)) if case.policy_docs else None
    constraint_pass = None
    if response.result is not None and response.result.status in {"optimal", "feasible"}:
        constraint_pass = validate_solution(
            snapshot.scenario(case.parameters), case.parameters, response.result.orders
        ).valid
        constraint_pass = (
            constraint_pass
            and response.result.validation is not None
            and response.result.validation.valid
        )
    status_ok = response.status == case.status
    # Wrong/empty final data must not count as success even with a correct route.
    if case.intent in {"inventory", "supplier", "orders"} and response.status == "completed":
        key = {"inventory": "inventory", "supplier": "suppliers", "orders": "purchase_orders"}[
            case.intent
        ]
        expected = {
            "inventory": lambda: snapshot.inventory(case.sku_ids),
            "supplier": lambda: snapshot.suppliers(case.sku_ids),
            "orders": lambda: snapshot.purchase_orders(case.sku_ids),
        }[case.intent]()
        answer_ok = response.facts.get(key) == expected
    else:
        answer_ok = bool(response.explanation)
    if case.policy_docs:
        answer_ok = answer_ok and any(
            c.id in response.explanation and c.id.split(":")[0] in case.policy_docs
            for c in response.citations
        )
    raw_intent = None
    for event in response.trace:
        if event.kind == "llm" and event.name == "intent":
            try:
                raw_intent = json.loads(event.data["response"]["content"])["action"] == case.intent
            except (ValueError, KeyError, TypeError):
                raw_intent = False
    success = all(
        (
            intent_ok,
            status_ok,
            set(case.tools).issubset(selected),
            parameters_ok,
            answer_ok,
            constraint_pass is not False,
            retrieval_hit is not False,
        )
    )
    return {
        "intent_correct": intent_ok,
        "raw_model_intent_correct": raw_intent,
        "status_correct": status_ok,
        "tool_selection_correct": tool_selection,
        "tool_arguments_correct": args_ok,
        "retrieval_hit": retrieval_hit,
        "constraint_pass": constraint_pass,
        "answer_correct": answer_ok,
        "end_to_end_success": success,
        "actual_tools": sorted(selected),
        "expected_tools": sorted(case.tools),
    }


def run_evaluation(dataset, mode, output, *, model_factory=None):
    metadata = source_metadata()
    cases = load_cases(dataset)
    rows = []
    with tempfile.TemporaryDirectory(prefix="supplychain-v2-eval-") as directory:
        root = Path(directory)
        business = BusinessStore(root / "business.sqlite3")
        seed_policies(business)
        retriever = PolicyRetriever(business.policies())
        traces = TraceStore(root / "traces.sqlite3")
        for case in cases:

            def fault_tool(name, arguments, ctx, fault=case.fault):
                if fault == "inventory_unavailable" and name == "inventory_query":
                    raise ToolError("business_database_unavailable", retryable=True)
                return execute(name, arguments, ctx)

            kwargs = {"model_factory": model_factory} if model_factory else {}
            agent = Agent(business, retriever, traces, tool_executor=fault_tool, **kwargs)
            response = agent.run(Request(message=case.message, mode=mode))
            scored = score(case, response, business.snapshot())
            rows.append(
                {
                    "case": case.model_dump(),
                    "score": scored,
                    "response": response.model_dump(),
                    "snapshot": business.snapshot().to_dict(),
                }
            )
            print(
                json.dumps(
                    {
                        "case": case.id,
                        "status": response.status,
                        "success": scored["end_to_end_success"],
                        "llm_calls": response.llm_calls,
                        "tokens": response.usage.total_tokens,
                        "elapsed_ms": response.elapsed_ms,
                    }
                ),
                flush=True,
            )
        metadata.update(
            retrieval=retriever.manifest(),
            source_changed_during_run=metadata["source_sha256"]
            != source_metadata()["source_sha256"],
        )
    scores = [row["score"] for row in rows]
    responses = [row["response"] for row in rows]
    metrics = {
        name: ratio([s[name] for s in scores if s[name] is not None])
        for name in (
            "intent_correct",
            "raw_model_intent_correct",
            "tool_selection_correct",
            "tool_arguments_correct",
            "retrieval_hit",
            "constraint_pass",
            "end_to_end_success",
        )
    }
    for name, intent in (("clarification_correct", "clarify"), ("refusal_correct", "reject")):
        metrics[name] = ratio(
            [
                row["score"]["intent_correct"]
                and row["score"]["status_correct"]
                and row["response"]["tool_calls"] == 0
                for row in rows
                if row["case"]["intent"] == intent
            ]
        )
    latencies = [r["elapsed_ms"] for r in responses]
    metrics.update(
        latency_ms={
            "p50": float(np.percentile(latencies, 50)),
            "p95": float(np.percentile(latencies, 95)),
            "total": sum(latencies),
        },
        llm_calls=sum(r["llm_calls"] for r in responses),
        http_attempts=sum(r["http_attempts"] for r in responses),
        known_usage_tokens={
            key: sum(r["usage"][key] for r in responses)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        all_usage_known=all(r["usage_known"] for r in responses),
        estimated_model_cost=None,
        cost_note="No versioned provider/cache-aware price table was supplied; no cost invented.",
    )
    result = {
        "kind": "deterministic_demo" if mode == "demo" else "live_llm",
        "mode": mode,
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset),
        "dataset_sha256": hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
        "metadata": metadata,
        "metrics": metrics,
        "cases": rows,
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def run_retrieval(dataset, output):
    with tempfile.TemporaryDirectory(prefix="supplychain-v2-rag-") as directory:
        store = BusinessStore(Path(directory) / "business.sqlite3")
        seed_policies(store)
        retriever = PolicyRetriever(store.policies())
        rows = []
        for case in load_cases(dataset, RetrievalCase):
            result = retriever.search(case.query, 3)
            found = list(
                dict.fromkeys(hit["citation"]["id"].split(":")[0] for hit in result["hits"])
            )
            expected = set(case.relevant_documents)
            relevant_ranks = [i + 1 for i, doc in enumerate(found) if doc in expected]
            rows.append(
                {
                    "case": case.model_dump(),
                    "retrieval": result,
                    "hit_at_1": bool(found and found[0] in expected),
                    "hit_at_3": bool(set(found) & expected),
                    "recall_at_3": len(set(found) & expected) / len(expected),
                    "reciprocal_rank_at_3": 1 / min(relevant_ranks) if relevant_ranks else 0,
                }
            )
        result = {
            "kind": "independent_retrieval",
            "dataset_sha256": hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
            "metadata": source_metadata(),
            "manifest": retriever.manifest(),
            "cases": rows,
            "metrics": {
                "hit_at_1": ratio([r["hit_at_1"] for r in rows]),
                "hit_at_3": ratio([r["hit_at_3"] for r in rows]),
                "recall_at_3": float(np.mean([r["recall_at_3"] for r in rows])),
                "mrr_at_3": float(np.mean([r["reciprocal_rank_at_3"] for r in rows])),
            },
        }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["demo", "llm", "retrieval"], default="demo")
    args = parser.parse_args()
    if args.mode == "retrieval":
        run_retrieval(args.dataset, args.output)
    else:
        run_evaluation(args.dataset, args.mode, args.output)


if __name__ == "__main__":
    main()
