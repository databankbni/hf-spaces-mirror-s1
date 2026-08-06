"""app.py -- DeviceWiki Underwriter, public HuggingFace Space.

PUBLIC-SAFE APPLICATION. Consumes pre-compiled, hash-verified artifacts
(verified_rules.json, provenance_map.json, taxonomy_compiled.json,
coverage_report.json, canned_sessions.json). Contains no rule compilation,
no knowledge ingestion, no verification logic.

Env:
  ZHIPUAI_API_KEY : HF Space secret; enables the live photo assessment.
  DWU_MOCK=1      : local testing without API (mock VLM reports).

ASCII only.
"""

import json
import os
import random
import string

import gradio as gr

from decision_engine import DecisionEngine, load_rules
from prompt_builder import build_prompt, load_taxonomy
from reconcile import get_view_report, reconcile
from vlm_client import VLMClient
from fusion_ds import fraud_band

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "artifacts")
AUDIT = os.environ.get("DWU_AUDIT_PATH", "/tmp/dwu_audit.jsonl")

RULES = load_rules(os.path.join(ART, "verified_rules.json"))
PROV = json.load(open(os.path.join(ART, "provenance_map.json"), encoding="ascii"))
TAXONOMY = load_taxonomy(ART)
COVERAGE = json.load(open(os.path.join(ART, "coverage_report.json"), encoding="ascii"))
CANNED = json.load(open(os.path.join(ART, "canned_sessions.json"), encoding="ascii"))
ABOUT_MD = open(os.path.join(HERE, "about_content.md"), encoding="utf-8").read()

ENGINE = DecisionEngine(RULES, audit_path=AUDIT)
MOCK = os.environ.get("DWU_MOCK") == "1"
HAS_KEY = bool(os.environ.get("ZHIPUAI_API_KEY")) or MOCK

MODELS = sorted(RULES["catalog"].keys())
TIERS = RULES["plan_tiers"]
TO_VERIFY = sum(1 for a in PROV.values() if "TO-VERIFY" in a.get("locator", ""))

VERDICT_BADGE = {
    "eligible": "### :green[ELIGIBLE]",
    "ineligible": "### :red[INELIGIBLE]",
    "refer": "### :orange[REFER TO HUMAN REVIEW]",
}


def new_code():
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    return "".join(random.choice(alphabet) for _ in range(6))


def render_verdict(verdict, warnings, fraud_detail=None):
    lines = [VERDICT_BADGE.get(verdict["verdict"], verdict["verdict"])]
    if verdict.get("tier"):
        lines.append("**Plan tier:** " + verdict["tier"])
    if verdict.get("endorsements"):
        lines.append("**Endorsements attached:** "
                     + ", ".join(e["name"].replace("_", " ")
                                 for e in verdict["endorsements"]))
    if verdict.get("reasons"):
        lines.append("**Reasons:** "
                     + ", ".join(r.replace("_", " ") for r in verdict["reasons"]))
    if verdict.get("missing_slots"):
        lines.append("**Missing inputs:** " + ", ".join(verdict["missing_slots"]))
    if fraud_detail:
        lines.append("**Fraud belief (DS fusion):** band `%s`, Bel=%.2f, Pl=%.2f "
                     "(hand-set priors, pre-calibration)"
                     % (fraud_detail["band"], fraud_detail["bel_fraud"],
                        fraud_detail["pl_fraud"]))
    if warnings:
        lines.append("\n**Notes:**")
        for w in warnings:
            lines.append("- " + w)
    lines.append("\n---\n#### Why (every rule, its clause, its source)")
    for aid in verdict.get("assertions", []):
        a = PROV.get(aid, {})
        lines.append("- **[%s]** %s  \n  *source: %s | %s*"
                     % (aid, a.get("statement", "?"),
                        a.get("source_doc", "?"), a.get("locator", "?")))
    lines.append("\n`engine %s | rules sha256 %s`"
                 % (verdict.get("engine_version", ""),
                    verdict.get("rules_sha256", "")[:16]))
    return "\n\n".join(lines)


def findings_rows(damage):
    return [[d["component"], d["type"], d["severity"], d["status"],
             d["confidence"]] for d in damage] or [["-", "no damage found",
                                                    "-", "-", "-"]]


def assess(model, months, tier, prior, img_off, img_on, img_back,
           skip_challenge, code):
    if not HAS_KEY:
        return ("**Live assessment is disabled on this deployment** "
                "(no vision-model key configured). Use the Safety gate demo "
                "tab to explore the decision behaviour."), [], gr.update()
    if not any([img_off, img_on, img_back]):
        return ("Please upload at least the two front photos "
                "(screen off, screen on)."), [], gr.update()

    client = VLMClient(mock=MOCK, challenge_code=code)
    reports, raws_note = {}, []
    for view, img in (("front_off", img_off), ("front_on", img_on),
                      ("back", img_back)):
        if img is None:
            reports[view] = None
            continue
        prompt = build_prompt(TAXONOMY, view)
        rep, _raws, err = get_view_report(client, TAXONOMY, view, img, prompt)
        if rep is None:
            raws_note.append("view %s: model output invalid after retry (%s)"
                             % (view, err))
        reports[view] = rep

    challenge_arg = "SKIPPED" if skip_challenge else code
    fragment, warnings = reconcile(reports, challenge_arg)
    warnings = raws_note + warnings

    # DS fusion overrides the placeholder band (unless simulated skip)
    fraud_detail = None
    if skip_challenge:
        fragment["fraud_band"] = "accept"
        warnings.append("challenge SKIPPED: fraud channel SIMULATED as accept "
                        "(demo mode)")
    else:
        n_valid = sum(1 for v in reports.values() if v is not None)
        status = "pass" if fragment["challenge_verified"] else "fail"
        b, fraud_detail = fusion_override(status, n_valid)
        fragment["fraud_band"] = b

    session = dict(fragment)
    session["session_id"] = "space"
    session["declared"] = {"model": model, "purchase_months_ago": int(months),
                           "requested_tier": tier, "prior_repair": prior}
    verdict = ENGINE.decide(session)
    return (render_verdict(verdict, warnings, fraud_detail),
            findings_rows(fragment["damage"]),
            gr.update(value=new_code()))


