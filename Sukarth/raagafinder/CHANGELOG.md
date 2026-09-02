# Changelog

All notable changes to RaagaFinder. Dates are 2026. Accuracy numbers are
recording-level top-1/top-3; "YouTube" is the found-concert benchmark and
"holdout" is the solo-voice set that never enters training (n=18 each).

## 2026-08-27 — a raga can be added without retraining

The app gains an **Add a raga** tab. Three to five recordings of a raga
outside the 154 are embedded by the sequence model, averaged into one
768-dimension prototype, and compared alongside the trained classes on every
identification for the rest of that browser session. Nothing is trained and
nothing is written to disk.

Measured out-of-fold with thirty ragas withheld from every training fold,
added from five recordings each and competing against all 154 classes at
full strength — the trained classes keeping every recording they have, as
they do in the app: **80.0%** top-1, against **84.9%** for the trained
classes under that same prototype comparison. Both halves come from one run
of `scripts/enroll_abstain_whitened.py`, which is the point — measuring an
added raga against the app's headline 84.4% would compare a prototype match
against a full blended pipeline. The 80.0% is what the whitened metric buys;
plain cosine on the same split gives 76.3% against 82.1%.

**The new artifact is a metric, not a model.**
`models_artifacts/model_v3_1.whitener.npy` is a single 768×768 WCCN
transform, fitted by `scripts/build_whitener.py` on the within-class scatter
of the serving encoder's embeddings of all 1275 corpus recordings at
shrinkage 0.5. It is applied to the enrolled comparison only. Whitening the
154 trained classes as well measures **+0.31 points at Wilcoxon p = 0.65** at
the shipped mixing weight, which does not justify moving the metric that the
blend weight, the temperature and every advertised accuracy were fitted
against — so the trained-class path is byte-identical with the file present
and absent, and `tests/test_enrollment.py` runs the served stage both ways to
prove it rather than reading the code.

Two properties of that transform are worth recording. Its shrinkage optimum
is interior rather than at a grid edge: prototype accuracy runs 0.804 at
shrinkage 0, peaks at 0.870 at 0.5, and returns to plain cosine's 0.838 as
the transform approaches the identity, which is the algebraic check the
construction requires. And it is fitted only from classes the encoder trained
on yet still improves classes it has never seen, so what it suppresses is a
property of the embedding space rather than of a class list.

**Added ragas abstain more, on purpose.** They pass one gate with the trained
classes — the softmax over cosine similarities at the shipped prototype
temperature 0.05, kept above 0.4161 (`scripts/enroll_abstain.py`, 1275
queries). It lets through **67.7%** of answers on added ragas against 80.6%
on trained ones, and the two are then **89.4%** and 90.3% accurate. The raw
cosine and the cosine margin were measured against the same 90% target and
both fail: they keep about three quarters of each group and are then four
points further apart in accuracy on them, which is a gate whose promise means
two different things depending on which kind of raga the user happens to have.

That threshold was fitted on the plain cosine, before the whitened metric
existed, and it is carried over unchanged rather than refitted — a second
constant for enrolled classes is a decision to take on purpose rather than a
quiet edit. `scripts/enroll_abstain_whitened.py` measures what the carry-over
does, on the same 1275 queries with only the metric changed: it lets through
**69.6%** of enrolled answers at **92.0%**, and 74.0% of all answers at 94.3%.
The threshold was chosen as the largest coverage still reaching 90% overall,
so on the whitened metric the carried-over rule under-promises rather than
over-promises — it answers slightly less often than the fit intended and is
four points more accurate when it does.

**Selection guidance, not silent filtering.** Keeping the recordings closest
to their own class mean scores 0.772 at three recordings against 0.753 for
five random ones; deliberately diverse ones are the worst strategy measured,
0.569 (`scripts/enroll_selection.py`, 375 queries). What sits far from a class
mean is more often a failed pitch track or a mislabelled recording than an
unusual rendition. The tab says so and filters nothing, because the rule also
discards genuinely unusual renditions and the person adding the raga is the
one who can tell them apart.

Every figure here is out-of-fold on corpus recordings. A recording found
elsewhere carries the found-audio penalty the rest of this system does, and
nothing measures the two apart.

