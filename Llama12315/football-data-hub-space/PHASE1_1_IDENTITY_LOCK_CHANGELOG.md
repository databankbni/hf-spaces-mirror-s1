# Phase 1.1 Identity Lock Changelog

Generated package: `hf_football_data_hub_phase1_1_identity_lock.zip`

## Added

- `hf_football_data_hub/match_identity_resolver.py`
  - Titan007 match_id primary anchor
  - `canonical_match_key = titan007:<match_id>`
  - team alias normalization
  - team type detection: first team / women / U21 / U23 / reserve
  - kickoff-time tolerance checks
  - league consistency checks
  - home/away direction guard
  - cross-source candidate scoring
  - blockers for home-away swapped, league mismatch, time mismatch, team-type mismatch

- `hf_football_data_hub/source_conflict_detector.py`
  - turns identity failures into recommendation-blocking source conflicts

- `config/team_alias_registry.json`
  - example alias schema
  - positive aliases and negative aliases
  - explicit reminder that aliases are recall-only, not final proof

- `tests/test_match_identity_lock.py`
  - primary match_id lock
  - alias/time/league/direction merge pass
  - home-away swapped blocker
  - kickoff mismatch blocker
  - U21/Women/reserve false-positive blocker
  - packet quality blocker when identity is not locked

- `deploy/PHASE1_1_IDENTITY_LOCK_DEPLOYMENT.md`
  - Hermes deployment notes and strict_50 blocking rules

## Changed

- `PACKET_VERSION` changed to `football_multi_source_phase1_1_identity_lock_v1`
- `packet_builder.py` now includes:
  - `match_identity`
  - `hf_decision_boundary`
  - `packet_usage`
  - `identity_lock_requirements`
- `quality.py` now blocks if `match_identity.identity_locked=false` or `identity_score<90`
- `hermes_client/hermes_hf_client.py` now supports private HF Spaces via `Authorization: Bearer $HF_TOKEN`
- `hermes_client/HERMES_INTEGRATION_PATCH.md` now documents identity lock requirements

## Test result

```text
11 passed
```

## Boundary

This package is still data-layer only. It does not generate final_pick, stake, bankroll, retention_proof, post-match review, or case memory.
