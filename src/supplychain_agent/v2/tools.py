"""Read-only tool registry. Proposal numbers remain private until explicit validation."""

import math
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import Field, ValidationError

from ..optimizer import resolve_scenario, solve, validate_solution
from ..schemas import OptimizationResult, PlanParameters, StrictModel
from .contracts import Citation, parameters_equal
from .database import DataError, Snapshot


class ToolError(RuntimeError):
    def __init__(self, code, *, retryable=False):
        super().__init__(code)
        self.code, self.retryable = code, retryable


class SKUQuery(StrictModel):
    sku_ids: list[str] = Field(default_factory=list, max_length=100)


class PolicyQuery(StrictModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=5)


class OptimizeArgs(StrictModel):
    parameters: PlanParameters = Field(default_factory=PlanParameters)


class ValidateArgs(StrictModel):
    plan_id: str = Field(min_length=1, max_length=60)


@dataclass
class ToolContext:
    snapshot: Snapshot
    parameters: PlanParameters = field(default_factory=PlanParameters)
    allow_optimization: bool = False
    retriever: Any = None
    solver: Any = solve
    validator: Any = validate_solution
    inventory_seen: set = field(default_factory=set)
    suppliers_seen: set = field(default_factory=set)
    orders_seen: set = field(default_factory=set)
    citations: dict[str, Citation] = field(default_factory=dict)
    facts: dict = field(default_factory=dict)
    proposal: OptimizationResult | None = None
    plan_id: str | None = None
    verified: bool = False
    tool_seconds: float = 5.0

    @property
    def scenario(self):
        return self.snapshot.scenario(self.parameters)


def inventory_query(args, ctx):
    rows = ctx.snapshot.inventory(args.sku_ids, ctx.scenario.horizon_days)
    ctx.inventory_seen.update(r["sku_id"] for r in rows)
    merged = {r["sku_id"]: r for r in ctx.facts.get("inventory", [])}
    merged.update({r["sku_id"]: r for r in rows})
    ctx.facts["inventory"] = list(merged.values())
    return {
        "rows": rows,
        "snapshot_id": ctx.snapshot.snapshot_id,
        "source": "sqlite:inventory + purchase_orders",
        "provenance": "synthetic / demo data",
    }


def supplier_query(args, ctx):
    rows = ctx.snapshot.suppliers(args.sku_ids)
    ctx.suppliers_seen.update(r["sku_id"] for r in rows)
    merged = {r["sku_id"]: r for r in ctx.facts.get("suppliers", [])}
    merged.update({r["sku_id"]: r for r in rows})
    ctx.facts["suppliers"] = list(merged.values())
    return {
        "rows": rows,
        "snapshot_id": ctx.snapshot.snapshot_id,
        "source": "sqlite:sku_supplier + suppliers",
        "provenance": "synthetic / demo data",
    }


def order_query(args, ctx):
    rows = ctx.snapshot.purchase_orders(args.sku_ids)
    ctx.orders_seen.update(args.sku_ids or ctx.snapshot.ids)
    merged = {r["order_id"]: r for r in ctx.facts.get("purchase_orders", [])}
    merged.update({r["order_id"]: r for r in rows})
    ctx.facts["purchase_orders"] = list(merged.values())
    return {
        "rows": rows,
        "snapshot_id": ctx.snapshot.snapshot_id,
        "source": "sqlite:purchase_orders",
        "provenance": "synthetic / demo data",
    }


def policy_retrieval(args, ctx):
    if ctx.retriever is None:
        raise ToolError("retriever_unavailable")
    result = ctx.retriever.search(args.query, args.top_k)
    for item in result["hits"]:
        cite = Citation.model_validate(item["citation"])
        ctx.citations[cite.id] = cite
    return result


