"""Complete SQLite store for SWMM model inputs, outputs, summaries and AI retrieval."""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


class ResultDatabase:
    """File-backed SQLite database containing the complete model and simulation dataset.

    The database is intentionally file-backed rather than ``:memory:`` so the user can
    download it, inspect it in any SQLite client, and retain an auditable simulation
    artefact. The LLM still receives only bounded query results.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            fd, name = tempfile.mkstemp(prefix="swmm_model_", suffix=".sqlite")
            Path(name).unlink(missing_ok=True)
            try:
                import os
                os.close(fd)
            except OSError:
                pass
            self.path = Path(name)
        else:
            self.path = Path(db_path)
        self.connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA foreign_keys=ON")

    @staticmethod
    def _safe_table_name(section: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9_]+", "_", section.strip().lower()).strip("_")
        return f"inp_{clean or 'unknown'}"

    def _load_complete_input(self, inp_path: str | Path) -> None:
        path = Path(inp_path)
        text = path.read_text(encoding="utf-8", errors="replace")
        line_rows: list[dict[str, Any]] = []
        section_rows: dict[str, list[dict[str, Any]]] = {}
        catalog: list[dict[str, Any]] = []
        current_section = "PREAMBLE"
        section_row_no = 0

        for line_no, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.strip()
            is_section = stripped.startswith("[") and "]" in stripped
            if is_section:
                current_section = stripped[1:stripped.index("]")].strip().upper()
                section_row_no = 0
            elif stripped and not stripped.startswith(";"):
                section_row_no += 1

            line_rows.append({
                "line_no": line_no,
                "section_name": current_section,
                "section_row_no": section_row_no if not is_section else 0,
                "raw_text": raw,
                "stripped_text": stripped,
                "is_blank": int(not stripped),
                "is_comment": int(stripped.startswith(";")),
                "is_section_header": int(is_section),
            })

            if stripped and not stripped.startswith(";") and not is_section:
                # Keep both the exact raw line and all whitespace-delimited values.
                tokens = stripped.split()
                row = {
                    "row_no": section_row_no,
                    "source_line_no": line_no,
                    "raw_text": raw,
                }
                for i, token in enumerate(tokens, start=1):
                    row[f"value_{i}"] = token
                section_rows.setdefault(current_section, []).append(row)

        pd.DataFrame(line_rows).to_sql(
            "model_input_lines", self.connection, if_exists="replace", index=False
        )
        pd.DataFrame([{
            "file_name": path.name,
            "absolute_path_at_run": str(path),
            "byte_size": path.stat().st_size,
            "line_count": len(line_rows),
            "full_text": text,
        }]).to_sql("model_input_file", self.connection, if_exists="replace", index=False)

        for section, rows in section_rows.items():
            table = self._safe_table_name(section)
            pd.DataFrame(rows).to_sql(table, self.connection, if_exists="replace", index=False)
            catalog.append({
                "section_name": section,
                "table_name": table,
                "row_count": len(rows),
                "max_values_per_row": max(
                    (sum(1 for k in r if k.startswith("value_")) for r in rows), default=0
                ),
            })

        pd.DataFrame(catalog).to_sql(
            "model_input_section_catalog", self.connection, if_exists="replace", index=False
        )

    @staticmethod
    def _time_strings(times: list[Any]) -> list[str]:
        return [t.isoformat(sep=" ") if hasattr(t, "isoformat") else str(t) for t in times]

    def _load_complete_outputs(self, results: dict[str, Any]) -> None:
        times = results.get("times", [])
        time_strings = self._time_strings(times)

        node_rows: list[dict[str, Any]] = []
        for node_id, data in results.get("node_ts", {}).items():
            n = max((len(data.get(k, [])) for k in (
                "depth", "flooding", "inflow", "head", "outflow", "volume"
            )), default=0)
            for i in range(n):
                node_rows.append({
                    "time_index": i,
                    "timestamp": time_strings[i] if i < len(time_strings) else str(i),
                    "node_id": node_id,
                    "depth": data.get("depth", [None] * n)[i],
                    "flooding": data.get("flooding", [None] * n)[i],
                    "inflow": data.get("inflow", [None] * n)[i],
                    "head": data.get("head", [None] * n)[i],
                    "outflow": data.get("outflow", [None] * n)[i],
                    "volume": data.get("volume", [None] * n)[i],
                })
        pd.DataFrame(node_rows, columns=[
            "time_index", "timestamp", "node_id", "depth", "flooding",
            "inflow", "head", "outflow", "volume"
        ]).to_sql("node_timeseries", self.connection, if_exists="replace", index=False, chunksize=5000)

        node_static = [{
            "node_id": node_id,
            "invert_elevation": data.get("invert_elevation"),
            "full_depth": data.get("full_depth"),
        } for node_id, data in results.get("node_ts", {}).items()]
        pd.DataFrame(node_static, columns=["node_id", "invert_elevation", "full_depth"]).to_sql(
            "node_output_metadata", self.connection, if_exists="replace", index=False
        )

        link_rows: list[dict[str, Any]] = []
        for link_id, data in results.get("link_ts", {}).items():
            n = max((len(data.get(k, [])) for k in (
                "flow", "depth", "velocity", "volume", "capacity"
            )), default=0)
            for i in range(n):
                link_rows.append({
                    "time_index": i,
                    "timestamp": time_strings[i] if i < len(time_strings) else str(i),
                    "link_id": link_id,
                    "flow": data.get("flow", [None] * n)[i],
                    "depth": data.get("depth", [None] * n)[i],
                    "velocity": data.get("velocity", [None] * n)[i],
                    "volume": data.get("volume", [None] * n)[i],
                    "capacity": data.get("capacity", [None] * n)[i],
                })
        pd.DataFrame(link_rows, columns=[
            "time_index", "timestamp", "link_id", "flow", "depth",
            "velocity", "volume", "capacity"
        ]).to_sql("link_timeseries", self.connection, if_exists="replace", index=False, chunksize=5000)

        link_static = [{
            "link_id": link_id,
            "length": data.get("length"),
            "roughness": data.get("roughness"),
            "diameter": data.get("diameter"),
        } for link_id, data in results.get("link_ts", {}).items()]
        pd.DataFrame(link_static, columns=["link_id", "length", "roughness", "diameter"]).to_sql(
            "link_output_metadata", self.connection, if_exists="replace", index=False
        )

        sub_rows: list[dict[str, Any]] = []
        for sub_id, data in results.get("sub_ts", {}).items():
            n = max((len(data.get(k, [])) for k in ("runoff", "rainfall", "infil")), default=0)
            for i in range(n):
                sub_rows.append({
                    "time_index": i,
                    "timestamp": time_strings[i] if i < len(time_strings) else str(i),
                    "subcatchment_id": sub_id,
                    "runoff": data.get("runoff", [None] * n)[i],
                    "rainfall": data.get("rainfall", [None] * n)[i],
                    "infiltration": data.get("infil", [None] * n)[i],
                })
        pd.DataFrame(sub_rows, columns=[
            "time_index", "timestamp", "subcatchment_id", "runoff", "rainfall", "infiltration"
        ]).to_sql("subcatchment_timeseries", self.connection, if_exists="replace", index=False, chunksize=5000)

        metadata = results.get("metadata", {})
        meta_rows = []
        warnings = metadata.get("warnings", []) or []
        for key, value in metadata.items():
            if key == "warnings":
                continue
            if isinstance(value, (dict, list, tuple)):
                value = json.dumps(value, default=str)
            elif hasattr(value, "isoformat"):
                value = value.isoformat()
            meta_rows.append({"key": key, "value": value})
        pd.DataFrame(meta_rows, columns=["key", "value"]).to_sql(
            "simulation_metadata", self.connection, if_exists="replace", index=False
        )
        pd.DataFrame(warnings, columns=["code", "message"]).to_sql(
            "simulation_warnings", self.connection, if_exists="replace", index=False
        )

        # Indexes materially reduce retrieval cost for large models.
        self.connection.executescript("""
        CREATE INDEX IF NOT EXISTS idx_node_ts_id_time ON node_timeseries(node_id, time_index);
        CREATE INDEX IF NOT EXISTS idx_node_ts_flood ON node_timeseries(flooding DESC);
        CREATE INDEX IF NOT EXISTS idx_link_ts_id_time ON link_timeseries(link_id, time_index);
        CREATE INDEX IF NOT EXISTS idx_link_ts_capacity ON link_timeseries(capacity DESC);
        CREATE INDEX IF NOT EXISTS idx_sub_ts_id_time ON subcatchment_timeseries(subcatchment_id, time_index);
        CREATE INDEX IF NOT EXISTS idx_input_section ON model_input_lines(section_name, section_row_no);
        """)

    def load(
        self,
        node_summary: pd.DataFrame,
        link_summary: pd.DataFrame,
        sub_summary: pd.DataFrame,
        *,
        inp_path: str | Path,
        results: dict[str, Any],
    ) -> None:
        node_summary.to_sql("node_summary", self.connection, if_exists="replace", index=False)
        link_summary.to_sql("link_summary", self.connection, if_exists="replace", index=False)
        sub_summary.to_sql("subcatchment_summary", self.connection, if_exists="replace", index=False)
        self._load_complete_input(inp_path)
        self._load_complete_outputs(results)
        self.connection.commit()

    def table_catalog(self) -> pd.DataFrame:
        return pd.read_sql_query("""
            SELECT name AS table_name
            FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """, self.connection)

    def export_bytes(self) -> bytes:
        self.connection.commit()
        # Checkpoint WAL so the downloaded main file is self-contained.
        try:
            self.connection.execute("PRAGMA wal_checkpoint(FULL)")
        except sqlite3.DatabaseError:
            pass
        return self.path.read_bytes()

    @staticmethod
    def _quoted(value: str) -> str:
        return value.replace("'", "''")

    def engineering_context(self, question: str, limit: int = 20) -> str:
        """Return compact SQL-derived context while retaining the full database locally."""
        q = question.lower()
        parts: list[str] = []

        # Asset IDs in the question are used to retrieve exact time series.
        ids = re.findall(r"\b[A-Za-z][A-Za-z0-9_.:-]*\b", question)
        known_noise = {"which", "what", "when", "where", "show", "compare", "node", "nodes",
                       "link", "links", "pipe", "pipes", "conduit", "flow", "depth", "runoff",
                       "the", "and", "for", "from", "with", "during", "model"}
        ids = [x for x in ids if x.lower() not in known_noise][:8]

        if any(k in q for k in ("input", "roughness", "diameter", "length", "invert", "elevation",
                                "option", "rain gage", "timeseries", "control", "weir", "orifice",
                                "pump", "storage", "infiltration", "subarea")):
            section_terms = {
                "roughness": "CONDUITS", "diameter": "XSECTIONS", "length": "CONDUITS",
                "invert": "JUNCTIONS", "elevation": "JUNCTIONS", "control": "CONTROLS",
                "pump": "PUMPS", "weir": "WEIRS", "orifice": "ORIFICES",
                "storage": "STORAGE", "infiltration": "INFILTRATION", "subarea": "SUBAREAS",
                "rain": "RAINGAGES", "option": "OPTIONS",
            }
            selected = {v for k, v in section_terms.items() if k in q}
            if not selected:
                selected = {"OPTIONS", "JUNCTIONS", "CONDUITS", "XSECTIONS", "SUBCATCHMENTS"}
            names = ",".join(f"'{self._quoted(s)}'" for s in selected)
            sql = f"""SELECT section_name, section_row_no, raw_text
                      FROM model_input_lines
                      WHERE section_name IN ({names}) AND is_comment=0 AND is_blank=0
                      LIMIT {int(limit * 2)}"""
            parts.append("MODEL INPUT\n" + pd.read_sql_query(sql, self.connection).to_csv(index=False))

        if any(k in q for k in ("flood", "node", "manhole", "head", "inflow", "outflow")):
            parts.append("NODE SUMMARY\n" + pd.read_sql_query(
                f'''SELECT * FROM node_summary ORDER BY "Peak Flooding (m³/s)" DESC, "Depth Ratio" DESC LIMIT {int(limit)}''',
                self.connection).to_csv(index=False))
            for asset_id in ids:
                df = pd.read_sql_query(
                    """SELECT * FROM node_timeseries WHERE lower(node_id)=lower(?)
                       ORDER BY time_index LIMIT ?""", self.connection, params=(asset_id, int(limit * 3)))
                if not df.empty:
                    parts.append(f"NODE TIMESERIES {asset_id}\n" + df.to_csv(index=False))

        if any(k in q for k in ("conduit", "pipe", "link", "surcharge", "velocity", "capacity", "flow")):
            parts.append("LINK SUMMARY\n" + pd.read_sql_query(
                f'''SELECT * FROM link_summary ORDER BY "Depth Ratio" DESC, "Peak Flow (m³/s)" DESC LIMIT {int(limit)}''',
                self.connection).to_csv(index=False))
            for asset_id in ids:
                df = pd.read_sql_query(
                    """SELECT * FROM link_timeseries WHERE lower(link_id)=lower(?)
                       ORDER BY time_index LIMIT ?""", self.connection, params=(asset_id, int(limit * 3)))
                if not df.empty:
                    parts.append(f"LINK TIMESERIES {asset_id}\n" + df.to_csv(index=False))

        if any(k in q for k in ("subcatch", "runoff", "rain", "catchment", "hydrology", "infiltration")):
            parts.append("SUBCATCHMENT SUMMARY\n" + pd.read_sql_query(
                f'''SELECT * FROM subcatchment_summary ORDER BY "Peak Runoff (m³/s)" DESC LIMIT {int(limit)}''',
                self.connection).to_csv(index=False))
            for asset_id in ids:
                df = pd.read_sql_query(
                    """SELECT * FROM subcatchment_timeseries WHERE lower(subcatchment_id)=lower(?)
                       ORDER BY time_index LIMIT ?""", self.connection, params=(asset_id, int(limit * 3)))
                if not df.empty:
                    parts.append(f"SUBCATCHMENT TIMESERIES {asset_id}\n" + df.to_csv(index=False))

        if not parts:
            for table in ("simulation_metadata", "node_summary", "link_summary", "subcatchment_summary"):
                parts.append(table.upper() + "\n" + pd.read_sql_query(
                    f"SELECT * FROM {table} LIMIT 10", self.connection).to_csv(index=False))

        return "\n".join(parts)
