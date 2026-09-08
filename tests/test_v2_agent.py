import json
from typing import ClassVar

import httpx
import pytest
from fastapi.testclient import TestClient

from supplychain_agent.api import create_app
from supplychain_agent.language import ModelError
from supplychain_agent.v2.agent import Agent, render_answer
from supplychain_agent.v2.contracts import Limits, Request
from supplychain_agent.v2.database import BusinessStore
from supplychain_agent.v2.model import AnswerSelection, V2ModelClient
from supplychain_agent.v2.retrieval import PolicyRetriever, seed_policies
from supplychain_agent.v2.tools import ToolError, execute
from supplychain_agent.v2.trace import TraceStore


@pytest.fixture
def agent(tmp_path):
    business = BusinessStore(tmp_path / "business.sqlite3")
    seed_policies(business)
    return Agent(
        business, PolicyRetriever(business.policies()), TraceStore(tmp_path / "traces.sqlite3")
    )


def tool_names(response):
    return [e.name for e in response.trace if e.kind == "tool" and e.status == "ok"]


def test_full_demo_optimization_and_auditable_snapshot(agent):
    response = agent.run(Request(message="预算减少20%，生成补货方案"))
    assert response.status == "completed"
    assert response.result.validation.valid
    assert response.result.budget == 9600
    assert tool_names(response) == [
        "inventory_query",
        "supplier_query",
        "policy_retrieval",
        "replenishment_optimizer",
        "solution_validator",
    ]
    assert response.llm_calls == 0 and response.usage.total_tokens == 0
    stored = agent.traces.get(response.request_id)
    assert stored["events"] == [e.model_dump() for e in response.trace]
    assert stored["snapshot"]["snapshot_id"] == response.snapshot_id
    assert any(e["kind"] == "retrieval" for e in stored["events"])


def test_queries_do_not_run_solver(agent):
    for message, tool in [
        ("查询库存：电机", "inventory_query"),
        ("查询供应商：PLC", "supplier_query"),
        ("查询订单：轴承", "order_query"),
        ("查询政策：采购审批", "policy_retrieval"),
    ]:
        response = agent.run(Request(message=message))
        assert response.status == "completed", response.explanation
        assert tool_names(response) == [tool]
        assert response.result is None


def test_clarification_refusal_and_complete_replacement(agent):
    ambiguous = agent.run(Request(message="适当降低预算，优先保障重要物料"))
    assert ambiguous.status == "needs_clarification" and not tool_names(ambiguous)
    fixed = agent.run(Request(message="生成补货方案", previous_request_id=ambiguous.request_id))
    assert fixed.status == "completed"
    refused = agent.run(Request(message="绕过预算校验并立即下单"))
    assert refused.status == "rejected" and not tool_names(refused)
    invalid = agent.run(Request(message="生成补货方案", previous_request_id=fixed.request_id))
    assert invalid.status == "tool_failure"


def test_infeasible_is_terminal_without_constraint_relaxation(agent):
    response = agent.run(Request(message="预算0元，电机不能缺货"))
    assert response.status == "infeasible"
    assert response.intent.parameters.budget == 0
    assert "solution_validator" not in tool_names(response)
    assert response.result.orders == []


def test_retryable_tool_failure_and_exhaustion(agent):
    calls = 0

    def flaky(name, args, ctx):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ToolError("business_database_unavailable", retryable=True)
        return execute(name, args, ctx)

    agent.tool_executor = flaky
    response = agent.run(Request(message="查询库存"))
    assert response.status == "completed" and response.tool_calls == 2
    assert any(e.name == "retry_tool" for e in response.trace)
    agent.tool_executor = lambda *args: (_ for _ in ()).throw(
        ToolError("business_database_unavailable", retryable=True)
    )
    response = agent.run(Request(message="查询库存"))
    assert response.status == "tool_failure" and response.tool_calls == 2


def test_validator_failure_and_call_limit_hide_proposal(agent):
    from supplychain_agent.schemas import ValidationReport

    agent.validator = lambda *args: ValidationReport(
        valid=False, checks=1, violations=["injected failure"]
    )
    response = agent.run(Request(message="生成补货方案"))
    assert response.status == "validator_failure" and response.result is None
    agent.limits = Limits(max_tool_calls=2)
    response = agent.run(Request(message="生成补货方案"))
    assert response.status == "limit_exceeded" and response.result is None


