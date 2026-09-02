"""Manual translations + synonym aliases + merge consolidations for Phase 3 ingest.

These supplement the auto-built `geo_to_eng_map` (from 2023-24 files) and the
existing `LINE_ITEM_ALIASES` / `LINE_ITEM_MERGE_TARGETS` from `lib/data_loader.py`.

The rebuild pipeline applies these in addition to the existing ones, so the final
v2 database has clean, deduped line items regardless of which year/file the data
came from.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 1) Manual Georgian → English translations
# These cover line items present in 2018–2022 raw files whose Georgian spelling
# differs from the spelling used in 2023–24 files. The auto-built map can't
# catch them because there's no overlap.
# ---------------------------------------------------------------------------
MANUAL_GEO_TO_ENG: dict[str, str] = {
    # === IFRS 17 insurer top line (2023+ filings) ===
    # Insurers adopted IFRS 17 (effective Jan 2023) and overhauled their P&L.
    # The new top-line measure "Insurance revenue" (სადაზღვევო ამონაგები) has no
    # English in the source export and no pre-2023 overlap, so the auto-built map
    # can't catch it — without this, 2023+ insurers ingest with NO revenue, the
    # sector aggregate undercounts ΣRevenue, and NetMargin blows up (242% for
    # 2024). This is the insurer equivalent of a bank's Operating income. (The
    # full IFRS-17 expense/reinsurance detail is a separate, careful follow-up —
    # several of those lines collide with auto-mapped labels and need per-line
    # reconciliation to avoid double-counting.)
    "სადაზღვევო ამონაგები": "Insurance revenue",
    # IFRS-17 insurer P&L COMPONENTS (2023+). All NULL-English in the source and
    # no pre-2023 overlap. These are the income/expense lines that sum (with the
    # already-mapped interest income / tax / etc.) to the reported net profit.
    # SUBTOTALS (insurance service result, net reinsurance result, net insurance
    # finance result) and the DUPLICATE "Net investment income"
    # (წმინდა საინვესტიციო შემოსავალი — equals the auto-mapped Interest income)
    # are deliberately NOT translated, so the ingest drops them (no double-count).
    "გამოშვებული სადაზღვევო ხელშეკრულებებიდან წარმოქმნილი სადაზღვევო მომსახურების ხარჯები":
        "Insurance service expenses",
    "გადამზღვეველის მიერ ანაზღაურებული თანხიდან მიღებული შემოსავალი":
        "Amounts recoverable from reinsurers",
    "ხარჯები, რომელიც წარმოიშობა გადამზღვეველთათვის გადახდილი პრემიების განაწილებიდან":
        "Allocation of reinsurance premiums paid",
    "სადაზღვევო ფინანსური შემოსვალი / (ხარჯები)": "Insurance finance income / (expenses)",
    "გადაზღვევის ხელშეკრულებებთან დაკავშირებული ფინანსური შემოსავალი / (ხარჯები)":
        "Reinsurance finance income / (expenses)",
    "წილი მეკავშირე საწარმოების მოგებაში ან ზარალში": "Share of profit (loss) of associates",
    "წილი ერთობლივი საწარმოების მოგებაში ან ზარალში": "Share of profit (loss) of joint ventures",
    "წმინდა შემოსულობა / (ზარალი) სამართლიანი ღირებულებით აღრიცხული ფინანსური აქტივებიდან/ვალდებულებებიდან, მოგება (ზარალში) ასახვით":
        "Net gain (loss) on financial assets at fair value through profit or loss",
    "წმინდა შემოსულობა / (ზარალი) სხვა": "Net other gains / (losses)",
    "წმინდა შემოსულობა / (ზარალი) წარმოებული ფინანსური ინსტრუმენტებიდან":
        "Net gain (loss) from financial derivatives",
    "წმინდა შემოსულობა / (ზარალი) საინვესტიციო ქონების გაყიდვიდან ან გადაფასებიდან":
        "Net gain (loss) from sale or revaluation of investment property",
    # Generic-looking lines whose EXACT IFRS-17 Georgian phrasing is insurer-only
    # (verified: 19 insurers, 0 non-insurers carry these NULL-English; non-insurers
    # use different strings that already auto-map). Not in the auto-map, so add here.
    "უცხოური ვალუტის კურსის ცვლილებით მიღებული წმინდა შემოსულობა / (ზარალი)":
        "Net gain (loss) from foreign exchange operations",
    "სხვა შემოსავალი": "Other income",
    "ფინანსური დანახარჯები": "Finance costs",

    # === Top unmatched from phase 3 report ===
    "ფული და ფულის ეკვივალენტები": "Cash and cash equivalents",
    "ვალდებულებების და ხარჯების ანარიცხები": "Provisions for liabilities and charges",
    "გაუნაწილებელი მოგება / ზარალი": "Retained earnings / (Accumulated deficit)",
    "სხვა რეზერვები": "Other reserves",
    "ფინანსური იჯარის ვალდებულება": "Finance lease payable",
    "სავაჭრო მოთხოვნები": "Trade receivables",
    "გადახდილი ავანსები": "Other current assets",
    "სხვა მიმდინარე აქტივები": "Other current assets",
    "მიმდინარე სასესხო ვალდებულებები": "Current borrowings",
    "გრძელვადიანი სასესხო ვალდებულებები": "Non current borrowings",
    "მოგება/(ზარალი)": "Profit/(loss)",
    "მთლიანი სრული შემოსავალი/ (ზარალი)": "Total comprehensive income / (loss)",
    "ცვეთა და ამორტიზაცია": "Depreciation and amortisation",
    "მოგება/(ზარალი) მოგების გადასახადის ხარჯამდე განგრძობითი ოპერაციებიდან":
        "Profit/(loss) before tax from continuing operations",
    "მოგების გადასახადი": "Income tax",
    "ძირითადი საშუალების (მათ შორის ბიოლოგიური აქტივის) გადაფასების რეზერვი":
        "Property, plant and equipment revaluation reserve",
    "სხვა სრული შემოსავალი / (ზარალი), სულ":
        "Total other comprehensive (loss) income",
    "რეალიზებული პროდუქციის თვითღირებულება": "Cost of goods sold",
    "სხვა წმინდა არასაოპერაციო შემოსავალი/ (ხარჯი)":
        "Other Net Non-Operating Income / (Expense)",
    "წმინდა ფულადი სახსრები საოპერაციო საქმიანობიდან":
        "Net cash from operating activities",
    # Force the high-volume Georgian phrase to "Other operating income". The
    # auto-translator otherwise picks "Other income" (0.773 confidence, 27,359
    # occurrences vs runner-up "Other operating income" at 6,202), which collapses
    # the OpEx-side row into the catch-all Other income bucket.
    "სხვა საოპერაციო შემოსავალი": "Other operating income",
}


# ---------------------------------------------------------------------------
# 2) Extra English-name aliases (same-meaning, different-name items)
# Used IN ADDITION to LINE_ITEM_ALIASES in lib/data_loader.py.
# Maps non-canonical -> canonical. Apply with the same dedup-keep-max-magnitude
# semantics.
# ---------------------------------------------------------------------------
EXTRA_LINE_ITEM_ALIASES: dict[str, str] = {
    # Staff / Personnel / Employee benefits family.
    # NOTE: "Employee benefits" is deliberately NOT aliased here. Every raw
    # row with that name (16,864 rows) is filed on the BS sheet — it is the
    # accrued-employee-benefits LIABILITY line of the nonfin BS form, not a
    # wage expense. Aliasing it into "Personnel expense" merged BS balances
    # into the P&L personnel line (and the per-filing magnitude tie-break
    # could then DROP the real expense row). It now classifies as a BS
    # liability via EXTRA_TAXONOMY_PATCHES + the BS-sheet gate.
    "Staff costs expense": "Personnel expense",
    "Salary expense": "Personnel expense",
    "Salaries and wages": "Personnel expense",
    "Wages and salaries": "Personnel expense",
    # Cost of goods sold canonical spelling
    "Cost of Goods Sold": "Cost of goods sold",
    # Interest-expense note-header vs. P&L total. "Interest expense from:" is a
    # note-breakdown HEADER (the trailing colon gives it away) that reportal
    # sometimes emits carrying the section total, and sometimes ALONGSIDE a clean
    # "Interest Expense" total (esp. FY2020 exports). taxonomy_patches maps the
    # header to ItemType=TOTAL so sole-header filings still get a total — but when
    # BOTH land as TOTAL, _sum_category summed them and DOUBLE-COUNTED interest
    # expense (~660 company-years). Aliasing the header to the canonical
    # "Interest Expense" makes collate_pass1 collapse the pair, keeping the
    # larger magnitude — which correctly picks the grand total over a subset
    # (e.g. Tegeta FY2019 keeps -15.3M, not the -305k P&L-face line).
    "Interest expense from:": "Interest Expense",
    # Same header-vs-total double-count on the income side ("Interest income
    # from:" alongside a clean "Interest Income" total, ~38 company-years).
    "Interest income from:": "Interest Income",
    # Case variants of "Other income"
    "other": "Other",                                  # generic "other" -> canonical
    "Other Income": "Other income",                    # collapse case
    # Total Comprehensive Income canonical
    "Total Other Comprehensive Income / (Loss)": "Total other comprehensive (loss) income",
    # PPE revaluation reserve canonical
    "Property, Plant and Equipment Revaluation Reserve": "Property, plant and equipment revaluation reserve",
}


# ---------------------------------------------------------------------------
# 3) Extra merge targets (sum-merge consolidations)
# Per user request: items like "other income / other expense / net other
# non-operating income / net other income" → consolidate into one canonical row.
# ---------------------------------------------------------------------------
EXTRA_LINE_ITEM_MERGE_TARGETS: dict[str, str] = {
    # All variants of "other (non-)operating income/expense" → Other Income (catch-all)
    "Other Net Non-Operating Income / (Expense)": "Other income",
    "Other net operating income/(expense)": "Other income",
    "Other expenses": "Other income",     # net into Other income (signed)
    "Total other operating income": "Other income",
}


# ---------------------------------------------------------------------------
# 4) Unit-column parsing
# The raw GEL column has values like:
#   ".ლარი"      → raw GEL (multiplier = 1)
#   ".000 ლარი"  → GEL thousands (multiplier = 1000)
#   ".000.ლარი"  → GEL thousands (variant spelling, multiplier = 1000)
# Apply per-row at ingest. Canonical storage convention: raw GEL (multiply by
# 1000 when unit indicates thousands), matching what v1 did and what the
# dashboard's `_fmt` already assumes.
# ---------------------------------------------------------------------------
UNIT_MULTIPLIERS: dict[str, int] = {
    ".ლარი": 1,
    ".000 ლარი": 1000,
    ".000.ლარი": 1000,
}


def parse_unit_multiplier(raw_unit: str | None) -> int:
    """Return the multiplier to convert a value with this unit to raw GEL.

    Defaults to 1 (assume raw GEL) when unit is missing/unknown.
    """
    if raw_unit is None:
        return 1
    s = str(raw_unit).strip()
    return UNIT_MULTIPLIERS.get(s, 1)


# ---------------------------------------------------------------------------
# 4b) Unit-reconciler overrides — manual escape hatch
# Consulted by ``reconcile_units_across_filings`` (scripts/ingest/policies.py).
#
# The reconciler resolves cross-filing unit-tag conflicts by majority vote on
# the per-row unit multiplier. This is correct for the common case (one
# mislabeled filing vs many honest ones — e.g. Tashir Pizza 400016647's
# 2019c3 file, or Sighnaghi Hotel 404557644's 2024c1c2 file) but can pick
# the wrong winner when the majority of filings are systematically mistagged.
# Liberty Bank's 2019 + 2020 filings are the canonical example: every line is
# tagged ``.ლარი`` (mult=1) when the truth is ``.000 ლარი`` (mult=1000), so
# the reconciler's majority vote across years confirms the wrong tag and
# downscales the real billions to thousands.
#
# Two override scopes — line-level takes precedence over company-level:
#
#   UNIT_RECONCILER_LINE_OVERRIDES — force one specific line's multiplier
#       for one company. Use when only a handful of lines are wrong.
#
#   UNIT_RECONCILER_COMPANY_OVERRIDES — force every line's multiplier for
#       one company. Use when a whole filing for that company is mistagged
#       (e.g. a bank whose 2019/2020 c1c2 export has the wrong column
#       header — dozens of lines move together).
#
# Forced multiplier must be 1 or 1000. The reconciler will rescale any row
# whose per-row tag differs from the forced multiplier and leave the rest
# alone. Populate only after confirming via the dashboard / dry-run script.
# ---------------------------------------------------------------------------
UNIT_RECONCILER_LINE_OVERRIDES: dict[tuple[str, str], int] = {
    # ("IdCode", "canonical LineItemENG"): 1 or 1000,
}

UNIT_RECONCILER_COMPANY_OVERRIDES: dict[str, int] = {
    # ("IdCode"): 1 or 1000,
    # Liberty Bank — the 2019 + 2020 filings tagged every row .ლარი when the
    # real magnitude is thousands. 74 lines affected, FY2019-FY2021. Force
    # all rows to be interpreted as thousands.
    "203828304": 1000,
    # State Catering Service (შპს სახელმწიფო კვებითი უზრუნველყოფა) — the
    # 2024c1c2 filing tagged every row .000 ლარი when previous filings all
    # used .ლარი (raw value magnitudes match across years). FY2022/FY2023
    # were rescued by the auto-reconciler (multiple filings disagreed) but
    # FY2024 sits alone in 2024c1c2 and needs an explicit override.
    "404482537": 1,
}


# Year-scoped unit override — forces every row of a specific (IdCode, FVYear)
# to use the given multiplier, regardless of the Excel's per-row unit tag.
# Use when one filing is mistagged in the source but adjacent years are
# correct, AND no later restatement exists for the auto-reconciler to catch
# the mislabel.
#
# Canonical case: Tashir Pizza (400016647) FY2018 — the 2018c3 file tags
# every row '.000 ლარი' but the actual numbers are raw GEL, and no later
# filing restates 2018 to create reconciler tension. Force multiplier=1
# so the ingest stops scaling 2018 by 1000.
UNIT_RECONCILER_YEAR_OVERRIDES: dict[tuple[str, int], int] = {
    # (IdCode, FVYear): 1 or 1000
    ("400016647", 2018): 1,  # Tashir Pizza — 2018c3 wrong-tagged as thousands
    # Tashir Pizza FY2017 has the same shape (BS Total Assets = 910M GEL is
    # implausible for a single-outlet startup; balance sheet still balances
    # at /1000 scale: assets 910K = liab 884K + equity 26K). Surfaced by
    # scripts/find_unit_anomalies.py — the BS rows of 2017 sit at the inflated
    # scale alongside fixed 2018 numbers.
    ("400016647", 2017): 1,  # Tashir Pizza — 2017 BS sits at GEL when later years are K-GEL

    # ---- Pilot batch surfaced by scripts/find_unit_mismatches.py ----
    # Cluster-based scanner identified these as filings whose entire row set
    # is mistagged at source. Each entry is paired with the company's other
    # filings landing on the correct scale (see correct cluster in the
    # scanner output). Apply via scripts/apply_year_overrides.py.

    # Retail Group Georgia sister cluster — identical 2020+2021 shrink across
    # 3 affiliated retail entities, suggesting a shared upstream filer mistag.
    ("404399236", 2020): 1000,  # Retail Group Georgia — Rev 159K vs FY18-19 ~140M
    ("404399236", 2021): 1000,  # Retail Group Georgia — Rev 107K vs FY18-19 ~140M
    ("404404774", 2020): 1000,  # Spanish Retail Georgia — Rev 63K vs FY18-19 ~48M
    ("404404774", 2021): 1000,  # Spanish Retail Georgia — Rev 41K vs FY18-19 ~48M
    ("404404809", 2020): 1000,  # Fashion Retail Georgia — Rev 32K vs FY18-19 ~35M
    ("404404809", 2021): 1000,  # Fashion Retail Georgia — Rev 21K vs FY18-19 ~35M

    # Rustavi Azoti — major chemical plant, 3 of 5 years mistagged at source.
    # Correct cluster {2017, 2018} has Rev 217M/330M and TA 93M/128M, consistent
    # with the plant's real scale; the small years (2019/2020) and 2016
    # placeholder need ×1000.
    ("404519794", 2016): 1000,  # Rustavi Azoti — TA 1K placeholder
    ("404519794", 2019): 1000,  # Rustavi Azoti — TA 201K, Rev 365K vs FY18 128M/330M
    ("404519794", 2020): 1000,  # Rustavi Azoti — TA 300K, Rev 344K

    # NOTE: L&G (215143609) FY2018 is deliberately NOT a YEAR override. The
    # scanner flagged the 2018 BS rows as 1000x too large (TA 3.16B vs peers
    # 2-5M), but the IS rows for the same year were already correct (Revenue
    # 3.9M). A year-level override ÷1000 fixes BS but over-shrinks IS —
    # confirmed in pilot run on 2026-06-09. This is now handled durably by the
    # (IdCode, FVYear, LineItemENG)-scoped UNIT_RECONCILER_ROW_OVERRIDES tier
    # below (the L&G FY2018 BS block migrated there 2026-06-18), so a full
    # rebuild_db.py reproduces the fix instead of re-introducing the 3.16B bug.
    # (Previously this fix lived ONLY as an out-of-band surgical SQL patch on
    # the live DB and silently reverted on rebuild.)

    # ---- Sprint 14 batch (2026-06-10): high-confidence ** double cross-metric
    # confirms from docs/reviews/sprint14-unit-mistag-triage.md. The * single-
    # confirm entries and the .-tail were held back for manual review. The
    # apply_year_overrides 500x direction-aware gate skips any that don't pass
    # (so wrong-direction / sub-gate entries are no-ops).
    ("404980231", 2018): 1000,  # ახალი კლინიკა — 1682x shrink **
    ("404980231", 2019): 1000,  # ახალი კლინიკა — 1207x shrink **
    ("405001466", 2021): 1,     # უნივერსალური სამედ. ცენტრი — 3032x grow ** (pair 3719x)
    ("405001466", 2022): 1,     # უნივერსალური სამედ. ცენტრი — 2961x grow **
    ("405413404", 2020): 1000,  # ჯიესპი გრუპ — 2347x shrink **
    # ლოკალი: the scanner's 6-yr ×1000 entries on 2019-24 were WRONG-DIRECTION
    # (it anchored on the inflated FY2018: Rev ₾3.55B / TA ₾1.12B for a
    # restaurant chain). Analyst-confirmed 2026-06-11: FY2018 is the mistag.
    ("443866238", 2018): 1,     # ლოკალი — FY2018 whole-year ×1000 too big (Rev+EBITDA+TA)
    ("404437702", 2017): 1000,  # ჯიარ ტრანზიტ ლაინი — 1377x shrink **
    ("404437702", 2018): 1000,  # ჯიარ ტრანზიტ ლაინი — 1461x shrink **
    ("405161792", 2019): 1000,  # ე უ ინვესთმენთს — 1180x shrink ** (pair 1071x)
    ("405161792", 2020): 1000,  # ე უ ინვესთმენთს — 1563x shrink **
    ("226523866", 2019): 1000,  # ქართ. ღვინისა და ალკ. სასმელები — 1299x shrink **
    ("226523866", 2020): 1000,  # ქართ. ღვინისა და ალკ. სასმელები — 1017x shrink **
    ("202460103", 2020): 1000,  # ჯიარ ქონების მართვა — 842x shrink ** (FY2019 row-level, excluded)
    ("202460103", 2021): 1000,  # ჯიარ ქონების მართვა — 826x shrink **
    ("202218698", 2018): 1000,  # მირა — 1223x shrink **
    ("202218698", 2019): 1000,  # მირა — 988x shrink **
    # 236035517 რეგიონული ჯანდაცვის ცენტრი: scanner's ×1 entries on 2016-19,21
    # REMOVED 2026-06-11 — wrong direction (it anchored on the shrunken
    # 2022-24 TA cluster; the M-scale 2016-21 years look genuine). Likely real
    # fixes, pending analyst confirm: ×1000 on 2023+2024 (whole-year shrink:
    # Rev ₾14K/₾18K, TA ₾37K), 2022 is row-level (Rev ₾15.98M OK, TA ₾42K off).
    #   UPDATE 2026-08-06: the RMS Auditors file CONFIRMS all three claims to the
    #   unit (FY2023 Income 14,062,000 / Assets 36,979,000 vs panel 14,062/36,979;
    #   FY2024 18,289,000 / 37,876,000 vs 18,289/37,876 — on BOTH filing bases).
    #   The pending entries are staged (commented, inert) in the STAGED block at
    #   the end of this dict; FY2022's row-level set is in the ROW dict's STAGED
    #   block. Evidence: docs/reviews/2026-08-06-rms-unit-triage.md.
    ("404537809", 2022): 1000,  # ბკ ქონსთრაქშენი — 888x shrink ** (pair 989x)
    ("404537809", 2023): 1000,  # ბკ ქონსთრაქშენი — 1100x shrink **
    ("405406109", 2023): 1000,  # მოსავლის მართვის კომპანია — 773x shrink **
    ("405406109", 2024): 1000,  # მოსავლის მართვის კომპანია — 1057x shrink **
    ("404589913", 2019): 1000,  # ჯორჯიან ბევერიჯის ჰოლდინგი — 1035x shrink **
    ("211360089", 2019): 1000,  # ბახტრიონი — 969x shrink **
    ("204920381", 2020): 1000,  # ელიზი ჯგუფი — 905x shrink ** (pair 1070x)
    ("404934381", 2020): 1000,  # Hualing SEZ — 824x shrink ** (pair 952x)
    ("404934381", 2021): 1000,  # Hualing SEZ — 891x shrink **
    ("204493002", 2019): 1000,  # რომპეტროლ საქართველო — 722x shrink ** (pair 1335x)
    ("204493002", 2020): 1000,  # რომპეტროლ საქართველო — 843x shrink **
    ("404386151", 2023): 1000,  # ტრანსფორდი — 755x shrink ** (pair 953x)
    ("405160819", 2022): 1000,  # ოპტიმა — 707x shrink ** (pair 927x)
    ("404485053", 2020): 1000,  # აიდიეს ბორჯომი საქართველო — 628x shrink **
    ("204875082", 2023): 1000,  # აკა — 590x shrink **
    ("204875082", 2024): 1000,  # აკა — 493x shrink ** (below ~500x gate; may skip)
    ("204497829", 2024): 1000,  # ბრიტანულ ქართული აკადემია — 529x shrink **

    # ---- Billions batch (2026-06-11): analyst rule — any year showing
    # billions-scale values is overstated (×1000 too big). Whole-year cases
    # only; the matching FY2018 IS-only inflations for სანტა-ტრანსი and
    # აუტო ვეი (Rev/EBITDA ×1000 but TA on-scale) are ROW-LEVEL and must wait
    # for the ROW_OVERRIDES tier. See docs/reviews/triage-revenue-matrix.md.
    ("205049197", 2017): 1,     # სანტა-ტრანსი — TA ₾1.50B vs ~₾1.3M peers (Rev/EBITDA are 0)
    ("225384312", 2017): 1,     # აუტო ვეი — TA ₾8.71B vs ~₾1.9M peers (Rev/EBITDA are 0)

    # ======================================================================
    # STAGED — NOT ACTIVE. RMS unit-triage batch, 2026-08-06.
    # ----------------------------------------------------------------------
    # These lines are deliberately COMMENTED OUT. This dict has no "pending"
    # tier — every live key here is honoured by `rebuild_db.py all`, so an
    # un-reviewed entry would apply itself on the next rebuild. That is exactly
    # what CLAUDE.md hard constraint #6 forbids. Un-commenting a line IS the
    # act of approval.
    #
    # Source: `python scripts/build_auditors.py --check-units` →
    #   docs/reviews/2026-08-05-rms-units-check-current-db.txt (37 hits
    #   corroborated on both Revenue and TotalAssets), triaged in
    #   docs/reviews/2026-08-06-rms-unit-triage.md.
    #
    # Direction (constraint #6): all of these are the DB being ×1000 too
    # SMALL → target 1000. Verified on ≥2 independent signals each — the RMS
    # Income/Assets tie plus own-history continuity plus a wage-per-head
    # check (|Personnel expense| / RMS Employees, which lands under ₾30 per
    # employee per YEAR at the stored scale and in the ₾13–26K range at ×1000).
    # 26 of the 37 hits look like "the DB is ×1000 too LARGE" and are NOT —
    # they are the RMS row presented in thousands. Do not add ×1 entries for
    # them; see §2 of the triage doc.
    #
    # ⚠ GATE: `apply_year_overrides.py` skips ("already_applied") any entry
    # whose year sits within ~500× of the company's other-year TA median.
    #   * 400013873 passes ONLY if 2019+2020+2021 are staged together.
    #   * 206268741 and 404582055 are gate-skipped at this tier no matter what
    #     (their TA grew ~5× mid-series) and this script has no --force-entry,
    #     so they are staged in the ROW dict instead.
    #
    # ("236035517", 2023): 1000,  # რეგიონული ჯანდაცვის ცენტრი — RMS 14,062,000/36,979,000 vs panel 14,062/36,979 (exact, both bases)
    # ("236035517", 2024): 1000,  # ditto — RMS 18,289,000/37,876,000 vs panel 18,289/37,876
    # ("400013873", 2019): 1000,  # სოფთ გრუპ — cluster companion (continuity only); REQUIRED or FY2021 is gate-skipped
    # ("400013873", 2020): 1000,  # ditto — matrix '*' entry "TA'20 3K vs med 2.20M"
    # ("400013873", 2021): 1000,  # ditto — RMS 5,280,442/3,230,759 vs panel 5,205/3,231
    # ("405116422", 2019): 1000,  # კომფორტი — cluster companion (continuity only)
    # ("405116422", 2020): 1000,  # ditto — matrix '*' entry "TA'20 4K vs med 3.18M"
    # ("405116422", 2021): 1000,  # ditto — RMS 7,529,519/4,408,065 vs panel 7,523/4,411
    #
    # NOT staged — 405127937 (დომუს - ვაკის პარკი) and 405356305 (ჯი ენ ერ
    # მენეჯმენტი) are whole-COMPANY mistags: every filed year is K-scale, so
    # continuity has no anchor and only UNIT_RECONCILER_COMPANY_OVERRIDES could
    # express the fix — a tier with NO sanity gate at all. Resolve from the
    # filed PDF first (report_pdf_links has both). Triage doc §5.
    # ======================================================================
}


# Row-scoped unit override — the MOST SPECIFIC tier. Forces ONE line item of
# ONE (IdCode, FVYear) to the given multiplier, leaving every other row of
# the same filing untouched.
#
# Semantics (identical to the other tiers): the value is the unit multiplier
# the row SHOULD have been ingested with — 1 = the Excel cell is raw GEL,
# 1000 = the cell is thousands of GEL. The reconciler rescales any staged row
# whose per-row unit tag disagrees with the forced multiplier
# (``new_value = value / row_multiplier * forced``). So an entry of 1 on a
# row currently tagged ".000 ლარი" divides the stored value by 1000; an
# entry of 1000 on a row tagged ".ლარი" multiplies it by 1000.
#
# Precedence: ROW > LINE > YEAR > COMPANY > auto-vote.
#
# Use for "Bucket B" mistags (docs/reviews/sprint14-unit-mistag-triage.md):
# filings where only SOME rows are mis-scaled ×1000 within a year — e.g.
# Revenue on the correct scale but the BS block ×1000 off (or the inverse).
# A YEAR override would corrupt the already-correct rows; this tier is
# surgical. LineItemENG must be the exact canonical (post-alias) spelling as
# stored in financial_data.
#
# Hot-patch the live DB with scripts/apply_row_overrides.py (dry-run by
# default; --apply to write; per-row direction-aware sanity gate).
UNIT_RECONCILER_ROW_OVERRIDES: dict[tuple[str, int, str], int] = {
    # (IdCode, FVYear, LineItemENG): 1 or 1000

    # ---- aversi-pharma (211386695) FY2020 & FY2021 - row-level x1000 mistag ----
    # 2020/2021 ingested x1000 too small for MOST IS+CF rows while a handful (Total
    # Comprehensive Income, 'Interest expense from:', the impairment lines, 'Other
    # Income') landed at correct full scale - a classic Bucket B partial mistag. A
    # YEAR override would over-scale the already-correct rows. Each row below is
    # ~1000x below its own other-year peer median (gate-confirmed 2026-06-19);
    # target=1000 lifts them to hundreds-of-millions, consistent with FY2019
    # (Rev 456.5M) / FY2022 (Rev 737.8M). Already-correct rows left untouched.
    # -- FY2020 --
    ("211386695", 2020, "Other administrative and operating expenses"): 1000,  # IS -3,474 -> -3,474,000
    ("211386695", 2020, "Net Revenue"): 1000,  # IS 508,166 -> 508,166,000
    ("211386695", 2020, "Personnel expense"): 1000,  # IS -99,017 -> -99,017,000
    ("211386695", 2020, "Rental expenses"): 1000,  # IS -357 -> -357,000
    ("211386695", 2020, "Utility and communication services"): 1000,  # IS -5,653 -> -5,653,000
    ("211386695", 2020, "Dividends received"): 1000,  # IS 1,120 -> 1,120,000
    ("211386695", 2020, "Profit/(loss) from continuing operations"): 1000,  # IS 26,206 -> 26,206,000
    ("211386695", 2020, "Profit/(loss) before tax from continuing operations"): 1000,  # IS 26,605 -> 26,605,000
    ("211386695", 2020, "Income tax"): 1000,  # IS -399 -> -399,000
    ("211386695", 2020, "Profit/(loss)"): 1000,  # IS 26,206 -> 26,206,000
    ("211386695", 2020, "Gross Profit"): 1000,  # IS 191,108 -> 191,108,000
    ("211386695", 2020, "Operating income"): 1000,  # IS 52,202 -> 52,202,000
    ("211386695", 2020, "Advertising and marketing expenses"): 1000,  # IS -4,746 -> -4,746,000
    ("211386695", 2020, "Other financial income"): 1000,  # IS 2,027 -> 2,027,000
    ("211386695", 2020, "Interest Expense"): 1000,  # IS -6,345 -> -6,345,000
    ("211386695", 2020, "Transportation and transmission expense"): 1000,  # IS -689 -> -689,000
    ("211386695", 2020, "Depreciation and amortisation"): 1000,  # IS -26,945 -> -26,945,000
    ("211386695", 2020, "Net gain (loss) from foreign exchange operations"): 1000,  # IS -23,578 -> -23,578,000
    ("211386695", 2020, "Penalties"): 1000,  # IS -84 -> -84,000
    ("211386695", 2020, "Owners of the parent"): 1000,  # IS 26,206 -> 26,206,000
    ("211386695", 2020, "Other operating income"): 1000,  # IS 5,091 -> 5,091,000
    ("211386695", 2020, "Effect of exchange rate changes on cash and cash equivalents"): 1000,  # CF -133 -> -133,000
    ("211386695", 2020, "Net cash used in investing activities"): 1000,  # CF -23,206 -> -23,206,000
    ("211386695", 2020, "Net Cash from Operating Activities"): 1000,  # CF 49,576 -> 49,576,000
    ("211386695", 2020, "Net cash raised in financing activities"): 1000,  # CF -22,964 -> -22,964,000
    ("211386695", 2020, "Cash at the end of the year"): 1000,  # CF 15,028 -> 15,028,000
    ("211386695", 2020, "Cash at the beginning of the year"): 1000,  # CF 11,755 -> 11,755,000
    ("211386695", 2020, "Net cash inflow for the year"): 1000,  # CF 3,406 -> 3,406,000
    # -- FY2021 --
    ("211386695", 2021, "Net Revenue"): 1000,  # IS 690,807 -> 690,807,000
    ("211386695", 2021, "Gross Profit"): 1000,  # IS 261,320 -> 261,320,000
    ("211386695", 2021, "Other operating income"): 1000,  # IS 4,936 -> 4,936,000
    ("211386695", 2021, "Personnel expense"): 1000,  # IS -128,902 -> -128,902,000
    ("211386695", 2021, "Advertising and marketing expenses"): 1000,  # IS -10,311 -> -10,311,000
    ("211386695", 2021, "Utility and communication services"): 1000,  # IS -8,618 -> -8,618,000
    ("211386695", 2021, "Rental expenses"): 1000,  # IS -523 -> -523,000
    ("211386695", 2021, "Transportation and transmission expense"): 1000,  # IS -1,146 -> -1,146,000
    ("211386695", 2021, "Depreciation and amortisation"): 1000,  # IS -30,319 -> -30,319,000
    ("211386695", 2021, "Other administrative and operating expenses"): 1000,  # IS -10,967 -> -10,967,000
    ("211386695", 2021, "Operating income"): 1000,  # IS 71,546 -> 71,546,000
    ("211386695", 2021, "Net gain (loss) from foreign exchange operations"): 1000,  # IS 13,705 -> 13,705,000
    ("211386695", 2021, "Other financial income"): 1000,  # IS 2,308 -> 2,308,000
    ("211386695", 2021, "Interest Expense"): 1000,  # IS -5,935 -> -5,935,000
    ("211386695", 2021, "Dividends received"): 1000,  # IS 1,445 -> 1,445,000
    ("211386695", 2021, "Profit/(loss) before tax from continuing operations"): 1000,  # IS 83,069 -> 83,069,000
    ("211386695", 2021, "Income tax"): 1000,  # IS -329 -> -329,000
    ("211386695", 2021, "Profit/(loss) from continuing operations"): 1000,  # IS 82,740 -> 82,740,000
    ("211386695", 2021, "Profit/(loss)"): 1000,  # IS 82,740 -> 82,740,000
    ("211386695", 2021, "Owners of the parent"): 1000,  # IS 82,740 -> 82,740,000
    ("211386695", 2021, "Net Cash from Operating Activities"): 1000,  # CF 79,921 -> 79,921,000
    ("211386695", 2021, "Net cash used in investing activities"): 1000,  # CF -57,649 -> -57,649,000
    ("211386695", 2021, "Net cash raised in financing activities"): 1000,  # CF -27,419 -> -27,419,000
    ("211386695", 2021, "Net cash inflow for the year"): 1000,  # CF -5,147 -> -5,147,000
    ("211386695", 2021, "Effect of exchange rate changes on cash and cash equivalents"): 1000,  # CF -96 -> -96,000
    ("211386695", 2021, "Cash at the beginning of the year"): 1000,  # CF 15,028 -> 15,028,000
    ("211386695", 2021, "Cash at the end of the year"): 1000,  # CF 9,785 -> 9,785,000

    # ---- საქართველოს ტურიზმის განვითარების ფონდი (405033734) FY2018 ----
    # Analyst-approved 2026-06-11 (billions rule). Within the FY2018 filing
    # the IS is on the correct scale (Net Revenue ₾26.12M, fits the
    # 727K→33.8M neighbour trend) but the BS block + one IS_OpEx row are
    # ×1000 too big. Internal proof at ÷1000: BS identity holds EXACTLY
    # (TL 28.860M + TE 357.068M = TA 385.928M) and TE 357.068M = equity attr.
    # to parent 346.318M (already on-scale) + NCI 10.750M. CF cross-confirm:
    # "Cash at the end of the year" FY2018 = 6,238,000 = the staged Cash row
    # ÷1000. Each row below is ~500–2000× its own other-year median.
    ("405033734", 2018, "Cash and Cash Equivalents"): 1,          # ₾6.238B → ₾6.238M (648K'17 / 8.93M'19)
    ("405033734", 2018, "Trade Receivables"): 1,                  # ₾2.824B → ₾2.824M (9.5M'17 / 5.9M'19)
    ("405033734", 2018, "Other intangible assets"): 1,            # ₾147M → ₾147K (8K'17 / 208K'19)
    ("405033734", 2018, "Investments in Subsidiaries"): 1,        # ₾595.7B → ₾595.7M (248M'16 / 715M'19)
    ("405033734", 2018, "Property, Plant and Equipment"): 1,      # ₾277.1B → ₾277.1M (157M'17 / 415M'19)
    ("405033734", 2018, "Total Assets"): 1,                       # ₾385.9B → ₾385.9M (241M'17 / 574M'19)
    ("405033734", 2018, "Retained earnings / (Accumulated deficit)"): 1,  # -₾233.8B → -₾233.8M
    ("405033734", 2018, 'Share capital (in case of Limited Liability Company - "capital", in case of cooperative entity - "unit capital"'): 1,  # ₾580.1B → ₾580.1M (400M'17 / 701M'19)
    ("405033734", 2018, "Total Equity"): 1,                       # ₾357.1B → ₾357.1M (179M'17 / 467M'19)
    ("405033734", 2018, "Total Liabilities"): 1,                  # ₾28.86B → ₾28.86M (BS identity exact)
    ("405033734", 2018, "Total Liabilities and Equity"): 1,       # ₾385.9B → ₾385.9M
    ("405033734", 2018, "Trade payables"): 1,                     # ₾19.06B → ₾19.06M (38.6M'17 / 16.0M'19)
    ("405033734", 2018, "Taxes other than on income"): 1,         # ₾32.21B → ₾32.21M (38.1M'17 / 42.9M'19) — the "EBITDA ₾32.2B" row
    # Same company, surfaced while inspecting FY2018 — also billions-scale
    # (analyst billions rule applies), per-row series fit at ÷1000:
    ("405033734", 2017, "Investments in Subsidiaries"): 1,        # ₾457.6B → ₾457.6M (series 248M'16 → 457.6M → 595.7M → 715M'19)
    ("405033734", 2019, "Personnel expense"): 1,                  # -₾8.53B → -₾8.53M (-11.9M'18 / -8.67M'20)

    # ---- სანტა-ტრანსი (205049197) FY2018 — inverse Bucket B ----
    # Analyst-approved 2026-06-11 (billions rule). The FY2018 BS is on the
    # correct scale (TA ₾1.54M) but the IS block is ×1000 too big
    # (Rev ₾3.28B; computed EBITDA ~₾251M). Internal proof at ÷1000:
    # Net Revenue 3,280,229 ≈ FY2019's 3,272,921; PBT 50,525 − tax 8,917 =
    # net 41,608 EXACTLY = the on-scale BS Retained earnings FY2018 (41,608).
    ("205049197", 2018, "Net Revenue"): 1,                        # ₾3.28B → ₾3.28M (3.27M'19 / 2.40M'20)
    ("205049197", 2018, "Cost of Goods Sold"): 1,                 # -₾2.89B → -₾2.89M (-2.34M'19)
    ("205049197", 2018, "Operating income"): 1,                   # ₾50.5M → ₾50.5K (284K'19 / 306K'20)
    ("205049197", 2018, "Profit/(loss)"): 1,                      # ₾41.6M → ₾41.6K (= BS RE 41,608 exact)
    ("205049197", 2018, "Profit/(loss) before tax from continuing operations"): 1,  # ₾50.5M → ₾50.5K
    ("205049197", 2018, "Total Comprehensive Income / (Loss)"): 1,  # ₾41.6M → ₾41.6K
    ("205049197", 2018, "Rental expenses"): 1,                    # -₾12.0M → -₾12.0K (-17.8K'19 / -16.2K'20)
    ("205049197", 2018, "Penalties"): 1,                          # -₾38.9M → -₾38.9K (no peer years — part of the same ×1000 IS block)
    ("205049197", 2018, "Transportation and transmission expense"): 1,  # -₾89.1M → -₾89.1K (no peer years — same IS block)
    ("205049197", 2018, "Income tax"): 1,                         # -₾8.92M → -₾8.92K (PBT−tax=net ties out exactly at ÷1000)

    # ---- L&G (215143609) FY2018 — BS block ×1000 too big; IS already correct ----
    # MIGRATED 2026-06-18 from the out-of-band surgical SQL patch that lived
    # ONLY on the live DB (see the NOTE in UNIT_RECONCILER_YEAR_OVERRIDES and
    # docs/reviews/2026-06-09-session-batch-code-review.md Issue 6). The 2018c?
    # export tagged the balance-sheet block '.000 ლარი' (thousands) so it
    # ingested ×1000 too big (TA ₾3.16B vs FY2019 ₾4.44M), while the IS rows
    # for the same year were already raw GEL (Net Revenue ₾3.9M). A YEAR
    # override would over-shrink the correct IS; these ROW overrides force ONLY
    # the inflated BS lines back to raw GEL (target=1 → ÷1000). Each row below
    # is the exact set the surgical patch divided — verified ~1.0× its own
    # other-year peer median after the fix, and the BS identity holds at the
    # corrected scale (TL 3,444 + TE 3,155,981 = TA 3,159,425). The small
    # summary rows (Closing/Opening Equity, Total current assets/liabilities,
    # Total Liabilities, Trade payables) are a SEPARATE pre-existing thousands-
    # scale quirk and are intentionally left out of this migration.
    ("215143609", 2018, "Total Assets"): 1,                       # ₾3.16B → ₾3.159M
    ("215143609", 2018, "Total Liabilities and Equity"): 1,       # ₾3.16B → ₾3.159M
    ("215143609", 2018, "Total Equity"): 1,                       # ₾3.156B → ₾3.156M
    ("215143609", 2018, "Retained earnings / (Accumulated deficit)"): 1,  # ₾3.156B → ₾3.156M
    ("215143609", 2018, "Property, Plant and Equipment"): 1,      # ₾1.488B → ₾1.488M
    ("215143609", 2018, "Cash and Cash Equivalents"): 1,          # ₾1.078B → ₾1.078M
    ("215143609", 2018, "Trade Receivables"): 1,                  # ₾400.1M → ₾400.1K
    ("215143609", 2018, "- inventories"): 1,                      # ₾19.48M → ₾19.48K
    ("215143609", 2018, "Other intangible assets"): 1,           # ₾718K → ₾718
    ("215143609", 2018, "Other Changes of retained earnings"): 1,  # ₾1.319M → ₾1,319

    # ---- აუტო ვეი (Auto Way, 225384312) FY2018 — inverse Bucket B, ACTIVATED 2026-07-22 ----
    # The whole FY2018 IS + CF + SOCE (equity-movement) block ingested ×1000 too
    # big; the balance-sheet-proper rows (TA ₾1.94M, Equity ₾1.91M, PPE, RE, share
    # capital, receivables/payables) are already on-scale. Same shape as Santa-Transi
    # 205049197 above but sub-billions (Rev ₾382.3M), so it waited in the "PENDING
    # ANALYST CONFIRM" block below until 2026-07-22. Analyst-confirmed by an over-
    # determined ÷1000 tie-out: Net Profit −3,040,694 = the on-scale BS retained-
    # earnings movement (−2,508,553 FY17 → −5,549,247 FY18, Δ exact); D&A −31,261 =
    # FY2019; SOCE Opening Equity 8,697,520 = FY17 BS equity; Closing Equity
    # 1,906,826 = FY18 BS equity; CF cash-end 107,979 = on-scale BS Cash; cash rec
    # foots (22,134 + 89,596 − 3,751 = 107,979); PBT foots (291,496 − 1,697 −
    # 3,330,493 = −3,040,694). The −₾3.33bn→−₾3.33M "Other income" is a real
    # subsidiary write-off (FY17 Investments-in-Subsidiaries 7.08M gone; share
    # capital 11.2M→7.46M). vs the old commented list below: names refreshed to
    # current canonical spelling ("Interest Income", not "Interest income from:")
    # and the previously-omitted "Personnel expense" + both FX lines added.
    # -- IS --
    ("225384312", 2018, "Net Revenue"): 1,                          # 382,306,000 → 382,306
    ("225384312", 2018, "- rendering of services"): 1,              # 382,306,000 → 382,306
    ("225384312", 2018, "Gross Profit"): 1,                         # 382,306,000 → 382,306
    ("225384312", 2018, "Operating income"): 1,                     # 291,496,000 → 291,496
    ("225384312", 2018, "Depreciation and amortisation"): 1,        # -31,261,000 → -31,261 (= FY2019)
    ("225384312", 2018, "Interest Income"): 1,                      # 36,266,000 → 36,266
    ("225384312", 2018, "Personnel expense"): 1,                    # -84,877,000 → -84,877
    ("225384312", 2018, "Other administrative and operating expenses"): 1,  # -10,938,000 → -10,938
    ("225384312", 2018, "Total operating expense"): 1,              # -90,810,000 → -90,810
    ("225384312", 2018, "Net gain (loss) from foreign exchange operations"): 1,  # -1,697,000 → -1,697 (pair-broken vs volatile FX peers; forced)
    ("225384312", 2018, "Other income"): 1,                         # -3,330,493,000 → -3,330,493 (no peers; subsidiary write-off)
    ("225384312", 2018, "Profit/(loss)"): 1,                        # -3,040,694,000 → -3,040,694 (= BS RE movement)
    ("225384312", 2018, "Profit/(loss) before tax from continuing operations"): 1,  # -3,040,694,000 → -3,040,694
    ("225384312", 2018, "Total Comprehensive Income / (Loss)"): 1,  # -3,040,694,000 → -3,040,694
    # -- CF (incl. CF-polluted BS_Cash rows) --
    ("225384312", 2018, "Cash at the beginning of the year"): 1,    # 22,134,000 → 22,134 (= FY2017 cash)
    ("225384312", 2018, "Cash at the end of the year"): 1,          # 107,979,000 → 107,979 (= on-scale BS Cash)
    ("225384312", 2018, "Effect of exchange rate changes on cash and cash equivalents"): 1,  # -3,751,000 → -3,751 (force-entry)
    ("225384312", 2018, "Net Cash from Operating Activities"): 1,   # 101,764,000 → 101,764
    ("225384312", 2018, "Net cash inflow for the year"): 1,         # 89,596,000 → 89,596
    ("225384312", 2018, "Net cash raised in financing activities"): 1,  # -3,750,000,000 → -3,750,000
    ("225384312", 2018, "Net cash used in investing activities"): 1,    # 3,737,832,000 → 3,737,832
    # -- SOCE (equity movements) --
    ("225384312", 2018, "Closing Equity"): 1,                       # 1,906,826,000 → 1,906,826 (= FY18 BS equity)
    ("225384312", 2018, "Opening Equity"): 1,                       # 8,697,520,000 → 8,697,520 (= FY17 BS equity)
    ("225384312", 2018, "Other Changes of equity"): 1,              # -3,750,000,000 → -3,750,000 (capital reduction)

    # ------------------------------------------------------------------
    # PENDING ANALYST CONFIRM — evidence gathered 2026-06-11, NOT staged.
    # These are outside the analyst's approved "billions" rule (sub-billions
    # magnitudes) or not yet reviewed. Ratios = |value| vs the same line's
    # other-year median. Uncomment after analyst sign-off.
    # ------------------------------------------------------------------

    # სანტა-ტრანსი (205049197) FY2018 — non-IS rows of the same mistagged
    # filing, sub-billions so outside the approved scope:
    # ("205049197", 2018, "Net Cash from Operating Activities"): 1,  # ₾23.61M → ₾23,608 = EXACTLY the on-scale BS Cash FY2018; no peer years
    # ("205049197", 2018, "Other current liabilities"): 1,           # ₾524.2M → ₾524.2K (540× vs FY2017's 970,981); TL 1.06M ties out exactly WITHOUT this row

    # აუტო ვეი (225384312) FY2018 — ACTIVATED 2026-07-22; entries moved up into
    # the live block above (names refreshed + Personnel/FX rows that were missing
    # here added). See that block for the full evidence.

    # ჯიარ ქონების მართვა (202460103) FY2019 — Rev ₾1,525,000 on-scale, BS
    # block ×1000 SHRUNK (needs ×1000). FY2020/21 already fixed via YEAR tier:
    # ("202460103", 2019, "Total Assets"): 1000,                  # 40,062 → 40.06M (1524× shrink vs med 61.1M)
    # ("202460103", 2019, "Total Liabilities and Equity"): 1000,  # 40,062 → 40.06M
    # ("202460103", 2019, "Total Equity"): 1000,                  # 39,570 → 39.57M (1532×)
    # ("202460103", 2019, "Net assets attributable to the bank's equity holders"): 1000,  # 39,570 (1532×)
    # ("202460103", 2019, "Share Capital"): 1000,                 # 122,337 → 122.3M (1139×)
    # ("202460103", 2019, "Retained earnings (Accumulated deficit)"): 1000,  # -74,112 (1020×)
    # ("202460103", 2019, "Cash and Cash Equivalents"): 1000,     # 6,246 (808×)
    # ("202460103", 2019, "Due from banks"): 1000,                # 3,000,000 (834× vs med 2.50B — verify peers!)
    # ("202460103", 2019, "Investment Property"): 1000,           # 14,779 (1885×)
    # ("202460103", 2019, "Property, Plant and Equipment"): 1000, # 11,854 (1075×)
    # ("202460103", 2019, "Other Current Assets"): 1000,          # 3,842 (736×)
    # ("202460103", 2019, "Trade Receivables"): 1000,             # 341 (2543×)
    # ("202460103", 2019, "Total Liabilities"): 1000,             # 492 (1589×)
    # ("202460103", 2019, "Other current liabilities"): 1000,     # 266 (1773×)
    # ("202460103", 2019, "Trade payables"): 1000,                # 226 (874×)

    # თბილისი მოლი (205226290) FY2023 — Rev ₾1,207,695 on-scale, BS shrunk:
    # ("205226290", 2023, "Total Assets"): 1000,                  # 34,175 → 34.18M (316× vs med 10.8M)
    # ("205226290", 2023, "Total Liabilities and Equity"): 1000,  # 34,175 (316×)
    # ("205226290", 2023, "Cash and Cash Equivalents"): 1000,     # 121 (787×)
    # ("205226290", 2023, "Cash at the end of the year"): 1000,   # 121 (908×, CF)
    # ("205226290", 2023, "Property, Plant and Equipment"): 1000, # 340 (272×)
    # NOTE: FY2023 "Personnel expense" -591,149 is 434× LARGER than its med
    # (-1,362) — opposite-direction oddity within the same year; review.

    # ეიპი (405371146) FY2020 — Rev ₾2,565,450 + EBITDA on-scale, BS shrunk:
    # ("405371146", 2020, "Total Assets"): 1000,                  # 2,093 → 2.09M (1535× vs med 3.2M)
    # ("405371146", 2020, "Total Liabilities and Equity"): 1000,  # 2,093 (1535×)
    # ("405371146", 2020, "Total Equity"): 1000,                  # 1,669 (1924×)
    # ("405371146", 2020, "Closing Equity"): 1000,                # 1,669 (1924×)
    # ("405371146", 2020, "Retained earnings (Accumulated deficit)"): 1000,  # 1,669 (618×)

    # ემ.ჯი რენიუებლზ (404533590) FY2018 — Rev ₾523,000 on-scale, BS shrunk:
    # ("404533590", 2018, "Total Assets"): 1000,                  # 6,190 → 6.19M (1132× vs med 7.0M)
    # ("404533590", 2018, "Total Liabilities and Equity"): 1000,  # 6,190 (1132×)
    # ("404533590", 2018, "Property, Plant and Equipment"): 1000, # 5,896 (1131×)
    # ("404533590", 2018, "Total Liabilities"): 1000,             # 7,527 (1903×)
    # ("404533590", 2018, "Non current borrowings"): 1000,        # 5,816 (2459×)
    # ("404533590", 2018, "Total Equity"): 1000,                  # -1,337 (5474×)
    # ("404533590", 2018, "Retained earnings / (Accumulated deficit)"): 1000,  # -1,337 (5474×)
    # ("404533590", 2018, "Cash and Cash Equivalents"): 1000,     # 81 (1569×)
    # ("404533590", 2018, "Current Borrowings"): 1000,            # 1,454 (380×)
    # ("404533590", 2018, "Total current assets"): 1000,          # 294 (680×)
    # ("404533590", 2018, "Other Current Assets"): 1000,          # 6 (1975×)
    # ("404533590", 2018, "Trade Receivables"): 1000,             # 73 (699×)
    # ("404533590", 2018, "Trade payables"): 1000,                # 67 (194×)

    # ჰანდლერ კორპორეიშენ (405382508) FY2024 — Rev ₾10,553,000 on-scale:
    # ("405382508", 2024, "Total Assets"): 1000,                  # 5,000 → 5.0M (1101× vs med 5.5M)
    # ("405382508", 2024, "Total current assets"): 1000,          # 5,000 (1100×)
    # ("405382508", 2024, "Total Liabilities and Equity"): 1000,  # 5,000 (1101×)
    # ("405382508", 2024, "Cash and Cash Equivalents"): 1000,     # 2,000 (597×)
    # ("405382508", 2024, "Cash at the end of the year"): 1000,   # 2,000 (597×, CF)

    # ელ + (206108950) FY2020 — Rev ₾14,177,000 on-scale, BS shrunk:
    # ("206108950", 2020, "Total Assets"): 1000,                  # 12,657 → 12.66M (1033× vs med 13.1M)
    # ("206108950", 2020, "Total Liabilities and Equity"): 1000,  # 12,657 (1033×)
    # ("206108950", 2020, "Total current assets"): 1000,          # 8,430 (1123×)
    # ("206108950", 2020, "Total Liabilities"): 1000,             # 8,205 (920×)
    # ("206108950", 2020, "Total Equity"): 1000,                  # 4,452 (1079×)
    # ("206108950", 2020, "Retained earnings / (Accumulated deficit)"): 1000,  # 4,452 (1079×)
    # ("206108950", 2020, "Property, Plant and Equipment"): 1000, # 4,227 (1080×)
    # ("206108950", 2020, "Current Inventory"): 1000,             # 4,093 (1462×)
    # ("206108950", 2020, "Trade Receivables"): 1000,             # 3,593 (600×)
    # ("206108950", 2020, "Total current liabilities"): 1000,     # 6,880 (390×)
    # ("206108950", 2020, "Current Borrowings"): 1000,            # 2,060 (1040×)
    # ("206108950", 2020, "Non current borrowings"): 1000,        # 1,325 (978×)
    # ("206108950", 2020, "Cash and Cash Equivalents"): 1000,     # 744 (1392×)
    # ("206108950", 2020, "Trade payables"): 1000,                # 739 (2275×)

    # ლოდი (405343249) FY2020 — Rev ₾28,003,672 on-scale, BS totals shrunk:
    # ("405343249", 2020, "Total Assets"): 1000,                  # 3,737 → 3.74M (250× vs med 936K)
    # ("405343249", 2020, "Total current assets"): 1000,          # 3,738 (250×)
    # ("405343249", 2020, "Total Liabilities and Equity"): 1000,  # 3,737 (250×)
    # ("405343249", 2020, "Total Liabilities"): 1000,             # 2,546 (370×)
    # ("405343249", 2020, "Trade payables"): 1000,                # 2,546 (349×)

    # ბლოქფაუერ (405229701) FY2021 — Rev ₾47,229,166 on-scale, BS shrunk:
    # ("405229701", 2021, "Total Assets"): 1000,                  # 280,854 → 280.9M (488× vs med 137.1M)
    # ("405229701", 2021, "Total Liabilities and Equity"): 1000,  # 280,854 (488×)
    # ("405229701", 2021, "Trade Receivables"): 1000,             # 280,638 (334×)
    # ("405229701", 2021, "Cash and Cash Equivalents"): 1000,     # 216 (248×)
    # ("405229701", 2021, "Cash at the end of the year"): 1000,   # 216 (124×, CF)

    # გეიმინგ გრუფ (422719419) FY2019 — Rev ₾988,260 on-scale, BS shrunk:
    # ("422719419", 2019, "Total Assets"): 1000,                  # 1,274 → 1.27M (481× vs med 612K)
    # ("422719419", 2019, "Total Liabilities and Equity"): 1000,  # 1,274 (481×)
    # ("422719419", 2019, "Total Equity"): 1000,                  # 1,274 (410×)
    # ("422719419", 2019, "Closing Equity"): 1000,                # 1,274 (394×)
    # ("422719419", 2019, "Retained earnings / (Accumulated deficit)"): 1000,  # 1,274 (251×)
    # ("422719419", 2019, "Other Current Assets"): 1000,          # 1,182 (131×)
    # ("422719419", 2019, "Property, Plant and Equipment"): 1000, # 88 (2089×)
    # ("422719419", 2019, "Cash and Cash Equivalents"): 1000,     # 4 (23609×)
    # ("422719419", 2019, "Cash at the end of the year"): 1000,   # 4 (22930×, CF)

    # რეგიონული ჯანდაცვის ცენტრი (236035517) FY2022 — Rev ₾15.98M on-scale,
    # BS shrunk ×1000. CAUTION: same year also shows GROW-side IS oddities
    # (Gross Profit ₾10.02M @710×, Other operating income ₾6.15M @1416×) —
    # the filing may be doubly mangled; review the whole year:
    # ("236035517", 2022, "Total Assets"): 1000,                  # 42,136 → 42.14M (712× vs med 30.0M)
    # ("236035517", 2022, "Total Liabilities and Equity"): 1000,  # 42,136 (712×)
    # ("236035517", 2022, "Total Equity"): 1000,                  # 38,115 (756×)
    # ("236035517", 2022, "Total equity attributable to owners of parent"): 1000,  # 38,115 (756×)
    # ("236035517", 2022, 'Share capital (in case of Limited Liability Company - "capital", in case of cooperative entity - "unit capital"'): 1000,  # 37,382 (863×)
    # ("236035517", 2022, "Property, Plant and Equipment"): 1000, # 28,114 (956×)
    # ("236035517", 2022, "Total Liabilities"): 1000,             # 4,021 (406×)
    # ("236035517", 2022, "Trade Receivables"): 1000,             # 2,787 (895×)
    # ("236035517", 2022, "Trade payables"): 1000,                # 1,834 (124×)
    # ("236035517", 2022, "Retained earnings / (Accumulated deficit)"): 1000,  # -1,697 (916×)
    # ("236035517", 2022, "Current Inventory"): 1000,             # 5,127 (253×)
    # ("236035517", 2022, "Other intangible assets"): 1000,       # 10 (1073×)
    # ("236035517", 2022, "Post-employment benefits"): 1000,      # 1,884 (634×, IS)

    # ---- teliani-valley (203855444) FY2019 & FY2020 — IS+CF x1000 mistag ----
    # The 2019/2020 filings report the balance sheet in full GEL (Total Assets
    # 41.8M / 42.2M, consistent with FY2021 48.4M) but the income statement and
    # cash-flow in '000 GEL, tagged as raw GEL — so every IS/CF row landed 1000×
    # too small (Net Revenue 32,964 -> should be 32.96M, consistent with FY2018
    # 70.1M / FY2021 38.0M). Classic Bucket-B partial mistag: a YEAR override
    # would over-scale the already-correct balance sheet. FY2019 net loss lifts
    # to -53.6M — a real discontinued-operations write-off (continuing ops were
    # +2.8M). One FY2020 row ('Total comprehensive income(loss)' = -2,607,000)
    # already landed at full GEL and is deliberately NOT listed here.
    # Surfaced 2026-07-01 (GCAP portfolio accuracy review). Values in comments
    # are the pre-fix ('000) amounts.
    # -- FY2019 --
    ("203855444", 2019, "Advertising and marketing expenses"): 1000,  # -884
    ("203855444", 2019, "Consultancy fee"): 1000,  # -389
    ("203855444", 2019, "Cost of Goods Sold"): 1000,  # -20,949
    ("203855444", 2019, "Depreciation and amortisation"): 1000,  # -1,017
    ("203855444", 2019, "Discontinued Operations"): 1000,  # -56,384
    ("203855444", 2019, "Gross Profit"): 1000,  # 12,015
    ("203855444", 2019, "Interest Expense"): 1000,  # -1,402
    ("203855444", 2019, "Net Cash from Operating Activities"): 1000,  # 414
    ("203855444", 2019, "Net Revenue"): 1000,  # 32,964
    ("203855444", 2019, "Net cash inflow for the year"): 1000,  # -2,436
    ("203855444", 2019, "Net cash raised in financing activities"): 1000,  # 1,478
    ("203855444", 2019, "Net cash used in investing activities"): 1000,  # -4,328
    ("203855444", 2019, "Net gain (loss) from foreign exchange operations"): 1000,  # -803
    ("203855444", 2019, "Operating income"): 1000,  # 2,373
    ("203855444", 2019, "Other administrative and operating expenses"): 1000,  # -1,634
    ("203855444", 2019, "Other financial income"): 1000,  # 3,004
    ("203855444", 2019, "Other income"): 1000,  # -410
    ("203855444", 2019, "Owners of the parent"): 1000,  # -53,622
    ("203855444", 2019, "Personnel expense"): 1000,  # -4,255
    ("203855444", 2019, "Profit/(loss)"): 1000,  # -53,622
    ("203855444", 2019, "Profit/(loss) before tax from continuing operations"): 1000,  # 2,762
    ("203855444", 2019, "Profit/(loss) from continuing operations"): 1000,  # 2,762
    ("203855444", 2019, "Rental expenses"): 1000,  # -1
    ("203855444", 2019, "Total Comprehensive Income / (Loss)"): 1000,  # -52,087
    ("203855444", 2019, "Total other comprehensive (loss) income"): 1000,  # 1,535
    ("203855444", 2019, "Transportation and transmission expense"): 1000,  # -1,330
    ("203855444", 2019, "Utility and communication services"): 1000,  # -96
    # -- FY2020 --
    ("203855444", 2020, "Advertising and marketing expenses"): 1000,  # -606
    ("203855444", 2020, "Consultancy fee"): 1000,  # -408
    ("203855444", 2020, "Cost of Goods Sold"): 1000,  # -18,220
    ("203855444", 2020, "Depreciation and amortisation"): 1000,  # -872
    ("203855444", 2020, "Gross Profit"): 1000,  # 9,928
    ("203855444", 2020, "Impairment (loss)/reversal of non- financial assets"): 1000,  # -31
    ("203855444", 2020, "Interest Expense"): 1000,  # -1,095
    ("203855444", 2020, "Net Cash from Operating Activities"): 1000,  # 3,665
    ("203855444", 2020, "Net Revenue"): 1000,  # 28,148
    ("203855444", 2020, "Net cash inflow for the year"): 1000,  # 575
    ("203855444", 2020, "Net cash raised in financing activities"): 1000,  # -2,267
    ("203855444", 2020, "Net cash used in investing activities"): 1000,  # -823
    ("203855444", 2020, "Net gain (loss) from foreign exchange operations"): 1000,  # -1,672
    ("203855444", 2020, "Operating income"): 1000,  # 414
    ("203855444", 2020, "Other administrative and operating expenses"): 1000,  # -896
    ("203855444", 2020, "Other financial income"): 1000,  # 16
    ("203855444", 2020, "Owners of the parent"): 1000,  # -2,607
    ("203855444", 2020, "Personnel expense"): 1000,  # -5,314
    ("203855444", 2020, "Profit/(loss)"): 1000,  # -2,337
    ("203855444", 2020, "Profit/(loss) before tax from continuing operations"): 1000,  # -2,337
    ("203855444", 2020, "Profit/(loss) from continuing operations"): 1000,  # -2,337
    ("203855444", 2020, "Rental expenses"): 1000,  # -81
    ("203855444", 2020, "Total Comprehensive Income / (Loss)"): 1000,  # -2,607
    ("203855444", 2020, "Total other comprehensive (loss) income"): 1000,  # -270
    ("203855444", 2020, "Transportation and transmission expense"): 1000,  # -1,269
    ("203855444", 2020, "Utility and communication services"): 1000,  # -44

    # ---- BGA / British-Georgian Academy (204497829) FY2024 — single BS line x1000 too big ----
    # 'Non current borrowings' ingested as 4,008,000,000 (4.0bn) vs the 2017-2023
    # trend of 4-15M (2023 = 4.68M). A school with 54.7M assets / 29.5M equity
    # cannot carry 4bn of debt; the BS does not balance at that scale. Everything
    # else in FY2024 is correct — target=1 rescales this one row to 4.008M.
    # Surfaced 2026-07-01 (GCAP portfolio accuracy review); same shape as the L&G
    # FY2018 BS block above.
    ("204497829", 2024, "Non current borrowings"): 1,  # 4,008,000,000 -> 4,008,000

    # ---- NP tie-out batch (2026-07-07) — top offenders of the T1.4 data-quality
    # scan's category (c). Each filing's TOTALs (Net Revenue, Profit/(loss)) are
    # on the correct scale but individual COMPONENT rows landed x1000 too big,
    # blowing up the bottom-up PBT/EBITDA into the billions (and, for the OpEx-
    # side rows, corrupting metrics_panel EBITDA/EBIT). Every row below is
    # 100-7,000x its own line's other-year median; where the statement allows it
    # the fix ties out exactly (see per-row notes). target=1 -> /1000.

    # ორბი ბეტონი (448382090) — concrete, Rev ~9-16M. FY2019 calc PBT was -4.02bn.
    ("448382090", 2019, "- sale of goods"): 1,           # 14,933,266,000 -> 14,933,266 (vs Net Revenue TOTAL 14,754,876)
    ("448382090", 2019, "Purchases"): 1,                 # -9,080,611,000 -> -9,080,611 (vs COGS TOTAL -10,667,472)
    ("448382090", 2019, "Total operating expense"): 1,   # -4,266,799,000 -> -4,266,799 (the "EBITDA -4.26bn" row)
    ("448382090", 2019, "Interest income from:"): 1,     # 240,492,000 -> 240,492 = EXACTLY its own 'Other financial income' component
    ("448382090", 2018, "Other Income"): 1,              # 644,625,000 -> 644,625 (peers 66K-1.8M)
    ("448382090", 2018, "Net gain (loss) from foreign exchange operations"): 1,  # 101,836,000 -> 101,836 (peer med 83K)
    ("448382090", 2018, "Interest income from:"): 1,     # 227,198,000 -> 227,198 (FY2019 twin also x1000 - both staged; peer-median gate is blind to the pair, hot-patched surgically)
    ("448382090", 2018, "Interest expense from:"): 1,    # -221,515,000 -> -221,515 (fits 'Interest Expense' series -187K/-287K/-366K; no same-line peers -> --force)

    # ა გრუფი (405291795) — insurance holding. One row: dividends x1000.
    ("405291795", 2018, "Dividends received"): 1,        # 3,773,488,000 -> 3,773,488 (peers 9.3-28M; PBT then ties reported 18.45M within 6%)

    # ჯიარ ქონების მართვა (202460103) — FY2020/21 whole-year fixed by the YEAR
    # tier; these rows stayed x1000 ABOVE their year-mates (ROW > YEAR keeps the
    # relative /1000 on rebuild). PBT ties EXACTLY without the OpEx impairment
    # copy: -2,918K +589K -147K +332K +207K -7K +2,237K = 293K = reported.
    # Keyed on the CANONICAL paren spelling — LINE_ITEM_ALIASES canonicalizes
    # "Impairment loss/reversal of non-financial assets" (the spelling this row
    # carries in the raw export) before the reconciler runs.
    ("202460103", 2021, "Impairment (loss)/reversal of non- financial assets"): 1,  # 2,237,000,000 -> 2,237,000 (x1000 duplicate of the on-scale IS_OtherExpense twin; scale fix - the twin now dedups away via LINE_ITEM_ALIASES). CAUTION: no same-line peers and the post-fix value still exceeds the --force divide bound, so this stays 'verify' forever - a blanket `--apply --force` would shrink it AGAIN. Never blanket-force; eyeball the plan.
    ("202460103", 2021, "Total Comprehensive Income / (Loss)"): 1,  # 293,000,000 -> 293,000 = reported Profit/(loss)
    ("202460103", 2020, "Total Comprehensive Income / (Loss)"): 1,  # -1,603,000,000 -> -1,603,000 = reported Profit/(loss) (surfaced while triaging FY2021)

    # ალკორითეილ გრუპ (406222859) FY2018 — five rows x1000. Internal proof at
    # /1000 is EXACT: EBIT recomputes to 1,220,750 = stored Operating income,
    # and PBT 1,220,750 + 21,000 (fin.income) + 5,686 (FX) = 1,247,436 = reported.
    ("406222859", 2018, "Personnel expense"): 1,         # -1,979,113,000 -> -1,979,113 (peer med -3.6M)
    ("406222859", 2018, "Advertising and marketing expenses"): 1,  # -249,605,000 -> -249,605 (peer med -280K)
    ("406222859", 2018, "Other financial income"): 1,    # 21,000,000 -> 21,000 (exact PBT tie)
    ("406222859", 2018, "Net gain (loss) from foreign exchange operations"): 1,  # 5,686,000 -> 5,686 (exact PBT tie; only 18x peer med so under the 100x gate - hot-patched surgically)
    ("406222859", 2018, "Profit/(loss) from continuing operations"): 1,  # 1,247,436,000 -> 1,247,436 = reported Profit/(loss)

    # დომუსი (404908864) FY2018 — single row x1000 (Rev 30.3M, reported NP 8.9M).
    ("404908864", 2018, "Impairment (loss)/reversal of financial assets"): 1,  # 1,537,420,000 -> 1,537,420 (peers -125K/-215K/+230K)

    # ---- Georgia Pharmacy Group / ex-GHG (405098399) FY2021-2024 — D&A x1000 ----
    # 2026-07-10 GCAP PDF audit: the "Depreciation and amortisation" line ingested
    # x1000 too SMALL (stored in thousands while every other line of the filing is
    # raw GEL) for FY2021 onward — a clean 1000x cliff at the FY2020->FY2021 boundary
    # (FY2020 D&A -58,167,000 raw GEL; FY2021 -62,381 = should be -62,381,000). EBITDA
    # excludes D&A so it stayed correct, but EBIT (= EBITDA + D&A) was overstated by
    # ~the full D&A each year. FY2024 (41,911k) + FY2023 (35,137k) tie to the audited
    # reportal.ge IFRS PDFs to the thousand; sister-entity Gepha (201991229) stores the
    # identical-magnitude D&A correctly, so this is line-specific to 405098399. FY2021
    # (-62,381) + FY2022 (-71,198) show the identical broken magnitude and are corrected
    # for the same reason (internal evidence: smooth GEL-million series, EBITDA untouched;
    # not PDF-audited). target=1000 lifts each to full GEL. Gate-confirmed (each ~1000x
    # below its own other-year median, dominated by the on-scale FY2017-2020 values).
    # Corrected EBIT: FY2021 155,580,450 / FY2022 117,240,783 / FY2023 75,281,394 /
    # FY2024 74,522,000. See memory project_gcap_pdf_audit_2026-07-10.
    ("405098399", 2021, "Depreciation and amortisation"): 1000,  # IS -62,381 -> -62,381,000
    ("405098399", 2022, "Depreciation and amortisation"): 1000,  # IS -71,198 -> -71,198,000
    ("405098399", 2023, "Depreciation and amortisation"): 1000,  # IS -35,137 -> -35,137,000 (audited)
    ("405098399", 2024, "Depreciation and amortisation"): 1000,  # IS -41,911 -> -41,911,000 (audited)

    # ---- BS "Total Liabilities" x1000 mistags (2026-07-24) — 3 NCI group filers
    # whose balance sheet did not foot (flagged by scripts/wrong_filing_rules.py
    # bs_identity_broken). In each the "Total Liabilities" TOTAL row (and, where
    # present, the "Total current liabilities" COMPONENT) was ingested x1000 too
    # SMALL while Total Assets and Total Equity landed on the correct full-GEL
    # scale — a classic Bucket B partial mistag. PROOF (no PDF needed): the
    # filing's own correct Assets and Equity totals pin the liabilities, and the
    # stored value x1000 equals (Assets - Equity) EXACTLY to the GEL for every
    # year below. Display/statement-integrity only: metrics_panel stores no total
    # liabilities and TotalDebt sums the borrowing categories, so no headline
    # metric moves (verified per filing). target=1000 lifts each row to full GEL.
    # -- სს ქართუ ჯგუფი (Kartu Group) 204876642 --
    ("204876642", 2016, "Total Liabilities"): 1000,  # BS 1,098,094 -> 1,098,094,000 (= A-E)
    ("204876642", 2017, "Total Liabilities"): 1000,  # BS 920,197 -> 920,197,000
    ("204876642", 2018, "Total Liabilities"): 1000,  # BS 852,509 -> 852,509,000
    # -- სს ა გრუფი (A Group) 405291795 --
    ("405291795", 2021, "Total Liabilities"): 1000,  # BS 98,568 -> 98,568,000 (= A-E)
    ("405291795", 2021, "Total current liabilities"): 1000,  # BS 40,414 -> 40,414,000
    ("405291795", 2022, "Total Liabilities"): 1000,  # BS 105,821 -> 105,821,000 (= A-E)
    ("405291795", 2022, "Total current liabilities"): 1000,  # BS 35,210 -> 35,210,000
    ("405291795", 2023, "Total Liabilities"): 1000,  # BS 121,412 -> 121,412,000 (= A-E)
    # -- სს პრივატი (Privati) 404392082 --
    ("404392082", 2021, "Total Liabilities"): 1000,  # BS 15,897 -> 15,897,000 (= A-E)
    ("404392082", 2021, "Total current liabilities"): 1000,  # BS 15,897 -> 15,897,000
    ("404392082", 2022, "Total Liabilities"): 1000,  # BS 23,420 -> 23,420,000 (= A-E)
    ("404392082", 2022, "Total current liabilities"): 1000,  # BS 23,420 -> 23,420,000
    # ======================================================================
    # STAGED — NOT ACTIVE. RMS unit-triage batch, 2026-08-06.
    # ----------------------------------------------------------------------
    # Deliberately COMMENTED OUT. Every live key in this dict is honoured by
    # `rebuild_db.py all`, so an un-reviewed entry would apply itself on the
    # next rebuild — CLAUDE.md hard constraint #6. Un-commenting IS approval.
    # Full evidence: docs/reviews/2026-08-06-rms-unit-triage.md.
    #
    # All three blocks are the DB ×1000 too SMALL → target 1000. Each is
    # backed by >=2 independent signals (RMS Income/Assets tie + own-history
    # continuity, or a closed roll-up identity). They live at the ROW tier
    # rather than the YEAR tier for the reasons stated per block.
    # ======================================================================

    # ---- სს ლილო 1 (206268741) FY2023 + FY2024 — whole-year shrink, ROW tier ----
    # The year is unit-CLEAN (0 rows already on scale), so a YEAR override
    # would be correct in principle — but `apply_year_overrides.py` GATE-SKIPS
    # it and has no --force-entry escape. The company's TA jumped ₾13.6M
    # (FY2020) → ₾70.5M (FY2021), so the all-year TA median sits ₾13.9M and
    # the shrunk year reads only ~190× below it, under the 500× gate. The ROW
    # tier compares each line against ITS OWN other-year median (~1000× off)
    # and passes, and it has --force-entry if any single line still gates out.
    # PROOF: RMS ties EXACTLY at ×1000 on both metrics, both years —
    #   FY2023 Income 11,143,000 / Assets 73,068,000 vs panel 11,143 / 73,068
    #   FY2024 Income 11,201,000 / Assets 81,239,000 vs panel 11,201 / 81,239
    # plus FY2022 is on-scale (Rev ₾9.67M, TA ₾70.41M, RMS ties 1:1), plus
    # |Personnel expense| / RMS Employees = ₾26 per employee per YEAR at the
    # stored scale (impossible) → ₾25.8K/₾26.2K at ×1000 (normal).
    # -- FY2023 --
    # ('206268741', 2023, 'Cash advances made to other parties'): 1000,  # BS_Assets 178 -> 178,000
    # ('206268741', 2023, 'Cash and Cash Equivalents'): 1000,  # BS_Assets 2,554 -> 2,554,000
    # ('206268741', 2023, 'Current Inventory'): 1000,  # BS_Assets 55 -> 55,000
    # ('206268741', 2023, 'Investment Property'): 1000,  # BS_Assets 67,220 -> 67,220,000
    # ('206268741', 2023, 'Other intangible assets'): 1000,  # BS_Assets 111 -> 111,000
    # ('206268741', 2023, 'Property, Plant and Equipment'): 1000,  # BS_Assets 1,697 -> 1,697,000
    # ('206268741', 2023, 'Revaluation reserve of property, plant and equipment'): 1000,  # BS_Assets -1 -> -1,000
    # ('206268741', 2023, 'Total Assets'): 1000,  # BS_Assets 73,068 -> 73,068,000
    # ('206268741', 2023, 'Total current assets'): 1000,  # BS_Assets 4,040 -> 4,040,000
    # ('206268741', 2023, 'Trade Receivables'): 1000,  # BS_Assets 1,253 -> 1,253,000
    # ('206268741', 2023, 'Property, plant and equipment revaluation reserve'): 1000,  # BS_Equity 128 -> 128,000
    # ('206268741', 2023, 'Retained earnings / (Accumulated deficit)'): 1000,  # BS_Equity 35,836 -> 35,836,000
    # ('206268741', 2023, 'Share capital (in case of Limited Liability Company - "capital", in case of cooperative entity - "unit capital"'): 1000,  # BS_Equity 19,836 -> 19,836,000
    # ('206268741', 2023, 'Total Equity'): 1000,  # BS_Equity 55,800 -> 55,800,000
    # ('206268741', 2023, 'Current Borrowings'): 1000,  # BS_Liabilities 2,766 -> 2,766,000
    # ('206268741', 2023, 'Finance lease payable'): 1000,  # BS_Liabilities 831 -> 831,000
    # ('206268741', 2023, 'Non current borrowings'): 1000,  # BS_Liabilities 13,390 -> 13,390,000
    # ('206268741', 2023, 'Other current liabilities'): 1000,  # BS_Liabilities 52 -> 52,000
    # ('206268741', 2023, 'Total Liabilities'): 1000,  # BS_Liabilities 17,268 -> 17,268,000
    # ('206268741', 2023, 'Total Liabilities and Equity'): 1000,  # BS_Liabilities 73,068 -> 73,068,000
    # ('206268741', 2023, 'Total current liabilities'): 1000,  # BS_Liabilities 3,047 -> 3,047,000
    # ('206268741', 2023, 'Trade payables'): 1000,  # BS_Liabilities 229 -> 229,000
    # ('206268741', 2023, 'Cash at the beginning of the year'): 1000,  # CF 758 -> 758,000
    # ('206268741', 2023, 'Cash at the end of the year'): 1000,  # CF 2,554 -> 2,554,000
    # ('206268741', 2023, 'Net Cash from Operating Activities'): 1000,  # CF 5,124 -> 5,124,000
    # ('206268741', 2023, 'Net cash inflow for the year'): 1000,  # CF 1,796 -> 1,796,000
    # ('206268741', 2023, 'Net cash raised in financing activities'): 1000,  # CF -1,835 -> -1,835,000
    # ('206268741', 2023, 'Net cash used in investing activities'): 1000,  # CF -1,493 -> -1,493,000
    # ('206268741', 2023, 'Auditors remuneration'): 1000,  # IS -14 -> -14,000
    # ('206268741', 2023, 'Consultancy fee'): 1000,  # IS -170 -> -170,000
    # ('206268741', 2023, 'Cost of Goods Sold'): 1000,  # IS -1,475 -> -1,475,000
    # ('206268741', 2023, 'Depreciation and amortisation'): 1000,  # IS -299 -> -299,000
    # ('206268741', 2023, 'Gross Profit'): 1000,  # IS 9,668 -> 9,668,000
    # ('206268741', 2023, 'Interest Expense'): 1000,  # IS -2,293 -> -2,293,000
    # ('206268741', 2023, 'Net Gains/(losses) from revaluation and disposal of investment properties'): 1000,  # IS -436 -> -436,000
    # ('206268741', 2023, 'Net Revenue'): 1000,  # IS 11,143 -> 11,143,000
    # ('206268741', 2023, 'Net gain (loss) from foreign exchange operations'): 1000,  # IS -3 -> -3,000
    # ('206268741', 2023, 'Operating income'): 1000,  # IS 6,343 -> 6,343,000
    # ('206268741', 2023, 'Other administrative and operating expenses'): 1000,  # IS -650 -> -650,000
    # ('206268741', 2023, 'Other financial income'): 1000,  # IS 107 -> 107,000
    # ('206268741', 2023, 'Other income'): 1000,  # IS -20 -> -20,000
    # ('206268741', 2023, 'Personnel expense'): 1000,  # IS -1,728 -> -1,728,000
    # ('206268741', 2023, 'Profit/(loss)'): 1000,  # IS 3,698 -> 3,698,000
    # ('206268741', 2023, 'Profit/(loss) before tax from continuing operations'): 1000,  # IS 3,698 -> 3,698,000
    # ('206268741', 2023, 'Profit/(loss) from continuing operations'): 1000,  # IS 3,698 -> 3,698,000
    # ('206268741', 2023, 'Rental expenses'): 1000,  # IS -116 -> -116,000
    # ('206268741', 2023, 'Taxes other than on income'): 1000,  # IS -348 -> -348,000
    # ('206268741', 2023, 'Total Comprehensive Income / (Loss)'): 1000,  # IS 3,697 -> 3,697,000
    # ('206268741', 2023, 'Total other comprehensive (loss) income'): 1000,  # IS -1 -> -1,000
    # -- FY2024 --
    # ('206268741', 2024, 'Cash advances made to other parties'): 1000,  # BS_Assets 3,521 -> 3,521,000
    # ('206268741', 2024, 'Cash and Cash Equivalents'): 1000,  # BS_Assets 3,194 -> 3,194,000
    # ('206268741', 2024, 'Current Inventory'): 1000,  # BS_Assets 41 -> 41,000
    # ('206268741', 2024, 'Investment Property'): 1000,  # BS_Assets 71,102 -> 71,102,000
    # ('206268741', 2024, 'Other intangible assets'): 1000,  # BS_Assets 85 -> 85,000
    # ('206268741', 2024, 'Property, Plant and Equipment'): 1000,  # BS_Assets 2,007 -> 2,007,000
    # ('206268741', 2024, 'Revaluation reserve of property, plant and equipment'): 1000,  # BS_Assets 7 -> 7,000
    # ('206268741', 2024, 'Total Assets'): 1000,  # BS_Assets 81,239 -> 81,239,000
    # ('206268741', 2024, 'Total current assets'): 1000,  # BS_Assets 8,045 -> 8,045,000
    # ('206268741', 2024, 'Trade Receivables'): 1000,  # BS_Assets 1,289 -> 1,289,000
    # ('206268741', 2024, 'Property, plant and equipment revaluation reserve'): 1000,  # BS_Equity 129 -> 129,000
    # ('206268741', 2024, 'Retained earnings / (Accumulated deficit)'): 1000,  # BS_Equity 41,960 -> 41,960,000
    # ('206268741', 2024, 'Share capital (in case of Limited Liability Company - "capital", in case of cooperative entity - "unit capital"'): 1000,  # BS_Equity 19,836 -> 19,836,000
    # ('206268741', 2024, 'Total Equity'): 1000,  # BS_Equity 61,925 -> 61,925,000
    # ('206268741', 2024, 'Current Borrowings'): 1000,  # BS_Liabilities 2,070 -> 2,070,000
    # ('206268741', 2024, 'Finance lease payable'): 1000,  # BS_Liabilities 775 -> 775,000
    # ('206268741', 2024, 'Non current borrowings'): 1000,  # BS_Liabilities 15,753 -> 15,753,000
    # ('206268741', 2024, 'Other current liabilities'): 1000,  # BS_Liabilities 345 -> 345,000
    # ('206268741', 2024, 'Total Liabilities'): 1000,  # BS_Liabilities 19,314 -> 19,314,000
    # ('206268741', 2024, 'Total Liabilities and Equity'): 1000,  # BS_Liabilities 81,239 -> 81,239,000
    # ('206268741', 2024, 'Total current liabilities'): 1000,  # BS_Liabilities 2,786 -> 2,786,000
    # ('206268741', 2024, 'Trade payables'): 1000,  # BS_Liabilities 371 -> 371,000
    # ('206268741', 2024, 'Cash at the beginning of the year'): 1000,  # CF 2,554 -> 2,554,000
    # ('206268741', 2024, 'Cash at the end of the year'): 1000,  # CF 3,194 -> 3,194,000
    # ('206268741', 2024, 'Effect of exchange rate changes on cash and cash equivalents'): 1000,  # CF 8 -> 8,000
    # ('206268741', 2024, 'Net Cash from Operating Activities'): 1000,  # CF 1,911 -> 1,911,000
    # ('206268741', 2024, 'Net cash inflow for the year'): 1000,  # CF 632 -> 632,000
    # ('206268741', 2024, 'Net cash raised in financing activities'): 1000,  # CF 1,131 -> 1,131,000
    # ('206268741', 2024, 'Net cash used in investing activities'): 1000,  # CF -2,410 -> -2,410,000
    # ('206268741', 2024, 'Auditors remuneration'): 1000,  # IS -14 -> -14,000
    # ('206268741', 2024, 'Consultancy fee'): 1000,  # IS -194 -> -194,000
    # ('206268741', 2024, 'Cost of Goods Sold'): 1000,  # IS -1,602 -> -1,602,000
    # ('206268741', 2024, 'Depreciation and amortisation'): 1000,  # IS -266 -> -266,000
    # ('206268741', 2024, 'Gross Profit'): 1000,  # IS 9,599 -> 9,599,000
    # ('206268741', 2024, 'Interest Expense'): 1000,  # IS -1,714 -> -1,714,000
    # ('206268741', 2024, 'Net Gains/(losses) from revaluation and disposal of investment properties'): 1000,  # IS 2,045 -> 2,045,000
    # ('206268741', 2024, 'Net Revenue'): 1000,  # IS 11,201 -> 11,201,000
    # ('206268741', 2024, 'Net gain (loss) from foreign exchange operations'): 1000,  # IS 7 -> 7,000
    # ('206268741', 2024, 'Operating income'): 1000,  # IS 6,069 -> 6,069,000
    # ('206268741', 2024, 'Other administrative and operating expenses'): 1000,  # IS -664 -> -664,000
    # ('206268741', 2024, 'Other financial income'): 1000,  # IS 205 -> 205,000
    # ('206268741', 2024, 'Other income'): 1000,  # IS 1 -> 1,000
    # ('206268741', 2024, 'Personnel expense'): 1000,  # IS -1,726 -> -1,726,000
    # ('206268741', 2024, 'Profit/(loss)'): 1000,  # IS 6,613 -> 6,613,000
    # ('206268741', 2024, 'Profit/(loss) before tax from continuing operations'): 1000,  # IS 6,613 -> 6,613,000
    # ('206268741', 2024, 'Profit/(loss) from continuing operations'): 1000,  # IS 6,613 -> 6,613,000
    # ('206268741', 2024, 'Rental expenses'): 1000,  # IS -205 -> -205,000
    # ('206268741', 2024, 'Taxes other than on income'): 1000,  # IS -461 -> -461,000
    # ('206268741', 2024, 'Total Comprehensive Income / (Loss)'): 1000,  # IS 6,620 -> 6,620,000
    # ('206268741', 2024, 'Total other comprehensive (loss) income'): 1000,  # IS 7 -> 7,000

    # ---- რეგიონული ჯანდაცვის ცენტრი (236035517) FY2022 — inverse Bucket B ----
    # NOT one of the 37 RMS hits (the RMS file has no FY2022 row for this
    # company) but the best-proved case in the batch, entirely from our own
    # data. The IS + CF block is on scale (Net Revenue ₾15,980,000, Personnel
    # -₾14,445,000); the whole BS block is ×1000 short. The standing NOTE in
    # UNIT_RECONCILER_YEAR_OVERRIDES already predicted this ("2022 is
    # row-level (Rev ₾15.98M OK, TA ₾42K off)").
    # PROOF 1 (cross-statement): CF "Cash at the end of the year" = 6,098,000
    #   while BS "Cash and Cash Equivalents" = 6,098 — same figure, two
    #   statements, exactly ×1000 apart.
    # PROOF 2 (roll-ups close to the unit at the stored scale):
    #   Total current assets 14,012 = Cash 6,098 + Inventory 5,127 + TR 2,787
    #   TA 42,136 = current 14,012 + PP&E 28,114 + intangibles 10
    #   TE 38,115 = Share capital 37,382 + Other Reserves 2,430 + RE (-1,697)
    #   TA 42,136 = TL 4,021 + TE 38,115
    # PROOF 3 (continuity): FY2021 TA ₾42,209,000; RMS FY2023 Assets
    #   ₾36,979,000. Post-fix ₾42,136,000 lands between them.
    # EXCLUDED: 'Changes in finished goods inventory and work in progress'
    #   (-5,963,000) — an IS row mis-sectioned into BS_Assets by the
    #   name-keyed taxonomy; it is ALREADY on the IS scale.
    # ('236035517', 2022, 'Cash and Cash Equivalents'): 1000,  # BS_Assets 6,098 -> 6,098,000
    #   EXCLUDED — DO NOT STAGE: ('236035517', 2022, 'Changes in finished goods inventory
    #   and work in progress') is at -5,963,000, i.e. ALREADY on the IS scale (it is an IS
    #   row mis-sectioned into BS_Assets). ×1000 would make it -₾5.963B.
    # ('236035517', 2022, 'Current Inventory'): 1000,  # BS_Assets 5,127 -> 5,127,000
    # ('236035517', 2022, 'Other intangible assets'): 1000,  # BS_Assets 10 -> 10,000
    # ('236035517', 2022, 'Property, Plant and Equipment'): 1000,  # BS_Assets 28,114 -> 28,114,000
    # ('236035517', 2022, 'Total Assets'): 1000,  # BS_Assets 42,136 -> 42,136,000
    # ('236035517', 2022, 'Total current assets'): 1000,  # BS_Assets 14,012 -> 14,012,000
    # ('236035517', 2022, 'Trade Receivables'): 1000,  # BS_Assets 2,787 -> 2,787,000
    # ('236035517', 2022, 'Other Reserves'): 1000,  # BS_Equity 2,430 -> 2,430,000
    # ('236035517', 2022, 'Retained earnings / (Accumulated deficit)'): 1000,  # BS_Equity -1,697 -> -1,697,000
    # ('236035517', 2022, 'Share capital (in case of Limited Liability Company - "capital", in case of cooperative entity - "unit capital"'): 1000,  # BS_Equity 37,382 -> 37,382,000
    # ('236035517', 2022, 'Total Equity'): 1000,  # BS_Equity 38,115 -> 38,115,000
    # ('236035517', 2022, 'Total equity attributable to owners of parent'): 1000,  # BS_Equity 38,115 -> 38,115,000
    # ('236035517', 2022, 'Other current liabilities'): 1000,  # BS_Liabilities 303 -> 303,000
    # ('236035517', 2022, 'Post-employment benefits'): 1000,  # BS_Liabilities 1,884 -> 1,884,000
    # ('236035517', 2022, 'Total Liabilities'): 1000,  # BS_Liabilities 4,021 -> 4,021,000
    # ('236035517', 2022, 'Total Liabilities and Equity'): 1000,  # BS_Liabilities 42,136 -> 42,136,000
    # ('236035517', 2022, 'Total current liabilities'): 1000,  # BS_Liabilities 4,022 -> 4,022,000
    # ('236035517', 2022, 'Trade payables'): 1000,  # BS_Liabilities 1,834 -> 1,834,000

    # ---- აჭარა.ქომ (404582055) FY2024 — MIXED-unit year, ROW tier mandatory ----
    # 41 of 48 rows are ~500-2000× below their own other-year median; ONE row,
    # 'Investments in Subsidiaries', is already on full-GEL scale at 701,000.
    # It was 5,000 in every year FY2019-FY2023 (a literal ₾5,000 stake printed
    # as "5" in a thousands column) — i.e. that single line kept its ×1000
    # treatment in FY2024 while the other 47 lost it. A YEAR override would
    # inflate it to ₾701M against a ₾57M balance sheet.
    # PROOF it must be excluded — the asset roll-up closes EXACTLY without it:
    #   TA 57,319 = current 27,779 + advances 23,580 + PP&E 4,314
    #               + other non-current 1,324 + intangibles 322
    # PROOF of direction: RMS FY2024 consolidated Assets 57,319,000 == panel
    #   TA × 1000 EXACTLY; FY2023 is on scale (Rev ₾35.87M / TA ₾68.04M);
    #   |Personnel| / 317 employees = ₾65 per employee per YEAR at the stored
    #   scale → ₾64,896 at ×1000.
    # PROOF the IS block moves as one — the PBT identity closes at the stored
    #   scale: 3,046 + 287 + 206 - 2,008 - 11,507 = -9,976 = PBT.
    # ALSO EXCLUDED (analyst call, immaterial): 'Loans and advances' (90) and
    #   'Finance lease payable' (1,407) sit outside every roll-up identity and
    #   have no same-line reference year. Everything metrics_panel reads is in
    #   the staged set, so the panel-visible fix is complete either way.
    # ('404582055', 2024, 'Cash advances made to other parties'): 1000,  # BS_Assets 23,580 -> 23,580,000
    # ('404582055', 2024, 'Cash and Cash Equivalents'): 1000,  # BS_Assets 761 -> 761,000
    # ('404582055', 2024, 'Current Inventory'): 1000,  # BS_Assets 65 -> 65,000
    #   EXCLUDED: 'Investments in Subsidiaries' = 701,000
    #   EXCLUDED: 'Loans and advances' = 90
    # ('404582055', 2024, 'Other intangible assets'): 1000,  # BS_Assets 322 -> 322,000
    # ('404582055', 2024, 'Other non current assets'): 1000,  # BS_Assets 1,324 -> 1,324,000
    # ('404582055', 2024, 'Property, Plant and Equipment'): 1000,  # BS_Assets 4,314 -> 4,314,000
    # ('404582055', 2024, 'Total Assets'): 1000,  # BS_Assets 57,319 -> 57,319,000
    # ('404582055', 2024, 'Total current assets'): 1000,  # BS_Assets 27,779 -> 27,779,000
    # ('404582055', 2024, 'Trade Receivables'): 1000,  # BS_Assets 26,863 -> 26,863,000
    # ('404582055', 2024, 'Retained earnings / (Accumulated deficit)'): 1000,  # BS_Equity -66,834 -> -66,834,000
    # ('404582055', 2024, 'Share capital (in case of Limited Liability Company - "capital", in case of cooperative entity - "unit capital"'): 1000,  # BS_Equity 104,697 -> 104,697,000
    # ('404582055', 2024, 'Total Equity'): 1000,  # BS_Equity 37,863 -> 37,863,000
    # ('404582055', 2024, 'Total equity attributable to owners of parent'): 1000,  # BS_Equity 37,863 -> 37,863,000
    # ('404582055', 2024, 'Current Borrowings'): 1000,  # BS_Liabilities 11,052 -> 11,052,000
    #   EXCLUDED: 'Finance lease payable' = 1,407
    # ('404582055', 2024, 'Other current liabilities'): 1000,  # BS_Liabilities 452 -> 452,000
    # ('404582055', 2024, 'Post-employment benefits'): 1000,  # BS_Liabilities 619 -> 619,000
    # ('404582055', 2024, 'Total Liabilities'): 1000,  # BS_Liabilities 19,456 -> 19,456,000
    # ('404582055', 2024, 'Total Liabilities and Equity'): 1000,  # BS_Liabilities 57,319 -> 57,319,000
    # ('404582055', 2024, 'Total current liabilities'): 1000,  # BS_Liabilities 18,308 -> 18,308,000
    # ('404582055', 2024, 'Trade payables'): 1000,  # BS_Liabilities 5,926 -> 5,926,000
    # ('404582055', 2024, 'Cash at the beginning of the year'): 1000,  # CF 352 -> 352,000
    # ('404582055', 2024, 'Cash at the end of the year'): 1000,  # CF 761 -> 761,000
    # ('404582055', 2024, 'Effect of exchange rate changes on cash and cash equivalents'): 1000,  # CF -193 -> -193,000
    # ('404582055', 2024, 'Net Cash from Operating Activities'): 1000,  # CF -5,510 -> -5,510,000
    # ('404582055', 2024, 'Net cash inflow for the year'): 1000,  # CF 602 -> 602,000
    # ('404582055', 2024, 'Net cash raised in financing activities'): 1000,  # CF 6,436 -> 6,436,000
    # ('404582055', 2024, 'Net cash used in investing activities'): 1000,  # CF -324 -> -324,000
    # ('404582055', 2024, 'Advertising and marketing expenses'): 1000,  # IS -5,429 -> -5,429,000
    # ('404582055', 2024, 'Depreciation and amortisation'): 1000,  # IS -2,502 -> -2,502,000
    # ('404582055', 2024, 'Gross Profit'): 1000,  # IS 39,797 -> 39,797,000
    # ('404582055', 2024, 'Impairment (loss)/reversal of non- financial assets'): 1000,  # IS -11,507 -> -11,507,000
    # ('404582055', 2024, 'Interest Expense'): 1000,  # IS -2,008 -> -2,008,000
    # ('404582055', 2024, 'Net Revenue'): 1000,  # IS 39,797 -> 39,797,000
    # ('404582055', 2024, 'Net gain (loss) from foreign exchange operations'): 1000,  # IS 287 -> 287,000
    # ('404582055', 2024, 'Operating income'): 1000,  # IS 3,046 -> 3,046,000
    # ('404582055', 2024, 'Other administrative and operating expenses'): 1000,  # IS -8,662 -> -8,662,000
    # ('404582055', 2024, 'Other financial income'): 1000,  # IS 206 -> 206,000
    # ('404582055', 2024, 'Other operating income'): 1000,  # IS 830 -> 830,000
    # ('404582055', 2024, 'Owners of the parent'): 1000,  # IS -9,976 -> -9,976,000
    # ('404582055', 2024, 'Personnel expense'): 1000,  # IS -20,572 -> -20,572,000
    # ('404582055', 2024, 'Profit/(loss)'): 1000,  # IS -9,976 -> -9,976,000
    # ('404582055', 2024, 'Profit/(loss) before tax from continuing operations'): 1000,  # IS -9,976 -> -9,976,000
    # ('404582055', 2024, 'Profit/(loss) from continuing operations'): 1000,  # IS -9,976 -> -9,976,000
    # ('404582055', 2024, 'Rental expenses'): 1000,  # IS -416 -> -416,000
    # ('404582055', 2024, 'Total Comprehensive Income / (Loss)'): 1000,  # IS -9,976 -> -9,976,000

    # ---- NOT staged ----
    # 405127937 (დომუს - ვაკის პარკი) and 405356305 (ჯი ენ ერ მენეჯმენტი) are
    # whole-COMPANY mistags — every filed year is K-scale, so continuity has no
    # anchor and only UNIT_RECONCILER_COMPANY_OVERRIDES could express the fix,
    # a tier with NO sanity gate. Resolve from the filed PDF first
    # (report_pdf_links: GetFile/32606 and GetFile/30363). Triage doc §5.
    # ======================================================================
}


# ---------------------------------------------------------------------------
# 4c) Sign-normalisation overrides — manual escape hatch
# Consulted by ``normalize_signs`` (scripts/ingest/policies.py).
#
# The DB stores income-statement values SIGNED (expenses negative, income
# positive). The dashboard's EBITDA/EBIT path sums IS_OpEx rows AS STORED, so
# an expense line stored POSITIVE silently inflates computed EBITDA by 2× its
# magnitude. The cousin of the ×1000 unit-mistag bug — see
# docs/reviews/sign-anomaly-triage.md.
#
# These overrides force a curated set of line items to a known sign
# (``-1`` = expense/negative, ``+1`` = income/positive). They mirror the
# unit-reconciler tier design — three scopes, most-specific-wins, all keyed by
# canonical (post-alias) ``LineItemENG``. The value is the REQUIRED sign of the
# row; ``normalize_signs`` flips only rows that contradict it (so it is
# idempotent — a re-run is a clean no-op). Magnitude is never touched, only the
# sign. Zero-valued rows are never flipped.
#
# Precedence (most specific first — the unit-reconciler's LINE > YEAR > COMPANY
# analogue, narrowest scope wins):
#
#   SIGN_OVERRIDES_YEAR  ``{(IdCode, FVYear, LineItemENG): sign}`` — one line of
#       one filing. Use when only a single year of one company is wrong.
#   SIGN_OVERRIDES_LINE  ``{(IdCode, LineItemENG): sign}`` — one line of one
#       company across ALL years. Use for a company that stores ONE line the
#       wrong way every year (a per-company exception to the universe rule).
#   SIGN_OVERRIDES       ``{LineItemENG: sign}`` — the universe-wide rule:
#       applies to EVERY (IdCode, FVYear) carrying that line. The high-value
#       tier (one rule fixes the line for every company at once).
#
# Only add a line to the universe-wide ``SIGN_OVERRIDES`` when the convention is
# overwhelming AND the line is unambiguously single-signed (a true expense /
# contra, never a gain/(loss) or reversal line that legitimately swings — see
# the AMBIGUOUS section of sign-anomaly-triage.md). Per-company / per-year
# exceptions go in the narrower-scoped dicts, which take precedence.
#
# Forced sign must be -1 or +1. Populate only after confirming via
# scripts/find_sign_anomalies.py.
# ---------------------------------------------------------------------------

# Universe-wide line-sign rule: applies to EVERY company-year carrying the line.
SIGN_OVERRIDES: dict[str, int] = {
    # RETIRED 2026-07-10: "Post-employment benefits" was here with -1, on the
    # theory that it was an expense stored positive in 99.94% of rows. The
    # 2026-07-10 raw-sheet scan showed WHY it is positive: every one of its
    # 2,619 raw rows sits on the BS sheet — it is the IAS 19 LIABILITY line of
    # the nonfin BS form, never a P&L row (confirmed against Gepha's audited
    # FY2024 PDF). Flipping BS balances negative was treating the symptom; the
    # line now classifies as BS_Provisions via EXTRA_TAXONOMY_PATCHES and the
    # BS-sheet gate, so no sign rule applies.
}

# Per-(IdCode, LineItemENG) sign override — all years of one company.
SIGN_OVERRIDES_LINE: dict[tuple[str, str], int] = {
    # ("IdCode", "canonical LineItemENG"): -1 or +1,
}

# Per-(IdCode, FVYear, LineItemENG) sign override — one filing of one company.
SIGN_OVERRIDES_YEAR: dict[tuple[str, int, str], int] = {
    # ("IdCode", FVYear, "canonical LineItemENG"): -1 or +1,
}


# ---------------------------------------------------------------------------
# 5) #NAME? / formula error handling
# Excel exports values like "#NAME?" when a cell's formula errors (often when
# the line item starts with "-" or "=" which Excel auto-interprets as a formula).
# These rows are noise; drop them rather than trying to recover the original.
# ---------------------------------------------------------------------------
EXCEL_ERROR_VALUES = frozenset({
    "#NAME?", "#REF!", "#DIV/0!", "#NULL!", "#NUM!", "#VALUE!", "#N/A",
})


def is_excel_error_row(line_item: str | None, value) -> bool:
    """True if the row should be dropped due to an Excel error in either field."""
    if line_item is None:
        return False
    if isinstance(line_item, str) and line_item.strip() in EXCEL_ERROR_VALUES:
        return True
    if isinstance(value, str) and value.strip() in EXCEL_ERROR_VALUES:
        return True
    return False


# ---------------------------------------------------------------------------
# 6) Manual taxonomy patches for items the unmatched-translations list reveals
# After translation succeeds, some items may still lack proper taxonomy entries
# in `line_item_taxonomy`. These supplement scripts/ingest/taxonomy_patches.py.
#
# Many items the auto-classifier put in Section='Other' are actually real P&L
# line items: impairment is an OpEx component; insurance technical items are
# IS items for insurers; reinsurance items net into Other Income/Expense.
# Reclassifying them here means they get included in IS totals instead of dropped.
# ---------------------------------------------------------------------------
EXTRA_TAXONOMY_PATCHES: dict[str, tuple[str, str, str]] = {
    # (LineItemENG): (Section, Category, ItemType)
    "Finance lease payable": ("BS_Liabilities", "BS_NonCurrentLeasePayable", "TOTAL"),
    "- Financial assets": ("BS_Assets", "BS_Investments", "COMPONENT"),
    "- Other": ("IS", "IS_OtherIncome", "COMPONENT"),
    # "Other operating income" is an OpEx-side line — positive values reduce
    # total expense magnitude and flow correctly into EBITDA when summed as-is.
    "Other operating income": ("IS", "IS_OpEx", "COMPONENT"),

    # ---- Impairment items: were Other_Impairment, belong in IS_OpEx ----
    "Impairment (Charge) / Reversal on Inventories": ("IS", "IS_OpEx", "COMPONENT"),
    "Impairment (Charge) / Reversal on Repossessed Collateral": ("IS", "IS_OpEx", "COMPONENT"),
    "Impairment of amounts due from banks": ("IS", "IS_OpEx", "COMPONENT"),
    "Impairment of investment securities held to maturity": ("IS", "IS_OpEx", "COMPONENT"),
    "Impairment of other financial assets": ("IS", "IS_OpEx", "COMPONENT"),
    "Impairment of receivables from financial lease": ("IS", "IS_OpEx", "COMPONENT"),
    "Impairment of trade receivables": ("IS", "IS_OpEx", "COMPONENT"),
    "(Allowance for) / recovery of impairment of other assets": ("IS", "IS_OpEx", "COMPONENT"),
    "(Allowance for) / recovery of impairment of repossessed collateral": ("IS", "IS_OpEx", "COMPONENT"),
    # Items that look like generic "Other" but were in Other_Impairment
    "Investment Securities": ("IS", "IS_OtherIncome", "COMPONENT"),
    "Other Assets": ("IS", "IS_OtherIncome", "COMPONENT"),
    # ("Other financial assets" moved to the BS-sheet block below — it is a
    # BS investments line, not income.)

    # ---- IFRS 17 insurer P&L (2023+ filings) ----
    # Top line + all income/expense components. Categories only affect displayed
    # subtotals; for the PBT tie-out every line is summed. Subtotals + the
    # net-investment-income duplicate are intentionally left untranslated (dropped).
    "Insurance revenue": ("IS", "IS_Revenue", "TOTAL"),
    "Insurance service expenses": ("IS", "IS_COGS", "COMPONENT"),
    "Amounts recoverable from reinsurers": ("IS", "IS_OtherIncome", "COMPONENT"),
    "Allocation of reinsurance premiums paid": ("IS", "IS_OtherExpense", "COMPONENT"),
    "Insurance finance income / (expenses)": ("IS", "IS_OtherExpense", "COMPONENT"),
    "Reinsurance finance income / (expenses)": ("IS", "IS_OtherIncome", "COMPONENT"),
    "Share of profit (loss) of associates": ("IS", "IS_OtherIncome", "COMPONENT"),
    "Share of profit (loss) of joint ventures": ("IS", "IS_OtherIncome", "COMPONENT"),
    "Net gain (loss) on financial assets at fair value through profit or loss": ("IS", "IS_OtherIncome", "COMPONENT"),
    "Net other gains / (losses)": ("IS", "IS_OtherIncome", "COMPONENT"),
    "Net gain (loss) from financial derivatives": ("IS", "IS_OtherIncome", "COMPONENT"),
    "Net gain (loss) from sale or revaluation of investment property": ("IS", "IS_OtherIncome", "COMPONENT"),
    "Finance costs": ("IS", "IS_InterestExpense", "COMPONENT"),

    # ---- BS-sheet lines the name-keyed taxonomy used to misfile into IS ----
    # The 2026-07-10 raw-sheet scan (scan_sheet_conflicts) showed every raw row
    # of these names is filed on the BS sheet (ფინანსური მდგომარეობა) — they are
    # balance-sheet lines of the reportal forms, never P&L flows. Filing them in
    # IS inflated EBITDA/PBT (confirmed vs Gepha's audited FY2024 PDF: EBITDA
    # +16.8% from loyalty + post-employment alone). BS rows / IS rows per name
    # in parentheses.
    "Customer loyalty programmes": ("BS_Liabilities", "BS_OtherCurrentLiabilities", "COMPONENT"),  # (101/0) IFRS 15 contract liability
    "Post-employment benefits": ("BS_Liabilities", "BS_Provisions", "COMPONENT"),  # (2,619/0) IAS 19 liability
    "Employee benefits": ("BS_Liabilities", "BS_OtherCurrentLiabilities", "COMPONENT"),  # (16,864/0) accrued benefits; alias into Personnel expense removed
    "Taxes other than income tax": ("BS_Liabilities", "BS_CurrentTaxPayable", "COMPONENT"),  # (6,070/0) non-profit taxes payable
    "Received grants": ("BS_Liabilities", "BS_OtherNonCurrentLiabilities", "COMPONENT"),  # (562/0) deferred grant income
    "Accrued Income": ("BS_Assets", "BS_OtherCurrentAssets", "COMPONENT"),  # (74/0) accrued-income asset
    "Non-current Assets Held for Sale and Discontinued Operations": ("BS_Assets", "BS_OtherCurrentAssets", "COMPONENT"),  # (210/0) IFRS 5 assets
    "Non-current liabilities Held for Sale and Discontinued Operations": ("BS_Liabilities", "BS_OtherCurrentLiabilities", "COMPONENT"),  # (33/0) IFRS 5 liabilities
    "Reinsurers’ share of insurance liabilities provision": ("BS_Assets", "BS_InsuranceAssets", "COMPONENT"),  # (149/0)
    "Insurance contract liabilities:": ("BS_Liabilities", "BS_CurrentInsuranceLiabilities", "COMPONENT"),  # (133/0)

    # "Other financial assets" is a BS investments line (136 BS-sheet rows,
    # 0 IS-sheet rows) — the old IS_OtherIncome patch leaked asset balances
    # into non-operating income.
    "Other financial assets": ("BS_Assets", "BS_Investments", "COMPONENT"),

    # ---- Reinsurance items (insurer-only — premium ceded, reinsurance finance) ----
    "Insurance premium attributable to reinsurers": ("IS", "IS_OtherExpense", "COMPONENT"),
    "Expenses from Allocation of Premiums Paid to Reinsurers": ("IS", "IS_OtherExpense", "COMPONENT"),
    "Finance Income / (Expenses) from Reinsurance Contracts": ("IS", "IS_OtherIncome", "COMPONENT"),
    "Changes in Reinsurers’ portion in provision for unearned premiums": ("IS", "IS_OtherIncome", "COMPONENT"),

    # ---- Statement-of-Changes-in-Equity MOVEMENT / FLOW lines ----
    # These are period *movements* (opening/closing balances, distributions,
    # other changes, capital increases), NOT balance-sheet equity components.
    # The name-keyed taxonomy filed them into BS_Equity, where they never foot
    # to the equity subtotal and pollute anything reading equity *components*
    # (the recurring theme in project_bs_equity_total_detail_fix). The raw
    # exports file them on the IS sheet (statement of changes in equity), so the
    # BS-sheet gate can't catch them — it only acts BS-sheet -> IS-section.
    #
    # Route them to a dedicated non-BS Section='SOCE' so they leave BS_Equity
    # but stay queryable (dividend history, equity roll-forward) instead of
    # being dropped. Nothing reads 'SOCE' today; the BS view filters on the
    # 'BS_' prefix and metrics_panel picks TotalEquity by name from the
    # BS_TotalEquity 'Total equity' rows — none of which are touched here — so
    # this moves NO metric (golden stays green). ItemType is preserved
    # (Closing balances are TOTAL, everything else COMPONENT).
    #
    # 'Distributions s to owners (i.e. dividends)' was previously parked in
    # BS_Equity/BS_RetainedEarnings by an earlier "out of IS" fix; it belongs
    # with its SOCE siblings.  'Share issue' is context-dependent (a movement
    # only when a share-capital *balance* coexists) and is handled per-co-year
    # by reclass_share_issue_movements() in policies.py, NOT here.
    "Distributions s to owners (i.e. dividends)": ("SOCE", "SOCE_Distributions", "COMPONENT"),
    "Opening Equity": ("SOCE", "SOCE_OpeningEquity", "COMPONENT"),
    "Opening Balance of Equity": ("SOCE", "SOCE_OpeningEquity", "COMPONENT"),
    "Closing Equity": ("SOCE", "SOCE_ClosingEquity", "TOTAL"),
    "Closing Balance of Equity": ("SOCE", "SOCE_ClosingEquity", "TOTAL"),
    "Other Changes of equity": ("SOCE", "SOCE_OtherChanges", "COMPONENT"),
    "Other Changes of retained earnings": ("SOCE", "SOCE_OtherChanges", "COMPONENT"),
    "Issuance of New Shares (Capital Increase)": ("SOCE", "SOCE_ShareIssue", "COMPONENT"),
    "Dividends payable": ("BS_Liabilities", "BS_OtherCurrentLiabilities", "COMPONENT"),

    # ---- Management service fee: an OpEx item, not fee income ----
    # Auto-discovery put "Management service fee" under IS_FeeIncome, but for
    # non-financial filers it is always a negative-value charge from a parent /
    # related party (e.g. H&M Georgia pays a fee to H&M Hennes & Mauritz, Sopmar,
    # Poti Seaport, etc. — 96 companies, 420 rows, 100% negative in the live DB).
    # It's an operating expense, not fee/commission income. Reclassifying it lets
    # it roll into Operating Expenses and removes the spurious "Total Fee &
    # Commission Income" row from the IS view for these companies.
    "Management service fee": ("IS", "IS_OpEx", "COMPONENT"),
}


# ---------------------------------------------------------------------------
# 7) BS-sheet gate — source statement is first truth
# The raw exports carry the filer's own statement assignment per row
# (SheetName). A row filed on the BS sheet (ფინანსური მდგომარეობა) can never
# be a P&L flow, whatever the name-keyed taxonomy says: names like
# "Non-controlling interest" or "Taxes other than on income" are genuine IS
# lines for some rows and BS balances for others, so the name alone cannot
# decide. ``apply_taxonomy_and_filters`` consults this map for any row whose
# source sheet is BS but whose resolved Section is IS:
#
#   name in map, value is a tuple  -> reclassify to that BS classification
#   name in map, value is None     -> drop intentionally (counted in the report)
#   name NOT in map                -> drop + surface in the rebuild report so
#                                     a new conflict name never silently
#                                     pollutes the IS again
#
# Names whose rows are 100% BS-sheet are fixed at the taxonomy level in
# EXTRA_TAXONOMY_PATCHES above (the gate then never fires for them); this map
# carries only the MIXED names (both genuine IS rows and BS rows exist) and
# the intentional drops.
# ---------------------------------------------------------------------------
BS_SHEET_IS_RECLASS: dict[str, tuple[str, str, str] | None] = {
    # Mixed names — per-row split is the whole point of the gate:
    # NCI: 2,896 IS-sheet rows (share of profit) vs 526 BS-sheet rows (equity balance).
    "Non-controlling interest": ("BS_Equity", "BS_NonControllingInterest", "COMPONENT"),
    # Real P&L "taxes other than on income" expense rows live on the IS sheet;
    # GEO-translated BS rows (taxes payable) share the same canonical name.
    "Taxes other than on income": ("BS_Liabilities", "BS_CurrentTaxPayable", "COMPONENT"),
    # Any BS-sheet stragglers still aliased into the personnel line.
    "Personnel expense": ("BS_Liabilities", "BS_OtherCurrentLiabilities", "COMPONENT"),
    # "Other Assets" is patched to IS_OtherIncome above for bank impairment
    # tables, but 810 raw rows are BS-sheet asset balances (2026-07-10
    # verification rebuild) — route those back to the BS per-row.
    "Other Assets": ("BS_Assets", "BS_OtherNonCurrentAssets", "COMPONENT"),

    # Intentional drops:
    # Bare "other" note sub-lines on the BS sheet (34,662 raw rows — inventory
    # note, PPE note, ...). This is the general form of the
    # drop_inventory_other_income_leak fix: the value-equality guard only
    # caught the subset equal to the BS inventory value; the gate removes the
    # whole class from IS. Not reclassified — a bare "other" note fragment has
    # no place on the BS face either.
    "other": None,
    "Other": None,
    # ("Net assets attributable to the bank's equity holders" — 1,929 BS-sheet
    # rows — is already routed to BS_Equity by NET_PROFIT_TAXONOMY_FIXES in
    # rebuild_db.py, so it never reaches this gate.)
}


# Sanity helper used by the rebuild script
def all_extra_aliases() -> dict[str, str]:
    """Return EXTRA_LINE_ITEM_ALIASES (separate from MANUAL_GEO_TO_ENG)."""
    return dict(EXTRA_LINE_ITEM_ALIASES)


def all_extra_merges() -> dict[str, str]:
    return dict(EXTRA_LINE_ITEM_MERGE_TARGETS)


def all_manual_translations() -> dict[str, str]:
    return dict(MANUAL_GEO_TO_ENG)
