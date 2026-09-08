from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from supplychain_agent.api import create_app
from supplychain_agent.audit import AuditStore
from supplychain_agent.data import demo_scenario
from supplychain_agent.language import ModelError
from supplychain_agent.schemas import AgentRequest, ParsedIntent, PlanParameters, TokenUsage
from supplychain_agent.service import run_agent


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "audit.sqlite3")) as client:
        yield client


def test_health_and_scenario_do_not_expose_credentials(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-test-value-never-return")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["llm_key_configured"] is True
    assert "private-test-value" not in response.text
    assert client.get("/scenarios").json()[0]["provenance"].startswith("synthetic")
    assert client.get("/scenarios/missing").status_code == 404


def test_structured_baseline_and_schema_rejection(client):
    response = client.post("/plan", json={"scenario": demo_scenario().model_dump()})
    assert response.status_code == 200
    assert response.json()["status"] == "optimal"
    assert response.json()["validation"]["valid"]
    assert client.post("/plan", json={"parameters": {"budget": -1}}).status_code == 422
    assert client.post("/plan", json={"parameters": {"budget": True}}).status_code == 422
    assert client.post("/plan", json={"parameters": {"execute_purchase": True}}).status_code == 422
    assert (
        client.post("/plan", json={"parameters": {"protected_skus": ["UNKNOWN"]}}).status_code
        == 422
    )


def test_agent_response_and_audit_roundtrip(client):
    body = {"message": "按默认条件生成补货方案", "mode": "rules"}
    response = client.post("/agent", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["model"] is None
    assert data["usage"]["total_tokens"] == 0
    assert data["result"]["validation"]["valid"]
    stored = client.get(f"/runs/{data['request_id']}").json()
    assert stored["response"] == data
    assert stored["request"]["message"] == body["message"]
    assert client.get("/runs").json()[0]["request_id"] == data["request_id"]
    assert client.get("/runs/not-found").status_code == 404
    assert client.get("/runs", params={"limit": 1000}).status_code == 422


def test_unknown_scenario_and_oversized_request(client):
    assert (
        client.post(
            "/agent", json={"message": "生成补货方案", "scenario_id": "unknown"}
        ).status_code
        == 404
    )
    assert client.post("/agent", json={"message": "x" * 4001}).status_code == 422


def test_explicit_constraint_changes_restore_feasibility(client):
    first = client.post("/plan", json={"parameters": {"protected_skus": ["PLC"]}}).json()
    assert first["status"] == "infeasible"
    second = client.post(
        "/plan",
        json={
            "parameters": {
                "budget": 15000,
                "horizon_days": 14,
                "protected_skus": [s.sku_id for s in demo_scenario().skus],
            }
        },
    ).json()
    assert second["status"] == "optimal"
    assert second["purchase_cost"] == 14385
    assert second["fill_rate"] == 1


def test_compound_restrictions_are_applied_together(client):
    response = client.post(
        "/agent",
        json={
            "message": "伺服电机不能缺货，同时排除伺服电机",
            "mode": "rules",
        },
    ).json()
    assert response["status"] == "infeasible"
    assert response["intent"]["parameters"]["protected_skus"] == ["MOTOR"]
    assert response["intent"]["parameters"]["excluded_skus"] == ["MOTOR"]


def test_model_error_fails_closed_without_fallback_or_leak():
    class BrokenClient:
        model = "test-provider"

        def parse(self, message, scenario):
            raise ModelError("sensitive-provider-body")

    response = run_agent(
        AgentRequest(message="生成补货方案", mode="llm"), model_client=BrokenClient()
    )
    assert response.status == "error"
    assert response.result is None
    assert response.mode == "llm"
    assert "sensitive-provider-body" not in response.model_dump_json()
    assert all(step.name != "optimize_replenishment" for step in response.trace)


def test_model_clarification_never_calls_solver(monkeypatch):
    class ClarifyClient:
        model = "test-provider"

        def parse(self, message, scenario):
            return ParsedIntent(action="clarify", questions=["预算具体是多少？"]), TokenUsage(
                total_tokens=10
            )

    def forbidden(*args, **kwargs):
        pytest.fail("Solver must not run on an unresolved request")

    monkeypatch.setattr("supplychain_agent.service.solve", forbidden)
    response = run_agent(
        AgentRequest(message="预算少一些", mode="llm"), model_client=ClarifyClient()
    )
    assert response.status == "needs_clarification"
    assert response.usage.total_tokens == 10


def test_model_guard_is_not_presented_as_model_inference(monkeypatch):
    from supplychain_agent.language import ModelClient

    client = ModelClient(api_key="dummy")
    response = run_agent(
        AgentRequest(message="整体需求满足率至少90%", mode="llm"), model_client=client
    )
    assert response.status == "needs_clarification"
    assert response.local_guarded
    assert response.provider_calls == 0
    assert response.usage_known
    assert response.usage.total_tokens == 0
    assert "未调用模型" in response.trace[1].detail


def test_tampered_summary_blocks_recommendation(monkeypatch):
    from supplychain_agent.optimizer import solve

    valid = solve(demo_scenario(), PlanParameters())
    assert valid.status == "optimal"
    valid.total_cost = 0
    monkeypatch.setattr("supplychain_agent.service.solve", lambda *args, **kwargs: valid)
    response = run_agent(AgentRequest(message="按默认条件生成补货方案"))
    assert response.status == "error"
    assert response.result.orders == []
    assert not response.result.validation.valid


def test_audit_parallel_writes_and_parameterized_queries(tmp_path):
    store = AuditStore(tmp_path / "runs.sqlite3")
    request = AgentRequest(message="按默认条件生成补货方案")
    base = run_agent(request)

    def save(i):
        response = base.model_copy(update={"request_id": f"run-{i}"})
        store.save(request, response)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, range(16)))
    assert len(store.recent(100)) == 16
    assert store.get("' OR 1=1 --") is None


def test_audit_closes_each_connection(tmp_path, monkeypatch):
    import sqlite3

    original_connect = sqlite3.connect
    opened = []

    class RecordingConnection(sqlite3.Connection):
        was_closed = False

        def close(self):
            self.was_closed = True
            return super().close()

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=RecordingConnection)
        opened.append(connection)
        return connection

    monkeypatch.setattr("supplychain_agent.audit.sqlite3.connect", connect)
    store = AuditStore(tmp_path / "closed.sqlite3")
    store.recent()
    store.get("missing")
    assert len(opened) == 3
    assert all(con.was_closed for con in opened)
