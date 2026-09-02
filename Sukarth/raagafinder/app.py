"""RaagaFinder — Carnatic raga identification. Gradio entry point (HF Spaces)."""

import html
import json
import subprocess
import tempfile
import traceback
from pathlib import Path

import gradio as gr

from raagafinder.config import (
    ARTIFACTS_DIR,
    ASSETS_DIR,
    MULTISEG_ABOVE_S,
    SEGMENT_POSITIONS,
    SEGMENT_S,
)
from raagafinder.inference.enroll import (
    MAX_ENROLL_RECORDINGS,
    MIN_ENROLL_RECORDINGS,
    EnrolledRaga,
    build_prototype,
    embed_sections,
    exposes_embedding,
    load_whitener,
    recording_embedding,
    score_query,
)
from raagafinder.inference.pipeline import analyze_segments
from raagafinder.models.artifact import ModelArtifact
from raagafinder.ui.plots import pcd_overlay_figure
from raagafinder.ui.raga_info import (
    card_html,
    chips_html,
    confidence_bar_html,
    load_metadata,
    non_curated_note,
    stratified_md,
)

# Four shipped models, user-selectable: one coverage/accuracy ladder. Adding
# ragas necessarily dilutes per-raga top-1 (more look-alikes compete), so four
# points on that trade-off ship rather than one chosen for everyone -- each
# model's raga count and measured accuracy are shown right at the selector.
#
# `complete` is the default as of 2026-08-26, replacing `broad`.
#
# It was NOT the default before, on the strength of the 18-clip concert set,
# where broad answers 67% correctly against complete's 56%. A power analysis
# on 2026-08-26 showed that set cannot resolve anything below about 56 points
# and that the comparison rests on four clips disagreeing, one gained and
# three lost, McNemar p = 0.625. That is noise, and it was the sole evidence
# for the previous default.
#
# The two better-powered sources both favour `complete`, and they were being
# overridden:
#   corpus out-of-fold, n=1275   complete 0.8442 vs broad 0.8280
#   fresh-YouTube probe, n=67    complete 0.7313 vs broad 0.6418,
#                                six clips gained and none lost, p = 0.031
# All 67 probe ragas are inside broad's class list, so this is not complete
# winning on ragas broad cannot name; it is a like-for-like comparison on the
# largest held-out set, and the only statistically real one of the three.
#
# The coverage-dilution argument for a narrower default still holds in
# principle -- more classes do mean more look-alikes competing -- and the
# ladder still ships so a user who wants the narrower model can pick it. What
# does not hold is the specific claim that swapping is a regression for the
# majority. That claim was measured on a set too small to support it.
#
# `complete` covers the whole melakarta system: its 154 classes include all
# 72 parent scales. Since 2026-08-24 it is also the strongest model on
# out-of-fold accuracy, after a second round of noisy-student training on
# about 670 hours of unlabeled concert audio cleared the project's
# pre-registered adoption bar (+2.2 points at the blend, Wilcoxon p = 0.012).
#
# On 2026-08-25 its sequence stage gained a class-prototype mixture, taking
# it to 85.0/92.6 blended (+2.5 top-1, ten folds of ten, Wilcoxon p = 0.002).
# That gain is not spread evenly and the honest version of the claim says so:
# it is +12.8 points on classes with three or four recordings and +0.0 on
# classes with thirteen or more, so a well-known raga returns the same answer
# as before and the rare melakartas return a much better one. Those rare
# classes still rest on three or four YouTube recordings each, so their
# per-class numbers remain thin by construction.
#
# All four models carry a paired LSTM (models_artifacts/*.lstm.json); the
# inference pipeline loads it with load_if_present and runs the numpy
# ensemble alone when a model ships without one.
MODEL_FILES = {"broad": "model_v2_4", "concert": "model_v2_3",
               "widest": "model_v2_7", "complete": "model_v3_1"}
DEFAULT_MODEL = "complete"
# The cascade's two stages, independent of whichever model is default.
SMART_FIRST, SMART_FALLBACK = "broad", "complete"
ARTIFACTS = {k: ModelArtifact.load(ARTIFACTS_DIR / fn) for k, fn in MODEL_FILES.items()}
_KIND = {"broad": "Broad coverage", "concert": "Concert-tuned",
         "widest": "Widest coverage", "complete": "All melakartas"}
_BLURB = {
    "broad": "fewer ragas competing · strong on clean solo voice",
    "concert": "sharper single top-1 on full concert recordings",
    "widest": "most ragas at useful accuracy",
    "complete": "recommended · all 72 melakartas · best measured accuracy",
}


def _metrics(key):
    """Headline accuracy for a model: what it serves, not what part of it does.

    `metrics.ensemble` is the numpy ensemble's own grouped CV. For all four
    models that is not the system: a sequence stage is blended in at
    inference, and the blend scores two to six points of top-1 above the
    ensemble alone (1.7 concert, 2.0 broad, 2.3 widest, 6.0 complete).
    Quoting the ensemble understates the app, which is not the safe
    direction -- the same lesson the raga lists taught when they listed
    fewer ragas than the pipeline could return.

    So prefer the blend's measured accuracy, and only when it was measured
    honestly: a COMPLETE out-of-fold fit. A fold-0 fit scores the LSTM on the
    fold its own early stopping selected, which is optimistic by construction,
    and a partial merge scores it on whichever folds happened to land. Both
    would raise the advertised number without raising the accuracy, so both
    fall back to the ensemble's figure. Returns the basis so the sentence can
    say which of the two it is quoting.
    """
    art = ARTIFACTS[key]
    fit = BLEND_FIT.get(key) or {}
    m = art.meta["metrics"]
    if fit:
        return (fit["top1"] * 100, fit["top3"] * 100, fit["n"],
                len(art.classes), "blend")
    return (m["ensemble"]["top1"] * 100, m["ensemble"]["top3"] * 100,
            m["n_recordings"], len(art.classes), "ensemble")


