# RICS Hardcoded-Constant Inventory

**Status: RESOLVED** — all three constants relocated/extracted; `test_no_rics_hardcodes`
now passes (suite stepped 3 → 2 → 1 → 0, one constant at a time). The sections
below retain the original pre-refactor analysis and append the post-refactor
source-of-truth location and its guard test.

Scope: the three production modules that previously failed `test_no_rics_hardcodes`
because they hardcoded RICS-domain rating vocabulary.

> The refactor was a **pure relocation / schema-driven extraction**: no constant
> value and no runtime behaviour changed. Byte-for-byte identity (2.2) and exact
> set identity (2.1) are pinned by dedicated guard tests.

---

## 1. The guard test

`backend/tests/test_no_rics_hardcodes.py`

```python
_FORBIDDEN = re.compile(r"Condition Rating|CR[123]|_RICS_LETTER", re.IGNORECASE)
```

Parametrised over every `backend/**/*.py` **except**:

- anything under a `tests/` path
- anything under a `prompts/` path
- `rics_level3_schema.py`
- `__init__.py`

**Architectural intent encoded by the exemptions:** RICS-specific literals are
permitted only in (a) the canonical schema seed (`rics_level3_schema.py`),
(b) prompt templates (`backend/prompts/`), and (c) tests. Everywhere else,
domain vocabulary must be **derived from the discovered `TemplateSchema`**, not
inlined — so the engine stays firm-/template-agnostic.

---

## 2. The three violations

### 2.1 `backend/core/pii_scrubber.py` — `_STATUS_TERMS` (line ~58)

```python
_STATUS_TERMS = frozenset({
    "condition rating", "defect", "satisfactory", "serviceable", "deflection",
    "distortion", "cracking", "spalled", "damp", "moisture", "insulation",
})
```

- **Match that trips the test:** `"condition rating"`.
- **Role:** part of `PROPTECH_SAFE_WHITELIST` (Pass-2 guardrail). Whitelisted
  spans are **never masked** as PII. Removing/renaming the term risks the
  scrubber redacting the legitimate phrase "condition rating" out of reference
  prose — re-introducing exactly the over-redaction class we just fixed.
- **Blast radius:** every REFERENCE-tier ingest (`RagStore.ingest_document` →
  `scrub_reference_for_ingest`) and every `assert_no_pii` gate (DOCX export).
- **Load-bearing:** YES. Touching this changes what survives redaction globally.
- **RESOLVED →** `pii_scrubber._BASE_STATUS_TERMS` (the 10 non-rating terms) plus
  the rating term derived as `DEFAULT_RATING_SYSTEM_NAME.lower()` imported from
  `rics_level3_schema.py`. `_STATUS_TERMS = _BASE_STATUS_TERMS | {rating}` — the
  effective set is unchanged. No literal `"condition rating"` remains in the file.
  Guard: `backend/tests/test_pii_whitelist_source.py` (exact set match +
  canonical-derivation + the phrase still survives a scrub).

### 2.2 `backend/core/reference_mapper.py` — `_RICS_DOMAIN_RULES` (lines ~26–32)

```python
_RICS_DOMAIN_RULES = """
RICS LEVEL 3 DOMAIN RULES (mandatory):
- Condition ratings may only use: "1", "2", "3", "NI", "NA". Never emit an empty rating token.
- If a note or baseline fragment is ambiguous or corrupted, preserve it verbatim inside [AMBIGUOUS: <text>].
- Output pure continuous prose only. No markdown fences, bullet lists, or chat preamble.
- British English throughout.
"""
```

- **Matches that trip the test:** `"Condition ratings"` (line 28) and
  `"condition rating field"` (line ~88, the per-call rating hint).
- **Role:** system-prompt fragment injected into the in-place mapping LLM call.
  The allowed rating tokens (`1/2/3/NI/NA`) are RICS-L3-specific.
- **Blast radius:** the grounding/mapping LLM output contract. Changing the
  allowed-values text changes what the model is told it may emit per section.
- **Load-bearing:** YES (prompt contract). NOTE: this is arguably mis-located —
  prompt text belongs under `backend/prompts/` (which the test exempts), so a
  large part of the fix is simply **relocation**, not redesign.
