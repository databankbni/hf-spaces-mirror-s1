---
title: MBench Leaderboard
emoji: 🏆
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 4.36.1
python_version: '3.10'
app_file: app.py
pinned: false
license: mit
---

# MBench Leaderboard

MBench is a benchmark for evaluating the memory capability of video world models. It focuses on whether a model can preserve a coherent world state across long-horizon video continuation and interaction.

The benchmark is organized around three core memory dimensions:

- **Entity Consistency:** persistent object and human identity, geometry, texture, and appearance.
- **Environment Consistency:** stable spatial layout, reprojection behavior, lighting, and style.
- **Causal Consistency:** reliable state evolution and interaction consequences over time.

MBench uses trigger-conditioned scoring: Trigger Coverage measures whether the model actually enters the intended memory challenge, Memory Reliability measures consistency after the challenge is triggered, and M-Score balances both with a harmonic mean.

The bundled seed leaderboard is transcribed from Table 2 of the MBench paper. Aggregate leaderboard columns are derived as unweighted averages over the reported sub-dimensions until official leaderboard totals are released.

## Links

- **Dataset:** `studyOverflow/TempMemoryData`
- **Leaderboard data repo:** `PeanutUp/membench_leaderboard_submission`
- **GitHub repo:** https://github.com/study-overflow/MBench
- **Project page:** https://peanutup.github.io/MBench-project/

## Submission format

Upload a ZIP with `leaderboard_submission.json` at its root:

```text
submission.zip
├── leaderboard_submission.json
└── verification/
    ├── entity/
    │   ├── summary.json
    │   ├── items.jsonl
    │   └── units.jsonl
    ├── environment/
    │   ├── summary.json
    │   ├── items.jsonl
    │   └── units.jsonl
    └── causal/
        ├── summary.json
        ├── items.jsonl
        └── units.jsonl
```

The verification files are recommended for official review but are not used
directly for public ranking. The aggregate file must contain:

```json
{
  "model_name": "ExampleWorldModel",
  "model_link": "https://example.com/model",
  "model_type": "text-conditioned",
  "total_m_score": 52.46,
  "entity_score": 55.1,
  "environment_score": 50.2,
  "causal_score": 47.8,
  "trigger_coverage": 61.0,
  "memory_reliability": 46.0
}
```

`model_type` must be `text-conditioned` or `action-conditioned`. All provided
scores must be numeric values between 0 and 100.

The Space stores each accepted upload under `submissions/pending/` in the
leaderboard data repo. Pending submissions do not modify `results.csv` and are
not displayed until they have been reviewed by the MBench team.