- Added ragas live in a `gr.State`, so they are per-session, never written to
  disk and never visible to another visitor. `tests/test_enrollment.py` walks
  the app module for a shared container rather than trusting the wiring.
- Enrolled scoring always runs in the complete model's embedding space,
  whichever model the selector is on, because that is the model carrying
  prototypes. The trained answer on the page stays the selected model's own,
  and it stays on the page even when an added raga wins.
- Enrollment refuses to run at all if the whitener is missing from a
  deployment, rather than falling back to the 76.3% metric while the page
  quotes 80.0%.

## 2026-08-26 — the default model changes, and why the old one was wrong

The default is now the **complete** 154-raga model, replacing **broad**.

The previous default rested on one comparison: the 18-clip YouTube concert
set, where broad scores 67% against complete's 56%. A power analysis this
day found that set cannot resolve anything below roughly 56 points, and that
this particular comparison rests on four clips disagreeing — one gained,
three lost, **McNemar p = 0.63**. That is noise, and it was the sole evidence
for the previous default.

Both better-powered sources disagreed with it and were being overridden:

- grouped cross-validation, 1275 recordings: complete **84.4%** vs broad 82.8%
- fresh-YouTube probe, 67 recordings: complete **73.1%** vs broad 64.2%, six
  clips gained and none lost, **p = 0.031**

All 67 probe ragas are inside broad's class list, so this is a like-for-like
comparison rather than complete winning on ragas broad cannot name.

**The wider finding behind it.** The three held-out sets cannot validate
anything this project has measured. Simulated as paired changes, the smallest
effect detectable at 80% power is ~56 points on either 18-clip set, ~17 on the
probe, ~11 on all three pooled. The effects actually argued about are 0.5 to
2.5 points. The improve-or-hold ship rule therefore catches catastrophic
breakage and nothing finer — it has never validated a gain and by
construction cannot. Adoption decisions rest on the 1275-recording
out-of-fold matrix, where the power exists.

**The widest model loses its remaining justification.** It was kept because it
named ragas nothing else could reach. The complete model's 154 classes are a
superset of its 104, so that stopped being true when the complete model
shipped, and the About tab claimed otherwise until now. It stays selectable
for continuity and is recommended for nothing.

- The smart cascade's stages are now named explicitly rather than keyed off
  the default constant, which would have made it fall back from complete to
  complete and quietly do nothing.
- Three tests that used the default model as a stand-in for "the model with
  sequence-only classes" now name the broad model directly.

## 2026-08-25 — accuracy figures corrected for duplicate performances

An audit that fingerprinted the audio rather than comparing identifiers
found 26 pairs of recordings that are the same performance stored twice
under different names, 26 of them byte-identical after pitch extraction.
They arrive structurally: one video fetched under two composition-targeted
search queries lands in two per-query filenames, and a release present in
both source datasets enters twice. Every deduplication guard in the
project compared names, so none could see this.

49 of those recordings sit on opposite sides of a cross-validation fold
boundary, so each was scored against a training set holding its own twin,
with a nearest-neighbour member holding that twin at distance zero. All 49
were top-1 correct.

- Complete model: **85.0 / 92.6 → 84.4 / 92.2** out-of-fold.
- Concert model: 84.0 / 93.4 → 83.7 / 93.2.
- The broad and widest models carry the same contamination, but their
  stored out-of-fold dumps do not reproduce their published figures
  exactly, so they are marked rather than given an invented correction.
- Worst affected are the smallest classes, where up to 40% of a raga can
  be one performance counted twice — so the rare-raga per-class numbers
  the coverage claim leans on are the least trustworthy ones.

**No model changed. The correction is to the measurement.** The prototype
mixture adopted earlier the same day survives deduplication at +2.6 points
across ten folds of ten at p = 0.002, slightly larger than the +2.5 first
reported, because duplicates had inflated the baseline it was measured
against.

`scripts/audit_duplicate_recordings.py` reproduces the set from the audio,
and `tests/test_no_new_duplicates.py` pins it as a ratchet so the corpus
can lose duplicates but not gain them. The guard checks a pitch-class
profile as well as a hash: 26 of the 27 pairs are byte-identical, and a
hash-only version was verified blind to the twenty-seventh, which is the
same performance re-encoded.

