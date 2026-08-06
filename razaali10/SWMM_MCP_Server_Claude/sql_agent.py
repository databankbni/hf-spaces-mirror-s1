"""Safe provider-agnostic SQL retrieval agent for the complete SWMM SQLite store.

The language model produces a constrained JSON retrieval plan. This module validates
that plan and executes read-only SELECT statements only. No model-generated SQL is
executed directly.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

import pandas as pd


_ALLOWED_FILTER_OPS = {
    "eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
    "like": "LIKE", "in": "IN", "between": "BETWEEN",
    "is_null": "IS NULL", "not_null": "IS NOT NULL",
}
_ALLOWED_AGGS = {"MAX", "MIN", "AVG", "SUM", "COUNT"}
_MAX_ACTIONS = 6
_MAX_ROWS_PER_ACTION = 120
_MAX_CONTEXT_CHARS = 45_000


@dataclass
class RetrievalResult:
    context: str
    audit: list[dict[str, Any]]
    plan: dict[str, Any]


class SafeSQLAgent:
    """Validate and execute bounded, read-only retrieval plans against a ResultDatabase."""

    def __init__(self, result_db: Any) -> None:
        self.db = result_db
        self.conn: sqlite3.Connection = result_db.connection
        self._tables = self._read_tables()
        self._columns = {table: self._read_columns(table) for table in self._tables}

    @staticmethod
    def _quote_identifier(name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def _read_tables(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [str(r[0]) for r in rows]

    def _read_columns(self, table: str) -> list[str]:
        if table not in self._tables:
            return []
        rows = self.conn.execute(f"PRAGMA table_info({self._quote_identifier(table)})").fetchall()
        return [str(r[1]) for r in rows]

    def _row_count(self, table: str) -> int:
        try:
            return int(self.conn.execute(
                f"SELECT COUNT(*) FROM {self._quote_identifier(table)}"
            ).fetchone()[0])
        except Exception:
            return 0

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {t.lower() for t in re.findall(r"[A-Za-z0-9_:.\-]+", text) if len(t) > 1}

    def schema_context(self, question: str, max_tables: int = 16) -> str:
        """Return a compact, question-ranked schema catalogue for the planning call."""
        q_tokens = self._tokens(question)
        synonyms = {
            "node": {"node", "junction", "outfall", "storage", "manhole", "flood", "head", "depth"},
            "link": {"link", "conduit", "pipe", "pump", "weir", "orifice", "outlet", "flow", "velocity", "capacity"},
            "subcatchment": {"subcatchment", "catchment", "runoff", "rainfall", "infiltration", "hydrology"},
            "input": {"input", "option", "roughness", "diameter", "length", "invert", "curve", "pattern", "control"},
            "timeseries": {"time", "timeseries", "duration", "when", "peak", "first", "last", "hour"},
        }
        expanded = set(q_tokens)
        for _, words in synonyms.items():
            if q_tokens & words:
                expanded |= words

        always = {
            "simulation_metadata", "simulation_warnings", "node_summary", "link_summary",
            "subcatchment_summary", "model_input_section_catalog",
        }
        scored: list[tuple[float, str]] = []
        for table in self._tables:
            hay = self._tokens(table + " " + " ".join(self._columns[table]))
            score = float(len(expanded & hay) * 5)
            for token in expanded:
                if token in table.lower():
                    score += 3
                score += sum(1 for c in self._columns[table] if token in c.lower()) * 0.5
            if table in always:
                score += 4
            if table.endswith("_timeseries") and (expanded & synonyms["timeseries"]):
                score += 5
            if table.startswith("inp_") and (expanded & synonyms["input"]):
                score += 5
            scored.append((score, table))

        selected = [t for _, t in sorted(scored, reverse=True)[:max_tables]]
        for table in always:
            if table in self._tables and table not in selected:
                selected.append(table)
        selected = selected[:max_tables]

        lines = ["AVAILABLE SQLITE TABLES (question-ranked):"]
        for table in selected:
            cols = self._columns[table]
            count = self._row_count(table)
            lines.append(f"- {table} ({count} rows): {', '.join(cols)}")
        lines.append(
            "The complete database may contain additional inp_<section> tables. "
            "Use model_input_lines to search exact source text when a section is not listed."
        )
        return "\n".join(lines)

    def planner_system_prompt(self, schema_context: str) -> str:
        return f"""You are a retrieval planner for an EPA SWMM SQLite database.
Return ONLY valid JSON. Do not answer the engineering question.
Create the smallest read-only retrieval plan that supplies enough evidence for a later engineering answer.
Never emit SQL. Use only the operations and fields below.

{schema_context}