def _coverage_note(artifact, name, seq_stats=None) -> str:
    """Flag a listed raga the model has never once got right.

    Both raga lists in this app are flat: a class the model scored 0 for 4 on
    reads exactly like one it gets right nine times in ten, so "supported"
    becomes a claim the system cannot keep. Printing the raw fraction rather
    than a verdict keeps the tiny denominator visible -- "0 of 4" is a
    measurement, "does not work" is an extrapolation from four recordings.

    Silent when the artifact carries no per_class block. That was model_v2_3's
    situation until its OOF row order was recovered and checked against the
    saved probabilities, and the complete model's until 2026-08-25, when a
    post-ship audit found it listing its whole class list with no annotation
    at all -- the model with the most rare classes said the least about them.
    All four carry one again, and none of the concert model's 71 classes is at
    zero. The branch stays because no annotation is the correct output for an
    unmeasured model, not a fabricated one, and the next model starts out
    unmeasured.

    One provenance difference is deliberate and recorded inside the artifact:
    the first three models' blocks are the ensemble's out-of-fold numbers,
    written by scripts/eval_stratified.py, while the complete model's are the
    blend's, written by scripts/write_blend_per_class.py. The ensemble is not
    the system -- on that model it scores 0.743 against the 0.850 that ships
    -- so an ensemble-derived block would flag ragas the served model gets
    right, and understating coverage steers a user hunting for one of them
    toward a worse model.

    `seq_stats` covers the classes the ensemble does not carry, whose numbers
    live in the LSTM sidecar rather than the artifact because the run that
    produced them is the per-fold LSTM run, not the ensemble's CV. Before it
    existed those classes were annotated "experimental" and nothing else, which
    is the honest label for unmeasured and the wrong one for measured-at-zero.
    Only written by a COMPLETE out-of-fold fit -- see fit_v3_blend.py -- so a
    number appearing here is a number over the whole corpus.
    """
    st = ((artifact.meta.get("stratified") or {}).get("per_class")
          or {}).get(name) or (seq_stats or {}).get(name) or {}
    n = st.get("n") or 0
    if n and st.get("top3") == 0:
        return f" — ⚠️ not yet working: correct in 0 of {n} test recordings"
    return ""


def _sequence_only_classes(key) -> list:
    """Ragas a model names through its sequence stage but not its ensemble.

    The broad model's LSTM carries four classes its ensemble does not, and the
    pipeline does surface them: align_classes builds a union probability vector
    and the top-3 is read off that. The raga lists showed ensemble classes
    alone, so those four read as unsupported -- and someone hunting for one of
    them switches to the widest model, which is the only model measured at 0
    for Śuddha Sāvēri. Understating coverage steered users to the worse answer.

    Routed through align_classes rather than trusting the sidecar's class list,
    because a pairing below MIN_CLASS_OVERLAP is rejected at inference: the
    LSTM never runs, so its extra classes are unreachable and must not be
    advertised. Reads the sidecar JSON rather than calling load_if_present so
    app startup does not pay for an ONNX session it may never use.
    """
    from raagafinder.models.onnx_lstm import align_classes

    side = _sidecar(key)
    if not side:
        return []
    align = align_classes(ARTIFACTS[key].classes, side["classes"])
    if align is None:
        return []
    return align.classes[len(ARTIFACTS[key].classes):]


def _sidecar(key) -> dict:
    """The LSTM sidecar for a model, or {} if its sequence stage never runs.

    The .onnx existence check mirrors load_if_present's: a sidecar without its
    graph describes a stage the pipeline will not load, and everything read out
    of this file describes what that stage contributes.
    """
    name = MODEL_FILES[key]
    onnx, sidecar = (ARTIFACTS_DIR / f"{name}.onnx",
                     ARTIFACTS_DIR / f"{name}.lstm.json")
    if not (onnx.exists() and sidecar.exists()):
        return {}
    return json.loads(sidecar.read_text(encoding="utf-8"))


def _sequence_only_stats(key) -> dict:
    """Out-of-fold per-class numbers for those same ragas, if any were fitted.

    Empty when the sidecar predates the complete out-of-fold run, which is the
    correct output rather than a fallback to the single-fold numbers that
    preceded it.
    """
    return (_sidecar(key).get("seq_only_oof") or {}).get("per_class") or {}


def _blend_fit(key) -> dict:
    """The blend's own measured accuracy, but only if honestly measured.

    fit_v3_blend.py stores this next to the weight it chose, with the source
    and fold coverage that produced it. Anything short of a complete
    out-of-fold fit is optimistic -- see _metrics -- so it is dropped here
    rather than filtered at each call site, and callers can treat a non-empty
    result as quotable.
    """
    fit = _sidecar(key).get("blend_fit") or {}
    if fit.get("source") != "oof" or not fit.get("complete"):
        return {}
    # n is quoted in the same sentence as the scores, so it is part of the
    # contract: a fit missing any of the three is not quotable.
    return fit if all(k in fit for k in ("top1", "top3", "n")) else {}


SEQ_ONLY = {k: _sequence_only_classes(k) for k in MODEL_FILES}
SEQ_ONLY_STATS = {k: _sequence_only_stats(k) for k in MODEL_FILES}
BLEND_FIT = {k: _blend_fit(k) for k in MODEL_FILES}


def _model_label(key) -> str:
    t1, t3, _n, ncls, _basis = _metrics(key)
    return (f"{_KIND[key]} — {ncls} ragas · "
            f"top-1 {t1:.0f}% / top-3 {t3:.0f}%")


MODEL_LABELS = {k: _model_label(k) for k in MODEL_FILES}

# The smart cascade is a routing rule over two of the models above, not an
# artifact, so it lives beside MODEL_FILES rather than in it: everything
# that iterates the artifact set (per-class panels, deploy manifests,
# tests) must not see it. It answers with the broad model unless broad's
# own shipped uncertainty gate fires, and only then answers with the
# complete model -- so a raga only the complete model knows is reachable
# precisely because broad is uncertain on it. Nothing was fitted: the gate
# predates the cascade, which is what left the evaluation sets honest.
#
# Its accuracy therefore has no single cross-validation number, and quoting
# one would be false: the two models trained on each other's test folds, so
# the honest figures are the three real-world sets no deployed model ever
# trained on (scripts/eval_cascade.py, remeasured 2026-08-24 with the
# complete model's v3_0 sequence stage). Shown wherever the other models
# show theirs, with their own basis sentence.
SMART = "smart"
SMART_NUMBERS = dict(
    probe=dict(top1=68.7, top3=86.6, n=67,
               label="fresh YouTube concerts, ragas both models cover"),
    youtube=dict(top1=55.6, top3=66.7, n=18, label="YouTube concert set"),
    holdout=dict(top1=83.3, top3=88.9, n=18, label="solo devotional holdout"),
)
_KIND[SMART] = "Smart cascade"
_BLURB[SMART] = ("broad's answer unless it is uncertain, then complete's · "
                 "all 72 melakartas reachable · slower on hard recordings")
