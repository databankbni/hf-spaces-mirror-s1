import sqlite3
from pathlib import Path
import json
from typing import Optional, Dict, Any

SCHEMA = '''
CREATE TABLE IF NOT EXISTS competitor_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    competitor_price REAL NOT NULL,
    source TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS ab_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    group_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ab_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    group_name TEXT,
    outcome_json TEXT
);

CREATE TABLE IF NOT EXISTS market_context (
    product_id INTEGER PRIMARY KEY,
    inventory INTEGER,
    unit_cost REAL,
    updated_at TEXT
);
'''


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(SCHEMA)


def insert_competitor_signal(db_path: Path, product_id: int, competitor_price: float, source: Optional[str], timestamp: Optional[str]) -> Dict[str, Any]:
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO competitor_signals(product_id, competitor_price, source, timestamp) VALUES (?, ?, ?, ?)",
            (int(product_id), float(competitor_price), source, timestamp),  # type: ignore[arg-type]
        )
        conn.commit()
        return {"status": "ok", "id": cur.lastrowid}


def get_aggregated_competitor_price(db_path: Path, product_id: int) -> Dict[str, Any]:
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT competitor_price FROM competitor_signals WHERE product_id = ?", (int(product_id),))  # type: ignore[arg-type]
        rows = [r[0] for r in cur.fetchall()]
        if not rows:
            return {"median_competitor_price": None, "count": 0}
        rows.sort()
        mid = rows[len(rows) // 2]
        return {"median_competitor_price": float(mid), "count": len(rows)}


def get_competitor_signals(db_path: Path, product_id: int, limit: int = 100) -> Dict[str, Any]:
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, product_id, competitor_price, source, timestamp FROM competitor_signals WHERE product_id = ? ORDER BY id DESC LIMIT ?", (int(product_id), int(limit)))  # type: ignore[arg-type]
        rows = cur.fetchall()
        cols = ["id", "product_id", "competitor_price", "source", "timestamp"]
        return {"rows": [dict(zip(cols, r)) for r in rows]}


def insert_ab_assignment(db_path: Path, experiment: str, subject_id: str, group: str) -> Dict[str, Any]:
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ab_assignments(experiment, subject_id, group_name) VALUES (?, ?, ?)",
            (experiment, subject_id, group),  # type: ignore[arg-type]
        )
        conn.commit()
        return {"status": "ok", "id": cur.lastrowid}


def insert_ab_outcome(db_path: Path, experiment: str, subject_id: str, group: Optional[str], outcome: dict) -> Dict[str, Any]:  # type: ignore[type-arg]
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ab_outcomes(experiment, subject_id, group_name, outcome_json) VALUES (?, ?, ?, ?)",
            (experiment, subject_id, group, json.dumps(outcome)),  # type: ignore[arg-type]
        )
        conn.commit()
        return {"status": "ok", "id": cur.lastrowid}


def get_ab_summary(db_path: Path, experiment: str) -> Dict[str, Any]:
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT group_name, outcome_json FROM ab_outcomes WHERE experiment = ?", (experiment,))  # type: ignore[arg-type]
        rows = cur.fetchall()
        by_group: Dict[str, list] = {}
        for g, o in rows:
            try:
                obj = json.loads(o) if o else {}
            except Exception:
                obj = {}
            by_group.setdefault(g or "unknown", []).append(obj)

        summary: Dict[str, Any] = {}
        for g, items in by_group.items():
            count = len(items)
            numeric_vals = [i.get("metric") for i in items if isinstance(i.get("metric"), (int, float))]
            mean_metric = sum(numeric_vals) / len(numeric_vals) if numeric_vals else None
            summary[g] = {"count": count, "mean_metric": mean_metric}

        return {"experiment": experiment, "groups": summary}


def get_ab_outcomes(db_path: Path, experiment: str, limit: int = 200) -> Dict[str, Any]:
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, experiment, subject_id, group_name, outcome_json FROM ab_outcomes WHERE experiment = ? ORDER BY id DESC LIMIT ?", (experiment, int(limit)))  # type: ignore[arg-type]
        rows = cur.fetchall()
        cols = ["id", "experiment", "subject_id", "group_name", "outcome_json"]
        return {"rows": [dict(zip(cols, r)) for r in rows]}


def upsert_market_context(db_path: Path, product_id: int, inventory: Optional[int], unit_cost: Optional[float], updated_at: str) -> Dict[str, Any]:
    """Insert or update the live market context (inventory, unit_cost) for a product."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO market_context(product_id, inventory, unit_cost, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                inventory=excluded.inventory,
                unit_cost=excluded.unit_cost,
                updated_at=excluded.updated_at
            """,
            (int(product_id), inventory, unit_cost, updated_at),  # type: ignore[arg-type]
        )
        conn.commit()
    return {"status": "ok", "product_id": product_id}


def get_market_context(db_path: Path, product_id: int) -> Dict[str, Any]:
    """Retrieve the latest market context for a product. Returns empty dict if none."""
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT product_id, inventory, unit_cost, updated_at FROM market_context WHERE product_id = ?",
            (int(product_id),),  # type: ignore[arg-type]
        )
        row = cur.fetchone()
        if not row:
            return {}
        return {"product_id": row[0], "inventory": row[1], "unit_cost": row[2], "updated_at": row[3]}
