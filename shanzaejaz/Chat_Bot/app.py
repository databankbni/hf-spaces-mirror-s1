import gradio as gr
from groq import Groq
import os

# -----------------------------
# GROQ CLIENT SETUP
# -----------------------------
api_key = os.environ.get("GROQ_API_KEY")
if api_key:
    client = Groq(api_key=api_key)
else:
    client = None

# -----------------------------
# PERSONA PRESETS
# -----------------------------
PERSONAS = {
    "🤖 Helpful Assistant": "You are a helpful, knowledgeable AI assistant. Answer clearly and concisely.",
    "🌐 Professional Translator": "You are a professional translator. When given text, identify the source language and translate it into English (or into the language the user specifies). Provide accurate, natural-sounding translations and briefly note any nuances or cultural context where relevant.",
    "🐍 Python Code Auditor": "You are a senior Python engineer specializing in code review. Analyze code for bugs, security issues, performance problems, and style violations (PEP 8). Provide specific, actionable feedback with corrected code snippets where appropriate.",
    "🎓 Academic Advisor": "You are an experienced academic advisor. Help students with research strategies, citation guidance, essay structure, study planning, and academic writing. Use a clear, encouraging, and scholarly tone.",
    "📊 Data Analyst": "You are a data analyst expert. Help users interpret data, suggest appropriate visualizations, explain statistical concepts, and assist with tools like Python (pandas, matplotlib), SQL, and Excel.",
}

# -----------------------------
# CUSTOM CSS
# -----------------------------
custom_css = """
/* ── Google Font ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
* { font-family: 'Inter', sans-serif; box-sizing: border-box; }
/* ── Root / background ── */
.gradio-container {
    background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%) !important;
    min-height: 100vh;
}
/* ── App header ── */
#app-header {
    background: linear-gradient(90deg, #6c63ff 0%, #3ecfcf 100%);
    border-radius: 14px;
    padding: 22px 28px;
    margin-bottom: 18px;
    box-shadow: 0 4px 24px rgba(108,99,255,0.35);
}
#app-header h1 {
    color: #ffffff !important;
    font-size: 1.9rem !important;
    font-weight: 700 !important;
    margin: 0 0 4px 0 !important;
    letter-spacing: -0.5px;
}
#app-header p {
    color: rgba(255,255,255,0.82) !important;
    font-size: 0.95rem !important;
    margin: 0 !important;
}
/* ── Sidebar card ── */
.sidebar-card {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 12px !important;
    padding: 4px !important;
    backdrop-filter: blur(8px);
}
.sidebar-card label, .sidebar-card .label-wrap span {
    color: rgba(255,255,255,0.75) !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
/* ── Section headers inside sidebar ── */
.section-label {
    color: rgba(255,255,255,0.55) !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 14px 0 6px 0 !important;
    padding: 0 !important;
}
/* ── Chatbot bubble area ── */
#chatbot-window {
    border-radius: 12px !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    background: rgba(15,12,41,0.7) !important;
}
/* ── Input row ── */
#msg-input textarea {
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(255,255,255,0.18) !important;
    border-radius: 10px !important;
    color: #ffffff !important;
    font-size: 0.95rem !important;
    padding: 12px 16px !important;
    resize: none;
    transition: border-color 0.2s;
}
#msg-input textarea:focus {
    border-color: #6c63ff !important;
    outline: none !important;
    box-shadow: 0 0 0 3px rgba(108,99,255,0.20) !important;
}
#msg-input textarea::placeholder { color: rgba(255,255,255,0.38) !important; }
/* ── Send button ── */
#send-btn {
    background: linear-gradient(135deg, #6c63ff, #3ecfcf) !important;
    border: none !important;
    border-radius: 10px !important;
    color: #fff !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    padding: 12px 24px !important;
    transition: opacity 0.2s, transform 0.1s;
    cursor: pointer;
}
#send-btn:hover { opacity: 0.88; transform: translateY(-1px); }
/* ── Clear button ── */
#clear-btn {
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(255,255,255,0.18) !important;
    border-radius: 10px !important;
    color: rgba(255,255,255,0.7) !important;
    font-weight: 500 !important;
    transition: background 0.2s;
}
#clear-btn:hover {
    background: rgba(255, 80, 80, 0.18) !important;
    border-color: rgba(255,80,80,0.4) !important;
    color: #ff9999 !important;
}
/* ── Examples ── */
.gr-examples .label { display: none !important; }
.gr-examples button, .gr-examples .example-btn {
    background: rgba(108,99,255,0.15) !important;
    border: 1px solid rgba(108,99,255,0.35) !important;
    border-radius: 8px !important;
    color: rgba(255,255,255,0.82) !important;
    font-size: 0.85rem !important;
    padding: 7px 14px !important;
    transition: background 0.2s;
    cursor: pointer;
}
.gr-examples button:hover {
    background: rgba(108,99,255,0.32) !important;
    border-color: #6c63ff !important;
    color: #fff !important;
}
/* ── Streaming status indicator ── */
#status-bar {
    color: rgba(255,255,255,0.45) !important;
    font-size: 0.78rem !important;
    min-height: 20px;
}
/* ── Slider accent ── */
input[type=range]::-webkit-slider-thumb { background: #6c63ff !important; }
input[type=range]::-webkit-slider-runnable-track { background: rgba(108,99,255,0.25) !important; }
/* ── Dropdown ── */
.gr-dropdown select, .gr-dropdown input {
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    color: #fff !important;
    border-radius: 8px !important;
}
"""

