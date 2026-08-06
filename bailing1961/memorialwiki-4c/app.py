# -*- coding: ascii -*-
"""
app.py -- MemorialWiki-4C public Space shell (v0.1).

Public shell only: UI + subprocess verification runtime + public rule
catalogue. The platform core (extraction pipeline, privacy policy engine,
audit log, evaluation dashboard, approval workflow, deployment template)
is private and NOT part of this repository.

Every HTML element carries an explicit inline color (never rely on theme
inheritance -- Gradio theme CSS overrides inherited colors on ul/li/b/span).

ASCII-only. gradio 4.44.1, launch on 0.0.0.0:7860.
"""

import json
import os
import subprocess
import sys
import tempfile

import gradio as gr

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, "runtime", "run_verify.py")
SAMPLES_DIR = os.path.join(HERE, "samples")

SAMPLES = {
    "Demo family (7 injected error types)": "demo_family.ged",
    "Clean family (passes all checks)": "clean_family.ged",
}

# ---------------------------------------------------------------- palette
BG = "#0E1626"      # dark card background
GOLD = "#E3A741"
TEAL = "#46B7AE"
TXT = "#F2F5FA"     # near-white text on dark cards
SUB = "#B9C4D4"     # secondary text on dark cards
RED = "#E05B4F"
AMBER = "#E3A741"
GREEN = "#3FA26A"

CARD = ("background:%s; border-radius:12px; padding:18px 22px; "
        "margin-bottom:10px; border:1px solid #24314A;" % BG)


def _sp(text, color, extra=""):
    return "<span style='color:%s;%s'>%s</span>" % (color, extra, text)


INTRO_HTML = (
    "<div style='%s'>" % CARD
    + "<div style='color:%s; font-size:22px; font-weight:700; "
      "margin-bottom:6px;'>MemorialWiki-4C</div>" % GOLD
    + "<div style='color:%s; font-size:15px; margin-bottom:12px;'>"
      "A verification-first assistant for digital memorials and family "
      "history: it formally checks genealogy files for impossible facts "
      "before they ever reach a published memorial.</div>" % TXT
    + "<ul style='color:%s; margin:0 0 4px 18px; padding:0;'>" % TXT
    + "<li style='color:%s; margin-bottom:5px;'>%s a GEDCOM family-tree "
      "file (the open standard exported by Ancestry, FamilySearch, "
      "Gramps and most genealogy tools), or pick a built-in sample."
      "</li>" % (TXT, _sp("<b style='color:%s'>Input:</b>" % TEAL, TEAL))
    + "<li style='color:%s; margin-bottom:5px;'>%s a verdict "
      "(PASS / REVIEW / REJECT) with every finding explained in plain "
      "language, plus a downloadable JSON report.</li>"
      % (TXT, _sp("<b style='color:%s'>Output:</b>" % TEAL, TEAL))
    + "<li style='color:%s; margin-bottom:5px;'>%s 20 formal rules "
      "(12 hard violations, 8 review warnings) proved by a symbolic "
      "logic engine -- not guessed by an LLM. Partial dates are handled "
      "conservatively: the checker never invents what it does not know."
      "</li>"
      % (TXT, _sp("<b style='color:%s'>How:</b>" % TEAL, TEAL))
    + "</ul></div>"
)

TOUR_MD = """
**60-second tour**

1. Open the **Verify a family tree** tab (you are on it).
2. Pick *Demo family (7 injected error types)* and press **Run verification**.
3. Read the verdict banner, then the three sections: impossible facts
   (violations), implausible facts (warnings), and missing information
   (completeness gaps).
4. Switch the sample to *Clean family* and run again to see a PASS.
5. Upload your own GEDCOM export if you have one -- it is processed in
   memory for this check only and is not stored.
6. The **Rule catalogue** tab lists every public check; the **About** tab
   explains the project in plain language.
"""

SAFETY_MD = """
- **No storage of your data.** Uploaded files are verified in a temporary
  workspace and discarded; nothing is retained after the check.
- **Verification only.** This demo checks logical consistency of dates and
  relationships. It does not provide legal, medical or genealogical advice.
- **Conservative by design.** When dates are partial or missing, the checker
  reports *undetermined* or a *completeness gap* -- it never guesses, and it
  never fabricates a fact about a person.
- **Not affiliated** with any memorial platform or genealogy service.
- **Demo scope.** The public Space carries the open rule subset. The full
  platform (narrative fact extraction, privacy policy verification, audit
  log, human approval workflow) is a separate private system.
"""