def replenishment_optimizer(args, ctx):
    if not ctx.allow_optimization:
        raise ToolError("optimization_not_authorized_by_intent")
    if not parameters_equal(args.parameters, ctx.parameters):
        raise ToolError("parameters_must_match_locked_intent")
    if ctx.inventory_seen != ctx.snapshot.ids or ctx.suppliers_seen != ctx.snapshot.ids:
        raise ToolError("query_all_inventory_and_suppliers_before_optimization")
    if not ctx.citations:
        raise ToolError("retrieve_policy_before_optimization")
    if ctx.proposal is not None:
        raise ToolError("optimization_already_executed")
    ctx.proposal = ctx.solver(ctx.scenario, ctx.parameters, time_limit=ctx.tool_seconds)
    ctx.proposal = OptimizationResult.model_validate(ctx.proposal)
    ctx.plan_id = uuid4().hex
    if ctx.proposal.status == "error":
        raise ToolError("solver_failure")
    return {
        "plan_id": ctx.plan_id,
        "status": ctx.proposal.status,
        "diagnostics": ctx.proposal.diagnostics,
        "next": "solution_validator"
        if ctx.proposal.orders
        else "explain_infeasible_without_relaxing_constraints",
    }


def solution_validator(args, ctx):
    if ctx.proposal is None or args.plan_id != ctx.plan_id:
        raise ToolError("unknown_plan_id")
    if ctx.proposal.status not in {"optimal", "feasible"}:
        raise ToolError("no_feasible_proposal_to_validate")
    result = ctx.proposal
    try:
        checked = ctx.validator(ctx.scenario, ctx.parameters, result.orders)
    except Exception:  # noqa: BLE001 -- unavailable validator never certifies a plan
        raise ToolError("validator_failure") from None
    purchase = sum(o.purchase_cost for o in result.orders)
    holding = sum(o.holding_cost for o in result.orders)
    shortage = sum(o.shortage_cost for o in result.orders)
    demand = sum(o.demand for o in result.orders)
    summary = {
        "purchase_cost": purchase,
        "holding_cost": holding,
        "shortage_cost": shortage,
        "total_cost": purchase + holding + shortage,
        "fill_rate": 1 - sum(o.shortage for o in result.orders) / demand if demand else 1.0,
        "budget": resolve_scenario(ctx.scenario, ctx.parameters).budget,
    }
    for name, expected in summary.items():
        checked.checks += 1
        actual = getattr(result, name)
        if actual is None or not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-5):
            checked.violations.append("summary_mismatch:" + name)
    checked.valid = not checked.violations
    result.validation = checked
    ctx.verified = checked.valid
    if not checked.valid:
        raise ToolError("validator_failure")
    return {
        "plan_id": ctx.plan_id,
        "validation": checked.model_dump(),
        "result": result.model_dump(),
        "source": "independent_validator + deterministic_cost_recalculation",
    }


REGISTRY = {
    "inventory_query": (
        SKUQuery,
        inventory_query,
        "Read on-hand, demand and in-transit inventory. Empty sku_ids means ALL SKUs.",
    ),
    "supplier_query": (
        SKUQuery,
        supplier_query,
        "Read fixed approved supplier, unit cost, MOQ, lead time and cap. Empty sku_ids means ALL.",
    ),
    "policy_retrieval": (
        PolicyQuery,
        policy_retrieval,
        "Retrieve synthetic purchase policy evidence; returns source citations. Never changes constraints.",
    ),
    "replenishment_optimizer": (
        OptimizeArgs,
        replenishment_optimizer,
        "Compute a proposal using locked intent parameters. First query ALL inventory and suppliers and retrieve policies. Never performs purchases.",
    ),
    "solution_validator": (
        ValidateArgs,
        solution_validator,
        "Independently validate a proposal using its returned plan_id. Required before showing any feasible plan.",
    ),
    "order_query": (
        SKUQuery,
        order_query,
        "Read synthetic existing orders; cannot create or update orders.",
    ),
}


def definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": model.model_json_schema(),
            },
        }
        for name, (model, _, description) in REGISTRY.items()
    ]


def execute(name, arguments, ctx):
    if name not in REGISTRY:
        raise ToolError("unknown_tool")
    schema, function, _ = REGISTRY[name]
    try:
        args = schema.model_validate(arguments, strict=True)
        return function(args, ctx)
    except ValidationError:
        raise ToolError("invalid_tool_arguments") from None
    except DataError as exc:
        raise ToolError(str(exc), retryable=str(exc) == "business_database_unavailable") from None
    except ToolError:
        raise
    except TimeoutError:
        raise ToolError("tool_timeout") from None
    except Exception:  # noqa: BLE001 -- public tool boundary must sanitize injected implementation failures
        raise ToolError("tool_execution_failed") from None
