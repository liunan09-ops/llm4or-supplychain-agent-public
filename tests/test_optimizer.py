"""Behavioral checks with an independent enumeration oracle, not model-matrix snapshots."""

from decimal import ROUND_CEILING, Decimal
from itertools import product
from random import Random
from types import SimpleNamespace

import numpy as np
import pytest

from supplychain_agent import optimizer
from supplychain_agent.data import demo_scenario
from supplychain_agent.optimizer import resolve_scenario, solve, validate_solution
from supplychain_agent.schemas import SKU, DemandUpdate, OrderLine, PlanParameters, Scenario


def item(sku_id="A", **changes):
    data = {
        "sku_id": sku_id,
        "name": f"Material {sku_id}",
        "initial_stock": 0,
        "demand": 4,
        "unit_cost": 2,
        "holding_cost": 1,
        "shortage_penalty": 10,
        "min_order_qty": 0,
        "max_order_qty": 8,
        "lead_time_days": 1,
    }
    data.update(changes)
    return SKU(**data)


def scenario(*items, **changes):
    data = {
        "scenario_id": "test",
        "name": "Synthetic test",
        "budget": 100,
        "horizon_days": 7,
        "skus": list(items) or [item()],
    }
    data.update(changes)
    return Scenario(**data)


def oracle(case, parameters):
    """Enumerate business choices independently; no call to optimizer resolution or helpers."""
    budget = parameters.budget if parameters.budget is not None else case.budget
    if parameters.budget_change_pct is not None:
        budget = case.budget * (1 + parameters.budget_change_pct / 100)
    horizon = parameters.horizon_days if parameters.horizon_days is not None else case.horizon_days
    level = (
        parameters.min_service_level
        if parameters.min_service_level is not None
        else case.min_service_level
    )
    updates = {update.sku_id: update.demand for update in parameters.demand_updates}
    choices = []
    for sku in case.skus:
        choices.append(
            [
                q
                for q in range(sku.max_order_qty + 1)
                if (q == 0 or q >= sku.min_order_qty)
                and (q == 0 or sku.lead_time_days <= horizon)
                and (q == 0 or sku.sku_id not in parameters.excluded_skus)
            ]
        )
    best = None
    for quantities in product(*choices):
        cost = 0.0
        spend = sum(q * sku.unit_cost for sku, q in zip(case.skus, quantities))
        if spend > budget + 1e-8:
            continue
        valid = True
        for sku, q in zip(case.skus, quantities):
            demand = updates.get(sku.sku_id, sku.demand)
            shortage = max(demand - sku.initial_stock - q, 0)
            surplus = max(sku.initial_stock + q - demand, 0)
            minimum = int(
                (Decimal(demand) * Decimal(str(level))).to_integral_value(rounding=ROUND_CEILING)
            )
            if demand - shortage < minimum:
                valid = False
            if sku.sku_id in parameters.protected_skus and shortage:
                valid = False
            cost += q * sku.unit_cost + surplus * sku.holding_cost + shortage * sku.shortage_penalty
        if valid and (best is None or cost < best):
            best = cost
    return best


@pytest.mark.parametrize("seed", range(30))
def test_small_instances_match_exhaustive_oracle(seed):
    rng = Random(seed)
    case = scenario(
        *[
            item(
                str(i),
                initial_stock=rng.randint(0, 5),
                demand=rng.randint(0, 6),
                unit_cost=rng.choice([0.75, 2, 4]),
                holding_cost=rng.choice([0, 0.5, 3]),
                shortage_penalty=rng.choice([1, 8, 20]),
                min_order_qty=rng.randint(0, 4),
                max_order_qty=rng.randint(2, 5),
                lead_time_days=rng.choice([1, 10]),
                critical=True,
            )
            for i in range(3)
        ],
        budget=rng.randint(0, 25),
        min_service_level=rng.choice([0, 0.5, 1]),
    )
    params = PlanParameters(
        protected_skus=["0"] if seed % 4 == 0 else [],
        excluded_skus=["1"] if seed % 5 == 0 else [],
        demand_updates=[DemandUpdate(sku_id="2", demand=seed % 7)] if seed % 3 == 0 else [],
    )
    expected = oracle(case, params)
    result = solve(case, params)
    if expected is None:
        assert result.status == "infeasible"
        assert result.orders == []
    else:
        assert result.status == "optimal", result.model_dump()
        assert result.validation.valid
        assert result.total_cost == pytest.approx(expected, abs=1e-7)
        assert result.purchase_cost <= result.budget + 1e-7


