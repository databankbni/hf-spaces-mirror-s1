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

- **Four selectable models plus a smart cascade**: a complete 154-raga model
  covering all 72 melakartas (default), a broad 87-raga one, a concert-tuned
  71-raga one, a widest 104-raga one, and a cascade that answers with
  the broad model unless it is uncertain, then with the complete one
  (CompMusic 480-recording corpus + Saraga 1.5 Carnatic + verified concert
  recordings + a private solo devotional set; see RAGA_TRACKER.md). Top-3
  predictions with calibrated confidence bars, raga info cards, and a "show
  your work" pitch-class plot.
- **Add a raga without retraining**: three to five recordings of a raga the
  models do not know are averaged into one prototype and compared alongside
  the trained classes for the length of a session. Measured at 0.800 top-1
  out-of-fold against 0.849 for trained ragas under the same comparison,
  with an abstention gate that is deliberately harsher on the added ones.
- Melody extraction via [essentia](https://essentia.upf.edu/) MELODIA,
  tonic-normalized pitch-class distributions + time-delayed melody surfaces
  (TDMS, Gulati et al. ISMIR 2016), a pure-numpy model artifact (kNN on melody
  surfaces + logistic regression on the pitch distribution + a per-swara gamaka
  member) — no GPU needed anywhere.
- Honest evaluation: grouped cross-validation, so no concert or release
  spans train and test. Artists are *not* separated -- folds are grouped by
  artist-and-release, so 85% of the benchmark recordings that carry an
  artist field are by artists appearing on both sides. The paired
  artist-disjoint retrain that prices this is reported in the paper
  (+1.88 points, McNemar p = 0.22). See the About tab for current numbers.

Live app: <https://huggingface.co/spaces/Sukarth/raagafinder> · Source:
<https://github.com/Sukarth/raagafinder> · History: see CHANGELOG.md

## Results (four selectable models)

Every model is a pure-numpy ensemble (kNN on melody surfaces + logistic
regression on the pitch distribution, and in the two newer models a per-swara
gamaka member) blended with a DeepSRGM-style LSTM reading the token-level
*sequence* of the melody, i.e. note order and phrase context that
distribution features cannot see, each with its own checkpoint and blend
calibration. All four models' blend weights are now fitted on a complete
ten-fold out-of-fold sequence run, so every quoted accuracy is the full
pipeline's, measured on recordings no component selected on.
Everything is evaluated with StratifiedGroupKFold(10) grouped by concert, so
recordings from the same concert or release never span train and test.

**Corrected 2026-08-25 for duplicate performances.** Every deduplication
guard in this project compared identifiers -- a video id, an mbid, a
filename -- and an audit against the audio itself found 26 pairs of
recordings that are the same performance under two names, 26 of them
byte-identical after pitch extraction. They arrive when one video is
fetched under two search queries, or when a release sits in both source
datasets. 49 of those recordings straddle a fold boundary, so each was
scored against a training set holding its own twin, and every one of the
49 was top-1 correct. The figures below exclude them. For the complete
model that moves 85.0 / 92.6 to 84.4 / 92.2; for the concert model,
84.0 / 93.4 to 83.7 / 93.2. † marks the two models whose stored
out-of-fold dump does not reproduce its published figure exactly, so no
corrected number is quoted for them: they carry the same contamination,
measured at roughly 0.1 and 0.8 points on the nearest available dump,
and the uncorrected value is shown rather than an invented one.
`scripts/audit_duplicate_recordings.py` reproduces the whole set from
the audio. The correction is to the measurement only; no model changed,
and the prototype gain that motivated the current complete model
survives deduplication at +2.6 points, ten folds of ten, p = 0.002.

| | Broad (87 ragas) | Concert-tuned (71 ragas) | Widest (104 ragas) | Complete (154 ragas, default) |
|---|---|---|---|---|
| corpus | 855 recordings | 756 recordings | 986 recordings | 1275 recordings |
| grouped-CV top-1 / top-3 (distribution ensemble only) | 79.4% / 90.1% | 82.3% / 91.7% | 77.1% / 88.2% | 74.3% / 86.7% |
| out-of-fold top-1 / top-3, full pipeline (see below) | 82.8% / 92.0%† | 83.7% / 93.2% | 80.7% / 90.8%† | **84.4% / 92.2%** |
| real-world concerts (18 in-set YouTube) | 67% / **78%** | **78%** / 78% | 56% / 67% | 56% / 67% |
| solo devotional voice (18-recording holdout, never trained) | **89%** / 89% | 83% / 89% | **89%** / 89% | 83% / 89% |
| sequence model | yes | yes | yes | yes |

**The complete model covers the whole melakarta system.** Its 154 classes
include all 72 parent scales, and since 2026-08-24 its sequence stage is
trained with a second round of noisy-student pseudo-labels drawn from about
670 hours of unlabeled concert audio -- the first change to clear this
project's pre-registered adoption bar since seed selection (+2.2 points at
the blend across ten folds, Wilcoxon p = 0.012). On 67 freshly collected
YouTube recordings it scores 73%/84% top-1/top-3 against the broad model's
64%/81%. The n=18 rows above each moved by one recording between versions,
which is within single-clip noise. The melakarta classes still rest on three
or four YouTube recordings each, so their per-class numbers remain thin by
construction; several of the rarest are reachable mainly through
recital-series uploads rather than concert performances.