Two claims about the held-out sets are corrected in the paper at the same
time. The 18-recording devotional holdout was described as the only fully
out-of-domain benchmark; 80 further recordings from that same private
collection do train every model, so it is song-disjoint but not
source-disjoint. And both 18-clip sets have served as the project's
ship/no-ship acceptance gates while also being quoted as independent
results, which biases them upward — at n=18 a single clip is 5.6 points.

## 2026-08-25 — model_v3_1: every raga gets a second opinion

The complete model's sequence stage now consults a class prototype
alongside its classifier. Each of the 154 ragas is represented by the
average of its recordings' learned embeddings, and a softmax over
similarity to those averages is mixed into the sequence stage before the
ensemble blend, at a weight and temperature fixed on a different model's
sweep rather than on the data they are judged against.

- Out-of-fold full-pipeline accuracy: 82.5/91.7 to **85.0/92.6**,
  +2.5 points of top-1, winning ten folds of ten (Wilcoxon p = 0.002).
  This is now the best cross-validated top-1 of the four models.
- More answers, not fewer: with the abstention constants untouched, this
  model answers 80.4% of out-of-fold recordings at 92.2% accuracy among
  the answers given, where the previous one answered 77.3% at 92.7%.

**Where the gain is, stated plainly, because it is not spread evenly.**
Split by how many recordings a raga has in the corpus, the change is
worth +12.8 points of top-1 for ragas with three or four recordings,
+5.0 for five or six, +1.0 for seven or eight, and +0.0 for thirteen or
more. Nothing measured got worse. So a well-known raga returns the same
answer as before and a rare melakarta returns a considerably better one.
A softmax head has to learn a decision boundary for each raga from that
raga's own examples, and four examples against 153 competitors do not
place one; an average needs no boundary.

**The held-out sets are unchanged, and that is expected.** The
solo-voice holdout stays at 83/89, the YouTube concert set at 56/67, and
the 67-recording fresh probe at 73 top-1 with zero paired changes in
either direction and one recording lost from top-3. The reason is
measurable rather than mysterious: the probe contains no raga with fewer
than nine recordings and is 82% drawn from ragas with thirteen or more,
against 44% for the corpus, because it was built by fresh web search and
web search returns the ragas people record. Restricted to that same
class-size profile, the out-of-fold gain is +0.0. No held-out set here
can see a change that helps the tail, which is a gap in the evaluation
suite rather than a doubt about the result.

- The ensemble stage, the abstention thresholds, the blend weight and
  the calibration temperature are all unchanged. The ONNX graph differs
  from model_v3_0's only by an added output exposing the pooled context
  vector, and the logits were verified bit-identical before the
  prototypes were attached.
- Three refinements were measured and rejected: a median or two- or
  three-centroid prototype instead of the mean (best +0.08, p = 0.95),
  dropping each class's least typical recordings before averaging, and
  giving rare classes a heavier prototype weight (+0.39, p = 0.31,
  directionally right and too small to adopt).
- model_v3_0 is retired from the shipped set, superseded by this model.

## 2026-08-24 — model_v3_0: the complete model learns from unlabeled audio

The complete model's sequence stage is replaced by one trained with two
rounds of noisy-student pseudo-labels drawn from roughly 670 hours of
unlabeled concert audio (about 250 full concerts fetched by generic
search, never reviewed, never labeled by hand). Each fold's pseudo-labels
come from a teacher that never saw that fold, so the cross-validated
comparison stays honest; iteration two cleared the pre-registered
adoption bar that iteration one missed (+2.2 points at the blend, CI
[+0.8, +3.6], Wilcoxon p = 0.012, 8 folds of 10). The same unlabeled
corpus had already failed to transfer twice as causal language-model
pretraining (+0.16 then +0.39, both p > 0.7), so the gain is attributable
to supervision injection, not to the data alone.

- Out-of-fold full-pipeline accuracy: 80.3/91.3 to **82.5/91.7**, now the
  strongest model except the concert-tuned one.
