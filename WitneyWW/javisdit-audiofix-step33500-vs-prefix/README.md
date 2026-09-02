---
title: JavisDiT audio-repair - step 33500 vs pre-fix baseline
emoji: "⚖️"
colorFrom: indigo
colorTo: red
sdk: static
pinned: false
---

> ## ⚠️ SUPERSEDED — the conclusion on this page is wrong
>
> This page reported that the audio-repair fine-tune cost ~40% of video edit strength.
> It does not. That comparison evaluated the fine-tuned model **without** the reference
> anchor, which is out-of-distribution for it: `ref_prepend_warmup_steps = 0` is falsy,
> so the training-time annealing branch never ran and the anchor was kept on every step.
> Read in its own native condition the fine-tune is ~50% **stronger** than the baseline
> (video gap −19.35 vs −12.95), with the audio gain intact.
>
> See **[the corrected anchor matrix](https://huggingface.co/spaces/WitneyWW/javisdit-anchor-matrix)** for all 8 model × ref-mode × task cells.


# Audio repair at step 33500 - what it fixed, and what it cost

Ten held-out `test.jsonl` clips. Each shows **input / fine-tuned / pre-fix / target /
pseudo GT**. The two generated columns differ only in weights: same clips, same corrected
audio latents, same per-entry seeds.

| | pre-fix (step-140000) | fine-tuned (step-33500) |
|---|---|---|
| **video** edit gap (L1->target - L1->input, lower is better) | **-12.95** (9/10) | -7.74 (7/10) |
| **audio** log-mel corr vs pseudo GT (higher is better) | 0.617 (median 0.647) | **0.72** (median 0.854) |

Round-trip ceiling for the audio column: 0.973.

**The repair worked on audio and cost video.** The fine-tune was run after a mel
filterbank regression (torchaudio `norm=None/htk` instead of librosa `slaney/slaney`)
was found to have made every encoded target mel 122x too hot. Retraining on corrected
latents lifted audio correlation from 0.647 to 0.854 median, but video edit
strength fell about 40%.

The video drop is caused by the fine-tune, not by the regenerated data: the pre-fix
checkpoint scores -12.95 on this same corrected data, versus -13.11 on the old data.

Both metrics plateaued by step ~10500 -- steps 10500, 14000 and 33500 score within noise
of each other on both axes -- so the extra 23,000 steps changed nothing either way.

256x256, 81 frames @ 16 fps, mono 16 kHz, cfg 1.0, 50 steps, no reference frame.
N=10 clips: enough to see a 40% video drop and a 0.2 audio gain, not enough to resolve
small step-to-step differences.
