"""NotebookLM export — a single, always-current markdown digest of the verified
corpus, served at a public URL so NotebookLM (or any tool) can ingest it as a
source.

GET /api/export/notebooklm.md  →  text/markdown

It combines:
  - stable, sourced fact-checks (TASMAC, Power/EB, Investments),
  - live credit-steals (govt) + propaganda misattributions,
  - recently documented, VERIFIED TVK-era incidents.

Public + read-only (same data the dashboard already shows). Snapshot at fetch
time — re-import / refresh the source in NotebookLM to update.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter
from fastapi.responses import Response
from app.database import get_db
from app.config import settings

router = APIRouter(prefix="/export", tags=["export"])

SITE = "https://tvkfiles.vercel.app"
# Public backend URL that serves the always-current verified corpus markdown.
# This is the single source the user attaches in NotebookLM each day.
_CORPUS_URL = "https://goknaga-tvk-tracker-backend.hf.space/api/export/notebooklm.md"

# Rotating "angle of the day" — one stable theme per weekday so the daily
# prompt stays varied without RNG. Each entry: (slug, headline, the NotebookLM
# instruction to paste, a copy-ready social caption seed). The corpus source is
# always /api/export/notebooklm.md, so the prompt only has to steer the angle.
DAILY_TOPICS = [
    ("tasmac", "Does TN really 'run on' TASMAC money?",
     "Using only the attached sourced fact pack, make a 60-second explainer script "
     "(English + simple Tamil) on why 'TN runs on TASMAC' is misleading. Lead with the "
     "₹48,344 cr sales-vs-income distinction, then the ~25% / ~11% / ~1.5% figures, then "
     "the prohibition-states-still-have-hooch point. Stay even-handed; cite the named institutions only.",
     "TASMAC ₹48,344 cr is SALES, not govt income. The treasury keeps ~25% of own-tax "
     "revenue from liquor — big, but not the engine. Prohibition didn't end hooch deaths. #TamilNadu #TVKFiles"),
    ("power", "Who actually decides your EB hike?",
     "Using only the attached sourced fact pack,draft a myth-vs-fact card on TN power tariffs: the "
     "2014–2022 freeze, the Sep-2022 TNERC order, and why 2023–2026 hikes are automatic "
     "CPI-linked regulator decisions — including the July-2026 hike firing under a DMK-era "
     "order while TVK governs. Keep it factual, cite the named institutions.",
     "Your EB hike isn't a yearly govt 'decision' — it's an automatic CPI-linked TNERC "
     "formula set in 2022. The July-2026 hike runs on that same order, now under TVK. #PowerTariff #TVKFiles"),
    ("creditsteal", "New ribbon, old project?",
     "Using only the attached sourced fact pack,list the top credit-steal cases where TVK is claiming "
     "DMK-era work, each with the original-credit precedent and the date. Present it as a "
     "neutral 'who started it' ledger. Do not invent any item not in the fact pack.",
     "A ribbon-cutting isn't a groundbreaking. Tracking which 'new' TVK launches were "
     "DMK-era projects — sourced, dated, side by side. #CreditWhereDue #TVKFiles"),
    ("whitepaper", "The white paper's numbers vs its spin",
     "Using only the attached sourced fact pack,build a 5-slide outline on the TVK fiscal white paper: "
     "concede what's factually correct, then debunk the misleading interpretation (the "
     "%-of-GSDP trick, the AIADMK→DMK comparison, the central-borrowing context). Be fair: "
     "say plainly where the data is right.",
     "The white paper's DATA is mostly right. Its INTERPRETATION isn't. A debt number "
     "shrinks as a % when the economy grows — that's not 'control,' it's arithmetic. #FactCheck #TVKFiles"),
    ("investments", "MoU signed ≠ factory built",
     "Using only the attached sourced fact pack,write a short explainer on the gap between signed "
     "investment MoUs (~₹2.98 lakh cr) and what's actually OPERATIONAL on the ground "
     "(~₹27,000 cr / ~9%). Flag the at-risk Mazagon Dock case. Cite the named institutions only.",
     "₹2.98 lakh cr in MoUs sounds huge — but only ~9% is operational on the ground so far. "
     "Signed ≠ built. We track which ones actually land. #TNInvestments #TVKFiles"),
    ("tasmac", "Liquor money, in proportion",
     "Using only the attached sourced fact pack,produce a single 'at-a-glance' explainer that zooms out: "
     "liquor is ~1.5% of TN's economy and ~11% of the budget. Compare with states that lean "
     "MORE on liquor. Keep the framing honest and sourced.",
     "Zoom out: liquor is ~1.5% of TN's whole economy. UP, Karnataka and Uttarakhand lean on "
     "it MORE. 'TN runs on TASMAC' doesn't survive the proportion test. #TVKFiles"),
    ("creditsteal", "This week's misattributions",
     "Using only the attached sourced fact pack,summarise the propaganda misattributions — fan/page "
     "cards crediting Vijay for actions that were someone else's or never happened — with the "
     "debunk source for each. Neutral tone; named institutions only.",
     "Viral card ≠ verified fact. This week's debunked misattributions, each with the receipt. "
     "Share the correction, not the rumour. #DebunkDaily #TVKFiles"),
]

# Stable, sourced fact-checks (mirror the dashboard tabs / outreach packs).
STABLE = f"""## Key fact-checks (verified, stable)

