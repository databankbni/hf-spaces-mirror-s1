# Phase 2 Structured Sources Deployment

## Required Space secret

Set in Hugging Face Space Settings -> Variables and secrets:

- `FOOTBALL_DATA_API_TOKEN` = your football-data.org token

Do not paste the token into chat or reports.

## Optional Space secret

- `THE_ODDS_API_KEY` for Phase 2B.

## Required variables

Keep existing Phase 1.1 variables:

- `HF_DATASET_REPO`
- `VENDOR_DIR`
- `DEFAULT_COMPANY_IDS`
- `MAX_PACKET_KB`
- `PYTHON_BIN`
- `HF_FREE_MODE`

## Smoke test

1. Upload this package to the existing Docker Space.
2. Wait until RUNNING.
3. Call `/health` and confirm packet_version is `football_multi_source_phase2_structured_sources_v1`.
4. Run `/refresh-match` for a not-started match with identity_hint from hot_match_pool.
5. Verify packet has:
   - `fixtures_standings_compact`
   - `weather_compact`
   - `source_match_map`
   - `source_conflict_audit`
   - `data_completeness_score`
   - `prediction_quality_guard`
6. Confirm final_pick/stake/bankroll are absent.
