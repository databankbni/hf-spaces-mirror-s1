import sqlite3
from pathlib import Path

import pandas as pd

# Canonicalize alias spellings so old/new taxonomy variants collapse to one.
LINE_ITEM_ALIASES = {
    "Staff Costs": "Personnel expense",
    "Depreciation and Amortization": "Depreciation and amortisation",
    "Taxes other than income tax": "Taxes other than on income",
    "Income Tax Expense": "Income tax",
    "Profit(loss)": "Profit/(loss)",
    # Impairment spelling variants. The reportal form carries the SAME quantity
    # twice per family — the IS line ("ფინანსური აქტივების გაუფასურების (ხარჯი) /
    # აღდგენა" → paren spelling) and a breakdown-block total ("გაუფასურების
    # (ხარჯი) / აღდგენა ფინანსურ აქტივებზე" → no-paren spelling); the 2021-era
    # exports also stamped a double-space raw-English spelling on both rows.
    # Without these aliases both rows sit in IS_OpEx and EBITDA counts the
    # impairment twice (e.g. GCAP 404549690 FY2024: -3,562K duplicated).
    "Impairment loss/reversal of financial assets": "Impairment (loss)/reversal of financial assets",
    "Impairment loss/reversal of  financial assets": "Impairment (loss)/reversal of financial assets",
    "Impairment loss/reversal of non-financial assets": "Impairment (loss)/reversal of non- financial assets",
    "Impairment loss/reversal of  non- financial assets": "Impairment (loss)/reversal of non- financial assets",
}

# Category overrides: certain line items belong to a different category than the DB records.
# Applied after fetching rows, before dedup. The mapping uses the *canonical* (post-alias) name.
LINE_ITEM_CATEGORY_OVERRIDES = {
    "Other financial expense": "IS_InterestExpense",
    # The FY2020-21 double-space impairment spellings were ingested under
    # IS_OtherExpense; post-alias they must share their IS_OpEx twins' category
    # so the dedup key matches (dedup keys on Category) and the line lands in
    # EBITDA rather than being counted again below it.
    "Impairment (loss)/reversal of financial assets": "IS_OpEx",
    "Impairment (loss)/reversal of non- financial assets": "IS_OpEx",
}

# Merge targets: certain line items should be SUMMED into a target name rather than
# kept separate. Unlike LINE_ITEM_ALIASES (which dedups identical duplicates), this
# combines distinct rows whose values should be added together. Applied AFTER dedup.
LINE_ITEM_MERGE_TARGETS = {
    "Other financial expense": "Interest Expense",
}

# Section overrides: certain line items are mislabeled at the Section level in the DB.
# These cash-flow reconciliation rows are stored under Section='BS_Assets'/Category='BS_Cash'
# but really belong to the cash-flow statement (Section='CF'). The override moves them so
# BS queries (section_prefix='BS_') don't return them, while CF analytics can still find them
# under the canonical Section.
LINE_ITEM_SECTION_OVERRIDES = {
    "Cash at the beginning of the year": "CF",
    "Cash at the end of the year": "CF",
    "Cash and Cash Equivalents at Beginning of Year": "CF",
    "Cash and Cash Equivalents at End of Year": "CF",
    "Effect of exchange rate changes on cash and cash equivalents": "CF",
}

def _canonical(name: str) -> str:
    return LINE_ITEM_ALIASES.get(name, name)

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    # Apply performance PRAGMAs. These are cheap (microseconds) and idempotent,
    # so applying on every connect is fine. We deliberately keep the existing
    # open/close lifecycle (no st.cache_resource) so callers' conn.close()
    # calls continue to work as before.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA mmap_size = 268435456")  # 256 MB
    conn.execute("PRAGMA cache_size = -65536")    # 64 MB
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn

