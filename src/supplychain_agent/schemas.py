"""Typed public contracts. Money is in CNY, quantities are integer units, time is days."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class SKU(StrictModel):
    sku_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    initial_stock: int = Field(ge=0, le=1_000_000)
    demand: int = Field(ge=0, le=1_000_000)
    unit_cost: float = Field(gt=0, le=1_000_000)
    holding_cost: float = Field(ge=0, le=1_000_000)
    shortage_penalty: float = Field(gt=0, le=1_000_000)
    min_order_qty: int = Field(ge=0, le=1_000_000)
    max_order_qty: int = Field(ge=0, le=1_000_000)
    lead_time_days: int = Field(ge=0, le=365)
    critical: bool = False


class Scenario(StrictModel):
    scenario_id: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    provenance: str = "synthetic"
    budget: float = Field(ge=0, le=1_000_000_000)
    horizon_days: int = Field(ge=1, le=365)
    min_service_level: float = Field(default=0.0, ge=0, le=1)
    skus: list[SKU] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_skus(self):
        ids = [s.sku_id for s in self.skus]
        if len(ids) != len(set(ids)):
            raise ValueError("sku_id must be unique")
        return self


class DemandUpdate(StrictModel):
    sku_id: str = Field(min_length=1, max_length=40)
    demand: int = Field(ge=0, le=1_000_000)


class PlanParameters(StrictModel):
    budget: float | None = Field(default=None, ge=0, le=1_000_000_000)
    budget_change_pct: float | None = Field(default=None, ge=-100, le=500)
    horizon_days: int | None = Field(default=None, ge=1, le=365)
    min_service_level: float | None = Field(default=None, ge=0, le=1)
    protected_skus: list[str] = Field(default_factory=list, max_length=100)
    excluded_skus: list[str] = Field(default_factory=list, max_length=100)
    demand_updates: list[DemandUpdate] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def consistent(self):
        if self.budget is not None and self.budget_change_pct is not None:
            raise ValueError("Choose an absolute budget or a relative budget change, not both")
        ids = [d.sku_id for d in self.demand_updates]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate demand update")
        return self


class ParsedIntent(StrictModel):
    action: Literal["optimize", "clarify", "reject"]
    parameters: PlanParameters = Field(default_factory=PlanParameters)
    questions: list[str] = Field(default_factory=list, max_length=10)
    reason: str = Field(default="", max_length=2000)


class OrderLine(StrictModel):
    sku_id: str
    name: str
    initial_stock: int
    demand: int
    order_qty: int
    ending_stock: int
    shortage: int
    purchase_cost: float
    holding_cost: float
    shortage_cost: float


class ValidationReport(StrictModel):
    valid: bool
    checks: int
    violations: list[str] = Field(default_factory=list)


class OptimizationResult(StrictModel):
    status: Literal["optimal", "feasible", "infeasible", "error"]
    message: str
    orders: list[OrderLine] = Field(default_factory=list)
    purchase_cost: float | None = None
    holding_cost: float | None = None
    shortage_cost: float | None = None
    total_cost: float | None = None
    fill_rate: float | None = None
    budget: float
    solver_seconds: float = 0
    mip_gap: float | None = None
    lower_bound: float | None = None
    validation: ValidationReport | None = None
    diagnostics: list[str] = Field(default_factory=list)


class TraceStep(StrictModel):
    name: str
    status: Literal["ok", "blocked", "error"]
    elapsed_ms: float = 0
    detail: str = ""


class TokenUsage(StrictModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AgentRequest(StrictModel):
    scenario_id: str = "factory-demo"
    message: str = Field(
        min_length=1, max_length=4000, examples=["预算9000元，电机和传感器不能缺货"]
    )
    mode: Literal["rules", "llm"] = "rules"


class AgentResponse(StrictModel):
    request_id: str
    status: Literal["completed", "needs_clarification", "rejected", "infeasible", "error"]
    mode: Literal["rules", "llm"]
    model: str | None = None
    intent: ParsedIntent | None = None
    result: OptimizationResult | None = None
    explanation: str
    trace: list[TraceStep] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    usage_known: bool = True
    provider_calls: int = 0
    http_attempts: int = 0
    local_guarded: bool = False
    elapsed_ms: float = 0
