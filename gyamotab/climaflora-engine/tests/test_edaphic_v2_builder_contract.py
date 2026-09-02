import importlib.util
import sqlite3
from pathlib import Path


def _load_common():
    path=Path(__file__).resolve().parents[1]/'.github'/'tools'/'edaphic_v2_common.py'
    spec=importlib.util.spec_from_file_location('edaphic_v2_common_test',path)
    module=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_usda_ph_runtime_weight_matches_existing_edaphic_calibration():
    m=_load_common()
    assert m.USDA_PH_WEIGHT == 0.30
    con=sqlite3.connect(':memory:')
    con.execute('''CREATE TABLE soil_envelope(
        taxon_id TEXT, variable TEXT, hard_low REAL, optimum_low REAL,
        optimum_high REAL, hard_high REAL, weight REAL, group_code TEXT,
        fatal INTEGER, confidence TEXT, source_ref TEXT, method TEXT, method_version TEXT
    )''')
    m.upsert_runtime_ph(
        con,'1',4.8,7.2,opt_low=None,opt_high=None,confidence='B',
        source_ref='USDA test',method=m.USDA_PH_METHOD,
    )
    row=con.execute("SELECT hard_low,optimum_low,optimum_high,hard_high,weight FROM soil_envelope").fetchone()
    assert row == (4.8,None,None,7.2,0.30)


def test_usda_range_only_semantics_do_not_create_an_optimum():
    m=_load_common()
    con=sqlite3.connect(':memory:')
    con.execute('''CREATE TABLE soil_envelope(
        taxon_id TEXT, variable TEXT, hard_low REAL, optimum_low REAL,
        optimum_high REAL, hard_high REAL, weight REAL, group_code TEXT,
        fatal INTEGER, confidence TEXT, source_ref TEXT, method TEXT, method_version TEXT
    )''')
    m.upsert_runtime_ph(
        con,'1',5.0,8.0,opt_low=None,opt_high=None,confidence='B',
        source_ref='USDA test',method=m.USDA_PH_METHOD,
    )
    row=con.execute("SELECT optimum_low,optimum_high FROM soil_envelope").fetchone()
    assert row == (None,None)