- **RESOLVED →** both fragments relocated **verbatim** to
  `backend/prompts/mapping_prompt.py` as `RICS_DOMAIN_RULES` (the rules block) and
  `RATING_HINT_TEMPLATE` (the line-88 hint). `reference_mapper._RICS_DOMAIN_RULES`
  is now an alias to the relocated object; the hint is built via
  `RATING_HINT_TEMPLATE.format(rating_value=...)`. Done as **pure relocation only**
  (the `1/2/3/NI/NA` token parameterisation in §3 below was deliberately *not*
  performed — it would break the byte-for-byte requirement; see §3 note). Guard:
  `backend/tests/test_grounding_prompt_relocation.py` pins SHA-256
  `75b4d183…b06c` (len 363) and the hint string.

### 2.3 `backend/pipeline/hybrid_discovery_compiler.py` — REMOVED

Previously held a rating-name fallback via `DEFAULT_RATING_SYSTEM_NAME`. The
hybrid discovery compiler, model, prompt, and tests were removed (L3 uses
canonical schema + classic `discovery_prompt` enrichment only).
`DEFAULT_RATING_SYSTEM_NAME` remains in `rics_level3_schema.py` for PII
whitelist / DOCX rating label use.

---

## 3. Target schema-driven shape

The relevant model already exists — `backend/models/schema.py::RatingSystem`:

```python
class RatingSystem(BaseModel):
    detected: bool = False
    name: str = ""                  # discovered label from the template
    type: str | None = None
    values: list[RatingValue] = []  # discovered legend (e.g. 1/2/3/NI/NA)
    format_template: str | None = None
    inline_example: str | None = None
```

Intended end-state per violation:

| # | Module | Move the literal to | Mechanism |
|---|--------|---------------------|-----------|
| 2.1 | `pii_scrubber._STATUS_TERMS` | schema/canonical-derived whitelist | Build the status-term whitelist from `schema.rating_system.name` + `RatingValue` labels (+ a small canonical seed in `rics_level3_schema.py`). Whitelist becomes data, not an inline literal. |
| 2.2 | `reference_mapper._RICS_DOMAIN_RULES` | `backend/prompts/` (exempt) | Relocate the prompt fragment to a `prompts/` builder; parameterise allowed rating tokens from `schema.rating_system.values` instead of the hardcoded `1/2/3/NI/NA`. |
| 2.3 | ~~`hybrid_discovery_compiler`~~ | — | **Removed** with hybrid discovery. |

Net effect: the only files that mention "Condition Rating" become the two the
test already exempts (`rics_level3_schema.py`, `backend/prompts/*`), so the engine
core is genuinely template-agnostic and the test passes without weakening it.

**Deviation from the original mechanism column (as built):**

- **2.2** was executed as **pure verbatim relocation**. The proposed
  "parameterise allowed rating tokens from `schema.rating_system.values`" was
  deliberately **not** done — it would alter the prompt string and break the
  byte-for-byte / SHA-256 guard. Token parameterisation remains a *separate,
  future* enhancement (it changes behaviour and must be specced/tested on its own).
- **2.1** uses the **canonical seed** (`DEFAULT_RATING_SYSTEM_NAME`) rather than a
  live `schema.rating_system.name` lookup, because `PROPTECH_SAFE_WHITELIST` is a
  module-level constant with no per-request schema in scope. Net set is identical.

---

## 4. Safe refactor ordering (when undertaken separately)

1. **2.3** — hybrid discovery removed; `DEFAULT_RATING_SYSTEM_NAME` retained for PII/DOCX.
2. **2.2 next** (prompt relocation + parameterisation). Verify with a live/mock
   mapping run that allowed rating tokens still match `schema.rating_system.values`;
   confirm `test_minimum_weave` / `test_maximum_compose` / `test_medium_expand`.
3. **2.1 last** (highest risk — PII). Build the whitelist from schema + canonical
   seed; verify reference ingest does **not** redact "condition rating" and that
   `assert_no_pii` still blocks genuine PII. Re-run the full PII suite and the
   reference-ingest E2E (`test_section_photos`, `test_source_attribution_e2e`).

Each step is independently shippable and independently revertible. Do **not**
batch 2.1 with 2.2 — PII and prompt-contract regressions must be bisectable.

### Verification gate for the whole refactor

Status: **PASSING** — full `backend/tests` suite green (0 failures); the three
`test_no_rics_hardcodes` cases now pass, plus the two new relocation guards.

```
python -m pytest backend/tests/test_no_rics_hardcodes.py \
  backend/tests/test_grounding_prompt_relocation.py \
  backend/tests/test_pii_whitelist_source.py \
  backend/tests/test_pii_scrubber.py \
  backend/tests/test_section_photos.py \
  backend/tests/test_source_attribution_e2e.py \
  backend/tests/test_minimum_weave.py backend/tests/test_maximum_compose.py \
  backend/tests/test_medium_expand.py --no-cov
```
