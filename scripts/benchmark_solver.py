"""A reproducible solver scaling smoke benchmark, separate from language evaluation.

Uses synthetic independent SKUs. This is not a real manufacturing workload or a
comparison against another solver. Runtime is machine-specific and capped per solve.
"""

import argparse
import json
import platform
import random
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from supplychain_agent.optimizer import solve, validate_solution
from supplychain_agent.schemas import SKU, PlanParameters, Scenario


def make_scenario(size, seed):
    rng = random.Random(seed)
    skus = []
    full_cost = 0
    for i in range(size):
        demand = rng.randint(20, 200)
        stock = rng.randint(0, demand // 2)
        price = rng.randint(5, 300)
        full_cost += (demand - stock) * price
        skus.append(
            SKU(
                sku_id=f"S{i:03d}",
                name=f"合成物料{i}",
                initial_stock=stock,
                demand=demand,
                unit_cost=price,
                holding_cost=price * 0.03,
                shortage_penalty=price * rng.randint(2, 8),
                min_order_qty=rng.randint(5, 40),
                max_order_qty=demand + 50,
                lead_time_days=rng.randint(1, 7),
            )
        )
    return Scenario(
        scenario_id=f"scale-{size}-{seed}",
        name="Synthetic scaling",
        budget=float(full_cost * 0.65),
        horizon_days=7,
        skus=skus,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("reports/solver-scaling.json"))
    args = parser.parse_args()
    records = []
    for size in [5, 20, 50, 100]:
        for seed in [7, 23, 61]:
            scenario = make_scenario(size, seed)
            started = time.perf_counter()
            result = solve(scenario, PlanParameters(), time_limit=5)
            elapsed = time.perf_counter() - started
            checked = (
                validate_solution(scenario, PlanParameters(), result.orders)
                if result.orders
                else None
            )
            records.append(
                {
                    "sku_count": size,
                    "seed": seed,
                    "status": result.status,
                    "elapsed_ms": round(elapsed * 1000, 3),
                    "mip_gap": result.mip_gap,
                    "validated": checked.valid if checked else None,
                    "objective": result.total_cost,
                }
            )
    report = {
        "date": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "scope": "synthetic solver scaling smoke; 3 seeds per size; no business claims",
        "time_limit_seconds": 5,
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise SystemExit("Refusing to overwrite an existing report")
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for size in [5, 20, 50, 100]:
        selected = [r for r in records if r["sku_count"] == size]
        print(
            f"{size} SKUs: {sum(r['status'] == 'optimal' for r in selected)}/3 optimal; "
            f"median {statistics.median(r['elapsed_ms'] for r in selected):.1f} ms; "
            f"validated {sum(r['validated'] is True for r in selected)}/3"
        )


if __name__ == "__main__":
    main()