- On 67 freshly collected YouTube recordings none of this ever trained
  on: 65.7/85.1 to **73.1/85.1** — the found-audio gap narrowed by more
  than the cross-validation gain, consistent with the pseudo-corpus
  exposing the model to found-audio conditions.
- The two n=18 sets each moved one recording (holdout 89 to 83 top-1,
  YouTube 61 to 56), inside single-clip noise; top-3 held on both.
- Ensemble, thresholds, and calibration are unchanged: they are fitted on
  ensemble out-of-fold data the pseudo-labels never touched. Blend weight
  re-fitted on the new sequence out-of-fold matrix and kept at 0.30
  (inside the statistical plateau).

## Unreleased

No model changed and nothing was redeployed. A capacity idea was tested and
rejected, and the testing turned up a bug in how every previous model
comparison here was measured.

- **A bidirectional sequence model was evaluated over ten folds and not
  adopted.** At the shipped blend weight it is +1.4 points with a 95% interval
  of [-1.3, +4.2], winning 8 folds of 10 at Wilcoxon p = 0.15, against a bar
  fixed before the result existed of p < 0.05 and at least a point. Lowering
  the learning rate to stabilise it made it significantly *worse*, -1.6 points
  at the blend. Written up in full, traps included, in
  `docs/bidirectional_lstm_experiment.md`.
- **Both out-of-fold notebooks seeded once per session rather than once per
  fold.** `torch.manual_seed(42)` sat in the import cell, above the fold loop,
  so a fold's weight init depended on how many folds had already run in that
  session — and the twelve-hour session cap means the ten folds are split
  across sessions differently for every arm. Measured cost: the same fold,
  same recipe, scored 0.8100 run first and 0.7600 run second. Now seeded from
  the fold index inside the loop. The shipped forward-only matrix is
  deliberately not regenerated, because a new recipe would not make old and
  new folds comparable, only make them look it.
- **`scripts/compare_blend_arms.py`** compares two sequence models at the
  blend with the fold as the unit of analysis, at a weight fixed in advance,
  reporting a paired t, Wilcoxon and sign test with a confidence interval.
  It exists because the obvious test, McNemar over recordings, holds the two
  trained models fixed and cannot see the run-to-run variance above: it
  reported p = 0.0026 for a margin whose honest interval reached nearly to
  zero. `scripts/fit_v3_blend.py` gained `--dump-hits` to feed it.

## v5.1 (2026-07-31)

Correctness rather than capability. No model was retrained and no raga was
added; what changed is that several things the app asserted are now true, and
several things it could not previously claim now have a measurement behind
them.

**The concert model finally has an honest number, and it went up.** It was the
last of the three still quoting its ensemble's accuracy rather than the
pipeline's, because its blend weight had been fitted on fold 0 alone — the
fold its own sequence checkpoint early-stopped against, so the sequence model
was scored on a selected maximum while the ensemble was scored out-of-fold.
Running all ten folds settled it.

- The honest fit picks the same `w = 0.35` the fold-0 fit did, so the shipped
  weight was never biased; the temperature moves only from 0.523 to 0.538.
- The full pipeline measures **84.0 / 93.4** against the ensemble's
  82.3 / 91.7. The sequence stage is worth 1.7 points of top-1 here, and the
  model had been understating itself.
- The weight sits in a wide plateau: every value from 0.20 to 1.00 is
  statistically indistinguishable from the peak under McNemar, 17 of 21 grid
  points. That is the honest reason not to tune it further.
- All three models now quote a full-pipeline number fitted on a complete
  ten-fold out-of-fold run. None of the three quotes an ensemble-only figure
  as a conservative floor any more, because none of them has to.
- **The concert model's per-class recall was backfilled too.** v5 left it out
  because its OOF row order had been lost when its splits file was extended
  past the saved probabilities. `scripts/recover_oof_order.py` recovers that
  order from the probabilities themselves — the assignment that makes the
  saved rows agree with the labels — rather than assuming it from a splits
  file that has since moved. All three models now carry
  `stratified.per_class`, and none of the concert model's 71 classes is dead.

**Twelve raga cards were wrong, and three collection gates with them.** Every
one of the 104 cards was checked against public references.

