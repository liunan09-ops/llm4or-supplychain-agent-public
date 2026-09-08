"""Deterministic, parameterized business reads from request-consistent SQLite snapshots."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..data import demo_scenario
from ..schemas import SKU, PlanParameters, Scenario


class DataError(RuntimeError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scenario_config (
 id TEXT PRIMARY KEY, budget REAL NOT NULL CHECK(budget>=0),
 horizon_days INTEGER NOT NULL CHECK(horizon_days BETWEEN 1 AND 365));
CREATE TABLE IF NOT EXISTS inventory (
 sku_id TEXT PRIMARY KEY, name TEXT NOT NULL, on_hand INTEGER NOT NULL CHECK(on_hand>=0),
 demand INTEGER NOT NULL CHECK(demand>=0), holding_cost REAL NOT NULL CHECK(holding_cost>=0),
 shortage_penalty REAL NOT NULL CHECK(shortage_penalty>0), critical INTEGER NOT NULL CHECK(critical IN (0,1)));
CREATE TABLE IF NOT EXISTS suppliers (
 supplier_id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('approved','inactive')));
CREATE TABLE IF NOT EXISTS sku_supplier (
 sku_id TEXT PRIMARY KEY REFERENCES inventory(sku_id), supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id),
 unit_cost REAL NOT NULL CHECK(unit_cost>0), min_order_qty INTEGER NOT NULL CHECK(min_order_qty>=0),
 max_order_qty INTEGER NOT NULL CHECK(max_order_qty>=0), lead_time_days INTEGER NOT NULL CHECK(lead_time_days>=0));
CREATE TABLE IF NOT EXISTS purchase_orders (
 order_id TEXT PRIMARY KEY, sku_id TEXT NOT NULL REFERENCES inventory(sku_id),
 supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id), quantity INTEGER NOT NULL CHECK(quantity>0),
 arrival_day INTEGER NOT NULL CHECK(arrival_day>=0), status TEXT NOT NULL CHECK(status IN ('in_transit','received','cancelled')));
CREATE TABLE IF NOT EXISTS policy_documents (
 document_id TEXT PRIMARY KEY, title TEXT NOT NULL, source TEXT NOT NULL,
 content TEXT NOT NULL, sha256 TEXT NOT NULL, provenance TEXT NOT NULL);
"""


@dataclass(frozen=True)
class Snapshot:
    config: dict
    inventories: tuple[dict, ...]
    offers: tuple[dict, ...]
    orders: tuple[dict, ...]
    snapshot_id: str

    @property
    def ids(self):
        return {row["sku_id"] for row in self.inventories}

    def _selected(self, rows, ids):
        if not set(ids).issubset(self.ids):
            raise DataError("unknown_sku")
        return [dict(row) for row in rows if not ids or row["sku_id"] in ids]

    def inventory(self, ids=(), horizon=7):
        result = self._selected(self.inventories, ids)
        for row in result:
            pending = [
                o
                for o in self.orders
                if o["sku_id"] == row["sku_id"] and o["status"] == "in_transit"
            ]
            row["in_transit"] = sum(o["quantity"] for o in pending)
            row["arriving_in_horizon"] = sum(
                o["quantity"] for o in pending if o["arrival_day"] <= horizon
            )
            row["available_in_horizon"] = row["on_hand"] + row["arriving_in_horizon"]
            row["horizon_days"] = horizon
        return result

    def suppliers(self, ids=()):
        return self._selected(self.offers, ids)

    def purchase_orders(self, ids=()):
        return self._selected(self.orders, ids)

    def scenario(self, params=None):
        params = params or PlanParameters()
        horizon = (
            params.horizon_days if params.horizon_days is not None else self.config["horizon_days"]
        )
        offers = {r["sku_id"]: r for r in self.offers}
        if set(offers) != self.ids:
            raise DataError("incomplete_supplier_data")
        rows = []
        for row in self.inventory(horizon=horizon):
            offer = offers[row["sku_id"]]
            rows.append(
                SKU(
                    sku_id=row["sku_id"],
                    name=row["name"],
                    initial_stock=row["available_in_horizon"],
                    demand=row["demand"],
                    holding_cost=row["holding_cost"],
                    shortage_penalty=row["shortage_penalty"],
                    critical=bool(row["critical"]),
                    unit_cost=offer["unit_cost"],
                    min_order_qty=offer["min_order_qty"],
                    max_order_qty=offer["max_order_qty"] if offer["status"] == "approved" else 0,
                    lead_time_days=offer["lead_time_days"],
                )
            )
        return Scenario(
            scenario_id=self.config["id"],
            name="Synthetic V2 factory",
            budget=self.config["budget"],
            horizon_days=horizon,
            skus=rows,
            provenance="synthetic / demo data; snapshot=" + self.snapshot_id,
        )

    def to_dict(self):
        return {
            "config": self.config,
            "inventory": list(self.inventories),
            "suppliers": list(self.offers),
            "purchase_orders": list(self.orders),
            "snapshot_id": self.snapshot_id,
        }


