"""Release default and explicit model-free override; no implicit fallback."""

import os

import pytest
from fastapi.testclient import TestClient

from supplychain_agent.api import create_app
from supplychain_agent.v2.embeddings import DEFAULT_MODEL_DIR, EmbeddingUnavailable


def configure(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_RETRIEVAL_BACKEND", raising=False)
    monkeypatch.setenv("AGENT_BUSINESS_PATH", str(tmp_path / "business.sqlite3"))


@pytest.mark.embedding_integration
@pytest.mark.skipif(
    os.getenv("RUN_EMBEDDING_INTEGRATION") != "1", reason="explicit real model opt-in"
)
def test_release_api_defaults_to_real_hybrid(tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_EMBEDDING_MODEL_DIR", str(DEFAULT_MODEL_DIR.resolve()))
    with TestClient(create_app(tmp_path / "trace.sqlite3")) as client:
        assert client.get("/v2/health").json()["retrieval"]["backend"] == "hybrid"
        result = client.post("/optimize", json={"parameters": {"budget": 9000}}).json()
        assert result["status"] == "completed" and result["result"]["validation"]["valid"]


def test_explicit_lexical_api_does_not_need_model_files(tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_RETRIEVAL_BACKEND", "lexical")
    monkeypatch.setenv("AGENT_EMBEDDING_MODEL_DIR", str(tmp_path / "absent"))
    with TestClient(create_app(tmp_path / "trace.sqlite3")) as client:
        assert (
            client.get("/v2/health").json()["retrieval"]["embedding"] == "tfidf-zh-bigram-word-v1"
        )


def test_default_missing_weights_fail_explicitly_instead_of_falling_back(tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_EMBEDDING_MODEL_DIR", str(tmp_path / "absent"))
    with pytest.raises(EmbeddingUnavailable, match="embedding_file_missing"):
        create_app(tmp_path / "trace.sqlite3")
