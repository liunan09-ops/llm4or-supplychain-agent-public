"""Single-period integer replenishment, solved by SciPy/HiGHS and independently checked.

The model intentionally has no hidden "protect critical items" policy. Only explicit
``protected_skus`` impose zero shortage. A solve never relaxes user constraints.
"""

from decimal import ROUND_CEILING, Decimal
from math import isfinite, ulp
from numbers import Integral, Real
from time import perf_counter

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_array

from .schemas import (
    OptimizationResult,
    OrderLine,
    PlanParameters,
    Scenario,
    ValidationReport,
)


def _required_service(demand: int, level: float) -> int:
    # Decimal avoids ceil(100 * 0.14) unexpectedly becoming 15 in binary floating point.
    return int((Decimal(demand) * Decimal(str(level))).to_integral_value(rounding=ROUND_CEILING))


def _tolerance(*values: float) -> float:
    return max(1e-6, *(16 * ulp(float(v)) for v in values))


def resolve_scenario(scenario: Scenario, parameters: PlanParameters) -> Scenario:
    """Apply a request to a copy, refusing unknown identifiers and invalid effective values."""
    known = {s.sku_id for s in scenario.skus}
    referenced = (
        set(parameters.protected_skus)
        | set(parameters.excluded_skus)
        | {d.sku_id for d in parameters.demand_updates}
    )
    unknown = sorted(referenced - known)
    if unknown:
        raise ValueError(f"Unknown SKU identifiers: {', '.join(unknown)}")
    changes = {d.sku_id: d.demand for d in parameters.demand_updates}
    payload = scenario.model_dump()
    if parameters.budget is not None:
        payload["budget"] = parameters.budget
    elif parameters.budget_change_pct is not None:
        multiplier = Decimal(1) + Decimal(str(parameters.budget_change_pct)) / Decimal(100)
        payload["budget"] = float(Decimal(str(scenario.budget)) * multiplier)
    if parameters.horizon_days is not None:
        payload["horizon_days"] = parameters.horizon_days
    if parameters.min_service_level is not None:
        payload["min_service_level"] = parameters.min_service_level
    for sku in payload["skus"]:
        if sku["sku_id"] in changes:
            sku["demand"] = changes[sku["sku_id"]]
    return Scenario.model_validate(payload)


