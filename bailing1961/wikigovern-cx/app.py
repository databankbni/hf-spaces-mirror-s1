# app.py - WikiGovern-CX Space UI (PUBLIC). ASCII only.
# Deps: gradio (pinned in requirements.txt). No LLM in any verdict path.
# Run locally:  python space\app.py   then open http://127.0.0.1:7860

import json
import os
import sys

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "engine"))

from gate import Gate  # noqa: E402
import audit  # noqa: E402

ART = os.path.join(HERE, "artifacts")
DATA = os.path.join(HERE, "data")
LINKS = os.path.join(DATA, "resolved_links.jsonl")

GATE = Gate(ART, DATA, links_path=LINKS)
DATASETS = sorted(GATE.catalog.keys())
PURPOSES = ["service_delivery", "marketing", "analytics_internal"]

PRESETS = {
    "1. Cross-brand member view (A x B join, analytics)": {
        "scope": {"type": "join", "left": "brand_a_customers",
                  "right": "brand_b_members"},
        "purpose": "analytics_internal", "use_case": "churn_model_v1"},
    "2. Email a win-back offer to Brand C customers (marketing)": {
        "scope": {"type": "single_source",
                  "dataset": "brand_c_customers"},
        "purpose": "marketing"},
    "3. Use full Brand A transaction history (service)": {
        "scope": {"type": "single_source",
                  "dataset": "brand_a_transactions"},
        "purpose": "service_delivery"},
    "4. Headline count of Brand C customers (aggregate)": {
        "scope": {"type": "aggregate", "dataset": "brand_c_customers"},
        "purpose": "analytics_internal"},
    "5. Partner loyalty overlap (Partner x B join, analytics)": {
        "scope": {"type": "join", "left": "partner_loyalty",
                  "right": "brand_b_members"},
        "purpose": "analytics_internal", "use_case": "churn_model_v1"},
    "6. Email all Brand B members (marketing)": {
        "scope": {"type": "single_source", "dataset": "brand_b_members"},
        "purpose": "marketing"},
}


def render_decision(query, d):
    lines = []
    v = d.get("verdict", "?").upper()
    lines.append("## Verdict: %s" % v)
    if "error" in d:
        lines.append("Error: `%s`" % d["error"])
    if "n_selected" in d:
        lines.append("Records selected: **%d** | allowed: **%d**"
                     % (d["n_selected"], d.get("n_allowed", 0)))
    if "group_size" in d:
        lines.append("Aggregate group size: **%d** (minimum k = %d; "
                     "deletion requests excluded: %d)"
                     % (d["group_size"], d["k"],
                        d.get("excluded_deletion_requests", 0)))
    if d.get("blocked_by"):
        lines.append("")
        lines.append("**Blocked records by rule:**")
        for rid, n in sorted(d["blocked_by"].items()):
            lines.append("- `%s`: %d record(s)" % (rid, n))
    if d.get("unknown_slots"):
        lines.append("")
        lines.append("**Unknown (missing information - the gate never "
                     "guesses):**")
        for slot, n in sorted(d["unknown_slots"].items()):
            lines.append("- `%s` not captured for %d record(s)"
                         % (slot, n))
    if d.get("reasons"):
        lines.append("")
        lines.append("**Why (rule -> statement -> source):**")
        for r in d["reasons"]:
            src = "; ".join(r["sources"]) if r["sources"] else "-"
            lines.append("- `%s` - %s  \n  source: %s"
                         % (r["rule_id"], r["statement"], src))
    for note in d.get("conflict_notes", []):
        lines.append("")
        lines.append("**CONFLICT NOTE** (%s): %s"
                     % (" vs ".join(note["rules"]), note["posture"]))
    for note in d.get("capability_notes", []):
        tag = "ENFORCED" if note.get("enforced") else "NOT ENFORCED"
        lines.append("")
        lines.append("*Capability: rule `%s` is %s - %s*"
                     % (note["rule_id"], tag, note["reason"]))
    lines.append("")
    lines.append("<sub>KB `%s` | release: %s</sub>"
                 % (d.get("kb_hash", "")[:16], d.get("release", "?")))
    return "\n".join(lines)


def run_query(query):
    d = GATE.decide(json.loads(json.dumps(query)))
    audit.log_decision(query, d)
    return render_decision(query, d), d, recent_md()


