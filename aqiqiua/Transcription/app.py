"""Gradio web UI: paste a YouTube link or upload a video/audio file → get a TXT.

Runs on Hugging Face Spaces (or any host). API keys are read from environment
variables / Space Secrets: ANTHROPIC_API_KEY (required), GROQ_API_KEY (needed
for uploaded files and for videos without subtitles).
"""

import os
import tempfile
import threading
import time

import gradio as gr

from transcriber import (TranscribeError, answer_question, bulk_asr, bulk_format,
                         factcheck_transcript, transcribe, usage_json)

# Injected via Blocks(head=…) — the ONLY css that reaches the login page
# (the css= parameter ships in the app config, which loads after auth).
HEAD = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
body {
  background:
    radial-gradient(560px 560px at -160px -180px, rgba(16,185,129,.26), transparent 68%),
    radial-gradient(480px 480px at calc(100% + 200px) 160px, rgba(45,212,191,.14), transparent 68%),
    radial-gradient(520px 520px at 15% calc(100% + 200px), rgba(99,102,241,.14), transparent 68%),
    #080D1A !important;
  background-attachment: fixed !important;
}
/* gradio wraps the app in elements with their own background — they must be
   transparent or the aurora glows on <body> are covered up */
gradio-app, .gradio-container, .main, .app, .fillable {
  background: transparent !important;
}
</style>
"""

# Reference-transplanted pages (2a Aurora): served verbatim from files.
from pathlib import Path as _Path

_HERE = _Path(__file__).resolve().parent
SITE_HTML = (_HERE / "site.html").read_text(encoding="utf-8")
LOGIN_HTML = (_HERE / "login.html").read_text(encoding="utf-8")

TOPBAR = """
<div id="topbar">
  <div class="mark">T.</div>
  <div class="brand">
    <h1>Transcriber</h1>
    <p>Video &amp; audio → text</p>
  </div>
</div>
"""

HERO = """
<div id="hero">
  <div class="kicker">Transcription</div>
  <h2>Link or file → clean text</h2>
  <p>Paste a YouTube link or upload video/audio — get clean text with
     logical paragraphs, chapters and timestamps.</p>
  <div id="chips">
    <span>YouTube link</span>
    <span>MP4 · MOV · MP3</span>
    <span>Paragraphs &amp; chapters</span>
    <span>Timestamps</span>
  </div>
</div>
"""  # 2a Aurora hero: glass card, emerald eyebrow, 40px H1 (styles in CSS)

FOOTER = """
<div id="foot">
  Videos without subtitles may take a couple of minutes to transcribe — keep this tab open.
  Large files take longer to upload from a phone.
