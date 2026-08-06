"""Insurance-regulator (insurance.gov.ge) data model — pure, no Streamlit/DB.

The regulator's 12-month return is a fixed-template XLSX with two sheets:
  * ``BS`` — statement of financial position, line codes ``00010``–``00380``.
  * ``IS`` — statement of comprehensive income, line codes ``00010``–``00560``.

Line **codes** (column B of each sheet) are stable across all years and companies,
so they — not the Georgian free text — are the canonical anchors. This module holds:
  * ``BS_CODES`` / ``IS_CODES`` — ordered ``{code: (line_no, geo, eng)}``.
  * subtotal/total code sets, the IS section layout, and the metric-anchor codes.
  * ``SITE_NAME_TO_IDCODE`` — curated crosswalk from the site's company name to our
    DB ``IdCode`` (for names the normalized auto-match can't resolve).
  * ``normalize_site_name`` — used for the auto-match fallback.

Values in the form are absolute GEL (the form header reads "ლარებში").
"""
from __future__ import annotations

import re

# --- Source URLs on insurance.gov.ge ---------------------------------------
# The regulator's statistics index and per-file XLSX download. `SourceFileId`
# (stored per row in `insurance_statements`) plugs into GetFile. `type=4` is
# the 12-month return form these statements are parsed from.
INSURANCE_GOV_INDEX_URL = "https://www.insurance.gov.ge/ka/Statistics/Index/2"
INSURANCE_GOV_FILE_URL = "https://www.insurance.gov.ge/ka/Statistics/GetFile/{id}?type=4"


def insurance_gov_source_url(file_id) -> str:
    """Absolute insurance.gov.ge download URL for a statements SourceFileId."""
    return INSURANCE_GOV_FILE_URL.format(id=file_id)


# --- Balance sheet: code -> (line_no, georgian, english) -------------------
BS_CODES: dict[str, tuple[int, str, str]] = {
    "00010": (1, "ფულადი სახსრები და მათი ეკვივალენტები", "Cash and cash equivalents"),
    "00020": (2, "მოთხოვნები საკრედიტო დაწესებულებების მიმართ", "Receivables from credit institutions (deposits)"),
    "00030": (3, "გასაყიდად არსებული ფინანსური აქტივები", "Available-for-sale financial assets"),
    "00040": (4, "დაფარვის ვადამდე მფლობელობაში არსებული ფინანსური აქტივები", "Held-to-maturity financial assets"),
    "00050": (5, "რეალური ღირებულებით აღრიცხული ფინანსური აქტივები, მოგებაში ან ზარალში ასახვით", "Financial assets at fair value through P&L"),
    "00060": (6, "სადაზღვევო მოთხოვნები, წმინდა", "Insurance receivables, net"),
    "00070": (7, "გადაზღვევის მოთხოვნები, წმინდა", "Reinsurance receivables, net"),
    "00080": (8, "მოთხოვნები გადარჩენილი ქონებიდან", "Receivables from salvage"),
    "00090": (9, "გაცემული სესხები, წმინდა", "Loans issued, net"),
    "00100": (10, "ინვესტიციები მეკავშირე კომპანიებში", "Investments in associates"),
    "00110": (11, "ინვესტიციები შვილობილ კომპანიებში", "Investments in subsidiaries"),
    "00120": (12, "გადამზღვევლის წილი სადაზღვევო რეზერვებში", "Reinsurers' share of insurance reserves"),
    "00130": (13, "გადავადებული საკომისიო ხარჯი", "Deferred acquisition costs"),
    "00140": (14, "ძირითადი საშუალებები, წმინდა", "Property and equipment, net"),
    "00150": (15, "საინვესტიციო ქონება", "Investment property"),
    "00160": (16, "გუდვილი და სხვა არამატერიალური აქტივები, წმინდა", "Goodwill and other intangible assets, net"),
    "00170": (17, "გადავადებული საგადასახადო აქტივი", "Deferred tax asset"),
    "00180": (18, "სხვა აქტივები", "Other assets"),
    "00190": (19, "სულ აქტივები", "Total assets"),
    "00200": (20, "სადაზღვევო რეზერვები, ბრუტო", "Insurance reserves, gross"),
    "00210": (21, "სხვა სადაზღვევო ვალდებულებები", "Other insurance liabilities"),
    "00220": (22, "ვალდებულებები რეგრესიდან და გადარჩენილი ქონებიდან", "Liabilities from regress and salvage"),
    "00230": (23, "ფინანსური ვალდებულებები", "Financial liabilities"),
    "00240": (24, "საპენსიო ვალდებულებები", "Pension liabilities"),
    "00250": (25, "ვალდებულებები მეკავშირე კომპანიებთან", "Liabilities to associates"),
    "00260": (26, "ვალდებულებები შვილობილ კომპანიებთან", "Liabilities to subsidiaries"),
    "00270": (27, "გადავადებული საკომისიო შემოსავალი", "Deferred commission income"),
    "00280": (28, "გადავადებული საგადასახადო ვალდებულება", "Deferred tax liability"),
    "00290": (29, "სხვა ვალდებულებები", "Other liabilities"),
    "00300": (30, "სულ ვალდებულებები", "Total liabilities"),
    "00310": (31, "სააქციო კაპიტალი/კაპიტალი შპს-ში", "Share capital"),
    "00320": (32, "საემისიო კაპიტალი", "Share premium"),
    "00330": (33, "გამოსყიდული აქციები", "Treasury shares"),
    "00340": (34, "აკუმულირებული მოგება/(ზარალი)", "Retained earnings / (accumulated loss)"),
    "00350": (35, "პერიოდის წმინდა მოგება/(ზარალი)", "Net profit / (loss) for the period"),
    "00360": (36, "სხვა რეზერვები", "Other reserves"),
    "00370": (37, "სულ კაპიტალი", "Total equity"),
    "00380": (38, "სულ ვალდებულებები და კაპიტალი", "Total liabilities and equity"),
}

