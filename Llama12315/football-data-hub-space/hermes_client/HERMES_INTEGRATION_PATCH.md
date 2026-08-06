# Hermes Integration Patch: HF Data Hub Phase 1

Add this before local Titan007 fetch in the football prediction pipeline:

1. Call `hf_data_client.py match-packet --match-id <id>`.
2. If `ok=true` and `packet.recommendation_allowed=true`, use packet fields:
   - `titan007_compact`
   - `multi_company_metrics`
   - `kline_summary`
   - `data_quality_score`
   - `source_conflicts`
3. If packet missing, call `hf_data_client.py refresh --match-id <id>`.
4. If HF refresh fails, fallback to current local Titan007 compact path.
5. Do not read `raw_sources` into context.
6. Keep final_pick, bankroll, retention_proof, MATCH_TRACKER_MASTER local.

Every compact report must include:

```json
{
  "hf_data_hub": {
    "enabled": true,
    "packet_used": true,
    "packet_version": "football_multi_source_phase1_v1",
    "packet_generated_at": "",
    "packet_size_kb": "",
    "recommendation_allowed": true,
    "fallback_used": false,
    "fallback_reason": ""
  }
}
```
