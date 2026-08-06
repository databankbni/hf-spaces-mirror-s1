# SPDX-License-Identifier: Apache-2.0
# (c) 2026 SZL Holdings - Stephen P. Lutar - ORCID 0009-0001-0110-4173
"""SZLHOLDINGS/energy-attested-runs - live energy-attested inference receipts.

Runs a clearly-mock-labelled routed inference and returns a SIGNED (or
UNSIGNED-honest) receipt carrying token counts, honest cost, and HONEST energy:
measured joules where a real NVML meter exists, otherwise null / "UNAVAILABLE".
A joule is NEVER fabricated. A "Verify this receipt" button runs SZL's open,
dependency-free governed-receipt-spec verifier in-process.
"""
from __future__ import annotations

import json
import os
import tempfile

import gradio as gr

import energy_receipt as er
import verify

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "schema", "governed-receipt.schema.json")
SCHEMA = verify.load_schema(SCHEMA_PATH)

DATASET_URL = "https://huggingface.co/datasets/SZLHOLDINGS/energy-attested-runs"
SPEC_URL = "https://github.com/szl-holdings/governed-receipt-spec"
ESTATE_URL = "https://a-11-oy.com"
ORG_URL = "https://huggingface.co/SZLHOLDINGS"

# --------------------------------------------------------------------------- #
# Signing mode (honest): env key -> real; else ephemeral demo key; else none. #
# --------------------------------------------------------------------------- #
_SIGN_PEM = os.environ.get("SZL_SIGN_KEY")
_SIGN_MODE = "unsigned"
_PUBKEY_PEM = None
_KEYID = "energy-attested-runs"

if _SIGN_PEM:
    _SIGN_MODE = "env-key"
    _KEYID = "energy-attested-runs/env"
else:
    try:  # generate an ephemeral demo key so the signature demo works live
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        _k = ec.generate_private_key(ec.SECP256R1())
        _SIGN_PEM = _k.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("utf-8")
        _PUBKEY_PEM = _k.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        _SIGN_MODE = "ephemeral-demo-key"
        _KEYID = "energy-attested-runs/ephemeral-demo"
    except Exception:  # noqa: BLE001 - cryptography absent -> UNSIGNED-honest
        _SIGN_PEM = None
        _SIGN_MODE = "unsigned"

CHAIN = er.EnergyReceiptChain(sign_key_pem=_SIGN_PEM, keyid=_KEYID)
CAP = er.energy_capability()

_SIGN_BANNER = {
    "env-key": "SIGNED with a configured key (SZL_SIGN_KEY).",
    "ephemeral-demo-key": (
        "SIGNED with an EPHEMERAL demo key (regenerated on every Space "
        "restart). The signature is real and verifiable with the public key "
        "below - it proves integrity within this session, not long-term "
        "authorship."
    ),
    "unsigned": (
        "UNSIGNED-honest: no signing key present. Integrity is still checkable "
        "via the hash chain + _pae_sha256; a signature is never faked."
    ),
}[_SIGN_MODE]


def _field_status_md(decision: dict) -> str:
    e = decision["energy"]
    t = decision["tokens"]
    c = decision["cost"]
    energy_state = "MEASURED" if e.get("joules") is not None else "UNAVAILABLE"
    joules = e.get("joules")
    joules_txt = ("%.6f J" % joules) if joules is not None else "null"
    rows = [
        "| Field | Status | Value |",
        "| --- | --- | --- |",
        "| **energy.joules** | %s | `%s` |" % (energy_state, joules_txt),
        "| energy.label | - | %s |" % e.get("label"),
        "| tokens_in | MEASURED (real count) | %s |" % t.get("tokens_in"),
        "| tokens_out | MEASURED (real count) | %s |" % t.get("tokens_out"),
        "| cost.usd | %s | `%s` |" % (
            "COMPUTED" if c.get("usd") is not None else "UNAVAILABLE",
            c.get("usd") if c.get("usd") is not None else "null"),
        "| lambda | ADVISORY | %s |" % decision["lambda"]["label"],
        "| decision | GOVERNANCE | %s |" % decision["decision"],
        "| chain | seq=%s | prev=`%s...` |" % (
            decision["seq"], decision["prev"][:16]),
    ]
    note = e.get("evidence", {}).get("reason") or ""
    md = "\n".join(rows)
    if energy_state == "UNAVAILABLE":
        md += (
            "\n\n> **Honest energy note:** %s. No joule figure is fabricated - "
            "this Space runs on CPU with no NVML energy counter. On GPU "
            "hardware with NVML, `energy.joules` becomes a real measured value."
            % note
        )
    return md


