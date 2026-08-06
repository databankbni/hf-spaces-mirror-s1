# Generic City of Calgary SWMR workflow

Kincora Phase 2 is a regression fixture only. Production functions do not
contain Kincora object IDs, values, geometry, or report conclusions.

## MCP sequence

1. `upload_model` — immutable EPA SWMM INP upload and inventory.
2. `set_report_details` — project, consultant, professional, site, objective,
   methodology and administrative information.
3. `set_report_configuration` — project-specific criteria, major routes,
   special flow limits, facility classifications, drawing inventory,
   applicable reports and checklist overrides.
4. `run_simulation` — legacy-default normalization where required, isolated
   execution, execution-integrity gate, database creation and RPT reconciliation.
5. `get_table_catalog` / `query_results` — complete tokenized input and result
   review rather than top-N-only evidence.
6. `preliminary_design_review`, `get_reconciliation`, `calgary_screening` —
   deterministic QA/QC and preliminary City screening.
7. `get_timeseries` and controlled `run_scenario` calls where authorized.
8. `generate_report` — editable SWMR DOCX plus immutable audit ZIP, model
   listings, model schematic, depth-velocity figure and readiness registers.

## Execution and readiness gates

- An invalid hydraulic run produces an Input/Configuration Review and no
  hydraulic screening conclusions.
- Missing drawings, approved criteria, boundary conditions, current-source
  verification, or professional fields remain explicit readiness gaps.
- Generated figures do not replace drawing-to-model reconciliation.
- The output is never represented as approved, authenticated, or submission
  ready solely because the automated workflow completed.

## Project-neutral design

- Object selection is derived from each uploaded INP or explicit project
  configuration.
- Unit labels and effective solver defaults follow the model unit system.
- Coordinates and vertices drive schematic geometry; incomplete coordinate
  sets receive a deterministic topology fallback.
- Criteria and facility classifications are session-scoped and archived with
  the report package.
- Kincora-specific numerical pins remain only in regression tests.
