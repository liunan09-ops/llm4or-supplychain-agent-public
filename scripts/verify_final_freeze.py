"""Re-score final records and check immutable cases, test IDs, files and secrets offline."""

import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from evaluate_retrieval_backends import diagnose, summarize
from regress_semantic import compare

from supplychain_agent.v2.contracts import Response
from supplychain_agent.v2.database import Snapshot
from supplychain_agent.v2.embeddings import file_sha256
from supplychain_agent.v2.evaluation import load_cases, score, source_metadata

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "evaluation/final"
SEMANTIC_COMMIT = "f85e98b078061414b95027612f00c5ebf3b3d92c"
DOCUMENTS = [
    "README.md",
    "AGENT_V2_FINAL_REPORT.md",
    "FINAL_FREEZE_DECISION.md",
    "RESUME_AGENT_V2_EVIDENCE.md",
    "RETRIEVAL_BACKEND_DECISION.md",
    "DOCKER_RUNTIME_VERIFICATION.md",
    "evaluation/retrieval_backend_e2e_report.md",
]


def read(path):
    return json.loads(path.read_text())


def main():
    protected = read(ROOT / "evaluation/semantic_v2/protected_checkpoint_files.json")
    for name, sha in protected["files"].items():
        assert file_sha256(ROOT / name) == sha, "protected_file_changed:" + name
    manifest = read(FINAL / "freeze_manifest.json")
    for name, sha in manifest["files"].items():
        assert file_sha256(ROOT / name) == sha, "final_file_changed:" + name
    e2e = read(ROOT / "evaluation/retrieval_backend_e2e_results.json")
    rescored = 0
    if e2e["status"] == "completed":
        freeze_path = ROOT / "evaluation" / e2e["freeze"]
        assert file_sha256(freeze_path) == e2e["freeze_sha256"]
        freeze = read(freeze_path)
        assert (
            file_sha256(ROOT / "scripts/evaluate_retrieval_backends.py") == freeze["runner_sha256"]
        )
        assert freeze["checkpoint"] == SEMANTIC_COMMIT
        # An intentional default-backend change may follow the experiment.
        # The evaluated implementation is anchored to the committed checkpoint.
        for path, sha in freeze["source"]["source_files"].items():
            data = subprocess.check_output(
                [
                    "git",
                    "show",
                    f"{SEMANTIC_COMMIT}:supplychain-agent/src/supplychain_agent/{path}",
                ],
                cwd=ROOT,
            )
            assert hashlib.sha256(data).hexdigest() == sha
        dataset = ROOT / "evaluation/heldout_v2.jsonl"
        assert file_sha256(dataset) == e2e["dataset_sha256"] == freeze["dataset_sha256"]
        cases = load_cases(dataset)
        for backend, run in e2e["runs"].items():
            rows = []
            assert len(run["cases"]) == len(cases) == 24
            for case, ref in zip(cases, run["cases"]):
                path = ROOT / "evaluation" / ref["path"]
                assert file_sha256(path) == ref["sha256"]
                row = read(path)
                assert row["case"] == case.model_dump() and ref["id"] == case.id
                raw = row["snapshot"]
                snapshot = Snapshot(
                    raw["config"],
                    tuple(raw["inventory"]),
                    tuple(raw["suppliers"]),
                    tuple(raw["purchase_orders"]),
                    raw["snapshot_id"],
                )
                response = Response.model_validate(row["response"])
                assert response.mode == "llm"
                assert score(case, response, snapshot) == row["score"]
                assert diagnose(case, response, row["score"]) == row["diagnostics"]
                rows.append(row)
                rescored += 1
            assert summarize(rows) == run["metrics"], "e2e_aggregate_mismatch:" + backend
            assert run["metrics"]["http_attempts"] > 0
    else:
        assert e2e["status"] == "blocked" and e2e["blocker"]
    comparison = FINAL / "retrieval"
    freeze = read(comparison / "freeze.json")
    assert freeze["source"] == source_metadata()
    for split in ("dev", "heldout"):
        assert (
            file_sha256(ROOT / f"evaluation/retrieval_{split}_v2.jsonl")
            == freeze["dataset_sha256"][split]
        )
        for backend in ("lexical", "semantic", "hybrid"):
            old = read(ROOT / f"evaluation/semantic_v2/comparison/{split}_{backend}.json")
            new = read(comparison / f"{split}_{backend}.json")
            assert len(old["cases"]) == len(new["cases"])
            for a, b in zip(old["cases"], new["cases"]):
                assert a["case"] == b["case"] and a["retrieval"] == b["retrieval"]
                assert all(
                    a[k] == b[k]
                    for k in (
                        "hit_at_1",
                        "hit_at_3",
                        "recall_at_1",
                        "recall_at_3",
                        "reciprocal_rank_at_3",
                    )
                )
            for name, value in old["metrics"].items():
                if name != "query_latency_ms":
                    assert new["metrics"][name] == value
    regression = compare(FINAL / "regression")
    baseline = ET.parse(ROOT / "evaluation/semantic_v2/pytest-final.xml").getroot()
    final = ET.parse(FINAL / "pytest-final.xml").getroot()

    def names(root):
        return {(c.attrib["classname"], c.attrib["name"]) for c in root.findall(".//testcase")}

    assert len(names(baseline)) == 308 and names(baseline).issubset(names(final))
    assert not any(final.findall(".//" + tag) for tag in ("failure", "error", "skipped"))
    tests = {
        "previous": 308,
        "added": len(names(final) - names(baseline)),
        "total": len(names(final)),
        "passed": len(names(final)),
        "failed": 0,
        "skipped": 0,
    }
    assert tests == read(FINAL / "test_summary.json")["tests"]
    for name in DOCUMENTS:
        path = ROOT / name
        assert path.is_file()
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            target = target.split("#", 1)[0]
            assert (
                not target
                or target.startswith(("http:", "https:"))
                or (path.parent / target).exists()
                or (path.parent / target).resolve() == FINAL / "verification.json"
            ), f"broken_link:{name}:{target}"
    assert (
        "PROJECT_FROZEN_FOR_2027_CAMPUS_RECRUITING"
        in (ROOT / "FINAL_FREEZE_DECISION.md").read_text()
    )
    keys = [
        os.getenv(name, "").encode() for name in ("DEEPSEEK_API_KEY", "LLM_API_KEY", "HF_TOKEN")
    ]
    keys = [key for key in keys if len(key) > 8]
    for name in manifest["files"]:
        assert not any(key in (ROOT / name).read_bytes() for key in keys), (
            "configured_secret_found:" + name
        )
    docker = read(FINAL / "docker_runtime.json")
    assert docker["image_build_success"] is None and docker["container_startup_success"] is None
    result = {
        "success": True,
        "tests": tests,
        "protected_files_unchanged": len(protected["files"]),
        "freeze_files_verified": len(manifest["files"]),
        "real_llm_responses_rescored": rescored,
        "retrieval_rankings_and_metrics_unchanged": True,
        "offline_regression": regression,
        "configured_secret_matches": 0,
        "key_scan_performed": bool(keys),
        "docker_runtime": "blocked_unavailable",
        "freeze": "PROJECT_FROZEN_FOR_2027_CAMPUS_RECRUITING",
    }
    (FINAL / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