def get_companies(db_path: str) -> list[tuple[str, str]]:
    """Return list of (IdCode, CompanyName) tuples, sorted by IdCode."""
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT IdCode, CompanyName FROM company_metadata ORDER BY IdCode"
        )
        return [(row[0], row[1]) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_curated_sector_buckets(db_path: str) -> dict[str, list[str]]:
    """Return ``{Sector: [IdCode, IdCode, ...]}`` for the curated-sector taxonomy
    seeded via ``scripts/enrich_company_descriptions.py``.

    Each bucket's IdCode list is sorted by descending latest IS_Revenue (or
    IS_InterestIncome for banks), so when the Sector View loads a bucket the
    largest companies appear first. Buckets are returned ordered by company
    count (largest bucket first) for sensible UI presentation.

    Returns an empty dict when the DB pre-dates the Sector migration — keeps
    the Sector View functional against a stale cache.
    """
    conn = _connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "Sector" not in cols:
            return {}
        rows = conn.execute(
            """
            WITH revs AS (
                SELECT IdCode, SUM(Value) AS R
                FROM financial_data
                WHERE ItemType='TOTAL'
                  AND Category IN ('IS_Revenue', 'IS_InterestIncome')
                GROUP BY IdCode
            )
            SELECT c.Sector, c.IdCode, COALESCE(MAX(r.R), 0) AS RankR
            FROM companies c
            LEFT JOIN revs r ON r.IdCode = c.IdCode
            WHERE c.Sector IS NOT NULL AND c.Sector != ''
            GROUP BY c.Sector, c.IdCode
            ORDER BY c.Sector, RankR DESC
            """
        ).fetchall()
    finally:
        conn.close()

    buckets: dict[str, list[str]] = {}
    for sector, idc, _ in rows:
        buckets.setdefault(sector, []).append(idc)
    # Re-order keys by descending company count for UI display.
    return dict(sorted(buckets.items(), key=lambda kv: -len(kv[1])))


def get_sectors(db_path: str) -> dict[str, str]:
    """Return ``{IdCode: Sector}`` for every company that has one.

    Empty dict when the Sector column doesn't exist or no rows are
    classified yet. Cheap one-shot query — used by views that want to
    decorate company lists with the curated sector label.
    """
    conn = _connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "Sector" not in cols:
            return {}
        rows = conn.execute(
            "SELECT IdCode, Sector FROM companies "
            "WHERE Sector IS NOT NULL AND Sector != ''"
        ).fetchall()
    finally:
        conn.close()
    return {idc: sec for idc, sec in rows}


def get_sub_sectors(db_path: str) -> dict[str, str]:
    """Return ``{IdCode: SubSector}`` for every company that has one.

    Empty dict when the SubSector column doesn't exist or no rows are
    classified yet. Cheap one-shot query — used by views that want to
    decorate company lists with the finer-grained label.
    """
    conn = _connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "SubSector" not in cols:
            return {}
        rows = conn.execute(
            "SELECT IdCode, SubSector FROM companies "
            "WHERE SubSector IS NOT NULL AND SubSector != ''"
        ).fetchall()
    finally:
        conn.close()
    return {idc: sub for idc, sub in rows}

def get_years_available(db_path: str, idcode: str, min_is_rows: int = 5, min_bs_rows: int = 5,
                        table: str = "financial_data") -> list[int]:
    """Return sorted list of fiscal years where the company has substantive data
    in BOTH the income statement AND the balance sheet.

    A year is included only if it has at least ``min_is_rows`` non-zero IS rows
    AND at least ``min_bs_rows`` non-zero BS rows. This filters out stub years
    where only a couple of items were recorded (e.g. 2016 for many companies
    only has 1–2 IS rows alongside a partial BS), since such years would render
    as a nearly-empty Income Statement in the dashboard.
    """
    if table not in FINANCIAL_TABLES:
        raise ValueError(f"unsupported financial table: {table!r}")
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            f"""
            SELECT FVYear
            FROM {table}
            WHERE IdCode = ? AND Value != 0
            GROUP BY FVYear
            HAVING SUM(CASE WHEN Section = 'IS' THEN 1 ELSE 0 END) >= ?
               AND SUM(CASE WHEN Section LIKE 'BS_%' THEN 1 ELSE 0 END) >= ?
            ORDER BY FVYear
            """,
            (idcode, min_is_rows, min_bs_rows),
        )
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

