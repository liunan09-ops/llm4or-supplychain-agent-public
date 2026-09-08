import pytest

from supplychain_agent.schemas import PlanParameters
from supplychain_agent.v2.database import BusinessStore, DataError
from supplychain_agent.v2.tools import ToolContext, ToolError, execute


@pytest.fixture
def db(tmp_path):
    return BusinessStore(tmp_path / "business.sqlite3")


def test_seed_is_idempotent_and_snapshot_consistent(db):
    first = db.snapshot()
    db.seed_demo()
    assert first.snapshot_id == db.snapshot().snapshot_id
    with db.connect() as con:
        con.execute("UPDATE inventory SET on_hand=10 WHERE sku_id='MOTOR'")
    assert first.inventory(["MOTOR"])[0]["on_hand"] == 8
    assert db.snapshot().inventory(["MOTOR"])[0]["on_hand"] == 10
    assert first.snapshot_id != db.snapshot().snapshot_id


def test_inventory_in_transit_boundary_and_received_not_counted_twice(db):
    snapshot = db.snapshot()
    belt = snapshot.inventory(["BELT"], horizon=8)[0]
    assert belt["in_transit"] == 12
    assert belt["available_in_horizon"] == 15
    assert snapshot.inventory(["BELT"], horizon=9)[0]["available_in_horizon"] == 27
    assert snapshot.inventory(["MOTOR"])[0]["available_in_horizon"] == 8
    assert snapshot.scenario().skus[-1].sku_id == "SENSOR"
    assert snapshot.scenario().skus[-1].initial_stock == 25


def test_unknown_identifiers_and_sql_injection_fail_closed(db):
    with pytest.raises(DataError, match="unknown_scenario"):
        db.snapshot("' OR 1=1 --")
    with pytest.raises(DataError, match="unknown_sku"):
        db.snapshot().inventory(["' OR 1=1 --"])


def test_schema_rejects_invalid_data_and_missing_supplier(db):
    with pytest.raises(DataError), db.connect() as con:
        con.execute("UPDATE inventory SET on_hand=-1 WHERE sku_id='MOTOR'")
    with db.connect() as con:
        con.execute("DELETE FROM sku_supplier WHERE sku_id='MOTOR'")
    with pytest.raises(DataError, match="incomplete_supplier_data"):
        db.snapshot()


def test_inactive_supplier_disables_procurement(db):
    with db.connect() as con:
        con.execute("UPDATE suppliers SET status='inactive' WHERE supplier_id='SUP-A'")
    assert next(s for s in db.snapshot().scenario().skus if s.sku_id == "MOTOR").max_order_qty == 0


def test_query_tools_return_db_facts_and_cannot_write(db):
    ctx = ToolContext(db.snapshot())
    inv = execute("inventory_query", {"sku_ids": ["MOTOR"]}, ctx)
    sup = execute("supplier_query", {"sku_ids": ["MOTOR"]}, ctx)
    orders = execute("order_query", {"sku_ids": ["BELT"]}, ctx)
    assert inv["rows"][0]["on_hand"] == 8
    assert sup["rows"][0]["unit_cost"] == 220
    assert orders["rows"][0]["quantity"] == 12
    with pytest.raises(ToolError, match="unknown_tool"):
        execute("place_order", {}, ctx)
    with pytest.raises(ToolError, match="invalid_tool_arguments"):
        execute("inventory_query", {"sku_ids": ["MOTOR"], "sql": "DROP TABLE inventory"}, ctx)


class PolicyFixture:
    def search(self, query, top_k):
        return {
            "hits": [
                {
                    "citation": {
                        "id": "POL-TEST#1",
                        "source": "test",
                        "text": "synthetic policy",
                        "source_sha256": "test",
                    }
                }
            ]
        }


def prepared(db, params=None):
    ctx = ToolContext(
        db.snapshot(),
        parameters=params or PlanParameters(),
        allow_optimization=True,
        retriever=PolicyFixture(),
    )
    execute("inventory_query", {}, ctx)
    execute("supplier_query", {}, ctx)
    execute("policy_retrieval", {"query": "预算"}, ctx)
    return ctx


def test_optimization_requires_locked_parameters_and_tool_dependencies(db):
    ctx = ToolContext(db.snapshot())
    with pytest.raises(ToolError, match="not_authorized"):
        execute("replenishment_optimizer", {}, ctx)
    ctx.allow_optimization = True
    with pytest.raises(ToolError, match="query_all"):
        execute("replenishment_optimizer", {}, ctx)
    ctx = prepared(db, PlanParameters(budget=1000))
    with pytest.raises(ToolError, match="locked_intent"):
        execute("replenishment_optimizer", {"parameters": {"budget": 2000}}, ctx)


def test_solver_proposal_and_explicit_independent_validation(db):
    ctx = prepared(db)
    proposal = execute("replenishment_optimizer", {}, ctx)
    assert "orders" not in proposal
    assert not ctx.verified
    result = execute("solution_validator", {"plan_id": proposal["plan_id"]}, ctx)
    assert result["validation"]["valid"]
    assert ctx.verified
    assert result["result"]["purchase_cost"] <= 12000
    with pytest.raises(ToolError, match="already_executed"):
        execute("replenishment_optimizer", {}, ctx)


def test_invalid_plan_id_and_tampered_summary_never_certified(db):
    ctx = prepared(db)
    execute("replenishment_optimizer", {}, ctx)
    with pytest.raises(ToolError, match="unknown_plan_id"):
        execute("solution_validator", {"plan_id": "forged"}, ctx)
    ctx.proposal.total_cost = 0
    with pytest.raises(ToolError, match="validator_failure"):
        execute("solution_validator", {"plan_id": ctx.plan_id}, ctx)
    assert not ctx.verified


def test_infeasible_is_not_a_validated_plan(db):
    params = PlanParameters(protected_skus=["PLC"])
    ctx = prepared(db, params)
    result = execute("replenishment_optimizer", {"parameters": params.model_dump()}, ctx)
    assert result["status"] == "infeasible"
    assert not ctx.verified
    with pytest.raises(ToolError, match="no_feasible"):
        execute("solution_validator", {"plan_id": ctx.plan_id}, ctx)


def test_policy_storage_and_retrieval_failure_are_explicit(db):
    db.put_policy("p", "title", "p.md", "synthetic / demo data")
    assert db.policies()[0]["content"] == "synthetic / demo data"
    with pytest.raises(ToolError, match="retriever_unavailable"):
        execute("policy_retrieval", {"query": "budget"}, ToolContext(db.snapshot()))
