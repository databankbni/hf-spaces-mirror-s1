# Raga coverage tracker

Living document, updated every expansion round. It records what the models can
name, what was tried and cut, and what is queued next.

Four models ship, all user-selectable in the app, plus a cascade that
routes between two of them. Adding ragas is a genuine trade-off rather
than a free win, so rather than pick one point on it, every point is
offered:

| | Concert-tuned | Broad | Widest | Complete (default) |
|---|---|---|---|---|
| ensemble classes | 71 | 87 | 104 | 154 |
| sequence-model classes | 71 | 90 | 104 | 154 |
| corpus | 756 recordings | 855 | 986 | 1275 |
| melakartas among its classes | 14 / 72 | 14 / 72 | 22 / 72 | **72 / 72** |
| out-of-fold top-1 / top-3, full pipeline | 83.7 / **93.2** | 82.8 / 92.0† | 80.7 / 90.8† | **84.4** / 92.2 |
| real-world concerts (18 in-set YouTube) | **78 / 78** | 67 / **78** | 56 / 67 | 56 / 67 |
| solo-voice holdout (18, never trained) | 83 / 89 | **89 / 89** | **89 / 89** | 83 / 89 |
| fresh-YouTube probe (67, never trained) | — | 64 / 81 | — | **73 / 84** |
| artifact | `model_v2_3` | `model_v2_4` | `model_v2_7` | `model_v3_1` |

† The full-pipeline row is corrected for duplicate performances: 26 pairs of
recordings turned out to be the same performance under two identifiers, and
49 of them sat on opposite sides of a fold boundary, so each was scored
against a training set holding its own twin. All 49 were top-1 correct. The
concert and complete columns are exactly recomputable and are shown
corrected; the other two models' stored dumps do not reproduce their
published figures, so their uncorrected numbers stand with this mark rather
than an invented correction. See the README for the full account and
`scripts/audit_duplicate_recordings.py` to reproduce it.

The widest model adds 17 classes over the broad one. It used to be the only
route to 13 of them; the complete model's 154 classes are a superset of its
104, so since the complete model shipped there is no raga only the widest can
answer, and it is kept selectable for continuity rather than recommended. It
loses to the complete model on every axis measured, and the app says so at
the selector.

The complete model reached all 72 melakartas in August 2026 (batch 8, three
title-verified recordings per new class) and gained its current sequence
stage on 2026-08-24 from two rounds of noisy-student training on about 670
hours of unlabeled concert audio -- the first accuracy change to clear the
pre-registered adoption bar since seed selection.

On 2026-08-25 it gained a class-prototype mixture: every raga is also
represented by the average of its recordings' learned embeddings, and a
match against those averages is mixed into the sequence stage. Worth +2.5
points of out-of-fold top-1 across all ten folds (Wilcoxon p = 0.002),
which is what moves this column to the best cross-validated top-1 of the
four.

That gain lives almost entirely in the tail, and the table above cannot
show it. Split by how many recordings a raga has, the change is worth
+12.8 points for ragas with three or four, +5.0 for five or six, +1.0 for
seven or eight, and +0.0 for thirteen or more. The three held-out rows are
unchanged because none of those sets contains a single raga from the bands
where the effect lives -- the fresh-YouTube probe, for instance, is 82%
drawn from ragas with thirteen or more recordings and contains none below
nine. The probe's top-3 moved by one recording of 67, which is noise.

The practical reading for anyone choosing a model: if the raga is common,
this changed nothing; if it is one of the rare melakartas, it changed a
great deal. There is currently no held-out set that can demonstrate the
second half of that sentence, which is a gap in the evaluation rather than
a doubt about the measurement.

## Summary

| | count |
|---|---|
| **Ragas nameable (complete model)** | **154** |
| Ragas nameable (broad model) | 87 ensemble + 4 sequence-only (91 in all) |
| Melakarta (parent) ragas covered | **72 / 72** |
| Active concert repertoire (est. 300–400 ragas¹) | ~40–50% covered |
| Classes shipped with a measured 0-of-n top-3 | 4 (listed below, not hidden) |
| Raga cards, all with a scale reference | 154 |

¹ Roughly 300–400 ragas are commonly taught and performed today; the 72
melakartas are the canonical parent scales, and janya ragas are theoretically
unbounded. Coverage here skews heavily toward the most-performed ragas, so the
share of what a listener actually encounters is considerably higher than the
raw percentage suggests.

## Melakarta checklist (22 / 72)

