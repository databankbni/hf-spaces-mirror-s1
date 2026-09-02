from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATALOG_VERSION = "2.0.0"
SCHEMA_VERSION = "2.0.0"
BUILD_VERSION = "2.0"
USDA_SOURCE_ID = "USDA_PLANTS"
BASEFLOR_SOURCE_ID = "BASEFLOR_2023_10"
USDA_METHOD = "USDA_PLANTS_GROWTH_REQUIREMENTS"
USDA_PH_METHOD = "USDA_PLANTS_PH_COMPATIBILITY_RANGE"
BASEFLOR_METHOD = "BASEFLOR_JULVE_INDICATORS"
BASEFLOR_VERSION = "2023.10"
USDA_VERSION = "2026-08-20"
USDA_PH_WEIGHT = 0.30
NOW = lambda: datetime.now(timezone.utc).isoformat()

BASEFLOR_INDICATORS = {
    "Humidité_édaphique": ("BASEFLOR_MOISTURE", 1.0, 12.0),
    "Réaction_du_sol_(pH)": ("BASEFLOR_REACTION", 1.0, 9.0),
    "Niveau_trophique": ("BASEFLOR_TROPHIC", 1.0, 9.0),
    "Salinité": ("BASEFLOR_SALINITY", 0.0, 9.0),
    "Texture": ("BASEFLOR_TEXTURE", 1.0, 9.0),
    "Matière_organique": ("BASEFLOR_ORGANIC_MATTER", 1.0, 9.0),
}


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def finite(v: Any) -> float | None:
    try: x=float(v)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) else None


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in con.execute(f"PRAGMA table_info({table})")}


def has_table(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is not None


def dynamic_insert(con: sqlite3.Connection, table: str, values: dict[str, Any], *, replace: bool=False, ignore: bool=False) -> None:
    cols=table_columns(con,table)
    data={k:v for k,v in values.items() if k in cols}
    if not data: return
    verb='INSERT OR REPLACE' if replace else ('INSERT OR IGNORE' if ignore else 'INSERT')
    names=list(data)
    con.execute(f"{verb} INTO {table}({','.join(names)}) VALUES({','.join('?' for _ in names)})",[data[n] for n in names])


def insert_source(con: sqlite3.Connection, source_id: str, source_name: str, source_version: str, citation: str, source_url: str, license_text: str, source_type: str, notes: str) -> None:
    dynamic_insert(con,'soil_sources',{
        'source_id':source_id,'source_name':source_name,'source_version':source_version,
        'citation':citation,'source_url':source_url,'license':license_text,
        'source_type':source_type,'license_status':'VERIFIED','access_date':datetime.now(timezone.utc).date().isoformat(),'notes':notes,
    },replace=True)


def add_generic_evidence(con: sqlite3.Connection, taxon_id: str, claim_type: str, claim_value: Any, source_id: str, source_reference: str, source_version: str, extraction_method: str, confidence: str, notes: str | None=None) -> None:
    dynamic_insert(con,'evidence',{
        'taxon_id':taxon_id,'claim_type':claim_type,
        'claim_value':claim_value if isinstance(claim_value,str) else json.dumps(claim_value,ensure_ascii=False,separators=(',',':'),sort_keys=True),
        'source_id':source_id,'source_reference':source_reference,'source_version':source_version,
        'extraction_method':extraction_method,'confidence':confidence,'notes':notes,'created_at':NOW(),
    })


def add_soil_evidence(con: sqlite3.Connection, taxon_id: str, variable: str | None, source_id: str, evidence_type: str, source_table: str, source_row_id: str | None, value: Any, confidence_score: float, scoring_enabled: int, notes: str | None=None) -> None:
    if not has_table(con,'soil_evidence'): return
    payload=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True)
    dynamic_insert(con,'soil_evidence',{
        'taxon_id':taxon_id,'variable':variable,'source_id':source_id,'evidence_type':evidence_type,
        'source_table':source_table,'source_row_id':source_row_id,
        'value_json':payload,'evidence_json':payload,'confidence_score':confidence_score,'weight':confidence_score,
        'scoring_enabled':scoring_enabled,'notes':notes,
    })