# --- Income statement: code -> (line_no, georgian, english) ----------------
IS_CODES: dict[str, tuple[int, str, str]] = {
    # I. Non-life insurance
    "00010": (1, "მოზიდული პრემია, ბრუტო", "Gross written premium"),
    "00020": (2, "გადაზღვევის პრემია", "Reinsurance premium (ceded)"),
    "00030": (3, "ცვლილება გამოუმუშავებელი პრემიის რეზერვში, ბრუტო", "Change in unearned premium reserve, gross"),
    "00040": (4, "ცვლილება გამოუმუშავებელი პრემიის რეზერვში, გადამზღვევლის წილი", "Change in UPR, reinsurers' share"),
    "00050": (5, "გამომუშავებული პრემია (ნეტო)/სადაზღვევო შემოსავალი", "Net earned premium / insurance revenue"),
    "00060": (6, "ანაზღაურებული ზარალები", "Claims paid"),
    "00070": (7, "გადამზღვევლის წილი ანაზღაურებულ ზარალებში", "Reinsurers' share of claims paid"),
    "00080": (8, "ცვლილება ზარალების რეზერვში, ბრუტო", "Change in loss reserve, gross"),
    "00090": (9, "ცვლილება ზარალების რეზერვში, გადამზღვევლის წილი", "Change in loss reserve, reinsurers' share"),
    "00100": (10, "შემოსავალი რეგრესიდან და გადარჩენილი ქონებიდან, ნეტო", "Income from regress and salvage, net"),
    "00110": (11, "სადაზღვევო/დამდგარი ზარალები, ნეტო", "Net incurred claims"),
    "00120": (12, "დარიცხული ბონუსები", "Accrued bonuses"),
    "00130": (13, "საკომისიო შემოსავალი (ხარჯი), წმინდა", "Net commission income (expense)"),
    "00140": (14, "სადაზღვევო მოგება (ზარალი), წმინდა", "Net underwriting result (non-life)"),
    # II. Life insurance
    "00150": (15, "მოზიდული პრემია, ბრუტო", "Gross written premium (life)"),
    "00160": (16, "გადაზღვევის პრემია", "Reinsurance premium (life)"),
    "00170": (17, "ცვლილება გამოუმუშავებელი პრემიის რეზერვში, ბრუტო", "Change in UPR, gross (life)"),
    "00180": (18, "ცვლილება გამოუმუშავებელი პრემიის რეზერვში, გადამზღვევლის წილი", "Change in UPR, reinsurers' share (life)"),
    "00190": (19, "გამომუშავებული პრემია (ნეტო)/სადაზღვევო შემოსავალი", "Net earned premium / insurance revenue (life)"),
    "00200": (20, "ანაზღაურებული ზარალები", "Claims paid (life)"),
    "00210": (21, "გადამზღვევლის წილი ანაზღაურებულ ზარალებში", "Reinsurers' share of claims paid (life)"),
    "00220": (22, "ცვლილება ზარალების რეზერვში, ბრუტო", "Change in loss reserve, gross (life)"),
    "00230": (23, "ცვლილება ზარალების რეზერვში, გადამზღვევლის წილი", "Change in loss reserve, reinsurers' share (life)"),
    "00240": (24, "შემოსავალი რეგრესიდან (სიცოცხლის)", "Income from regress (life)"),
    "00250": (25, "სადაზღვევო/დამდგარი ზარალები, ნეტო", "Net incurred claims (life)"),
    "00260": (26, "ცვლილება სიცოცხლის დაზღვევის რეზერვში, ბრუტო", "Change in life insurance reserve, gross"),
    "00270": (27, "ცვლილება სიცოცხლის დაზღვევის რეზერვში, გადამზღვევლის წილი", "Change in life reserve, reinsurers' share"),
    "00280": (28, "ცვლილება სიცოცხლის რეზერვში, ნეტო", "Change in life reserve, net"),
    "00290": (29, "დარიცხული ბონუსები (სიცოცხლის)", "Accrued bonuses (life)"),
    "00300": (30, "საკომისიო შემოსავალი (ხარჯი), წმინდა", "Net commission income (expense) (life)"),
    "00310": (31, "სადაზღვევო მოგება (ზარალი), წმინდა", "Net underwriting result (life)"),
    "00320": (32, "სადაზღვევო მოგება (ზარალი), წმინდა", "Net underwriting result (total)"),
    # III. Pension activity
    "00330": (33, "საპენსიო შემოსავალი", "Pension income"),
    "00340": (34, "საპენსიო ხარჯები", "Pension expenses"),
    "00350": (35, "საპენსიო სქემის საინვესტიციო საქმიანობიდან წარმოშობილი ზარალი", "Loss from pension scheme investment activity"),
    "00360": (36, "შედეგი საპენსიო საქმიანობიდან, წმინდა", "Net result from pension activity"),
    # IV. Investment income
    "00370": (37, "საკრედიტო დაწესებულებებში განთავსებული დეპოზიტები", "Income from deposits at credit institutions"),
    "00380": (38, "ფინანსური აქტივები: - გასაყიდად არსებული", "Income from available-for-sale financial assets"),
    "00390": (39, "ფინანსური აქტივები: - დაფარვის ვადამდე მფლობელობაში არსებული", "Income from held-to-maturity financial assets"),
    "00400": (40, "ფინანსური აქტივები: - რეალური ღირებულებით ასახული მოგებაში ან ზარალში ასახვით", "Income from financial assets at FVTPL"),
    "00410": (41, "ინვესტიციები მეკავშირე კომპანიებში", "Income from investments in associates"),
    "00420": (42, "ინვესტიციები შვილობილ კომპანიებში", "Income from investments in subsidiaries"),
    "00430": (43, "საინვესტიციო ქონება", "Income from investment property"),
    "00440": (44, "გაცემული სესხები", "Income from loans issued"),
    "00450": (45, "სხვა ინვესტიციები", "Income from other investments"),
    "00460": (46, "შემოსავალი ინვესტიციებიდან", "Total investment income"),
    # V. Other expenses and income
    "00470": (47, "ხელფასის ხარჯი და სხვა გაცემები", "Salary expense and other payments"),
    "00480": (48, "ადმინისტრაციული ხარჯები", "Administrative expenses"),
    "00490": (49, "გადასახადები", "Taxes (other than income tax)"),
    "00500": (50, "ცვეთის, ამორტიზაციის და გაუფასურების ხარჯი", "Depreciation, amortization and impairment"),
    "00510": (51, "ფინანსური ხარჯი", "Finance cost"),
    "00520": (52, "ნეგატიური გუდვილი", "Negative goodwill"),
    "00530": (53, "სხვა შემოსავალი (ხარჯი), წმინდა", "Other income (expense), net"),
    "00540": (54, "მოგება (ზარალი) დაბეგვრამდე", "Profit (loss) before tax"),
    "00550": (55, "მოგების გადასახადი", "Income tax"),
    "00560": (56, "პერიოდის წმინდა მოგება (ზარალი)", "Net profit (loss) for the period"),
}

