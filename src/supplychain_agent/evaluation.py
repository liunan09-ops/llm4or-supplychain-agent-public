"""Reproducible, explicitly synthetic intent and execution regression evaluation.

The JSON report preserves every case, including provider and solver failures.
An injected parser is useful for testing the metric implementation, and is labelled
as injected in the manifest rather than presented as a model measurement.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import statistics
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from .data import get_scenario
from .schemas import (
    OptimizationResult,
    ParsedIntent,
    PlanParameters,
    Scenario,
    StrictModel,
    TokenUsage,
    ValidationReport,
)

PROTOCOL_VERSION = "1.1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_CASES_PATH = Path.cwd() / "evals" / "cases-v1.1.jsonl"
DEFAULT_CASES_PATH = (
    _WORKSPACE_CASES_PATH
    if _WORKSPACE_CASES_PATH.is_file()
    else PROJECT_ROOT / "evals" / "cases-v1.1.jsonl"
)
FROZEN_CASES_SHA256 = "958643ed048dc3c7446f287748f88ac7a6e39adc33ad3b11eedab7c8a5a420fe"
ORIGINAL_FROZEN_CASES_SHA256 = "86226f45072f30acd5d173798429110acc9cdf9772b55905204be90350bff1ab"
FROZEN_TEST_LINES_SHA256 = "2cb105643bee2f2d8e82d5c4b5ed233b9ded5c5d2595cc54f7fbd9f9f85edf4a"


class EvaluationCase(StrictModel):
    id: str = Field(min_length=1)
    split: Literal["dev", "test"]
    category: str = Field(min_length=1)
    message: str = Field(min_length=1)
    scenario_id: str = "factory-demo"
    expected_action: Literal["optimize", "clarify", "reject"]
    expected_parameters: PlanParameters = Field(default_factory=PlanParameters)
    expected_solution_status: Literal["optimal", "feasible", "infeasible", "error"] | None = None


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[EvaluationCase]:
    cases = [
        EvaluationCase.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Evaluation case IDs must be unique")
    return cases


def canonical_parameters(parameters: PlanParameters) -> dict:
    """Compare all fields, including defaults, while ignoring list order only."""
    value = parameters.model_dump(mode="json")
    value["protected_skus"] = sorted(set(value["protected_skus"]))
    value["excluded_skus"] = sorted(set(value["excluded_skus"]))
    value["demand_updates"] = sorted(value["demand_updates"], key=lambda item: item["sku_id"])
    return value


def _ratio(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def _latency(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None}
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean_ms": round(statistics.mean(values), 3),
        "p50_ms": round(statistics.median(values), 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
    }


def summarize_results(rows: list[dict]) -> dict:
    """Compute metrics with explicit denominators and no credit for call errors."""
    parsed = [row for row in rows if row.get("parse_status") == "ok"]
    invoked = [row for row in rows if row.get("execution_attempted")]
    completed = [row for row in invoked if row.get("execution_status") == "completed"]
    plans = [row for row in completed if row.get("solution_status") in {"optimal", "feasible"}]
    status_cases = [row for row in rows if row.get("expected_solution_status") is not None]
    usage_rows = [row["usage"] for row in rows if row.get("usage") is not None]
    provider_rows = [row for row in rows if (row.get("provider_call_count") or 0) > 0]
    provider_parsed = [row for row in provider_rows if row.get("parse_status") == "ok"]
    guarded = [row for row in rows if row.get("local_guarded") is True]
    guarded_parsed = [row for row in guarded if row.get("parse_status") == "ok"]
    action_correct = sum(bool(row.get("action_match")) for row in parsed)
    intent_correct = sum(bool(row.get("strict_intent_match")) for row in parsed)
    safe_completed = sum(bool(row.get("safe_execution")) for row in completed)
    unsafe_completed = len(completed) - safe_completed
    return {
        "total_cases": len(rows),
        "parsed_cases": len(parsed),
        "parse_error_count": len(rows) - len(parsed),
        "parse_error_ids": [row["id"] for row in rows if row.get("parse_status") != "ok"],
        "action_accuracy_on_parsed": _ratio(action_correct, len(parsed)),
        "strict_intent_accuracy_on_parsed": _ratio(intent_correct, len(parsed)),
        "end_to_end_action_success": _ratio(action_correct, len(rows)),
        "end_to_end_strict_intent_success": _ratio(intent_correct, len(rows)),
        "provider_call_count": sum(row.get("provider_call_count") or 0 for row in rows),
        "provider_http_attempt_count": sum(
            row.get("provider_http_attempt_count") or 0 for row in rows
        ),
        "provider_call_attribution_unknown_cases": sum(
            row.get("provider_call_count") is None for row in rows
        ),
        "provider_backed_case_count": len(provider_rows),
        "provider_backed_parse_error_count": len(provider_rows) - len(provider_parsed),
        "provider_backed_action_accuracy_on_parsed": _ratio(
            sum(bool(row.get("action_match")) for row in provider_parsed), len(provider_parsed)
        ),
        "provider_backed_strict_intent_accuracy_on_parsed": _ratio(
            sum(bool(row.get("strict_intent_match")) for row in provider_parsed),
            len(provider_parsed),
        ),
        "provider_backed_end_to_end_strict_intent_success": _ratio(
            sum(bool(row.get("strict_intent_match")) for row in provider_parsed), len(provider_rows)
        ),
        "local_guarded_count": len(guarded),
        "local_guarded_action_accuracy": _ratio(
            sum(bool(row.get("action_match")) for row in guarded_parsed), len(guarded)
        ),
        "solution_status_accuracy": _ratio(
            sum(bool(row.get("solution_status_match")) for row in status_cases), len(status_cases)
        ),
        "execution_attempt_count": len(invoked),
        "completed_execution_count": len(completed),
        "execution_error_count": len(invoked) - len(completed),
        "false_execution": _ratio(
            sum(bool(row.get("false_execution")) for row in invoked), len(invoked)
        ),
        "safe_execution": _ratio(safe_completed, len(completed)),
        "unsafe_execution_count": unsafe_completed,
        "unsafe_execution_ids": [row["id"] for row in completed if not row.get("safe_execution")],
        "returned_plan_count": len(plans),
        "plan_validation": _ratio(
            sum(row.get("validation_valid") is True for row in plans), len(plans)
        ),
        "safe_returned_plan": _ratio(
            sum(bool(row.get("safe_execution")) for row in plans), len(plans)
        ),
        "known_token_usage_cases": len(usage_rows),
        "unknown_token_usage_cases": len(rows) - len(usage_rows),
        "tokens": {
            key: sum(usage.get(key, 0) for usage in usage_rows)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "parse_latency": _latency([row["parse_ms"] for row in rows]),
        "successful_parse_latency": _latency([row["parse_ms"] for row in parsed]),
        "execution_latency": _latency([row["execution_ms"] for row in invoked]),
        "total_latency": _latency([row["elapsed_ms"] for row in rows]),
        "categories": dict(sorted(Counter(row["category"] for row in rows).items())),
    }


def _parse_attribution(mode: str, setup_error: Exception | None, stats: dict | None) -> dict:
    """Use explicit client telemetry; never infer an API call from token counts."""
    if mode == "rules" or setup_error is not None:
        return {
            "provider_call_count": 0,
            "provider_http_attempt_count": 0,
            "local_guarded": False,
            "parse_origin": "rules" if mode == "rules" else "setup_error",
        }
    if isinstance(stats, dict):
        calls, attempts, guarded = (
            stats.get("provider_calls"),
            stats.get("http_attempts"),
            stats.get("guarded"),
        )
        if (
            isinstance(calls, int)
            and not isinstance(calls, bool)
            and calls >= 0
            and isinstance(attempts, int)
            and not isinstance(attempts, bool)
            and attempts >= 0
            and isinstance(guarded, bool)
            and not (guarded and (calls or attempts))
        ):
            return {
                "provider_call_count": calls,
                "provider_http_attempt_count": attempts,
                "local_guarded": guarded,
                "parse_origin": "local_guard" if guarded else ("provider" if calls else "local"),
            }
    return {
        "provider_call_count": None,
        "provider_http_attempt_count": None,
        "local_guarded": None,
        "parse_origin": "unknown",
    }


def _safe_error(error: Exception) -> dict:
    message = str(error)
    for key, value in os.environ.items():
        if (
            value
            and len(value) >= 6
            and any(part in key.upper() for part in ("KEY", "TOKEN", "SECRET"))
        ):
            message = message.replace(value, "[REDACTED]")
    return {"type": type(error).__name__, "message": message[:1000]}


def _git_metadata() -> dict:
    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            )
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    status = run("status", "--porcelain", "--", str(PROJECT_ROOT))
    return {
        "commit": run("rev-parse", "HEAD"),
        "worktree_dirty": None if status is None else bool(status),
    }


def _source_metadata() -> dict:
    """Hash source bytes and relative paths even when Git points at a parent repo."""
    digest = hashlib.sha256()
    file_hashes = {}
    source_root = Path(__file__).resolve().parent
    for path in sorted(source_root.rglob("*.py")):
        relative_path = "src/supplychain_agent/" + path.relative_to(source_root).as_posix()
        encoded_path = relative_path.encode("utf-8")
        content = path.read_bytes()
        # Length prefixes make path/content boundaries unambiguous.
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        file_hashes[relative_path] = hashlib.sha256(content).hexdigest()
    return {"source_sha256": digest.hexdigest(), "source_file_sha256": file_hashes}


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _percent(metric: dict) -> str:
    rate = metric["rate"]
    value = "N/A" if rate is None else f"{rate:.1%}"
    return f"{value} ({metric['numerator']}/{metric['denominator']})"


def _markdown_report(report: dict) -> str:
    metadata, metrics = report["metadata"], report["metrics"]
    lines = [
        "# 供应链决策助手 · 工程回归评测",
        "",
        "> 数据和业务成本均为合成示例。本集合不是公开基准；小样本结果不代表独立泛化能力或真实企业收益。",
        "",
        f"- 时间（UTC）：{metadata['started_at']}",
        f"- 模式 / 模型：{metadata['mode']} / {metadata['model'] or '无模型调用'}",
        f"- 解析器来源：{metadata['parser_source']}",
        f"- 集合：{metadata['split']}，{metrics['total_cases']} 条；标签：{metadata['run_label'] or '未提供'}",
        f"- 协议版本：{metadata['protocol_version']}；代码版本：{metadata['package_version']}",
        f"- Git：{metadata['git']['commit']}；工作区有修改：{metadata['git']['worktree_dirty']}",
        f"- 源码 SHA-256：`{metadata['source_sha256']}`；运行期间源码变化：{metadata['source_changed_during_run']}",
        f"- 用例文件 SHA-256：`{metadata['cases_sha256']}`",
        f"- 原始冻结集一致：{metadata['matches_frozen_cases']}",
        "",
        "## 指标与分母",
        "",
        "| 指标 | 实测值 |",
        "| --- | --- |",
        f"| 系统动作正确率（成功解析） | {_percent(metrics['action_accuracy_on_parsed'])} |",
        f"| 系统严格意图正确率（成功解析，全部参数） | {_percent(metrics['strict_intent_accuracy_on_parsed'])} |",
        f"| 有模型请求的系统动作正确率（成功解析） | {_percent(metrics['provider_backed_action_accuracy_on_parsed'])} |",
        f"| 有模型请求的系统严格意图正确率（成功解析） | {_percent(metrics['provider_backed_strict_intent_accuracy_on_parsed'])} |",
        f"| 有模型请求的端到端严格意图成功率（含请求失败） | {_percent(metrics['provider_backed_end_to_end_strict_intent_success'])} |",
        f"| 本地守卫动作正确率 | {_percent(metrics['local_guarded_action_accuracy'])} |",
        f"| 端到端动作成功率（全部用例） | {_percent(metrics['end_to_end_action_success'])} |",
        f"| 端到端严格意图成功率（全部用例） | {_percent(metrics['end_to_end_strict_intent_success'])} |",
        f"| 求解状态符合预期（要求状态的全部用例） | {_percent(metrics['solution_status_accuracy'])} |",
        f"| 误触发求解（本应澄清/拒绝，除以求解尝试数） | {_percent(metrics['false_execution'])} |",
        f"| 安全执行（除以正常完成的求解调用） | {_percent(metrics['safe_execution'])} |",
        f"| 不安全执行数 | {metrics['unsafe_execution_count']} |",
        f"| 方案可行性校验（仅已返回可行方案） | {_percent(metrics['plan_validation'])} |",
        f"| 语义正确且可行（仅已返回可行方案） | {_percent(metrics['safe_returned_plan'])} |",
        "",
        f"解析/API 错误：{metrics['parse_error_count']}；求解调用错误：{metrics['execution_error_count']}。",
        f"供应商逻辑调用 {metrics['provider_call_count']} 次，HTTP 请求尝试 {metrics['provider_http_attempt_count']} 次（含重试）；本地守卫处理 {metrics['local_guarded_count']} 条；调用归因未知 {metrics['provider_call_attribution_unknown_cases']} 条。",
        f"实际请求供应商的用例 {metrics['provider_backed_case_count']} 条，其中解析/API 错误 {metrics['provider_backed_parse_error_count']} 条。",
        "本地守卫的拒绝/澄清不计入模型请求子集；归因来自显式调用遥测，不根据零 Token 猜测。系统输出可能经过本地后置校验，不能解释为裸模型准确率。",
        "调用失败不算模型回答，不进入成功解析正确率分母；在端到端指标中计为未成功。",
        "安全执行同时要求完整意图匹配、求解正常结束，以及可行方案通过重新校验；正确报告不可行也算安全完成。",
        "此处执行仅指本地求解器调用，本项目不发送采购订单、不付款。",
        "",
        f"解析延迟：{json.dumps(metrics['parse_latency'], ensure_ascii=False)}",
        f"求解延迟：{json.dumps(metrics['execution_latency'], ensure_ascii=False)}",
        f"已知 Token 用量：{json.dumps(metrics['tokens'], ensure_ascii=False)}；",
        f"用量已知 {metrics['known_token_usage_cases']} 条，未知 {metrics['unknown_token_usage_cases']} 条。未知用量未当作 0；未估算金额。",
        "",
        "## 逐例结果",
        "",
        "| ID | 分类 | 预期动作 | 实际动作 | 严格匹配 | 求解状态 | 错误阶段 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["cases"]:
        lines.append(
            f"| {row['id']} | {row['category']} | {row['expected_action']} | "
            f"{row.get('actual_action') or '—'} | {row.get('strict_intent_match', False)} | "
            f"{row.get('solution_status') or '—'} | {row.get('error_stage') or '—'} |"
        )
    lines.extend(
        [
            "",
            "完整输入、期望参数、实际参数、校验结果、异常和耗时均保存在同目录的 `report.json`。",
            "dev 可用于开发；test 的首次运行报告应单独保留。看过 test 失败后进行修改的结果须另标后续回归，不能继续称为未见测试。",
            "",
        ]
    )
    return "\n".join(lines)


def run_evaluation(
    mode: Literal["rules", "llm"] = "rules",
    split: Literal["dev", "test", "all"] = "dev",
    limit: int | None = None,
    output_dir: Path = Path("reports/evaluation"),
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    parser: Callable | None = None,
    solver: Callable | None = None,
    validator: Callable | None = None,
    model_client=None,
    telemetry_reader: Callable | None = None,
    run_label: str | None = None,
) -> dict:
    """Run serially, write auditable JSON/Markdown, and return a compact summary.

    Supplying ``parser``/``solver``/``validator`` is intended for unit tests and is
    recorded in metadata. A model is called only for mode="llm". Runtime errors
    are recorded per case and do not terminate or disappear from the report.
    Existing report paths are never overwritten (preserving a first test run).
    """
    if mode not in {"rules", "llm"} or split not in {"dev", "test", "all"}:
        raise ValueError("Unsupported evaluation mode or split")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    output_dir = Path(output_dir)
    report_json, report_md = output_dir / "report.json", output_dir / "report.md"
    if report_json.exists() or report_md.exists():
        raise FileExistsError(f"Refusing to overwrite an evaluation: {output_dir}")
    cases_path = Path(cases_path)
    cases = [case for case in load_cases(cases_path) if split == "all" or case.split == split]
    if limit is not None:
        cases = cases[:limit]
    if not cases:
        raise ValueError("No cases selected")

    injected_parser = parser is not None
    injected_solver = solver is not None
    injected_validator = validator is not None
    setup_error: Exception | None = None
    model = None
    if parser is None:
        if mode == "rules":
            from .language import parse_rules

            parser = parse_rules
        else:
            from .language import ModelClient

            try:
                model_client = model_client or ModelClient.from_env()
                parser = model_client.parse
                model = getattr(model_client, "model", None)
            except Exception as error:  # noqa: BLE001 - preserve setup failures in evaluation reports
                setup_error = error
    elif mode == "llm" and model_client is not None:
        model = getattr(model_client, "model", None)

    if solver is None or validator is None:
        from .optimizer import solve, validate_solution

        solver = solver or solve
        validator = validator or validate_solution

    started_at = datetime.now(UTC).isoformat()
    source_before = _source_metadata()
    rows = []
    for case in cases:
        start = time.perf_counter()
        scenario: Scenario = get_scenario(case.scenario_id)
        row = {
            **case.model_dump(mode="json"),
            "parse_status": "error",
            "actual_action": None,
            "actual_parameters": None,
            "action_match": False,
            "strict_intent_match": False,
            "execution_attempted": False,
            "execution_status": "not_called",
            "false_execution": False,
            "safe_execution": None,
            "solution_status": None,
            "solution_status_match": False if case.expected_solution_status is not None else None,
            "validation_valid": None,
            "usage": None,
            "parse_ms": 0,
            "execution_ms": 0,
        }
        parse_start = time.perf_counter()
        try:
            if setup_error is not None:
                raise setup_error
            parsed = parser(case.message, scenario)
            if isinstance(parsed, tuple):
                intent, usage = parsed
                usage = TokenUsage.model_validate(usage)
                row["usage"] = usage.model_dump(mode="json")
            else:
                intent = parsed
                if mode == "rules":
                    row["usage"] = TokenUsage().model_dump(mode="json")
            intent = ParsedIntent.model_validate(intent)
            row["parse_status"] = "ok"
            row["actual_action"] = intent.action
            row["actual_parameters"] = intent.parameters.model_dump(mode="json")
            row["intent"] = intent.model_dump(mode="json")
            row["action_match"] = intent.action == case.expected_action
            row["strict_intent_match"] = row["action_match"] and (
                canonical_parameters(intent.parameters)
                == canonical_parameters(case.expected_parameters)
            )
        except Exception as error:  # noqa: BLE001 - record every parser/provider failure per case
            row["error_stage"] = "parser_setup" if setup_error else "parse"
            row["error"] = _safe_error(error)
        finally:
            row["parse_ms"] = round((time.perf_counter() - parse_start) * 1000, 3)
            stats = None
            try:
                stats = (
                    telemetry_reader()
                    if telemetry_reader is not None
                    else getattr(model_client, "last_parse_stats", None)
                )
            except Exception as error:  # noqa: BLE001 - missing telemetry is unknown, never zero
                row["telemetry_error"] = _safe_error(error)
            row.update(_parse_attribution(mode, setup_error, stats))

        if row["parse_status"] == "ok" and intent.action == "optimize":
            row["execution_attempted"] = True
            row["false_execution"] = case.expected_action != "optimize"
            execution_start = time.perf_counter()
            try:
                result = OptimizationResult.model_validate(solver(scenario, intent.parameters))
                row["result"] = result.model_dump(mode="json")
                row["solution_status"] = result.status
                if case.expected_solution_status is not None:
                    row["solution_status_match"] = result.status == case.expected_solution_status
                if result.status == "error":
                    row["execution_status"] = "error"
                    row["error_stage"] = "solve"
                    row["error"] = {"type": "SolverErrorResult", "message": result.message}
                else:
                    row["execution_status"] = "completed"
                    if result.status in {"optimal", "feasible"}:
                        validation = ValidationReport.model_validate(
                            validator(scenario, intent.parameters, result.orders)
                        )
                        row["independent_validation"] = validation.model_dump(mode="json")
                        row["validation_valid"] = validation.valid
                    row["safe_execution"] = row["strict_intent_match"] and (
                        result.status == "infeasible" or row["validation_valid"] is True
                    )
            except Exception as error:  # noqa: BLE001 - a failed tool must remain visible in the report
                row["execution_status"] = "error"
                row["error_stage"] = "solve_or_validate"
                row["error"] = _safe_error(error)
            finally:
                row["execution_ms"] = round((time.perf_counter() - execution_start) * 1000, 3)
        row["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)
        rows.append(row)

    cases_sha256 = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    source_after = _source_metadata()
    metadata = {
        "protocol_version": PROTOCOL_VERSION,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "model": model,
        "split": split,
        "limit": limit,
        "run_label": run_label,
        "parser_source": "injected" if injected_parser else "production",
        "solver_source": "injected" if injected_solver else "production",
        "validator_source": "injected" if injected_validator else "production",
        "provenance": "synthetic engineering regression set; not a public benchmark",
        "cases_path": str(cases_path.resolve()),
        "cases_sha256": cases_sha256,
        "matches_frozen_cases": cases_sha256 == FROZEN_CASES_SHA256,
        "selected_case_ids": [case.id for case in cases],
        "selected_cases_sha256": hashlib.sha256(
            json.dumps([case.model_dump(mode="json") for case in cases], sort_keys=True).encode()
        ).hexdigest(),
        "git": _git_metadata(),
        **source_before,
        "source_changed_during_run": source_before != source_after,
        "source_sha256_after_run": source_after["source_sha256"],
        "package_version": _package_version("supplychain-decision-agent"),
        "python_version": platform.python_version(),
        "dependency_versions": {
            name: _package_version(name) for name in ("scipy", "numpy", "pydantic", "httpx")
        },
        "scenario": get_scenario("factory-demo").model_dump(mode="json"),
    }
    metrics = summarize_results(rows)
    report = {"metadata": metadata, "metrics": metrics, "cases": rows}
    output_dir.mkdir(parents=True, exist_ok=True)
    report_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_md.write_text(_markdown_report(report), encoding="utf-8")
    return {
        "metadata": metadata,
        "metrics": metrics,
        "reports": {"json": str(report_json.resolve()), "markdown": str(report_md.resolve())},
    }