</div>
"""

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
:root {
  --bg:#080D1A; --tx:#F4F7FB; --tx-2:#E2E8F0; --mut:rgba(203,213,225,.55);
  --mut2:rgba(203,213,225,.65); --faint:rgba(148,163,184,.5);
  --surf:rgba(148,163,184,.07); --bd:rgba(148,163,184,.14); --bd-2:rgba(148,163,184,.16);
  --dash:rgba(148,163,184,.25); --acc:#34D399; --acc2:#14B8A6; --onacc:#062B1F;
  --body:'Manrope',sans-serif;
}
/* page background + aurora glows live in HEAD (they must also reach the login
   page, which never receives this css= payload) */
.gradio-container { max-width:980px !important; margin:0 auto !important;
  font-family:var(--body) !important; background:transparent !important; position:relative; }
.main, .app, .fillable { background:transparent !important; }

#topbar { display:flex; align-items:center; gap:13px; padding:22px 2px 18px; }
#topbar .mark { width:46px; height:46px; border-radius:14px; flex:none;
  display:flex; align-items:center; justify-content:center;
  background:linear-gradient(135deg,#34D399,#14B8A6); color:var(--onacc);
  font-family:var(--body); font-weight:800; font-size:18px;
  box-shadow:0 8px 24px rgba(20,184,166,.3); }
#topbar h1 { font-family:var(--body); font-weight:800; font-size:19px;
  margin:0; color:var(--tx); line-height:1; }
#topbar .brand p { font-size:12.5px; font-weight:500; color:var(--mut); margin:4px 0 0; }

#hero { border:1px solid var(--bd-2); border-radius:26px; padding:36px; margin-bottom:20px;
  background:var(--surf); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
#hero .kicker { font-size:11px; text-transform:uppercase; letter-spacing:.16em;
  color:var(--acc); font-weight:800; margin-bottom:12px; }
#hero h2 { font-family:var(--body); font-weight:800; font-size:40px; letter-spacing:-1px;
  margin:0 0 10px; color:var(--tx); line-height:1.1; }
#hero p { font-size:15px; font-weight:500; color:rgba(203,213,225,.6); margin:0;
  line-height:1.6; max-width:600px; }
#chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:18px; }
#chips span { font-size:12.5px; font-weight:600; padding:7px 14px; border-radius:999px;
  color:#CBD5E1; background:var(--surf); border:1px solid var(--bd-2); }

.card { background:var(--surf) !important; border:1px solid var(--bd-2) !important;
  border-radius:20px !important; padding:18px !important; box-shadow:none !important;
  backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px);
  display:flex !important; flex-direction:column !important; gap:10px !important; }
/* distinct input fields inside the card (explicit class — no fragile :has) */
.card .field { background:var(--surf) !important;
  border:1px solid var(--bd) !important; border-radius:16px !important; }
/* SINGLE surface per row: the inner gradio input must not draw its own box
   (nested box-in-box looked wrong vs the reference) */
.card .field :is(input, select, textarea, .wrap, .secondary-wrap, .container) {
  background:transparent !important; border:0 !important; box-shadow:none !important; }
/* the link input is a pill */
#url-in { border-radius:999px !important; }
#url-in textarea, #url-in input { padding:15px 18px !important; font-weight:500; }
/* keep inputs strictly inside their container on narrow screens (padding must
   count toward the width, or long text/placeholders overflow the card on mobile) */
.card .field textarea, .card .field input, .card .field select {
  box-sizing:border-box !important; max-width:100% !important; width:100% !important; }
.card .field textarea, .card .field input {
  overflow-x:hidden !important; text-overflow:ellipsis !important; }
/* section titles as pure CSS text (no Gradio block wrapper → no container box at all) */
.card-in::before, .card-out::before {
  font-size:11px; text-transform:uppercase; letter-spacing:.14em;
  color:var(--faint); font-weight:800; font-family:var(--body); line-height:1; margin-bottom:4px; }
.card-in::before { content:"What to transcribe"; }
.card-out::before { content:"Result"; }

/* dashed file zones (Aurora): ONLY the drop zone + files strip */
#file-in, #file-out,
#file-in .auto-margin, #file-out .auto-margin {
  border:1.5px dashed var(--dash) !important; background:transparent !important;
  border-radius:18px !important; transition:border-color .15s; box-shadow:none !important; }
#file-in:hover, #file-out:hover { border-color:rgba(52,211,153,.55) !important; }
#file-in .auto-margin, #file-out .auto-margin { border:0 !important; }
#file-out .empty, #file-out .auto-margin { min-height:48px !important; border-radius:16px !important; }
#file-in .empty { min-height:112px !important; }
/* drop zone per reference: paperclip icon, two lines, no gradio i18n text */
#file-in .wrap { font-size:0 !important; display:flex !important; flex-direction:column;
  align-items:center; gap:6px; background:transparent !important; }
#file-in .wrap .icon-wrap { display:none !important; }
#file-in .wrap::before { content:""; width:18px; height:18px; opacity:.75;
  background:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%2364748B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>') center/contain no-repeat; }
#file-in .wrap::after {
  content:"Drop a file here — or click to upload\\A MP4 · MOV · MP3 · M4A · WAV";
  white-space:pre-line; display:block; font-size:12.5px !important; font-weight:600;
  color:var(--mut) !important; font-family:var(--body); letter-spacing:0;
  line-height:1.8; text-align:center; }

/* files strip per reference: inline icon + hint text (empty state can be
   .wrap or .empty depending on gradio's render path — cover both) */
#file-out :is(.wrap, .empty) { font-size:0 !important; display:flex !important;
  flex-direction:row !important; align-items:center; justify-content:center;
  gap:8px; min-height:48px; background:transparent !important; }
#file-out :is(.wrap, .empty) .icon-wrap { font-size:15px !important; opacity:.6; }
#file-out :is(.wrap, .empty)::after { content:"Files will appear here — TXT · SRT";
  font-size:13px !important; font-weight:500; color:rgba(148,163,184,.5);
  font-family:var(--body); }

/* neutralize + micro-style Gradio component labels */
.card .float, .card .svelte-19djge9, .card .svelte-jdcl7l:not(.sr-only) {
  background:transparent !important; background-image:none !important; color:var(--faint) !important;
  border:none !important; box-shadow:none !important; font-weight:700 !important;
  font-size:9.5px !important; text-transform:uppercase !important; letter-spacing:.09em !important; }

/* summary row → Aurora switch */
#summary-check { background:var(--surf) !important; border:1px solid var(--bd) !important;
  border-radius:16px !important; }
#summary-check label { display:flex !important; flex-direction:row-reverse;
  justify-content:space-between; align-items:center; width:100%;
  padding:13px 16px !important; cursor:pointer; gap:10px; }
#summary-check input[type=checkbox] { appearance:none; -webkit-appearance:none;
  width:40px !important; height:24px !important; border-radius:999px !important;
  background:rgba(148,163,184,.25) !important; border:0 !important; position:relative;
  transition:background .2s; margin:0 !important; flex:none; box-shadow:none !important; }
#summary-check input[type=checkbox]::after { content:""; position:absolute; top:3px; left:3px;
  width:18px; height:18px; border-radius:50%; background:#F8FAFC;
  box-shadow:0 1px 3px rgba(0,0,0,.4); transition:transform .2s; }
#summary-check input[type=checkbox]:checked {
  background:linear-gradient(135deg,#34D399,#14B8A6) !important; }
#summary-check input[type=checkbox]:checked::after { transform:translateX(16px); }
#summary-check span { font-weight:600 !important; font-size:12.5px !important;
  color:var(--tx-2) !important; display:flex; align-items:center; gap:8px;
  line-height:1.3; white-space:nowrap; text-transform:none !important;
  letter-spacing:0 !important; }
#summary-check span::after { content:"FREE"; font-weight:800; font-size:9.5px;
  letter-spacing:.07em; color:var(--acc); background:rgba(52,211,153,.12);
  padding:3px 7px; border-radius:999px; }

/* result output area: dashed, tall, skeleton bars while empty */
#preview-out { border:1.5px dashed var(--dash) !important; border-radius:18px !important;
  background:transparent !important; }
#preview-out textarea { min-height:330px !important; background:transparent !important;
  color:var(--mut2) !important; font-size:13px; line-height:1.6; }
/* skeleton bars live on the CONTAINER (overlay) so they never collide with
   the placeholder text; text sits centered below while the area is empty */
#preview-out { position:relative; }
#preview-out:has(textarea:placeholder-shown)::before { content:""; position:absolute;
  top:20px; left:16px; right:16px; height:66px; pointer-events:none;
  background:
    linear-gradient(var(--surf),var(--surf)) 0 0/85% 10px no-repeat,
    linear-gradient(var(--surf),var(--surf)) 0 22px/65% 10px no-repeat,
    linear-gradient(var(--surf),var(--surf)) 0 44px/45% 10px no-repeat; }
#preview-out textarea:placeholder-shown { padding-top:150px !important;
  text-align:center; }
#preview-out textarea::placeholder { color:rgba(148,163,184,.5); font-weight:500; }

#go-btn button { font-family:var(--body) !important;
  background:linear-gradient(135deg,#34D399,#14B8A6) !important; color:var(--onacc) !important;
  border:none !important; font-weight:800 !important; font-size:16px !important;
  padding:17px 18px !important; border-radius:999px !important; margin-top:8px !important;
  box-shadow:0 12px 34px rgba(20,184,166,.32), inset 0 1px 0 rgba(255,255,255,.35) !important;
  transition:filter .15s ease, transform .15s ease !important; }
#go-btn button:hover { filter:brightness(1.07); }
#go-btn button:active { transform:scale(.97); }

#foot { text-align:center; color:var(--faint); font-size:12px; font-weight:500;
  margin-top:22px; line-height:1.55; }
footer { display:none !important; }
@media (max-width:900px){ #hero h2 { font-size:32px; } #hero { padding:26px; } }

"""