# Subtotal / derived lines (computed in the form via the parenthetical formula) —
# they are NOT independent components and must be excluded when summing detail.
BS_TOTAL_CODES = frozenset({"00190", "00300", "00370", "00380"})
IS_SUBTOTAL_CODES = frozenset({
    "00050", "00110", "00140", "00190", "00250", "00280", "00310", "00320",
    "00360", "00460", "00540", "00560",
})

# IS display layout: (section title, [component codes], subtotal code | None).
IS_SECTIONS: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    ("Non-life insurance",
     ("00010", "00020", "00030", "00040"), "00050"),
    ("Net incurred claims (non-life)",
     ("00060", "00070", "00080", "00090", "00100"), "00110"),
    ("— commission & bonuses (non-life)",
     ("00120", "00130"), "00140"),
    ("Life insurance",
     ("00150", "00160", "00170", "00180"), "00190"),
    ("Net incurred claims (life)",
     ("00200", "00210", "00220", "00230", "00240"), "00250"),
    ("Life reserve / commission",
     ("00260", "00270", "00280", "00290", "00300"), "00310"),
    ("Pension activity",
     ("00330", "00340", "00350"), "00360"),
    ("Investment income",
     ("00370", "00380", "00390", "00400", "00410", "00420", "00430", "00440", "00450"), "00460"),
    ("Other income & expenses",
     ("00470", "00480", "00490", "00500", "00510", "00520", "00530"), None),
)

