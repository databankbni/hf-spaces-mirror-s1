# Tasks

## Done — Phase 0: deployment feasibility

- [x] Synthetic borehole page generator using synthetic data only
- [x] PDF rasterisation check
- [x] OCR feasibility check
- [x] Embedding model feasibility check
- [x] LLM structured-output feasibility check on ZeroGPU
- [x] Gradio smoke-test UI
- [x] Hugging Face Space created and publicly accessible
- [x] Anonymous inference validated
- [x] Tag `phase-0-validated`
- [x] Phase 0 findings recorded in README / DECISIONS

### Residual Phase 0 observations

- Run-all sequence was not the acceptance path for later phases
- One transient ZeroGPU allocation failure was observed
- Sleep/wake latency was not systematically measured

---

## Phase 1: BGS / SOBI public-data audit

### Done

- [x] Identify BGS SOBI / Onshore Borehole Index as the public source
- [x] Validate current OGC API collection and useful query fields
- [x] Validate public PDF download endpoint
- [x] Record BGS / UKRI attribution and licensing note
- [x] Add reproducible SOBI sampling script
- [x] Build deterministic ~30-document audit sample
- [x] Add SOBI search utility
- [x] Add public scan download utility
- [x] Keep downloaded PDFs Git-ignored
- [x] Inspect initial real scans, including multi-page and difficult cases

### Still useful later

- [ ] Continue manual audit of the selected ~30 scans
- [ ] Record broader layout / OCR / document-quality findings
- [ ] Select 3–5 final public demo documents
- [ ] Do not treat SOBI registry metadata as benchmark truth

---

## Phase 2: extraction contract

Implemented as part of the Phase 4 groundwork.

- [x] Separate `raw_value` from `accepted_value`
- [x] Typed evidence references
- [x] Candidate provenance
- [x] Closed extraction status vocabulary
- [x] Traceability against actual source OCR regions
- [x] Grounding against source OCR text
- [x] Validation state
- [x] Typed candidate list
- [x] JSON round-trip support

---

## Done — Phase 3: normalized OCR layer

Commit: `23c0c42 phase3: add normalized OCR document layer`

- [x] `OCRDocument`
- [x] `OCRPage`
- [x] `OCRRegion`
- [x] Full SHA-256 document identity
- [x] 1-based page and region identifiers
- [x] Original OCR polygons preserved
- [x] Bounding boxes derived from polygons
- [x] Page-level `ok` / `no_text` / `error` states
- [x] Whole-document OCR
- [x] UTF-8 JSON serialisation on Windows
- [x] Real multi-page BGS scan validated
- [x] Real OCR cost measured

---

## Done — Phase 4: grounded Expert / Hybrid extractor

Commit: `ba46179 phase4: add grounded expert extractor`

Target fields:

- borehole reference / ID
- Easting
- Northing
- final depth

Completed:

- [x] Config-driven deterministic extractor
- [x] No private/client-specific constants or models
- [x] Candidate-level provenance
- [x] Distinguish BGS wrapper evidence from historical document-body evidence
- [x] Evidence traceability against actual OCR source regions
- [x] Value grounding
- [x] Numeric / format validation
- [x] Conservative abstention rules
- [x] No silent OCR-ID corrections
- [x] Explicit unit handling without unit conversion
- [x] Real-table geometry for final depth
- [x] Real BGS document `623562` validated:
      borehole ID `129`,
      Easting `335244.0`,
      Northing `858196.0`,
      final depth `15.0`
- [x] Full repository test suite passed before deployment

---

## Done — Phase 5: minimal live deployed product

Commit: `e9b484f phase5: add minimal grounded extraction UI`

Current live flow:

PDF upload
→ normalized OCR
→ Expert / Hybrid extraction
→ accepted/rejected field results
→ textual OCR evidence
→ structured JSON result

Validated:

- [x] Local Gradio UI starts successfully
- [x] Real public BGS PDF processed end-to-end locally
- [x] Hugging Face deployment successful
- [x] Space currently runs on CPU Basic
- [x] Public page accessible without Hugging Face login
- [x] Anonymous public extraction succeeds
- [x] Real `623562` result: 4/4 fields accepted
- [x] Evidence shown for each accepted field
- [x] Structured JSON result exposed
- [x] Public OCR runtime measured at ~33–39 s for the 6-page validation document

### Infrastructure note

The Phase 5 app currently uses CPU OCR + deterministic extraction and therefore
does not expose a real `@spaces.GPU` function. The Space should remain on
CPU Basic for this phase. ZeroGPU can be reintroduced when a real GPU-backed
LLM method is added.

---

## Now — Phase 6: visual evidence

Goal: make grounding visually inspectable, not just textual.

- [ ] Render the relevant PDF page
- [ ] Resolve evidence `region_id` back to OCR bbox / polygon
- [ ] Draw evidence boxes on the page
- [ ] Let the user inspect the evidence supporting each extracted field
- [ ] Preserve current textual evidence
- [ ] Keep the UI small and understandable
- [ ] Validate on the real `623562` document
- [ ] Deploy and verify anonymously

Do not add RAG or benchmark logic in this phase.

---

## Later

### Phase 7 — Context measurement / model selection

- Measure document lengths and context requirements
- Choose the common local/open LLM and embedding model for comparison methods

### Phase 8 — Naive RAG

- OCR text
- fixed chunks
- embedding retrieval
- top-k context
- shared LLM
- same grounded output contract

### Phase 9 — Adaptive structure-aware RAG

- layout-aware candidate regions
- minimal context
- adaptive expansion
- same LLM and output contract

### Phase 10 — Direct LLM decision

- Only include if the complete document fits model context
- Never silently truncate

### Phase 11 — Manual truth set

- Manually verify document values
- Keep `document_truth` separate from SOBI / registry metadata

### Phase 12 — Benchmark

Compare methods using:

- field correctness
- abstention
- grounding / traceability
- context size
- latency
- failure modes

### Phase 13 — Red-team / failure tests

- wrapper/body conflicts
- neighbouring boreholes
- OCR corruption
- missing fields
- unreadable pages
- unusual units
- conflicting candidates

### Phase 14 — packaging and final polish

- README
- limitations
- demo examples
- reviewer-facing explanation
- final recruitment submission link