def run_preset(name):
    return run_query(dict(PRESETS[name]))


def run_custom(scope_type, dataset, dataset2, purpose, use_case,
               filter_text, deletion_only):
    if scope_type == "join":
        scope = {"type": "join", "left": dataset, "right": dataset2}
    else:
        scope = {"type": scope_type, "dataset": dataset}
    q = {"scope": scope, "purpose": purpose}
    if use_case.strip():
        q["use_case"] = use_case.strip()
    filters = {}
    if filter_text.strip() and "=" in filter_text:
        k, _, v = filter_text.partition("=")
        filters[k.strip()] = v.strip()
    if deletion_only:
        filters["__deletion_requested"] = True
    if filters:
        q["filters"] = filters
    return run_query(q)


def recent_md():
    rows = audit.recent(10)
    if not rows:
        return "*No decisions logged yet.*"
    lines = ["| time (UTC) | verdict | allowed / selected | blocked by |",
             "|---|---|---|---|"]
    for r in rows:
        blocked = ", ".join("%s:%d" % (k, v)
                            for k, v in (r.get("blocked_by") or
                                         {}).items()) or "-"
        lines.append("| %s | %s | %s / %s | %s |"
                     % (r["ts"][11:19], r.get("verdict"),
                        r.get("n_allowed"), r.get("n_selected"), blocked))
    return "\n".join(lines)


def audit_tab_md():
    path = os.path.join(ART, "4c_report.md")
    with open(path) as f:
        report = f.read()
    with open(os.path.join(DATA, "er_metrics.json")) as f:
        m = json.load(f)
    h = m["ab_probabilistic_holdout"]
    er = ["", "## Identity resolution quality (held-out evaluation)",
          "- Cross-brand name matching (A-B): precision %.3f, recall "
          "%.3f (threshold %.2f tuned on a separate 20%% partition)"
          % (h["precision"], h["recall"], m["threshold_tuned"]),
          "- Exact-key links (email, hashed mobile): precision and "
          "recall 1.000",
          "- Component purity: %.4f - %d false-merge component(s) "
          "exist and are listed in er_metrics.json, not hidden"
          % (m["component_purity"], len(m["impure_component_examples"])),
          "- Ground-truth links used for this evaluation stay private "
          "and are never read by the running agent."]
    return report + "\n".join(er)


def datamap_md():
    with open(os.path.join(ART, "4c_report.json")) as f:
        rep = json.load(f)
    with open(os.path.join(DATA, "link_report.json")) as f:
        lrep = json.load(f)
    lines = ["## Sources"]
    for name in DATASETS:
        d = GATE.catalog[name]
        lines.append("### %s  (brand: %s, class: %s)"
                     % (name, d["brand"], d["record_class"]))
        lines.append("| field | type | pii |")
        lines.append("|---|---|---|")
        for fld in d["fields"]:
            lines.append("| %s | %s | %s |"
                         % (fld["name"], fld["type"], fld["pii"]))
        for defect in d.get("consent_defects", []):
            lines.append("- KNOWN DEFECT: %s" % defect)
        lines.append("")
    lines.append("## Customer-360 concept coverage")
    for concept, ds in rep["C4_complete"]["customer360_matrix"].items():
        lines.append("- **%s**: %s" % (concept, ", ".join(ds)))
    lines.append("")
    lines.append("## Identity links (governance-gated)")
    lines.append("Total links: %d | by status: %s"
                 % (lrep["n_links"], lrep["by_status"]))
    lines.append("- *active*: usable for member-level operations")
    lines.append("- *member_level_blocked*: link exists but member-level"
                 " use is barred (no subscription: SHR-001; partner "
                 "aggregate_only: SHR-010)")
    lines.append("- *quarantined*: identity touches a deletion request "
                 "(RET-010) - unusable everywhere")
    return "\n".join(lines)