def run(url, file, language, translate_to, want_summary, use_claude, out_format="txt"):
    """Generator: streams a live status line while a worker thread transcribes.

    Gradio's progress bar doesn't update reliably during long blocking steps, so
    instead we run the work in a background thread and yield a status string
    (stage + percent) into the preview box every ~0.4s — the user always sees
    movement.
    """
    url = (url or "").strip()
    file_path = file.name if file else None
    if not url and not file_path:
        raise gr.Error("Provide a video link or upload a file.")

    lang = None if language in (None, "", "auto") else language
    state = {"msg": "Starting…", "frac": 0.02}
    result = {}

    def worker():
        try:
            def prog(frac, msg):
                state["frac"] = frac
                state["msg"] = msg
            result["value"] = transcribe(url, file_path, lang,
                                         want_summary=want_summary,
                                         use_claude=use_claude,
                                         translate_to=translate_to or None,
                                         progress=prog)
        except TranscribeError as e:
            result["error"] = str(e)
        except Exception as e:  # noqa: BLE001 — surface anything unexpected
            result["error"] = f"Unexpected error: {e}"

    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()

    while worker_thread.is_alive():
        pct = int(max(0.0, min(1.0, state["frac"])) * 100)
        yield None, f"{state['msg']}  ·  {pct}%"
        time.sleep(0.4)
    worker_thread.join()

    if "error" in result:
        raise gr.Error(result["error"])

    filename, txt, srt = result["value"]
    files = []
    if out_format in ("txt", "both") or not srt:
        out_path = os.path.join(tempfile.gettempdir(), filename)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(txt)
        files.append(out_path)
    if srt and out_format in ("srt", "both"):
        srt_path = os.path.join(tempfile.gettempdir(), filename[:-4] + ".srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt)
        files.append(srt_path)
    # Show the whole transcript on screen for any normal-length video; only very
    # long ones (multi-hour) get clipped, and the note points to the full file.
    PREVIEW_LIMIT = 300000
    preview = txt if len(txt) <= PREVIEW_LIMIT else (
        txt[:PREVIEW_LIMIT]
        + "\n\n──────────\n⬆ On-screen preview stops here. This is a very long video — "
          "the COMPLETE transcript is in the downloadable TXT file above.")
    yield files, preview


_DARK = {  # Aurora Glass tokens, applied in both light & dark browser modes
    "body_background_fill": "#080D1A", "body_background_fill_dark": "#080D1A",
    "body_text_color": "#F4F7FB", "body_text_color_dark": "#F4F7FB",
    "body_text_color_subdued": "rgba(203,213,225,.55)",
    "body_text_color_subdued_dark": "rgba(203,213,225,.55)",
    "background_fill_primary": "#0B1222", "background_fill_primary_dark": "#0B1222",
    "background_fill_secondary": "#0E1528", "background_fill_secondary_dark": "#0E1528",
    "block_background_fill": "rgba(148,163,184,.05)",
    "block_background_fill_dark": "rgba(148,163,184,.05)",
    "block_border_color": "rgba(148,163,184,.14)",
    "block_border_color_dark": "rgba(148,163,184,.14)",
    "border_color_primary": "rgba(148,163,184,.14)",
    "border_color_primary_dark": "rgba(148,163,184,.14)",
    "block_label_text_color": "rgba(148,163,184,.6)",
    "block_label_text_color_dark": "rgba(148,163,184,.6)",
    "block_title_text_color": "#E2E8F0", "block_title_text_color_dark": "#E2E8F0",
    "input_background_fill": "rgba(148,163,184,.07)",
    "input_background_fill_dark": "rgba(148,163,184,.07)",
    "input_border_color": "rgba(148,163,184,.16)",
    "input_border_color_dark": "rgba(148,163,184,.16)",
    "input_border_color_focus": "rgba(52,211,153,.5)",
    "input_border_color_focus_dark": "rgba(52,211,153,.5)",
}

THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.emerald,
    secondary_hue=gr.themes.colors.teal,
    neutral_hue=gr.themes.colors.slate,
    radius_size=gr.themes.sizes.radius_lg,
    font=[gr.themes.GoogleFont("Manrope"), "ui-sans-serif", "system-ui", "sans-serif"],
).set(**_DARK)