On 2026-08-25 its sequence stage gained a second opinion: each raga is also
represented by the average of its recordings' learned embeddings, and a
match against those averages is mixed into the sequence stage's own answer.
That is worth +2.5 points of out-of-fold top-1, winning all ten folds
(Wilcoxon p = 0.002), and it takes this model to the best cross-validated
accuracy of the four.

The gain is not spread evenly, and the useful version of the claim says
where it lands. Split by how many recordings a raga has in the corpus, the
change is worth +12.8 points on ragas with three or four, +5.0 on ragas
with five or six, and +0.0 on ragas with thirteen or more. A well-known
raga therefore returns the same answer it did before; a rare melakarta
returns a much better one. Nothing measured got worse. The three held-out
sets above are unchanged by it, and that is expected rather than
disappointing: none of them contains a single rare raga, so none of them
can see this change at all.

**The smart cascade.** The broad model answers unless its own shipped
uncertainty gate fires, in which case the complete model answers instead,
so all 154 ragas are reachable. The cascade predates the default change of
2026-08-26 and its rationale was "reach the complete model's ragas without
paying its cost on common ones"; now that the complete model IS the default,
the cascade is a way of getting the broad model's answer first rather than a
way of reaching further, and it is kept because it is measured rather than
because that rationale still holds. Nothing was fitted to build it -- the gate predates the idea
-- which is what keeps its evaluation honest. It has no single
cross-validation figure, because the two models trained on each other's
test folds; measured instead on three held-out sets no deployed model
trained on (remeasured 2026-08-24 with the v3_0 fallback): 69%/87%
top-1/top-3 on 67 fresh YouTube recordings -- where its top-3 now exceeds
either model alone -- 56%/67% on the 18-clip concert set, 83%/89% on the
devotional holdout. Hard recordings take longer, since two models run.

**The default changed on 2026-08-26, from the broad model to the complete
one.** The broad model held the slot on the strength of the 18-clip YouTube
set, where it scores 67% against the complete model's 56%. A power analysis
that day showed that set cannot resolve anything below roughly 56 points, and
that this particular comparison rests on four clips disagreeing -- one gained,
three lost, McNemar p = 0.63. It is noise, and it was the only evidence for
the previous default. The two better-powered sources disagree with it: the
complete model leads on grouped cross-validation over 1275 recordings
(84.4% against 82.8%) and by nine points on the 67-recording fresh-YouTube
probe (73.1% against 64.2%, six clips gained and none lost, p = 0.031). All 67
probe ragas sit inside the broad model's class list, so this is a like-for-like
comparison rather than the complete model winning on ragas the broad one
cannot name.

**The widest model no longer has a reason to exist.** It was kept because it
named ragas nothing else could reach; the complete model's 154 classes are a
superset of its 104, so that stopped being true the day the complete model
shipped, and the About tab said otherwise until this was noticed. It remains
selectable for continuity and is recommended for nothing.

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
| blend at the newly fitted weight | 81.4% | 91.4% |
| the same blend, corrected for the long tail | **82.8%** | **92.0%** |

The ensemble scores a point lower here than in the table above because those
17 recordings are counted against it and it cannot name their ragas at all.
The two components are within a point of each other and the blend beats both,
which is the case for carrying a second model rather than picking the better
one. The blend weight itself moved from 0.15 to 0.40, the first time the fit
had enough sample to say that 0.15 was too low rather than merely
indistinguishable from everything else; weights from 0.20 to 0.55 tie the peak
under McNemar and the app ships the middle of that run.

