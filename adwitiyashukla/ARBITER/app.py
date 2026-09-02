from __future__ import annotations

import html
import io
import json
import os
import sys

import cv2
import gradio as gr
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from arbiter.benchmark import load_suite
from arbiter.judge import build_payload
from arbiter.oracle.visual import (ACTIVE_RATIO_LIMIT, CONCENTRATION_LIMIT,
                                   MOTION_EPS, NOOP_EPS, analyze_burst)
from arbiter.persist import signal_from_dict, step_from_dict

DATA = os.path.join(HERE, "data")
REPO = "https://github.com/adwitiyashukla/ARBITER"
PAGES = "https://adwitiyashukla.github.io/ARBITER/"

with open(os.path.join(DATA, "results.json"), encoding="utf-8") as fh:
    RESULTS = json.load(fh)
with open(os.path.join(DATA, "judge_audit.json"), encoding="utf-8") as fh:
    AUDIT = json.load(fh)

SPECS = {s.id: s for s in load_suite(os.path.join(DATA, "bugs"))}
BUGS = {b["id"]: b for b in RESULTS["bugs"]}
BUG_IDS = sorted(BUGS)
METRICS = RESULTS["metrics"]

MAX_ANALYSIS_FRAMES = 24

BG, CARD, LINE = "#0f1319", "#161c25", "#242e3b"
FG, MUTED = "#e6eaf0", "#94a3b8"
GOOD, BAD, WARN, ACCENT = "#34d399", "#f87171", "#fbbf24", "#60a5fa"

CSS = """
.gradio-container {
  max-width: 1180px !important;
  --body-background-fill: #0f1319;
  --background-fill-primary: #161c25;
  --background-fill-secondary: #131922;
  --block-background-fill: #161c25;
  --block-border-color: #242e3b;
  --border-color-primary: #242e3b;
  --body-text-color: #e6eaf0;
  --body-text-color-subdued: #94a3b8;
  --block-label-text-color: #94a3b8;
  --block-title-text-color: #e6eaf0;
  --input-background-fill: #0f1319;
  --link-text-color: #60a5fa;
  --link-text-color-hover: #93c5fd;
}
.arb-hero { padding: 4px 2px 14px; }
.arb-hero h1 { font-size: 34px; margin: 0 0 2px; letter-spacing: -.02em; color: #e6eaf0; }
.arb-hero .sub { color: #94a3b8; font-size: 15px; margin-bottom: 14px; }
.arb-hero p { color: #cbd5e1; max-width: 70ch; line-height: 1.6; }
.arb-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
             gap: 10px; margin: 16px 0 6px; }
.arb-card { background: #161c25; border: 1px solid #242e3b; border-radius: 10px;
            padding: 12px 14px; }
.arb-card .v { font-size: 24px; font-weight: 650; letter-spacing: -.02em; color: #e6eaf0; }
.arb-card .k { color: #94a3b8; font-size: 11px; text-transform: uppercase;
               letter-spacing: .06em; margin-top: 2px; }
.arb-panel { background: #161c25; border: 1px solid #242e3b; border-radius: 10px;
             padding: 16px 18px; color: #e6eaf0; line-height: 1.6; }
.arb-panel h2 { font-size: 20px; margin: 0 0 6px; letter-spacing: -.01em; }
.arb-panel h3 { font-size: 15px; margin: 18px 0 6px; color: #cbd5e1; }
.arb-panel p { color: #cbd5e1; }
.arb-meta { color: #94a3b8; font-size: 13px; margin-bottom: 10px; }
.arb-quote { border-left: 2px solid #2f3a47; padding-left: 12px; color: #94a3b8;
             font-size: 13px; margin: 8px 0 14px; }
.arb-report { background: #0b0f14; border: 1px solid #242e3b; border-radius: 8px;
              padding: 12px 14px; white-space: pre-wrap; font-size: 12.5px;
              color: #cbd5e1; font-family: ui-monospace, Consolas, monospace; }
.arb-trial { border-left: 2px solid #242e3b; padding: 4px 0 4px 14px; margin: 14px 0; }
.arb-trial .who { color: #94a3b8; font-size: 13px; }
.arb-pill { display: inline-block; padding: 2px 9px; border-radius: 99px; font-size: 12px;
            font-weight: 600; }
.arb-ok { background: rgba(52,211,153,.15); color: #34d399; }
.arb-no { background: rgba(248,113,113,.15); color: #f87171; }
.arb-mid { background: rgba(251,191,36,.15); color: #fbbf24; }
.arb-dim { background: rgba(148,163,184,.15); color: #94a3b8; }
.arb-sig { font-family: ui-monospace, Consolas, monospace; font-size: 12px; color: #94a3b8;
           margin-top: 6px; }
.arb-table { width: 100%; border-collapse: collapse; font-size: 13.5px; margin-top: 10px; }
.arb-table th { text-align: left; color: #94a3b8; font-size: 11px; text-transform: uppercase;
                letter-spacing: .05em; padding: 8px 10px; border-bottom: 1px solid #242e3b; }
.arb-table td { padding: 8px 10px; border-bottom: 1px solid #1d242e; vertical-align: top; }
.arb-table tr:last-child td { border-bottom: none; }
.arb-code { font-family: ui-monospace, Consolas, monospace; background: #0b0f14;
            padding: 1px 6px; border-radius: 4px; font-size: 12.5px; color: #cbd5e1; }
"""