with gr.Blocks(title="Transcriber · video → text", css=CSS, theme=THEME,
               head=HEAD) as demo:
    gr.HTML(TOPBAR)
    gr.HTML(HERO)
    with gr.Row(equal_height=False):
        with gr.Column(scale=5, elem_classes=["card", "card-in"]):
            url_in = gr.Textbox(
                label="YouTube link", show_label=False, elem_classes="field",
                elem_id="url-in", placeholder="🔗  Paste a YouTube link")
            file_in = gr.File(
                label="…or upload a file (MP4, MOV, MP3, M4A, WAV…)",
                show_label=False,
                file_types=["video", "audio"], elem_id="file-in", height=150)
            lang_in = gr.Dropdown(
                label="Recognition language",
                choices=["auto", "ru", "en", "uk", "de", "fr", "es"],
                value="auto", elem_classes="field")
            translate_in = gr.Dropdown(
                label="Translate result (free)",
                choices=[("Off — keep original language", ""), ("Русский", "ru"),
                         ("English", "en"), ("Українська", "uk"), ("Deutsch", "de"),
                         ("Français", "fr"), ("Español", "es")],
                value="", elem_classes="field")
            format_in = gr.Dropdown(
                label="Output format",
                choices=[("TXT — readable text", "txt"),
                         ("TXT + SRT subtitles", "both"),
                         ("SRT subtitles only", "srt")],
                value="txt", elem_classes="field")
            summary_in = gr.Checkbox(
                label="Summary, key points & outline", value=False,
                elem_id="summary-check")
            # Claude is retired from the UI (free Gemini matches it) but the
            # input stays for API compatibility with the deployed Mini App.
            claude_in = gr.Checkbox(
                label="Higher quality — use Claude (paid, ~$0.05/video)", value=False,
                elem_id="claude-check", visible=False)
            go = gr.Button("✨  Transcribe", variant="primary", elem_id="go-btn")
        with gr.Column(scale=6, elem_classes=["card", "card-out"]):
            file_out = gr.File(label="Files", show_label=False, elem_id="file-out",
                               height=64, file_count="multiple")
            preview_out = gr.Textbox(
                label="Preview", show_label=False, lines=12, max_lines=22,
                elem_classes="field", elem_id="preview-out",
                placeholder="The ready text will appear here…")

    gr.HTML(FOOTER)

    go.click(run, inputs=[url_in, file_in, lang_in, translate_in, summary_in,
                          claude_in, format_in],
             outputs=[file_out, preview_out])

    # Hidden API endpoint for the Telegram Mini App: structured usage/limits.
    usage_out = gr.JSON(visible=False)
    usage_btn = gr.Button("usage", visible=False)
    usage_btn.click(usage_json, inputs=None, outputs=usage_out, api_name="usage")

    # Hidden API endpoint for bulk mode: the Mac worker posts raw caption
    # segments (fetched from its home IP) and gets back a formatted TXT.
    bulk_in = gr.JSON(visible=False)
    bulk_out = gr.JSON(visible=False)
    bulk_btn = gr.Button("bulk", visible=False)
    bulk_btn.click(bulk_format, inputs=bulk_in, outputs=bulk_out, api_name="bulk_format")

    # Bulk AUDIO endpoint: the Mac uploads a downloaded audio file (its home IP can
    # reach YouTube; the cloud's datacenter IP can't) and we transcribe it here.
    asr_file = gr.File(visible=False)
    asr_meta = gr.JSON(visible=False)
    asr_out = gr.JSON(visible=False)
    asr_btn2 = gr.Button("bulkasr", visible=False)
    asr_btn2.click(bulk_asr, inputs=[asr_file, asr_meta], outputs=asr_out,
                   api_name="bulk_asr")

    # Hidden webhook inlet: the Deno relay forwards Telegram updates here
    # (webhook mode = no constant polling, ~100x less relay traffic).
    def _tg_update(upd):
        try:
            from telegram_bot import process_update
            process_update(upd or {})
        except Exception as e:  # noqa: BLE001 — must always ACK to Telegram
            print(f"[tg_update] error: {e}", flush=True)
        return {"ok": True}

    tg_in = gr.JSON(visible=False)
    tg_out = gr.JSON(visible=False)
    tg_btn = gr.Button("tg", visible=False)
    tg_btn.click(_tg_update, inputs=tg_in, outputs=tg_out, api_name="tg_update")

    # Ask-the-video: answer a question from the last transcript (free Gemini→Groq).
    def _ask(payload):
        try:
            payload = payload or {}
            ans = answer_question(payload.get("transcript", ""), payload.get("question", ""))
            return {"answer": ans}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:300]}

    ask_in = gr.JSON(visible=False)
    ask_out = gr.JSON(visible=False)
    ask_btn = gr.Button("ask", visible=False)
    ask_btn.click(_ask, inputs=ask_in, outputs=ask_out, api_name="ask_video")

    # Fact-check: AI review of the video with Google-search grounding.
    def _factcheck(transcript):
        try:
            return factcheck_transcript(transcript or "")
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:300]}

    fc_in = gr.JSON(visible=False)
    fc_out = gr.JSON(visible=False)
    fc_btn = gr.Button("fc", visible=False)
    fc_btn.click(_factcheck, inputs=fc_in, outputs=fc_out, api_name="factcheck")


