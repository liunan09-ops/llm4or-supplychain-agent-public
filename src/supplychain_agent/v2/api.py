"""Additive V2 endpoints; existing V1 request/response contracts are unchanged."""

import os
import sqlite3
from pathlib import Path

from fastapi import HTTPException, Query
from fastapi import Response as HTTPResponse
from pydantic import Field

from ..schemas import PlanParameters, StrictModel
from .agent import Agent
from .contracts import Request, Response
from .database import BusinessStore, DataError
from .retrieval import seed_policies
from .semantic_retrieval import create_retriever
from .trace import TraceStore


class OptimizeRequest(StrictModel):
    parameters: PlanParameters = Field(default_factory=PlanParameters)


def install_routes(app, audit_path, capacity):
    path = Path(audit_path)
    business = BusinessStore(
        os.getenv("AGENT_BUSINESS_PATH", str(path.with_name("business.sqlite3")))
    )
    seed_policies(business)
    retriever = create_retriever(
        business.policies(),
        backend=os.getenv("AGENT_RETRIEVAL_BACKEND", "lexical"),
        model_dir=os.getenv("AGENT_EMBEDDING_MODEL_DIR"),
    )
    traces = TraceStore(path)
    agent = Agent(business, retriever, traces)
    app.state.v2_agent = agent

    def run(request, http_response, parameters=None):
        if not capacity.acquire(blocking=False):
            raise HTTPException(429, "当前计算任务较多，请稍后重试")
        try:
            result = agent.run(request, structured_parameters=parameters)
            http_response.headers["X-Request-ID"] = result.request_id
            return result
        except sqlite3.Error:
            raise HTTPException(503, "审计存储不可用，未确认完成请求") from None
        finally:
            capacity.release()

    @app.post("/v2/agent", response_model=Response, tags=["V2 Tool Agent"])
    def agent_endpoint(request: Request, response: HTTPResponse):
        return run(request, response)

    @app.post("/optimize", response_model=Response, tags=["V2 Tool Agent"])
    def optimize_endpoint(request: OptimizeRequest, response: HTTPResponse):
        return run(Request(message="结构化优化请求", mode="demo"), response, request.parameters)

    @app.get("/v2/runs", tags=["V2 Trace"])
    def runs(limit: int = Query(default=20, ge=1, le=100)):
        return traces.recent(limit)

    @app.get("/v2/runs/{request_id}", tags=["V2 Trace"])
    def trace(request_id: str):
        result = traces.get(request_id)
        if result is None:
            raise HTTPException(404, "运行记录不存在")
        return result

    @app.get("/v2/health", tags=["V2 Tool Agent"])
    def health():
        try:
            snapshot = business.snapshot()
            traces.recent(1)
            # A readiness check distinguishes stale policy data from the loaded index.
            current = {r["source"]: r["sha256"] for r in business.policies()}
            if current != retriever.manifest()["sources"]:
                raise ValueError("policy_index_stale")
            return {
                "status": "ok",
                "snapshot_id": snapshot.snapshot_id,
                "retrieval": retriever.manifest(),
                "data": "synthetic / demo data",
            }
        except (DataError, sqlite3.Error, ValueError, OSError):
            raise HTTPException(503, "数据、规则索引或审计存储未就绪") from None
