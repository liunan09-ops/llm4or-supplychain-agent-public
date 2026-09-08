"""Offline release gate: historical anchors, privacy-only edits and real runtime evidence."""

import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from evaluate_retrieval_backends import diagnose, summarize
from regress_semantic import compare

from supplychain_agent.v2.contracts import Response
from supplychain_agent.v2.database import Snapshot
from supplychain_agent.v2.evaluation import load_cases, score, source_metadata

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "evaluation/release"
BASE = "e10ce8f9766337b8e42f83b2d057722d51a0612d"
SEMANTIC = "f85e98b078061414b95027612f00c5ebf3b3d92c"


def read(path):
    return json.loads(path.read_text())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def historical(name, commit=BASE):
    return subprocess.check_output(["git", "show", f"{commit}:supplychain-agent/{name}"], cwd=ROOT)


def main():
    redactions = read(RELEASE / "privacy_redactions.json")["changes"]
    for item in redactions:
        before = historical(item["path"])
        after = (ROOT / item["path"]).read_bytes()
        assert sha(before) == item["old_sha256"] and sha(after) == item["new_sha256"]
        expected = re.sub(r'/Users/[^"\s]*/supplychain-agent/', "", before.decode())
        if item["path"].endswith(".xml"):
            expected = re.sub(r'hostname="[^"]*"', 'hostname="redacted-local-host"', expected)
        assert after == expected.encode(), "non_privacy_edit:" + item["path"]
    redacted_names = {row["path"] for row in redactions}
    manifest = json.loads(historical("evaluation/final/freeze_manifest.json"))
    for name, expected in manifest["files"].items():
        assert sha(historical(name)) == expected, "historical_manifest:" + name
    protected = read(ROOT / "evaluation/semantic_v2/protected_checkpoint_files.json")
    for name, expected in protected["files"].items():
        assert sha(historical(name)) == expected
        if name not in redacted_names:
            assert sha((ROOT / name).read_bytes()) == expected, "protected:" + name
    # No source, tests, lock, datasets, policy content or E2E traces changed at release.
    frozen_paths = (
        subprocess.check_output(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                BASE,
                "--",
                "src",
                "tests",
                "evals",
                "evaluation/heldout_v2.jsonl",
                "evaluation/dev_v2.jsonl",
                "evaluation/retrieval_dev_v2.jsonl",
                "evaluation/retrieval_heldout_v2.jsonl",
                "evaluation/backend_e2e",
                "evaluation/retrieval_backend_e2e_results.json",
                "pyproject.toml",
                "uv.lock",
            ],
            cwd=ROOT,
        )
        .decode()
        .splitlines()
    )
    for name in frozen_paths:
        assert historical(name) == (ROOT / name).read_bytes(), "frozen_input:" + name
    e2e = read(ROOT / "evaluation/retrieval_backend_e2e_results.json")
    freeze_file = ROOT / "evaluation" / e2e["freeze"]
    assert sha(freeze_file.read_bytes()) == e2e["freeze_sha256"]
    freeze = read(freeze_file)
    assert (
        sha((ROOT / "scripts/evaluate_retrieval_backends.py").read_bytes())
        == freeze["runner_sha256"]
    )
    for name, expected in freeze["source"]["source_files"].items():
        assert sha(historical("src/supplychain_agent/" + name, SEMANTIC)) == expected
    dataset = ROOT / "evaluation/heldout_v2.jsonl"
    assert sha(dataset.read_bytes()) == e2e["dataset_sha256"] == freeze["dataset_sha256"]
    cases = load_cases(dataset)
    rescored = 0
    for backend, run in e2e["runs"].items():
        rows = []
        assert len(run["cases"]) == len(cases) == 24
        for case, ref in zip(cases, run["cases"]):
            path = ROOT / "evaluation" / ref["path"]
            assert sha(path.read_bytes()) == ref["sha256"]
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
        assert summarize(rows) == run["metrics"], "e2e_aggregate:" + backend
    retrieval = RELEASE / "retrieval"
    frozen_retrieval = read(retrieval / "freeze.json")
    assert frozen_retrieval["source"] == source_metadata()
    for split in ("dev", "heldout"):
        assert (
            sha((ROOT / f"evaluation/retrieval_{split}_v2.jsonl").read_bytes())
            == (frozen_retrieval["dataset_sha256"][split])
        )
        for backend in ("lexical", "semantic", "hybrid"):
            old = read(ROOT / f"evaluation/final/retrieval/{split}_{backend}.json")
            new = read(retrieval / f"{split}_{backend}.json")
            for a, b in zip(old["cases"], new["cases"], strict=True):
                for field in (
                    "case",
                    "retrieval",
                    "hit_at_1",
                    "hit_at_3",
                    "recall_at_1",
                    "recall_at_3",
                    "reciprocal_rank_at_3",
                ):
                    assert a[field] == b[field], "retrieval_regression:" + field
            for metric, value in old["metrics"].items():
                if metric != "query_latency_ms":
                    assert new["metrics"][metric] == value
    baseline = ET.fromstring(historical("evaluation/final/pytest-final.xml"))
    current = ET.parse(RELEASE / "pytest-final.xml").getroot()

    def test_ids(root):
        return {(r.attrib["classname"], r.attrib["name"]) for r in root.findall(".//testcase")}

    assert test_ids(baseline) == test_ids(current) and len(test_ids(current)) == 313
    assert not any(current.findall(".//" + tag) for tag in ("failure", "error", "skipped"))
    docker = read(RELEASE / "docker/summary.json")
    assert docker["success"] and docker["restart"] and docker["persisted_sqlite"]
    assert docker["live"]["outcome"] == "completed" and docker["live"]["llm_calls"] > 0
    image = read(RELEASE / "image_audit.json")
    assert image["secret_matches"] == 0 and not image["forbidden_files"]
    final_docker = read(RELEASE / "docker-final/summary.json")
    assert final_docker["image_id"] == image["image_id"]
    assert final_docker["success"] and final_docker["restart"]
    assert final_docker["live"]["outcome"] == "completed"
    assert final_docker["live"]["validation"]["valid"]
    audit = read(RELEASE / "public_audit.json")
    assert audit["public_release_snapshot_safe"]
    assert (RELEASE / "ruff.log").read_text().strip() == "All checks passed!"
    docs = [
        "README.md",
        "DOCKER_RUNTIME_VERIFICATION.md",
        "PUBLIC_REPO_SAFETY_AUDIT.md",
        "CAMPUS_RECRUITING_GAP_AUDIT.md",
        "RESUME_AGENT_V2_EVIDENCE.md",
        "FINAL_FREEZE_DECISION.md",
        "AGENT_V2_FINAL_REPORT.md",
    ]
    for name in docs:
        for target in re.findall(r"\]\(([^)]+)\)", (ROOT / name).read_text()):
            target = target.split("#", 1)[0]
            assert (
                not target
                or target.startswith(("http:", "https:"))
                or (ROOT / target).exists()
                or target == "evaluation/release/verification.json"
            ), "broken_link:" + target
    for marker in (
        "PROJECT_FROZEN_FOR_2027_CAMPUS_RECRUITING",
        "NO_ADDITIONAL_PROJECT_FEATURES_REQUIRED",
    ):
        assert marker in (ROOT / "FINAL_FREEZE_DECISION.md").read_text()
    # Explicit file manifest is generated from the reviewed Git index.
    release_manifest = read(RELEASE / "file_manifest.json")
    for name, expected in release_manifest["files"].items():
        assert sha((ROOT / name).read_bytes()) == expected, "release_file:" + name
    result = {
        "success": True,
        "previous_head": BASE,
        "tests": {"passed": 313, "failed": 0, "errors": 0, "skipped": 0, "added": 0},
        "historical_manifest_files": len(manifest["files"]),
        "privacy_only_files": len(redactions),
        "frozen_source_test_data_files": len(frozen_paths),
        "protected_checkpoint_files": len(protected["files"]),
        "real_llm_responses_rescored": rescored,
        "retrieval_rankings_metrics_unchanged": True,
        "offline_regression": compare(RELEASE / "regression"),
        "docker_runtime": "passed",
        "public_release_snapshot_safe": True,
        "release_files_verified": len(release_manifest["files"]),
        "history_privacy_cleaned": False,
        "additional_project_features_required": False,
    }
    (RELEASE / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