def fusion_override(status, n_valid):
    return fraud_band(status, n_valid)


def run_canned(name):
    case = next(c for c in CANNED if c["name"] == name)
    verdict = ENGINE.decide(dict(case["session"], session_id="demo_" + name))
    header = "**Scenario:** %s\n\n" % case["description"]
    return header + render_verdict(verdict, [])


INTRO = """
# DeviceWiki Underwriter

**Photograph a used phone. Get an underwriting decision you can audit.**

An AI vision model describes the damage -- but it never decides. The decision
comes from a pre-compiled rule base that has been machine-checked so that no
two rules contradict each other and every possible case has a defined outcome.
Every verdict cites the exact rule and source document behind it, and anything
uncertain goes to human review, never to silent approval.

**60-second tour:** open *Safety gate demo* and run two or three canned
scenarios to see the three verdict types and their full provenance -- no
photos needed. Then try *Assess a device* with your own phone. Details,
honest limitations and live verification numbers are under *About*.
"""


def build_ui():
    with gr.Blocks(title="DeviceWiki Underwriter") as demo:
        gr.Markdown(INTRO)
        with gr.Tabs():
            with gr.Tab("Assess a device"):
                gr.Markdown(
                    "Three photos of the SAME phone, taken with a second "
                    "device, whole phone in frame: **1)** front, screen off; "
                    "**2)** front, screen on, showing the challenge code "
                    "below typed large in a notes app; **3)** back.")
                code_box = gr.Textbox(value=new_code(),
                                      label="Challenge code (display this on "
                                            "the phone's screen for photo 2)",
                                      interactive=False)
                with gr.Row():
                    model = gr.Dropdown(MODELS, value=MODELS[0],
                                        label="Device model")
                    months = gr.Slider(0, 72, value=10, step=1,
                                       label="Months since purchase")
                with gr.Row():
                    tier = gr.Radio(TIERS, value="standard",
                                    label="Requested plan tier")
                    prior = gr.Dropdown(["none", "screen", "battery",
                                         "other", "unknown"],
                                        value="unknown",
                                        label="Prior repairs (declared)")
                with gr.Row():
                    img_off = gr.Image(type="filepath",
                                       label="1. Front, screen OFF")
                    img_on = gr.Image(type="filepath",
                                      label="2. Front, screen ON + code")
                    img_back = gr.Image(type="filepath", label="3. Back")
                skip = gr.Checkbox(label="Skip challenge verification "
                                         "(demo mode; result marked simulated)")
                btn = gr.Button("Assess", variant="primary")
                out_md = gr.Markdown()
                out_tbl = gr.Dataframe(
                    headers=["component", "type", "severity", "status",
                             "confidence"],
                    label="Reconciled findings", interactive=False)
                btn.click(assess,
                          [model, months, tier, prior, img_off, img_on,
                           img_back, skip, code_box],
                          [out_md, out_tbl, code_box])

            with gr.Tab("Safety gate demo"):
                gr.Markdown(
                    "Ten pre-built scenarios exercise the decision layer "
                    "directly (no photos, no AI calls). Watch how the system "
                    "refuses to guess, downgrades unconfirmed evidence, and "
                    "attaches endorsements instead of blanket rejections.")
                pick = gr.Dropdown([c["name"] for c in CANNED],
                                   value=CANNED[0]["name"], label="Scenario")
                run = gr.Button("Run scenario")
                demo_md = gr.Markdown()
                run.click(run_canned, [pick], [demo_md])

            with gr.Tab("About"):
                gr.Markdown(ABOUT_MD)
                gr.Markdown(
                    "#### Live verification numbers (from the shipped, "
                    "hash-verified artifact)\n"
                    "- assertions in the underwriting wiki: **%d** "
                    "(%d locators still marked TO-VERIFY -- shown honestly "
                    "until source collection completes)\n"
                    "- decision-matrix cells enumerated at compile time: "
                    "**%d**, cells without a defined outcome: **%d**\n"
                    "- rule artifact sha256: `%s`"
                    % (len(PROV), TO_VERIFY, COVERAGE["cells"],
                       len(COVERAGE["uncovered_cells"]),
                       RULES.get("_sha256", "")[:16]))
    return demo


if __name__ == "__main__":
    build_ui().launch(server_name="0.0.0.0", server_port=7860)