def get_financial_data_bulk(db_path: str, idcodes: list[str]) -> pd.DataFrame:
    """Every stored financial_data row for the given companies, as a DataFrame.

    Columns: IdCode, FVYear, Section, Category, ItemType, LineItemENG, Value.
    Raw stored values (no canonicalization) — the complete data dump backing the
    Sector View "Download all financial data" export. Returns an empty DataFrame
    (with the right columns) when no idcodes are given.
    """
    cols = ["IdCode", "FVYear", "Section", "Category", "ItemType", "LineItemENG", "Value"]
    if not idcodes:
        return pd.DataFrame(columns=cols)
    placeholders = ",".join("?" * len(idcodes))
    sql = (
        f"SELECT IdCode, FVYear, Section, Category, ItemType, LineItemENG, Value "
        f"FROM financial_data WHERE IdCode IN ({placeholders}) "
        f"ORDER BY IdCode, FVYear, Section, Category, LineItemENG"
    )
    conn = _connect(db_path)
    try:
        return pd.read_sql_query(sql, conn, params=list(idcodes))
    finally:
        conn.close()


#: Tables shaped like financial_data that the read layer may serve. The
#: sidecar carries the individual-basis statements of dual-basis filers
#: (scripts/build_individual_basis.py) for the Single-Company basis toggle.
FINANCIAL_TABLES = ("financial_data", "financial_data_individual")


def get_financial_rows(
    db_path: str,
    idcode: str,
    years: list[int],
    section_prefix: str | None = None,
    table: str = "financial_data",
) -> list[dict]:
    """
    Return raw financial-data rows for a company across years.

    section_prefix='IS' returns IS rows; 'BS_' returns balance sheet rows.
    None returns all sections. ``table`` selects the source (allowlisted in
    :data:`FINANCIAL_TABLES` — the name is interpolated into SQL).
    """
    if not years:
        return []
    if table not in FINANCIAL_TABLES:
        raise ValueError(f"unsupported financial table: {table!r}")

    placeholders = ",".join("?" * len(years))
    sql = f"""
        SELECT DISTINCT FVYear, Section, Category, ItemType, LineItemENG, Value
        FROM {table}
        WHERE IdCode = ? AND FVYear IN ({placeholders})
    """
    params: list = [idcode, *years]

    if section_prefix is not None:
        if section_prefix.endswith("_"):
            sql += " AND Section LIKE ?"
            params.append(section_prefix + "%")
        else:
            sql += " AND Section = ?"
            params.append(section_prefix)

    sql += " ORDER BY FVYear, Section, Category, LineItemENG"

    conn = _connect(db_path)
    try:
        cursor = conn.execute(sql, params)
        cols = [d[0] for d in cursor.description]
        raw = [dict(zip(cols, row)) for row in cursor.fetchall()]
        return canonicalize_rows(raw, section_prefix)
    finally:
        conn.close()


def canonicalize_rows(raw: list[dict], section_prefix: str | None = None) -> list[dict]:
    """Apply the full canonicalization pipeline to already-fetched rows.

    This is the read-layer SSOT (Sprint 5): both ``get_financial_rows`` (the
    per-company IS/BS view loader) and ``lib.screener.build_metrics_table``
    (the bulk metrics_panel builder) run their rows through this exact
    function, so alias/override/dedup/merge semantics can never diverge
    between the two surfaces.

    Rows must carry FVYear, Section, Category, LineItemENG, Value (ItemType
    passes through untouched). Rows are mutated in place. Steps:

    1. Canonicalize names (LINE_ITEM_ALIASES), apply LINE_ITEM_CATEGORY_OVERRIDES
       and LINE_ITEM_SECTION_OVERRIDES.
    2. Re-check ``section_prefix`` AFTER the section override and drop rows that
       no longer match (an override may move a row out of the requested section).
    3. Dedup on (FVYear, Section, Category, LineItemENG). When an alias collision
       occurs (two distinct DB names canonicalize to the same item), keep the row
       with the LARGER ABSOLUTE VALUE rather than the first row — otherwise a
       zero-value legacy row can crowd out the real non-zero new-taxonomy row
       (e.g. Nikora 2024 has 'Taxes other than income tax' = 0 alongside
       'Taxes other than on income' = -6,234K; keep-first would drop the -6,234K).
    4. Sum merge-target rows (LINE_ITEM_MERGE_TARGETS) via _apply_line_item_merges.

    NOTE: callers iterating multiple companies must call this per company —
    the dedup key does not include IdCode.
    """
    by_key: dict = {}  # key -> index in out
    out: list = []
    for r in raw:
        r["LineItemENG"] = _canonical(r["LineItemENG"])
        if r["LineItemENG"] in LINE_ITEM_CATEGORY_OVERRIDES:
            r["Category"] = LINE_ITEM_CATEGORY_OVERRIDES[r["LineItemENG"]]
        if r["LineItemENG"] in LINE_ITEM_SECTION_OVERRIDES:
            r["Section"] = LINE_ITEM_SECTION_OVERRIDES[r["LineItemENG"]]
        if section_prefix is not None:
            if section_prefix.endswith("_"):
                if not r["Section"].startswith(section_prefix):
                    continue
            elif r["Section"] != section_prefix:
                continue
        key = (r["FVYear"], r["Section"], r["Category"], r["LineItemENG"])
        if key in by_key:
            existing = out[by_key[key]]
            if abs(r["Value"] or 0) > abs(existing["Value"] or 0):
                out[by_key[key]] = r
            continue
        by_key[key] = len(out)
        out.append(r)
    return _apply_line_item_merges(out)