6 Tanarūpi, 8 Tōḍi (Hanumatōḍi), 10 Nāṭakapriya, 14 Vakuḷābharaṇaṁ,
15 Māyāmāḷavagauḷa, 16 Chakravākaṁ, 20 Naṭabhairavi, 21 Kīravāṇi,
22 Karaharapriya, 26 Cārukēśi, 28 Harikāmbhōji, 29 Śankarābharaṇaṁ,
34 Vāgadīśvari, 45 Śubhapantuvarāḷi, 51 Kāmavardani (Pantuvarāḷi),
56 Ṣanmukhapriya, 57 Simhēndramadhyamaṁ, 63 Latāngi, 64 Vācaspati,
65 Kalyāṇi (Mēcakalyāṇi), 67 Sucaritra, 72 Rasikapriya.

Eight of those arrived with the widest model, which is most of what the extra
17 classes bought. Varāḷi is a janya of 39 Jhālavarāḷi as performed and is not
counted here, though older versions of this file counted it.

Most of the remaining 50 melas are rarely performed as ragas in their own
right and matter mainly as parents. The higher-value uncovered ones are
27 Sarasāngi, 36 Calanāṭa, 58 Hemavati and 59 Dharmavati.

## What the widest model added (17)

Cittaranjani, Gaṁbhīra nāṭa, Janaranjani, Kēdāraṁ, Latāngi, Mandāri, Māṇḍ,
Naṭabhairavi, Nāṭakapriya, Puṇṇāgavarāḷi, Rasikapriya, Sucaritra,
Sālaga bhairavi, Tanarūpi, Vakuḷābharaṇaṁ, Vāgadīśvari, Śuddha Sāvēri.

Four of them (Māṇḍ, Naṭabhairavi, Sālaga bhairavi, Śuddha Sāvēri) had been cut
from an earlier ensemble and carried only by the sequence model; crossing the
recording quota promoted them into the ensemble.

## Classes shipped with a measured zero

Three classes in the widest model never reached the top-3 in cross-validation:
**Puṇṇāgavarāḷi**, **Janaranjani** and **Śuddha Sāvēri**. They are listed in
the app with their measured 0-of-n rather than dropped, so the raga list stays
complete and the reader is told which entries not to trust.

Śuddha Sāvēri is a regression specifically. It identifies by note order within
a scale it shares with a much larger class, which is why it was previously
reachable only through the broad model's sequence stage; crossing the quota
promoted it into an ensemble that cannot represent it. The sequence stage is
not much better, putting it in the top-3 for 1 of 5 recordings.

The broad model's four sequence-only classes were measured the same way,
having shipped since v4 on the assumption that the sequence model could name
them. It can name one: **Māṇḍ**, top-1 correct in 3 of 6. **Naṭabhairavi**,
**Sālaga bhairavi** and **Śuddha Sāvēri** are top-1 correct in 1 of 11 between
them, that one being a Śuddha Sāvēri recording; three reach the top-3, two of
them Sālaga bhairavi. They stay listed with those numbers for the same reason.

## Expansion history

**v1/v2 core (42).** The CompMusic 40-raga dataset plus Saraga additions.

**v2.2, batch 1 (+13).** Demand-driven, from failures observed in the private
and YouTube evaluations: Abheri, Bauli, Brindāvana Sāranga, Cārukēśi,
Hamsadhwani, Hamsanandi, Hindōḷaṁ, Kīravāṇi, Madhuvanti, Rēvati, Vaḷaji,
Śivaranjani, and Naṭabhairavi, which was cut at 0/3 out-of-fold.

**v2.3, batch 2 (+17).** Demand plus popularity: Amṛtavarṣiṇi, Bahudāri,
Chakravākaṁ, Darbāri Kānaḍā, Desh, Kadanakutūhalaṁ, Nalinakānti, Ranjani,
Simhēndramadhyamaṁ, Sāramati, Tilang, Vasantā, Vācaspati, Yamunā Kaḷyāṇi,
Ābhōgi, Śubhapantuvarāḷi, Śuddha Dhanyāsi. Māṇḍ and Śuddha Sāvēri were
attempted and cut.

**v2.4, round 3 (+13 kept of 16).** Cross-source assembly from the Saraga
tail: each class is two Saraga reference recordings plus at least one verified
YouTube recording, using cross-source quota pooling. Kept after the
out-of-fold gate: Bāgēśrī, Hamīr kaḷyaṇi, Kalgaḍa, Kumudakriyā,
Kuntalavarāḷi, Lalita, Maṇirangu, Mārgahindōḷaṁ, Nādanāmakriya, Nīlāṁbari,
Pāḍi, Pūrṇacandrika, Sāranga. Roughly 23 further recordings were merged by
normalising Saraga spellings. Scale gates for this round were derived
empirically from the Saraga reference recordings rather than from theory,
because gamaka smear makes real recordings broader than canon. The first
instrumental recordings were admitted here, since melody features are
instrument-agnostic.

Cut by that round's gate at 0 top-3: Jaganmōhini, Karṇāṭaka dēvagāndhāri,
Sālaga bhairavi. All three have verified labels.

