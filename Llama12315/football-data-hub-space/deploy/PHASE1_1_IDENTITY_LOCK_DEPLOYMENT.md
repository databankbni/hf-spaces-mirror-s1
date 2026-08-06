# HF Football Data Hub Phase 1.1 — Identity Lock Deployment Notes

Phase 1.1 adds a P0-0 Match Identity Lock before multi-source packet merging.

## Core rule

`Titan007 match_id` is the primary anchor. Team aliases are used only for candidate recall and are never sufficient to confirm same-match identity.

## Merge requirements for external sources

An external source can attach to `canonical_match_key` only when identity scoring passes:

- league / competition consistent
- kickoff time within tolerance
- home-team alias match
- away-team alias match
- home/away direction not swapped
- team type consistent (first team vs U21/Women/Reserve)
- identity_score >= 90

If identity is uncertain, the packet must carry `identity_locked=false` and Hermes must block strict_50 analysis with `DATA_IDENTITY_UNCERTAIN`.

## Packet fields

Every packet contains:

```json
{
  "match_identity": {
    "version": "match_identity_lock_v1",
    "canonical_match_key": "titan007:<match_id>",
    "identity_locked": true,
    "primary_source": "titan007",
    "primary_match_id": "<match_id>",
    "identity_score": 100,
    "team_alias_policy": {
      "alias_used_for": "candidate_recall_only",
      "alias_not_sufficient_for_merge": true
    },
    "cross_source_attachment_policy": {
      "min_identity_score_to_merge": 90,
      "home_away_swapped_blocks_ah_merge": true,
      "llm_guessing_allowed": false
    }
  }
}
```

## Hermes integration

Hermes must treat `hf_final_pick_allowed=false` as data-layer boundary only. It must not treat that field as NO_BET.

Hermes must treat `match_identity.identity_locked=false` or `match_identity.identity_score<90` as critical data failure:

```text
DATA_IDENTITY_UNCERTAIN
```

Do not merge AH/OU data when home/away is swapped.
