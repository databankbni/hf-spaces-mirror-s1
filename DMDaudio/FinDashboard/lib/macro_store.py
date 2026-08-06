"""Shared storage layer for the macro-economics data pipeline.

Every macro source — Geostat PxWeb (GDP, labour, FDI, CPI), Geostat external-
trade API, Geostat tourism, and the National Bank of Georgia (remittances,
balance of payments, policy rate) — lands in **one tidy long table**,
``macro_series``, plus a self-describing catalog, ``macro_dataset``. The macro
page reads a chart's data with a single ``WHERE dataset=? AND period_type=?``
slice; the catalog tells it each dataset's title, unit, source and coverage.

Design choices:
  * **One long table, not one-per-indicator.** ~30 heterogeneous datasets with
    different breakdowns (activity / country / product / COICOP group …) would
    otherwise mean 30 bespoke tables. A single ``(dataset, period, breakdown,
    sub_breakdown) → value`` grain keeps the schema stable as datasets are
    added, and the row count (tens of thousands) is trivial for SQLite.
  * **Idempotent UPSERT** on the primary key — re-running a source overwrites
    its rows in place; a failed fetch leaves prior rows untouched (callers guard
    with their own try/except, mirroring ``import_gdp.py``).
  * **Survives ``rebuild_db.py``** — these tables are populated by the macro
    importers (run as a best-effort rebuild step) and are not in any DROP list,
    so an offline rebuild keeps the last good macro snapshot.

This module is pure DB plumbing (stdlib ``sqlite3`` only) — no network, no
Streamlit. Sources build :class:`SeriesRow` objects and hand them to
:func:`upsert_series`; :func:`refresh_catalog` then recomputes ``macro_dataset``
coverage from whatever is present.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

MACRO_SERIES_TABLE = "macro_series"
MACRO_DATASET_TABLE = "macro_dataset"

DDL = f"""
CREATE TABLE IF NOT EXISTS {MACRO_SERIES_TABLE} (
  dataset       TEXT NOT NULL,
  period        TEXT NOT NULL,          -- 'YYYY' | 'YYYY-Qn' | 'YYYY-MM'
  period_type   TEXT NOT NULL,          -- 'annual' | 'quarter' | 'month'
  breakdown     TEXT NOT NULL DEFAULT 'TOTAL',
  sub_breakdown TEXT NOT NULL DEFAULT '',
  value         REAL,
  unit          TEXT,
  source        TEXT,
  updated_at    TEXT,
  PRIMARY KEY (dataset, period, breakdown, sub_breakdown)
);
CREATE INDEX IF NOT EXISTS idx_macro_series_lookup
  ON {MACRO_SERIES_TABLE} (dataset, period_type, period);

