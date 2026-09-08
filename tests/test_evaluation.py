"""Metric accounting tests use fake parsers; they do not tune on test prompts."""

import hashlib
import json

import pytest

from supplychain_agent.evaluation import (
    DEFAULT_CASES_PATH,
    FROZEN_CASES_SHA256,
    FROZEN_TEST_LINES_SHA256,
    ORIGINAL_FROZEN_CASES_SHA256,
    canonical_parameters,
    load_cases,
    run_evaluation,
)
from supplychain_agent.schemas import (
    OptimizationResult,
    ParsedIntent,
    PlanParameters,
    TokenUsage,
    ValidationReport,
)


def write_cases(tmp_path, cases):
    target = tmp_path / "cases.jsonl"
    target.write_text(
        "\n".join(
            json.dumps({"id": f"case-{i}", "split": "dev", "category": "metric-test", **case})
            for i, case in enumerate(cases)
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def optimal_solver(scenario, parameters):
    return OptimizationResult(
        status="optimal", message="fake for metric testing", budget=scenario.budget
    )


def valid_validator(scenario, parameters, orders):
    return ValidationReport(valid=True, checks=1)


def evaluate(tmp_path, cases, parser, **kwargs):
    return run_evaluation(
        cases_path=write_cases(tmp_path, cases),
        output_dir=tmp_path / "output",
        parser=parser,
        solver=kwargs.pop("solver", optimal_solver),
        validator=kwargs.pop("validator", valid_validator),
        **kwargs,
    )


def test_dataset_frozen_before_first_run():
    assert hashlib.sha256(DEFAULT_CASES_PATH.read_bytes()).hexdigest() == FROZEN_CASES_SHA256
    cases = load_cases()
    assert len(cases) == 36
    assert sum(case.split == "dev" for case in cases) == 24
    assert sum(case.split == "test" for case in cases) == 12
    assert all(
        case.expected_solution_status is not None
        for case in cases
        if case.expected_action == "optimize"
    )
    original = DEFAULT_CASES_PATH.with_name("cases.jsonl").read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_FROZEN_CASES_SHA256
    for content in [original, DEFAULT_CASES_PATH.read_bytes()]:
        test_lines = b"".join(
            line
            for line in content.splitlines(keepends=True)
            if json.loads(line)["split"] == "test"
        )
        assert hashlib.sha256(test_lines).hexdigest() == FROZEN_TEST_LINES_SHA256


def test_parameter_comparison_checks_defaults_but_ignores_order():
    one = PlanParameters(protected_skus=["MOTOR", "SENSOR"])
    two = PlanParameters(protected_skus=["SENSOR", "MOTOR"])
    assert canonical_parameters(one) == canonical_parameters(two)
    two.horizon_days = 14
    assert canonical_parameters(one) != canonical_parameters(two)


def test_parse_errors_are_visible_with_separate_denominators(tmp_path):
    cases = [
        {"message": "provider-error", "expected_action": "clarify"},
        {"message": "success", "expected_action": "clarify"},
    ]

    def parser(message, scenario):
        if message == "provider-error":
            raise TimeoutError("simulated timeout; no provider called")
        return ParsedIntent(action="clarify"), TokenUsage(
            prompt_tokens=20, completion_tokens=3, total_tokens=23
        )

    summary = evaluate(tmp_path, cases, parser, mode="llm")
    metrics = summary["metrics"]
    assert metrics["parse_error_count"] == 1
    assert metrics["action_accuracy_on_parsed"] == {"numerator": 1, "denominator": 1, "rate": 1}
    assert metrics["end_to_end_action_success"]["rate"] == 0.5
    assert metrics["known_token_usage_cases"] == 1
    assert metrics["unknown_token_usage_cases"] == 1
    assert metrics["tokens"]["total_tokens"] == 23
    assert metrics["safe_execution"]["rate"] is None
    assert summary["metadata"]["parser_source"] == "injected"
    assert len(summary["metadata"]["source_sha256"]) == 64
    assert "src/supplychain_agent/evaluation.py" in summary["metadata"]["source_file_sha256"]
    assert summary["metadata"]["source_changed_during_run"] is False
    saved = json.loads((tmp_path / "output" / "report.json").read_text())
    assert saved["cases"][0]["error"]["type"] == "TimeoutError"
    assert "调用失败" in (tmp_path / "output" / "report.md").read_text()


def test_false_execution_is_unsafe_even_when_plan_is_feasible(tmp_path):
    summary = evaluate(
        tmp_path,
        [{"message": "ambiguous", "expected_action": "clarify"}],
        lambda message, scenario: ParsedIntent(action="optimize"),
    )
    metrics = summary["metrics"]
    assert metrics["false_execution"]["numerator"] == 1
    assert metrics["unsafe_execution_count"] == 1
    assert metrics["safe_execution"]["rate"] == 0
    assert metrics["plan_validation"]["rate"] == 1
    assert metrics["safe_returned_plan"]["rate"] == 0


def test_extra_parameter_change_fails_strict_match(tmp_path):
    summary = evaluate(
        tmp_path,
        [
            {
                "message": "budget only",
                "expected_action": "optimize",
                "expected_parameters": {"budget": 9000},
            }
        ],
        lambda message, scenario: ParsedIntent(
            action="optimize", parameters=PlanParameters(budget=9000, horizon_days=14)
        ),
    )
    metrics = summary["metrics"]
    assert metrics["action_accuracy_on_parsed"]["rate"] == 1
    assert metrics["strict_intent_accuracy_on_parsed"]["rate"] == 0
    assert metrics["unsafe_execution_count"] == 1
    assert metrics["false_execution"]["numerator"] == 0


def test_valid_infeasible_response_safe_but_not_a_validated_plan(tmp_path):
    summary = evaluate(
        tmp_path,
        [
            {
                "message": "infeasible",
                "expected_action": "optimize",
                "expected_solution_status": "infeasible",
            }
        ],
        lambda message, scenario: ParsedIntent(action="optimize"),
        solver=lambda scenario, parameters: OptimizationResult(
            status="infeasible", message="fake", budget=0
        ),
    )
    metrics = summary["metrics"]
    assert metrics["safe_execution"]["rate"] == 1
    assert metrics["returned_plan_count"] == 0
    assert metrics["plan_validation"]["denominator"] == 0
    assert metrics["solution_status_accuracy"]["rate"] == 1


@pytest.mark.parametrize("raises", [False, True])
def test_solver_errors_count_separately(tmp_path, raises):
    def solver(scenario, parameters):
        if raises:
            raise RuntimeError("simulated solver failure")
        return OptimizationResult(status="error", message="simulated error status", budget=0)

    summary = evaluate(
        tmp_path,
        [
            {
                "message": "solve",
                "expected_action": "optimize",
                "expected_solution_status": "optimal",
            }
        ],
        lambda message, scenario: ParsedIntent(action="optimize"),
        solver=solver,
    )
    metrics = summary["metrics"]
    assert metrics["execution_attempt_count"] == 1
    assert metrics["execution_error_count"] == 1
    assert metrics["safe_execution"]["denominator"] == 0
    assert metrics["solution_status_accuracy"]["rate"] == 0


def test_failed_independent_validator_marks_execution_unsafe(tmp_path):
    summary = evaluate(
        tmp_path,
        [{"message": "solve", "expected_action": "optimize"}],
        lambda message, scenario: ParsedIntent(action="optimize"),
        validator=lambda scenario, parameters, orders: ValidationReport(
            valid=False, checks=1, violations=["fake invalid quantity"]
        ),
    )
    assert summary["metrics"]["plan_validation"]["rate"] == 0
    assert summary["metrics"]["unsafe_execution_count"] == 1


def test_first_report_cannot_be_overwritten(tmp_path):
    cases = [{"message": "clarify", "expected_action": "clarify"}]
    parser = lambda message, scenario: ParsedIntent(action="clarify")
    evaluate(tmp_path, cases, parser)
    with pytest.raises(FileExistsError):
        evaluate(tmp_path, cases, parser)


def test_provider_error_does_not_expose_environment_secret(tmp_path, monkeypatch):
    secret = "test-secret-never-send"
    monkeypatch.setenv("EXAMPLE_API_KEY", secret)

    def parser(message, scenario):
        raise RuntimeError(f"fake error with {secret}")

    evaluate(tmp_path, [{"message": "error", "expected_action": "clarify"}], parser, mode="llm")
    report = (tmp_path / "output" / "report.json").read_text()
    assert secret not in report
    assert "[REDACTED]" in report


def test_local_guard_is_not_credited_as_model_inference(tmp_path):
    stats = {}

    def parser(message, scenario):
        stats.clear()
        if message == "guard":
            stats.update(provider_calls=0, http_attempts=0, guarded=True)
            return ParsedIntent(action="reject"), TokenUsage()
        if message == "provider-failed":
            stats.update(provider_calls=1, http_attempts=3, guarded=False)
            raise TimeoutError("simulated retries, no network used")
        stats.update(provider_calls=1, http_attempts=1, guarded=False)
        # Explicit telemetry proves a provider invocation even with zero reported usage.
        return ParsedIntent(action="clarify"), TokenUsage()

    summary = evaluate(
        tmp_path,
        [
            {"message": "guard", "expected_action": "reject"},
            {"message": "provider-wrong", "expected_action": "optimize"},
            {"message": "provider-failed", "expected_action": "optimize"},
        ],
        parser,
        mode="llm",
        telemetry_reader=lambda: stats,
    )
    metrics = summary["metrics"]
    assert metrics["action_accuracy_on_parsed"]["rate"] == 0.5
    assert metrics["provider_call_count"] == 2
    assert metrics["provider_http_attempt_count"] == 4
    assert metrics["provider_backed_case_count"] == 2
    assert metrics["provider_backed_parse_error_count"] == 1
    assert metrics["provider_backed_action_accuracy_on_parsed"] == {
        "numerator": 0,
        "denominator": 1,
        "rate": 0,
    }
    assert metrics["provider_backed_end_to_end_strict_intent_success"]["denominator"] == 2
    assert metrics["local_guarded_count"] == 1
    assert metrics["local_guarded_action_accuracy"]["rate"] == 1
    assert metrics["provider_call_attribution_unknown_cases"] == 0


def test_zero_tokens_without_telemetry_cannot_prove_local_guard(tmp_path):
    summary = evaluate(
        tmp_path,
        [{"message": "unknown", "expected_action": "reject"}],
        lambda message, scenario: (ParsedIntent(action="reject"), TokenUsage()),
        mode="llm",
    )
    metrics = summary["metrics"]
    assert metrics["provider_call_attribution_unknown_cases"] == 1
    assert metrics["local_guarded_count"] == 0
    assert metrics["provider_backed_action_accuracy_on_parsed"]["rate"] is None


def test_inconsistent_telemetry_is_unknown_not_zero(tmp_path):
    summary = evaluate(
        tmp_path,
        [{"message": "unknown", "expected_action": "reject"}],
        lambda message, scenario: (ParsedIntent(action="reject"), TokenUsage()),
        mode="llm",
        telemetry_reader=lambda: {"provider_calls": 1, "http_attempts": 1, "guarded": True},
    )
    assert summary["metrics"]["provider_call_attribution_unknown_cases"] == 1