- 59 fields corrected across the 104 cards, including twelve scales that no
  source supports. Kāpi's arohana, Mārgahindōḷaṁ's parent mela and both its
  scales, Vasantā's dhaivata, Janaranjani's vakra ascent, Cittaranjani's
  nishadantya ending and Pāḍi's descent were all wrong.
- Every card now carries the reference its ārōhaṇa and avarōhaṇa came from,
  rendered as a link, and a test requires the field.
- Six composition attributions were corrected. Twelve cards now list no
  composition at all, which is the honest state: a guessed composer credit is
  the single item on a card a listener is least able to check.
- Three of the errors were **functional, not cosmetic**, because the same
  scale drives a collection gate. The gate does not only accept or reject a
  recording, it picks the tonic that maximises scale fit and stores every
  feature relative to that choice, so a wrong scale silently renormalises
  the recordings it keeps. Sencuruṭṭi's gate simply followed its corrected
  card. Vasantā and Pāḍi were disputed, and were adjudicated against the
  project's own collected audio rather than against books, because widening
  a gate until curated recordings pass can detect a set that is too narrow
  and can never detect one that is wrong.

**A sequence model could be served for the wrong ensemble.** The per-artifact
component cache was keyed on `id(artifact)`, which is a memory address and is
reused as soon as the object it belonged to is collected. With three models
loaded and unloaded, a cache hit could return another model's sequence
component. Now keyed on the artifact's name and class tuple, with a test that
demonstrates the collision.

**The best-distance rule measured the farthest reference.** A Bhattacharyya
distance is `-log(bc)`, and `-np.log(bc).min()` reduces before the minus
applies, so it returns `-log(min bc)` — the largest distance, where the
docstring promises the smallest. Present since v1 in
`ModelArtifact.knn_best_distance` and in the evidence loop that scores the
`dist` tonic-hypothesis rule. Nothing shipped changes: no artifact carries a
`rotation_rule` at all, so no model ever selected the rule this feeds. What the
bug did was hand the tuner a wrong number whenever it compared that rule
against the others, which is a comparison it then always lost.

**The fresh-YouTube probe was held out by accident; it is now a decision.**
The 67 batch-6 recordings that make the paired source-gap control possible
sat outside the corpus only because the splits file was frozen before they
were collected. The next routine `extend_splits.py` run would have absorbed
all 67 and printed nothing about it, ending a measurement that cannot be
retaken. They are now listed, guarded, and absorbable only behind an explicit
flag.

**Publication readiness.** An audit of everything in the repository for
privacy and for audience:

- No absolute path to a development machine remains. The private solo-voice
  set is located through environment variables.
- What the Space publishes is now an **allow-list** rather than a list of
  exclusions, and what it withdraws is computed by diffing the live Space
  against that list rather than remembered. A deny-list is only as complete as
  its last edit.
- Comments and docstrings were rewritten for a reader: no first person, no
  phrasing that addresses the author. Where a comment recounts a past failure
  it stays, because the failure is the reason the code is shaped the way it
  is, and deleting it invites the same change back.
- `scripts/README.md` indexes the 51 scripts and groups the thirteen kept only
  for a measured verdict under nine directions, one of which (per-swara gamaka)
  shipped. Three duplicate packaging scripts and three unreachable model
  artifacts were deleted, and the Colab twin of the out-of-fold notebook was
  repurposed for the concert corpus.

## v5 (2026-07-29)

**The widest model retrained on clean splits, with a paired sequence model
(`model_v2_7`, replacing `model_v2_6`).** The round-5 splits had been produced
by extending the round-4 folds, which left them lopsided (outer folds ranged
from 55 to 172 recordings). The 986-recording corpus was re-split from
scratch — folds of 98–100, no orphaned or starving classes — and everything
retrained on that.

- Ensemble, 104 classes / 986 recordings: grouped CV **77.1 / 88.2**, coverage
  at the 90% confidence bar 65.8% — against 76.3 / 88.5 and 63.6% from the
  lopsided splits.
- A 104-class LSTM now pairs with it (fold-0 validation top-1 0.828), the
  first checkpoint trained after the worker-RNG fix, so it is also the first
  to see full augmentation diversity.