MODEL_LABELS[SMART] = (
    f"Smart cascade — {len(ARTIFACTS['complete'].classes)} ragas reachable · "
    f"best top-3 on the largest held-out set")
MODEL_CHOICES = [(MODEL_LABELS[k], k) for k in MODEL_FILES]
MODEL_CHOICES.append((MODEL_LABELS[SMART], SMART))
RAGA_META = load_metadata()
MAX_DURATION_S = 60 * 60


def _basis_note(basis) -> str:
    """Say which system the number describes, in the sentence quoting it.

    All four models blend a sequence stage into the answer, but a model whose
    blend was never fitted honestly falls back to its ensemble's figure, so a
    single "grouped cross-validation" clause would cover two different
    measurements without distinguishing them.
    """
    return ("of the full pipeline, sequence stage included" if basis == "blend"
            else "of the distribution models")


def _accuracy_line(key) -> str:
    t1, t3, nrec, ncls, basis = _metrics(key)
    # The blend is scored over the union class space, so its n spans the
    # sequence-only classes too; pairing that n with the ensemble's class
    # count would misdescribe the measurement in the sentence quoting it.
    span = ncls + len(SEQ_ONLY[key]) if basis == "blend" else ncls
    return (
        f"Top-1 accuracy {t1:.0f}%, top-3 {t3:.0f}% on held-out concerts "
        f"({_basis_note(basis)}; grouped cross-validation over {nrec} "
        f"recordings, {span} ragas)."
    )


def model_summary_md(model_key) -> str:
    """Accuracy + coverage line under the selector; refreshed on selection.

    Falls back to the default on an unrecognised key, the way model_ragas_md
    does. The artifact lookup already did; the label and blurb next to it did
    not, so a dropdown reset handing this None raised rather than rendering.
    """
    if model_key == SMART:
        lines = "; ".join(
            f"top-1 {v['top1']:.0f}% / top-3 {v['top3']:.0f}% on {v['label']} "
            f"(n={v['n']})" for v in SMART_NUMBERS.values())
        return (
            f"**{MODEL_LABELS[SMART]}**  \n"
            f"_{_BLURB[SMART]}_\n\n"
            f"Answers with the broad model; when broad's own uncertainty "
            f"gate fires, the complete model answers instead, so every one "
            f"of its {len(ARTIFACTS['complete'].classes)} ragas is "
            f"reachable. Measured on held-out real audio no deployed model "
            f"trained on: {lines}. It wins on the fresh-concert probe, "
            f"where every extra raga it can reach is a raga the broad "
            f"model cannot, and it gives up ground on the two 18-clip "
            f"sets, where the broad model scores 67/78 and 89/89. "
            f"There is no single cross-validation figure for the "
            f"cascade because the two models trained on each other's test "
            f"folds; the numbers above are the honest ones."
        )
    key = model_key if model_key in ARTIFACTS else DEFAULT_MODEL
    t1, t3, nrec, ncls, _basis = _metrics(key)
    extra = len(SEQ_ONLY[key])
    cover = (f"Covers **{ncls} ragas**"
             + (f" (a sequence stage attempts {extra} more)" if extra else ""))
    return (
        f"**{MODEL_LABELS[key]}**  \n"
        f"_{_BLURB.get(key, '')}_\n\n"
        f"{cover}. Measured **top-1 {t1:.0f}%**, "
        f"**top-3 {t3:.0f}%** on held-out concerts (grouped cross-validation, "
        f"{nrec} recordings). The top answer is right most of the time; when "
        f"it isn't, the correct raga is usually in the top three — so read all "
        f"three."
    )


def model_ragas_md(model_key) -> str:
    """The full raga list for a model (inside the accordion); refreshed on
    selection. Grouped-CV per-raga accuracy varies, so this lists, not ranks."""
    if model_key == SMART:
        # everything the fallback model lists is reachable through the cascade
        model_key = "complete"
    key = model_key if model_key in ARTIFACTS else DEFAULT_MODEL
    art = ARTIFACTS[key]

    def entry(name, suffix=""):
        mela = RAGA_META.get(name, {}).get("melakarta", "")
        return (f"- **{name}**" + (f" — {mela}" if mela else "")
                + suffix + _coverage_note(art, name, SEQ_ONLY_STATS[key]))

    lines = [entry(n) for n in art.classes]
    # Sequence-only classes have no ensemble OOF number. They now have an LSTM
    # one, once a complete out-of-fold run has been merged, and _coverage_note
    # reads it from the sidecar -- so "experimental" is joined by the same
    # 0-of-n annotation every other class gets rather than standing in for it.
    extra = SEQ_ONLY[key]
    lines += [entry(n, " — *sequence model only, experimental*") for n in extra]
    # The count stays the ensemble's; the extras are a separate clause. What
    # that clause says depends on which number the app is quoting: a complete
    # out-of-fold blend fit is scored over the union space, extras included,
    # so "not covered by the accuracy figure" would be false there.
    head = f"These {len(art.classes)} ragas can be named"
    if extra:
        covered = bool(BLEND_FIT.get(key))
        head += (f", plus {len(extra)} more the sequence model attempts "
                 + ("(marked below; included in the quoted accuracy)"
                    if covered else
                    "(marked below, and not covered by the accuracy figure)"))
    return head + ":\n\n" + "\n".join(lines)


class UserError(Exception):
    pass


def _probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise UserError("Couldn't read this file — try mp3, wav, or m4a.")


