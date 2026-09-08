"""V2 contracts are additive; V1 public models remain unchanged."""

from typing import Any, Literal

from pydantic import Field, model_validator

from ..schemas import OptimizationResult, PlanParameters, StrictModel, TokenUsage


def parameters_equal(first, second):
    def canonical(parameters):
        value = parameters.model_dump()
        for name in ("protected_skus", "excluded_skus"):
            value[name] = sorted(value[name])
        value["demand_updates"] = sorted(value["demand_updates"], key=lambda row: row["sku_id"])
        return value

    return canonical(first) == canonical(second)


Task = Literal[
    "optimize",
    "inventory",
    "supplier",
    "policy",
    "orders",
    "query_then_optimize",
    "clarify",
    "reject",
]
Outcome = Literal[
    "completed",
    "needs_clarification",
    "rejected",
    "infeasible",
    "tool_failure",
    "llm_failure",
    "validator_failure",
    "limit_exceeded",
]


class Intent(StrictModel):
    action: Task
    parameters: PlanParameters = Field(default_factory=PlanParameters)
    sku_ids: list[str] = Field(default_factory=list, max_length=100)
    policy_query: str = Field(default="", max_length=1000)
    questions: list[str] = Field(default_factory=list, max_length=5)
    reason: str = Field(default="", max_length=600)

    @model_validator(mode="after")
    def consistent(self):
        if (
            self.action not in {"optimize", "query_then_optimize"}
            and self.parameters != PlanParameters()
        ):
            raise ValueError("Non-optimization tasks cannot change optimization parameters")
        if self.action not in {"clarify", "reject"} and self.questions:
            raise ValueError("Unresolved questions cannot accompany execution")
        if self.action == "clarify" and not self.questions:
            raise ValueError("Clarification requires a question")
        if len(set(self.sku_ids)) != len(self.sku_ids):
            raise ValueError("Duplicate SKU identifiers")
        for values in (self.parameters.protected_skus, self.parameters.excluded_skus):
            if len(set(values)) != len(values):
                raise ValueError("Duplicate constraint SKU identifiers")
        return self


class Request(StrictModel):
    message: str = Field(min_length=1, max_length=4000)
    mode: Literal["demo", "llm"] = "demo"
    scenario_id: Literal["factory-demo"] = "factory-demo"
    previous_request_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Limits(StrictModel):
    max_tool_calls: int = Field(default=10, ge=1, le=16)
    max_model_calls: int = Field(default=12, ge=1, le=20)
    max_tool_retries: int = Field(default=1, ge=0, le=2)
    max_replans: int = Field(default=2, ge=0, le=3)
    total_seconds: float = Field(default=60.0, gt=0, le=180)
    tool_seconds: float = Field(default=5.0, gt=0, le=15)


class Citation(StrictModel):
    id: str
    source: str
    text: str
    source_sha256: str
    provenance: Literal["synthetic / demo data"] = "synthetic / demo data"


class ToolCall(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any]


class Event(StrictModel):
    sequence: int
    kind: Literal["state", "intent", "tool", "llm", "retrieval", "final", "error"]
    name: str
    status: str
    elapsed_ms: float = 0
    data: dict[str, Any] = Field(default_factory=dict)


class Response(StrictModel):
    request_id: str
    version: Literal["v2"] = "v2"
    status: Outcome
    mode: Literal["demo", "llm"]
    model: str | None = None
    intent: Intent | None = None
    result: OptimizationResult | None = None
    explanation: str
    facts: dict[str, Any] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    trace: list[Event] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    usage_known: bool = True
    llm_calls: int = 0
    http_attempts: int = 0
    tool_calls: int = 0
    elapsed_ms: float = 0
    snapshot_id: str | None = None
    estimated_cost: dict[str, Any] | None = None
    provenance: Literal["synthetic / demo data"] = "synthetic / demo data"
