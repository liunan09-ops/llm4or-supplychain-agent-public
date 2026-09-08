"""Local REST service and generated OpenAPI exploration interface."""

import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import Field

from . import __version__
from .audit import AuditStore
from .data import demo_scenario, get_scenario
from .optimizer import resolve_scenario, solve
from .schemas import (
    AgentRequest,
    AgentResponse,
    OptimizationResult,
    PlanParameters,
    Scenario,
    StrictModel,
)
from .service import run_agent


class PlanRequest(StrictModel):
    scenario: Scenario = Field(default_factory=demo_scenario)
    parameters: PlanParameters = Field(default_factory=PlanParameters)


def create_app(audit_path: Path | str | None = None) -> FastAPI:
    app = FastAPI(
        title="SupplyChain Decision Agent · 供应链决策助手",
        version=__version__,
        description=(
            "以合成工厂数据演示自然语言需求解析、MILP 补货优化及独立验证。"
            "`rules` 为可离线运行的受限规则模式；`llm` 为真实模型调用，失败时不会伪装成功。"
            "先查看场景，再调用 POST /agent；需要自定义数据时使用 POST /plan。"
            "本服务默认只在本机运行，不会下单。"
        ),
        swagger_ui_parameters={"defaultModelsExpandDepth": -1, "displayRequestDuration": True},
    )
    store = AuditStore(audit_path or os.getenv("AGENT_AUDIT_PATH", ".runtime/runs.sqlite3"))
    capacity = threading.BoundedSemaphore(4)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @app.get("/health", tags=["运行状态"])
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "data": "synthetic",
            "llm_key_configured": bool(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")),
        }

    @app.get("/scenarios", response_model=list[Scenario], tags=["场景"])
    def scenarios():
        return [demo_scenario()]

    @app.get("/scenarios/{scenario_id}", response_model=Scenario, tags=["场景"])
    def scenario(scenario_id: str):
        try:
            return get_scenario(scenario_id)
        except KeyError:
            raise HTTPException(404, "场景不存在") from None

    @app.post("/agent", response_model=AgentResponse, tags=["自然语言决策"])
    def agent(request: AgentRequest):
        """示例：预算减少20%，生成补货方案。或：计划周期延长到14天，全部物料不能缺货。"""
        if not capacity.acquire(blocking=False):
            raise HTTPException(429, "当前计算任务较多，请稍后重试")
        try:
            return run_agent(request, store=store)
        except KeyError:
            raise HTTPException(404, "场景不存在") from None
        finally:
            capacity.release()

    @app.post("/plan", response_model=OptimizationResult, tags=["结构化优化基准"])
    def plan(request: PlanRequest):
        """直接指定场景与参数，不调用语言模型，可作为正确性对照。"""
        if not capacity.acquire(blocking=False):
            raise HTTPException(429, "当前计算任务较多，请稍后重试")
        try:
            resolve_scenario(request.scenario, request.parameters)
            return solve(request.scenario, request.parameters)
        except ValueError:
            raise HTTPException(422, "物料引用或参数不适用于该场景") from None
        finally:
            capacity.release()

    @app.get("/runs", tags=["本地审计"])
    def runs(limit: int = Query(default=20, ge=1, le=100)):
        return store.recent(limit)

    @app.get("/runs/{request_id}", tags=["本地审计"])
    def run(request_id: str):
        record = store.get(request_id)
        if record is None:
            raise HTTPException(404, "运行记录不存在")
        return record

    from .v2.api import install_routes

    install_routes(app, store.path, capacity)
    return app


app = create_app()
