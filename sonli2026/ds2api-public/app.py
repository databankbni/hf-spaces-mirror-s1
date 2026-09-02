import os
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import gradio as gr

from pdf_translate import translate_pdf
from translator import engine_status

QUEUE = []
JOBS = {}
QUEUE_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=1)


def queue_snapshot():
    with QUEUE_LOCK:
        active = sum(1 for j in JOBS.values() if j["status"] == "processing")
        waiting = sum(1 for j in JOBS.values() if j["status"] == "queued")
        return active, waiting


def _queue_snapshot_locked():
    active = sum(1 for j in JOBS.values() if j["status"] == "processing")
    waiting = sum(1 for j in JOBS.values() if j["status"] == "queued")
    return active, waiting


def _run(job_id, path, source, target):
    with QUEUE_LOCK:
        JOBS[job_id].update(status="processing", progress=2, message="Đang khởi động model local…")
    try:
        name = Path(path).stem
        output = os.path.join(tempfile.gettempdir(), f"dolor_{job_id}_{name}_{target}.pdf")
        def cb(done, total):
            with QUEUE_LOCK:
                JOBS[job_id].update(progress=int(done / max(total, 1) * 96), message=f"Đang dịch trang {done}/{total}…")
        translate_pdf(path, output, source, target, cb)
        with QUEUE_LOCK:
            JOBS[job_id].update(status="done", progress=100, message="Hoàn tất", output=output)
    except Exception as exc:
        with QUEUE_LOCK:
            JOBS[job_id].update(status="error", progress=0, message=f"Lỗi: {exc}")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def submit(files, source, target):
    if not files:
        raise gr.Error("Vui lòng tải lên ít nhất một file PDF.")
    if isinstance(files, str):
        files = [files]
    job_id = uuid.uuid4().hex[:10]
    temp_path = os.path.join(tempfile.gettempdir(), f"dolor_input_{job_id}.pdf")
    shutil.copyfile(files[0], temp_path)
    with QUEUE_LOCK:
        position = sum(1 for j in JOBS.values() if j["status"] == "queued") + 1
        JOBS[job_id] = {"status": "queued", "progress": 0, "message": f"Đang chờ · vị trí #{position}", "output": None}
    EXECUTOR.submit(_run, job_id, temp_path, source, target)
    return job_id, status_text(job_id), None


def status_text(job_id):
    if not job_id:
        return "Sẵn sàng nhận tài liệu."
    with QUEUE_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return "Không tìm thấy phiên xử lý."
        active, waiting = _queue_snapshot_locked()
        return f"{job['message']}\n\nLive queue · đang xử lý: {active}/1 · đang chờ: {waiting}"


def poll(job_id):
    if not job_id:
        return status_text(job_id), None, 0
    with QUEUE_LOCK:
        job = JOBS.get(job_id, {})
        output = job.get("output") if job.get("status") == "done" else None
        progress = job.get("progress", 0)
    return status_text(job_id), output, progress