### Does Tamil Nadu "run on" TASMAC / liquor money? — MISLEADING
- ₹48,344 cr (FY25) is TASMAC's SALES turnover, NOT government income.
- The treasury's real take (VAT + excise) ≈ ₹46,000 cr = ~25% of own-tax revenue,
  ~11% of the total state budget, ~1.5% of the economy (GSDP). Big, but not the engine.
- TN is mid-pack: UP, Karnataka, Uttarakhand lean on liquor MORE. Prohibition states
  (Bihar, Gujarat) earn ~₹0 and still see hooch deaths.
- The ₹10/bottle is a court-driven REFUNDABLE deposit (buyback), not a simple overcharge.
- Authoritative sources: TN Finance Dept (Budget 2024-25 & Policy Notes), CAG State Finances Audit Report, RBI "State Finances: A Study of Budgets", PRS Legislative Research, The Federal, Times of India.

### EB bills under DMK: who decides the annual hike? — "DMK alone" is OVERSTATED
- First tariff hike in 8 years came Sep 2022 (TNERC Order 7/2022; ₹3 → ₹4.50/unit),
  ending a 2014–2022 freeze (most of it under AIADMK).
- 2023/24/25 hikes (2.18%, 4.83%, 3.16%) are AUTOMATIC, CPI-linked, set by the
  independent regulator TNERC — not a yearly DMK choice. The same mechanism now runs
  under TVK (July-2026 hike fires under the DMK-era order).
- 100 free units + free power for huts retained; domestic/MSME/agri shielded by subsidy.
- Authoritative sources: TNERC Tariff Order 7/2022 & subsequent CPI-linked true-up orders, Mercom India, DT Next, The South First.

