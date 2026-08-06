---
title: RaagaFinder
emoji: 🎵
colorFrom: indigo
colorTo: red
sdk: gradio
sdk_version: 6.19.0
python_version: "3.12"
app_file: app.py
license: mit
short_description: Identify the raga of a Carnatic recording
---

# 🎵 RaagaFinder

Upload a Carnatic music recording — get the **raga**, with honest confidence.

- **Three selectable models**: a broad 87-raga model (default), a
  concert-tuned 71-raga one and a widest 104-raga one (CompMusic 480-recording
  corpus + Saraga 1.5 Carnatic + verified concert recordings + a private solo
  devotional set; see RAGA_TRACKER.md). Top-3 predictions with calibrated
  confidence bars, raga info cards, and a "show your work" pitch-class plot.
- Melody extraction via [essentia](https://essentia.upf.edu/) MELODIA,
  tonic-normalized pitch-class distributions + time-delayed melody surfaces
  (TDMS, Gulati et al. ISMIR 2016), a pure-numpy model artifact (kNN on melody
  surfaces + logistic regression on the pitch distribution + a per-swara gamaka
  member) — no GPU needed anywhere.
- Honest evaluation: grouped cross-validation (no concert/artist leakage
  between train and test). See the About tab for current numbers.

Live app: <https://huggingface.co/spaces/Sukarth/raagafinder> · Source:
<https://github.com/Sukarth/raagafinder> · History: see CHANGELOG.md

## Results (three selectable models)

Every model is a pure-numpy ensemble (kNN on melody surfaces + logistic
regression on the pitch distribution, and in the two newer models a per-swara
gamaka member) blended with a DeepSRGM-style LSTM reading the token-level
*sequence* of the melody, i.e. note order and phrase context that
distribution features cannot see, each with its own checkpoint and blend
calibration. All three models' blend weights are now fitted on a complete
ten-fold out-of-fold sequence run, so every quoted accuracy is the full
pipeline's, measured on recordings no component selected on.
Everything is evaluated with StratifiedGroupKFold(10) grouped by concert, so
recordings from the same concert or release never span train and test.

| | Broad (87 ragas, default) | Concert-tuned (71 ragas) | Widest (104 ragas) |
|---|---|---|---|
| corpus | 855 recordings | 756 recordings | 986 recordings |
| grouped-CV top-1 / top-3 (distribution ensemble only) | 79.4% / 90.1% | 82.3% / 91.7% | 77.1% / 88.2% |
| out-of-fold top-1 / top-3, full pipeline (see below) | 81.4% / 91.4% | **84.0% / 93.4%** | 79.4% / 90.5% |
| real-world concerts (18 in-set YouTube) | 67% / **78%** | **78%** / 78% | 56% / 67% |
| solo devotional voice (18-recording holdout, never trained) | **89%** / 89% | 83% / 89% | **89%** / 89% |
| sequence model | yes | yes | yes |

**Why the widest model is not the default.** It names ragas the other two
cannot, and that is the only reason to pick it. It ties the default on the
devotional holdout and loses on every other axis, worst of all on the audio
most like a real upload: 56% top-1 on the YouTube set against the default's
67%. Most of that is the arithmetic of adding classes, since every addition
is one more look-alike competing for every answer. It is offered as a third
choice rather than promoted, and the app says so at the selector.

Three of its classes (Puṇṇāgavarāḷi, Janaranjani, Śuddha Sāvēri) never once
reached the top-3 in cross-validation. The app lists them with their measured
0-of-n rather than dropping them, so the list stays complete and the reader is
told which entries not to trust. Śuddha Sāvēri is a regression specifically:
it identifies by note *order* within a scale it shares with a much larger
class, it was reachable before only through the broad model's sequence stage
for exactly that reason, and crossing the recording quota promoted it into an
ensemble that cannot represent it. The sequence stage is not much better: the
ten-fold run below puts it in the top-3 for 1 of 5 recordings.

**What the two accuracy rows measure.** The first is the distribution ensemble
by itself, cross-validated over the corpus. The second is the system the app
actually serves, sequence stage included — and producing it honestly took ten
LSTMs, one trained per fold, each predicting only the recordings its own fold
held out. Until those existed the blend could be scored only on the single
fold a shipped checkpoint held out, which flattered it: that same fold chose
the checkpoint's stopping epoch, so the sequence model was scored on its best
showing while the ensemble was scored out-of-fold. The old ensemble-only row
was quoted as a conservative floor for exactly that reason. It no longer has
to be.

Measured over all ten folds and 872 recordings — the 855 the ensemble covers,
plus 17 in four ragas only the sequence stage can name:

| system | top-1 | top-3 |
|---|---|---|
| distribution ensemble alone | 78.4% | 89.6% |
| sequence model alone | 77.3% | 88.9% |
| blend at the previously shipped weight | 79.9% | 91.2% |
| blend at the newly fitted weight | **81.4%** | **91.4%** |

The ensemble scores a point lower here than in the table above because those
17 recordings are counted against it and it cannot name their ragas at all.
The two components are within a point of each other and the blend beats both,
which is the case for carrying a second model rather than picking the better
one. The blend weight itself moved from 0.15 to 0.40, the first time the fit
had enough sample to say that 0.15 was too low rather than merely
indistinguishable from everything else; weights from 0.20 to 0.55 tie the peak
under McNemar and the app ships the middle of that run.

A single number also hides most of what a user wants to know, because the
corpus is four very different sources:

| source | broad model top-1 | n |
|---|---|---|
| CompMusic 480 (curated research recordings) | 87.7% | 480 |
| YouTube concerts | 71.2% | 146 |
| private solo devotional | 68.8% | 80 |
| Saraga 1.5 | 66.4% | 149 |

Clean, well-recorded solo material is where the system is strongest; dense
concert audio with heavy accompaniment is where it is weakest. The About tab
breaks this down further by clip length and by how many recordings of that
raga the model has seen.

The three models exist because adding ragas is a genuine trade-off, not a free
win. Growing the class list spreads probability mass across more allied-raga
candidates, so on noisy full-concert audio the correct raga slips to second or
third place more often (top-1 dips) even though it stays in the top-3. The
concert-tuned model keeps the sharpest top-1 ranking on concert recordings
across the smallest raga set; the broad model takes the trade for 16 more
ragas and clearly better accuracy on clean solo voice; the widest model takes
it again, and much harder, for 17 more still. Because the app is built around
the top-3 rather than a single answer, the first two serve most uploads well.
Pick with the Model selector, and see the About tab for guidance.

The LSTM is blended into the final answer only where evidence corroborates it:
for long recordings when several independently-analyzed sections agree, and for
short single-section recordings only when the model's own analysis windows
agree (weight and temperature fit on a complete ten-fold out-of-fold run for
all three models, never on the real-world sets). On the concert-tuned model
this recovered three allied-raga YouTube misses (+17 points top-1) with no
holdout regression.

The concert-tuned model was the last of the three still quoting its ensemble's
accuracy rather than the pipeline's, because its blend weight had been fitted
on fold 0 alone, which is the fold its own sequence checkpoint early-stopped
against. Running all ten folds settled it: the honest fit picks the same
`w=0.35` that the fold-0 fit did, so the shipped weight was never biased, and
the temperature moves only from 0.523 to 0.538. What changes is what may be
claimed. The pipeline measures 84.0% / 93.4% against the ensemble's 82.3% /
91.7%, so the sequence stage is worth 1.7 points of top-1 here and the model
had been understating itself. The weight also sits in a wide plateau: every
value from 0.20 to 1.00 is statistically indistinguishable from the peak under
McNemar, 17 of the 21 grid points, which is the honest reason not to tune it
further.

Class expansion is demand-driven and quality-gated: every new raga needs ≥3
verified recordings, and classes that fail out-of-fold sanity (a rarely-performed
parent mela swamped by its own janyas; note-ORDER ragas invisible to
distribution features) are cut from the ensemble rather than shipped. A few of
those cut ragas return in the broad model as experimental classes the sequence
stage alone can name — and the ten-fold run finally measured them, four ragas
that had shipped since v4 on the assumption that the sequence model could
identify them. It can name one: Māṇḍ, top-1 correct in 3 of 6. The other
three are top-1 correct in 0 of 11 between them, and reach the top-3 once. They
stay listed, with those numbers, for the same reason the widest model's dead
classes do. See RAGA_TRACKER.md for what's covered, what was cut and why, and
what's queued next.

For reference, the baseline reproduction (TDMS + 1-NN, leave-one-out, on the
original 480-recording corpus) scores 85.2% top-1, against Gulati 2016's
published 86.7%. That v1 artifact is no longer shipped — nothing in the app can
select it — but the reproduce steps below regenerate it from the dataset.

Tonic robustness (v1.1): octave errors are absorbed by octave folding; the
tonic itself is chosen BEFORE classification by consensus across sampled
sections of the recording, with a Sa-mass sanity veto rescuing catastrophic
detector errors (validated on the training corpus: 99.8% keep-correct).
Long recordings are analyzed as independent sections merged by corroboration,
so one bad section (applause, speech, a different item) can't poison the
result. Real-world YouTube-recording benchmark: top-1 57% → 71% across the
v1 → v1.1 changes.

Known limitations (measured, documented as dead ends in-code): recordings
without a drone can lock the tonic a minor third off — no histogram-level
signal can catch this (graha bheda: the rotated note set matches a different
valid raga); same-note-set raga pairs (Tōḍi/Sindhubhairavi) and one-swara-off
pairs (Pūrvīkaḷyāṇi/Kāmavardani, and out-of-set Madhuvanti → Kalyāṇi) are
beyond pitch-distribution features entirely, and the v3 LSTM blend
(`notebooks/kaggle_v3.ipynb`) now attacks exactly this on
long recordings; on short single-section clips it is consulted only when the
sequence model's own analysis windows agree, so it helps less often there.

## Repo layout

- `app.py` — Gradio app (this Space's entry point)
- `raagafinder/` — package: dataset adapter, pure-numpy features (PCD/TDMS),
  pitch backends (essentia / rmvpe fallback), models, inference pipeline, UI
- `scripts/` — command-line entry points for collection, training, evaluation
  and deployment; see `scripts/README.md` for an index of all 51
- `tests/` — the suite, run with `python -m pytest`
- `notebooks/` — the GPU training notebooks for the sequence models
- `models_artifacts/` — trained model artifacts (npz + json + onnx, Git LFS)
- `docs/` — writeups of measured experiments
- `RAGA_TRACKER.md` — what is covered, what was cut and why, what is queued
- `DATASET_NOTES.md` — discovered dataset schema and invariants

## Reproduce the model (CPU is enough)

```bash
pip install -r requirements-train.txt
python scripts/make_sample_clips.py                 # synthetic test clips
python -m raagafinder.dataset.preprocess            # needs the Zenodo zip in data/raw/
python -m raagafinder.models.train                  # TDMS+kNN baseline + frozen splits
python -m raagafinder.models.zoo                    # model zoo, calibration, artifact
python -m pytest                                    # golden feature tests
```

Training data: [Indian Art Music Raga Recognition Dataset (features)](https://zenodo.org/records/7278506)
(3.6 GB zip → `data/raw/raga_features.zip`).

## Attribution

Trained on features from the **Indian Art Music Raga Recognition Dataset**
by S. Gulati, J. Serrà, K. K. Ganguli, S. Sentürk & X. Serra
(CompMusic project, Music Technology Group, Universitat Pompeu Fabra),
[Zenodo 7278506](https://zenodo.org/records/7278506), licensed CC-BY 4.0.

Also trained on **Saraga 1.5 Carnatic** (CompMusic / MTG-UPF),
[Zenodo 4301737](https://zenodo.org/records/4301737), licensed CC BY-NC-SA
4.0 — pitch and tonic annotations only, no audio is redistributed here.

Method follows *Time-Delayed Melody Surfaces for Rāga Recognition* (ISMIR 2016).
Code license: MIT (see `LICENSE`).