**Round 4 (+3, reaching 87).** Dvijāvanti, Jaganmōhini and Karṇāṭaka
dēvagāndhāri crossed quota and graduated into the ensemble, the last two having
been cut by the previous round's gate.

**Round 5 (+17, reaching 104).** Chiefly melakartas absent from the
repertoire-driven rounds, which is why the mela count moved by eight at once,
plus the four sequence-only classes crossing quota.

### Kēdāraṁ, a class lost to two silent problems

Kēdāraṁ already had its three recordings; two independent problems hid them.

1. **Spelling.** Saraga spells it `Kedāraṁ`, the YouTube fetch spelled it
   `Kēdāraṁ`. The quota counted 1 and 1 instead of 2, so the class never
   reached 3. Fixed by a `SARAGA_NORM` entry; the long-e form is canonical
   because the corpus already spells its sibling `Kēdāragauḷa`.
2. **An unreviewed gate flag.** `Ananda Natana Prakasam`, Dikshitar's
   canonical Kēdāraṁ kriti, scored 0.80 against an `IN_SCALE_MIN` of 0.82 and
   was auto-rejected without ever reaching review.

The override is evidence-backed rather than title-backed. All three recordings
show the same profile — S, G3, P, R2, N3, M1 with dhaivata absent, exactly
Kēdāraṁ's note set — the out-of-scale mass is R1 and G2 smear off a heavily
oscillated gandhara, and Saraga's own ground-truth Kēdāraṁ recording scores
0.767 on the same gate, below the recording the gate rejected. The threshold
sits under what this raga's ornamentation permits, which is the bias
`review_newraga.py` exists to correct.

An audit for the same failure across the whole candidate pool found
`Kedāraṁ`/`Kēdāraṁ` to be the only spelling collision, and Kēdāraṁ the only
near-miss class recoverable without new recordings. Every other under-quota
raga sits at one counted recording with nothing blocked: those need data, not
fixes.

## Scale corrections

All 104 raga cards were checked against public references. Twelve carried a
scale no source supports, and 59 fields in total were corrected. Every card
now names the reference its ārōhaṇa and avarōhaṇa came from, and a test
requires that field to exist.

Two of those errors were functional rather than cosmetic. The collection gate
in `scripts/extract_newraga.py` does not only accept or reject a recording: it
picks the tonic that maximises scale fit, then stores every feature relative
to that choice. A wrong scale therefore silently renormalises the features of
the recordings it keeps. Widening a gate until curated recordings pass detects
a set that is too narrow and cannot detect one that is wrong, because a
wrong-and-wide set passes everything. Vasantā and Pāḍi were corrected against
the project's own collected audio, not against books alone.

## Cut once, and what became of them

Nothing here was abandoned: a class cut by an out-of-fold gate is cut for want
of recordings, so the entry stays open and the gate is re-run once the corpus
grows. Every raga below has since come back.

- **Jaganmōhini** and **Karṇāṭaka dēvagāndhāri**: cut at 0 top-3 by the v2.4
  gate, swamped by the mela-15 family and the Abheri/Karaharapriya crowd
  respectively. Both crossed quota in round 4 and are now ensemble classes in
  the default and widest models. In the default they measure top-3 0.50 (n=6)
  and 0.80 (n=5); the widest model sees Jaganmōhini more often and does better
  on it, 0.78 (n=9).
- **Māṇḍ**, **Naṭabhairavi**, **Sālaga bhairavi**, **Śuddha Sāvēri**: cut from
  an earlier ensemble, carried by the sequence model, now full classes in the
  widest model. Their measured accuracy is above.

## Out of scope

Out-of-set singles in the private collection are kept as honesty
evaluation items rather than classes: Jog, Jogkauns, Chandrakauns,
Marubihag, Bhagyashree, Saraswati and Janjooti (Jhinjhoti), all
Hindustani; plus one Sarasāngi recording, which is Carnatic (mela 27) and
simply under quota.

## Rules of the game

- A raga becomes a class only with **at least three verified recordings**
  across the CompMusic set, Saraga, the private solo-voice training split and
  YouTube. Labels are verified by the scale-fit gate plus a composition
  identity review, and the review overrides the gate, which is biased against
  pentatonic and bhashanga ragas.
- The **private holdout split (18 recordings) never trains.** It is the
  permanent solo-voice benchmark, and the exclusion is asserted in the
  packaging script rather than promised.
- Crossing the recording quota is **not sufficient** to ship a class. A quota
  is a statement about data volume; whether the features can represent the
  raga is a separate question, and the out-of-fold measurement is what answers
  it. Classes that measure zero are shipped only with that number attached.
- Fold assignments are **extended, never regenerated** (`extend_splits.py`),
  so a sequence model's validation set stays valid for the blend fit.