def run_inference(prompt, rate_in, rate_out):
    prompt = (prompt or "").strip()
    if not prompt:
        return ("_Enter a prompt to emit a receipt._", "", "", "")
    r_in = float(rate_in) if rate_in not in (None, "", 0) else None
    r_out = float(rate_out) if rate_out not in (None, "", 0) else None
    rec = CHAIN.emit(prompt, usd_per_1k_in=r_in, usd_per_1k_out=r_out)
    decision = rec["_decision"]
    envelope = {k: v for k, v in rec.items() if k != "_decision"}

    # deterministic mock reply (same text that was hashed into the receipt)
    reply = er.mock_route(prompt)["completion"]
    completion_md = "**Mock-routed reply** (`%s`):\n\n> %s" % (
        decision["organ"], reply)

    status_md = _field_status_md(decision)
    receipt_json = json.dumps(
        {"envelope": envelope, "decision_decoded": decision},
        indent=2, ensure_ascii=False,
    )
    return completion_md, status_md, receipt_json, "_Click **Verify this receipt** to check it._"


def verify_all():
    if CHAIN.count() == 0:
        return "_No receipts yet - run an inference first._"
    nd = CHAIN.to_ndjson()
    with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(nd)
        path = fh.name
    try:
        ok, lines = verify.verify_file(path, SCHEMA)
    finally:
        os.unlink(path)
    header = "### %s - %d receipt(s) in the session chain\n\n" % (
        ("PASS" if ok else "FAIL"), CHAIN.count())
    body = "```\n" + "\n".join(lines) + "\nRESULT: %s\n```" % (
        "PASS" if ok else "FAIL")
    tail = (
        "\n\nThis runs the **same dependency-free verifier** published in "
        "[`governed-receipt-spec`](%s): it validates each receipt against the "
        "JSON Schema, recomputes the DSSE PAE content hash, and re-walks the "
        "`prev <- digest` hash chain." % SPEC_URL
    )
    return header + body + tail


CAP_MD = (
    "**Energy meter capability on this host:** "
    "`pynvml importable = %s`, `NVML init = %s`, `GPU count = %s`, "
    "`measurable = %s`. "
    % (CAP["pynvml_importable"], CAP["nvml_init_ok"], CAP["device_count"],
       CAP["measurable"])
)

INTRO = """
# ⚡ Energy-Attested Inference Runs

**One line:** run a routed inference, get back a **signed receipt** of its
**tokens, cost, and energy** - where every field is honestly labelled
**MEASURED** or **UNAVAILABLE**. A joule is never fabricated.

**Why it matters (the gap):** energy/cost papers *measure* inference but don't
*attest* it, and providers can over-count tokens. A signed, hash-chained
**energy + token + cost receipt** is the honest, cheap countermeasure - the
"receipt tier" of trust (not zkML, not a TEE).

**What you're using here:** a **local, deterministic mock route** (so it runs
with zero downloads) wrapped in **real** receipt mechanics - real token
counting, honest energy metering, a SHA-256 hash chain, and a real ECDSA-P256
signature. Swap in a live model and the energy field stays honest-null until a
real NVML meter is present.
"""


with gr.Blocks(title="Energy-Attested Inference Runs - SZL Holdings",
               theme=gr.themes.Soft()) as demo:
    gr.Markdown(INTRO)
    gr.Markdown("> **Signing mode:** " + _SIGN_BANNER)
    gr.Markdown("> " + CAP_MD)

    with gr.Row():
        with gr.Column(scale=3):
            prompt = gr.Textbox(
                label="Prompt (routed to the local mock model)",
                placeholder="e.g. Summarize what an energy-attested receipt proves.",
                lines=3,
            )
            with gr.Row():
                rate_in = gr.Number(label="USD / 1k input tokens (optional)",
                                    value=None)
                rate_out = gr.Number(label="USD / 1k output tokens (optional)",
                                     value=None)
            run_btn = gr.Button("Run inference + emit receipt", variant="primary")
            reply_md = gr.Markdown()
        with gr.Column(scale=2):
            gr.Markdown("### Field status - MEASURED vs UNAVAILABLE")
            status_md = gr.Markdown()

    gr.Markdown("### Signed receipt (DSSE envelope + decoded decision)")
    receipt_out = gr.Code(language="json", label="receipt.json")

    with gr.Row():
        verify_btn = gr.Button("Verify this receipt", variant="secondary")
    verify_out = gr.Markdown()

    if _PUBKEY_PEM:
        with gr.Accordion("Public key for this session (verify the signature)",
                          open=False):
            gr.Code(_PUBKEY_PEM, label="ephemeral-demo public key (PEM)")

    gr.Markdown(
        "---\n"
        "**Companion dataset:** append-only sample receipts produced by this "
        "Space -> [SZLHOLDINGS/energy-attested-runs dataset](%s)  \n"
        "**Open spec + verifier:** [governed-receipt-spec](%s)  \n"
        "**Estate:** [a-11-oy.com](%s) · [SZLHOLDINGS on Hugging Face](%s)  \n\n"
        "_Honesty brand: energy = measured joules OR honest null; "
        "Λ = Conjecture 1 (advisory, never \"green\"); receipts signed or "
        "UNSIGNED-honest, never faked._"
        % (DATASET_URL, SPEC_URL, ESTATE_URL, ORG_URL)
    )

    run_btn.click(run_inference, [prompt, rate_in, rate_out],
                  [reply_md, status_md, receipt_out, verify_out])
    verify_btn.click(verify_all, None, verify_out)


if __name__ == "__main__":
    demo.launch()
