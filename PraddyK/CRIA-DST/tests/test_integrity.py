"""
Extra data-integrity and consistency tests for the CRIA tool.
Run:  pytest -q
Complements test_app.py with checks on the newer views, the uncertainty helper,
and a few physically-grounded sanity conditions.
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd


def test_workflow_view_renders():
    import app
    assert app.VIEW_LAYOUTS["workflow"]() is not None


def test_governance_allocations_consistent():
    from modules import governance as g
    assert abs(sum(v for _, v in g.BASIN_ALLOC) - 16.5) < 1e-6
    assert abs(sum(v for _, v in g.LOWER_STATES) - 7.5) < 1e-6


def test_snotel_station_count_reasonable():
    from utils.data_loader import load_snotel_stations
    s = load_snotel_stations()
    assert len(s) >= 100


def test_spatial_grid_schema():
    from utils.data_loader import load_spatial
    d = load_spatial("OUT_RUNOFF")
    assert not d.empty
    assert {"water_year", "lat", "lon", "value"}.issubset(set(d.columns))


def test_scenario_warmer_drier_reduces_supply():
    """Physics: a warmer, drier climate must lower CRB runoff."""
    from modules.scenario import _project
    r = _project("CRB", 2.0, -10.0)
    assert r is not None and r["pct"] < 0


def test_trend_ci_brackets_slope_and_flags_significance():
    from utils.data_loader import trend_ci
    yrs = pd.Series(range(2000, 2020))
    rng = np.random.RandomState(0)
    y = pd.Series(np.arange(20) * 2.0 + rng.randn(20))  # strong upward trend
    r = trend_ci(y, yrs)
    assert r["lo"] <= r["slope"] <= r["hi"]
    assert r["sig"] is True and r["slope"] > 0


def test_trend_ci_handles_too_few_points():
    from utils.data_loader import trend_ci
    r = trend_ci(pd.Series([1.0, 2.0]), pd.Series([2000, 2001]))
    assert r["slope"] is None and r["sig"] is False