### Tamil Nadu investment scorecard — MoU ≠ money delivered
- Flagship MoUs total ~₹2.98 lakh cr (a subset of GIM 2024's ₹6.64 lakh cr / 631 MoUs).
- Only ~₹27,000 cr (~9%) is OPERATIONAL on the ground; most is signed MoUs not yet built.
- Every commitment is source-linked; Mazagon Dock (₹15,000 cr) is at-risk (Andhra drift).
- Authoritative sources: Guidance Tamil Nadu GIM 2024 official MoU list, company regulatory filings / press releases, PRS Legislative Research.
"""


def _src(urls) -> str:
    """First two http(s) links as markdown citations."""
    links = [u for u in (urls or []) if isinstance(u, str) and u.startswith("http")][:2]
    if not links:
        return ""
    return " — " + " ".join(f"[source{'' if i == 0 else ' '+str(i+1)}]({u})"
                            for i, u in enumerate(links))


@router.get("/notebooklm.md")
async def notebooklm_export():
    db = get_db()
    floor = settings.govt_start_date.isoformat()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out: list[str] = []

    out.append(
        f"# Tamil Nadu Governance & Public Finance — Sourced Fact Pack\n\n"
        f"_Compiled {now}. A neutral, citation-first digest for NotebookLM. Every claim is "
        f"attributed to a primary or authoritative source. Re-import to refresh._\n\n"
        f"**Grounding & citation rules (read carefully):**\n"
        f"1. Attribute every fact ONLY to the named authoritative sources — government and "
        f"regulator data (RBI, CAG, TNERC, NITI Aayog, TN Finance Department, GIM 2024), "
        f"official guidelines (e.g. RBI Model Operational Guidelines), and the named credible "
        f"news outlets (The Federal, Times of India, Mercom, DT Next, The South First, "
        f"Deccan Herald, Business Today, NewsMeter).\n"
        f"2. Do NOT cite or name 'TVK Files', any dashboard, blog, or this document itself as "
        f"a source — they are only the compiler. Cite the underlying institutions instead.\n"
        f"3. Keep the even-handed framing (state the counter-arguments too). Do not add any "
        f"figure or claim that is not present here."
    )
    out.append(
        "## Authoritative sources behind this pack\n"
        "- **RBI** — \"State Finances: A Study of Budgets\" (annual); RBI Model Operational "
        "Guidelines for crop-loan waivers (28 Nov 2025).\n"
        "- **CAG** — State Finances Audit Reports for Tamil Nadu.\n"
        "- **TNERC** (TN Electricity Regulatory Commission) — Tariff Order 7/2022 and the "
        "subsequent CPI-linked true-up orders.\n"
        "- **NITI Aayog** — Fiscal Health Index 2025; Export Preparedness Index 2024.\n"
        "- **TN Finance Department** — Budget 2024-25, Policy Notes, and the White Paper on "
        "State Finances (16 Jun 2026).\n"
        "- **PRS Legislative Research** — Tamil Nadu State Budget Analysis.\n"
        "- **Guidance Tamil Nadu** — Global Investors Meet (GIM) 2024 official MoU list.\n"
        "- **Credible news / fact-checkers** — The Federal, Times of India, Mercom India, "
        "DT Next, The South First, Deccan Herald, Business Today, NewsMeter."
    )
    out.append(STABLE)

    # --- Credit-steals (government claiming DMK-era credit) ---
    try:
        cs = (db.table("incidents")
              .select("title,summary,original_credit,source_urls,incident_date")
              .eq("is_credit_steal", True).eq("status", "approved")
              .order("incident_date", desc=True).limit(30).execute().data or [])
    except Exception:
        cs = []
    if cs:
        out.append("## Credit-steals — TVK claiming credit for DMK-era work")
        for r in cs:
            line = f"- **{r['title']}**"
            if r.get("original_credit"):
                line += f" — DMK precedent: {r['original_credit']}"
            line += _src(r.get("source_urls"))
            out.append(line)

    # --- Propaganda misattributions (debunked cards) ---
    try:
        pr = (db.table("propaganda_events")
              .select("title,description,debunk_source,source_urls,status,tags,propaganda_type")
              .order("first_seen", desc=True).limit(60).execute().data or [])
    except Exception:
        pr = []
    pr = [p for p in pr if (p.get("tags") and "credit_steal" in p["tags"])
          or p.get("propaganda_type") == "misattributed_event"]
    if pr:
        out.append("\n## Propaganda misattributions — fan/page cards crediting Vijay for others' actions")
        for p in pr:
            tag = "DEBUNKED" if p.get("status") == "debunked" else "under review"
            line = f"- **[{tag}] {p['title']}** — {(p.get('description') or '')[:400]}"
            if p.get("debunk_source"):
                line += f" (debunked by {p['debunk_source']})"
            line += _src(p.get("source_urls"))
            out.append(line)

    # --- Recent verified TVK-era incidents ---
    try:
        inc = (db.table("incidents")
               .select("title,summary,category,incident_date,location,source_urls,verification_status")
               .gte("incident_date", floor).eq("status", "approved")
               .in_("verification_status", ["multi_source_verified", "press_verified", "admin_verified"])
               .order("incident_date", desc=True).limit(50).execute().data or [])
    except Exception:
        inc = []
    if inc:
        out.append(f"\n## Recently documented incidents (TVK era, verified — since {floor})")
        for r in inc:
            loc = f" ({r['location']})" if r.get("location") else ""
            line = (f"- **{r['title']}**{loc} — {(r.get('summary') or '')[:300]}"
                    f" [{(r.get('incident_date') or '')[:10]}]{_src(r.get('source_urls'))}")
            out.append(line)

    out.append(
        "\n---\n_Compiled for analysis from the institutions listed above. When citing, "
        "name those underlying sources — not this compilation. Data current as of fetch time._"
    )
    md = "\n".join(out)
    return Response(content=md, media_type="text/markdown; charset=utf-8")


@router.get("/daily-prompt.md")
async def daily_prompt():
    """A copy-ready 'prompt of the day' for NotebookLM + the day's NEW verified
    items + a ready-to-post caption. Free, deterministic, no AI call — safe to
    fetch every morning (cron/Telegram) without burning the Groq/Gemini pool.

    The angle rotates by day-of-year over DAILY_TOPICS; the corpus source is
    always /api/export/notebooklm.md so the user only pastes the prompt.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    today = now.date()
    topic = DAILY_TOPICS[today.toordinal() % len(DAILY_TOPICS)]
    slug, headline, prompt, caption = topic
    since = (today - timedelta(days=1)).isoformat()

    out: list[str] = []
    out.append(
        f"# Today's NotebookLM prompt — {today.isoformat()}\n\n"
        f"**Angle of the day:** {headline}\n\n"
        f"_Source to attach: {SITE.replace('tvkfiles.vercel.app', '')}"
        f"{SITE and ''}`{ _CORPUS_URL }` (the always-current sourced fact pack)._"
    )

    out.append("## 1. Paste this into NotebookLM\n\n```\n" + prompt + "\n```")

    out.append("## 2. Ready-to-post caption\n\n```\n" + caption + f"\n\n{SITE}/{slug}\n```")

    # --- What's NEW since yesterday (so the prompt is grounded in fresh facts) ---
    fresh: list[str] = []
    try:
        ni = (db.table("incidents")
              .select("title,category,incident_date,location,source_urls,created_at")
              .gte("created_at", since).eq("status", "approved")
              .in_("verification_status",
                   ["multi_source_verified", "press_verified", "admin_verified"])
              .order("created_at", desc=True).limit(20).execute().data or [])
    except Exception:
        ni = []
    for r in ni:
        loc = f" ({r['location']})" if r.get("location") else ""
        fresh.append(f"- **{r['title']}**{loc} [{(r.get('incident_date') or '')[:10]}]"
                     f"{_src(r.get('source_urls'))}")

    try:
        ncs = (db.table("incidents")
               .select("title,original_credit,source_urls,created_at")
               .eq("is_credit_steal", True).eq("status", "approved")
               .gte("created_at", since)
               .order("created_at", desc=True).limit(10).execute().data or [])
    except Exception:
        ncs = []
    for r in ncs:
        line = f"- **[credit-steal] {r['title']}**"
        if r.get("original_credit"):
            line += f" — DMK precedent: {r['original_credit']}"
        fresh.append(line + _src(r.get("source_urls")))

    out.append("## 3. New verified items since yesterday")
    if fresh:
        out.append("_Mention these in your post if they fit today's angle:_\n")
        out.extend(fresh)
    else:
        out.append("_No new verified items in the last 24h — today's angle stands on the "
                   "stable fact pack above. (This is normal; quality over volume.)_")

    out.append(
        "\n## 4. After NotebookLM generates\n"
        "- For **number-exact infographics** (₹ figures, %, Tamil text): use Share Studio "
        f"({SITE}/studio) or Canva — NotebookLM mangles precise digits/Tamil glyphs.\n"
        "- For **audio / video overview**: NotebookLM is great — generate, then share.\n"
        f"- Full fact pack any time: `{_CORPUS_URL}`"
    )

    md = "\n".join(out)
    return Response(content=md, media_type="text/markdown; charset=utf-8")
