from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, Text
from sqlalchemy import select, insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional, Dict, Any
import json


metadata = MetaData()

competitor_signals = Table(
    "competitor_signals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("product_id", Integer, nullable=False),
    Column("competitor_price", Float, nullable=False),
    Column("source", String, nullable=True),
    Column("timestamp", String, nullable=True),
)

ab_assignments = Table(
    "ab_assignments",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("experiment", String, nullable=False),
    Column("subject_id", String, nullable=False),
    Column("group_name", String, nullable=False),
)

ab_outcomes = Table(
    "ab_outcomes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("experiment", String, nullable=False),
    Column("subject_id", String, nullable=False),
    Column("group_name", String, nullable=True),
    Column("outcome_json", Text, nullable=True),
)


class ORMStore:
    def __init__(self, database_url: str):
        self.engine: Engine = create_engine(database_url, future=True)
        metadata.create_all(self.engine)

    def insert_competitor_signal(self, product_id: int, competitor_price: float, source: Optional[str], timestamp: Optional[str]) -> Dict[str, Any]:
        try:
            with self.engine.begin() as conn:
                res = conn.execute(
                    insert(competitor_signals).values(product_id=int(product_id), competitor_price=float(competitor_price), source=source, timestamp=timestamp)
                )
                return {"status": "ok", "id": int(res.inserted_primary_key[0])}
        except SQLAlchemyError as e:
            return {"status": "error", "error": str(e)}

    def get_aggregated_competitor_price(self, product_id: int) -> Dict[str, Any]:
        with self.engine.connect() as conn:
            stmt = select(competitor_signals.c.competitor_price).where(competitor_signals.c.product_id == int(product_id))
            rows = [r[0] for r in conn.execute(stmt).all()]
            if not rows:
                return {"median_competitor_price": None, "count": 0}
            rows.sort()
            mid = rows[len(rows) // 2]
            return {"median_competitor_price": float(mid), "count": len(rows)}

    def get_competitor_signals(self, product_id: int, limit: int = 100) -> Dict[str, Any]:
        with self.engine.connect() as conn:
            stmt = select(competitor_signals.c.id, competitor_signals.c.product_id, competitor_signals.c.competitor_price, competitor_signals.c.source, competitor_signals.c.timestamp).where(competitor_signals.c.product_id == int(product_id)).order_by(competitor_signals.c.id.desc()).limit(limit)
            rows = conn.execute(stmt).all()
            cols = ["id", "product_id", "competitor_price", "source", "timestamp"]
            return {"rows": [dict(zip(cols, r)) for r in rows]}

    def insert_ab_assignment(self, experiment: str, subject_id: str, group: str) -> Dict[str, Any]:
        try:
            with self.engine.begin() as conn:
                res = conn.execute(
                    insert(ab_assignments).values(experiment=experiment, subject_id=subject_id, group_name=group)
                )
                return {"status": "ok", "id": int(res.inserted_primary_key[0])}
        except SQLAlchemyError as e:
            return {"status": "error", "error": str(e)}

    def insert_ab_outcome(self, experiment: str, subject_id: str, group: Optional[str], outcome: dict) -> Dict[str, Any]:
        try:
            with self.engine.begin() as conn:
                res = conn.execute(
                    insert(ab_outcomes).values(experiment=experiment, subject_id=subject_id, group_name=group, outcome_json=json.dumps(outcome))
                )
                return {"status": "ok", "id": int(res.inserted_primary_key[0])}
        except SQLAlchemyError as e:
            return {"status": "error", "error": str(e)}

    def get_ab_summary(self, experiment: str) -> Dict[str, Any]:
        with self.engine.connect() as conn:
            stmt = select(ab_outcomes.c.group_name, ab_outcomes.c.outcome_json).where(ab_outcomes.c.experiment == experiment)
            rows = conn.execute(stmt).all()
            by_group: dict = {}
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

    def get_ab_outcomes(self, experiment: str, limit: int = 200) -> Dict[str, Any]:
        with self.engine.connect() as conn:
            stmt = select(ab_outcomes.c.id, ab_outcomes.c.experiment, ab_outcomes.c.subject_id, ab_outcomes.c.group_name, ab_outcomes.c.outcome_json).where(ab_outcomes.c.experiment == experiment).order_by(ab_outcomes.c.id.desc()).limit(limit)
            rows = conn.execute(stmt).all()
            cols = ["id", "experiment", "subject_id", "group_name", "outcome_json"]
            return {"rows": [dict(zip(cols, r)) for r in rows]}
