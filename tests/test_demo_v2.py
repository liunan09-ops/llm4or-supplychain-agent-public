"""Exercise the display wrapper with real Agent execution and isolated demo data."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/demo_v2.py"


def run_demo(output: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"LLM_API_KEY", "DEEPSEEK_API_KEY"}}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(output), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    ("message", "status", "plan_expected"),
    [
        ("先查询库存，再预算9000元，电机不能缺货", "completed", True),
        ("查询库存：电机", "completed", False),
        ("预算0元，电机不能缺货", "infeasible", False),
    ],
)
def test_exports_match_actual_agent_outcome(tmp_path, message, status, plan_expected):
    output = tmp_path / "demo"
    run = run_demo(output, "--message", message)
    assert run.returncode == 0, run.stderr
    response = json.loads((output / "response.json").read_text())
    trace = json.loads((output / "trace.json").read_text())
    assert response["status"] == status
    assert trace["response"] == response
    assert response["llm_calls"] == 0
    assert "offline rules / no LLM" in run.stdout
    assert ("Verified replenishment" in run.stdout) == plan_expected
    if plan_expected:
        assert response["result"]["validation"]["valid"]
        assert response["result"]["purchase_cost"] <= 9000
    else:
        assert "solution_validator" not in run.stdout
    assert "<svg" in (output / "demo.svg").read_text()
    assert "<html>" in (output / "demo.html").read_text()
    assert str(output) not in (output / "demo.svg").read_text()


def test_missing_live_key_is_visible_failure_not_offline_fallback(tmp_path):
    output = tmp_path / "live"
    run = run_demo(output, "--mode", "llm")
    assert run.returncode == 1
    response = json.loads((output / "response.json").read_text())
    assert response["mode"] == "llm" and response["status"] == "llm_failure"
    assert "live LLM" in run.stdout
    assert "Verified replenishment" not in run.stdout


def test_existing_output_is_never_overwritten(tmp_path):
    marker = tmp_path / "response.json"
    marker.write_text("existing evidence")
    run = run_demo(tmp_path)
    assert run.returncode == 2
    assert marker.read_text() == "existing evidence"
    assert not (tmp_path / "runs.sqlite3").exists()
