import hashlib

import pytest

from supplychain_agent.v2.database import BusinessStore
from supplychain_agent.v2.retrieval import PolicyRetriever, chunk_documents, seed_policies


@pytest.fixture
def corpus(tmp_path):
    store = BusinessStore(tmp_path / "business.sqlite3")
    seed_policies(store)
    return store


def test_real_document_to_faiss_citation_pipeline(corpus):
    retriever = PolicyRetriever(corpus.policies())
    hits = retriever.search("采购预算是否包括持有成本和缺货惩罚", 3)["hits"]
    assert hits[0]["citation"]["id"].startswith("POL-BUDGET:")
    docs = {d["source"]: d for d in corpus.policies()}
    for hit in hits:
        cite = hit["citation"]
        assert cite["source_sha256"] == docs[cite["source"]]["sha256"]
        assert cite["provenance"] == "synthetic / demo data"
    assert retriever.index.ntotal == len(retriever.chunks)


def test_unknown_words_do_not_fabricate_evidence(corpus):
    retriever = PolicyRetriever(corpus.policies())
    assert retriever.search("quasarxyz")["hits"] == []
    assert retriever.search("MOQ 起订量", 1)["hits"][0]["citation"]["id"].startswith("POL-MOQ:")
    with pytest.raises(ValueError):
        retriever.search(" ")


def test_chunking_keeps_source_and_detects_modified_document(corpus):
    docs = corpus.policies()
    assert all(len(c.text) < 760 for c in chunk_documents(docs))
    docs[0]["content"] += "unaudited change"
    with pytest.raises(ValueError, match="hash_mismatch"):
        chunk_documents(docs)
    docs[0]["sha256"] = hashlib.sha256(docs[0]["content"].encode()).hexdigest()
    assert chunk_documents(docs)


def test_index_reproducible_and_sensitive_to_policy_change(corpus):
    first = PolicyRetriever(corpus.policies())
    second = PolicyRetriever(corpus.policies())
    assert first.manifest() == second.manifest()
    assert first.search("交期超过计划窗口") == second.search("交期超过计划窗口")
    corpus.put_policy("NEW", "额外合成规则", "policies/test.md", "替代物料规则")
    assert PolicyRetriever(corpus.policies()).corpus_sha256 != first.corpus_sha256
