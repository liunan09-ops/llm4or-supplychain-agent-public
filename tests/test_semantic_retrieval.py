"""Algorithm/error-path tests use explicit doubles, never as embedding evidence."""

import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

from supplychain_agent.v2.embeddings import (
    MODEL_FILES,
    QUERY_INSTRUCTION,
    BGEEncoder,
    EmbeddingUnavailable,
    normalize_embeddings,
    verify_model_files,
)
from supplychain_agent.v2.evaluation import RetrievalCase
from supplychain_agent.v2.retrieval import PolicyRetriever
from supplychain_agent.v2.semantic_evaluation import score_hits, validate_splits, write_record
from supplychain_agent.v2.semantic_retrieval import (
    HybridPolicyRetriever,
    SemanticPolicyRetriever,
    create_retriever,
)


def document(identifier, content):
    return {
        "document_id": identifier,
        "title": identifier,
        "source": f"policies/{identifier}.md",
        "content": content,
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "provenance": "synthetic / demo data",
    }


@pytest.fixture
def documents():
    return [document("A", "Alpha"), document("B", "Beta"), document("C", "Gamma")]


class StubEncoder:
    dimensions = 2

    def encode(self, texts, *, query=False):
        if query:
            return np.array([[2.0, 0.0] for _ in texts])
        return np.array([{"A": [1, 0], "B": [1, 1], "C": [-1, 0]}[s[0]] for s in texts])

    def manifest(self):
        return {"model": "TEST_DOUBLE_NOT_A_REAL_MODEL", "dimensions": 2}


def test_semantic_cosine_normalization_negative_scores_and_source_hash(documents):
    retriever = SemanticPolicyRetriever(documents, StubEncoder())
    result = retriever.search("question", 5)
    hits = result["hits"]
    assert [h["citation"]["id"] for h in hits] == ["A:01", "B:01", "C:01"]
    assert [h["score"] for h in hits] == pytest.approx([1, 1 / np.sqrt(2), -1])
    assert hits[0]["citation"]["source_sha256"] == documents[0]["sha256"]
    assert retriever.corpus_sha256 == PolicyRetriever(documents).corpus_sha256
    assert retriever.manifest()["sources"] == PolicyRetriever(documents).manifest()["sources"]


def test_semantic_ties_use_citation_ids(documents):
    class TiedEncoder(StubEncoder):
        def encode(self, texts, *, query=False):
            return np.ones((len(texts), 2))

    retriever = SemanticPolicyRetriever(list(reversed(documents)), TiedEncoder())
    assert [h["citation"]["id"] for h in retriever.search("q")["hits"]] == ["A:01", "B:01", "C:01"]


@pytest.mark.parametrize(
    "query,top_k",
    [("", 3), (" ", 3), (None, 3), ("x" * 1001, 3), ("q", 0), ("q", 6), ("q", True), ("q", 1.5)],
)
@pytest.mark.parametrize("backend", ["semantic", "hybrid"])
def test_invalid_search_parameters(documents, query, top_k, backend):
    semantic = SemanticPolicyRetriever(documents, StubEncoder())
    retriever = (
        semantic
        if backend == "semantic"
        else HybridPolicyRetriever(PolicyRetriever(documents), semantic)
    )
    with pytest.raises(ValueError, match="invalid_retrieval_query"):
        retriever.search(query, top_k)


@pytest.mark.parametrize(
    "matrix", [[[0, 0]], [[np.nan, 1]], [[np.inf, 1]], [[1, 2, 3]], [[1, 1], [1, 1]]]
)
def test_invalid_embeddings_fail_closed(matrix):
    with pytest.raises(ValueError, match="invalid_embedding"):
        normalize_embeddings(matrix, 1, 2)


def test_corpus_errors_fail_closed(documents):
    with pytest.raises(ValueError, match="empty_policy_corpus"):
        SemanticPolicyRetriever([], StubEncoder())
    documents[0]["content"] += "tampered"
    with pytest.raises(ValueError, match="policy_hash_mismatch"):
        SemanticPolicyRetriever(documents, StubEncoder())
    documents[0]["provenance"] = "unknown"
    with pytest.raises(ValueError, match="policy_provenance_required"):
        SemanticPolicyRetriever(documents, StubEncoder())