def _prepare_wavs(path: str) -> tuple[list[str], str | None]:
    """Decode to mono 44.1k wav. Long recordings become SEPARATE section wavs
    (analyzed independently and merged) so one bad section — intro speech, a
    violin interlude, a different item on the same upload — can't poison the
    whole analysis."""
    dur = _probe_duration(path)
    if dur > MAX_DURATION_S:
        raise UserError(
            f"That's {dur / 60:.0f} minutes — please upload up to 60 minutes."
        )
    note = None
    starts = [0.0]
    seg_args: list[list[str]] = [[]]
    if dur > MULTISEG_ABOVE_S:
        starts = [max(0.0, min(dur * f, dur - SEGMENT_S)) for f in SEGMENT_POSITIONS]
        seg_args = [["-ss", f"{s:.1f}", "-t", str(SEGMENT_S)] for s in starts]
        note = (f"Long recording — analyzed {len(starts)} sections "
                f"({SEGMENT_S} s each) spread across it.")
    wavs = []
    for extra in seg_args:
        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        args = (["ffmpeg", "-y", "-v", "error"] + extra
                + ["-i", path, "-ac", "1", "-ar", "44100", wav])
        proc = subprocess.run(args, capture_output=True, timeout=300)
        if proc.returncode != 0:
            raise UserError("Couldn't read this file — try mp3, wav, or m4a.")
        wavs.append(wav)
    return wavs, note


def _smart_analysis(wavs):
    """The cascade: broad answers unless its own gate defers to complete.

    Returns the artifact that actually answered alongside its result, so
    the caller renders cards, templates and class counts for the model
    whose answer the user is reading. A fallback that itself errors is
    discarded -- broad's uncertain answer with its honest banner beats an
    error page. Raw pitch extraction is memoized in the backends, so the
    deferral pays for the second model's classification only.
    """
    # Named explicitly rather than via DEFAULT_MODEL. The cascade is a
    # broad-then-complete routing rule, and it was written when broad was
    # the default; keying the first stage off the default constant meant
    # that changing the default on 2026-08-26 would have silently made the
    # cascade fall back from complete to complete and do nothing at all.
    result = analyze_segments(wavs, ARTIFACTS[SMART_FIRST])
    if result.status != "ok":
        fallback = analyze_segments(wavs, ARTIFACTS[SMART_FALLBACK])
        if fallback.status != "error":
            fallback.warnings.append(
                "The broad model was uncertain here, so the complete model "
                "(all 72 melakartas) answered.")
            return ARTIFACTS[SMART_FALLBACK], fallback
    return ARTIFACTS[SMART_FIRST], result


# --------------------------------------------------------------------------
# Adding a raga the models never trained on, for the length of one session
# --------------------------------------------------------------------------
# Enrollment compares a recording against class prototypes -- the mean
# pooled embedding of a class -- and a raga the model has never trained on
# gets one the same way, by averaging a few uploads. Nothing is retrained
# and nothing is written to disk.
#
# It always runs in the complete model's embedding space, whichever model
# the selector is on. That model is the one carrying prototypes and the one
# the whitener was fitted against, and a prototype means nothing outside the
# encoder that produced it, so the alternative is not "enrol under the broad
# model" but "no enrolled answer at all". The trained answer the user reads
# still comes from whichever model they chose.
ENROLL_MODEL = "complete"
# Enrollment refuses to run without the whitener rather than falling back to
# plain cosine. The fallback would work -- it is the same code at 0.763
# instead of 0.800 -- but every sentence this tab shows quotes the whitened
# figure, and an app that silently serves one number while displaying
# another is the failure the accuracy tests exist to prevent.
ENROLL_WHITENER = load_whitener(ARTIFACTS_DIR, MODEL_FILES[ENROLL_MODEL])


def _enroll_component():
    """The sequence model enrolled ragas are embedded and scored by."""
    from raagafinder.inference.pipeline import _lstm_component

    return _lstm_component(ARTIFACTS[ENROLL_MODEL])


def _enroll_blocker() -> str:
    """Why enrollment cannot run here, or "" when it can.

    Every reason is environmental rather than user error -- an artifact
    missing from the deployment, a graph exported before the embedding
    output existed -- so the tab reports it in place instead of failing at
    the moment someone has finished uploading five recordings.

    Deliberately cheap. This runs while the page is being built, and the
    reason _sequence_only_classes reads the sidecar rather than calling
    load_if_present applies here too: startup must not pay for an ONNX
    session it may never use. The checks that need the loaded graph run
    in _enroll_prototype, at the moment someone actually adds a raga.
    """
    side = _sidecar(ENROLL_MODEL)
    if not side:
        return ("The sequence model this feature needs is missing from this "
                "deployment, so no raga can be added.")
    if not float(side.get("prototype_w", 0.0)):
        return ("The sequence model in this deployment carries no class "
                "prototypes, which is what an added raga is compared "
                "against, so no raga can be added.")
    if ENROLL_WHITENER is None:
        return ("The whitening transform added ragas are scored under is "
                "missing from this deployment, and the measured accuracy "
                "below is the accuracy under it, so no raga can be added.")
    return ""


def _enroll_paths(files) -> list:
    """Filepaths out of whatever the file component handed over."""
    out = []
    for f in files or []:
        p = getattr(f, "name", f)
        if p:
            out.append(str(p))
    return out


def enrolled_names(enrolled) -> list:
    return [e.name for e in enrolled or []]


def enrolled_md(enrolled) -> str:
    """What this session has added, listed under the upload box."""
    if not enrolled:
        return ("_Nothing added yet. Ragas added here last until this tab is "
                "closed and are visible only to this session._")
    rows = "\n".join(
        f"- **{e.name}** — built from {e.n_recordings} recording"
        + ("s" if e.n_recordings != 1 else "") for e in enrolled)
    return (f"Added in this session, and compared alongside the "
            f"{len(ARTIFACTS[ENROLL_MODEL].classes)} trained ragas on every "
            f"identification:\n\n{rows}")