def test_budget_absolute_relative_and_original_remains_unchanged():
    case = scenario(budget=10)
    relative = solve(case, PlanParameters(budget_change_pct=-40))
    absolute = solve(case, PlanParameters(budget=6))
    assert relative.budget == absolute.budget == 6
    assert relative.orders == absolute.orders
    assert relative.orders[0].order_qty == 3
    assert case.budget == 10
    assert solve(case, PlanParameters(budget_change_pct=-100)).orders[0].order_qty == 0


def test_moq_can_force_overstock_or_no_order_and_does_not_round_to_packs():
    case = scenario(item(initial_stock=0, demand=2, min_order_qty=5, max_order_qty=8))
    result = solve(case, PlanParameters())
    assert (result.orders[0].order_qty, result.orders[0].ending_stock) == (5, 3)
    assert solve(case, PlanParameters(budget=9)).orders[0].order_qty == 0
    not_pack_case = scenario(item(demand=6, min_order_qty=5))
    assert solve(not_pack_case, PlanParameters()).orders[0].order_qty == 6


def test_moq_larger_than_upper_bound_allows_zero_but_protection_is_infeasible():
    case = scenario(item(min_order_qty=9, max_order_qty=8))
    assert solve(case, PlanParameters()).orders[0].order_qty == 0
    result = solve(case, PlanParameters(protected_skus=["A"]))
    assert result.status == "infeasible"
    assert any("上限" in note for note in result.diagnostics)


def test_delivery_boundary_exclusion_and_protection_have_distinct_meanings():
    case = scenario(item(lead_time_days=7, critical=True))
    assert solve(case, PlanParameters()).orders[0].order_qty == 4
    late = solve(case, PlanParameters(horizon_days=6))
    assert late.status == "optimal"  # The critical label does not silently protect the SKU.
    assert late.orders[0].order_qty == 0
    assert late.orders[0].shortage == 4
    protected = solve(case, PlanParameters(horizon_days=6, protected_skus=["A"]))
    assert protected.status == "infeasible"
    assert any("交期" in note for note in protected.diagnostics)
    excluded = solve(case, PlanParameters(excluded_skus=["A"]))
    assert excluded.orders[0].order_qty == 0
    enough_existing = scenario(item(initial_stock=6, lead_time_days=20))
    assert (
        solve(enough_existing, PlanParameters(excluded_skus=["A"], protected_skus=["A"])).status
        == "optimal"
    )


def test_minimum_service_is_per_sku_and_decimal_ceiling_is_stable():
    case = scenario(
        item("A", demand=100, max_order_qty=100, shortage_penalty=0.01),
        item("B", demand=3, max_order_qty=100, shortage_penalty=0.01),
        budget=100,
    )
    result = solve(case, PlanParameters(min_service_level=0.14))
    assert result.status == "optimal"
    assert [line.order_qty for line in result.orders] == [14, 1]
    assert result.fill_rate == pytest.approx(15 / 103)
    impossible = solve(case, PlanParameters(min_service_level=0.14, budget=29))
    assert impossible.status == "infeasible"
    assert any("最低" in note or "必要采购成本" in note for note in impossible.diagnostics)


def test_initial_overstock_zero_demand_and_demand_updates():
    case = scenario(item(initial_stock=8, demand=2), item("B", demand=0))
    result = solve(case, PlanParameters())
    assert [line.order_qty for line in result.orders] == [0, 0]
    assert result.orders[0].ending_stock == 6
    assert result.holding_cost == 6
    assert result.shortage_cost == 0
    update = PlanParameters(demand_updates=[DemandUpdate(sku_id="A", demand=10)])
    updated = solve(case, update)
    assert updated.orders[0].demand == 10
    assert updated.orders[0].order_qty == 2
    assert case.skus[0].demand == 2
    zero = solve(scenario(item(demand=0)), PlanParameters())
    assert zero.fill_rate == 1


def test_protection_budget_conflict_is_reported_and_never_relaxed():
    case = scenario(item(min_order_qty=5), budget=9)
    params = PlanParameters(protected_skus=["A"])
    result = solve(case, params)
    assert result.status == "infeasible"
    assert result.budget == 9
    assert result.orders == []
    assert any("10.00" in note for note in result.diagnostics)


def test_unknown_ids_are_not_silently_ignored():
    case = scenario()
    for params in [
        PlanParameters(protected_skus=["MISSING"]),
        PlanParameters(excluded_skus=["MISSING"]),
        PlanParameters(demand_updates=[DemandUpdate(sku_id="MISSING", demand=2)]),
    ]:
        with pytest.raises(ValueError, match="Unknown SKU"):
            resolve_scenario(case, params)
        assert solve(case, params).status == "error"
        assert not validate_solution(case, params, []).valid