def test_hybrid_rrf_ranks_scores_and_unmatched_lexical_query(documents):
    lexical = PolicyRetriever(documents)
    semantic = SemanticPolicyRetriever(documents, StubEncoder())
    hybrid = HybridPolicyRetriever(lexical, semantic)
    hits = hybrid.search("Beta")["hits"]
    assert hits[0]["citation"]["id"] == "B:01"
    assert hits[0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert hits[0]["components"]["lexical"]["rank"] == 1
    assert hits[0]["components"]["semantic"]["rank"] == 2
    no_lexical = hybrid.search("quasarxyz")["hits"]
    assert no_lexical[0]["citation"]["id"] == "A:01"
    assert no_lexical[0]["score"] == pytest.approx(1 / 61)
    assert all(set(h["components"]) == {"semantic"} for h in no_lexical)
    assert len({h["citation"]["id"] for h in hits}) == len(hits)
    assert hybrid.manifest()["sources"] == lexical.manifest()["sources"]


def test_hybrid_rejects_mismatched_corpora(documents):
    with pytest.raises(ValueError, match="hybrid_corpus_mismatch"):
        HybridPolicyRetriever(
            PolicyRetriever(documents[:2]), SemanticPolicyRetriever(documents, StubEncoder())
        )


def test_factory_default_is_unchanged_lexical_without_model_files(documents, tmp_path):
    retriever = create_retriever(documents, model_dir=tmp_path)
    assert type(retriever) is PolicyRetriever
    assert retriever.search("Beta") == PolicyRetriever(documents).search("Beta")
    with pytest.raises(ValueError, match="unknown_retrieval_backend"):
        create_retriever(documents, "typo", tmp_path)
    for backend in ("semantic", "hybrid"):
        with pytest.raises(EmbeddingUnavailable, match="embedding_file_missing"):
            create_retriever(documents, backend, tmp_path)


def test_model_hash_checked_before_optional_runtime_load(tmp_path):
    name = next(iter(MODEL_FILES))
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"invalid weights")
    with pytest.raises(EmbeddingUnavailable, match="embedding_file_hash_mismatch"):
        BGEEncoder(tmp_path)
    with pytest.raises(EmbeddingUnavailable):
        verify_model_files(tmp_path)


def test_encoder_cls_pooling_query_instruction_and_padding_mask():
    seen = []

    class TokenizerDouble:
        def encode_batch(self, texts):
            seen.extend(texts)
            return [
                SimpleNamespace(ids=[1, 2], attention_mask=[1, 0], type_ids=[0, 0]) for _ in texts
            ]

    class SessionDouble:
        def run(self, outputs, feed):
            assert outputs == ["last_hidden_state"]
            assert set(feed) == {"input_ids", "attention_mask", "token_type_ids"}
            assert feed["input_ids"].dtype == np.int64
            assert (feed["attention_mask"][:, 1] == 0).all()
            # A very different second token detects erroneous mean pooling.
            return [
                np.tile(np.array([[[3.0, 4.0], [900.0, -900.0]]]), (len(feed["input_ids"]), 1, 1))
            ]

    encoder = BGEEncoder.__new__(BGEEncoder)
    encoder.dimensions = 2
    encoder.tokenizer = TokenizerDouble()
    encoder.session = SessionDouble()
    np.testing.assert_allclose(encoder.encode(["document"]), [[0.6, 0.8]])
    np.testing.assert_allclose(encoder.encode(["question"], query=True), [[0.6, 0.8]])
    assert seen == ["document", QUERY_INSTRUCTION + "question"]
    assert encoder.encode(["document"] * 10).shape == (10, 2)
    with pytest.raises(ValueError, match="empty_embedding_input"):
        encoder.encode([])


def test_retrieval_metrics_use_chunk_cutoff_and_document_recall():
    case = RetrievalCase(id="unit", query="unseen unit query", relevant_documents=["A", "B"])
    hits = [{"citation": {"id": cid}} for cid in ("A:01", "A:02", "C:01", "B:01")]
    scored = score_hits(case, hits)
    assert scored == {
        "hit_at_1": True,
        "hit_at_3": True,
        "recall_at_1": 0.5,
        "recall_at_3": 0.5,
        "reciprocal_rank_at_3": 1.0,
    }
    assert score_hits(case, [])["recall_at_3"] == 0


def test_split_validation_and_evidence_never_overwritten(tmp_path):
    a = RetrievalCase(id="a", query="a", relevant_documents=["A"])
    b = RetrievalCase(id="b", query="b", relevant_documents=["B"])
    validate_splits([a], [b], {"A", "B"})
    with pytest.raises(ValueError, match="overlap"):
        validate_splits([a], [a], {"A", "B"})
    with pytest.raises(ValueError, match="unknown_retrieval_label"):
        validate_splits([a], [b], {"A"})
    path = tmp_path / "record.json"
    write_record(path, {"success": False})
    with pytest.raises(FileExistsError):
        write_record(path, {"success": True})