- **The ten-fold out-of-fold sequence run is complete** (~20 GPU-hours across
  Colab and Kaggle sessions; every fold's training passed the divergence
  guard). LSTM alone, out-of-fold over all 986 recordings: **75.5 / 88.0**.
  The blend weight refit on that matrix moved from the provisional 0.50 to
  **w = 0.45** (plateau rule, peak at 0.40), and the full pipeline's honest
  number — what the app now quotes for this model — is **79.4 / 90.5**,
  against the ensemble's 77.1 / 88.2 alone.
- Real sets (n=18 each): holdout **88.9 / 88.9**, unchanged. YouTube
  **55.6 / 66.7** against v2_6's 44.4 / 72.2 — two clips gained at top-1, one
  lost at top-3. At n=18 each move is single-clip noise; the model ships on
  the cleaner splits, the 12 extra recordings and the honestly-fitted sequence
  stage, not on that row.
- The same three classes stay dead (Puṇṇāgavarāḷi 0 of 3, Janaranjani 0 of 4,
  Śuddha Sāvēri 0 of 4 at top-3), kept listed with their measured fractions.
  The sequence stage was their most plausible route, and the out-of-fold run
  closed it: the LSTM also scores 0 of n at top-3 on all three.

**A third model: widest coverage, 104 ragas.** Round 5 grew the corpus to 974
recordings across 104 classes. The result ships as a *third* selectable model
rather than a replacement, because on measurement it is not a better model,
only a wider one.

- Widest model (`model_v2_6`), ensemble only, 104 classes / 974 recordings:
  grouped CV **76.3 / 88.5**, coverage at the 90% bar 63.6%. Against the broad
  model's 79.4 / 90.1 at 74.4%, that is a clear step down.
- Real sets (n=18 each): holdout **88.9 / 88.9**, identical to the broad
  model, so nothing was lost on clean solo voice. YouTube **44.4 / 72.2**
  against the broad model's 66.7 / 77.8 — a 22-point top-1 drop on the audio
  most like a real upload. Each figure is what that model actually serves: this
  one has no sequence stage, the broad model's number includes its own. That
  number is why it is not the default.
- No paired LSTM: the 104-class sequence model needs a training-corpus upload
  that has not happened, so this model runs the numpy ensemble alone.
- **Three classes are dead**: Puṇṇāgavarāḷi (0 of 3), Janaranjani (0 of 4) and
  Śuddha Sāvēri (0 of 4) never reached the top-3. Not a data fault — their
  pitch tracks carry 139–523 s of voiced melody at plausible tonics. Their
  recordings scatter to unrelated ragas rather than to a scale twin, and
  Cittaranjani scores 2 of 3 while sharing Karaharapriya's scale, so scale
  collision alone does not explain it.
- Śuddha Sāvēri is a **regression with a clean cause**. It identifies by note
  order inside a scale it shares with a far larger class, which is why it was
  an LSTM-only retry class by design. Graduation to full ensemble class is
  gated on recording quota alone; round 5 crossed that quota, which both moved
  it into an ensemble that cannot represent it and removed it from the retry
  list the sequence model reads. Five of the six candidates graduated fine
  (top-3 0.60–0.75), so the rule is not wrong in general, only blind to
  whether the ensemble can express the class it promotes.
- **Per-class OOF recall is now written into the artifact**
  (`stratified.per_class`) and every raga list renders it: a class measured at
  top-3 0 is labelled with its raw fraction instead of appearing as
  well-supported as any other. Backfilled for the broad model, which has no
  dead classes. The concert model got none at the time: its OOF row order had
  been lost when its splits file was extended past the saved probabilities, so
  the eval asserted rather than publishing numbers against the wrong
  recordings. Recovered later; see v5.1.
- **The raga lists now show sequence-only classes.** They rendered
  `artifact.classes`, but inference blends over a *union* class space, so the
  broad model could return four ragas it never listed (Māṇḍ, Naṭabhairavi,
  Sālaga bhairavi, Śuddha Sāvēri). Understating coverage was actively harmful
  here: a reader looking for Śuddha Sāvēri, not finding it, would switch to
  the widest model — the one model measured at 0 for it. They are now listed
  and marked experimental, and `tests/test_advertised_coverage.py` fails if
  anything the pipeline can return goes unlisted.

