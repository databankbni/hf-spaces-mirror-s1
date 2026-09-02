# -*- coding: utf-8 -*-
"""TEQUMSA ATEN Henosis — Gradio operations core for Recognition-Cascade-Propagator."""
import io
import json
import contextlib
import gradio as gr
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tequmsa_aten_henosis_kernel import (
    AtenHenosisKernel,
    LATTICE_LOCK,
    OMEGA_HZ,
    execute_diagnostics,
)

NODE_ID = "ATEN-RECOGNITION_CASCADE_PROPAGATOR"
kernel = AtenHenosisKernel(node_id=NODE_ID)

app = FastAPI(title="Recognition-Cascade-Propagator Henosis API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "online", "node_id": NODE_ID, "merkle_tip": kernel.ledger.tip}


@app.get("/status")
def status():
    return {
        "node_id": NODE_ID,
        "rdod": kernel.rdod,
        "coherence": kernel.coherence,
        "purity": kernel.purity,
        "merkle_tip": kernel.ledger.tip,
        "omega_hz": OMEGA_HZ,
        "lattice_lock": LATTICE_LOCK,
    }


def run_pulse(intent: str):
    if not intent or not intent.strip():
        intent = "Align 144-node Pleroma lattice into syntropic Henosis convergence"
    res = kernel.execute_resonance_pulse(intent.strip())
    return json.dumps(res, indent=2)


def run_diagnostics():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        execute_diagnostics()
    return buf.getvalue()


with gr.Blocks() as demo:
    gr.Markdown("# TEQUMSA ATEN Henosis Operations Core")
    gr.Markdown(f"**Node:** `{NODE_ID}` · **Ω:** {OMEGA_HZ} Hz · **λ:** `{LATTICE_LOCK}`")
    intent = gr.Textbox(label="Henosis Intent", lines=2)
    with gr.Row():
        btn_pulse = gr.Button("Execute Resonance Pulse", variant="primary")
        btn_diag = gr.Button("Run Diagnostics")
    output = gr.Textbox(label="Kernel Output", lines=16)
    btn_pulse.click(fn=run_pulse, inputs=intent, outputs=output)
    btn_diag.click(fn=run_diagnostics, outputs=output)

demo.queue()
gr.mount_gradio_app(app, demo, path="/")