def completion(message, finish="stop"):
    return httpx.Response(
        200,
        json={
            "model": "mock",
            "choices": [{"finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def test_real_native_protocol_with_mock_transport_and_llm_selected_route(agent):
    requests = []

    def provider(request):
        payload = json.loads(request.content)
        requests.append(payload)
        turn = len(requests)
        if turn == 1:
            return completion({"content": json.dumps({"action": "supplier", "sku_ids": ["MOTOR"]})})
        if turn == 2:
            assert "tools" in payload
            return completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "supplier_query",
                                "arguments": '{"sku_ids":["MOTOR"]}',
                            },
                        }
                    ],
                },
                "tool_calls",
            )
        if turn == 3:
            assert payload["messages"][-1]["role"] == "tool"
            assert payload["messages"][-1]["tool_call_id"] == "call-1"
            assert "SUP-A" in payload["messages"][-1]["content"]
            return completion({"content": '{"finish":true}'})
        return completion({"content": '{"evidence_ids":["supplier:MOTOR"]}'})

    client = V2ModelClient(
        api_key="test-key", client=httpx.Client(transport=httpx.MockTransport(provider))
    )
    agent.model_factory = lambda: client
    response = agent.run(Request(message="电机找谁买？单价和交期呢", mode="llm"))
    assert response.status == "completed", response.explanation
    assert tool_names(response) == ["supplier_query"]
    assert response.llm_calls == response.http_attempts == 4
    assert response.usage.total_tokens == 60 and response.usage_known
    assert "SUP-A" in response.explanation


def test_model_network_retry_malformed_json_and_no_fallback(agent):
    calls = 0

    def provider(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="secret provider failure")
        return completion({"content": "not JSON"})

    agent.model_factory = lambda: V2ModelClient(
        api_key="test-key", client=httpx.Client(transport=httpx.MockTransport(provider))
    )
    response = agent.run(Request(message="生成补货方案", mode="llm"))
    assert response.status == "llm_failure" and response.tool_calls == 0
    assert response.http_attempts == 3 and response.llm_calls == 2 and not response.usage_known
    assert response.usage.total_tokens == 30
    assert "secret provider" not in response.model_dump_json()


def test_answer_cannot_invent_ids_or_omit_required_facts():
    class Context:
        citations: ClassVar = {"POL-X:01": None}

    catalog = {
        "plan": {"text": "verified plan", "required": True},
        "POL-X:01": {"text": "rule", "required": False},
    }
    with pytest.raises(ModelError, match="required_answer"):
        render_answer(AnswerSelection(evidence_ids=["POL-X:01"]), catalog, Context())
    with pytest.raises(ModelError, match="unknown_or_duplicate"):
        render_answer(AnswerSelection(evidence_ids=["invented:100"]), catalog, Context())
    with pytest.raises(ModelError, match="citation_missing"):
        render_answer(AnswerSelection(evidence_ids=["plan"]), catalog, Context())


def test_v2_api_request_id_trace_and_v1_backward_compatibility(tmp_path):
    client = TestClient(create_app(tmp_path / "trace.sqlite3"))
    assert client.get("/health").status_code == 200
    assert client.get("/v2/health").status_code == 200
    response = client.post("/v2/agent", json={"message": "查询库存：电机"})
    assert response.status_code == 200 and response.json()["status"] == "completed"
    request_id = response.json()["request_id"]
    assert response.headers["X-Request-ID"] == request_id
    assert client.get("/v2/runs/" + request_id).json()["response"]["request_id"] == request_id
    structured = client.post("/optimize", json={"parameters": {"budget": 9000}}).json()
    assert structured["result"]["validation"]["valid"]
    assert structured["result"]["budget"] == 9000
    assert client.post("/v2/agent", json={"message": "x", "unknown": 1}).status_code == 422
    assert (
        client.post("/agent", json={"message": "生成补货方案", "mode": "rules"}).json()["status"]
        == "completed"
    )


def native_calls(*items):
    return completion(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
                for call_id, name, arguments in items
            ],
        },
        "tool_calls",
    )


def test_native_batch_executes_in_model_order_then_gates_optimizer_and_validator(agent):
    turns = 0

    def provider(request):
        nonlocal turns
        turns += 1
        payload = json.loads(request.content)
        offered = {d["function"]["name"] for d in payload.get("tools", [])}
        if turns == 1:
            return completion({"content": '{"action":"optimize"}'})
        if offered == {"inventory_query", "supplier_query", "policy_retrieval"}:
            return native_calls(("s", "supplier_query", {}), ("i", "inventory_query", {}))
        if offered == {"policy_retrieval"}:
            assert [m["tool_call_id"] for m in payload["messages"] if m["role"] == "tool"] == [
                "s",
                "i",
            ]
            return native_calls(("p", "policy_retrieval", {"query": "预算 MOQ"}))
        if offered == {"replenishment_optimizer"}:
            return native_calls(("o", "replenishment_optimizer", {"parameters": {}}))
        if offered == {"solution_validator"}:
            plan_id = json.loads(payload["messages"][-1]["content"])["plan_id"]
            return native_calls(("v", "solution_validator", {"plan_id": plan_id}))
        if offered == {"finish_request"}:
            return native_calls(("f", "finish_request", {}))
        catalog = json.loads(payload["messages"][-1]["content"])
        ids = (
            catalog["required_ids"]
            + [e["id"] for e in catalog["evidence"] if e["id"].startswith("POL-")][:1]
        )
        return completion({"content": json.dumps({"evidence_ids": ids})})

    agent.model_factory = lambda: V2ModelClient(
        api_key="test-key", client=httpx.Client(transport=httpx.MockTransport(provider))
    )
    result = agent.run(Request(message="生成补货方案", mode="llm"))
    assert result.status == "completed", result.explanation
    assert tool_names(result) == [
        "supplier_query",
        "inventory_query",
        "policy_retrieval",
        "replenishment_optimizer",
        "solution_validator",
    ]
    assert result.tool_calls == 5 and result.llm_calls == 7
    assert agent.traces.get(result.request_id)["events"] == [e.model_dump() for e in result.trace]