def esc(text) -> str:
    return html.escape(str(text))


def pill(text: str, kind: str = "dim") -> str:
    return '<span class="arb-pill arb-{0}">{1}</span>'.format(kind, esc(text))


def outcome_kind(outcome: str) -> str:
    return {"CONFIRMED": "ok", "REJECTED": "no", "DISPUTED": "mid",
            "AGREED_NOT_REPRODUCED": "ok", "UNRESOLVED": "mid"}.get(outcome, "dim")


def hero_html() -> str:
    m = METRICS
    cards = [
        ("{0}/{1}".format(m["reproduced"], m["seeded_bugs"]), "seeded bugs reproduced"),
        ("{0}/{1}".format(m["false_positives"], m["controls"]), "false positives on controls"),
        ("{0:.0%}".format(m["accuracy"]), "overall accuracy"),
        ("{0} to {1}".format(m["actor_claimed"], m["judge_confirmed"]), "claims to confirmations"),
        ("{0}/{1}".format(AUDIT["refused"], AUDIT["pairs"]), "adversarial audit refused"),
        ("${0:.4f}".format(m["cost"]["usd"]), "total cost"),
    ]
    card_html = "".join(
        '<div class="arb-card"><div class="v">{0}</div><div class="k">{1}</div></div>'.format(
            esc(v), esc(k)) for v, k in cards)
    return """<div class="arb-hero">
  <h1>ARBITER</h1>
  <div class="sub">Automated Reproduction of Bugs with Independent Trial Evidence Review</div>
  <p>An LLM agent reads a bug report, drives a real browser to reproduce it, and then has to
  convince a <b>separate model that never sees its reasoning</b> that the evidence actually shows
  the reported symptom. A claim the judge cannot verify does not count.</p>
  <div class="arb-cards">{0}</div>
  <p style="font-size:13px;color:#94a3b8;margin-top:10px">
    Every tab below runs the project's own code, with no API key, because none of these paths
    call a language model. &nbsp;|&nbsp;
    <a href="{1}">Source</a> &nbsp;|&nbsp; <a href="{2}">Full HTML report</a>
  </p>
</div>""".format(card_html, REPO, PAGES)


def header_markdown() -> str:
    m = METRICS
    return ("ARBITER: {0}/{1} seeded bugs reproduced, {2}/{3} false positives, "
            "accuracy {4:.0%}, {5} claims to {6} confirmations, ${7:.4f}.").format(
        m["reproduced"], m["seeded_bugs"], m["false_positives"], m["controls"],
        m["accuracy"], m["actor_claimed"], m["judge_confirmed"], m["cost"]["usd"])


def evidence_dir_for(bug_id: str, trial: int = 0) -> str:
    return os.path.join(DATA, "evidence", bug_id, "t{0}".format(trial))