def validate_solution(
    scenario: Scenario, parameters: PlanParameters, orders: list[OrderLine]
) -> ValidationReport:
    """Check business equations directly, without inspecting the solver or its matrix.

    Recomputes quantities/costs from trusted scenario data. Missing, repeated, unknown,
    noninteger, negative, nonfinite, or doctored fields cannot certify a solution.
    """
    checks = 0
    violations: list[str] = []

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            violations.append(message)

    try:
        resolved = resolve_scenario(scenario, parameters)
    except (ValueError, TypeError) as exc:
        return ValidationReport(valid=False, checks=1, violations=[f"Invalid parameters: {exc}"])
    sku_map = {s.sku_id: s for s in resolved.skus}
    protected = set(parameters.protected_skus)
    excluded = set(parameters.excluded_skus)
    seen: set[str] = set()
    purchase_total = 0.0
    check(isinstance(orders, list), "Orders must be a list of OrderLine records")
    if not isinstance(orders, list):
        return ValidationReport(valid=False, checks=checks, violations=violations)
    for line in orders:
        check(isinstance(line, OrderLine), "Every order must be an OrderLine record")
        if not isinstance(line, OrderLine):
            continue
        complete = all(hasattr(line, field) for field in OrderLine.model_fields)
        check(complete, "Order line is missing required fields")
        if not complete:
            continue
        check(isinstance(line.sku_id, str), "SKU identifier must be a string")
        if not isinstance(line.sku_id, str):
            continue
        label = line.sku_id
        check(label not in seen, f"{label}: duplicate order line")
        seen.add(label)
        check(label in sku_map, f"{label}: unknown SKU")
        if label not in sku_map:
            continue
        sku = sku_map[label]
        check(line.name == sku.name, f"{label}: name does not match scenario")
        check(
            all(
                isinstance(v, Integral) and not isinstance(v, bool)
                for v in (line.initial_stock, line.demand)
            ),
            f"{label}: initial stock and demand must be integers",
        )
        check(line.initial_stock == sku.initial_stock, f"{label}: altered initial stock")
        check(line.demand == sku.demand, f"{label}: altered demand")
        quantities = (line.order_qty, line.ending_stock, line.shortage)
        integer = all(isinstance(v, Integral) and not isinstance(v, bool) for v in quantities)
        check(integer, f"{label}: order, ending stock and shortage must be integers")
        if not integer:
            continue
        q, ending, shortage = (int(v) for v in quantities)
        check(all(v >= 0 for v in quantities), f"{label}: negative quantity")
        check(q <= sku.max_order_qty, f"{label}: exceeds maximum order quantity")
        check(q == 0 or q >= sku.min_order_qty, f"{label}: violates minimum order quantity")
        check(label not in excluded or q == 0, f"{label}: excluded SKU was ordered")
        check(
            sku.lead_time_days <= resolved.horizon_days or q == 0,
            f"{label}: delivery arrives after planning horizon",
        )
        check(
            sku.initial_stock + q + shortage - ending == sku.demand,
            f"{label}: inventory balance does not hold",
        )
        check(
            ending == max(sku.initial_stock + q - sku.demand, 0),
            f"{label}: ending stock is not physical surplus",
        )
        check(
            shortage == max(sku.demand - sku.initial_stock - q, 0),
            f"{label}: shortage is not physical unmet demand",
        )
        check(label not in protected or shortage == 0, f"{label}: protected SKU has shortage")
        check(
            sku.demand - shortage >= _required_service(sku.demand, resolved.min_service_level),
            f"{label}: per-SKU minimum service level violated",
        )
        expected_costs = (
            ("purchase", line.purchase_cost, q * sku.unit_cost),
            ("holding", line.holding_cost, ending * sku.holding_cost),
            ("shortage", line.shortage_cost, shortage * sku.shortage_penalty),
        )
        for cost_name, actual, expected in expected_costs:
            numeric = isinstance(actual, Real) and not isinstance(actual, bool) and isfinite(actual)
            check(numeric, f"{label}: {cost_name} cost is not a finite number")
            if numeric:
                check(
                    abs(actual - expected) <= _tolerance(actual, expected),
                    f"{label}: altered {cost_name} cost",
                )
        purchase_total += q * sku.unit_cost
    check(seen == set(sku_map), "Exactly one order line is required for every scenario SKU")
    check(
        purchase_total <= resolved.budget + _tolerance(purchase_total, resolved.budget),
        f"Purchase budget exceeded: {purchase_total:.6f} > {resolved.budget:.6f}",
    )
    return ValidationReport(valid=not violations, checks=checks, violations=violations)


def _infeasibility_diagnostics(scenario: Scenario, parameters: PlanParameters) -> list[str]:
    """Explain sufficient contradictions; never represent heuristics as an IIS proof."""
    notes: list[str] = []
    minimum_spend = 0.0
    protected = set(parameters.protected_skus)
    excluded = set(parameters.excluded_skus)
    for sku in scenario.skus:
        target = (
            sku.demand
            if sku.sku_id in protected
            else _required_service(sku.demand, scenario.min_service_level)
        )
        needed = max(0, target - sku.initial_stock)
        if needed == 0:
            continue
        minimum_order = max(needed, sku.min_order_qty)
        minimum_spend += minimum_order * sku.unit_cost
        if sku.sku_id in excluded:
            notes.append(
                f"充分证据：{sku.sku_id} 被禁止采购，但满足服务约束至少需要补货 {needed} 件。"
            )
        if sku.lead_time_days > scenario.horizon_days:
            notes.append(
                f"充分证据：{sku.sku_id} 交期 {sku.lead_time_days} 天超过计划期 "
                f"{scenario.horizon_days} 天，现有库存无法满足服务约束。"
            )
        if minimum_order > sku.max_order_qty:
            notes.append(
                f"充分证据：{sku.sku_id} 满足服务约束及 MOQ 至少需采购 {minimum_order} 件，"
                f"超过订购上限 {sku.max_order_qty} 件。"
            )
    if minimum_spend > scenario.budget + _tolerance(minimum_spend, scenario.budget):
        notes.append(
            f"充分证据：满足服务约束及 MOQ 的必要采购成本至少 {minimum_spend:.2f} 元，"
            f"超过预算 {scenario.budget:.2f} 元。"
        )
    if not notes:
        notes.append("HiGHS 判定当前模型不可行；上述简单规则未定位矛盾，不声称已获得最小冲突集。")
    notes.append("未自动放松预算、服务水平、保护清单、交期或采购限制。")
    return notes


