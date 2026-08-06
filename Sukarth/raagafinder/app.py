"""RaagaFinder — Carnatic raga identification. Gradio entry point (HF Spaces)."""

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

# Three shipped models, user-selectable: one coverage/accuracy ladder. Adding
# ragas necessarily dilutes per-raga top-1 (more look-alikes compete), so three
# points on that trade-off ship rather than one chosen for everyone -- each
# model's raga count and measured accuracy are shown right at the selector.
#
# `broad` stays the default despite `widest` covering strictly more. Swapping
# them would be a straight regression for the majority: measured on the same
# grouped CV, widest is 77.1/88.2 at 65.8% coverage against broad's 79.4/90.1
# at 74.4%. Both weights now come from a complete ten-fold out-of-fold run, so
# the comparison is like for like. Widest is the right pick only when the
# raga in question is one only it knows -- so it is offered, not imposed.
#
# All three models carry a paired LSTM (models_artifacts/*.lstm.json); the
# inference pipeline loads it with load_if_present and runs the numpy
# ensemble alone when a model ships without one.
MODEL_FILES = {"broad": "model_v2_4", "concert": "model_v2_3",
               "widest": "model_v2_7"}
DEFAULT_MODEL = "broad"
ARTIFACTS = {k: ModelArtifact.load(ARTIFACTS_DIR / fn) for k, fn in MODEL_FILES.items()}
_KIND = {"broad": "Broad coverage", "concert": "Concert-tuned",
         "widest": "Widest coverage"}
_BLURB = {
    "broad": "recommended · best all-round accuracy",
    "concert": "sharper single top-1 on full concert recordings",
    "widest": "most ragas named · lower accuracy",
}


def _metrics(key):
    """Headline accuracy for a model: what it serves, not what part of it does.

    `metrics.ensemble` is the numpy ensemble's own grouped CV. For all three
    models that is not the system: a sequence stage is blended in at
    inference, and the blend scores about two points of top-1 above the
    ensemble alone (1.7 concert, 2.0 broad, 2.3 widest). Quoting the ensemble
    understates the app, which is not the safe direction -- the same lesson
    the raga lists taught when they listed fewer ragas than the pipeline
    could return.

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
    saved probabilities; all three models now carry one, and none of the
    concert model's 71 classes is at zero. The branch stays because no
    annotation is the correct output for an unmeasured model, not a fabricated
    one, and the next model starts out unmeasured.

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
MODEL_CHOICES = [(MODEL_LABELS[k], k) for k in MODEL_FILES]
RAGA_META = load_metadata()
MAX_DURATION_S = 60 * 60


def _basis_note(basis) -> str:
    """Say which system the number describes, in the sentence quoting it.

    All three models blend a sequence stage into the answer, but a model whose
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


def identify(path, model_key=DEFAULT_MODEL):
    empty = ("", "", None, "")
    if not path:
        return ('<h3 style="color:#b71c1c">Please upload an audio file first.</h3>', *empty)
    artifact = ARTIFACTS.get(model_key) or ARTIFACTS[DEFAULT_MODEL]
    try:
        wavs, trim_note = _prepare_wavs(path)
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
        if result.status == "uncertain":
            headline = (
                f'<h3 style="color:#757575">None of the {len(artifact.classes)} supported ragas matched '
                "confidently — best guesses below.</h3>"
            )
        else:
            headline = f"<h3>Most likely: <b>{result.top3[0][0]}</b></h3>"
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

# Ragas only the widest model can reach at all. NOT len(widest) - len(broad):
# the broad model's sequence stage also attempts four of those, and for at
# least Śuddha Sāvēri it is the better route (1 of 5 in the out-of-fold run
# vs the widest model's 0 of 4). Telling users the widest model is "the only
# way" for a raga the default reaches better is the exact steering error the
# sequence-only listing was added to stop.
_WIDEST_ONLY = [c for c in _WIDEST.classes
                if c not in {*_BROAD.classes, *SEQ_ONLY["broad"],
                             *_CONCERT.classes, *SEQ_ONLY["concert"]}]
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
its opinion is blended into the final answer. All three models carry that
stage, and all three quote the accuracy of the whole pipeline with it included,
measured out-of-fold on recordings no part of the system was fitted on.

## Which model? (choose below the upload box)
Three models ship together, and you can switch between them. They trade
coverage against accuracy: each raga a model adds is one more look-alike
competing with every other, so naming more ragas costs accuracy on the ragas
it already knew. Pick the smallest one that contains the raga you're asking
about.

- **{MODEL_LABELS['broad']}** — the default, and the best all-round accuracy.
  It recognizes {len(_BROAD.classes) - len(_CONCERT.classes)} more ragas than
  the concert-tuned model and is stronger on clean solo-voice recordings.
  On full concert recordings (voice together with violin and percussion) it
  sometimes ranks the correct raga second or third rather than first, so read
  the whole top-3.
- **{MODEL_LABELS['concert']}** — ranks the single most-likely raga most sharply
  on full concert recordings. Choose it for a concert clip of a common raga when
  you want the crispest top-1 answer.
- **{MODEL_LABELS['widest']}** — names
  {len(_WIDEST_ONLY)} ragas no other model can reach, and is the only way to
  get an answer for those. ({len(_WIDEST_ALSO_SEQ)} more of its additions are
  also attempted by the default model's sequence stage. Measured against each
  other, that route wins only on Śuddha Sāvēri, this model wins on Naṭabhairavi
  and Sālaga bhairavi, and the two tie on Māṇḍ.) It pays for its reach with
  lower accuracy across the board than the other two models. Use it when the
  raga you want is missing from the default's list; otherwise prefer the
  default.

Accuracy (grouped cross-validation on held-out concerts):
- Broad coverage: {_accuracy_line("broad")}
- Concert-tuned: {_accuracy_line("concert")}
- Widest coverage: {_accuracy_line("widest")}

{_n_flagged("widest")} of the ragas the widest model lists are marked "not yet
working" there: it never once placed them in the top-3 during testing. They are
kept listed rather than quietly dropped, because a missing raga looks like an
oversight while a marked one tells you not to trust the answer.

{stratified_md(_BROAD.meta, "broad model")}
{non_curated_note(_CONCERT.meta, "concert-tuned model")}
## Honest limitations
- Only the ragas below are supported; anything else gets low-confidence guesses.
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
Listed for the default model, including the ones only its sequence stage
attempts. The concert-tuned model covers a {len(_CONCERT.classes)}-raga
subset of them; the widest model adds
{len(_WIDEST.classes) - len(_BROAD.classes)} beyond the default's ensemble.
Selecting a model below the upload box shows that model's own list.

{_supported_ragas_md(DEFAULT_MODEL)}

## API access
This Space exposes a programmatic API. From Python:
```python
from gradio_client import Client
client = Client("Sukarth/raagafinder")
# second argument picks the model: "broad" ({len(_BROAD.classes)} ragas), "concert" ({len(_CONCERT.classes)}), or "widest" ({len(_WIDEST.classes)})
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
        btn.click(identify, inputs=[audio_in, model_sel], outputs=[headline, bars, cards, plot, chips])
    with gr.Tab("About"):
        gr.Markdown(ABOUT_MD)

demo.queue(max_size=10, default_concurrency_limit=1)

if __name__ == "__main__":
    demo.launch(max_file_size="30mb")