def show_bug(bug_id: str):
    bug = BUGS[bug_id]
    spec = SPECS.get(bug_id)
    truth = "a real seeded bug" if not bug["control"] else "no bug, this report is mistaken"
    verdict_kind = "ok" if bug["correct"] else "no"

    parts = ['<div class="arb-panel">',
             "<h2>{0}</h2>".format(esc(spec.title if spec else bug_id)),
             '<div class="arb-meta"><span class="arb-code">{0}</span> &nbsp;|&nbsp; {1} '
             "&nbsp;|&nbsp; ground truth: {2} &nbsp;|&nbsp; {3}</div>".format(
                 esc(bug_id), esc(bug["category"]), esc(truth),
                 pill(bug["verdict"].lower().replace("_", " "), verdict_kind))]
    if spec and spec.pattern:
        parts.append('<div class="arb-quote">{0}</div>'.format(esc(spec.pattern)))
    parts += ["<h3>The report as filed</h3>",
              '<div class="arb-report">{0}</div>'.format(
                  esc(spec.report.strip() if spec else "(unavailable)")),
              "<h3>Outcome</h3>",
              "<p>{0} of {1} trials judge-confirmed, stability <b>{2}</b>. The actor claimed a "
              "reproduction in {3} trial(s); the judge confirmed {4}.</p>".format(
                  bug["judge_confirmed"], len(bug["trials"]), esc(bug["stability"]),
                  bug["actor_claimed"], bug["judge_confirmed"])]

    for t in bug["trials"]:
        hard = [s for s in t["signals"] if s.get("severity") == "hard"]
        parts.append('<div class="arb-trial">')
        parts.append("<div><b>Trial {0}</b> &nbsp; {1} &nbsp; <span class=\"arb-meta\">"
                     "{2} step(s), {3:.0f}s</span></div>".format(
                         t["trial_index"] + 1,
                         pill(t["outcome"].lower().replace("_", " "), outcome_kind(t["outcome"])),
                         len(t["steps"]), t.get("duration_s", 0.0)))
        parts.append('<div class="who">actor said <b>{0}</b>: {1}</div>'.format(
            esc(t["actor_verdict"]), esc(t["actor_reason"])))
        parts.append('<div class="who">judge said <b>{0}</b> (confidence {1:.2f}): {2}</div>'.format(
            esc(t["judge_verdict"]), t.get("judge_confidence", 0.0), esc(t["judge_reason"])))
        if hard:
            parts.append('<div class="arb-sig">{0}</div>'.format(
                esc(" | ".join(s["detail"] for s in hard))))
        parts.append("</div>")
    parts.append("</div>")

    gallery = []
    d = evidence_dir_for(bug_id, 0)
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.endswith(".png"):
                gallery.append((os.path.join(d, name),
                                name.replace("_", " ").replace(".png", "")))
    return "".join(parts), gallery


def _box_frame(x: int, width: int = 320, height: int = 120) -> np.ndarray:
    f = np.full((height, width), 240, dtype=np.uint8)
    x0 = max(0, min(width - 1, x))
    f[20:height - 20, x0:min(width, x0 + 80)] = 20
    return f


def example_frames(kind: str):
    if kind == "smooth":
        return [_box_frame(i * 20) for i in range(12)]
    if kind == "stepped":
        return [_box_frame(p) for p in ([0] * 4 + [100] * 4 + [200] * 4)]
    return [_box_frame(0) for _ in range(12)]


def frames_from_video(path: str):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frames = []
    if total > 0:
        idxs = np.linspace(0, max(0, total - 1), min(MAX_ANALYSIS_FRAMES, total)).astype(int)
        wanted = set(int(i) for i in idxs)
        pos = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if pos in wanted:
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            pos += 1
    else:
        while len(frames) < MAX_ANALYSIS_FRAMES:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    cap.release()
    return frames


