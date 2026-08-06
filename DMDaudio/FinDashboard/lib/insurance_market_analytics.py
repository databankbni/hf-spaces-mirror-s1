"""Read-only analytics over the ``insurance_market`` table (premium/claims by class).

Pure DB reads + pandas shaping — no Streamlit. Cached wrappers live in
``lib/cache.py``. Underwriting metrics (GWP, share, loss/retention ratios, product
mix) come from ``insurance_market``; profitability (Net Profit, Equity, ROE, ROA)
from the regulator-sourced insurer rows in ``metrics_panel``; the Combined Ratio is
reused from ``lib.insurance_gov_statements.compute_insurance_gov_ratios``.

Market share / structure use the synthetic ``_MARKET`` row (the regulator's printed
market total) so shares stay correct even in older years that still include
now-exited insurers we don't carry as companies.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from lib.insurance_market import (
    CLASS_LABELS,
    CLASS_ORDER,
    MARKET_TOTAL_IDCODE,
)
from lib.insurance_gov_statements import compute_insurance_gov_ratios

_MKT = MARKET_TOTAL_IDCODE


def _df(db_path: str) -> pd.DataFrame:
    """Full insurance_market table as a DataFrame (empty if the table is absent)."""
    con = sqlite3.connect(db_path)
    try:
        return pd.read_sql_query(
            "SELECT IdCode, FVYear, Class, Metric, Value FROM insurance_market", con
        )
    except Exception:
        return pd.DataFrame(columns=["IdCode", "FVYear", "Class", "Metric", "Value"])
    finally:
        con.close()


def has_market_data(db_path: str) -> bool:
    con = sqlite3.connect(db_path)
    try:
        con.execute("SELECT 1 FROM insurance_market LIMIT 1").fetchone()
        return True
    except Exception:
        return False
    finally:
        con.close()


def available_years(db_path: str) -> list[int]:
    df = _df(db_path)
    return sorted(int(y) for y in df["FVYear"].unique()) if not df.empty else []


def insurer_idcodes(db_path: str) -> list[str]:
    df = _df(db_path)
    if df.empty:
        return []
    return sorted(i for i in df["IdCode"].unique() if i != _MKT)


def _pivot_total(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """(IdCode × FVYear) matrix of a metric's 'total' class value."""
    sub = df[(df["Metric"] == metric) & (df["Class"] == "total")]
    if sub.empty:
        return pd.DataFrame()
    return sub.pivot_table(index="IdCode", columns="FVYear", values="Value", aggfunc="sum")


def market_totals(db_path: str) -> pd.DataFrame:
    """Per-year market aggregates from the ``_MARKET`` row. Index = FVYear."""
    df = _df(db_path)
    if df.empty:
        return pd.DataFrame()
    mkt = df[df["IdCode"] == _MKT]
    rows = []
    for yr in sorted(mkt["FVYear"].unique()):
        m = mkt[mkt["FVYear"] == yr]

        def tot(metric):
            s = m[(m["Metric"] == metric) & (m["Class"] == "total")]["Value"]
            return float(s.iloc[0]) if len(s) else None

        gwp = tot("financial_written_premium")
        ceded = tot("financial_reinsurance_premium") or 0.0
        net_prem = (gwp - ceded) if gwp is not None else None
        incurred = tot("incurred_claims_net")
        rows.append({
            "FVYear": int(yr),
            "gwp": gwp,
            "net_premium": net_prem,
            "net_incurred_claims": incurred,
            "net_loss_ratio": (incurred / net_prem) if net_prem else None,
        })
    out = pd.DataFrame(rows).set_index("FVYear").sort_index()
    out["gwp_growth"] = out["gwp"].pct_change()
    return out


