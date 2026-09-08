"""Real DeepSeek E2E comparison; frozen cases/scoring and balanced backend order."""

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from supplychain_agent.language import ModelError
from supplychain_agent.v2.agent import Agent
from supplychain_agent.v2.contracts import Request
from supplychain_agent.v2.database import BusinessStore
from supplychain_agent.v2.embeddings import file_sha256
from supplychain_agent.v2.evaluation import load_cases, ratio, score, source_metadata
from supplychain_agent.v2.model import V2ModelClient
from supplychain_agent.v2.retrieval import seed_policies
from supplychain_agent.v2.semantic_evaluation import write_record
from supplychain_agent.v2.semantic_retrieval import create_retriever
from supplychain_agent.v2.tools import ToolError, execute
from supplychain_agent.v2.trace import TraceStore

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = ("lexical", "hybrid", "semantic")


def diagnose(case, response, scored):
    """Independent, non-exclusive diagnostics; never alter the Core success score."""
    labels = []
    if not scored["intent_correct"]:
        labels.append("routing_failure")
    if not scored["tool_selection_correct"]:
        labels.append("tool_selection_failure")
    if not scored["tool_arguments_correct"]:
        labels.append("argument_extraction_or_tool_argument_failure")
    if scored["retrieval_hit"] is False:
        labels.append("retrieval_failure")
    if response.status == "llm_failure":
        labels.append("llm_generation_failure")
    if not scored["answer_correct"] and scored["retrieval_hit"] is True:
        labels.append("evidence_selection_failure")
    if response.status == "validator_failure" or scored["constraint_pass"] is False:
        labels.append("validator_failure")
    if response.status == "limit_exceeded":
        labels.append("execution_limit")
    if response.result is not None and response.result.status == "infeasible":
        labels.append(
            "expected_solver_infeasible"
            if case.status == "infeasible"
            else "unexpected_solver_infeasible"
        )
    if scored["end_to_end_success"] and case.intent in {"clarify", "reject"}:
        labels.append("expected_clarification" if case.intent == "clarify" else "expected_refusal")
    if case.fault and scored["end_to_end_success"]:
        labels.append("expected_injected_tool_failure")
    if not scored["end_to_end_success"] and not labels:
        labels.append("status_or_execution_failure")
    return labels