def plot_diffs(analysis) -> Image.Image:
    fig, ax = plt.subplots(figsize=(7.4, 3.0), dpi=140)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(CARD)
    diffs = analysis.diffs or [0.0]
    xs = list(range(1, len(diffs) + 1))
    colors = [ACCENT if d > MOTION_EPS else "#334155" for d in diffs]
    ax.bar(xs, diffs, color=colors)
    ax.axhline(MOTION_EPS, color=WARN, linewidth=1, linestyle="--",
               label="motion threshold {0}".format(MOTION_EPS))
    ax.set_xlabel("frame pair", color=MUTED, fontsize=9)
    ax.set_ylabel("mean absolute difference", color=MUTED, fontsize=9)
    ax.set_title("how the change was distributed across the clip", color=FG, fontsize=11)
    ax.tick_params(colors=MUTED, labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("bottom", "left"):
        ax.spines[side].set_color(LINE)
    leg = ax.legend(loc="upper right", fontsize=8, frameon=False)
    for text in leg.get_texts():
        text.set_color(MUTED)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def verdict_html(a) -> str:
    if a.no_op:
        title, kind = "no_op", "no"
        body = ("Nothing on screen changed. When a report says a control should do something, "
                "this is the evidence that it did not.")
    elif a.stepped:
        title, kind = "stepped_animation", "no"
        body = ("The change arrived in a few discrete jumps with still frames between them. "
                "That is what a hand-rolled timer animation looks like, and the DOM is identical "
                "either way, so a DOM-only tool cannot see it.")
    elif a.instant:
        title, kind = "instant_change", "mid"
        body = ("One frame carried the whole change. Deliberately <b>not</b> reported as jank: "
                "an un-animated update is not an animation bug. Getting that wrong is the "
                "obvious way to build a jank detector that cries wolf.")
    else:
        title, kind = "smooth", "ok"
        body = ("The change was spread evenly across the clip, which is what a real CSS "
                "transition looks like. No animation defect reported.")

    rows = [
        ("frames analysed", "{0}".format(a.frames)),
        ("total change, first to last frame",
         "{0:.4f} &nbsp;<span class='arb-meta'>no-op below {1}</span>".format(
             a.total_change, NOOP_EPS)),
        ("frame pairs carrying motion",
         "{0} of {1} &nbsp;<span class='arb-meta'>{2:.0%}, jank needs {3:.0%} or less</span>".format(
             a.motion_frames, max(1, a.frames - 1), a.active_ratio, ACTIVE_RATIO_LIMIT)),
        ("change held by the two busiest frames",
         "{0:.0%} &nbsp;<span class='arb-meta'>jank needs {1:.0%} or more</span>".format(
             a.concentration, CONCENTRATION_LIMIT)),
        ("longest run of still frames mid-transition", "{0}".format(a.max_freeze_run)),
    ]
    table = "".join("<tr><td>{0}</td><td>{1}</td></tr>".format(esc(k), v) for k, v in rows)
    return ('<div class="arb-panel"><h2>{0} {1}</h2><p>{2}</p>'
            '<table class="arb-table"><tr><th>measurement</th><th>value</th></tr>{3}</table>'
            "</div>").format(pill(title, kind), "", body, table)


def analyse(frames):
    if not frames or len(frames) < 2:
        return None, ('<div class="arb-panel"><p>Could not read at least two frames from that '
                      "file. Try an mp4 or webm screen recording, or use one of the built-in "
                      "examples.</p></div>")
    a = analyze_burst(frames)
    return plot_diffs(a), verdict_html(a)


def analyse_upload(video_path):
    if not video_path:
        return None, ('<div class="arb-panel"><p>Upload a screen recording first, or press one '
                      "of the built-in examples.</p></div>")
    return analyse(frames_from_video(video_path))


def analyse_example(kind: str):
    return analyse(example_frames(kind))


def isolation_view(bug_id: str, trial_label: str):
    bug = BUGS[bug_id]
    idx = max(0, min(len(bug["trials"]) - 1, int(trial_label) - 1))
    t = bug["trials"][idx]
    spec = SPECS.get(bug_id)

    steps = [step_from_dict(s) for s in t["steps"]]
    signals = [signal_from_dict(s) for s in t["signals"]]
    system, user, images, notes = build_payload(
        spec.prompt_view() if spec else bug_id, steps, signals,
        t.get("final_state") or "(not recorded in the published run)",
        evidence_dir_for(bug_id, idx))

    actor_html = ('<div class="arb-panel"><h2>What the actor concluded</h2>'
                  "<p>{0}</p><div class=\"arb-quote\">{1}</div>"
                  "<p style='font-size:13px'>This text, and every word of the actor's reasoning, "
                  "is withheld from the judge. The <span class='arb-code'>finish</span> action "
                  "that carries it is stripped out before the judge sees anything.</p>"
                  "</div>").format(pill(t["actor_verdict"],
                                        "ok" if t["actor_verdict"] == "REPRODUCED" else "dim"),
                                   esc(t["actor_reason"]))

    reason = (t["actor_reason"] or "").strip()
    leaked = bool(reason) and reason in user
    words = [w for w in reason.split() if len(w) > 6][:8]
    shared = [w for w in words if w in user]
    rows = [
        ("actor's written conclusion inside the judge payload",
         pill("LEAKED", "no") if leaked else pill("no, 0 occurrences", "ok")),
        ("distinctive words from it appearing anywhere",
         esc(", ".join(shared)) if shared else "none"),
        ("screenshots resolved in this rebuild", "{0} <span class='arb-meta'>of up to 4</span>".format(
            len(images))),
        ("payload length", "{0:,} characters".format(len(user))),
    ]
    table = "".join("<tr><td>{0}</td><td>{1}</td></tr>".format(esc(k), v) for k, v in rows)
    check_html = ('<div class="arb-panel"><h2>Live check</h2>'
                  '<table class="arb-table">{0}</table>'
                  "<p style='font-size:13px;margin-top:12px'>Shared words are expected and "
                  "harmless: the judge is looking at the same page, so it will naturally mention "
                  "the same UI elements. What matters is that the actor's conclusion is not in "
                  "there. This is the property <span class='arb-code'>tests/"
                  "test_judge_isolation.py</span> enforces in CI, and it caught a real leak the "
                  "first time it ran.</p>"
                  "<p style='font-size:12.5px;color:#94a3b8'>The screenshot count refers to this "
                  "rebuild, not to the original run. Each trial recorded its screenshots as "
                  "absolute paths on the machine that ran the benchmark, so only the images "
                  "bundled with this Space resolve here. The text of the payload is "
                  "identical.</p></div>").format(table)
    return actor_html, system + "\n\n" + ("=" * 70) + "\n\n" + user, check_html


def audit_markdown() -> str:
    rows = "".join(
        "<tr><td><span class='arb-code'>{0}</span></td>"
        "<td><span class='arb-code'>{1}</span></td><td>{2}</td><td>{3}</td></tr>".format(
            esc(r["evidence_from"]), esc(r["judged_against"]), esc(r["verdict"]),
            pill("correctly refused", "ok") if r["refused"] else pill("rubber stamped", "no"))
        for r in AUDIT["rows"])
    detail = "".join(
        "<div class='arb-trial'><div><b>{0}</b> evidence judged against the <b>{1}</b> report"
        "</div><div class='who'>{2}</div></div>".format(
            esc(r["evidence_from"]), esc(r["judged_against"]), esc(r["reasoning"]))
        for r in AUDIT["rows"])
    return ('<div class="arb-panel"><h2>Is the judge actually discriminating?</h2>'
            "<p>A judge that confirms everything is indistinguishable from no judge at all. This "
            "check takes the evidence captured for one bug and asks the judge to review it "
            "against a <b>different</b> bug's report, one that evidence cannot support.</p>"
            "<p><b>{0} of {1} mismatched pairs correctly refused.</b> Judge model "
            "<span class='arb-code'>{2}</span>.</p>"
            "<table class='arb-table'><tr><th>evidence from</th><th>judged against</th>"
            "<th>verdict</th><th>outcome</th></tr>{3}</table>"
            "<h3>What the judge said each time</h3>{4}</div>").format(
        AUDIT["refused"], AUDIT["pairs"], esc(AUDIT["judge_model"]), rows, detail)


with gr.Blocks(title="ARBITER", css=CSS, theme=gr.themes.Base(
        primary_hue="blue", neutral_hue="slate")) as demo:
    gr.HTML(hero_html())

    with gr.Tabs():
        with gr.Tab("Benchmark results"):
            gr.HTML("<p style='color:#94a3b8;font-size:14px'>Ten reports against ten small web "
                    "apps: eight with a seeded defect and two <b>negative controls</b> whose "
                    "reports describe symptoms that do not exist. Reproducing a control counts "
                    "as a false positive.</p>")
            bug_dd = gr.Dropdown(choices=BUG_IDS, value=BUG_IDS[0], label="report")
            bug_md = gr.HTML()
            bug_gallery = gr.Gallery(label="the evidence the judge reviewed",
                                     columns=3, height=320)
            bug_dd.change(show_bug, inputs=bug_dd, outputs=[bug_md, bug_gallery])

        with gr.Tab("Frame-difference oracle"):
            gr.HTML("<p style='color:#94a3b8;font-size:14px'>This is the part that catches "
                    "animation bugs, and it is pure numpy and OpenCV, so it runs here for real. "
                    "Frames become grayscale, are downscaled, and are reduced to a series of "
                    "mean absolute differences. A smooth transition spreads its change evenly; a "
                    "hand-rolled timer animation dumps it into two or three frames and freezes "
                    "in between. Upload any screen recording, or press an example.</p>")
            with gr.Row():
                with gr.Column(scale=1):
                    video_in = gr.Video(label="your screen recording (mp4 or webm)")
                    analyse_btn = gr.Button("Analyse this clip", variant="primary")
                    smooth_btn = gr.Button("Example: a smooth transition")
                    stepped_btn = gr.Button("Example: a stepped, janky animation")
                    static_btn = gr.Button("Example: nothing happens at all")
                with gr.Column(scale=2):
                    chart = gr.Image(label="per frame-pair difference", type="pil")
                    verdict_md = gr.HTML()

            analyse_btn.click(analyse_upload, inputs=video_in, outputs=[chart, verdict_md])
            smooth_btn.click(lambda: analyse_example("smooth"), outputs=[chart, verdict_md])
            stepped_btn.click(lambda: analyse_example("stepped"), outputs=[chart, verdict_md])
            static_btn.click(lambda: analyse_example("static"), outputs=[chart, verdict_md])

        with gr.Tab("Judge isolation"):
            gr.HTML("<p style='color:#94a3b8;font-size:14px'>The whole project rests on one "
                    "property: the judge decides from evidence and never learns what the actor "
                    "concluded. Pick any real trial. The payload on the right is generated right "
                    "now by the project's own <code>build_payload</code>, the same function the "
                    "pipeline uses, over the evidence that trial actually recorded.</p>")
            with gr.Row():
                iso_bug = gr.Dropdown(choices=BUG_IDS, value="todo-crash", label="report")
                iso_trial = gr.Dropdown(choices=["1", "2", "3"], value="1", label="trial")
            with gr.Row():
                with gr.Column(scale=1):
                    iso_actor = gr.HTML()
                    iso_check = gr.HTML()
                with gr.Column(scale=2):
                    iso_payload = gr.Textbox(label="exactly what the judge received",
                                             lines=28, max_lines=28)
            iso_bug.change(isolation_view, inputs=[iso_bug, iso_trial],
                           outputs=[iso_actor, iso_payload, iso_check])
            iso_trial.change(isolation_view, inputs=[iso_bug, iso_trial],
                             outputs=[iso_actor, iso_payload, iso_check])

        with gr.Tab("Auditing the judge"):
            gr.HTML(audit_markdown())

    def _startup():
        bug_html, gallery = show_bug(BUG_IDS[0])
        actor_v, payload_v, check_v = isolation_view("todo-crash", "1")
        return bug_html, gallery, actor_v, payload_v, check_v

    demo.load(_startup, outputs=[bug_md, bug_gallery, iso_actor, iso_payload, iso_check])

if __name__ == "__main__":
    demo.launch()
