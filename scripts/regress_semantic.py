"""Rerun existing offline V1/V2 evaluations without touching historical records."""

import argparse
import json
from pathlib import Path

from supplychain_agent.evaluation import run_evaluation as run_v1
from supplychain_agent.v2.evaluation import run_evaluation as run_v2
from supplychain_agent.v2.semantic_evaluation import write_record

ROOT = Path(__file__).resolve().parents[1]
V1_SCORE_FIELDS = (
    "id",
    "parse_status",
    "actual_action",
    "actual_parameters",
    "action_match",
    "strict_intent_match",
    "execution_status",
    "false_execution",
    "safe_execution",
    "solution_status",
    "solution_status_match",
    "validation_valid",
    "independent_validation",
)


def compare(output):
    counts = {}
    for split in ("dev", "test"):
        baseline = json.loads(
            (ROOT / f"reports/v2-regression-rules-{split}/report.json").read_text()
        )
        current = json.loads((output / f"v1_rules_{split}/report.json").read_text())
        old = [{key: row.get(key) for key in V1_SCORE_FIELDS} for row in baseline["cases"]]
        new = [{key: row.get(key) for key in V1_SCORE_FIELDS} for row in current["cases"]]
        assert old == new, f"v1_{split}_regression"
        counts[f"v1_rules_{split}"] = len(new)
    for split, name in (("dev", "dev_demo_final"), ("heldout", "heldout_demo")):
        baseline = json.loads((ROOT / f"evaluation/runs_v2/{name}.json").read_text())
        current = json.loads((output / f"v2_demo_{split}.json").read_text())
        old = [(row["case"], row["score"]) for row in baseline["cases"]]
        new = [(row["case"], row["score"]) for row in current["cases"]]
        assert old == new, f"v2_{split}_regression"
        counts[f"v2_demo_{split}"] = {
            "cases": len(new),
            "end_to_end_success": current["metrics"]["end_to_end_success"],
        }
    return {"all_case_scores_unchanged": True, "rerun_cases": counts, "new_live_llm_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation/semantic_v2/regression")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output directory; existing evidence is never overwritten")
    for split in ("dev", "test"):
        run_v1(
            mode="rules",
            split=split,
            cases_path=ROOT / "evals/cases-v1.1.jsonl",
            output_dir=args.output / f"v1_rules_{split}",
            run_label="semantic-hardening-regression",
        )
    for split in ("dev", "heldout"):
        run_v2(ROOT / f"evaluation/{split}_v2.jsonl", "demo", args.output / f"v2_demo_{split}.json")
    result = compare(args.output)
    write_record(args.output / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