def market_uw_profit(db_path: str) -> pd.DataFrame:
    """Market-aggregate underwriting ratios + profitability by year, summed across
    ALL carried regulator insurers (premium-weighted, so it's the true market ratio).

    Underwriting components come from ``insurance_statements`` (the financial returns,
    net-earned-premium basis, so combined = loss + expense exactly); profitability
    (net profit, equity, assets) from the regulator-sourced ``metrics_panel`` rows.

    Columns (index = FVYear): nep, loss, expense, combined, net_profit, equity,
    assets, np_margin (NP ÷ NEP), roe, roa. Ratios are fractions.
    """
    con = sqlite3.connect(db_path)
    try:
        is_rows = con.execute(
            "SELECT FVYear, LineCode, SUM(Value) FROM insurance_statements "
            "WHERE Statement='IS' GROUP BY FVYear, LineCode"
        ).fetchall()
        ids = [str(r[0]) for r in con.execute(
            "SELECT DISTINCT IdCode FROM insurance_statements").fetchall()]
        mp = {}
        if ids:
            ph = ",".join("?" * len(ids))
            mp = {int(r[0]): (r[1], r[2], r[3]) for r in con.execute(
                f"SELECT FVYear, SUM(COALESCE(NetProfit,0)), SUM(COALESCE(TotalEquity,0)), "
                f"SUM(COALESCE(TotalAssets,0)) FROM metrics_panel "
                f"WHERE IdCode IN ({ph}) GROUP BY FVYear", ids).fetchall()}
    except Exception:
        return pd.DataFrame()
    finally:
        con.close()
    if not is_rows:
        return pd.DataFrame()

    by_year: dict[int, dict[str, float]] = {}
    for yr, code, val in is_rows:
        by_year.setdefault(int(yr), {})[str(code)] = float(val or 0.0)

    def s(d, codes):
        return sum(d.get(c, 0.0) for c in codes)

    rows = []
    for yr in sorted(by_year):
        d = by_year[yr]
        nep = s(d, ("00050", "00190"))                 # net earned premium
        claims = s(d, ("00110", "00250"))              # net incurred claims (cost)
        comm = s(d, ("00130", "00300"))                # net commission
        admin = s(d, ("00470", "00480", "00490", "00500", "00510"))
        loss = (abs(claims) / nep) if nep else None
        expense = ((abs(comm) + abs(admin)) / nep) if nep else None
        combined = (loss or 0) + (expense or 0) if (loss is not None or expense is not None) else None
        np_, eq, ast = mp.get(yr, (None, None, None))
        rows.append({
            "FVYear": yr, "nep": nep, "loss": loss, "expense": expense, "combined": combined,
            "net_profit": np_, "equity": eq, "assets": ast,
            "np_margin": (np_ / nep) if (np_ is not None and nep) else None,
            "roe": (np_ / eq) if (np_ is not None and eq) else None,
            "roa": (np_ / ast) if (np_ is not None and ast) else None,
        })
    return pd.DataFrame(rows).set_index("FVYear").sort_index()


def class_structure(db_path: str, year: int) -> pd.DataFrame:
    """GWP + market share by insurance class for one year (market-wide, _MARKET row)."""
    df = _df(db_path)
    if df.empty:
        return pd.DataFrame()
    m = df[(df["IdCode"] == _MKT) & (df["FVYear"] == year) & (df["Metric"] == "financial_written_premium")]
    total = m[m["Class"] == "total"]["Value"]
    total = float(total.iloc[0]) if len(total) else 0.0
    rows = []
    for cls in CLASS_ORDER:
        v = m[m["Class"] == cls]["Value"]
        gwp = float(v.iloc[0]) if len(v) else 0.0
        if gwp:
            rows.append({"class": cls, "label": CLASS_LABELS.get(cls, cls),
                         "gwp": gwp, "share": (gwp / total) if total else None})
    out = pd.DataFrame(rows)
    return out.sort_values("gwp", ascending=False).reset_index(drop=True) if not out.empty else out


