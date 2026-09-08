"""Audit a saved SQLite run without querying current business data or calling an LLM.

This rechecks the saved plan and trace, not nondeterministic model generation.
"""

import argparse
import hashlib
import json

from supplychain_agent.schemas import OptimizationResult
from supplychain_agent.v2.contracts import Response
from supplychain_agent.v2.database import Snapshot
from supplychain_agent.v2.tools import ToolContext, ValidateArgs, solution_validator
from supplychain_agent.v2.trace import TraceStore


def replay_record(record):
    response = Response.model_validate(record["response"])
    saved = record["snapshot"]
    if not saved:
        return {
            "request_id": response.request_id,
            "snapshot_available": False,
            "original_status": response.status,
            "plan_valid": None,
        }
    canonical = {
        "config": saved["config"],
        "inventory": saved["inventory"],
        "suppliers": saved["suppliers"],
        "orders": saved["purchase_orders"],
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if digest != saved["snapshot_id"]:
        raise ValueError("saved_snapshot_hash_mismatch")
    if record["events"] != [e.model_dump() for e in response.trace]:
        raise ValueError("saved_trace_mismatch")
    snapshot = Snapshot(
        saved["config"],
        tuple(saved["inventory"]),
        tuple(saved["suppliers"]),
        tuple(saved["purchase_orders"]),
        digest,
    )
    result = {
        "request_id": response.request_id,
        "snapshot_verified": True,
        "trace_verified": True,
        "original_status": response.status,
        "plan_valid": None,
        "llm_replayed": False,
    }
    if response.result and response.result.status in {"optimal", "feasible"}:
        ctx = ToolContext(
            snapshot,
            parameters=response.intent.parameters,
            proposal=OptimizationResult.model_validate(response.result.model_dump()),
            plan_id="replay",
        )
        checked = solution_validator(ValidateArgs(plan_id="replay"), ctx)
        result.update(
            plan_valid=checked["validation"]["valid"], checks=checked["validation"]["checks"]
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-db", required=True)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args()
    record = TraceStore(args.trace_db).get(args.request_id)
    if record is None:
        parser.error("request_id not found")
    print(json.dumps(replay_record(record), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