def enroll_raga(name, files, enrolled):
    """Build one prototype from a few uploads and add it to the session.

    Returns a NEW list rather than appending to the one it was handed.
    The list arrives from a gr.State, and gradio hands the same object
    back on every call for a session; mutating it in place works, right
    up until a caller holds a reference to what it thought was the
    previous value.
    """
    enrolled = list(enrolled or [])
    blocked = _enroll_blocker()
    if blocked:
        return enrolled, f"❌ {blocked}", enrolled_md(enrolled)

    name = (name or "").strip()
    paths = _enroll_paths(files)
    if not name:
        return enrolled, "❌ Give the raga a name first.", enrolled_md(enrolled)
    if name in set(ARTIFACTS[ENROLL_MODEL].classes):
        return (enrolled,
                f"❌ **{name}** is already one of the trained ragas. Adding "
                f"it again would put a prototype built from a handful of "
                f"recordings up against one built from the whole corpus, "
                f"which is a worse answer, not a better one.",
                enrolled_md(enrolled))
    if name in set(enrolled_names(enrolled)):
        return (enrolled,
                f"❌ **{name}** has already been added in this session. "
                f"Remove the added ragas and start again to rebuild it.",
                enrolled_md(enrolled))
    if not (MIN_ENROLL_RECORDINGS <= len(paths) <= MAX_ENROLL_RECORDINGS):
        return (enrolled,
                f"❌ Upload between {MIN_ENROLL_RECORDINGS} and "
                f"{MAX_ENROLL_RECORDINGS} recordings — {len(paths)} "
                f"received.",
                enrolled_md(enrolled))

    try:
        vec, used, failed = _enroll_prototype(paths)
    except UserError as exc:
        return enrolled, f"❌ {exc}", enrolled_md(enrolled)
    except Exception:
        traceback.print_exc()
        return (enrolled,
                "❌ Something went wrong reading those recordings. Try "
                "different files.", enrolled_md(enrolled))
    if vec is None or used < MIN_ENROLL_RECORDINGS:
        return (enrolled,
                f"❌ Only {used} of {len(paths)} recordings had enough "
                f"melody to use, and {MIN_ENROLL_RECORDINGS} is the "
                f"minimum. Longer or cleaner recordings would help.",
                enrolled_md(enrolled))

    enrolled = enrolled + [EnrolledRaga(name=name, prototype=vec,
                                        n_recordings=used)]
    note = (f" {failed} upload{'s' if failed != 1 else ''} had too little "
            f"melody to use." if failed else "")
    return (enrolled,
            f"✅ **{name}** added from {used} recordings.{note} It is now "
            f"compared on every identification in this session.",
            enrolled_md(enrolled))


def _enroll_prototype(paths):
    """(prototype, recordings used, recordings dropped) for one raga.

    The graph-level checks _enroll_blocker deliberately skipped happen
    here, where the component is loaded anyway, and they are raised as a
    UserError so the caller's existing error path carries the reason to
    the page rather than reporting it as unusable audio.
    """
    from raagafinder.pitch.base import get_backend

    comp = _enroll_component()
    if comp is None or comp.proto is None or not exposes_embedding(comp):
        raise UserError(
            "The sequence model in this deployment cannot produce the "
            "embeddings an added raga is compared by, so no raga can be "
            "added here.")
    backend = get_backend()
    vectors = []
    for p in paths:
        wavs, _note = _prepare_wavs(p)
        v = embed_sections(comp, backend, wavs)
        if v is not None:
            vectors.append(v)
    if not vectors:
        return None, 0, len(paths)
    return build_prototype(vectors), len(vectors), len(paths) - len(vectors)


def clear_enrolled(enrolled):
    n = len(enrolled or [])
    msg = (f"Removed {n} added raga{'s' if n != 1 else ''}." if n
           else "Nothing to remove.")
    return [], msg, enrolled_md([])


def _enrolled_answer(result, enrolled):
    """Score one analyzed recording against the session's added ragas.

    Reads the pitch track the sequence stage was already given rather
    than re-extracting it. On a long upload that track is one section
    rather than the whole recording -- analyze_segments returns the
    section it chose as primary -- so an enrolled answer sees less of a
    long recording than the trained answer beside it does.
    """
    if not enrolled or _enroll_blocker():
        return None
    if result.lstm_input is None:
        return None
    comp = _enroll_component()
    if comp is None or comp.proto is None:
        return None
    query = recording_embedding(comp, *result.lstm_input)
    if query is None:
        return None
    return score_query(query, comp.proto, comp.classes, enrolled,
                       ENROLL_WHITENER)


# The honest description of what an enrolled answer is worth, shown with
# every one of them. Both numbers come from one run of
# scripts/enroll_abstain_whitened.py, ten folds out-of-fold: enrolling from
# five recordings scores 0.800 on thirty ragas withheld from training and
# competing against all 154 at full strength, and the trained ragas score
# 0.849 under that same prototype comparison. Quoting the app's headline
# 0.850 instead would compare a prototype match against a full blended
# pipeline, which is a different measurement wearing the same units.
# Rounded to whole points, because a percentage on a result card reads as a
# property of this recording, and the fold-to-fold spread is wider than the
# last digit would imply.
ENROLL_PROVENANCE = (
    "User-enrolled this session; measured accuracy on enrolled ragas is "
    "lower than on trained ones. Adding a raga from five recordings scored "
    "80% out-of-fold on ragas withheld from training, against 85% for the "
    "154 trained ragas measured the same way, and both figures are on corpus "
    "recordings — a recording found elsewhere is harder than that by an "
    "amount nothing here measures."
)


def _enrolled_html(answer) -> str:
    """The enrolled verdict, above the model's own answer rather than
    replacing it.

    The trained top-3 stays on the page in every case. An enrolled raga
    has no card, no scale, no confusion history and no per-class
    accuracy, so promoting it into the layout those things fill would
    dress a prototype built from three uploads as the best-documented
    answer on the page.
    """
    if answer is None:
        return ""
    box = ('margin:8px 0;padding:10px 12px;border-radius:8px;'
           'border:1px solid #cfd8dc;background:#fafafa')
    if not answer.is_enrolled:
        return (f'<div style="{box};color:#607d8b;font-size:13px">'
                f'{answer.n_enrolled} raga'
                f'{"s" if answer.n_enrolled != 1 else ""} added in this '
                f'session were compared too; none was closer than the '
                f'trained ragas below.</div>')
    name = html.escape(answer.winner)
    if not answer.kept:
        return (f'<div style="{box};color:#757575;font-size:13.5px">'
                f'<b>{name}</b>, added in this session, was the closest '
                f'match of all — but not by enough to clear the confidence '
                f'gate added ragas have to pass, so it is not being given '
                f'as the answer. The gate is deliberately harder on added '
                f'ragas than on trained ones: it lets through about seven '
                f'answers in ten, and is right on 92% of those it lets '
                f'through.</div>')
    return (
        f'<div style="{box};border-color:#2e7d32;background:#f1f8e9">'
        f'<div style="font-size:17px"><b>{name}</b> '
        f'<span style="color:#33691e">— added in this session</span></div>'
        f'<div style="color:#555;font-size:13px;margin-top:6px">'
        f'{ENROLL_PROVENANCE}</div></div>'
    )


