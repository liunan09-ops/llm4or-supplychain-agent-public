"""Opt-in REAL model tests. Enable RUN_EMBEDDING_INTEGRATION=1 after preparation.

Explicit enablement with missing weights/dependencies fails, never skips or mocks.
"""

import os
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from supplychain_agent.api import create_app
from supplychain_agent.v2.embeddings import DEFAULT_MODEL_DIR, BGEEncoder
from supplychain_agent.v2.retrieval import PolicyRetriever
from supplychain_agent.v2.semantic_retrieval import SemanticPolicyRetriever

pytestmark = [
    pytest.mark.embedding_integration,
    pytest.mark.skipif(
        os.getenv("RUN_EMBEDDING_INTEGRATION") != "1", reason="explicit local model opt-in required"
    ),
]


@pytest.fixture(scope="module")
def model_dir():
    return Path(os.getenv("AGENT_EMBEDDING_MODEL_DIR", str(DEFAULT_MODEL_DIR))).resolve()


@pytest.fixture(scope="module")
def encoder(model_dir):
    return BGEEncoder(model_dir)


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("embedding integration attempted an external HTTP request")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)


def test_real_onnx_vectors_are_normalized_semantic_and_repeatable(encoder):
    docs = ["采购货物的支出不得超过批准的金额。", "今晚的天气晴朗，适合观察星空。"]
    matrix = encoder.encode(docs)
    assert matrix.shape == (2, 512)
    np.testing.assert_allclose(np.linalg.norm(matrix, axis=1), [1, 1], atol=1e-6)
    query = encoder.encode(["买东西要遵守经费额度吗？"], query=True)
    scores = (matrix @ query.T)[:, 0]
    assert scores[0] > scores[1]
    np.testing.assert_allclose(matrix, encoder.encode(docs), atol=1e-6)
    np.testing.assert_allclose(matrix[:1], encoder.encode(docs[:1]), atol=1e-5)
    assert encoder.manifest()["network_during_inference"] is False
    assert encoder.tokenizer.truncation["max_length"] == 512


@pytest.mark.parametrize("backend", ["semantic", "hybrid"])
def test_real_api_agent_milp_validator_sqlite_and_policy_trace(
    tmp_path, monkeypatch, model_dir, backend
):
    monkeypatch.setenv("AGENT_RETRIEVAL_BACKEND", backend)
    monkeypatch.setenv("AGENT_EMBEDDING_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("AGENT_BUSINESS_PATH", str(tmp_path / "business.sqlite3"))
    app = create_app(tmp_path / "traces.sqlite3")
    with TestClient(app) as client:
        health = client.get("/v2/health").json()
        assert health["status"] == "ok" and health["retrieval"]["backend"] == backend
        retrieval = app.state.v2_agent.retriever
        if backend == "hybrid":
            assert isinstance(retrieval.lexical, PolicyRetriever)
        else:
            assert isinstance(retrieval, SemanticPolicyRetriever)
        policy = client.post("/v2/agent", json={"message": "查询政策：采购预算", "mode": "demo"})
        assert policy.status_code == 200
        assert policy.json()["status"] == "completed"
        assert policy.json()["citations"]
        plan = client.post("/optimize", json={"parameters": {"budget": 9000}})
        assert plan.status_code == 200
        payload = plan.json()
        assert payload["status"] == "completed"
        assert payload["result"]["validation"]["valid"]
        assert payload["result"]["purchase_cost"] <= 9000
        assert payload["llm_calls"] == 0
        stored = client.get("/v2/runs/" + payload["request_id"]).json()
        assert stored["events"] == payload["trace"]
        tool = next(
            e for e in stored["events"] if e["kind"] == "tool" and e["name"] == "policy_retrieval"
        )
        assert tool["data"]["result"]["backend"] == backend
        assert all(c["source_sha256"] for c in payload["citations"])
        infeasible = client.post(
            "/optimize", json={"parameters": {"budget": 0, "protected_skus": ["MOTOR"]}}
        ).json()
        assert infeasible["status"] == "infeasible"
        assert not infeasible["result"]["orders"]
        # Stale-index protection must still apply to both new backends.
        app.state.v2_agent.business.put_policy(
            "EXTRA", "合成新规则", "policies/extra.md", "合成规则"
        )
        assert client.get("/v2/health").status_code == 503
