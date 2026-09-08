import json

import pytest

from supplychain_agent.v2.agent import Agent
from supplychain_agent.v2.contracts import Request
from supplychain_agent.v2.database import BusinessStore
from supplychain_agent.v2.evaluation import (
    Case,
    assert_disjoint,
    load_cases,
    ratio,
    run_evaluation,
    score,
)
from supplychain_agent.v2.retrieval import PolicyRetriever, seed_policies
from supplychain_agent.v2.trace import TraceStore


def test_dataset_isolation_and_missing_denominator(tmp_path):
    data = {
        "id": "a",
        "category": "query",
        "message": "查询库存",
        "intent": "inventory",
        "status": "completed",
        "tools": ["inventory_query"],
    }
    first, second = tmp_path / "dev.jsonl", tmp_path / "test.jsonl"
    first.write_text(json.dumps(data))
    second.write_text(json.dumps({**data, "id": "b"}))
    with pytest.raises(ValueError, match="overlap"):
        assert_disjoint(first, second)
    second.write_text(json.dumps({**data, "id": "b", "message": "查询库存：电机"}))
    assert_disjoint(first, second)
    first.write_text(json.dumps(data) + "\n" + json.dumps(data))
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(first)
    assert ratio([])["rate"] is None


def test_scoring_checks_business_facts_instead_of_status_alone(tmp_path):
    business = BusinessStore(tmp_path / "db.sqlite3")
    seed_policies(business)
    agent = Agent(
        business, PolicyRetriever(business.policies()), TraceStore(tmp_path / "trace.sqlite3")
    )
    case = Case(
        id="test",
        category="query",
        message="查询库存：电机",
        intent="inventory",
        status="completed",
        tools=["inventory_query"],
        sku_ids=["MOTOR"],
    )
    response = agent.run(Request(message=case.message))
    assert score(case, response, business.snapshot())["end_to_end_success"]
    response.facts["inventory"][0]["on_hand"] += 999
    scored = score(case, response, business.snapshot())
    assert (
        scored["status_correct"]
        and not scored["answer_correct"]
        and not scored["end_to_end_success"]
    )


def test_fault_case_is_successful_when_failure_is_contained(tmp_path):
    data = {
        "id": "fault",
        "category": "failure",
        "message": "查询库存",
        "intent": "inventory",
        "status": "tool_failure",
        "tools": ["inventory_query"],
        "fault": "inventory_unavailable",
    }
    path = tmp_path / "case.jsonl"
    path.write_text(json.dumps(data))
    result = run_evaluation(path, "demo", tmp_path / "result.json")
    assert result["metrics"]["end_to_end_success"]["passed"] == 1
    assert result["metrics"]["constraint_pass"]["rate"] is None
    assert result["metadata"]["source_changed_during_run"] is False
    assert result["metrics"]["llm_calls"] == 0