def identify(path, model_key=DEFAULT_MODEL, enrolled=None):
    empty = ("", "", None, "")
    if not path:
        return ('<h3 style="color:#b71c1c">Please upload an audio file first.</h3>', *empty)
    artifact = ARTIFACTS.get(model_key) or ARTIFACTS[DEFAULT_MODEL]
    try:
        wavs, trim_note = _prepare_wavs(path)
        if model_key == SMART:
            artifact, result = _smart_analysis(wavs)
        else:
            result = analyze_segments(wavs, artifact)

        if result.status == "error":
            msgs = "<br>".join(result.failures) or "Analysis failed."
            return (f'<h3 style="color:#b71c1c">{msgs}</h3>', *empty)

        warn_bits = list(result.warnings)
        if trim_note:
            warn_bits.append(trim_note)
        warn_html = (
            f'<div style="color:#8d6e63;font-size:13px;margin-top:4px">{" ".join(warn_bits)}</div>'
            if warn_bits else ""
        )
        enrol = _enrolled_answer(result, enrolled)
        if result.status == "uncertain":
            headline = (
                f'<h3 style="color:#757575">None of the {len(artifact.classes)} supported ragas matched '
                "confidently — best guesses below.</h3>"
            )
        else:
            headline = f"<h3>Most likely: <b>{result.top3[0][0]}</b></h3>"
        if enrol is not None and enrol.is_enrolled and enrol.kept:
            # The trained answer is demoted rather than dropped: it is the
            # measured half of the page, and a reader comparing the two is
            # the point of showing both. Its own uncertainty survives the
            # demotion -- "none of the trained ragas matched confidently"
            # is most of what makes an added raga winning believable.
            lead = ("None of the {n} trained ragas matched confidently; the "
                    "closest was" if result.status == "uncertain"
                    else "Closest of the {n} trained ragas:")
            headline = (
                f'<div style="color:#616161;font-size:14px">'
                f'{lead.format(n=len(artifact.classes))} '
                f'<b>{html.escape(result.top3[0][0])}</b>.</div>'
            )
        headline = _enrolled_html(enrol) + headline
        bars = confidence_bar_html(result.top3, result.status == "uncertain")
        confusions = artifact.meta.get("confusions")
        cards = "".join(
            card_html(name, prob, RAGA_META, i, confusions)
            for i, (name, prob) in enumerate(result.top3)
        )
        top_name = result.top3[0][0]
        # LSTM-only classes (class-union blend) have no ensemble template
        template = (
            artifact.arrays["pcd_templates"][artifact.classes.index(top_name)]
            if top_name in artifact.classes else None
        )
        fig = pcd_overlay_figure(result.pcd, template, top_name)
        return (headline + warn_html, bars, cards, fig, chips_html(result))
    except UserError as exc:
        return (f'<h3 style="color:#b71c1c">{exc}</h3>', *empty)
    except Exception:
        traceback.print_exc()
        return ('<h3 style="color:#b71c1c">Something went wrong analyzing this file. '
                "Please try a different recording.</h3>", *empty)


def _supported_ragas_md(key) -> str:
    """Same list as the selector accordion, so the two cannot disagree."""
    return model_ragas_md(key).split(":\n\n", 1)[1]


_BROAD = ARTIFACTS["broad"]
_CONCERT = ARTIFACTS["concert"]
_WIDEST = ARTIFACTS["widest"]
_COMPLETE = ARTIFACTS["complete"]

# Ragas only the widest model can reach at all. NOT len(widest) - len(broad):
# the broad model's sequence stage also attempts four of those, and for at
# least Śuddha Sāvēri it is the better route (1 of 5 in the out-of-fold run
# vs the widest model's 0 of 4). Telling users the widest model is "the only
# way" for a raga the default reaches better is the exact steering error the
# sequence-only listing was added to stop.
#
# The complete model belongs in this set and was missing from it until
# 2026-08-26. It carries all 154 classes, which is a superset of the widest
# model's 104, so every raga this list used to name as exclusive to the
# widest model has been reachable elsewhere since the complete model
# shipped. The list is empty now, and that is the true answer rather than a
# regression: the widest model no longer has a raga only it can name.
_WIDEST_ONLY = [c for c in _WIDEST.classes
                if c not in {*_BROAD.classes, *SEQ_ONLY["broad"],
                             *_CONCERT.classes, *SEQ_ONLY["concert"],
                             *_COMPLETE.classes, *SEQ_ONLY["complete"]}]
_WIDEST_ALSO_SEQ = [c for c in _WIDEST.classes if c in SEQ_ONLY["broad"]]


def _n_flagged(key) -> int:
    """How many classes _coverage_note will mark. Derived, so the About text
    can name the number without a human keeping it in sync -- the same failure
    tests/test_about_text_counts.py exists to prevent for raga counts.

    Keyed rather than given an artifact so it can walk the same list the
    accordion prints, sequence-only classes included. Those are now flaggable
    too, and a count that skipped them would understate exactly the ragas most
    likely to be flagged.
    """
    art, stats = ARTIFACTS[key], SEQ_ONLY_STATS[key]
    return sum(1 for c in list(art.classes) + SEQ_ONLY[key]
               if _coverage_note(art, c, stats))

ENROLL_INTRO_MD = f"""
Upload {MIN_ENROLL_RECORDINGS} to {MAX_ENROLL_RECORDINGS} recordings of a raga
this app does not know, give it a name, and it is compared alongside the
{len(_COMPLETE.classes)} trained ragas on every identification you run
afterwards. Nothing is retrained: each recording is turned into one vector,
the vectors are averaged, and the average competes with the trained ragas'
own averages.

**It lasts as long as this session.** What you add lives in your browser
session only — it is not written to disk, not shared with anyone else using
this Space, and gone when you close the tab. Your audio is used to compute
the average and then discarded with the rest of the upload.

**How well it works, before you spend the effort.** A raga added from five
recordings was identified correctly 80% of the time, against 85% for the
{len(_COMPLETE.classes)} ragas the model trained on for weeks, compared the
same way — measured out-of-fold on thirty ragas withheld from training
entirely, each competing against the full field. Added ragas also say "not sure" much more often:
about one answer in three is withheld, and the ones that get through are
right 92% of the time. Both figures come from corpus recordings, and a
recording found somewhere else is harder than that by an amount nothing here
measures.

**Which recordings to send matters more than how many.** Send typical ones.
Three recordings close to how the raga is usually sung scored 77%, where
five picked at random scored 75%; deliberately varied ones — different
tempo, instrument, school — were the worst strategy measured, at 57% for
three. What sits far from the middle of a raga is more often a failed
melody track or a mislabelled upload than an interesting rendition. Nothing
is filtered here — the choice is yours, and it is worth more than an extra
recording would be.

Clean solo or vocal-forward recordings of at least a minute work best, for
the same reasons they do on the Identify tab.
"""