def class_dynamics(db_path: str) -> pd.DataFrame:
    """Market GWP by class × year (FVYear index, one column per class label)."""
    df = _df(db_path)
    if df.empty:
        return pd.DataFrame()
    m = df[(df["IdCode"] == _MKT) & (df["Metric"] == "financial_written_premium") & (df["Class"] != "total")]
    if m.empty:
        return pd.DataFrame()
    piv = m.pivot_table(index="FVYear", columns="Class", values="Value", aggfunc="sum").fillna(0.0)
    # order + relabel columns
    cols = [c for c in CLASS_ORDER if c in piv.columns]
    piv = piv[cols]
    piv.columns = [CLASS_LABELS.get(c, c) for c in cols]
    return piv.sort_index()


def market_hhi(db_path: str, year: int) -> float | None:
    """Herfindahl–Hirschman index (Σ shareᵢ², shares in %) of GWP concentration."""
    df = _df(db_path)
    if df.empty:
        return None
    m = df[(df["FVYear"] == year) & (df["Class"] == "total") & (df["Metric"] == "financial_written_premium")]
    total = m[m["IdCode"] == _MKT]["Value"]
    total = float(total.iloc[0]) if len(total) else 0.0
    if not total:
        return None
    comp = m[m["IdCode"] != _MKT]
    return float(((comp["Value"] / total * 100.0) ** 2).sum())


def _company_names(db_path: str) -> dict[str, tuple[str, str]]:
    """IdCode -> (CompanyName, SubSector)."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT IdCode, CompanyName, SubSector FROM companies").fetchall()
        return {str(r[0]): (r[1] or str(r[0]), r[2] or "") for r in rows}
    finally:
        con.close()


def _panel_profitability(db_path: str, year: int) -> dict[str, dict]:
    """IdCode -> {NetProfit, TotalEquity, ROE, ROA} from regulator-sourced metrics_panel."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT IdCode, NetProfit, TotalEquity, ROE, ROA FROM metrics_panel WHERE FVYear=?",
            (year,),
        ).fetchall()
        return {str(r[0]): {"net_profit": r[1], "equity": r[2], "roe": r[3], "roa": r[4]}
                for r in rows}
    finally:
        con.close()


def _uw_ratios(db_path: str, idcode: str, year: int) -> tuple:
    """(loss, expense, combined) underwriting ratios for one insurer-year, reused from
    the canonical financial-statement ratio builder (net-earned-premium basis, so
    combined = loss + expense exactly)."""
    try:
        d = {r["Ratio"]: r.get(year) for r in compute_insurance_gov_ratios(db_path, idcode, [year])}
        return d.get("Loss Ratio"), d.get("Expense Ratio"), d.get("Combined Ratio")
    except Exception:
        return None, None, None


def company_table(db_path: str, year: int) -> pd.DataFrame:
    """One row per insurer for ``year``: underwriting (market data) + profitability."""
    df = _df(db_path)
    if df.empty:
        return pd.DataFrame()
    names = _company_names(db_path)
    profit = _panel_profitability(db_path, year)

    written = _pivot_total(df, "financial_written_premium")
    reins = _pivot_total(df, "financial_reinsurance_premium")
    incurred = _pivot_total(df, "incurred_claims_net")
    mkt_gwp = float(written.loc[_MKT, year]) if (_MKT in written.index and year in written.columns) else 0.0

    rows = []
    for idc in written.index:
        if idc == _MKT or year not in written.columns:
            continue
        gwp = written.loc[idc, year]
        if pd.isna(gwp) or gwp == 0:
            continue
        ceded = reins.loc[idc, year] if (idc in reins.index and year in reins.columns) else 0.0
        ceded = 0.0 if pd.isna(ceded) else float(ceded)
        net_prem = float(gwp) - ceded  # net financial premium (retained)
        ic = incurred.loc[idc, year] if (idc in incurred.index and year in incurred.columns) else None
        ic = None if (ic is None or pd.isna(ic)) else float(ic)
        prev = written.loc[idc, year - 1] if (year - 1) in written.columns and idc in written.index else None
        prev = None if (prev is None or pd.isna(prev) or prev == 0) else float(prev)
        pf = profit.get(idc, {})
        name, sub = names.get(idc, (idc, ""))
        loss_uw, expense_uw, combined_uw = _uw_ratios(db_path, idc, year)
        rows.append({
            "IdCode": idc,
            "Company": name,
            "SubSector": sub,
            "gwp": float(gwp),
            "market_share": (float(gwp) / mkt_gwp) if mkt_gwp else None,
            "gwp_growth": (float(gwp) / prev - 1.0) if prev else None,
            "retention": (net_prem / float(gwp)) if gwp else None,
            "net_loss_ratio": (ic / net_prem) if (net_prem and ic is not None) else None,
            "loss_ratio": loss_uw,          # underwriting (financial statements, NEP basis)
            "expense_ratio": expense_uw,
            "combined_ratio": combined_uw,
            "net_profit": pf.get("net_profit"),
            "equity": pf.get("equity"),
            "roe": pf.get("roe"),
            "roa": pf.get("roa"),
        })
    out = pd.DataFrame(rows)
    return out.sort_values("gwp", ascending=False).reset_index(drop=True) if not out.empty else out