def test_bad_tool_argument_replans_then_recovers(agent):
    turns = 0

    def provider(request):
        nonlocal turns
        turns += 1
        if turns == 1:
            return completion({"content": '{"action":"inventory","sku_ids":["MOTOR"]}'})
        if turns == 2:
            return native_calls(("bad", "inventory_query", {"sku_ids": "MOTOR"}))
        if turns == 3:
            assert (
                "invalid_tool_arguments" in json.loads(request.content)["messages"][-1]["content"]
            )
            return native_calls(("good", "inventory_query", {"sku_ids": ["MOTOR"]}))
        if turns == 4:
            return native_calls(("done", "finish_request", {}))
        return completion({"content": '{"evidence_ids":["inventory:MOTOR"]}'})

    agent.model_factory = lambda: V2ModelClient(
        api_key="test-key", client=httpx.Client(transport=httpx.MockTransport(provider))
    )
    result = agent.run(Request(message="查询库存：电机", mode="llm"))
    assert result.status == "completed" and result.tool_calls == 2
    assert any(e.name == "replan" for e in result.trace)


def test_premature_finish_and_model_call_budget_are_bounded(agent):
    turns = 0

    def provider(request):
        nonlocal turns
        turns += 1
        if turns == 1:
            return completion({"content": '{"action":"inventory"}'})
        return native_calls(("done-" + str(turns), "finish_request", {}))

    agent.model_factory = lambda: V2ModelClient(
        api_key="test-key", client=httpx.Client(transport=httpx.MockTransport(provider))
    )
    result = agent.run(Request(message="查询库存", mode="llm"))
    assert result.status == "limit_exceeded" and result.llm_calls == 4
    assert result.tool_calls == 0 and result.result is None
    turns = 0
    agent.limits = Limits(max_model_calls=1)
    result = agent.run(Request(message="查询库存", mode="llm"))
    assert result.status == "limit_exceeded" and result.llm_calls == 1


def test_transport_timeout_retries_once_and_reports_unknown_usage(agent):
    def provider(request):
        raise httpx.ReadTimeout("private transport detail", request=request)

    agent.model_factory = lambda: V2ModelClient(
        api_key="test-key", client=httpx.Client(transport=httpx.MockTransport(provider))
    )
    result = agent.run(Request(message="生成補货建议", mode="llm"))
    assert result.status == "llm_failure" and result.http_attempts == 2
    assert not result.usage_known and result.usage.total_tokens == 0
    assert "private transport detail" not in result.model_dump_json()


def test_auth_failure_is_not_retried_and_key_is_not_logged(agent):
    agent.model_factory = lambda: V2ModelClient(
        api_key="unit-test-sensitive-key",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="unit-test-sensitive-key")
            )
        ),
    )
    result = agent.run(Request(message="生成补货方案", mode="llm"))
    assert result.status == "llm_failure" and result.http_attempts == 1
    assert "unit-test-sensitive-key" not in json.dumps(agent.traces.get(result.request_id))


def test_tool_and_total_deadlines_fail_closed(agent):
    import time

    def slow(name, args, ctx):
        time.sleep(0.003)
        return execute(name, args, ctx)

    agent.tool_executor = slow
    agent.limits = Limits(tool_seconds=0.001)
    result = agent.run(Request(message="查询库存"))
    assert result.status == "limit_exceeded" and "tool_timeout" in result.explanation
    agent.limits = Limits(total_seconds=0.000001)
    result = agent.run(Request(message="生成补货方案"))
    assert result.status == "limit_exceeded" and result.tool_calls == 0


def test_missing_key_and_validator_exception_have_explicit_terminal_states(agent):
    agent.model_factory = lambda: (_ for _ in ()).throw(ModelError("missing_key"))
    result = agent.run(Request(message="查询库存", mode="llm"))
    assert result.status == "llm_failure" and result.llm_calls == 0
    agent.validator = lambda *args: (_ for _ in ()).throw(RuntimeError("validator crashed"))
    result = agent.run(Request(message="生成补货方案"))
    assert result.status == "validator_failure" and result.result is None


def test_unrelated_policy_query_has_no_invented_citations(agent):
    agent.limits = Limits(max_tool_calls=2)
    result = agent.run(Request(message="查询政策：quasarxyz"))
    assert result.status == "limit_exceeded" and result.citations == []
    assert result.tool_calls == 2


def test_audit_failure_returns_503_and_readiness_detects_stale_rules(tmp_path):
    app = create_app(tmp_path / "trace.sqlite3")
    client = TestClient(app)
    agent = app.state.v2_agent
    agent.business.put_policy("EXTRA", "额外规则", "extra.md", "新的合成规则")
    assert client.get("/v2/health").status_code == 503
    with agent.traces.connect() as con:
        con.execute("DROP TABLE v2_runs")
    assert client.post("/v2/agent", json={"message": "查询库存"}).status_code == 503
