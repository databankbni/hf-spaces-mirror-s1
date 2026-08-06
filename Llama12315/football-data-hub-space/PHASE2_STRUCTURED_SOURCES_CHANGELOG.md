# Phase 2 Structured Sources Changelog

## Added

- football-data.org adapter for structured fixture/standings compact data.
- Open-Meteo adapter for kickoff weather compact data.
- Optional The Odds API adapter stub for Phase 2B.
- Source match map.
- Phase 2 source conflict detector.
- Data completeness score.
- Prediction quality guard.
- Phase 2 source policy config.
- Tests for source map, completeness, and conflict summary.

## Preserved

- Titan007 remains primary AH/OU odds source.
- Match Identity Lock remains mandatory.
- HF remains data layer only.
- Hermes local owns final_pick / stake / bankroll / retention.
- Raw payloads are saved or summarized but not returned in packet context.