def _apply_line_item_merges(rows: list[dict]) -> list[dict]:
    """Sum rows that share a merge target into a single row.

    For each row whose LineItemENG is in LINE_ITEM_MERGE_TARGETS, rename it to the
    target name and combine with any existing row sharing the same target.
    Combination key is (FVYear, Section, Category, target_name). Preserves the
    first-seen order for stability.
    """
    if not rows:
        return rows
    accum: dict = {}
    order: list = []
    for r in rows:
        name = r["LineItemENG"]
        target = LINE_ITEM_MERGE_TARGETS.get(name, name)
        key = (r["FVYear"], r["Section"], r["Category"], target)
        if key not in accum:
            new_r = dict(r)
            new_r["LineItemENG"] = target
            accum[key] = new_r
            order.append(key)
        else:
            accum[key]["Value"] = (accum[key]["Value"] or 0) + (r["Value"] or 0)
    return [accum[k] for k in order]


def universe_stats(db_path: str) -> dict[str, int]:
    """Return high-level counts for the Home page's "Universe" panel.

    Keys:
      - n_companies: distinct companies in company_metadata
      - year_min / year_max: fiscal-year coverage in financial_data
      - n_rows: total financial_data rows

    All values are plain ints so they render cleanly in markdown.
    """
    conn = _connect(db_path)
    try:
        n_companies = conn.execute(
            "SELECT COUNT(*) FROM company_metadata"
        ).fetchone()[0]
        year_min, year_max = conn.execute(
            "SELECT MIN(FVYear), MAX(FVYear) FROM financial_data"
        ).fetchone()
        n_rows = conn.execute(
            "SELECT COUNT(*) FROM financial_data"
        ).fetchone()[0]
        return {
            "n_companies": int(n_companies),
            "year_min": int(year_min),
            "year_max": int(year_max),
            "n_rows": int(n_rows),
        }
    finally:
        conn.close()


def get_form_type(db_path: str, idcode: str) -> str:
    """Return the company's financial-statement format type.

    Reads ``companies.LatestFormType``. Maps:
      - 'bank'    → 'bank'
      - 'insurer' → 'insurer'
      - everything else (NULL, missing idcode, 'nonfin', 'cat3_simplified', any
        unknown future value) → 'nonfin'
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT LatestFormType FROM companies WHERE IdCode = ?", (idcode,)
        ).fetchone()
    finally:
        conn.close()
    if row and row[0] in ("bank", "insurer"):
        return row[0]
    return "nonfin"


def get_filing_meta(db_path: str, idcode: str) -> dict[int, dict]:
    """Per-year filing provenance from ``company_filing_meta``.

    Returns ``{FVYear: {"category", "form_type", "report_year", "own_year"}}``.

    Empty dict when the table is absent — a deployed DB predating
    ``scripts/build_filing_meta.py`` simply has no per-year provenance, and
    callers fall back to the latest-filing fields on ``companies``. Deliberately
    does NOT fall back here: silently serving ``LatestCategory`` for every year
    would reintroduce the exact error this table exists to prevent (a FY2024
    category stamped on FY2019 figures).
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT FVYear, Category, FormType, ReportYear, IsOwnYearFiling "
            "FROM company_filing_meta WHERE IdCode = ?",
            (str(idcode),),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
    return {
        int(r[0]): {
            "category": r[1],
            "form_type": r[2],
            "report_year": r[3],
            "own_year": bool(r[4]),
        }
        for r in rows
    }