if __name__ == "__main__":
    # Telegram bot (optional): activates only when TELEGRAM_BOT_TOKEN is set.
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        from telegram_bot import start_bot
        start_bot()

    # Password gate: fail CLOSED. If the secrets go missing the app must not
    # silently open to the whole internet (anyone could burn the API credits).
    _user, _pass = os.environ.get("APP_USER"), os.environ.get("APP_PASS")
    if not (_user and _pass) and os.environ.get("ALLOW_PUBLIC") != "1":
        raise SystemExit("APP_USER and APP_PASS must be set (Space Secrets). "
                         "Set ALLOW_PUBLIC=1 to run without a password on purpose.")

    demo.queue(max_size=8)
    app_, _local, _share = demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
        auth=(_user, _pass) if _user and _pass else None,
        pwa=True,
        prevent_thread_lock=True,
        # SSR puts a Node proxy in front of "/" that bypasses our login route
        # override — serve everything from Python, like local runs do.
        ssr_mode=False,
    )
    if _user and _pass:
        # Gradio renders its own login UI (ignoring css=/head=) BOTH at /login
        # and at "/" when unauthenticated — the HF Space iframe opens "/", so
        # both must serve the Aurora page. POST /login (actual auth) untouched.
        import inspect as _inspect

        from starlette.responses import HTMLResponse as _HTMLResponse
        from starlette.routing import Route as _Route

        _main_ep = None
        for _r in app_.router.routes:
            if getattr(_r, "path", None) == "/" and "GET" in (getattr(_r, "methods", None) or set()):
                _main_ep = _r.endpoint
                break

        def _current_user(request):
            token = request.cookies.get(f"access-token-{app_.cookie_id}")
            return app_.tokens.get(token)

        async def _login_page(request):
            return _HTMLResponse(LOGIN_HTML)

        async def _root(request):
            if _current_user(request) is None:
                return _HTMLResponse(LOGIN_HTML)
            return _HTMLResponse(SITE_HTML)   # transplanted 2a reference page

        async def _ui(request):
            # fallback: the original Gradio UI, for debugging/emergencies
            user = _current_user(request)
            if user is None or _main_ep is None:
                return _HTMLResponse(LOGIN_HTML)
            res = _main_ep(request, user=user, page="", deep_link="")
            if _inspect.iscoroutine(res):
                res = await res
            return res

        app_.router.routes.insert(0, _Route("/ui", _ui, methods=["GET"]))
        app_.router.routes.insert(0, _Route("/login", _login_page, methods=["GET"]))
        app_.router.routes.insert(0, _Route("/", _root, methods=["GET"]))
    demo.block_thread()