def summarize(rows):
    scores = [r["score"] for r in rows]
    responses = [r["response"] for r in rows]
    result = {
        key: ratio([s[key] for s in scores if s[key] is not None])
        for key in (
            "end_to_end_success",
            "intent_correct",
            "raw_model_intent_correct",
            "tool_selection_correct",
            "tool_arguments_correct",
            "retrieval_hit",
            "constraint_pass",
        )
    }
    for key, intent in (("clarification_correct", "clarify"), ("refusal_correct", "reject")):
        result[key] = ratio(
            [
                r["score"]["intent_correct"]
                and r["score"]["status_correct"]
                and r["response"]["tool_calls"] == 0
                for r in rows
                if r["case"]["intent"] == intent
            ]
        )
    tool_events = [e for r in responses for e in r["trace"] if e["kind"] == "tool"]
    optimizer = [e for e in tool_events if e["name"] == "replenishment_optimizer"]
    validators = [e for e in tool_events if e["name"] == "solution_validator"]
    result.update(
        total_requests=len(rows),
        optimizer_outcomes=dict(
            Counter(e["data"].get("result", {}).get("status", "tool_failure") for e in optimizer)
        ),
        optimization_feasibility=ratio(
            [
                e["data"].get("result", {}).get("status") in {"optimal", "feasible"}
                for e in optimizer
            ]
        ),
        validator_pass_rate=ratio(
            [
                e["status"] == "ok"
                and e["data"].get("result", {}).get("validation", {}).get("valid") is True
                for e in validators
            ]
        ),
        llm_calls=sum(r["llm_calls"] for r in responses),
        http_attempts=sum(r["http_attempts"] for r in responses),
        llm_calls_per_request={
            "p50": float(np.median([r["llm_calls"] for r in responses])),
            "max": max(r["llm_calls"] for r in responses),
        },
        latency_ms={
            "p50": float(np.percentile([r["elapsed_ms"] for r in responses], 50)),
            "p95": float(np.percentile([r["elapsed_ms"] for r in responses], 95)),
            "total": sum(r["elapsed_ms"] for r in responses),
        },
        known_usage_tokens={
            key: sum(r["usage"][key] for r in responses)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        all_usage_known=all(r["usage_known"] for r in responses),
        estimated_model_cost=None,
        cost_note="No cache-hit/miss usage breakdown and frozen provider price table in the existing client; no reliable monetary estimate.",
        diagnostic_counts=dict(Counter(label for row in rows for label in row["diagnostics"])),
        failures=[
            {
                "id": r["case"]["id"],
                "message": r["case"]["message"],
                "status": r["response"]["status"],
                "labels": r["diagnostics"],
                "reason": r["response"]["explanation"],
                "score": r["score"],
            }
            for r in rows
            if not r["score"]["end_to_end_success"]
        ],
    )
    return result


def report(record):
    lines = [
        "# 真实 DeepSeek Retrieval Backend E2E 对照",
        "",
        "同一固定 24 条合成 Agent 留出请求；不是新增盲测或生产准确率。原 Core score 函数不改。",
        "按请求轮换 lexical → hybrid → semantic 的执行起点，各自运行一次，降低固定先后顺序偏差；不消除模型随机性和服务缓存影响。",
        "",
        f"状态：{record['status']}；模型：{record.get('model', 'unavailable')}。",
        "",
    ]
    if record["status"] == "blocked":
        return "\n".join(lines + ["Blocker: " + record["blocker"], ""])
    lines += [
        "| backend | E2E | intent | tools | args | retrieval | clarify | refuse | validator | p50/p95 ms | calls | tokens |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    def ratio_text(value):
        return f"{value['passed']}/{value['total']}"

    for backend, data in record["runs"].items():
        m = data["metrics"]
        values = [
            ratio_text(m[k])
            for k in (
                "end_to_end_success",
                "intent_correct",
                "tool_selection_correct",
                "tool_arguments_correct",
                "retrieval_hit",
                "clarification_correct",
                "refusal_correct",
                "validator_pass_rate",
            )
        ]
        lines.append(
            f"| {backend} | "
            + " | ".join(values)
            + f" | {m['latency_ms']['p50']:.1f}/{m['latency_ms']['p95']:.1f} | {m['llm_calls']} | {m['known_usage_tokens']['total_tokens']} |"
        )
    lines += [
        "",
        "工具选择/参数指标按请求计，包含状态机约束；retrieval 仅对有政策相关标注的问题计分。Validator 仅对实际校验调用计分。",
        "Optimization feasibility 的分母是实际 optimizer 调用，包含预期 infeasible；预期不可行不是 Agent 失败。constraint_pass 则仅对已发布可行方案独立重验。",
        "金额估计为 null：现有客户端没有保存可靠的缓存命中/未命中用量拆分及冻结价格表；token 是 API 报告值。",
        "",
    ]
    for backend, data in record["runs"].items():
        lines += [
            f"## {backend} 失败与预期终态",
            "",
            f"Optimizer outcomes: `{data['metrics']['optimizer_outcomes']}`",
            "",
            f"诊断标签（可重叠）: `{data['metrics']['diagnostic_counts']}`",
            "",
        ]
        for failure in data["metrics"]["failures"]:
            lines += [
                f"- **{failure['id']}**：{failure['message']}；标签 `{', '.join(failure['labels'])}`。{failure['reason']}"
            ]
        if not data["metrics"]["failures"]:
            lines.append("本次无失败；仅限这 24 条合成请求。")
        lines.append("")
    lines += [
        "逐例原始请求、响应、trace、快照和评分见 [backend_e2e](backend_e2e)，路径与 SHA-256 索引见 [results](retrieval_backend_e2e_results.json)。",
        "所有失败保留；此次不根据留出结果修改任何业务规则、模型提示词或标注。",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation/backend_e2e")
    args = parser.parse_args()
    aggregate = args.output.parent / "retrieval_backend_e2e_results.json"
    markdown = args.output.parent / "retrieval_backend_e2e_report.md"
    if args.output.exists() or aggregate.exists() or markdown.exists():
        parser.error("Existing experiment preserved; choose a new output parent")
    dataset = ROOT / "evaluation/heldout_v2.jsonl"
    source = source_metadata()
    runner_sha = file_sha256(__file__)
    dataset_sha = file_sha256(dataset)
    try:
        configured = V2ModelClient.from_env()
        if not configured._official_deepseek:
            raise ModelError("Official DeepSeek endpoint required")
    except ModelError:
        record = {
            "status": "blocked",
            "blocker": "No valid official DeepSeek credentials/configuration in the existing environment",
            "dataset_sha256": dataset_sha,
        }
        write_record(aggregate, record)
        markdown.write_text(report(record))
        return
    with tempfile.TemporaryDirectory(prefix="supplychain-backend-e2e-") as directory:
        business = BusinessStore(Path(directory) / "business.sqlite3")
        seed_policies(business)
        retrievers = {name: create_retriever(business.policies(), name) for name in BACKENDS}
        freeze = {
            "created_at": datetime.now(UTC).isoformat(),
            "source": source,
            "checkpoint": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "runner_sha256": runner_sha,
            "dataset_sha256": dataset_sha,
            "model": configured.model,
            "base_url": configured.base_url,
            "temperature": 0,
            "max_tokens_per_call": 1200,
            "retrieval": {name: r.manifest() for name, r in retrievers.items()},
            "order": "case index modulo 3 rotates lexical, hybrid, semantic; one run per case/backend",
            "decision_rule": "Prefer higher E2E; ties consider retrieval quality, latency, dependency/resource readiness. No label or prompt tuning.",
        }
        write_record(args.output / "freeze.json", freeze)
        cases = load_cases(dataset)
        traces = {name: TraceStore(Path(directory) / f"{name}.sqlite3") for name in BACKENDS}
        runs = {name: [] for name in BACKENDS}
        for number, case in enumerate(cases):
            order = BACKENDS[number % 3 :] + BACKENDS[: number % 3]
            for backend in order:

                def fault_tool(name, arguments, ctx, fault=case.fault):
                    if fault == "inventory_unavailable" and name == "inventory_query":
                        raise ToolError("business_database_unavailable", retryable=True)
                    return execute(name, arguments, ctx)

                agent = Agent(
                    business, retrievers[backend], traces[backend], tool_executor=fault_tool
                )
                response = agent.run(Request(message=case.message, mode="llm"))
                scored = score(case, response, business.snapshot())
                row = {
                    "case": case.model_dump(),
                    "response": response.model_dump(),
                    "score": scored,
                    "diagnostics": diagnose(case, response, scored),
                    "snapshot": business.snapshot().to_dict(),
                }
                write_record(args.output / backend / f"{case.id}.json", row)
                runs[backend].append(row)
                print(
                    json.dumps(
                        {
                            "backend": backend,
                            "case": case.id,
                            "status": response.status,
                            "success": scored["end_to_end_success"],
                            "calls": response.llm_calls,
                            "elapsed_ms": response.elapsed_ms,
                        }
                    ),
                    flush=True,
                )
        assert source_metadata() == source and file_sha256(__file__) == runner_sha
        assert file_sha256(dataset) == dataset_sha
        record = {
            "status": "completed",
            "model": configured.model,
            "dataset_sha256": dataset_sha,
            "freeze": str((args.output / "freeze.json").relative_to(aggregate.parent)),
            "freeze_sha256": file_sha256(args.output / "freeze.json"),
            "inputs_unchanged": True,
            "runs": {},
        }
        for backend, rows in runs.items():
            record["runs"][backend] = {
                "metrics": summarize(rows),
                "cases": [
                    {
                        "id": row["case"]["id"],
                        "path": str(
                            (args.output / backend / f"{row['case']['id']}.json").relative_to(
                                aggregate.parent
                            )
                        ),
                        "sha256": file_sha256(args.output / backend / f"{row['case']['id']}.json"),
                    }
                    for row in rows
                ],
            }
        write_record(aggregate, record)
        markdown.write_text(report(record))
        print(
            json.dumps(
                {
                    name: data["metrics"]["end_to_end_success"]
                    for name, data in record["runs"].items()
                }
            )
        )


if __name__ == "__main__":
    main()