RULES_PUBLIC = [
    ("V01", "violation", "Death recorded before birth"),
    ("V02", "violation", "Ancestry cycle (person is their own ancestor)"),
    ("V03", "violation", "Parent born after their child"),
    ("V04", "violation", "Parent provably under 12 at child's birth"),
    ("V05", "violation", "Mother provably over 70 at child's birth"),
    ("V06", "violation", "Child born after mother's death"),
    ("V07", "violation", "Child born >1 year after father's death"),
    ("V08", "violation", "Lifespan provably exceeds 125 years"),
    ("V09", "violation", "Marriage dated after a spouse's death"),
    ("V10", "violation", "Marriage dated before a spouse's birth"),
    ("V11", "violation", "Same person as both husband and wife"),
    ("V12", "violation", "Same person as both spouse and child"),
    ("W01", "warning", "Parent aged 12-15 at child's birth"),
    ("W02", "warning", "Mother aged 56-70 at child's birth"),
    ("W03", "warning", "Lifespan of 111-125 years"),
    ("W04", "warning", "Married under 16"),
    ("W05", "warning", "Husband recorded with sex F"),
    ("W06", "warning", "Wife recorded with sex M"),
    ("W07", "warning", "Father over 80 at child's birth"),
    ("W08", "warning", "A finding relies on an approximate date"),
]

ABOUT_MD = """
## What problem does this solve?

Online memorials and family-history pages are usually written by several
family members together. People mis-remember years, mix up relatives, and
mistype dates. On most platforms nobody notices until a visitor spots that
grandma apparently died before she was born, or that an uncle is listed as
his own great-grandfather. On a memorial page, errors like these are
painful, not just embarrassing.

MemorialWiki-4C is the checking layer those platforms do not have. It takes
a standard family-tree file and *proves*, with a logic engine, whether the
recorded facts can all be true at the same time.

## Who is it for?

- Families preparing an online memorial or tribute page.
- Funeral service providers and memorial platforms that publish
  family-submitted content.
- Family-history hobbyists who want a sanity check on their tree file.

## What do I put in, and what do I get out?

**In:** one GEDCOM file (.ged) -- the standard export format of essentially
every genealogy tool.

**Out:** a verdict (PASS / REVIEW / REJECT), a plain-language list of every
impossible fact, every implausible fact worth a second look, and every gap
where information is missing, plus a machine-readable JSON report.

## What are the safety boundaries?

Your file is checked in memory and not stored. The tool only verifies
logical consistency -- it does not offer advice, it does not add facts, and
when information is incomplete it says so instead of guessing.

## How it works (one paragraph)

The file is compiled into logical facts and checked against a catalogue of
formal genealogy rules by a symbolic reasoning engine (Prolog). Rules fire
only when a problem is *provable* from the known parts of the data:
year-only dates are compared conservatively, and an ancestry loop is
detected even in deliberately corrupted files. This "prove, don't guess"
approach is the project's 4C methodology -- Correct, Consistent, Current,
Complete -- applied to biographical knowledge, where a fabricated detail
about a real person is the one failure a system must never produce.
"""


def _findings_html(items, color, empty_text):
    if not items:
        return ("<div style='%s'><span style='color:%s'>%s</span></div>"
                % (CARD, SUB, empty_text))
    lis = "".join(
        "<li style='color:%s; margin-bottom:6px;'>"
        "<b style='color:%s'>[%s]</b> "
        "<span style='color:%s'>%s</span></li>"
        % (TXT, color, it["code"], TXT, it["message"])
        for it in items)
    return ("<div style='%s'><ul style='color:%s; margin:0 0 0 18px; "
            "padding:0;'>%s</ul></div>" % (CARD, TXT, lis))


def _banner(verdict, summary):
    colors = {"PASS": GREEN, "REVIEW": AMBER, "REJECT": RED}
    c = colors.get(verdict, SUB)
    return ("<div style='background:%s; border-radius:12px; padding:14px "
            "22px; margin-bottom:10px;'>"
            "<span style='color:#FFFFFF; font-size:20px; font-weight:700;'>"
            "VERDICT: %s</span>"
            "<span style='color:#FFFFFF; font-size:14px; margin-left:16px;'>"
            "%d violations, %d warnings, %d completeness gaps</span></div>"
            % (c, verdict, summary["violations"], summary["warnings"],
               summary["completeness_gaps"]))


