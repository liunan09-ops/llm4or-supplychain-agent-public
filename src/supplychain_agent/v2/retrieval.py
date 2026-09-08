"""Small, inspectable lexical RAG: Markdown chunks -> TF-IDF embeddings -> FAISS.

These are sparse lexical embeddings stored densely for a tiny corpus, NOT a
pretrained semantic model. No implicit downloads, hidden fallback or LLM ranking.
"""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import faiss
import numpy as np

from .contracts import Citation


def tokens(text):
    result = []
    for part in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            result.extend(part[i : i + 2] for i in range(len(part) - 1))
            if len(part) == 1:
                result.append(part)
        else:
            result.append(part)
    return result


def seed_policies(store):
    for path in sorted(Path(__file__).with_name("policies").glob("*.md")):
        content = path.read_text(encoding="utf-8")
        title = content.splitlines()[0].removeprefix("# ")
        store.put_policy(title.split()[0], title, "policies/" + path.name, content)


def chunk_documents(documents, max_chars=700):
    chunks = []
    for doc in documents:
        if doc["provenance"] != "synthetic / demo data":
            raise ValueError("policy_provenance_required")
        if hashlib.sha256(doc["content"].encode()).hexdigest() != doc["sha256"]:
            raise ValueError("policy_hash_mismatch")
        sections = re.split(r"\n(?=## )", doc["content"])
        sections = sections[1:] if len(sections) > 1 else sections
        number = 0
        for section in sections:
            for offset in range(0, len(section), max_chars):
                number += 1
                chunks.append(
                    Citation(
                        id=f"{doc['document_id']}:{number:02d}",
                        source=doc["source"],
                        text=doc["title"] + "\n" + section[offset : offset + max_chars].strip(),
                        source_sha256=doc["sha256"],
                    )
                )
    return chunks


class PolicyRetriever:
    embedding = "tfidf-zh-bigram-word-v1"

    def __init__(self, documents):
        self.chunks = chunk_documents(documents)
        if not self.chunks:
            raise ValueError("empty_policy_corpus")
        bags = [Counter(tokens(c.text)) for c in self.chunks]
        self.vocabulary = {term: i for i, term in enumerate(sorted(set().union(*bags)))}
        if not self.vocabulary:
            raise ValueError("empty_policy_vocabulary")
        frequency = np.array(
            [sum(term in bag for bag in bags) for term in self.vocabulary], dtype="float32"
        )
        self.idf = np.log((1 + len(bags)) / (1 + frequency)) + 1
        matrix = self.embed([c.text for c in self.chunks])
        self.index = faiss.IndexFlatIP(matrix.shape[1])
        self.index.add(matrix)
        self.corpus_sha256 = hashlib.sha256(
            json.dumps(
                [c.model_dump() for c in self.chunks], sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest()

    def embed(self, texts):
        matrix = np.zeros((len(texts), len(self.vocabulary)), dtype="float32")
        for row, text in enumerate(texts):
            for token, count in Counter(tokens(text)).items():
                if token in self.vocabulary:
                    col = self.vocabulary[token]
                    matrix[row, col] = (1 + np.log(count)) * self.idf[col]
        faiss.normalize_L2(matrix)
        return matrix

    def search(self, query, top_k=3):
        if not isinstance(query, str) or not query.strip() or not 1 <= top_k <= 5:
            raise ValueError("invalid_retrieval_query")
        vector = self.embed([query])
        # Fetch all for a deterministic citation-id tie break in this tiny corpus.
        scores, ids = self.index.search(vector, len(self.chunks))
        ranked = sorted(
            [
                (float(s), self.chunks[int(i)])
                for s, i in zip(scores[0], ids[0])
                if i >= 0 and s > 0
            ],
            key=lambda item: (-item[0], item[1].id),
        )
        return {
            "query": query,
            "embedding": self.embedding,
            "index": "FAISS IndexFlatIP",
            "corpus_sha256": self.corpus_sha256,
            "hits": [
                {"score": score, "citation": cite.model_dump()} for score, cite in ranked[:top_k]
            ],
        }

    def manifest(self):
        return {
            "embedding": self.embedding,
            "documents": len({c.source for c in self.chunks}),
            "chunks": len(self.chunks),
            "dimensions": len(self.vocabulary),
            "corpus_sha256": self.corpus_sha256,
            "sources": {c.source: c.source_sha256 for c in self.chunks},
        }