class BusinessStore:
    def __init__(self, path: str | Path, *, seed=True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)
        if seed:
            self.seed_demo()

    @contextmanager
    def connect(self):
        try:
            con = sqlite3.connect(self.path, timeout=2)
        except sqlite3.Error:
            raise DataError("business_database_unavailable") from None
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA foreign_keys=ON")
            with con:
                yield con
        except sqlite3.Error:
            raise DataError("business_database_unavailable") from None
        finally:
            con.close()

    def seed_demo(self):
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT value FROM metadata WHERE key='seed_version'").fetchone():
                return
            original = demo_scenario()
            con.execute(
                "INSERT INTO scenario_config VALUES (?,?,?)",
                (original.scenario_id, original.budget, original.horizon_days),
            )
            con.executemany(
                "INSERT INTO suppliers VALUES (?,?,?)",
                [
                    ("SUP-A", "合成机电供应商A", "approved"),
                    ("SUP-B", "合成传动供应商B", "approved"),
                    ("SUP-C", "合成控制供应商C", "approved"),
                ],
            )
            for sku in original.skus:
                supplier = (
                    "SUP-C"
                    if sku.sku_id == "PLC"
                    else ("SUP-B" if sku.sku_id in {"BELT", "BEARING"} else "SUP-A")
                )
                con.execute(
                    "INSERT INTO inventory VALUES (?,?,?,?,?,?,?)",
                    (
                        sku.sku_id,
                        sku.name,
                        sku.initial_stock,
                        sku.demand,
                        sku.holding_cost,
                        sku.shortage_penalty,
                        int(sku.critical),
                    ),
                )
                con.execute(
                    "INSERT INTO sku_supplier VALUES (?,?,?,?,?,?)",
                    (
                        sku.sku_id,
                        supplier,
                        sku.unit_cost,
                        sku.min_order_qty,
                        sku.max_order_qty,
                        sku.lead_time_days,
                    ),
                )
            con.executemany(
                "INSERT INTO purchase_orders VALUES (?,?,?,?,?,?)",
                [
                    ("DEMO-PO-01", "SENSOR", "SUP-A", 5, 3, "in_transit"),
                    ("DEMO-PO-02", "BELT", "SUP-B", 12, 9, "in_transit"),
                    ("DEMO-PO-03", "MOTOR", "SUP-A", 8, 0, "received"),
                ],
            )
            con.execute("INSERT INTO metadata VALUES ('seed_version','v2-synthetic-1')")

    def snapshot(self, scenario_id="factory-demo"):
        with self.connect() as con:
            con.execute("BEGIN")
            config = con.execute(
                "SELECT * FROM scenario_config WHERE id=?", (scenario_id,)
            ).fetchone()
            if config is None:
                raise DataError("unknown_scenario")
            rows = [dict(r) for r in con.execute("SELECT * FROM inventory ORDER BY sku_id")]
            offers = [
                dict(r)
                for r in con.execute(
                    "SELECT o.*, s.name AS supplier_name, s.status FROM sku_supplier o JOIN suppliers s USING (supplier_id) ORDER BY sku_id"
                )
            ]
            orders = [
                dict(r) for r in con.execute("SELECT * FROM purchase_orders ORDER BY order_id")
            ]
        data = {"config": dict(config), "inventory": rows, "suppliers": offers, "orders": orders}
        sha = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        snapshot = Snapshot(dict(config), tuple(rows), tuple(offers), tuple(orders), sha)
        snapshot.scenario()  # Reject corrupt/out-of-range records before supplying facts to a model.
        return snapshot

    def put_policy(self, document_id, title, source, content):
        sha = hashlib.sha256(content.encode()).hexdigest()
        with self.connect() as con:
            con.execute(
                "INSERT INTO policy_documents VALUES (?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET title=excluded.title, source=excluded.source, content=excluded.content, sha256=excluded.sha256, provenance=excluded.provenance",
                (document_id, title, source, content, sha, "synthetic / demo data"),
            )

    def policies(self):
        with self.connect() as con:
            return [
                dict(r) for r in con.execute("SELECT * FROM policy_documents ORDER BY document_id")
            ]