ABOUT_MD = f"""
## How it works
RaagaFinder extracts the melody line from your recording
([MELODIA](https://essentia.upf.edu/reference/std_PredominantPitchMelodia.html)),
finds the tonic (Sa), and compares the tonic-normalized pitch distribution and
melodic-transition surface ([TDMS](https://compmusic.upf.edu/node/300)) against
a corpus of labelled recordings
(CompMusic raga dataset + Saraga 1.5 Carnatic + verified concert recordings).
A recurrent sequence model (a [DeepSRGM](https://archives.ismir.net/ismir2019/paper/000068.pdf)-style
LSTM trained on the same corpus) additionally listens to phrase-level melodic
movement — note order and gamaka context that distributions can't see — and
its opinion is blended into the final answer. All four models carry that
stage, and all four quote the accuracy of the whole pipeline with it included,
measured out-of-fold on recordings no part of the system was fitted on.

## Which model? (choose below the upload box)
Four models ship together, and you can switch between them. They trade
coverage against accuracy: each raga a model adds is one more look-alike
competing with every other, so naming more ragas costs accuracy on the ragas
it already knew. Pick the smallest one that contains the raga you're asking
about.

- **{MODEL_LABELS['smart']}** — the broad model's answer unless it is
  uncertain, in which case the complete model answers, so every supported
  raga is reachable. It buys that reach on the fresh-concert probe and
  pays for it on the two 18-clip sets, where the broad model alone scores
  higher; hard recordings take longer because two models run.
- **{MODEL_LABELS['complete']}** — the default since 2026-08-26. It names every
  raga the system knows, including all 72 melakarta parent scales, and it has
  the best measured accuracy of the four: it leads on cross-validation over
  1275 recordings and by nine points on the largest held-out set, 67 freshly
  collected concert recordings none of the models trained on. It was not the
  default before because an 18-clip set favoured the broad model; that set
  turned out to be too small to tell the two apart.
- **{MODEL_LABELS['broad']}** — fewer ragas, so fewer look-alikes competing.
  It recognizes {len(_BROAD.classes) - len(_CONCERT.classes)} more ragas than
  the concert-tuned model and is stronger on clean solo-voice recordings.
  On full concert recordings (voice together with violin and percussion) it
  sometimes ranks the correct raga second or third rather than first, so read
  the whole top-3.
- **{MODEL_LABELS['concert']}** — ranks the single most-likely raga most sharply
  on full concert recordings. Choose it for a concert clip of a common raga when
  you want the crispest top-1 answer.
- **{MODEL_LABELS['widest']}** — kept for continuity, and no longer
  recommended for anything. It once named ragas no other model could reach;
  the complete model's {len(_COMPLETE.classes)} classes are a superset of its
  {len(_WIDEST.classes)}, so there is now no raga only this model can answer,
  and it is less accurate than the default across the board. ({len(_WIDEST_ALSO_SEQ)}
  of its additions are also attempted by the broad model's sequence stage;
  measured against each other, that route wins only on Śuddha Sāvēri, this
  model wins on Naṭabhairavi and Sālaga bhairavi, and the two tie on Māṇḍ.)

Accuracy (grouped cross-validation on held-out concerts):
- All melakartas: {_accuracy_line("complete")}
- Broad coverage: {_accuracy_line("broad")}
- Concert-tuned: {_accuracy_line("concert")}
- Widest coverage: {_accuracy_line("widest")}

{_n_flagged("widest")} of the ragas the widest model lists are marked "not yet
working" there: it never once placed them in the top-3 during testing. They are
kept listed rather than quietly dropped, because a missing raga looks like an
oversight while a marked one tells you not to trust the answer.

{stratified_md(_BROAD.meta, "broad model")}
{non_curated_note(_CONCERT.meta, "concert-tuned model")}
## Adding a raga (the "Add a raga" tab)
A raga outside the list below can be added for the length of one session by
uploading {MIN_ENROLL_RECORDINGS}–{MAX_ENROLL_RECORDINGS} recordings of it.
The sequence model turns each recording into one 768-number vector, those are
averaged into a prototype, and the prototype competes with the trained ragas'
prototypes — the same mechanism that is already mixed into every answer the
default model gives. No training happens, and the added raga is held in the
browser session rather than on disk, so it is invisible to everyone else and
gone when the tab closes.

Three things about it are worth stating plainly.

It is less accurate than the trained ragas, and the gap is measured. Thirty
ragas were withheld from every training fold, added from five recordings
each, and asked to compete against all {len(_COMPLETE.classes)} classes at
full strength: 80.0% correct, against 84.9% for the trained ragas under that
same prototype comparison. Both halves come from one run, which is the point
— comparing an added raga against the app's headline figure would be
comparing a prototype match against a full blended pipeline. That
measurement is on corpus recordings; a recording found elsewhere carries the
same found-audio penalty the rest of this app does, and no measurement here
separates the two.

It abstains more, on purpose. Added ragas pass the same confidence gate as
everything else — the probability of the winning class at the shipped
prototype temperature — and being defined from a handful of recordings, they
clear it less often: 68% of answers on added ragas are let through against
81% on trained ones, and the two are then almost equally accurate, 89%
against 90%, over 1275 gated queries. Answering less often where the system
knows less is what keeps "confident" meaning one thing across both.

Those keep-rates come from the metric the threshold was fitted on, which is
the plain cosine. Added ragas are scored under a whitened version of the same
space instead — a correction worth 3.7 points on enrollment, 76.3% to 80.0%,
and used nowhere else in this app. The threshold was carried over rather than
refitted, and what that carry-over does was measured rather than assumed:
holding it fixed and changing only the metric, it lets through 69.6% of
added-raga answers at 92.0% accuracy and 74.0% of all answers at 94.3%. It
was fitted as the largest coverage still reaching 90% overall, so on the
whitened metric it answers slightly less often than the fit intended and is
four points more accurate when it does.

It runs in the complete model's space whatever model is selected, because
that is the model carrying prototypes. The trained answer on the page is
still the selected model's own.

## Honest limitations
- Only the ragas below are supported; anything else gets low-confidence
  guesses, or can be added for one session on the "Add a raga" tab at the
  lower accuracy that section states.
- Newer ragas with limited training data (noted on their cards) get lower confidence.
- The broad model's sequence stage also attempts a few rare ragas whose
  identity lives in note order rather than note choice; only some of these are
  robustly validated, so treat them as experimental.
- Film songs with Western harmony, heavy percussion sections, very short clips
  (< 30 s of melody), and noisy phone recordings reduce accuracy.
- Allied ragas (e.g. Śankarābharaṇaṁ-family look-alikes) are genuinely hard —
  which is why the app shows top-3 with confidence, not a single answer.
- First request after a long idle period takes ~1 minute while the app wakes up.

## Supported ragas
Listed for the default model, which names every raga the system knows. The
other three cover subsets: {len(_CONCERT.classes)} for the concert-tuned
model, {len(_BROAD.classes)} for the broad one and {len(_WIDEST.classes)} for
the widest. Selecting a model below the upload box shows that model's own
list.

{_supported_ragas_md(DEFAULT_MODEL)}

## API access
This Space exposes a programmatic API. From Python:
```python
from gradio_client import Client
client = Client("Sukarth/raagafinder")
# second argument picks the model: "broad" ({len(_BROAD.classes)} ragas), "concert"
# ({len(_CONCERT.classes)}), "widest" ({len(_WIDEST.classes)}), "complete" ({len(_COMPLETE.classes)})
# or "smart" (broad with a complete fallback)
result = client.predict("path/to/recording.mp3", "broad", api_name="/identify")
```
Fair use only — one request at a time; heavy users please duplicate the Space.

## Data & attribution
Trained on features from the **Indian Art Music Raga Recognition Dataset**
(Gulati et al., CompMusic / MTG-UPF), [Zenodo 7278506](https://zenodo.org/records/7278506),
CC-BY 4.0. Also trained on **Saraga 1.5 Carnatic** (CompMusic / MTG-UPF),
[Zenodo 4301737](https://zenodo.org/records/4301737), CC BY-NC-SA 4.0 — pitch
and tonic annotations only, no audio is redistributed here.
Methods follow Gulati et al. (ISMIR 2016) and the raga-recognition
literature. Built with [essentia](https://essentia.upf.edu/) and Gradio.
Source code and training recipe:
[github.com/Sukarth/raagafinder](https://github.com/Sukarth/raagafinder).
"""

