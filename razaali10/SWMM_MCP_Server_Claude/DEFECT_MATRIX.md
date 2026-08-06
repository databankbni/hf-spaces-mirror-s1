# Defect Matrix — deterministic report-quality fixes (Rev 23.3)

Response to the external review of MCP-generated SWMM Model Review reports.
Reference model: Kincora Phase 2 (regression pins live in `test_regression.py`
with documented tolerances; no Kincora values are hard-coded in server code).

| # | Defect (as observed) | Authoritative source | Root cause | Module / function | Fix | Regression test |
|---|---|---|---|---|---|---|
| 1 | Runoff continuity −1.933% never disclosed as exceeding the 1% absolute warning threshold | Engine `.rpt` continuity block | `_summary_findings` applied thresholds to `flow_error` only | `report_engine._summary_findings` | Replaced with `screening_logic.continuity_disclosure`: runoff and routing checked symmetrically against absolute review/warning thresholds, sign preserved (`-1.933%` printed signed; threshold on \|value\|) | unit: sign + threshold tests; docx: warning line present |
| 2 | Water-quality continuity reported as a number when no pollutants modelled | INP `[POLLUTANTS]` absent | No applicability gate | same | "Not applicable — no pollutants modelled" when `[POLLUTANTS]` empty; reported numerically only when pollutants exist | unit + docx checks |
| 3 | Storage facilities labelled **Pass** without facility classification, design HWL, freeboard, or release/spill criteria | None exists (criteria not established) | Permissive default-Pass in `apply_storage_classification` non-trap branch | `calgary_rules.apply_storage_classification` | Three-state screening: "Within modelled depth — compliance **Not assessed** (criteria not established)" / "Near modelled capacity — review" / "Exceeds modelled depth — flag". Trap-lows retain a screening verdict because the 0.5 m Alberta Environment criterion is an established register entry | unit: no bare Pass; docx: storage table scan |
| 4 | "Remaining Depth Margin" conflatable with regulatory freeboard | — | Terminology | `calgary_rules`, `report_engine` storage table | Renamed **"Modelled Depth Margin"** in both tables; explicitly a model quantity, not a freeboard determination | unit: column name; docx: terminology |
| 5 | Screening ignored the `.rpt` value for reconciliation-flagged links (e.g. 108(Spill): worker 1.186 vs `.rpt` 2.63 m/s) | Engine `.rpt` Link Flow Summary | Reconciliation produced findings but never fed screening | new `screening_logic.effective_velocity_table` + `report_engine._critical_elements` | Evidence precedence implemented: flagged links screen on the `.rpt` value; both values, Δabs, Δ%, evidence source, and "classification changed Yes/No" recorded; report states deterministically that the 108(Spill) discrepancy does **not** create a 3.0 m/s exceedance; verdict never claims reconciliation fully clean while links remain flagged | unit: precedence + delta tests; integration: 108(Spill); docx: precedence statements |
| 6 | Single 4.0 m/s velocity threshold; no advisory tier in the report | Criteria register (3.0 advisory / 4.0 critical) | Report used one threshold although the register held two | `report_engine` (`ReportCriteria.velocity_advisory`, `_critical_elements`) | Dual classification: "CRITICAL screening exceedance (>4.0)" for 1000/1001; "Advisory screening exceedance (>3.0)" for 1003/1002/1005; explicitly screening language, not regulatory failure | integration velocity pins; docx language check |
| 7 | No missing-evidence disclosure section | — | Data existed (readiness, criteria register) but no register | new `screening_logic.missing_information_register` + §4.10 | Deterministic register from unset metadata + "Not established" criteria + "Missing" checklist rows; text states listed items block any related Pass | docx heading + table |
| 8 | No model identity / provenance (hash, run ID, engine, status) | File bytes + session | Never computed | `tools.run_simulation`, `report_engine` §1.0a | SHA-256 of the uploaded INP + UTC run ID in run output, report Table 0A, and `metadata/model_identity.json` in the audit zip; revision-history Table 0B added | integration SHA check; docx table scan |
| 9 | No prioritized actions; presentation gaps (page numbers) | Findings register | Rendering only | `report_engine` §5.0a + footer | Severity-sorted (Critical→Low) deterministic action list from the findings register; footer with PAGE field on every page | docx heading check |

## Items reviewed and found already correct (no change)

- **Full-flow capacity**: already computed only for CIRCULAR conduits with
  explicit slope via Manning; otherwise basis = "Full-flow capacity not
  calculated" and status "Not assessed" — never inferred from velocity/depth.
- **Complete data coverage**: report tables and appendices are built from the
  complete result DataFrames; the 60-row bounds apply only to MCP tool
  responses (narrative summaries), as the review permits.
- **CB2A/CB2a case QA**, **advisory/critical thresholds in the screening
  tool**, **continuity percent conversion**, **base-model preservation in
  scenarios**, **velocity extraction** — fixed in Rev 23.2 and retained.

## Known remaining limitations (disclosed, not hidden)

1. Per-metric provenance is carried at table level (evidence source columns,
   reconciliation records, audit CSVs), not yet as a universal typed record
   for every scalar in the document.
2. DOCX→PDF rendering checks (blank pages, clipped tables) are approximated
   at the docx-structure level; a LibreOffice render pass is not run in the
   Space image.
3. The Word TOC relies on heading styles (Word can generate it); an embedded
   auto-updating TOC field is not inserted.
4. 108(Spill)-class discrepancies on mostly-dry transect channels are
   flagged and precedence-handled, but their physical cause (volume-averaged
   vs midpoint flow area during wave-front filling) is documented rather
   than eliminated.

## Reproduce

```bash
SWMM_WORKER_PYTHON=$(which python) python test_regression.py Kincora_Phase_2.inp
python smoke_test.py http://127.0.0.1:7860 Kincora_Phase_2.inp   # against a live server
```
