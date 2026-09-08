"""No-network checks of verified atomic download and failure recovery."""

import hashlib
import importlib.util
from pathlib import Path

import httpx
import pytest

from supplychain_agent.v2.embeddings import EmbeddingUnavailable


@pytest.fixture
def downloader(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/prepare_embeddings.py"
    spec = importlib.util.spec_from_file_location("prepare_embeddings", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = b"test artifact, not real weights"
    expected = {"test.onnx": {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}}
    monkeypatch.setattr(module, "MODEL_FILES", expected)
    monkeypatch.setattr(module, "verify_model_files", lambda directory: expected)
    return module, payload, expected


def mock_stream(monkeypatch, downloader, content, status=200):
    module, _, _ = downloader
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, content=content))
    )
    monkeypatch.setattr(module.httpx, "stream", client.stream)
    return client


def test_download_pins_revision_verifies_bytes_and_reuses_valid_file(
    tmp_path, monkeypatch, downloader
):
    module, payload, expected = downloader
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=payload)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(module.httpx, "stream", client.stream)
        assert module.prepare(tmp_path) == expected
        assert module.prepare(tmp_path) == expected
    assert len(requests) == 1
    assert module.REVISION in str(requests[0].url)
    assert "authorization" not in requests[0].headers
    assert (tmp_path / "test.onnx").read_bytes() == payload
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("fault", ["same_size_wrong_hash", "oversize", "http_error"])
def test_failed_download_leaves_no_loadable_or_partial_file(
    tmp_path, monkeypatch, downloader, fault
):
    module, payload, _ = downloader
    content = b"x" * len(payload) if fault == "same_size_wrong_hash" else payload + b"x"
    with (
        mock_stream(monkeypatch, downloader, content, 503 if fault == "http_error" else 200),
        pytest.raises((EmbeddingUnavailable, httpx.HTTPError)),
    ):
        module.prepare(tmp_path)
    assert not list(tmp_path.iterdir())


def test_existing_corrupt_file_is_not_silently_replaced(tmp_path, downloader):
    module, _, _ = downloader
    path = tmp_path / "test.onnx"
    path.write_bytes(b"corrupt")
    with pytest.raises(EmbeddingUnavailable, match="existing_embedding_file_corrupt"):
        module.prepare(tmp_path)
    assert path.read_bytes() == b"corrupt"