def make_build_schema(con: sqlite3.Connection) -> None:
    con.executescript('''
    PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=MEMORY;
    CREATE TABLE v2_sources(source_id TEXT PRIMARY KEY,source_version TEXT,source_url TEXT,license TEXT,sha256 TEXT,notes TEXT) WITHOUT ROWID;
    CREATE TABLE v2_usda_requirement(taxon_id TEXT NOT NULL,scientific_name TEXT NOT NULL,symbol TEXT NOT NULL,usda_id INTEGER,characteristic TEXT NOT NULL,value TEXT NOT NULL,scoring_enabled INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(taxon_id,symbol,characteristic,value)) WITHOUT ROWID;
    CREATE TABLE v2_baseflor_indicator(taxon_id TEXT NOT NULL,scientific_name TEXT NOT NULL,indicator TEXT NOT NULL,value REAL NOT NULL,scale_min REAL NOT NULL,scale_max REAL NOT NULL,source_name TEXT,PRIMARY KEY(taxon_id,indicator)) WITHOUT ROWID;
    CREATE TABLE v2_conflict(taxon_id TEXT NOT NULL,variable TEXT NOT NULL,source_a TEXT,source_b TEXT,details TEXT NOT NULL);
    CREATE TABLE v2_build_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;
    ''')


def read_usda(path: Path) -> list[dict[str,Any]]:
    out=[]
    with path.open(encoding='utf-8') as f:
        for line in f:
            if line.strip(): out.append(json.loads(line))
    return out


def growth_map(rec: dict[str,Any]) -> dict[str,list[str]]:
    d: dict[str,list[str]]=defaultdict(list)
    for item in rec.get('growth_requirements',[]):
        if isinstance(item,dict) and item.get('name') and item.get('value') not in (None,''):
            d[str(item['name'])].append(str(item['value']))
    return d


def load_name_map(con: sqlite3.Connection) -> tuple[dict[str,str],set[str]]:
    by: dict[str,list[str]]=defaultdict(list)
    for name,tid in con.execute('SELECT scientific_name,taxon_id FROM plant_index'):
        if name: by[str(name).strip()].append(str(tid))
    return {n:v[0] for n,v in by.items() if len(v)==1},{n for n,v in by.items() if len(v)>1}


def existing_canonical(con: sqlite3.Connection, tid: str, variable: str) -> sqlite3.Row | None:
    if not has_table(con,'soil_envelopes'): return None
    return con.execute('SELECT * FROM soil_envelopes WHERE taxon_id=? AND variable=?',(tid,variable)).fetchone()


def upsert_canonical(con: sqlite3.Connection, tid: str, variable: str, *, core_min: float|None, core_max: float|None, tol_min: float|None, tol_max: float|None, source_level: str, confidence_score: float, confidence_class: str, n_evidence: int, scoring_enabled: int, conflict_flag: int, conflict_notes: str|None, source_ref: str, method: str, method_version: str) -> None:
    if not has_table(con,'soil_envelopes'): return
    cols=table_columns(con,'soil_envelopes')
    values={
      'taxon_id':tid,'variable':variable,'core_min':core_min,'core_max':core_max,
      'tolerance_min':tol_min,'tolerance_max':tol_max,'median':None,'source_level':source_level,
      'source_subtype':'COMPATIBILITY_RANGE' if core_min is None and core_max is None else 'COMBINED',
      'confidence_score':confidence_score,'confidence_class':confidence_class,'n_evidence':n_evidence,
      'n_samples':None,'scoring_enabled':scoring_enabled,'conflict_flag':conflict_flag,
      'conflict_notes':conflict_notes,'source_ref':source_ref,'method':method,'method_version':method_version,'updated_at':NOW(),
    }
    keys=[k for k in values if k in cols]
    con.execute("DELETE FROM soil_envelopes WHERE taxon_id=? AND variable=?",(tid,variable))
    con.execute(f"INSERT INTO soil_envelopes({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",[values[k] for k in keys])


def upsert_runtime_ph(con: sqlite3.Connection, tid: str, low: float, high: float, *, opt_low: float|None, opt_high: float|None, confidence: str, source_ref: str, method: str) -> None:
    con.execute("DELETE FROM soil_envelope WHERE taxon_id=? AND variable='ph'",(tid,))
    con.execute('''INSERT INTO soil_envelope(taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,weight,group_code,fatal,confidence,source_ref,method,method_version)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (tid,'ph',low,opt_low,opt_high,high,USDA_PH_WEIGHT,'E',0,confidence,source_ref,method,BUILD_VERSION))


def classify_existing_level(row: sqlite3.Row | None) -> str:
    if row is None: return ''
    try: return str(row['source_level'] or '')
    except Exception: return ''