**The sequence stage reads a 4x coarser melody, and is better for it.** The
pitch track inherited a 4.4 ms hop from the research corpus's files, which
oversamples the music: gamakas move at a few hertz, not a hundred. On the
complete model, tokenizing at 17.8 ms (the same 20-second window in a
quarter of the steps) trains 4.6x faster, runs the sequence stage in 1.5
seconds a section instead of 4.2, and scores no worse -- out-of-fold the
blend moved from 78.5% to 80.3% top-1, a +1.8-point mean fold delta whose
interval just grazes zero (Wilcoxon p = 0.051), so it is claimed here as
"at least as accurate, four times cheaper" rather than as an accuracy win.
The shorter sequence also trains more stably: the full-resolution run had
two folds collapse below 0.71, the downsampled run none below 0.74.

**The long-tail correction.** The corpus runs from three recordings a class to
twenty-three, and a classifier trained on that learns the imbalance along with
the ragas. Each class's blended probability is divided by its training
frequency raised to a power and renormalised, which moves the decision
boundary toward the rare ragas without retraining anything. The power is
chosen leave-one-fold-out, so no fold's value was picked on the recordings it
then scores: that gives +1.60 top-1 points for the default model, 95% CI
[+0.73, +2.46], Wilcoxon p = 0.008, winning eight folds of ten and losing
none. The widest model gains +1.42 points on the same procedure. The
concert-tuned model does not clear the bar and ships uncorrected: it gains on
paper but moves only three folds of ten, and its interval reaches below zero.

Where the change lands matters more than the total, because the mechanism is
specific. For the default model, classes with three or four recordings gain
7.9 points and those with five to nine gain 5.8, while classes with ten to
fourteen are unmoved and those above fifteen lose 1.0. That last figure is the
honest cost, and it is the one to weigh against real use: uploads skew toward
the ragas that are common enough to be well covered, so a correction aimed at
the tail is paid for partly by the head. The power that the fold procedure
selects is shipped rather than a gentler one chosen after seeing that table,
since picking the knob after reading the outcome is the thing the procedure
exists to prevent.

The complete model is the counterexample that keeps this honest. On its
first build (153 classes, 2026-08-09) the fold-chosen power, 0.60, cleared
the same bar in cross-validation (+2.0 points, winning eight folds of ten)
and then failed on real audio: on the eighteen-clip YouTube set it left
top-1 unchanged and cost three of fifteen top-3 hits, because with dozens of
three-recording classes in the tail the correction moves real uploads'
probability onto ragas they never are. The cross-validated gain is measured
under the corpus's own class mix, and that is precisely what a real upload
does not share. So the complete model ships uncorrected, and the decision
rule is the one round 5 set: growing or reweighting the class list is judged
on the YouTube set, not on cross-validation.

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

The four models exist because adding ragas is a genuine trade-off, not a free
win. Growing the class list spreads probability mass across more allied-raga
candidates, so on noisy full-concert audio the correct raga slips to second or
third place more often (top-1 dips) even though it stays in the top-3. The
concert-tuned model keeps the sharpest top-1 ranking on concert recordings
across the smallest raga set; the broad model takes the trade for 16 more
ragas and clearly better accuracy on clean solo voice; the widest model takes
it again, and much harder, for 17 more still; the complete model takes it
hardest of all, paying two further points of out-of-fold top-1 to cover the
melakarta system. Because the app is built around the top-3 rather than a
single answer, the first two serve most uploads well. Pick with the Model
selector, and see the About tab for guidance.

The LSTM is blended into the final answer only where evidence corroborates it:
for long recordings when several independently-analyzed sections agree, and for
short single-section recordings only when the model's own analysis windows
agree (weight and temperature fit on a complete ten-fold out-of-fold run for
all four models, never on the real-world sets). On the concert-tuned model
this recovered three allied-raga YouTube misses (+17 points top-1) with no
holdout regression.

The concert-tuned model was the last of the original three still quoting its
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
three are top-1 correct in 1 of 11 between them, and reach the top-3 three
times. They
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

## Adding a raga without retraining

A raga outside the 154 can be added from the app's "Add a raga" tab for the
length of one browser session. Three to five recordings are embedded by the
sequence model, averaged into one 768-dimension prototype, and that prototype
competes with the trained classes' prototypes — the same class-mean mechanism
already mixed into every answer the default model gives. Nothing is trained,
nothing is written to disk, and nothing is shared between sessions.

