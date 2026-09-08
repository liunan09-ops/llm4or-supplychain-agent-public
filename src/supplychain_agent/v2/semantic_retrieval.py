"""Additive dense retrieval and equal-weight Reciprocal Rank Fusion for a tiny corpus.

No evaluation data or expected answers are imported here. The original lexical
retriever remains byte-for-byte intact and is still the default backend.
"""

import hashlib
import json

import faiss

from .embeddings import DEFAULT_MODEL_DIR, BGEEncoder, normalize_embeddings
from .retrieval import PolicyRetriever, chunk_documents

CHUNKING = {
    "method": "existing Markdown ## sections; fixed character windows within each section",
    "max_section_chars": 700,
    "overlap_chars": 0,
    "prepend_document_title": True,
    "shared_with_lexical": True,
}


def validate_query(query, top_k):
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > 1000
        or type(top_k) is not int
        or not 1 <= top_k <= 5
    ):
        raise ValueError("invalid_retrieval_query")


class SemanticPolicyRetriever:
    def __init__(self, documents, encoder):
        self.chunks = chunk_documents(documents)
        if not self.chunks:
            raise ValueError("empty_policy_corpus")
        self.encoder = encoder
        self.embedding = encoder.manifest()["model"]
        matrix = normalize_embeddings(
            encoder.encode([c.text for c in self.chunks]), len(self.chunks), encoder.dimensions
        )
        self.index = faiss.IndexFlatIP(encoder.dimensions)
        self.index.add(matrix)
        self.corpus_sha256 = hashlib.sha256(
            json.dumps(
                [c.model_dump() for c in self.chunks], sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest()

    def search(self, query, top_k=3):
        validate_query(query, top_k)
        vector = normalize_embeddings(
            self.encoder.encode([query], query=True), 1, self.encoder.dimensions
        )
        scores, ids = self.index.search(vector, len(self.chunks))
        ranked = sorted(
            [(float(s), self.chunks[int(i)]) for s, i in zip(scores[0], ids[0]) if i >= 0],
            key=lambda item: (-item[0], item[1].id),
        )
        return {
            "query": query,
            "backend": "semantic",
            "embedding": self.embedding,
            "model_revision": self.encoder.manifest().get("revision"),
            "index": "FAISS IndexFlatIP",
            "similarity": "cosine (L2-normalized inner product)",
            "corpus_sha256": self.corpus_sha256,
            "top_k": top_k,
            "hits": [
                {"score": score, "citation": cite.model_dump()} for score, cite in ranked[:top_k]
            ],
        }

    def manifest(self):
        return {
            "backend": "semantic",
            "embedding": self.embedding,
            "encoder": self.encoder.manifest(),
            "documents": len({c.source for c in self.chunks}),
            "chunks": len(self.chunks),
            "dimensions": self.encoder.dimensions,
            "chunking": CHUNKING,
            "similarity": "cosine (L2-normalized inner product)",
            "index": "FAISS IndexFlatIP",
            "default_top_k": 3,
            "allowed_top_k": [1, 2, 3, 4, 5],
            "score_threshold": None,
            "abstention": "not calibrated; nearest neighbors are not proof of relevance",
            "corpus_sha256": self.corpus_sha256,
            "sources": {c.source: c.source_sha256 for c in self.chunks},
        }


class HybridPolicyRetriever:
    """Fixed RRF: union of top-5 chunks per backend, constant 60, equal weights.

    Candidate scores/ranks are retained for inspection. There is no learned
    fusion, query classification, query-specific weight or synonym dictionary.
    """

    candidate_k = 5
    rrf_constant = 60
    embedding = "tfidf + bge / reciprocal-rank-fusion"

    def __init__(self, lexical, semantic):
        if lexical.corpus_sha256 != semantic.corpus_sha256:
            raise ValueError("hybrid_corpus_mismatch")
        self.lexical, self.semantic = lexical, semantic
        self.chunks = semantic.chunks
        self.corpus_sha256 = semantic.corpus_sha256

    def search(self, query, top_k=3):
        validate_query(query, top_k)
        candidates = {}
        for backend, retriever in (("lexical", self.lexical), ("semantic", self.semantic)):
            for rank, hit in enumerate(retriever.search(query, self.candidate_k)["hits"], 1):
                cid = hit["citation"]["id"]
                entry = candidates.setdefault(
                    cid, {"score": 0.0, "citation": hit["citation"], "components": {}}
                )
                contribution = 1 / (self.rrf_constant + rank)
                entry["score"] += contribution
                entry["components"][backend] = {
                    "rank": rank,
                    "score": hit["score"],
                    "rrf_contribution": contribution,
                }
        ranked = sorted(
            candidates.values(), key=lambda item: (-item["score"], item["citation"]["id"])
        )
        return {
            "query": query,
            "backend": "hybrid",
            "embedding": self.embedding,
            "index": "two FAISS IndexFlatIP indices + RRF",
            "corpus_sha256": self.corpus_sha256,
            "top_k": top_k,
            "rrf_constant": self.rrf_constant,
            "candidate_k_per_backend": self.candidate_k,
            "hits": ranked[:top_k],
        }

    def manifest(self):
        return {
            **self.lexical.manifest(),
            "backend": "hybrid",
            "embedding": self.embedding,
            "dimensions": {
                "lexical": len(self.lexical.vocabulary),
                "semantic": self.semantic.encoder.dimensions,
            },
            "chunking": CHUNKING,
            "fusion": "equal-weight reciprocal rank fusion at chunk level",
            "rrf_constant": self.rrf_constant,
            "candidate_k_per_backend": self.candidate_k,
            "default_top_k": 3,
            "components": {
                "lexical": self.lexical.manifest(),
                "semantic": self.semantic.manifest(),
            },
        }


def create_retriever(documents, backend="lexical", model_dir=None):
    if backend == "lexical":
        return PolicyRetriever(documents)
    if backend not in {"semantic", "hybrid"}:
        raise ValueError("unknown_retrieval_backend")
    encoder = BGEEncoder(model_dir if model_dir is not None else DEFAULT_MODEL_DIR)
    semantic = SemanticPolicyRetriever(documents, encoder)
    if backend == "semantic":
        return semantic
    return HybridPolicyRetriever(PolicyRetriever(documents), semantic)