def get_latest_filing_meta(db_path: str, idcode: str) -> dict:
    """Latest-filing category/form type from ``companies``.

    The fallback for a DB without ``company_filing_meta``. Correct for the
    company's most recent year and nothing else, which is how callers must use it.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT LatestCategory, LatestFormType FROM companies WHERE IdCode = ?",
            (str(idcode),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"category": None, "form_type": None}
    return {"category": row[0], "form_type": row[1]}


def get_revaluation_rows(db_path: str, idcode: str) -> list[dict]:
    """Non-zero balance-sheet lines whose name mentions revaluation, per year.

    A cheap pre-filter only — deciding which of these are *PP&E* revaluation
    reserves (as opposed to financial-asset or investment-property ones) is
    ``lib.filing_provenance.is_ppe_revaluation_line``'s job. Keyed on IdCode,
    which is the leading column of the ``financial_data`` primary key.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT FVYear, LineItemENG, Value FROM financial_data "
            "WHERE IdCode = ? AND Section LIKE 'BS_%' "
            "AND LOWER(LineItemENG) LIKE '%revalu%' AND Value <> 0",
            (str(idcode),),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"FVYear": int(r[0]), "LineItemENG": r[1], "Value": r[2]} for r in rows
    ]


def get_report_pdf_urls(db_path: str, idcode: str) -> dict[int, str]:
    """Return ``{FVYear: direct_pdf_url}`` for a company from ``report_pdf_links``.

    These are precomputed reportal.ge annual-report PDF links (built by
    ``scripts/build_report_links.py``). Only rows with a resolved URL are
    returned. Missing table (old DB) or missing company → empty dict, so the
    live-resolution fallback in ``lib/ui.py`` still applies.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT FVYear, PdfUrl FROM report_pdf_links "
            "WHERE IdCode = ? AND PdfUrl IS NOT NULL",
            (str(idcode),),
        ).fetchall()
    except sqlite3.OperationalError:
        # report_pdf_links not present (DB predates the feature).
        return {}
    finally:
        conn.close()
    return {int(y): url for y, url in rows}


def get_dividends(db_path: str, idcode: str) -> dict:
    """Dividends declared per year from the ``equity_movements`` SOCE data.

    Returns ``{"dividends": {FVYear: gel}, "covered": {FVYear, ...}}`` where
    dividend values keep the filed sign (negative = distribution to owners).
    ``covered`` lists the years with ANY clean equity-movement rows, so a
    covered year absent from ``dividends`` means "declared zero" — distinct
    from "no SOCE data". Suspect filings (internally inconsistent numbers) are
    excluded from both. Missing table/view (DB predates the feature) → empty.
    """
    conn = _connect(db_path)
    try:
        div_rows = conn.execute(
            "SELECT FVYear, DividendsDeclared FROM v_dividends "
            "WHERE IdCode = ? AND Suspect = 0",
            (str(idcode),),
        ).fetchall()
        cov_rows = conn.execute(
            "SELECT DISTINCT FVYear FROM equity_movements "
            "WHERE IdCode = ? AND Suspect = 0",
            (str(idcode),),
        ).fetchall()
    except sqlite3.OperationalError:
        # equity_movements / v_dividends not present (DB predates the feature).
        return {"dividends": {}, "covered": set()}
    finally:
        conn.close()
    return {
        "dividends": {int(y): float(v) for y, v in div_rows if v is not None},
        "covered": {int(y) for (y,) in cov_rows},
    }


def get_company_ownership(db_path: str, idcode: str) -> dict | None:
    """Return the precomputed companyinfo.ge detail dict for a company, or None.

    Reads ``company_ownership`` (built by ``scripts/build_company_ownership.py``),
    gzip-decompressing the stored DetailGz blob into the detail dict so callers
    can pass it straight to ``lib.companyinfo.summarize_affiliations`` — the same
    shape ``fetch_company_detail`` returns from the live API.

    None means: no precomputed row, a 'notfound'/'error' status, or the table is
    absent (old DB). Callers use that to decide whether to fall back to a live
    fetch (Ownership page only) — the whole point being that the statements never
    make a live companyinfo call.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT DetailGz FROM company_ownership "
            "WHERE IdCode = ? AND Status = 'ok' AND DetailGz IS NOT NULL",
            (str(idcode),),
        ).fetchone()
    except sqlite3.OperationalError:
        # company_ownership not present (DB predates the feature).
        return None
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    try:
        import gzip
        import json as _json
        # DetailGz is gzip-compressed UTF-8 JSON (~12x smaller than raw — the
        # full companyinfo detail incl. historical roster is ~15KB/co, so the
        # table is 176MB raw vs 18MB compressed).
        return _json.loads(gzip.decompress(row[0]).decode("utf-8"))
    except (ValueError, TypeError, OSError):
        return None