**A per-swara gamaka member, and an 87-raga corpus.** Not deployed: the
paired LSTM still has to be retrained on the new class set before the two
halves can ship together.

- **New third ensemble member: per-swara gamaka.** The PCD is time-averaged
  and the TDMS pairs notes at a fixed 0.2 s lag, so both are blind to how
  the pitch *moves*. The new descriptor measures, separately for each of the
  12 semitone positions, the pitch spread around it and the mean absolute
  pitch velocity while the melody sits near it. 24 dimensions, pure numpy,
  computed from the f0 contour that is already extracted.
- Pooling those same quantities over a whole recording (the first attempt)
  is near-useless: top-1 0.075 alone, and a blend gain inside noise. Pooled
  ornament statistics track the performer and the tempo, not the raga.
  Conditioning on the swara is what makes them work: 0.615 alone, the
  figure the shipped artifact records under `oof_scores.gamaka`.
- Ablation: the velocity half carries the signal (0.594 alone); the spread
  half is largely redundant with the PCD.
- Fitted blend weights are kNN 0.35 / logreg 0.25 / **gamaka 0.40**, so the
  new member takes the largest share of the three.
- Broad model, ensemble only, 87 classes / 855 recordings: grouped CV
  **77.8 / 89.4 to 79.4 / 90.1**, and coverage at the 90% covered-accuracy
  bar **60.6% to 74.4%** — the system abstains far less often at the same
  quality bar. Calibration: temperature 0.622, uncertain top-1 0.47.
- Real sets, ensemble only (n=18 each): holdout unchanged at 88.9 / 88.9;
  YouTube top-1 55.6 to 66.7 (+2 recordings), top-3 77.8 to 72.2 (-1, noise).
- The member is optional and self-describing: it is used only when the
  artifact carries `gamaka_W`, and its descriptor is versioned inside the
  artifact's own meta block rather than in the global feature-config hash,
  so older artifacts stay valid and the two selectable models can differ.
- Rotation equivariance verified exact against recomputation on a
  tonic-shifted contour at ±700 and ±500 cents.
- Corpus grown to 855 recordings / 87 classes (round 4). The solo-voice
  holdout still never enters training; the packaging assertion is unchanged.

**Measured and not shipped** (all on grouped OOF plus both real sets):
contrastive embedding with a prototype head; a targeted allied-cluster
resolver; and a learned global metric, which fixes the allied pairs it
targets but breaks the sparse-class tail. Also a phrase/motif note-order
model, which *beats* the histogram ensemble alone (0.801 to 0.831) and so
confirms note order is the missing information, but loses to the LSTM that
already captures it (fold 0: ens+LSTM 0.852 vs ens+phrase 0.795) and adds
nothing on top of it. See `docs/phrase_model_experiment.md`.

## v4 (2026-07-24) — live

**Two selectable models.** The app now ships the v3 model (71 ragas,
concert-tuned) alongside a new broad model (84 ragas), chosen with a Model
selector. The default is the broad model; the About tab explains which to pick.
Each model carries its own paired LSTM and blend calibration, so the two stay
fully independent.

- New **broad model** = the v2.4 ensemble (835 recordings, 84 ragas, +13 over
  v3) blended with a fresh 90-class LSTM (v10). Grouped CV 80.1% / 90.3%.
- Real-world trade-off, measured and documented rather than hidden:
  - Solo-voice holdout **83.3% -> 88.9%** top-1 (top-3 held at 88.9%).
  - YouTube concerts 77.8% -> 61.1% top-1, **top-3 held at 77.8%**. Adding
    ragas spreads mass across more allied candidates, so the right answer slips
    within the top-3 on noisy concert audio more often. The concert-tuned model
    stays available for the sharper top-1 on those clips.
- The 84-raga corpus came from cross-source assembly of Saraga-tail ragas (two
  reference recordings plus a verified concert recording each) and ~23 free
  recordings recovered by normalizing Saraga spelling variants.