Measured out-of-fold with thirty ragas withheld from every training fold,
added from five recordings each and competing against all 154 classes at
full strength — the trained classes keep every recording they have, as they
do in the app. Both columns come from one run of
`scripts/enroll_abstain_whitened.py` and the same prototype comparison, so
the gap between them is the cost of being an added raga rather than a
difference of method (375 enrolled queries of 1275):

| top-1 | enrolled from 5 | trained classes, same comparison |
|---|---|---|
| plain cosine | 0.763 | 0.821 |
| WCCN-whitened | **0.800** | 0.849 |

The right-hand column is the prototype comparison alone. Trained ragas do
not reach the user that way — they arrive through the full blended pipeline,
which scores 0.844 out-of-fold — and they are scored under plain cosine in
serving, whitened or not. The column is here because it is the only
like-for-like reading of what enrollment costs.

The whitening is a single global transform of the embedding space, fitted on
the within-class scatter of the trained classes at shrinkage 0.5 and applied
to the enrolled comparison only (`scripts/build_whitener.py`, written to
`models_artifacts/model_v3_1.whitener.npy`). It is worth 3.7 points on
enrollment, and it is deliberately **not** applied to the 154 trained
classes: there it measures +0.31 points at Wilcoxon p = 0.65, which does not
justify moving the metric that the blend weight, the temperature and every
advertised accuracy were fitted against. The shrinkage optimum is interior
rather than at a grid edge — prototype accuracy runs 0.804 at shrinkage 0,
0.870 at 0.5 and back to plain cosine's 0.838 as the transform approaches the
identity — and the transform, fitted only from classes the encoder trained
on, still improves classes it has never seen, which is what makes it a
statement about the representation rather than about a class list.

Enrolled answers pass an abstention gate: the softmax over cosine
similarities at the shipped prototype temperature 0.05, kept above 0.4161
(`scripts/enroll_abstain.py`, 1275 queries). One threshold serves both kinds
of class and it is deliberately harsher on the enrolled ones — 67.7% of their
answers are let through against 80.6% of trained-class answers, and the two
are then 89.4% and 90.3% accurate. Answering less often where the system
knows less is what keeps "confident" meaning one thing across both. The raw
cosine and the cosine margin were measured against the same target and both
fail here: they keep roughly three quarters of each group and are then four
points further apart in accuracy on them.

That threshold was fitted on the plain cosine, before the whitened metric
existed, and it is carried over rather than refitted — fitting a second
constant for enrolled classes is a decision to take on purpose. What the
carry-over does was measured rather than assumed
(`scripts/enroll_abstain_whitened.py`, the same 1275 queries with only the
metric changed):

| metric | enrolled kept | accuracy | all kept | accuracy |
|---|---|---|---|---|
| plain cosine, as fitted | 67.7% | 89.4% | 76.8% | 90.1% |
| whitened, threshold held | 69.6% | 92.0% | 74.0% | 94.3% |

The threshold was chosen as the largest coverage still reaching 90% overall,
so under whitening the carried-over rule under-promises rather than
over-promises: it answers slightly less often than the fit intended and is
four points more accurate when it does.

Which recordings are submitted matters more than how many. Keeping the
recordings closest to their own class mean scores 0.772 at three recordings
against 0.753 for five random ones, while deliberately diverse ones —
farthest-point sampling over the same pool — are the worst strategy measured
at 0.569 (`scripts/enroll_selection.py`, thirty withheld ragas, 375 queries).
What sits far from a class mean in this embedding is more often a failed
pitch track or a mislabelled recording than an unusual rendition. The app
surfaces that as guidance rather than filtering silently, because the
selection also discards genuinely unusual renditions and the person adding
the raga is the one who can tell the two apart.

Every figure above is measured on corpus recordings. A recording found
elsewhere carries the same found-audio penalty the rest of this system does,
and nothing here separates the two.

## Repo layout

- `app.py` — Gradio app (this Space's entry point)
- `raagafinder/` — package: dataset adapter, pure-numpy features (PCD/TDMS),
  pitch backends (essentia / rmvpe fallback), models, inference pipeline, UI
- `scripts/` — command-line entry points for collection, training, evaluation
  and deployment; see `scripts/README.md` for an index of all 51
- `tests/` — the suite, run with `python -m pytest`
- `notebooks/` — the GPU training notebooks for the sequence models
- `models_artifacts/` — trained model artifacts (npz + json + onnx under Git
  LFS, plus the npy class prototypes and enrollment whitener)
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