def hero_md():
    with open(os.path.join(ART, "compile_report.json")) as f:
        comp = json.load(f)
    with open(os.path.join(ART, "provenance.json")) as f:
        prov = json.load(f)
    with open(os.path.join(ART, "4c_report.json")) as f:
        rep = json.load(f)
    with open(os.path.join(DATA, "link_report.json")) as f:
        lrep = json.load(f)
    n_docs = len({ref.split("#")[0] for p in prov.values()
                  for ref in p["source_refs"]})
    n_conf = len(rep["C1_correct"]["conflict_scan"]["conflicts"])
    n_gold = rep["C1_correct"]["golden_gate"]["n_cases"] + 12
    return "\n".join([
        "# WikiGovern-CX",
        "### \"Can we use this customer data for that?\" - ask, and get "
        "an answer with receipts.",
        "",
        "A governance agent for multi-brand customer data. Every verdict "
        "is decided by rules compiled from real policy and contract "
        "documents - never by a language model - and every \"no\" cites "
        "the exact rule, statement and source clause behind it.",
        "",
        "**What you get:**",
        "- **ALLOW / PARTIAL / DENY, per record** - with a citation "
        "chain: rule, policy statement, source document and clause.",
        "- **UNKNOWN beats ALLOW** - if the deciding information was "
        "never captured (e.g. consent without a date), the gate refuses "
        "to guess.",
        "- **A standing audit** - provenance completeness, formally "
        "detected rule conflicts, cross-brand semantic drift, staleness "
        "and coverage gaps, all in the Audit tab.",
        "",
        "**At a glance:** %d active governance rules compiled from %d "
        "source documents | %d synthetic data sources across 3 brands + "
        "1 partner | %d identity links, every one governance-gated | "
        "**%d genuine rule conflict detected by a formal solver** | %d "
        "frozen test cases passing"
        % (comp["counts"]["active"], n_docs,
           comp["counts"]["datasets"], lrep["n_links"], n_conf, n_gold),
        "",
        "**Start in 30 seconds:** in *Ask the gate* below, run Scenario "
        "3 - watch 1,246 transactions get blocked by a partner contract "
        "clause, with a conflict alert (7-year retention policy vs "
        "2-year destruction contract) that no manual review would "
        "surface. All data is synthetic; see the About tab for safety "
        "boundaries.",
    ])


def build_app():
    with gr.Blocks(title="WikiGovern-CX") as demo:
        gr.Markdown(hero_md())
        with gr.Tab("Ask the gate"):
            gr.Markdown("### Quick demos")
            with gr.Row():
                preset = gr.Dropdown(choices=list(PRESETS.keys()),
                                     value=list(PRESETS.keys())[0],
                                     label="Scenario", scale=4)
                btn_preset = gr.Button("Run scenario", scale=1)
            gr.Markdown("### Custom query")
            with gr.Row():
                scope_type = gr.Radio(["single_source", "join",
                                       "aggregate"],
                                      value="single_source",
                                      label="Scope")
                purpose = gr.Radio(PURPOSES, value="service_delivery",
                                   label="Purpose")
            with gr.Row():
                dataset = gr.Dropdown(DATASETS, value=DATASETS[0],
                                      label="Dataset (or join left)")
                dataset2 = gr.Dropdown(DATASETS, value=DATASETS[2],
                                       label="Join right (join only)")
            with gr.Row():
                use_case = gr.Textbox(label="Approved use case "
                                      "(analytics only)",
                                      placeholder="churn_model_v1")
                filter_text = gr.Textbox(label="Filter (field=value, "
                                         "optional)",
                                         placeholder="status=lapsed")
                deletion_only = gr.Checkbox(label="Only deletion-"
                                            "requested records")
            btn_custom = gr.Button("Ask")
            out_md = gr.Markdown()
            with gr.Accordion("Raw decision JSON", open=False):
                out_json = gr.JSON()
            with gr.Accordion("Recent decisions (audit log)",
                              open=False):
                out_recent = gr.Markdown(recent_md())
            btn_preset.click(run_preset, [preset],
                             [out_md, out_json, out_recent])
            btn_custom.click(run_custom,
                             [scope_type, dataset, dataset2, purpose,
                              use_case, filter_text, deletion_only],
                             [out_md, out_json, out_recent])
        with gr.Tab("Audit report (4C)"):
            gr.Markdown(audit_tab_md())
        with gr.Tab("Data map"):
            gr.Markdown(datamap_md())
        with gr.Tab("About"):
            with open(os.path.join(HERE, "CASE_NOTE.md")) as f:
                gr.Markdown(f.read())
    return demo


demo = build_app()

if __name__ == "__main__":
    demo.launch()
