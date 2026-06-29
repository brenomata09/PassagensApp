from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any
from core.config import settings
from core.models import Route

SCHEMA = """
CREATE TABLE IF NOT EXISTS routes (
    id TEXT PRIMARY KEY,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    trip_type TEXT NOT NULL,
    trip_duration INTEGER,
    cabin_class TEXT DEFAULT 'ECONOMY',
    currency TEXT DEFAULT 'BRL',
    price_ceiling_total REAL,
    price_ceiling_outbound REAL,
    price_ceiling_return REAL,
    is_active INTEGER DEFAULT 1,
    label TEXT,
    split_legs INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES routes(id),
    snapshot_kind TEXT NOT NULL, -- TOTAL, OUTBOUND, RETURN
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    departure_date DATE NOT NULL,
    return_date DATE,
    trip_duration INTEGER,
    price REAL NOT NULL,
    currency TEXT DEFAULT 'BRL',
    data_source TEXT DEFAULT 'fli_dates',
    sweep_batch_id TEXT NOT NULL,
    raw_json TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_snap_route_kind ON price_snapshots(route_id, snapshot_kind, price);
CREATE INDEX IF NOT EXISTS idx_snap_batch ON price_snapshots(sweep_batch_id);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES routes(id),
    snapshot_id INTEGER REFERENCES price_snapshots(id),
    snapshot_kind TEXT,
    alert_type TEXT NOT NULL,
    price REAL NOT NULL,
    previous_price REAL,
    message TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_recent ON alerts(route_id, sent_at);

CREATE TABLE IF NOT EXISTS source_checks (
    id INTEGER PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES routes(id),
    snapshot_id INTEGER REFERENCES price_snapshots(id),
    sweep_batch_id TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    expected_price REAL NOT NULL,
    observed_price REAL,
    difference REAL,
    message TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_source_checks_snapshot ON source_checks(snapshot_id, checked_at);

CREATE TABLE IF NOT EXISTS monthly_ceilings (
    id INTEGER PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES routes(id),
    month TEXT NOT NULL,
    average_price REAL,
    ceiling_price REAL,
    discount_percent REAL NOT NULL DEFAULT 30,
    sources_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    source_names TEXT,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(route_id, month)
);

CREATE TABLE IF NOT EXISTS sweep_log (
    id INTEGER PRIMARY KEY,
    batch_id TEXT UNIQUE NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    routes_total INTEGER DEFAULT 0,
    routes_success INTEGER DEFAULT 0,
    routes_failed INTEGER DEFAULT 0,
    snapshots_saved INTEGER DEFAULT 0,
    alerts_sent INTEGER DEFAULT 0,
    message TEXT
);
"""