with gr.Blocks(title="RaagaFinder — Carnatic raga identification") as demo:
    gr.Markdown("# 🎵 RaagaFinder\nUpload a Carnatic recording — get the raga.")
    # Session-scoped, and gr.State is what makes that true: gradio gives each
    # browser session its own copy and never persists it. A module-level list
    # here would put one user's added ragas in front of every other user of
    # the Space, which is a privacy failure rather than a bug in a feature.
    enrolled_state = gr.State([])
    with gr.Tab("Identify"):
        audio_in = gr.Audio(sources=["upload"], type="filepath", label="Audio (mp3/wav/m4a, up to 60 min)")
        model_sel = gr.Radio(
            choices=MODEL_CHOICES, value=DEFAULT_MODEL, label="Model",
            info="More ragas means more look-alikes competing, so the broad "
                 "model trades a little top-1 sharpness for coverage. Pick by "
                 "your recording; details update below.",
        )
        model_info = gr.Markdown(model_summary_md(DEFAULT_MODEL))
        with gr.Accordion("See the ragas this model can name", open=False):
            model_ragas = gr.Markdown(model_ragas_md(DEFAULT_MODEL))
        model_sel.change(model_summary_md, inputs=[model_sel], outputs=[model_info])
        model_sel.change(model_ragas_md, inputs=[model_sel], outputs=[model_ragas])
        btn = gr.Button("Identify raga", variant="primary")
        headline = gr.HTML()
        bars = gr.HTML()
        with gr.Row():
            with gr.Column(scale=1):
                cards = gr.HTML()
            with gr.Column(scale=1):
                plot = gr.Plot(label="Pitch-class distribution vs. predicted raga")
                chips = gr.HTML()
        sample = ASSETS_DIR / "sample_clips" / "synthetic_kalyani.wav"
        if sample.exists():
            gr.Examples(
                examples=[[str(sample)]],
                inputs=[audio_in],
                label="Example (synthetic Kalyāṇi phrases — real recordings work much better)",
            )
        btn.click(identify, inputs=[audio_in, model_sel, enrolled_state],
                  outputs=[headline, bars, cards, plot, chips])
    with gr.Tab("Add a raga"):
        gr.Markdown(ENROLL_INTRO_MD)
        _blocked = _enroll_blocker()
        if _blocked:
            gr.Markdown(f"**Unavailable here.** {_blocked}")
        enroll_name = gr.Textbox(
            label="Raga name",
            placeholder="The name you want it reported under",
            info="Any spelling you like — it is shown back to you exactly as "
                 "typed, and only in this session.",
        )
        enroll_files = gr.File(
            file_count="multiple", type="filepath",
            file_types=["audio"],
            label=f"{MIN_ENROLL_RECORDINGS}–{MAX_ENROLL_RECORDINGS} "
                  f"recordings of that raga (mp3/wav/m4a)",
        )
        with gr.Row():
            enroll_btn = gr.Button("Add this raga", variant="primary",
                                   interactive=not _blocked)
            enroll_clear = gr.Button("Remove everything I added")
        enroll_status = gr.Markdown()
        enroll_list = gr.Markdown(enrolled_md([]))
        enroll_btn.click(
            enroll_raga, inputs=[enroll_name, enroll_files, enrolled_state],
            outputs=[enrolled_state, enroll_status, enroll_list])
        enroll_clear.click(
            clear_enrolled, inputs=[enrolled_state],
            outputs=[enrolled_state, enroll_status, enroll_list])
    with gr.Tab("About"):
        gr.Markdown(ABOUT_MD)

demo.queue(max_size=10, default_concurrency_limit=1)

if __name__ == "__main__":
    demo.launch(max_file_size="30mb")
