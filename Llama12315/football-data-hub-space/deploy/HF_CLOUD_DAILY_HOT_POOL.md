# HF cloud daily hot-pool deployment

## Purpose

The daily `赛事 → 热门` capture runs on Hugging Face infrastructure, never on Hermes.
It remains available when the local computer is offline.

## Collector

`scripts/hf_daily_hot_pool_job.py`:

1. fetches Titan007 public static schedule data in the cloud;
2. applies the existing popular-event filter;
3. takes two snapshots five minutes apart and requires ≥50% ID overlap;
4. uploads `data/hot_match_pool/YYYY-MM-DD.json` and `data/source_status/YYYY-MM-DD.json` to `Llama12315/football-data-hub`;
5. reads the Dataset back by SHA and verifies `/hot-matches?date_=YYYY-MM-DD` on the Space.

It has no model, analysis, pick, stake, bankroll, or Telegram path.

## Required scheduled Job

Create this Hugging Face Scheduled Job after Jobs credits are available:

```bash
hf jobs scheduled uv run '40 2 * * *' \
  https://huggingface.co/spaces/Llama12315/football-data-hub-space/resolve/main/scripts/hf_daily_hot_pool_job.py \
  --repo Llama12315/football-data-hub-space \
  --flavor cpu-basic \
  --timeout 20m \
  --env HF_DATASET_REPO=Llama12315/football-data-hub \
  --env HF_SPACE_URL=https://llama12315-football-data-hub-space.hf.space \
  --env HOT_POOL_STABILITY_GAP_SECONDS=300 \
  --secrets HF_TOKEN
```

`40 2 * * *` is 10:40 Asia/Shanghai (UTC+8). The job's `HF_TOKEN` secret needs Dataset write permission.

## Free-plan scheduler actually deployed

HF Jobs needs prepaid credits and is therefore deliberately **not used**. The
existing UptimeRobot HTTP/S monitor already calls:

```text
https://llama12315-football-data-hub-space.hf.space/health
```

Free Space code uses that ping as its cloud-only clock. A GET received during
10:40--10:55 Asia/Shanghai launches exactly one background data-only capture.
The runner takes two source snapshots five minutes apart, then persists only an
accepted stable pool to the HF Dataset. Outside that window `/health` stays a
normal lightweight health response.

No local Hermes process, HF Job, model call, prediction, stake, or bankroll path
is involved. The scheduler audit endpoint is:

```text
/daily-hot-pool-status
```

## Acceptance

1. At the next 10:40--10:55 Asia/Shanghai monitor window, inspect
   `/daily-hot-pool-status`; it must move `never_run → running → completed`.
2. Verify `/ready` has `hot_match_pool_available=true`.
3. Verify `/hot-matches?date_=YYYY-MM-DD` returns non-empty current-date rows.
4. Verify Dataset has `data/hot_match_pool/YYYY-MM-DD.json` and matching
   `data/source_status/YYYY-MM-DD.json`.
5. Packet construction is a separate follow-up: this deployment fixes the daily
   popular-event pool, not pool-member compact match packets.