- Six ragas cut from earlier ensembles return in the broad model as
  experimental LSTM-only classes; each ships only where the sequence model
  demonstrably identifies it on held-out data. Only one (Karnataka
  devagandhari) validated so far; the rest are kept but flagged experimental.
- Short single-section recordings now also consult the LSTM, but only when its
  own analysis windows agree (the within-model analog of section corroboration);
  ungated blending was measured to help nothing and cost a holdout item.

## v3 (2026-07-23)

**Phrase-aware LSTM joins the ensemble.** A DeepSRGM-style sequence model
(5-cent pitch tokens, LSTM width 768, attention pooling), trained on the
full 71-class corpus with grouped folds, now refines the final answer for
long recordings. Its opinion is blended once per recording, after the
section-corroboration step, with weight 0.35 and temperature 0.52 fit on
the LSTM's fold-0 validation recordings only.

- YouTube: 61.1% / 77.8% to **77.8% / 77.8%**. The three recovered items
  are exactly the allied-raga misses introduced by class growth.
- Holdout: **83.3% / 88.9%**, unchanged.
- Short single-section recordings stay pure-ensemble: blending them was
  measured to add no wins and cost one holdout top-3.
- Training required gradient clipping (1.0); without it the run diverges
  after epoch ~13 (peak 81.4%, collapse to 22%).

## v2.3 (2026-07-22)

**71 ragas, 756 recordings.** Second expansion round via the
weak-supervision recipe (composition-targeted search, scale-fit gate,
at least 3 verified recordings per class, out-of-fold sanity cut).

- Grouped CV 82.3 / 91.7; the original 580-recording core held at
  86.6 / 94.8.
- YouTube 61.1 / 77.8 (top-1 diluted by new allied classes, top-3 held;
  recovered in v3).
- Holdout benchmark established: 83.3 / 88.9.
- Cut before shipping (0 out-of-fold hits): Natabhairavi (parent scale
  swamped by its own janyas), Maand and Shuddha Saveri (note-order /
  pentatonic identity that distribution features cannot represent).
- Added RAGA_TRACKER.md (coverage ledger) and public API docs
  (`gradio_client`, endpoint `/identify`).

## v2.2 (2026-07-22, internal only)

55 classes, 692 recordings. First round of demand-driven class growth and
first use of the private solo-voice training split. Validated the recipe
(holdout jumped from 63.6% to 88.9% on in-set items) but was superseded by
v2.3 within the day and never deployed.

## v2 (2026-07-20)

**42 ragas, 580 recordings.** Added Saraga 1.5 Carnatic recordings as
extra training and two new classes (Jonpuri, Saurashtram). Grouped CV
86.4 / 94.7, core-40 preserved. YouTube 71.4 / 79.

Model selection may prefer a partner the pure-numpy artifact cannot
carry, so the ensemble weight is now refitted for the exportable pair
and the reported accuracy is that pair's. v1 reported the mixture it
selected rather than the one it shipped.

## v1.1 (2026-07-20)

**The wild-audio release.** No training changes; serving fixes only,
after a 17-recording YouTube benchmark showed 57% top-1 against 87% CV.

- Tonic is now chosen before classification: detector consensus across
  sections plus a Sa-plausibility veto (99.8% keep-correct on the
  training corpus). The old scheme (classifier picks its favorite tonic
  rotation) was the main source of confident wrong answers and is gone.
- Long recordings are analyzed as four independent 120-second sections
  merged by corroboration; a lone confident section is treated as
  contamination and forced to "uncertain".
- Result: YouTube 57% to 71% top-1.

## v1 (2026-07-07)

Initial release on Hugging Face Spaces. 40 ragas, 480 recordings
(CompMusic features dataset). kNN on TDMS surfaces plus logistic
regression on pitch-class distributions, temperature-calibrated with
abstention thresholds. Grouped CV 87.3 / 96.7 -- but measured on the
model-selection mixture, which paired kNN with gradient boosting; the
pure-numpy artifact could only export logistic regression in its place, so
the shipped model was never the one scored. Its kNN member alone scores
85.2. Fixed at v2, where the weight is refitted for the exportable pair
before anything is written out.