# --- Metric anchor codes (for metrics_panel + ratios) ----------------------
IS_NET_PROFIT = "00560"
IS_PBT = "00540"
IS_INCOME_TAX = "00550"
IS_NET_EARNED_PREMIUM = ("00050", "00190")     # non-life + life → "Revenue"
IS_GROSS_WRITTEN_PREMIUM = ("00010", "00150")  # non-life + life (available, not used as Revenue)
IS_UW_RESULT_TOTAL = "00320"
IS_INVESTMENT_INCOME = "00460"
IS_NET_CLAIMS = ("00110", "00250")             # non-life + life net incurred claims

BS_TOTAL_ASSETS = "00190"
BS_TOTAL_LIABILITIES = "00300"
BS_TOTAL_EQUITY = "00370"
BS_CASH = "00010"
BS_FINANCIAL_LIABILITIES = "00230"  # closest line to interest-bearing debt
BS_NET_PROFIT_PERIOD = "00350"      # equity-side net profit (ties to IS 00560)


# --- Name normalization + curated crosswalk --------------------------------
_DROP_TOKENS = (
    "სს", "ს.ს", "შპს", "სსიპ",
    "სადაზღვევო", "კომპანია", "დაზღვევის", "დაზღვევა",
    "რისკების", "მართვისა", "და",
)


def normalize_site_name(name: str) -> str:
    """Reduce an insurer name to a comparable brand core (drops legal-form and
    generic insurance words, punctuation and spaces; lowercases Latin chars)."""
    s = (name or "").lower().strip()
    s = s.replace(" s.s", " ").replace("ჯეო", "geo")
    # split on whitespace, drop generic tokens
    toks = [t for t in re.split(r"\s+", s) if t and t not in _DROP_TOKENS]
    s = "".join(toks)
    # keep Georgian + latin letters + digits only
    return re.sub(r"[^0-9a-zა-ჿ]", "", s)


# Curated site-name → IdCode for companies the normalized auto-match can't resolve.
# Finalized from `python scripts/download_insurance_gov.py --list-only`.
#   * "ევროინსი" on the site == our DB "ევროინს ჯორჯია" (Euroins Georgia).
#   * "ვაიზერი" (Wizer) IS our DB entity 204545572 — JSC PSP Insurance was rebranded
#     to Wizer on 15 Oct 2025 (same legal entity / IdCode; PSP Group). So the site's
#     "ვაიზერი" return belongs to the company we still carry as PSP's IdCode.
SITE_NAME_TO_IDCODE: dict[str, str] = {
    "სს სადაზღვევო კომპანია ევროინსი": "204491344",
    "სს სადაზღვევო კომპანია ვაიზერი": "204545572",  # Wizer == formerly PSP Insurance
}
