"""Verify frozen sources, saved scores, JUnit evidence and delivery links offline."""

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from supplychain_agent.v2.contracts import Response
from supplychain_agent.v2.database import Snapshot
from supplychain_agent.v2.evaluation import Case, load_cases, score, source_metadata

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / name).read_text())


def main():
    freeze = read("evaluation/evidence/pre_heldout_freeze.json")
    assert source_metadata()["source_sha256"] == freeze["source_sha256"], "source_changed"
    assert hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest() == freeze["lock_sha256"]
    baseline = read("evaluation/evidence/baseline_manifest.json")
    for name, sha in baseline.items():
        assert (ROOT / name).exists(), "baseline_file_deleted: " + name
        if name.startswith(("tests/", "evals/", "reports/")) or name in {
            "src/supplychain_agent/language.py",
            "src/supplychain_agent/optimizer.py",
            "src/supplychain_agent/schemas.py",
        }:
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, (
                "baseline_changed: " + name
            )
    junit = {
        name: ET.parse(ROOT / f"evaluation/evidence/pytest-{name}.xml").getroot()
        for name in ("baseline", "final")
    }
    names = {
        name: {
            (case.attrib["classname"], case.attrib["name"]) for case in root.findall(".//testcase")
        }
        for name, root in junit.items()
    }
    assert names["baseline"].issubset(names["final"])
    assert not junit["final"].findall(".//failure") and not junit["final"].findall(".//error")
    summary = read("evaluation/evidence/test_summary.json")
    assert len(names["final"]) == summary["final"]["total"]
    assert len(names["final"] - names["baseline"]) == summary["added"]
    checked_cases = 0
    aggregate = read("evaluation/results_v2.json")
    for name, record in aggregate["runs"].items():
        path = ROOT / "evaluation" / record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        run = json.loads(path.read_text())
        if name in {"dev_llm_final", "heldout_llm", "dev_demo_final", "heldout_demo"}:
            assert run["metadata"]["source_sha256"] == freeze["source_sha256"]
            assert run["metadata"]["source_changed_during_run"] is False
            dataset = ROOT / run["dataset"]
            assert hashlib.sha256(dataset.read_bytes()).hexdigest() == run["dataset_sha256"]
            cases = {c.id: c for c in load_cases(dataset)}
            assert len(cases) == len(run["cases"])
            for row in run["cases"]:
                case = Case.model_validate(row["case"])
                assert cases[case.id] == case
                raw = row["snapshot"]
                snapshot = Snapshot(
                    raw["config"],
                    tuple(raw["inventory"]),
                    tuple(raw["suppliers"]),
                    tuple(raw["purchase_orders"]),
                    raw["snapshot_id"],
                )
                assert (
                    score(case, Response.model_validate(row["response"]), snapshot) == row["score"]
                )
                checked_cases += 1
            assert (
                sum(row["score"]["end_to_end_success"] for row in run["cases"])
                == record["metrics"]["end_to_end_success"]["passed"]
            )
    link_errors = []
    documents = [
        "README.md",
        "AGENT_V2_AUDIT.md",
        "AGENT_V2_FINAL_REPORT.md",
        "RESUME_AGENT_V2_EVIDENCE.md",
        "FILES_CHANGED_V2.md",
        "evaluation/report_v2.md",
        "evaluation/PROTOCOL_V2.md",
    ]
    for name in documents:
        path = ROOT / name
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            target = target.split("#", 1)[0]
            if (
                target
                and not target.startswith(("http:", "https:"))
                and not (path.parent / target).exists()
            ):
                link_errors.append({"document": name, "target": target})
    assert not link_errors, link_errors
    configured_keys = [os.environ.get(name, "") for name in ("DEEPSEEK_API_KEY", "LLM_API_KEY")]
    configured_keys = [key.encode() for key in configured_keys if len(key) > 8]
    key_matches = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(
            p.startswith(".") or p == "__pycache__" for p in relative.parts
        ):
            continue
        if any(key in path.read_bytes() for key in configured_keys):
            key_matches.append(str(relative))
    assert not key_matches, "configured_key_detected_in_delivery"
    result = {
        "success": True,
        "frozen_source_matches": True,
        "original_test_ids_preserved": len(names["baseline"]),
        "final_passed_tests": len(names["final"]),
        "saved_agent_cases_rescored": checked_cases,
        "broken_local_document_links": link_errors,
        "configured_key_matches": key_matches,
        "key_scan_performed": bool(configured_keys),
        "scope": "Offline artifact verification; not another LLM evaluation or pytest run",
    }
    (ROOT / "evaluation/evidence/final_gate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