@pytest.mark.parametrize(
    "change",
    [
        {"purchase_cost": 0.0},
        {"holding_cost": 1.0},
        {"shortage_cost": 1.0},
        {"initial_stock": 100},
        {"demand": 0},
        {"name": "Forged"},
        {"order_qty": 3.5},
        {"order_qty": True},
        {"order_qty": -1},
        {"ending_stock": 2, "shortage": 2},  # Balance alone would pass this tampering.
        {"purchase_cost": float("nan")},
        {"shortage": float("inf")},
        {"initial_stock": False},
    ],
)
def test_validator_rejects_doctored_reports(change):
    case = scenario()
    params = PlanParameters()
    good = solve(case, params).orders[0]
    corrupt = good.model_copy(update=change)  # Bypass parsing to exercise trust boundary.
    assert not validate_solution(case, params, [corrupt]).valid


def test_validator_rejects_missing_duplicate_unknown_and_malformed_lines():
    case = scenario()
    params = PlanParameters()
    good = solve(case, params).orders[0]
    bad_orders = [
        [],
        [good, good],
        [good.model_copy(update={"sku_id": "UNKNOWN"})],
        [good.model_dump()],
        [OrderLine.model_construct(sku_id="A")],
    ]
    for orders in bad_orders:
        assert not validate_solution(case, params, orders).valid


def test_validator_rechecks_constraints_against_the_requested_scenario():
    case = scenario(item(min_order_qty=5, max_order_qty=8, demand=6))
    params = PlanParameters()
    good = solve(case, params).orders
    assert validate_solution(case, params, good).valid
    for changed in [
        PlanParameters(budget=0),
        PlanParameters(excluded_skus=["A"]),
        PlanParameters(demand_updates=[DemandUpdate(sku_id="A", demand=7)]),
    ]:
        assert not validate_solution(case, changed, good).valid
    late_case = scenario(item(min_order_qty=5, max_order_qty=8, demand=6, lead_time_days=8))
    assert not validate_solution(late_case, params, good).valid
    no_order = solve(case, PlanParameters(budget=0)).orders
    assert not validate_solution(case, PlanParameters(protected_skus=["A"]), no_order).valid
    assert not validate_solution(case, PlanParameters(min_service_level=0.5), no_order).valid


def incumbent_vector(result):
    return np.array(
        [
            value
            for line in result.orders
            for value in (
                line.order_qty,
                int(line.order_qty > 0),
                line.ending_stock,
                line.shortage,
                int(line.ending_stock > 0),
            )
        ],
        dtype=float,
    )


def test_time_limit_with_verified_incumbent_is_feasible_not_optimal(monkeypatch):
    case = scenario()
    x = incumbent_vector(solve(case, PlanParameters()))
    monkeypatch.setattr(
        optimizer,
        "milp",
        lambda **_: SimpleNamespace(
            status=1,
            message="Time limit",
            x=x,
            mip_gap=0.2,
            mip_dual_bound=6.4,
        ),
    )
    result = solve(case, PlanParameters())
    assert result.status == "feasible"
    assert result.validation.valid
    assert "尚未证明最优" in result.message
    assert result.mip_gap == 0.2
    assert result.lower_bound == 6.4


@pytest.mark.parametrize(
    "status,x",
    [
        (1, None),
        (0, None),
        (3, None),
        (4, None),
        (0, [1, 2]),
        (0, [float("nan")] * 5),
        (0, [3.5, 1, 0, 0.5, 0]),
        (0, ["bad"] * 5),
        (0, [100, 1, 96, 0, 1]),  # Physical but violates budget/order bounds.
    ],
)
def test_solver_errors_are_not_infeasibility_or_accepted_orders(monkeypatch, status, x):
    monkeypatch.setattr(
        optimizer,
        "milp",
        lambda **_: SimpleNamespace(
            status=status,
            message="Synthetic solver state",
            x=x,
        ),
    )
    result = solve(scenario(), PlanParameters())
    assert result.status == "error"
    assert result.orders == []
    if status == 1:
        assert "不能据此判定" in result.message


def test_solver_exception_is_contained(monkeypatch):
    def crash(**_):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(optimizer, "milp", crash)
    result = solve(scenario(), PlanParameters())
    assert result.status == "error"
    assert result.orders == []


@pytest.mark.parametrize("time_limit", [0, -1, float("nan"), float("inf"), True])
def test_invalid_time_limit_is_rejected(time_limit):
    assert solve(scenario(), PlanParameters(), time_limit=time_limit).status == "error"


def test_demo_is_synthetic_and_plc_protection_reveals_horizon_conflict():
    case = demo_scenario()
    normal = solve(case, PlanParameters())
    assert normal.status == "optimal"
    assert normal.validation.valid
    assert "synthetic" in case.provenance
    assert next(line for line in normal.orders if line.sku_id == "PLC").shortage == 6
    protected = solve(case, PlanParameters(protected_skus=["PLC"]))
    assert protected.status == "infeasible"
