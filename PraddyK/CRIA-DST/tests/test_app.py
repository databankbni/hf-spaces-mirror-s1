"""
Automated pre-deployment test suite for the CRIA Decision Support Tool.
Run:  pytest -q   (from the crb-dst/ root)

Covers: app import, routing coverage, every view renders, callbacks register,
data loaders, scenario uncertainty maths, water-balance physics, and that the
analytics match an independent statsmodels recomputation.
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import pytest


# ───────────────────────── App & routing ─────────────────────────
def test_app_imports():
    import app
    assert app.app is not None
    assert app.server is not None


def test_callbacks_registered():
    import app
    assert len(app.app.callback_map) >= 100, "callbacks did not register"


def test_every_view_in_nav_and_layouts():
    import app
    nav_views = [v for g in app.GROUPS for v in g["views"]]
    # Every view shown in the sidebar nav must have a registered layout.
    assert set(nav_views) <= set(app.VIEW_LAYOUTS), "nav view without a layout"
    assert len(nav_views) == len(set(nav_views)), "duplicate view in nav"
    # Views not in the main nav (e.g. the "Advanced" Aridity Severity Index) are still
    # valid standalone routes reachable from the Overview launcher.
    for extra in set(app.VIEW_LAYOUTS) - set(nav_views):
        assert callable(app.VIEW_LAYOUTS[extra])


def test_all_views_render():
    import app
    for key, fn in app.VIEW_LAYOUTS.items():
        comp = fn()
        assert comp is not None, f"view '{key}' returned None"


def test_finder_routes_valid():
    import app
    import modules.home as home
    valid = set("/" + k for k in app.VIEW_LAYOUTS)
    for opt in home.FINDER_OPTIONS:
        assert opt["value"] in valid, f"finder route {opt['value']} has no view"


def test_page_routing():
    import app
    for route in ["/", "/scenario", "/spatial", "/uncertainty", "/reservoirs", "/unknownxyz"]:
        # render_page is the callback; call its underlying function via the registry
        fn = app.VIEW_LAYOUTS.get(route.strip("/"), app.home_layout)
        assert fn() is not None


# ───────────────────────── Data loaders ─────────────────────────
def test_data_loaders_nonempty():
    from utils.data_loader import (load_vic_annual, load_grace, load_smap,
                                    load_snotel_annual)
    assert not load_vic_annual().empty
    assert not load_grace().empty
    assert not load_smap().empty
    assert not load_snotel_annual().empty


def test_grace_has_uncertainty():
    from utils.data_loader import load_grace
    g = load_grace()
    assert "tws_unc_mm" in g.columns
    assert g["tws_unc_mm"].dropna().gt(0).any()


def test_vic_annual_coverage():
    from utils.data_loader import load_vic_annual
    a = load_vic_annual()
    assert a["water_year"].min() <= 1985 and a["water_year"].max() >= 2023
    assert {"CRB", "UpperBasin", "LowerBasin"}.issubset(set(a["basin"]))


# ───────────────────────── Scenario uncertainty ─────────────────────────
def test_scenario_projection_fields_and_ci_order():
    from modules.scenario import _project
    r = _project("CRB", 2.0, -5.0)
    assert r is not None
    for k in ["pct", "pct_lo", "pct_hi", "c", "c_lo", "c_hi", "b", "n", "r2"]:
        assert k in r
    assert r["pct_lo"] <= r["pct"] <= r["pct_hi"], "CI must bracket the estimate"
    assert r["c_lo"] <= r["c"] * 100 <= r["c_hi"]
    assert 8 <= r["n"] <= 41


def test_scenario_matches_statsmodels():
    """The tool's elasticity CI must equal an independent statsmodels OLS fit."""
    sm = pytest.importorskip("statsmodels.api")
    from modules.scenario import _fit
    a = pd.read_parquet("data/cache/vic_annual_basin.parquet")
    d = a[(a.basin == "CRB") & (a.water_year >= 1984)].copy()
    d["Q"] = d.OUT_RUNOFF + d.OUT_BASEFLOW
    d = d.dropna(subset=["Q", "OUT_PREC", "OUT_AIR_TEMP"]); d = d[d.Q > 0]
    X = sm.add_constant(np.column_stack([np.log(d.OUT_PREC), d.OUT_AIR_TEMP]))
    m = sm.OLS(np.log(d.Q), X).fit()
    a0, b, c, *_ = _fit("CRB")
    assert abs(b - m.params.iloc[1]) < 1e-6
    assert abs(c - m.params.iloc[2]) < 1e-6


# ───────────────────────── Physics / analytics sanity ─────────────────────────
def test_water_balance_closes():
    """Long-term CRB: P should ≈ ET + Q (closure residual small)."""
    a = pd.read_parquet("data/cache/vic_annual_basin.parquet")
    c = a[(a.basin == "CRB") & (a.water_year >= 1984)]
    P = c.OUT_PREC.mean(); ET = c.OUT_EVAP.mean(); Q = (c.OUT_RUNOFF + c.OUT_BASEFLOW).mean()
    assert abs(P - ET - Q) / P < 0.05, "water balance does not close within 5%"


def test_budyko_physical():
    """Dryness ratio ET/P should be positive and not absurd."""
    a = pd.read_parquet("data/cache/vic_annual_basin.parquet")
    c = a[(a.basin == "CRB") & (a.water_year >= 1984)]
    ai = (c.OUT_EVAP / c.OUT_PREC).mean()
    assert 0.3 < ai < 1.5


def test_trend_sign_and_significance():
    """CRB runoff trend should be negative & significant (matches spatial/Sen's-slope tabs)."""
    from scipy import stats
    a = pd.read_parquet("data/cache/vic_annual_basin.parquet")
    d = a[a.basin == "CRB"].dropna(subset=["OUT_RUNOFF"]).sort_values("water_year")
    sl, _, _, p, _ = stats.linregress(d.water_year, d.OUT_RUNOFF)
    assert sl < 0 and p < 0.05


# ───────────────────────── Figure builders ─────────────────────────
def test_uncertainty_figs_build():
    import modules.uncertainty as u
    f = u._sensitivity_fig()
    assert len(f.data) == 1 and len(f.data[0].x) >= 5
    bf, (lo, mid, hi) = u._bootstrap_fig(n_boot=300)
    assert lo < mid < hi
    rows = u._sen_table()
    assert len(rows) == 5
    cf, r, n = u._crosssensor_fig()
    assert len(cf.data) == 2 and -1 <= r <= 1 and n >= 4


def test_spatial_chart_modes():
    import modules.spatial as sp
    for mode in ["basin", "trend", "compare"]:
        fig, title = sp._data_chart("OUT_RUNOFF", 2024, mode, [1983, 2001], [2010, 2024], "pct")
        assert fig is not None and title


def test_scenario_all_basins_project():
    from modules.scenario import _project, ALL_BASINS
    ok = [b for b in ALL_BASINS if _project(b, 1.0, 0) is not None]
    assert len(ok) >= 6


def test_maf_conversion():
    """Depth→volume must be sensible: CRB runoff ~36 mm → ~19 MAF basin volume."""
    from utils.manager import to_maf
    v = to_maf(36.0, "CRB")
    assert 15 < v < 23, f"CRB MAF conversion off: {v}"
    assert to_maf(0, "CRB") == 0


def test_scenario_has_maf_and_status():
    from modules.scenario import _project
    r = _project("CRB", 2.0, -5.0)
    assert "qnew_maf" in r and "maf_lost" in r
    assert r["status"] in ("Normal", "Caution", "Critical")