css = """
@import url('https://fonts.googleapis.com/css2?family=Bodoni+Moda:wght@500;600;700&family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
body { background:#2d2d2d !important; font-family:'DM Sans',sans-serif !important; }
.gradio-container { max-width:1320px !important; padding:34px 22px 48px !important; background:#2d2d2d !important; }
.notebook { background:#f8f6f1; color:#1a1a1a; border-radius:24px; padding:clamp(26px,4vw,58px) clamp(24px,5vw,72px) 42px 74px; box-shadow:0 24px 70px rgba(0,0,0,.28); position:relative; overflow:hidden; }
.notebook:before { content:'···'; position:absolute; left:24px; top:82px; color:#98d4bb; font:700 34px/1 'DM Sans'; letter-spacing:4px; writing-mode:vertical-rl; }
.notebook:after { content:''; position:absolute; inset:0; pointer-events:none; background:linear-gradient(105deg,rgba(255,255,255,.34),transparent 28%,transparent 74%,rgba(26,26,26,.035)); }
.tabs { position:absolute; right:0; top:30px; bottom:42px; width:38px; z-index:4; }
.tab { position:absolute; right:0; width:38px; min-height:112px; display:flex; align-items:center; justify-content:center; writing-mode:vertical-rl; border-radius:14px 0 0 14px; color:#1a1a1a; font:700 10px/1 'DM Sans'; letter-spacing:1.6px; box-shadow:-3px 3px 9px rgba(0,0,0,.08); }
.tab.mint { top:0; background:#98d4bb; } .tab.pink { top:128px; background:#f4b8c5; } .tab.lav { top:256px; background:#c7b8ea; } .tab.sky { top:384px; background:#a8d8ea; }
.masthead { display:flex; justify-content:space-between; align-items:flex-start; gap:24px; position:relative; z-index:2; }
.kicker { font:600 11px/1 'JetBrains Mono'; letter-spacing:2px; text-transform:uppercase; color:#6d6b66; margin-bottom:18px; }
.hero h1 { font:700 clamp(3.2rem,8vw,7.4rem)/.86 'Bodoni Moda',serif; letter-spacing:-.055em; margin:0; color:#1a1a1a; }
.hero p { max-width:490px; margin:24px 0 0; color:#5f5b54; font:400 16px/1.65 'DM Sans'; }
.badge { background:#1a1a1a; color:#98d4bb; border-radius:999px; padding:10px 14px; font:600 11px 'JetBrains Mono'; white-space:nowrap; }
.rule { height:1px; background:#d9d3c8; margin:44px 0 30px; position:relative; z-index:2; }
.section-label { font:600 11px 'JetBrains Mono'; letter-spacing:1.5px; text-transform:uppercase; color:#77736b; margin-bottom:12px; }
.workspace { background:#fffdf8; border:1px solid #ded8ce; border-radius:18px; padding:20px; box-shadow:0 5px 18px rgba(47,42,33,.06); }
.workspace-title { font:600 23px 'Bodoni Moda'; margin-bottom:3px; }
.workspace-subtitle { color:#7b766c; font-size:13px; margin-bottom:20px; }
.live-card { background:#1a1a1a; color:#f8f6f1; border-radius:16px; padding:21px; min-height:180px; }
.live-card textarea, .live-card input { color:#f8f6f1 !important; background:transparent !important; border:0 !important; }
.live-card label { color:#98d4bb !important; }
.dropzone { border:1.5px dashed #b8b0a3 !important; background:#f8f6f1 !important; min-height:158px; }
.dropzone:hover { border-color:#98d4bb !important; background:#f1faf5 !important; }
.prose, label, button, input, textarea { font-family:'DM Sans',sans-serif !important; }
.status textarea { min-height:112px !important; background:#242424 !important; color:#f8f6f1 !important; border:1px solid #444 !important; }
.status label { color:#98d4bb !important; }
button.primary { background:#1a1a1a !important; color:#98d4bb !important; border:1px solid #1a1a1a !important; border-radius:10px !important; min-height:48px; font-weight:700 !important; }
button.primary:hover { background:#383838 !important; transform:translateY(-1px); }
.footnote { color:#77736b; font:400 12px/1.5 'DM Sans'; margin-top:20px; }
@media (max-width: 760px) { .gradio-container { padding:12px !important; } .notebook { padding:28px 22px 30px 48px; border-radius:18px; } .masthead { display:block; } .badge { display:inline-block; margin-top:20px; } .tabs { display:none; } .notebook:before { left:14px; } }
"""

with gr.Blocks(title="Dolor · Document Translator", css=css, theme=gr.themes.Base()) as demo:
    with gr.Column(elem_classes="notebook"):
        gr.HTML("<div class='tabs'><div class='tab mint'>DOLOR</div><div class='tab pink'>TRANSLATE</div><div class='tab lav'>LOCAL AI</div><div class='tab sky'>PDF</div></div>")
        gr.HTML("<div class='masthead'><div class='hero'><div class='kicker'>Notebook 01 / document studio</div><h1>Dolor</h1><p>A quiet, private workspace for translating documents. Drop a PDF, choose the language, and let local AI rebuild the page.</p></div><div class='badge'>CPU / QUEUE 1</div></div><div class='rule'></div>")
        gr.HTML("<div class='section-label'>Translation desk</div><div class='workspace-title'>Start a new translation</div><div class='workspace-subtitle'>Your file stays inside this Space while the job is processed.</div>")
        with gr.Row(elem_classes="workspace"):
            with gr.Column(scale=6):
                files = gr.File(label="Drop your PDF here", file_types=[".pdf"], type="filepath", elem_classes="dropzone")
                with gr.Row():
                    source = gr.Dropdown(["en", "vi", "zh", "ja", "ko", "fr", "de"], value="en", label="From")
                    target = gr.Dropdown(["vi", "en", "zh", "ja", "ko", "fr", "de"], value="vi", label="To")
                run = gr.Button("Translate document", variant="primary")
            with gr.Column(scale=4, elem_classes="live-card"):
                gr.HTML("<div class='section-label' style='color:#98d4bb'>Live desk</div><div class='workspace-title' style='color:#f8f6f1'>Your place in line</div>")
                status = gr.Textbox(label="Queue status", value="Ready for your document.", lines=5, elem_classes="status", interactive=False)
                output = gr.File(label="Translated PDF")
                progress = gr.Number(value=0, visible=False)
        gr.HTML(f"<div class='footnote'>Local engine: TranslateGemma 4B Q4_K_M · 2 vCPU · one active job at a time · {engine_status()}</div>")
        job = gr.State("")
        timer = gr.Timer(1)
        run.click(submit, [files, source, target], [job, status, output])
        timer.tick(poll, [job], [status, output, progress])
    gr.Markdown("Dolor handles jobs sequentially to stay reliable on free CPU hardware. Complex scanned PDFs may need a later OCR pass.", elem_classes="footnote")

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860, ssr_mode=False)