def get_bia_directory(db_path: str, idcode: str) -> dict | None:
    """Return the verified bia.ge directory detail for a company, or None.

    Reads ``bia_directory`` (built by ``scripts/build_bia_directory.py``),
    gzip-decompressing ``DetailGz`` into the dict ``lib.bia.parse_company_page``
    produced: name, products, activity categories, activity fields, NACE codes,
    legal form, address.

    **Only ``Status='ok'`` rows are returned, and an ``ok`` row is one whose page
    ``საიდენტიფიკაციო კოდი`` was verified equal to this IdCode.** The
    ``code_mismatch`` / ``no_code`` / ``notfound`` rows are deliberately readable
    only by going to the table directly — a caller asking "what does bia say
    about this company?" must never be handed a same-named different company.
    None means: no row, an unverified row, or the table is absent (older DB).
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT DetailGz FROM bia_directory "
            "WHERE IdCode = ? AND Status = 'ok' AND DetailGz IS NOT NULL",
            (str(idcode),),
        ).fetchone()
    except sqlite3.OperationalError:
        # bia_directory not present (DB predates the feature).
        return None
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    try:
        import gzip
        import json as _json
        return _json.loads(gzip.decompress(row[0]).decode("utf-8"))
    except (ValueError, TypeError, OSError):
        return None


def iter_bia_directory(db_path: str):
    """Yield ``(IdCode, detail_dict)`` for every code-VERIFIED bia.ge row.

    Streamed, like ``iter_ownership_details``, so a whole-corpus sector
    cross-check never holds every payload plus its gzip blob in memory. Rows that
    fail to decompress are skipped; a missing table yields nothing.
    """
    import gzip
    import json as _json

    conn = _connect(db_path)
    try:
        try:
            cursor = conn.execute(
                "SELECT IdCode, DetailGz FROM bia_directory "
                "WHERE Status = 'ok' AND DetailGz IS NOT NULL"
            )
        except sqlite3.OperationalError:
            return
        for idcode, blob in cursor:
            try:
                yield str(idcode), _json.loads(gzip.decompress(blob).decode("utf-8"))
            except (ValueError, TypeError, OSError):
                continue
    finally:
        conn.close()


def get_consolidated_company_years(db_path: str) -> set[tuple[str, int]]:
    """``(IdCode, FVYear)`` pairs that filed on a CONSOLIDATED basis THAT YEAR.

    Read from ``filing_basis`` (built by ``scripts/build_filing_basis.py`` from
    the raw exports' ``CategoryMain``; "ჯგუფი" => consolidated). Strictly better
    information than ``get_consolidated_idcodes``, which reports only the
    company's *latest* basis.

    NOT currently used by the de-dup gate — see ``lib/consolidation.py`` for the
    measurement showing the per-year swap is revenue-neutral while adding
    weakly-evidenced drops, and that the real gap is missing ownership *vintage*.
    Kept as the input for the planned individual/consolidated switcher and for
    re-measuring the gate once ownership start dates exist.

    Returns an EMPTY set when the table is absent, which callers must treat as
    "no per-year data" — not as "nothing is consolidated".
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT IdCode, FVYear FROM filing_basis WHERE HasConsolidated = 1"
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()
    return {(str(r[0]), int(r[1])) for r in rows}


def get_consolidated_idcodes(db_path: str) -> set[str]:
    """IdCodes whose LATEST filing is on a CONSOLIDATED basis (``companies.
    LatestIsConsolidated = 1``).

    This is the reportal-sourced statement-basis flag: a consolidated filer's
    Revenue/EBITDA/Assets already contain its subsidiaries. NOTE: it is a
    *latest-filing* fact — prefer :func:`get_consolidated_company_years` for the
    de-dup gate and use this only as a fallback. Empty set if the column is absent.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT IdCode FROM companies WHERE LatestIsConsolidated = 1"
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()
    return {str(r[0]) for r in rows}


def get_ownership_edges(db_path: str) -> list[dict]:
    """All corporate ownership edges from ``ownership_edges`` as edge dicts.

    Each edge ``{"child","parent","share","is_internal","parent_name","since"}`` means
    ``child`` is owned BY ``parent`` (``share`` %); ``is_internal`` is True iff the
    parent itself files with us. Built by ``scripts/build_ownership_edges.py`` from
    ``company_ownership``. Empty list when the table is absent (older DB) so callers
    degrade to "no ownership data" rather than erroring. See ``lib/ownership.py``.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ChildIdCode, ParentIdCode, Share, IsInternal, ParentName, "
            "SinceDate FROM ownership_edges"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return [
        {"child": str(r[0]), "parent": str(r[1]), "share": r[2] or 0.0,
         "is_internal": bool(r[3]), "parent_name": r[4],
         "since": (r[5] if len(r) > 5 else None)}
        for r in rows
    ]


def iter_ownership_details(db_path: str):
    """Yield ``(IdCode, detail_dict)`` for every successfully-scraped company.

    The whole ``company_ownership`` table, streamed rather than fetched, so
    building the owners index never holds 9k decompressed registry payloads and
    9k gzip blobs in memory at once. Rows that fail to decompress are skipped —
    one corrupt blob must not sink the index. Missing table (older DB) yields
    nothing, so the Owners view shows its empty state instead of erroring.
    """
    import gzip
    import json as _json

    conn = _connect(db_path)
    try:
        try:
            cursor = conn.execute(
                "SELECT IdCode, DetailGz FROM company_ownership "
                "WHERE Status = 'ok' AND DetailGz IS NOT NULL"
            )
        except sqlite3.OperationalError:
            return
        for idcode, blob in cursor:
            try:
                yield str(idcode), _json.loads(gzip.decompress(blob).decode("utf-8"))
            except (ValueError, TypeError, OSError):
                continue
    finally:
        conn.close()


def get_latest_panel_metrics(db_path: str, metrics: tuple[str, ...]) -> dict:
    """Every company's LATEST filed year from ``metrics_panel``, keyed by IdCode.

    Returns ``{idcode: {"year": int, "metrics": {metric: value}}}`` in one scan.
    The owners leaderboard weights ~11k portfolios against this; doing it as a
    per-company lookup inside that loop is the shape that takes minutes.

    ``ORDER BY IdCode, FVYear`` ascending means the last write per IdCode wins,
    which is the latest year — no GROUP BY, no window function.
    """
    cols = ", ".join(metrics)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT IdCode, FVYear, {cols} FROM metrics_panel ORDER BY IdCode, FVYear"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
    return {
        str(r[0]): {"year": r[1], "metrics": dict(zip(metrics, r[2:]))}
        for r in rows
    }


def get_insurance_gov_source_urls(db_path: str, idcode: str) -> dict[int, str]:
    """Return ``{FVYear: insurance.gov.ge source-XLSX URL}`` for a regulator insurer.

    Built from the ``SourceFileId`` recorded per row in ``insurance_statements``
    (the actual data source behind a regulator-covered insurer's statements).
    Missing table / uncovered company → empty dict.
    """
    from lib.insurance_gov import insurance_gov_source_url

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT FVYear, SourceFileId FROM insurance_statements "
            "WHERE IdCode = ? AND SourceFileId IS NOT NULL",
            (str(idcode),),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
    return {int(y): insurance_gov_source_url(fid) for y, fid in rows}