CREATE TABLE IF NOT EXISTS {MACRO_DATASET_TABLE} (
  dataset     TEXT PRIMARY KEY,
  title       TEXT,
  category    TEXT,                      -- 'GDP' | 'Labour' | 'External' | 'Monetary'
  unit        TEXT,
  frequency   TEXT,                      -- 'annual' | 'quarter' | 'month' | 'mixed'
  source      TEXT,
  source_url  TEXT,
  description TEXT,
  n_rows      INTEGER,
  min_period  TEXT,
  max_period  TEXT,
  updated_at  TEXT
);
"""


@dataclass(frozen=True)
class SeriesRow:
    """One observation in ``macro_series`` (a single number for one period)."""

    dataset: str
    period: str
    period_type: str
    value: float | None
    breakdown: str = "TOTAL"
    sub_breakdown: str = ""
    unit: str | None = None
    source: str | None = None

    def key(self) -> tuple[str, str, str, str]:
        return (self.dataset, self.period, self.breakdown, self.sub_breakdown)


@dataclass
class DatasetMeta:
    """Catalog entry for a dataset (row in ``macro_dataset``)."""

    dataset: str
    title: str
    category: str
    unit: str
    source: str
    source_url: str = ""
    description: str = ""
    frequency: str = ""  # recomputed from data if left blank
    extra: dict = field(default_factory=dict)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


def upsert_series(
    conn: sqlite3.Connection, rows: list[SeriesRow], updated_at: str
) -> int:
    """UPSERT ``rows`` into ``macro_series``. Returns the number written.

    Idempotent on the (dataset, period, breakdown, sub_breakdown) key. Rows with
    a duplicate key inside the same batch keep the *last* occurrence.
    """
    ensure_schema(conn)
    deduped: dict[tuple, SeriesRow] = {}
    for r in rows:
        deduped[r.key()] = r
    payload = [
        (
            r.dataset, r.period, r.period_type, r.breakdown, r.sub_breakdown,
            r.value, r.unit, r.source, updated_at,
        )
        for r in deduped.values()
    ]
    conn.executemany(
        f"""
        INSERT INTO {MACRO_SERIES_TABLE}
          (dataset, period, period_type, breakdown, sub_breakdown,
           value, unit, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset, period, breakdown, sub_breakdown) DO UPDATE SET
          period_type = excluded.period_type,
          value       = excluded.value,
          unit        = excluded.unit,
          source      = excluded.source,
          updated_at  = excluded.updated_at
        """,
        payload,
    )
    conn.commit()
    return len(payload)


def replace_dataset(
    conn: sqlite3.Connection, dataset: str, rows: list[SeriesRow], updated_at: str
) -> int:
    """Delete all existing rows for ``dataset`` then insert ``rows``.

    Use when a source may *drop* series between runs (e.g. a country stops
    appearing) and stale rows should not linger. Runs in a single transaction so
    a mid-way failure rolls back to the prior snapshot.
    """
    ensure_schema(conn)
    try:
        conn.execute(
            f"DELETE FROM {MACRO_SERIES_TABLE} WHERE dataset = ?", (dataset,)
        )
        n = upsert_series(conn, rows, updated_at)
        conn.commit()
        return n
    except Exception:
        conn.rollback()
        raise


def upsert_dataset_meta(
    conn: sqlite3.Connection, meta: DatasetMeta, updated_at: str
) -> None:
    """Write/refresh a catalog row, recomputing coverage from ``macro_series``."""
    ensure_schema(conn)
    row = conn.execute(
        f"""
        SELECT COUNT(*), MIN(period), MAX(period),
               COUNT(DISTINCT period_type)
        FROM {MACRO_SERIES_TABLE} WHERE dataset = ?
        """,
        (meta.dataset,),
    ).fetchone()
    n_rows = row[0] or 0
    min_p, max_p = row[1], row[2]
    freq = meta.frequency or _infer_frequency(conn, meta.dataset)
    conn.execute(
        f"""
        INSERT INTO {MACRO_DATASET_TABLE}
          (dataset, title, category, unit, frequency, source, source_url,
           description, n_rows, min_period, max_period, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset) DO UPDATE SET
          title=excluded.title, category=excluded.category, unit=excluded.unit,
          frequency=excluded.frequency, source=excluded.source,
          source_url=excluded.source_url, description=excluded.description,
          n_rows=excluded.n_rows, min_period=excluded.min_period,
          max_period=excluded.max_period, updated_at=excluded.updated_at
        """,
        (
            meta.dataset, meta.title, meta.category, meta.unit, freq,
            meta.source, meta.source_url, meta.description,
            n_rows, min_p, max_p, updated_at,
        ),
    )
    conn.commit()


def _infer_frequency(conn: sqlite3.Connection, dataset: str) -> str:
    kinds = {
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT period_type FROM {MACRO_SERIES_TABLE} WHERE dataset=?",
            (dataset,),
        ).fetchall()
    }
    if not kinds:
        return ""
    if len(kinds) > 1:
        return "mixed"
    return next(iter(kinds))