def run_verification(uploaded, sample_name):
    if uploaded:
        path = uploaded
    else:
        path = os.path.join(SAMPLES_DIR, SAMPLES[sample_name])
    proc = subprocess.run(
        [sys.executable, RUNTIME, path],
        capture_output=True, text=True, timeout=120)
    try:
        rep = json.loads(proc.stdout)
    except json.JSONDecodeError:
        rep = {"error": "verifier produced no output: %s" % proc.stderr[-400:]}

    if "error" in rep:
        err = ("<div style='%s'><span style='color:%s'>Could not verify "
               "this file: %s</span></div>" % (CARD, RED, rep["error"]))
        return err, "", "", "", None

    banner = _banner(rep["summary"]["verdict"], rep["summary"])
    v_html = _findings_html(rep["violations"], RED,
                            "No impossible facts found.")
    w_html = _findings_html(rep["warnings"], AMBER,
                            "No implausible facts flagged.")
    g_html = _findings_html(
        [{"code": g["gap"], "message": g["message"]}
         for g in rep["completeness_gaps"]],
        TEAL, "No completeness gaps.")

    fd, json_path = tempfile.mkstemp(suffix="_report.json")
    with os.fdopen(fd, "w") as f:
        json.dump(rep, f, indent=2)
    return banner, v_html, w_html, g_html, json_path


def _rules_table_html():
    rows = []
    for rid, sev, desc in RULES_PUBLIC:
        c = RED if sev == "violation" else AMBER
        rows.append(
            "<tr>"
            "<td style='color:%s; padding:4px 12px; font-weight:700;'>%s"
            "</td>"
            "<td style='color:%s; padding:4px 12px;'>%s</td>"
            "<td style='color:%s; padding:4px 12px;'>%s</td></tr>"
            % (c, rid, c, sev, TXT, desc))
    return ("<div style='%s'><table style='border-collapse:collapse;'>"
            "<tr>"
            "<th style='color:%s; text-align:left; padding:4px 12px;'>Rule"
            "</th>"
            "<th style='color:%s; text-align:left; padding:4px 12px;'>"
            "Severity</th>"
            "<th style='color:%s; text-align:left; padding:4px 12px;'>"
            "What it checks</th></tr>%s</table>"
            "<div style='color:%s; margin-top:10px; font-size:13px;'>"
            "All rules are proved by the symbolic engine from known date "
            "components only. The private platform adds extended rule "
            "packs, narrative extraction and policy verification on top "
            "of this public subset.</div></div>"
            % (CARD, GOLD, GOLD, GOLD, "".join(rows), SUB))


def build_ui():
    with gr.Blocks(title="MemorialWiki-4C") as demo:
        gr.HTML(INTRO_HTML)
        with gr.Tab("Verify a family tree"):
            with gr.Accordion("Safety boundaries (please read)", open=True):
                gr.Markdown(SAFETY_MD)
            with gr.Accordion("60-second tour", open=False):
                gr.Markdown(TOUR_MD)
            with gr.Row():
                with gr.Column(scale=1):
                    sample = gr.Dropdown(
                        choices=list(SAMPLES.keys()),
                        value=list(SAMPLES.keys())[0],
                        label="Built-in sample")
                    upload = gr.File(
                        label="...or upload your own GEDCOM (.ged)",
                        file_types=[".ged"], type="filepath")
                    btn = gr.Button("Run verification", variant="primary")
                with gr.Column(scale=2):
                    banner = gr.HTML()
            gr.Markdown("### Impossible facts (violations)")
            v_out = gr.HTML()
            gr.Markdown("### Implausible facts (warnings)")
            w_out = gr.HTML()
            gr.Markdown("### Missing information (completeness gaps)")
            g_out = gr.HTML()
            report_file = gr.File(label="Download JSON report")
            btn.click(run_verification, [upload, sample],
                      [banner, v_out, w_out, g_out, report_file])
        with gr.Tab("Rule catalogue"):
            gr.HTML(_rules_table_html())
        with gr.Tab("About"):
            gr.Markdown(ABOUT_MD)
    return demo


if __name__ == "__main__":
    ui = build_ui()
    ui.launch(server_name="0.0.0.0", server_port=7860)