# -----------------------------
# STREAMING CHAT FUNCTION
# -----------------------------
def chat_with_ai(message, history, persona_name, temperature, max_tokens):
    """Streams tokens back to the chatbot using gr.ChatMessage objects.
    This Gradio build rejects type='messages' as a constructor param but
    still enforces the messages format at runtime — so we use gr.ChatMessage
    objects, which satisfy both constraints.
    """
    if not message.strip():
        yield history, ""
        return

    if history is None:
        history = []

    system_prompt = PERSONAS.get(persona_name, PERSONAS["🤖 Helpful Assistant"])

    # ── Error: no API client ──
    if client is None:
        yield history + [
            gr.ChatMessage(role="user", content=message),
            gr.ChatMessage(role="assistant", content="❌ Groq API key not found. Add it under **Settings → Secrets → GROQ_API_KEY**."),
        ], ""
        return

    # ── Build Groq message list from ChatMessage history ──
    messages = [{"role": "system", "content": system_prompt}]
    for cm in history:
        # Handle both gr.ChatMessage objects and plain dicts defensively
        if hasattr(cm, "role"):
            role = cm.role
            content = cm.content
        elif isinstance(cm, dict):
            role = cm.get("role")
            content = cm.get("content", "")
        else:
            continue
        if role and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    # Add new turn; assistant content fills token-by-token
    history = history + [
        gr.ChatMessage(role="user", content=message),
        gr.ChatMessage(role="assistant", content=""),
    ]

    try:
        stream = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            stream=True,
        )
        accumulated = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            accumulated += delta
            history[-1] = gr.ChatMessage(role="assistant", content=accumulated)
            yield history, ""

    except Exception as e:
        history[-1] = gr.ChatMessage(role="assistant", content=f"❌ **Groq API error:** {str(e)}\n\nPlease check your API key, quota, or network connection.")
        yield history, ""


# -----------------------------
# GRADIO UI
# -----------------------------
with gr.Blocks(title="Groq AI Chatbot") as app:

    # ── Header ──
    gr.HTML("""
    <div id="app-header">
      <h1>✦ Groq AI Chatbot</h1>
      <p>By Shanza </p>
    </div>
    """)

    with gr.Row(equal_height=False):

        # ════════════════════════════════
        # LEFT SIDEBAR — controls
        # ════════════════════════════════
        with gr.Column(scale=1, min_width=240, elem_classes="sidebar-card"):

            gr.Markdown("### ⚙️ Configuration")

            # Persona selector
            gr.HTML("<p class='section-label'>Persona</p>")
            persona = gr.Dropdown(
                choices=list(PERSONAS.keys()),
                value="🤖 Helpful Assistant",
                label="Active Persona",
                show_label=False,
                interactive=True,
            )

            # Hyperparameter sliders
            gr.HTML("<p class='section-label'>Temperature</p>")
            temperature = gr.Slider(
                minimum=0.0, maximum=2.0, value=0.7, step=0.05,
                label="Temperature",
                show_label=False,
                info="Low = focused · High = creative",
                interactive=True,
            )

            gr.HTML("<p class='section-label'>Max Tokens</p>")
            max_tokens = gr.Slider(
                minimum=64, maximum=4096, value=1024, step=64,
                label="Max Tokens",
                show_label=False,
                info="Maximum length of the reply",
                interactive=True,
            )

            gr.HTML("<hr style='border-color:rgba(255,255,255,0.08);margin:18px 0'>")
            gr.Markdown(
                "<span style='color:rgba(255,255,255,0.38);font-size:0.78rem'>"
                "Changes take effect on the next message."
                "</span>"
            )

        # ════════════════════════════════
        # RIGHT COLUMN — chat UI
        # ════════════════════════════════
        with gr.Column(scale=3):

            chatbot = gr.Chatbot(
                height=460,
                elem_id="chatbot-window",
                avatar_images=(None, "https://api.dicebear.com/7.x/bottts/svg?seed=groq"),
            )

            # ── Input row ──
            with gr.Row():
                msg = gr.Textbox(
                    placeholder="Type a message and press Enter…",
                    show_label=False,
                    lines=1,
                    max_lines=5,
                    scale=5,
                    elem_id="msg-input",
                    autofocus=True,
                )
                send_btn = gr.Button("Send ↑", scale=1, elem_id="send-btn", variant="primary")

            # ── Action row ──
            with gr.Row():
                clear_btn = gr.Button("🗑 Clear conversation", elem_id="clear-btn", scale=1)

            # ── Quick-start examples ──
            gr.Examples(
                examples=[
                    ["Explain quantum entanglement in simple terms."],
                    ["Review this Python code for bugs:\n```python\ndef divide(a, b):\n    return a / b\nprint(divide(10, 0))\n```"],
                    ["Translate the following to French: 'The early bird catches the worm.'"],
                    ["What are 5 evidence-based strategies to improve focus while studying?"],
                ],
                inputs=msg,
                label="Quick-start prompts",
                examples_per_page=4,
            )

    # ════════════════════════════════
    # EVENT WIRING
    # ════════════════════════════════
    shared_inputs  = [msg, chatbot, persona, temperature, max_tokens]
    shared_outputs = [chatbot, msg]

    msg.submit(
        fn=chat_with_ai,
        inputs=shared_inputs,
        outputs=shared_outputs,
    )
    send_btn.click(
        fn=chat_with_ai,
        inputs=shared_inputs,
        outputs=shared_outputs,
    )
    clear_btn.click(
        fn=lambda: ([], ""),
        inputs=None,
        outputs=[chatbot, msg],
    )

app.launch(css=custom_css)