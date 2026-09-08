"""Offline hardening evidence check; keeps the Core freeze and reports immutable."""

import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from regress_semantic import compare

from supplychain_agent.v2.contracts import Response
from supplychain_agent.v2.database import Snapshot
from supplychain_agent.v2.embeddings import file_sha256
from supplychain_agent.v2.evaluation import Case, RetrievalCase, load_cases, score, source_metadata
from supplychain_agent.v2.semantic_evaluation import score_hits

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evaluation/semantic_v2"


def read(path):
    return json.loads(path.read_text())


def main():
    protected = read(EVIDENCE / "protected_checkpoint_files.json")
    for name, sha in protected["files"].items():
        assert file_sha256(ROOT / name) == sha, "checkpoint_file_changed:" + name
    comparison = EVIDENCE / "comparison"
    freeze = read(comparison / "freeze.json")
    assert source_metadata() == freeze["source"], "experiment_source_changed"
    assert file_sha256(ROOT / "uv.lock") == freeze["lock_sha256"]
    assert file_sha256(ROOT / "pyproject.toml") == freeze["pyproject_sha256"]
    summary = read(comparison / "summary.json")
    assert summary["inputs_unchanged"]
    assert summary["freeze_sha256"] == file_sha256(comparison / "freeze.json")
    retrieval_cases = 0
    for split in ("dev", "heldout"):
        dataset = ROOT / f"evaluation/retrieval_{split}_v2.jsonl"
        assert file_sha256(dataset) == freeze["dataset_sha256"][split]
        cases = load_cases(dataset, RetrievalCase)
        for backend in ("lexical", "semantic", "hybrid"):
            run = read(comparison / f"{split}_{backend}.json")
            assert run["freeze_sha256"] == summary["freeze_sha256"]
            assert run["dataset_sha256"] == file_sha256(dataset)
            assert run["manifest"] == freeze["backends"][backend]
            assert run["metrics"] == summary["metrics"][split][backend]
            assert [r["case"] for r in run["cases"]] == [c.model_dump() for c in cases]
            for case, row in zip(cases, run["cases"]):
                rescored = score_hits(case, row["retrieval"]["hits"])
                assert all(row[key] == value for key, value in rescored.items())
            rows = run["cases"]
            for metric in ("hit_at_1", "hit_at_3"):
                assert run["metrics"][metric] == {
                    "passed": sum(r[metric] for r in rows),
                    "total": len(rows),
                    "rate": sum(r[metric] for r in rows) / len(rows),
                }
            for metric in ("recall_at_1", "recall_at_3", "mrr_at_3"):
                field = "reciprocal_rank_at_3" if metric == "mrr_at_3" else metric
                assert abs(run["metrics"][metric] - sum(r[field] for r in rows) / len(rows)) < 1e-12
            retrieval_cases += len(rows)
        old = read(ROOT / f"evaluation/runs_v2/retrieval_{split}.json")
        current = read(comparison / f"{split}_lexical.json")
        assert len(old["cases"]) == len(current["cases"])
        for a, b in zip(old["cases"], current["cases"]):
            assert a["retrieval"] == b["retrieval"], "lexical_ranking_changed"
            for key in ("case", "hit_at_1", "hit_at_3", "recall_at_3", "reciprocal_rank_at_3"):
                assert a[key] == b[key], "lexical_score_changed"
    junit = {
        name: ET.parse(EVIDENCE / f"pytest-{name}.xml").getroot() for name in ("baseline", "final")
    }
    identifiers = {
        name: {(c.attrib["classname"], c.attrib["name"]) for c in root.findall(".//testcase")}
        for name, root in junit.items()
    }
    assert len(identifiers["baseline"]) == 269
    assert identifiers["baseline"].issubset(identifiers["final"])
    assert not any(junit["final"].findall(".//" + tag) for tag in ("failure", "error", "skipped"))
    assert sum("test_semantic_integration" in name for name, _ in identifiers["final"]) == 3
    regression = compare(EVIDENCE / "regression")
    assert regression == read(EVIDENCE / "regression/summary.json")
    # Re-score historical saved responses only: these are NOT fresh LLM calls.
    saved_agent_cases = 0
    for name in ("dev_llm_final", "heldout_llm", "dev_demo_final", "heldout_demo"):
        run = read(ROOT / f"evaluation/runs_v2/{name}.json")
        for row in run["cases"]:
            raw = row["snapshot"]
            snapshot = Snapshot(
                raw["config"],
                tuple(raw["inventory"]),
                tuple(raw["suppliers"]),
                tuple(raw["purchase_orders"]),
                raw["snapshot_id"],
            )
            assert (
                score(
                    Case.model_validate(row["case"]),
                    Response.model_validate(row["response"]),
                    snapshot,
                )
                == row["score"]
            )
            saved_agent_cases += 1
    documents = [
        ROOT / "README.md",
        ROOT / "RESUME_AGENT_V2_EVIDENCE.md",
        ROOT / "SEMANTIC_RETRIEVAL_REPORT.md",
        EVIDENCE / "PROTOCOL.md",
    ]
    for path in documents:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            target = target.split("#", 1)[0]
            assert (
                not target
                or target.startswith(("http:", "https:"))
                or (path.parent / target).resolve() == EVIDENCE / "verification.json"
                or (path.parent / target).exists()
            ), f"broken_link:{path.name}:{target}"
    configured = [
        os.getenv(key, "").encode() for key in ("DEEPSEEK_API_KEY", "LLM_API_KEY", "HF_TOKEN")
    ]
    configured = [key for key in configured if len(key) > 8]
    checked_files = []
    for top in (ROOT / "src", ROOT / "tests", ROOT / "scripts", EVIDENCE):
        checked_files.extend(
            p for p in top.rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    checked_files.extend(documents)
    assert not any(key in path.read_bytes() for path in checked_files for key in configured), (
        "configured_secret_in_evidence"
    )
    result = {
        "success": True,
        "protected_checkpoint_files_unchanged": len(protected["files"]),
        "original_test_ids_preserved": len(identifiers["baseline"]),
        "final_passed_tests": len(identifiers["final"]),
        "added_tests": len(identifiers["final"] - identifiers["baseline"]),
        "real_embedding_integration_tests_passed": 3,
        "failure_error_skip": 0,
        "retrieval_rows_rescored": retrieval_cases,
        "lexical_rankings_and_scores_identical_to_core": True,
        "frozen_datasets_and_source_match": True,
        "regression": regression,
        "historical_saved_agent_cases_rescored": saved_agent_cases,
        "new_live_llm_evaluation": False,
        "configured_secret_matches": 0,
        "configured_secret_scan_performed": bool(configured),
    }
    (EVIDENCE / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
