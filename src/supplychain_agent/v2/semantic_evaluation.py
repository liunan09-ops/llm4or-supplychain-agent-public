"""Frozen lexical / semantic / hybrid comparison on the existing retrieval splits."""

import argparse
import json
import platform
import tempfile
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np

from .database import BusinessStore
from .embeddings import DEFAULT_MODEL_DIR, BGEEncoder, file_sha256
from .evaluation import RetrievalCase, load_cases, ratio, source_metadata
from .retrieval import PolicyRetriever, seed_policies
from .semantic_retrieval import CHUNKING, HybridPolicyRetriever, SemanticPolicyRetriever


def write_record(path, value):
    """Never overwrite an earlier run, including unsuccessful experiments."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def score_hits(case, hits):
    expected = set(case.relevant_documents)
    # Cut off by retrieved CHUNKS first, then de-duplicate document IDs. This is
    # the original V2 metric convention, not document-level top-k retrieval.
    found = list(dict.fromkeys(h["citation"]["id"].split(":")[0] for h in hits[:3]))
    ranks = [i + 1 for i, doc in enumerate(found) if doc in expected]
    return {
        "hit_at_1": bool(found and found[0] in expected),
        "hit_at_3": bool(set(found) & expected),
        "recall_at_1": len(set(found[:1]) & expected) / len(expected),
        "recall_at_3": len(set(found) & expected) / len(expected),
        "reciprocal_rank_at_3": 1 / min(ranks) if ranks else 0,
    }


def evaluate(cases, retriever):
    rows = []
    for case in cases:
        start = time.perf_counter()
        retrieved = retriever.search(case.query, 3)
        elapsed = (time.perf_counter() - start) * 1000
        rows.append(
            {
                "case": case.model_dump(),
                "retrieval": retrieved,
                **score_hits(case, retrieved["hits"]),
                "elapsed_ms": elapsed,
            }
        )
    return {
        "manifest": retriever.manifest(),
        "cases": rows,
        "metrics": {
            "hit_at_1": ratio([r["hit_at_1"] for r in rows]),
            "hit_at_3": ratio([r["hit_at_3"] for r in rows]),
            "recall_at_1": float(np.mean([r["recall_at_1"] for r in rows])),
            "recall_at_3": float(np.mean([r["recall_at_3"] for r in rows])),
            "mrr_at_3": float(np.mean([r["reciprocal_rank_at_3"] for r in rows])),
            "query_latency_ms": {
                "p50": float(np.percentile([r["elapsed_ms"] for r in rows], 50)),
                "p95": float(np.percentile([r["elapsed_ms"] for r in rows], 95)),
                "scope": "sequential warm-index CPU lookup including query encoding; not a load test",
            },
        },
    }


def validate_splits(dev, heldout, document_ids):
    if {r.id for r in dev} & {r.id for r in heldout} or {r.query for r in dev} & {
        r.query for r in heldout
    }:
        raise ValueError("development_heldout_overlap")
    for case in [*dev, *heldout]:
        if not set(case.relevant_documents).issubset(document_ids):
            raise ValueError("unknown_retrieval_label")


def run_comparison(dev, heldout, output, model_dir=DEFAULT_MODEL_DIR):
    output = Path(output)
    datasets = {"dev": Path(dev), "heldout": Path(heldout)}
    initial_source = source_metadata()
    dataset_hashes = {name: file_sha256(path) for name, path in datasets.items()}
    project = Path(__file__).resolve().parents[3]
    lock_sha = file_sha256(project / "uv.lock")
    config_sha = file_sha256(project / "pyproject.toml")
    with tempfile.TemporaryDirectory(prefix="supplychain-semantic-eval-") as directory:
        business = BusinessStore(Path(directory) / "business.sqlite3")
        seed_policies(business)
        documents = business.policies()
        lexical = PolicyRetriever(documents)
        encoder = BGEEncoder(model_dir)
        semantic = SemanticPolicyRetriever(documents, encoder)
        backends = {
            "lexical": lexical,
            "semantic": semantic,
            "hybrid": HybridPolicyRetriever(lexical, semantic),
        }
        freeze = {
            "created_at": datetime.now(UTC).isoformat(),
            "checkpoint": "ad58e78bcd98b06510bbca6f8f803f96c961e21f",
            "scope": "fixed existing synthetic splits; not a new blind holdout",
            "selection": "Chinese small CPU model; fixed equal RRF weights, constant 60, candidates 5; no label-based tuning",
            "source": initial_source,
            "lock_sha256": lock_sha,
            "pyproject_sha256": config_sha,
            "dataset_sha256": dataset_hashes,
            "retrieval_top_k": 3,
            "chunking": CHUNKING,
            "backends": {name: retriever.manifest() for name, retriever in backends.items()},
            "chunk_tokenization": {
                c.id: {
                    "tokens": sum(encoder.tokenizer.encode(c.text).attention_mask),
                    "truncated": bool(encoder.tokenizer.encode(c.text).overflowing),
                }
                for c in semantic.chunks
            },
            "environment": {
                "machine": platform.machine(),
                "platform": platform.platform(),
                "dependencies": {
                    name: version(name)
                    for name in ("onnxruntime", "tokenizers", "faiss-cpu", "numpy")
                },
            },
        }
        # Freeze code, data hashes, model and every ranking parameter BEFORE
        # reading either split's questions/labels in this execution.
        write_record(output / "freeze.json", freeze)
        freeze_sha = file_sha256(output / "freeze.json")
        cases = {name: load_cases(path, RetrievalCase) for name, path in datasets.items()}
        validate_splits(
            cases["dev"], cases["heldout"], {c.id.split(":")[0] for c in lexical.chunks}
        )
        summary = {}
        for split, rows in cases.items():
            summary[split] = {}
            for backend, retriever in backends.items():
                result = {
                    "kind": "independent_retrieval_comparison",
                    "split": split,
                    "backend": backend,
                    "dataset_sha256": dataset_hashes[split],
                    "freeze_sha256": freeze_sha,
                    **evaluate(rows, retriever),
                }
                write_record(output / f"{split}_{backend}.json", result)
                summary[split][backend] = result["metrics"]
                print(
                    json.dumps({"split": split, "backend": backend, **result["metrics"]}),
                    flush=True,
                )
    if (
        source_metadata() != initial_source
        or dataset_hashes != {name: file_sha256(path) for name, path in datasets.items()}
        or file_sha256(project / "uv.lock") != lock_sha
        or file_sha256(project / "pyproject.toml") != config_sha
    ):
        raise ValueError("experiment_inputs_changed_during_run")
    record = {"freeze_sha256": freeze_sha, "inputs_unchanged": True, "metrics": summary}
    write_record(output / "summary.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", type=Path, default=Path("evaluation/retrieval_dev_v2.jsonl"))
    parser.add_argument(
        "--heldout", type=Path, default=Path("evaluation/retrieval_heldout_v2.jsonl")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    args = parser.parse_args()
    run_comparison(args.dev, args.heldout, args.output, args.model_dir)


if __name__ == "__main__":
    main()