def _finite_optional(result: object, attribute: str) -> float | None:
    value = getattr(result, attribute, None)
    return float(value) if isinstance(value, Real) and isfinite(value) else None


def solve(
    scenario: Scenario, parameters: PlanParameters, *, time_limit: float = 5.0
) -> OptimizationResult:
    """Solve the exact integer model and certify any incumbent with an independent check.

    HiGHS status 1 is a limit, never an infeasibility certificate. It is returned as
    ``feasible`` only with a verified incumbent; without one the public status is ``error``.
    """
    started = perf_counter()
    try:
        resolved = resolve_scenario(scenario, parameters)
    except (ValueError, TypeError) as exc:
        return OptimizationResult(
            status="error", message=f"参数无效：{exc}", budget=scenario.budget
        )
    if (
        not isinstance(time_limit, Real)
        or isinstance(time_limit, bool)
        or not isfinite(time_limit)
        or time_limit <= 0
    ):
        return OptimizationResult(
            status="error", message="time_limit 必须为有限正数。", budget=resolved.budget
        )
    n = len(resolved.skus)
    # Five variables per item: integer order q, order-open binary y, ending e,
    # shortage s, and surplus-side binary z (enforces e*s == 0 even for incumbents).
    objective = np.zeros(5 * n)
    upper = np.zeros(5 * n)
    rows: list[dict[int, float]] = []
    row_lower: list[float] = []
    row_upper: list[float] = []

    def constraint(coefficients: dict[int, float], lower: float, high: float) -> None:
        rows.append(coefficients)
        row_lower.append(lower)
        row_upper.append(high)

    budget_row: dict[int, float] = {}
    protected = set(parameters.protected_skus)
    excluded = set(parameters.excluded_skus)
    for i, sku in enumerate(resolved.skus):
        q, y, e, s, z = range(i * 5, i * 5 + 5)
        can_order = sku.lead_time_days <= resolved.horizon_days and sku.sku_id not in excluded
        order_cap = sku.max_order_qty if can_order else 0
        surplus_cap = max(0, sku.initial_stock + order_cap - sku.demand)
        shortage_cap = max(0, sku.demand - sku.initial_stock)
        required = (
            sku.demand
            if sku.sku_id in protected
            else _required_service(sku.demand, resolved.min_service_level)
        )
        upper[q], upper[y], upper[e], upper[s], upper[z] = (
            order_cap,
            1,
            surplus_cap,
            min(shortage_cap, sku.demand - required),
            1,
        )
        objective[q], objective[e], objective[s] = (
            sku.unit_cost,
            sku.holding_cost,
            sku.shortage_penalty,
        )
        constraint({q: 1, y: -sku.max_order_qty}, -np.inf, 0)
        constraint({q: 1, y: -sku.min_order_qty}, 0, np.inf)
        constraint(
            {q: 1, e: -1, s: 1}, sku.demand - sku.initial_stock, sku.demand - sku.initial_stock
        )
        constraint({e: 1, z: -surplus_cap}, -np.inf, 0)
        constraint({s: 1, z: shortage_cap}, -np.inf, shortage_cap)
        budget_row[q] = sku.unit_cost
    constraint(budget_row, -np.inf, resolved.budget)
    matrix = np.zeros((len(rows), n * 5))
    for r, coefficients in enumerate(rows):
        for column, coefficient in coefficients.items():
            matrix[r, column] = coefficient
    try:
        raw = milp(
            c=objective,
            integrality=np.ones(n * 5),
            bounds=Bounds(np.zeros(n * 5), upper),
            constraints=LinearConstraint(csc_array(matrix), row_lower, row_upper),
            options={"time_limit": float(time_limit), "mip_rel_gap": 0.0},
        )
    except (ValueError, RuntimeError, TypeError, MemoryError) as exc:
        return OptimizationResult(
            status="error",
            message=f"求解器执行失败：{type(exc).__name__}: {exc}",
            budget=resolved.budget,
            solver_seconds=perf_counter() - started,
        )
    elapsed = perf_counter() - started
    if raw.status == 2:
        return OptimizationResult(
            status="infeasible",
            message="当前硬约束下无可行补货方案。",
            budget=resolved.budget,
            solver_seconds=elapsed,
            diagnostics=_infeasibility_diagnostics(resolved, parameters),
        )
    if raw.status not in (0, 1):
        return OptimizationResult(
            status="error",
            message=f"求解器未返回可用结果（状态 {raw.status}）：{raw.message}",
            budget=resolved.budget,
            solver_seconds=elapsed,
        )
    if getattr(raw, "x", None) is None:
        return OptimizationResult(
            status="error",
            message=(
                "求解达到时间或迭代上限，未找到可行解；不能据此判定问题不可行。"
                if raw.status == 1
                else "求解器报告成功但没有返回解。"
            ),
            budget=resolved.budget,
            solver_seconds=elapsed,
            lower_bound=_finite_optional(raw, "mip_dual_bound"),
        )
    try:
        values = np.asarray(raw.x, dtype=float)
    except (ValueError, TypeError):
        return OptimizationResult(
            status="error",
            message="求解器返回无法解析的数值，结果未获认证。",
            budget=resolved.budget,
            solver_seconds=elapsed,
        )
    if values.shape != (5 * n,) or not np.all(np.isfinite(values)):
        return OptimizationResult(
            status="error",
            message="求解器返回非有限数值或错误维度，结果未获认证。",
            budget=resolved.budget,
            solver_seconds=elapsed,
        )
    if np.any(np.abs(values - np.rint(values)) > 1e-5):
        return OptimizationResult(
            status="error",
            message="求解器返回非整数解，结果未获认证。",
            budget=resolved.budget,
            solver_seconds=elapsed,
        )
    orders: list[OrderLine] = []
    for i, sku in enumerate(resolved.skus):
        q, _, ending, shortage, _ = (round(v) for v in values[i * 5 : i * 5 + 5])
        orders.append(
            OrderLine(
                sku_id=sku.sku_id,
                name=sku.name,
                initial_stock=sku.initial_stock,
                demand=sku.demand,
                order_qty=q,
                ending_stock=ending,
                shortage=shortage,
                purchase_cost=q * sku.unit_cost,
                holding_cost=ending * sku.holding_cost,
                shortage_cost=shortage * sku.shortage_penalty,
            )
        )
    validation = validate_solution(scenario, parameters, orders)
    if not validation.valid:
        return OptimizationResult(
            status="error",
            message="求解结果未通过独立业务约束校验，禁止用于决策。",
            budget=resolved.budget,
            solver_seconds=elapsed,
            validation=validation,
        )
    purchase = sum(line.purchase_cost for line in orders)
    holding = sum(line.holding_cost for line in orders)
    shortage_cost = sum(line.shortage_cost for line in orders)
    total_demand = sum(sku.demand for sku in resolved.skus)
    return OptimizationResult(
        status="optimal" if raw.status == 0 else "feasible",
        message=(
            "已获得并独立校验整数最优补货方案。"
            if raw.status == 0
            else "求解达到时间或迭代上限；当前可行方案已通过校验，尚未证明最优。"
        ),
        orders=orders,
        purchase_cost=purchase,
        holding_cost=holding,
        shortage_cost=shortage_cost,
        total_cost=purchase + holding + shortage_cost,
        fill_rate=1 - sum(line.shortage for line in orders) / total_demand if total_demand else 1.0,
        budget=resolved.budget,
        solver_seconds=elapsed,
        mip_gap=_finite_optional(raw, "mip_gap"),
        lower_bound=_finite_optional(raw, "mip_dual_bound"),
        validation=validation,
    )