@contextmanager
def connect():
    con = sqlite3.connect(settings.db_path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

def init_db() -> None:
    settings.db_path.parent.mkdir(exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)

def upsert_route(route: Route) -> None:
    with connect() as con:
        con.execute("""
            INSERT INTO routes(id, origin, destination, trip_type, trip_duration, cabin_class, currency,
                               price_ceiling_total, price_ceiling_outbound, price_ceiling_return,
                               is_active, label, split_legs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                origin=excluded.origin,
                destination=excluded.destination,
                trip_type=excluded.trip_type,
                trip_duration=excluded.trip_duration,
                cabin_class=excluded.cabin_class,
                currency=excluded.currency,
                price_ceiling_total=excluded.price_ceiling_total,
                price_ceiling_outbound=excluded.price_ceiling_outbound,
                price_ceiling_return=excluded.price_ceiling_return,
                is_active=excluded.is_active,
                label=excluded.label,
                split_legs=excluded.split_legs
        """, (
            route.id, route.origin, route.destination, route.trip_type, route.trip_duration,
            route.cabin_class, route.currency, route.price_ceiling_total,
            route.price_ceiling_outbound, route.price_ceiling_return,
            int(route.is_active), route.label, int(route.split_legs),
        ))

def sync_routes(routes: list[Route]) -> list[Route]:
    init_db()
    for r in routes:
        upsert_route(r)
    return routes

def insert_snapshot(route_id: str, kind: str, item: dict[str, Any], batch_id: str) -> int:
    with connect() as con:
        cur = con.execute("""
            INSERT INTO price_snapshots(route_id, snapshot_kind, origin, destination, departure_date, return_date,
                                        trip_duration, price, currency, data_source, sweep_batch_id, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            route_id, kind, item["origin"], item["destination"],
            item["departure_date"], item.get("return_date"), item.get("trip_duration"),
            float(item["price"]), item.get("currency", "BRL"),
            item.get("source", "google_flights"), batch_id, json.dumps(item, ensure_ascii=False),
        ))
        return int(cur.lastrowid)

def start_sweep(batch_id: str, routes_total: int) -> None:
    with connect() as con:
        con.execute("INSERT INTO sweep_log(batch_id, routes_total) VALUES (?, ?)", (batch_id, routes_total))

def end_sweep(batch_id: str, success: int, failed: int, snapshots: int, alerts: int, message: str = "") -> None:
    with connect() as con:
        con.execute("""
            UPDATE sweep_log
            SET ended_at=CURRENT_TIMESTAMP, routes_success=?, routes_failed=?, snapshots_saved=?, alerts_sent=?, message=?
            WHERE batch_id=?
        """, (success, failed, snapshots, alerts, message, batch_id))

def best_in_batch(route_id: str, batch_id: str, kind: str):
    with connect() as con:
        return con.execute("""
            SELECT * FROM price_snapshots
            WHERE route_id=? AND sweep_batch_id=? AND snapshot_kind=?
            ORDER BY price ASC
            LIMIT 1
        """, (route_id, batch_id, kind)).fetchone()

def previous_best(route_id: str, batch_id: str, kind: str):
    with connect() as con:
        row = con.execute("""
            SELECT MIN(price) AS p FROM price_snapshots
            WHERE route_id=? AND sweep_batch_id != ? AND snapshot_kind=?
        """, (route_id, batch_id, kind)).fetchone()
        return float(row["p"]) if row and row["p"] is not None else None

def previous_batch_best(route_id: str, batch_id: str, kind: str):
    with connect() as con:
        row = con.execute("""
            SELECT p.sweep_batch_id, MIN(p.price) AS p
            FROM price_snapshots p
            JOIN sweep_log s ON s.batch_id = p.sweep_batch_id
            WHERE p.route_id=? AND p.sweep_batch_id != ? AND p.snapshot_kind=? AND s.ended_at IS NOT NULL
            GROUP BY p.sweep_batch_id
            ORDER BY s.ended_at DESC
            LIMIT 1
        """, (route_id, batch_id, kind)).fetchone()
        return float(row["p"]) if row and row["p"] is not None else None

def monthly_best_in_batch(route_id: str, batch_id: str, kind: str = "TOTAL"):
    with connect() as con:
        return con.execute("""
            SELECT *
            FROM (
                SELECT
                    *,
                    CAST(strftime('%m', departure_date) AS INTEGER) AS month_number,
                    ROW_NUMBER() OVER (
                        PARTITION BY strftime('%Y-%m', departure_date)
                        ORDER BY price ASC, trip_duration ASC, departure_date ASC
                    ) AS rn
                FROM price_snapshots
                WHERE route_id=? AND sweep_batch_id=? AND snapshot_kind=?
            )
            WHERE rn=1
            ORDER BY departure_date ASC
        """, (route_id, batch_id, kind)).fetchall()

def top_combinations_in_batch(route_id: str, batch_id: str, limit: int = 3):
    with connect() as con:
        return con.execute("""
            SELECT *
            FROM price_snapshots
            WHERE route_id=? AND sweep_batch_id=? AND snapshot_kind='TOTAL'
            ORDER BY price ASC, departure_date ASC, return_date ASC
            LIMIT ?
        """, (route_id, batch_id, limit)).fetchall()

def monthly_source_prices(batch_id: str):
    with connect() as con:
        return con.execute("""
            SELECT route_id, substr(departure_date, 1, 7) AS month, data_source, MIN(price) AS price
            FROM price_snapshots
            WHERE sweep_batch_id=? AND snapshot_kind='TOTAL'
            GROUP BY route_id, month, data_source
            ORDER BY route_id, month, data_source
        """, (batch_id,)).fetchall()

def upsert_monthly_ceiling(item: dict) -> None:
    with connect() as con:
        con.execute("""
            INSERT INTO monthly_ceilings(route_id, month, average_price, ceiling_price,
                                         discount_percent, sources_count, status, source_names)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(route_id, month) DO UPDATE SET
                average_price=excluded.average_price,
                ceiling_price=excluded.ceiling_price,
                discount_percent=excluded.discount_percent,
                sources_count=excluded.sources_count,
                status=excluded.status,
                source_names=excluded.source_names,
                calculated_at=CURRENT_TIMESTAMP
        """, (
            item["route_id"],
            item["month"],
            item.get("average_price"),
            item.get("ceiling_price"),
            item["discount_percent"],
            item["sources_count"],
            item["status"],
            json.dumps(item.get("source_names", []), ensure_ascii=False),
        ))

def has_recent_alert(route_id: str, hours: int, kind: str | None = None) -> bool:
    with connect() as con:
        if kind:
            row = con.execute("""
                SELECT 1 FROM alerts
                WHERE route_id=? AND snapshot_kind=? AND sent_at >= datetime('now', ?)
                LIMIT 1
            """, (route_id, kind, f"-{hours} hours")).fetchone()
        else:
            row = con.execute("""
                SELECT 1 FROM alerts
                WHERE route_id=? AND sent_at >= datetime('now', ?)
                LIMIT 1
            """, (route_id, f"-{hours} hours")).fetchone()
        return row is not None

def has_recent_alert_type(route_id: str, alert_type: str, hours: int, kind: str | None = None) -> bool:
    with connect() as con:
        if kind:
            row = con.execute("""
                SELECT 1 FROM alerts
                WHERE route_id=? AND alert_type=? AND snapshot_kind=? AND sent_at >= datetime('now', ?)
                LIMIT 1
            """, (route_id, alert_type, kind, f"-{hours} hours")).fetchone()
        else:
            row = con.execute("""
                SELECT 1 FROM alerts
                WHERE route_id=? AND alert_type=? AND sent_at >= datetime('now', ?)
                LIMIT 1
            """, (route_id, alert_type, f"-{hours} hours")).fetchone()
        return row is not None

def record_alert(route_id: str, snapshot_id: int, kind: str, alert_type: str, price: float, previous_price, message: str) -> None:
    with connect() as con:
        con.execute("""
            INSERT INTO alerts(route_id, snapshot_id, snapshot_kind, alert_type, price, previous_price, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (route_id, snapshot_id, kind, alert_type, price, previous_price, message))

def record_source_check(
    route_id: str,
    snapshot_id: int,
    batch_id: str,
    source: str,
    status: str,
    expected_price: float,
    observed_price,
    difference,
    message: str,
) -> None:
    with connect() as con:
        con.execute("""
            INSERT INTO source_checks(route_id, snapshot_id, sweep_batch_id, source, status,
                                      expected_price, observed_price, difference, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            route_id, snapshot_id, batch_id, source, status,
            expected_price, observed_price, difference, message,
        ))

def df(sql: str, params: tuple = ()):
    import pandas as pd
    with connect() as con:
        return pd.read_sql_query(sql, con, params=params)