def company_timeseries(db_path: str, idcode: str) -> pd.DataFrame:
    """Per-year totals for one insurer: GWP, net loss ratio, market share. Index FVYear."""
    df = _df(db_path)
    if df.empty:
        return pd.DataFrame()
    written = _pivot_total(df, "financial_written_premium")
    reins = _pivot_total(df, "financial_reinsurance_premium")
    incurred = _pivot_total(df, "incurred_claims_net")
    if written.empty or idcode not in written.index:
        return pd.DataFrame()
    rows = []
    for yr in sorted(c for c in written.columns):
        gwp = written.loc[idcode, yr] if idcode in written.index else None
        if gwp is None or pd.isna(gwp):
            continue
        mkt = written.loc[_MKT, yr] if _MKT in written.index else None
        ceded = reins.loc[idcode, yr] if (idcode in reins.index and yr in reins.columns) else 0.0
        ceded = 0.0 if pd.isna(ceded) else float(ceded)
        net_prem = float(gwp) - ceded
        ic = incurred.loc[idcode, yr] if (idcode in incurred.index and yr in incurred.columns) else None
        ic = None if (ic is None or pd.isna(ic)) else float(ic)
        rows.append({
            "FVYear": int(yr),
            "gwp": float(gwp),
            "market_share": (float(gwp) / float(mkt)) if (mkt and not pd.isna(mkt)) else None,
            "net_loss_ratio": (ic / net_prem) if (net_prem and ic is not None) else None,
        })
    return pd.DataFrame(rows).set_index("FVYear").sort_index() if rows else pd.DataFrame()


def company_class_mix(db_path: str, idcode: str) -> pd.DataFrame:
    """For one insurer: GWP and net loss ratio by class × year.

    Returns long form: columns [class, label, FVYear, gwp, net_loss_ratio].
    """
    df = _df(db_path)
    if df.empty:
        return pd.DataFrame()
    c = df[df["IdCode"] == idcode]
    if c.empty:
        return pd.DataFrame()
    rows = []
    for yr in sorted(c["FVYear"].unique()):
        cy = c[c["FVYear"] == yr]
        for cls in CLASS_ORDER:
            w = cy[(cy["Class"] == cls) & (cy["Metric"] == "financial_written_premium")]["Value"]
            gwp = float(w.iloc[0]) if len(w) else 0.0
            if not gwp:
                continue
            rp = cy[(cy["Class"] == cls) & (cy["Metric"] == "financial_reinsurance_premium")]["Value"]
            ic = cy[(cy["Class"] == cls) & (cy["Metric"] == "incurred_claims_net")]["Value"]
            ceded = float(rp.iloc[0]) if len(rp) else 0.0
            net_prem = gwp - ceded
            ic = float(ic.iloc[0]) if len(ic) else None
            rows.append({
                "class": cls, "label": CLASS_LABELS.get(cls, cls), "FVYear": int(yr),
                "gwp": gwp, "net_loss_ratio": (ic / net_prem) if (net_prem and ic is not None) else None,
            })
    return pd.DataFrame(rows)
