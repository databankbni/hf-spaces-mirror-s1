# Rev 28 change log

## Fixed

- Corrected the deterministic preflight gate for legacy EPA SWMM dynamic-wave
  options explicitly stored as zero.
- `MAX_TRIALS=0`, `HEAD_TOLERANCE=0`, and `MIN_SURFAREA=0` now resolve on an
  immutable derivative execution copy using unit-aware defaults.
- Preserved the original uploaded model and added original/execution filenames,
  SHA-256 hashes, and substitution records to run metadata and report identity.
- Included both original and derivative INP files in the SWMR audit ZIP.
- Retained blocking behavior for negative and non-numeric solver values.
- Added a deterministic Alberta/Calgary depth-velocity criteria figure directly
  below SWMR Table 9, including model depth/velocity points, peak-flow colour,
  the tabulated criterion, and audited PNG/CSV source artifacts.
- Added deterministic SWMM model-schematic automation using INP coordinates,
  vertices, subcatchment routing and hydraulic topology, with a stable fallback
  layout plus archived PNG and generation manifest.
- Exposed the report engine's project-specific City of Calgary configuration
  through `set_report_configuration`, removing the workflow gap that prevented
  non-sample projects from supplying major routes, criteria, classifications,
  drawing inventories, applicable reports and checklist overrides.

## Validation

- Python compilation passed.
- All 35 deterministic unit checks passed.
- Exact Kincora legacy-zero normalization was verified without modifying the
  uploaded INP.
- Full worker integration must be rerun in the Hugging Face Space image, which
  supplies the isolated OpenSWMM worker dependencies.
