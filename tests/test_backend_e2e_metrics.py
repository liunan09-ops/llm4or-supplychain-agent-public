"""Check comparison denominators and separate retrieval from answer selection failures."""

import importlib.util
from pathlib import Path

from supplychain_agent.v2.contracts import Response
from supplychain_agent.v2.evaluation import Case

spec = importlib.util.spec_from_file_location(
    "backend_e2e", Path(__file__).resolve().parents[1] / "scripts/evaluate_retrieval_backends.py"
)
backend_e2e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend_e2e)


def scores(**overrides):
    return {
        **dict.fromkeys(
            (
                "end_to_end_success",
                "intent_correct",
                "raw_model_intent_correct",
                "tool_selection_correct",
                "tool_arguments_correct",
                "status_correct",
                "answer_correct",
            ),
            True,
        ),
        "retrieval_hit": None,
        "constraint_pass": None,
        **overrides,
    }


def test_comparison_keeps_infeasibility_and_validator_denominators_distinct():
    rows = []
    for intent, solver_status in (
        ("optimize", "optimal"),
        ("optimize", "infeasible"),
        ("reject", None),
    ):
        events = []
        if solver_status:
            events.append(
                {
                    "kind": "tool",
                    "name": "replenishment_optimizer",
                    "status": "ok",
                    "data": {"result": {"status": solver_status}},
                }
            )
        if solver_status == "optimal":
            events.append(
                {
                    "kind": "tool",
                    "name": "solution_validator",
                    "status": "ok",
                    "data": {"result": {"validation": {"valid": True}}},
                }
            )
        rows.append(
            {
                "case": {"intent": intent},
                "score": scores(constraint_pass=True if solver_status == "optimal" else None),
                "diagnostics": [],
                "response": {
                    "trace": events,
                    "tool_calls": len(events),
                    "llm_calls": 0,
                    "http_attempts": 0,
                    "elapsed_ms": 10,
                    "usage_known": True,
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                },
            }
        )
    result = backend_e2e.summarize(rows)
    assert result["end_to_end_success"] == {"passed": 3, "total": 3, "rate": 1}
    assert result["optimization_feasibility"] == {"passed": 1, "total": 2, "rate": 0.5}
    assert (
        result["validator_pass_rate"]
        == result["constraint_pass"]
        == {"passed": 1, "total": 1, "rate": 1}
    )
    assert result["retrieval_hit"]["total"] == 0
    assert result["retrieval_hit"]["rate"] is None
    assert result["refusal_correct"]["passed"] == 1
    assert not result["failures"]


def test_diagnostics_do_not_blame_retriever_for_missing_final_evidence():
    case = Case(
        id="unit",
        message="policy question",
        intent="policy",
        status="completed",
        tools=["policy_retrieval"],
        category="unit",
    )
    response = Response(
        request_id="unit", mode="llm", status="llm_failure", explanation="missing required evidence"
    )
    result = backend_e2e.diagnose(
        case, response, scores(end_to_end_success=False, answer_correct=False, retrieval_hit=True)
    )
    assert "llm_generation_failure" in result and "evidence_selection_failure" in result
    assert "retrieval_failure" not in result
    result = backend_e2e.diagnose(
        case, response, scores(end_to_end_success=False, answer_correct=False, retrieval_hit=False)
    )
    assert "retrieval_failure" in result and "evidence_selection_failure" not in result