JSON format:
{{
  "reasoning_summary": "brief retrieval rationale",
  "actions": [
    {{
      "operation": "select",
      "table": "table_name",
      "columns": ["column1", "column2"],
      "filters": [{{"column":"column1","op":"eq|ne|gt|gte|lt|lte|like|in|between|is_null|not_null","value": "value or list"}}],
      "order_by": [{{"column":"column1","direction":"asc|desc"}}],
      "limit": 40,
      "label": "descriptive result label"
    }},
    {{
      "operation": "aggregate",
      "table": "table_name",
      "group_by": ["optional_column"],
      "metrics": [{{"function":"MAX|MIN|AVG|SUM|COUNT","column":"column_or_*","alias":"metric_name"}}],
      "filters": [],
      "order_by": [{{"column":"metric_alias_or_group_column","direction":"desc"}}],
      "limit": 40,
      "label": "descriptive result label"
    }},
    {{
      "operation": "search_input",
      "term": "text to find in raw SWMM input lines",
      "section": "optional SWMM section name without brackets",
      "limit": 40,
      "label": "descriptive result label"
    }},
    {{
      "operation": "describe_table",
      "table": "table_name",
      "label": "table structure"
    }}
  ]
}}

Rules:
- Maximum 6 actions and normally 1-4 actions.
- Use exact asset IDs appearing in the user's question as equality filters.
- Prefer summary/aggregate retrieval for broad questions and detailed time-series only for named assets or explicit temporal questions.
- For first/last/peak questions, use ordering and a small limit or an aggregate.
- Retrieve model inputs from inp_* tables or model_input_lines.
- Never request full tables. Keep each limit at or below 120.
- Use engineering evidence from both input and output tables when the question asks for diagnosis or recommendations.
"""

    @staticmethod
    def parse_plan(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start:end + 1]
        plan = json.loads(cleaned)
        if not isinstance(plan, dict):
            raise ValueError("Planner response must be a JSON object")
        actions = plan.get("actions", [])
        if not isinstance(actions, list):
            raise ValueError("Planner actions must be a list")
        plan["actions"] = actions[:_MAX_ACTIONS]
        return plan

    def _validate_table(self, table: str) -> str:
        if table not in self._tables:
            raise ValueError(f"Unknown table: {table}")
        return table

    def _validate_column(self, table: str, column: str, *, allow_star: bool = False) -> str:
        if allow_star and column == "*":
            return column
        if column not in self._columns[table]:
            raise ValueError(f"Unknown column {column!r} in {table}")
        return column

    def _build_filters(self, table: str, filters: Any) -> tuple[str, list[Any]]:
        if not filters:
            return "", []
        clauses: list[str] = []
        params: list[Any] = []
        for item in list(filters)[:12]:
            if not isinstance(item, dict):
                continue
            col = self._validate_column(table, str(item.get("column", "")))
            op_key = str(item.get("op", "eq")).lower()
            if op_key not in _ALLOWED_FILTER_OPS:
                raise ValueError(f"Unsupported filter operation: {op_key}")
            sql_op = _ALLOWED_FILTER_OPS[op_key]
            qcol = self._quote_identifier(col)
            value = item.get("value")
            if op_key in {"is_null", "not_null"}:
                clauses.append(f"{qcol} {sql_op}")
            elif op_key == "in":
                values = value if isinstance(value, list) else [value]
                values = values[:50]
                if not values:
                    clauses.append("1=0")
                else:
                    clauses.append(f"{qcol} IN ({','.join('?' for _ in values)})")
                    params.extend(values)
            elif op_key == "between":
                values = value if isinstance(value, list) else []
                if len(values) != 2:
                    raise ValueError("between requires exactly two values")
                clauses.append(f"{qcol} BETWEEN ? AND ?")
                params.extend(values)
            else:
                clauses.append(f"{qcol} {sql_op} ?")
                params.append(value)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def _build_order(self, table: str, order_by: Any, aliases: set[str] | None = None) -> str:
        if not order_by:
            return ""
        aliases = aliases or set()
        parts: list[str] = []
        for item in list(order_by)[:4]:
            if not isinstance(item, dict):
                continue
            col = str(item.get("column", ""))
            if col not in aliases:
                self._validate_column(table, col)
            direction = "DESC" if str(item.get("direction", "asc")).lower() == "desc" else "ASC"
            parts.append(f"{self._quote_identifier(col)} {direction}")
        return " ORDER BY " + ", ".join(parts) if parts else ""

    @staticmethod
    def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in out.columns:
            out[col] = out[col].map(
                lambda v: None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v
            )
        return out

    def _execute_select(self, action: dict[str, Any]) -> tuple[pd.DataFrame, str]:
        table = self._validate_table(str(action.get("table", "")))
        requested = action.get("columns") or self._columns[table]
        columns = [self._validate_column(table, str(c)) for c in requested]
        columns = columns[:24]
        where_sql, params = self._build_filters(table, action.get("filters"))
        order_sql = self._build_order(table, action.get("order_by"))
        limit = min(max(int(action.get("limit", 40)), 1), _MAX_ROWS_PER_ACTION)
        sql = (
            "SELECT " + ", ".join(self._quote_identifier(c) for c in columns) +
            f" FROM {self._quote_identifier(table)}" + where_sql + order_sql + " LIMIT ?"
        )
        df = pd.read_sql_query(sql, self.conn, params=(*params, limit))
        return self._clean_frame(df), sql

    def _execute_aggregate(self, action: dict[str, Any]) -> tuple[pd.DataFrame, str]:
        table = self._validate_table(str(action.get("table", "")))
        group_by = [self._validate_column(table, str(c)) for c in (action.get("group_by") or [])][:6]
        metric_exprs: list[str] = []
        aliases: set[str] = set()
        for metric in (action.get("metrics") or [])[:12]:
            if not isinstance(metric, dict):
                continue
            fn = str(metric.get("function", "")).upper()
            if fn not in _ALLOWED_AGGS:
                raise ValueError(f"Unsupported aggregate: {fn}")
            col = str(metric.get("column", "*"))
            self._validate_column(table, col, allow_star=(fn == "COUNT"))
            alias = re.sub(r"[^A-Za-z0-9_]+", "_", str(metric.get("alias") or f"{fn.lower()}_{col}"))
            aliases.add(alias)
            expr_col = "*" if col == "*" else self._quote_identifier(col)
            metric_exprs.append(f"{fn}({expr_col}) AS {self._quote_identifier(alias)}")
        if not metric_exprs:
            metric_exprs = ['COUNT(*) AS "row_count"']
            aliases.add("row_count")
        select_parts = [self._quote_identifier(c) for c in group_by] + metric_exprs
        where_sql, params = self._build_filters(table, action.get("filters"))
        group_sql = " GROUP BY " + ", ".join(self._quote_identifier(c) for c in group_by) if group_by else ""
        order_sql = self._build_order(table, action.get("order_by"), aliases=aliases)
        limit = min(max(int(action.get("limit", 40)), 1), _MAX_ROWS_PER_ACTION)
        sql = (
            "SELECT " + ", ".join(select_parts) + f" FROM {self._quote_identifier(table)}" +
            where_sql + group_sql + order_sql + " LIMIT ?"
        )
        df = pd.read_sql_query(sql, self.conn, params=(*params, limit))
        return self._clean_frame(df), sql

    def _execute_search_input(self, action: dict[str, Any]) -> tuple[pd.DataFrame, str]:
        term = str(action.get("term", "")).strip()
        if not term:
            raise ValueError("search_input requires a term")
        section = str(action.get("section", "")).strip().upper()
        limit = min(max(int(action.get("limit", 40)), 1), _MAX_ROWS_PER_ACTION)
        sql = (
            "SELECT line_no, section_name, section_row_no, raw_text FROM model_input_lines "
            "WHERE lower(raw_text) LIKE lower(?)"
        )
        params: list[Any] = [f"%{term}%"]
        if section:
            sql += " AND upper(section_name)=?"
            params.append(section)
        sql += " ORDER BY line_no LIMIT ?"
        params.append(limit)
        df = pd.read_sql_query(sql, self.conn, params=params)
        return self._clean_frame(df), sql

    def _execute_describe(self, action: dict[str, Any]) -> tuple[pd.DataFrame, str]:
        table = self._validate_table(str(action.get("table", "")))
        rows = self.conn.execute(f"PRAGMA table_info({self._quote_identifier(table)})").fetchall()
        df = pd.DataFrame(rows, columns=["cid", "name", "type", "notnull", "default_value", "primary_key"])
        df["row_count"] = self._row_count(table)
        return df, f"PRAGMA table_info({table})"

    def execute_plan(self, plan: dict[str, Any]) -> RetrievalResult:
        contexts: list[str] = []
        audit: list[dict[str, Any]] = []
        used_chars = 0
        for index, action in enumerate(plan.get("actions", [])[:_MAX_ACTIONS], start=1):
            if not isinstance(action, dict):
                continue
            operation = str(action.get("operation", "select")).lower()
            label = str(action.get("label") or f"Retrieval {index}")
            try:
                if operation == "select":
                    df, sql = self._execute_select(action)
                elif operation == "aggregate":
                    df, sql = self._execute_aggregate(action)
                elif operation == "search_input":
                    df, sql = self._execute_search_input(action)
                elif operation == "describe_table":
                    df, sql = self._execute_describe(action)
                else:
                    raise ValueError(f"Unsupported operation: {operation}")
                csv_text = df.to_csv(index=False)
                block = f"=== {label} ===\n{csv_text}"
                remaining = _MAX_CONTEXT_CHARS - used_chars
                if remaining <= 0:
                    break
                if len(block) > remaining:
                    block = block[:remaining] + "\n[retrieval context truncated]"
                contexts.append(block)
                used_chars += len(block)
                audit.append({
                    "action": index,
                    "label": label,
                    "operation": operation,
                    "table": action.get("table", "model_input_lines" if operation == "search_input" else ""),
                    "rows_returned": int(len(df)),
                    "status": "ok",
                })
            except Exception as exc:
                audit.append({
                    "action": index,
                    "label": label,
                    "operation": operation,
                    "table": action.get("table", ""),
                    "rows_returned": 0,
                    "status": f"error: {exc}",
                })
        return RetrievalResult(context="\n\n".join(contexts), audit=audit, plan=plan)
