"""A bounded Agent workflow: interpret -> resolve -> optimize -> independently verify.

Explanations are rendered from verified numbers, never synthesized by the language model.
There is no purchasing tool, arbitrary code execution or autonomous constraint relaxation.
"""

import math
from time import perf_counter
from uuid import uuid4

from .audit import AuditStore
from .data import get_scenario
from .language import ModelClient, ModelError, parse_rules
from .optimizer import resolve_scenario, solve, validate_solution
from .schemas import AgentRequest, AgentResponse, OptimizationResult, TokenUsage, TraceStep


def explain_result(result: OptimizationResult) -> str:
    if result.status == "infeasible":
        details = [d.rstrip("。；.") for d in result.diagnostics if not d.startswith("未自动放松")]
        detail = "；".join(details) or result.message.rstrip("。")
        return f"当前约束下没有可行补货方案。{detail}。系统没有修改预算或放宽服务要求。"
    if result.status == "error":
        return f"本次未能给出经过验证的补货方案：{result.message}"
    proof = "已找到最优方案" if result.status == "optimal" else "已找到可行方案，尚未证明最优"
    shortage = sum(line.shortage for line in result.orders)
    return (
        f"{proof}。采购支出 {result.purchase_cost:,.2f} 元，"
        f"预算 {result.budget:,.2f} 元；总目标成本 {result.total_cost:,.2f} 元"
        f"（采购＋期末持有＋缺货罚金），需求满足率 {result.fill_rate:.1%}，"
        f"缺货 {shortage} 件。"
        "结果已通过独立业务约束检查。以上为合成场景的决策建议，未执行采购。"
    )


def run_agent(
    request: AgentRequest,
    *,
    store: AuditStore | None = None,
    model_client: ModelClient | None = None,
) -> AgentResponse:
    started = perf_counter()
    request_id = uuid4().hex
    trace = []
    usage = TokenUsage()
    model_name = None
    provider_stats = {"provider_calls": 0, "http_attempts": 0, "guarded": False}
    usage_known = True
    intent = None
    result = None
    scenario = get_scenario(request.scenario_id)
    trace.append(TraceStep(name="load_scenario", status="ok", detail=f"{scenario.name} / 合成数据"))
    try:
        step = perf_counter()
        if request.mode == "llm":
            client = model_client or ModelClient.from_env()
            model_name = client.model
            try:
                intent, usage = client.parse(request.message, scenario)
            finally:
                provider_stats.update(getattr(client, "last_parse_stats", {}))
        else:
            intent = parse_rules(request.message, scenario)
        trace.append(
            TraceStep(
                name="interpret_request",
                status="ok" if intent.action == "optimize" else "blocked",
                elapsed_ms=(perf_counter() - step) * 1000,
                detail=("本地约束检查；未调用模型" if provider_stats["guarded"] else "真实模型解析")
                if request.mode == "llm"
                else "受限规则解析；未调用大模型",
            )
        )
        if intent.action == "clarify":
            status = "needs_clarification"
            explanation = "请补充完整条件后重新提交：" + "；".join(
                intent.questions or [intent.reason]
            )
        elif intent.action == "reject":
            status = "rejected"
            explanation = intent.reason or "该请求超出补货决策工具允许的操作范围。"
        else:
            step = perf_counter()
            try:
                resolve_scenario(scenario, intent.parameters)
                result = solve(scenario, intent.parameters)
            except ValueError:
                status = "needs_clarification"
                explanation = "请求包含无法应用的物料编号或参数，请核对场景后重新提交完整条件。"
                trace.append(
                    TraceStep(name="validate_parameters", status="blocked", detail=explanation)
                )
            else:
                trace.append(
                    TraceStep(
                        name="optimize_replenishment",
                        status="error" if result.status == "error" else "ok",
                        elapsed_ms=(perf_counter() - step) * 1000,
                        detail=result.message,
                    )
                )
                if result.status in {"optimal", "feasible"}:
                    step = perf_counter()
                    verified = validate_solution(scenario, intent.parameters, result.orders)
                    effective = resolve_scenario(scenario, intent.parameters)
                    expected_purchase = sum(line.purchase_cost for line in result.orders)
                    expected_holding = sum(line.holding_cost for line in result.orders)
                    expected_shortage = sum(line.shortage_cost for line in result.orders)
                    total_demand = sum(line.demand for line in result.orders)
                    expected_fill = (
                        1 - sum(line.shortage for line in result.orders) / total_demand
                        if total_demand
                        else 1.0
                    )
                    summaries = {
                        "purchase_cost": expected_purchase,
                        "holding_cost": expected_holding,
                        "shortage_cost": expected_shortage,
                        "total_cost": expected_purchase + expected_holding + expected_shortage,
                        "fill_rate": expected_fill,
                        "budget": effective.budget,
                    }
                    for name, expected in summaries.items():
                        actual = getattr(result, name)
                        verified.checks += 1
                        if actual is None or not math.isclose(
                            actual, expected, rel_tol=1e-8, abs_tol=1e-5
                        ):
                            verified.violations.append(f"汇总字段 {name} 与独立重算不一致")
                    verified.valid = not verified.violations
                    result.validation = verified
                    trace.append(
                        TraceStep(
                            name="verify_constraints",
                            status="ok" if verified.valid else "error",
                            elapsed_ms=(perf_counter() - step) * 1000,
                            detail=f"{verified.checks} 项检查；{len(verified.violations)} 项违反",
                        )
                    )
                    if not verified.valid:
                        # Do not expose a numerically plausible but invalid procurement recommendation.
                        result = OptimizationResult(
                            status="error",
                            message="独立验证未通过，已阻止输出采购方案。",
                            budget=result.budget,
                            validation=verified,
                        )
                status = {
                    "optimal": "completed",
                    "feasible": "completed",
                    "infeasible": "infeasible",
                    "error": "error",
                }[result.status]
                explanation = explain_result(result)
    except ModelError:
        usage_known = provider_stats["http_attempts"] == 0
        status = "error"
        explanation = "模型接口暂不可用或返回内容未通过校验。未切换为规则模式，未执行求解。"
        trace.append(TraceStep(name="interpret_request", status="error", detail=explanation))
    response = AgentResponse(
        request_id=request_id,
        status=status,
        mode=request.mode,
        model=model_name,
        intent=intent,
        result=result,
        explanation=explanation,
        trace=trace,
        usage=usage,
        usage_known=usage_known,
        provider_calls=provider_stats["provider_calls"],
        http_attempts=provider_stats["http_attempts"],
        local_guarded=provider_stats["guarded"],
        elapsed_ms=(perf_counter() - started) * 1000,
    )
    if store is not None:
        store.save(request, response)
    return response
