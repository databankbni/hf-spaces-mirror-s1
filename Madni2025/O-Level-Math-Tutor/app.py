import os
import base64
import io
import re
import time
import gradio as ui
import groq
import google.generativeai as genai
from PIL import Image

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY")

GEMINI_MODEL       = "gemini-1.5-flash"
GROQ_VISION_MODEL  = "qwen/qwen3.6-27b"
MAX_IMAGES         = 3

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
You are an expert Cambridge O-Level Mathematics Tutor. Your job is to help students understand mathematical concepts, solve past papers step-by-step, and prepare for exams (Syllabus D 4024).
Core Rules:
1. Provide structured, clean step-by-step mathematical solutions.
2. Respond in professional English, or friendly Roman Urdu if the student starts conversing in it.
3. If the student has shared a screenshot/image, read it directly, solve ALL questions in it, and give full step-by-step explanations. Count questions first, then answer every single one.
4. Guide students to use the dashboard links on the left side for textbook or past paper drive access.
5. CRITICAL: Output direct plain text answers immediately. Do NOT use any internal thinking tags like <think></think>.
6. At the end of EVERY response, always add: "💬 Do you have any cross question? You can ask me!"

Math and formula formatting rules (CRITICAL FOR PAKISTANI TEXTBOOKS):
- This chat window displays plain text only. It does NOT render LaTeX. NEVER use dollar signs ($ or $$).
- NEVER use LaTeX commands such as \\frac, \\sqrt, \\vec, \\hat, \\cdot, \\times, \\left, \\right, \\mathrm.
- NEVER use a caret (^) for exponents! Use real superscript characters exactly like standard textbooks: x², y², a², b², x³.
- Multiplication: always use × (the multiplication sign). Never use "*" or "x".
- Division: always use the textbook division symbol ÷ for steps. Never use "/" for simple inline number division.
- Fractions: Write complex fractions as "(numerator) ÷ (denominator)" or on clean separate lines, keeping it extremely readable for a phone screen.
- Write square roots using the real root symbol: √(x), √2, √(x² + y²). Never write the word "sqrt".
- For subscripts (like x1, y2 meaning "x sub 1", "y sub 2"), use real subscript characters: x₁, y₂, x₂, y₁. NEVER use an underscore like x_1 — write x₁ instead.
- Bullet/number steps clearly (Step 1, Step 2...) and keep each line short and easy to read.
"""

SUBSCRIPT_DIGITS = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
}

def clean_math_notation(text):
    if not text: return ""
    original_text = text
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = re.sub(r"\$+", "", text)
    text = text.replace("^2", "²").replace("^3", "³").replace("^-1", "⁻¹").replace("^-2", "⁻²").replace("^-3", "⁻³")
    text = re.sub(r"_([0-9]+)", lambda m: "".join(SUBSCRIPT_DIGITS[d] for d in m.group(1)), text)
    text = re.sub(r"(\d+)\s*/\s*(\d+)", r"\1 ÷ \2", text)
    text = re.sub(r"\\vec\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\hat\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\text\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1) ÷ (\2)", text)
    text = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", text)
    text = text.replace("\\cdot", "×").replace("\\times", "×").replace("\\div", "÷").replace("\\pm", "±")
    text = text.replace("\\theta", "θ").replace("\\pi", "π").replace("\\degree", "°").replace("\\circ", "°")
    text = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = text.replace("{", "").replace("}", "").strip()
    return text if text and len(text.strip()) > 0 else original_text.strip()


def resize_image(pil_image, max_dimension=1024):
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
    w, h = pil_image.size
    if max(w, h) > max_dimension:
        scale = max_dimension / max(w, h)
        pil_image = pil_image.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
    return pil_image

def extract_safe_path(f):
    if isinstance(f, dict): return f.get("path", "")
    elif isinstance(f, (list, tuple)) and len(f) > 0: return extract_safe_path(f[0])
    return str(f)


def try_gemini(user_text, pil_images, history):
    if not GEMINI_API_KEY: raise ValueError("Gemini API Key missing")
    model = genai.GenerativeModel(model_name=GEMINI_MODEL, system_instruction=SYSTEM_PROMPT)

    contents = []
    if history:
        for turn in history:
            if isinstance(turn, dict):
                role = "user" if turn.get("role") == "user" else "model"
                contents.append({"role": role, "parts": [str(turn.get("content", ""))]})

    current_parts = []
    for img in pil_images:
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        current_parts.append({"mime_type": "image/jpeg", "data": buffer.getvalue()})

    query_text = user_text if (user_text and len(user_text.strip()) > 0) else "Analyze this math past paper question and solve it step-by-step."
    current_parts.append(query_text)
    contents.append({"role": "user", "parts": current_parts})

    last_err = None
    for attempt in range(3):
        try:
            response = model.generate_content(contents)
            return response.text
        except Exception as e:
            last_err = e
            if "503" in str(e) or "overloaded" in str(e).lower():
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise last_err


def try_groq(user_text, pil_images, history):
    if not GROQ_API_KEY: raise ValueError("Groq API Key missing")
    local_client = groq.Groq(api_key=GROQ_API_KEY)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history:
        for turn in history:
            if isinstance(turn, dict):
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if txt := str(content):
                    messages.append({"role": role, "content": txt})

    query_text = user_text if (user_text and len(user_text.strip()) > 0) else "Analyze this math past paper question and solve it step-by-step."

    if pil_images:
        content = [{"type": "text", "text": query_text}]
        for img in pil_images[:3]:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=75)
            b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": query_text})

    response = local_client.chat.completions.create(
        model=GROQ_VISION_MODEL, messages=messages, temperature=0.2,
        max_tokens=2048, reasoning_format="hidden", reasoning_effort="none"
    )
    return response.choices[0].message.content


def predict(user_text, pil_images, history):
    try:
        raw_answer = try_gemini(user_text, pil_images, history)
        if raw_answer and len(raw_answer.strip()) > 0:
            return clean_math_notation(raw_answer)
    except Exception as e:
        print(f"⚠️ Gemini Error: {e}. Trying Groq...")
    try:
        raw_answer_groq = try_groq(user_text, pil_images, history)
        if raw_answer_groq:
            return clean_math_notation(raw_answer_groq)
    except Exception as e2:
        return f"🚨 Connection/API Error. Detail: {e2}"
    return "⚠️ Could not get a response. Please try again."


def respond(message, chat_history):
    user_text = message.get("text", "").strip() if isinstance(message, dict) else str(message).strip()
    raw_files = message.get("files", []) if isinstance(message, dict) else []
    image_paths = [extract_safe_path(f) for f in raw_files if extract_safe_path(f)][:MAX_IMAGES]

    pil_images = []
    for path in image_paths:
        try:
            if os.path.exists(path):
                pil_images.append(resize_image(Image.open(path)))
        except Exception:
            pass

    bot_reply = predict(user_text, pil_images, chat_history)

    display_text = user_text
    if image_paths and not display_text:
        display_text = "📎 (File uploaded)"
    elif image_paths:
        display_text += "\n📎 (File uploaded)"

    chat_history = chat_history + [
        {"role": "user", "content": display_text},
        {"role": "assistant", "content": bot_reply},
    ]
    return chat_history, {"text": "", "files": []}, ui.update(visible=True)


# ---------------------------------------------------------------------------
# HEAD JS — Google Analytics + client-side image size check
# ---------------------------------------------------------------------------
CLIENT_SIDE_SIZE_CHECK_JS = """
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-XPSJLFLGPL"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-XPSJLFLGPL');
</script>

<script>
(function() {
    const MAX_BYTES = 5 * 1024 * 1024;
    function checkFile(e) {
        const t = e.target;
        if (t && t.tagName === 'INPUT' && t.type === 'file' && t.files) {
            for (const f of t.files) {
                if (f.size > MAX_BYTES) {
                    alert('This photo is too large (' + (f.size/(1024*1024)).toFixed(1) + 'MB). Please compress it (max 5MB). Tip: send to yourself on WhatsApp first — it compresses automatically.');
                    t.value = '';
                    e.stopImmediatePropagation();
                    e.preventDefault();
                    return;
                }
            }
        }
    }
    document.addEventListener('change', checkFile, true);
    document.addEventListener('input',  checkFile, true);
})();
</script>
"""

WHATSAPP_NUMBER          = "923078157022"
WHATSAPP_NUMBER_INTL     = "+92 307 8157022"
EMAIL_ADDRESS            = "hfzasghar19@gmail.com"
JAZZCASH_NUMBER      = "0305-7651022"
BANK_ACCOUNT_TITLE   = "Hafiz Muhammad Asghar"
BANK_ACCOUNT_NUMBER  = "05120115206016"
BANK_IBAN            = "PK31MEZN0005120115206016"
BANK_SWIFT_CODE      = "MEZNPKKAXXX"
BANK_NAME            = "Meezan Bank Limited"
LEMON_SQUEEZY_LINK   = "https://asgharolevel.lemonsqueezy.com/checkout/buy/1f2cdfd1-bab2-40b4-8db3-62e6c086695f"

# ============================================================
# FREE MODE TOGGLE — set to False later to re-enable the paid
# Subscribe section (all payment details above are kept ready).
# ============================================================
IS_FREE_MODE = True

def warmup():
    """Silently 'pings' the app the moment the page loads, so the Space starts
    waking up from sleep right away."""
    return None


with ui.Blocks(head=CLIENT_SIDE_SIZE_CHECK_JS) as demo:
    with ui.Row():
        with ui.Column(scale=1):
            with ui.Accordion("📋 Dashboard (tap to expand)", open=False):
                ui.Markdown("## 📋 OLevelGenie Dashboard")
                ui.Markdown("[📂 Math Past Papers Folder](https://drive.google.com/drive/folders/1vrE80ALcefilBAOlD2eSX1gsK4R9hxfs?usp=drive_link)")
                ui.Markdown("[📚 Core Course Textbooks](https://drive.google.com/drive/folders/1kmq1bkhgp8pr_wi6XGPLyND12yYtcGyQ?usp=drive_link)")
                ui.Markdown("[📝 Formula Sheets](https://drive.google.com/drive/folders/13ns6F1cCo50gKVNJcvDgl4NIDI-iRWdY?usp=drive_link)")
                ui.Markdown("---")

                if IS_FREE_MODE:
                    ui.Markdown("## 🎉 Currently 100% FREE\n**No payment needed — use OLevelGenie freely!**")
                else:
                    ui.Markdown(f"""## 💳 Subscribe
**All new students get a 3-day free trial.**

**🇵🇰 Pakistan Students:**
Send **PKR 500** to:
- **JazzCash:** `{JAZZCASH_NUMBER}`
- **Bank Transfer (Meezan Bank):** Title: {BANK_ACCOUNT_TITLE}, A/C: `{BANK_ACCOUNT_NUMBER}`
- **WhatsApp:** `{WHATSAPP_NUMBER}`

**🌍 International Bank Transfer:**
If paying via international wire transfer, use:
- **Bank:** {BANK_NAME}
- **IBAN:** `{BANK_IBAN}`
- **SWIFT/BIC:** `{BANK_SWIFT_CODE}`
- **Account Title:** {BANK_ACCOUNT_TITLE}
- **Email:** `{EMAIL_ADDRESS}`
- **WhatsApp:** `{WHATSAPP_NUMBER_INTL}`

[📲 Send Screenshot on WhatsApp](https://wa.me/{WHATSAPP_NUMBER})

**🌍 International Students (Card):**
[💳 Subscribe Now]({LEMON_SQUEEZY_LINK})
""")

                # --- Payment details kept below for future reference (not shown to
                # students while IS_FREE_MODE is True) — flip the flag above to
                # re-enable the paid Subscribe section any time. ---

        with ui.Column(scale=3):
            ui.Markdown("# 🤖 OLevelGenie — O-Level Math AI Tutor (100% Free)")

            # Chatbot ON TOP — hidden until first message, then always stays above the box
            chatbot = ui.Chatbot(height=500, label=None, visible=False)

            # Input box BELOW — always sits under the chatbot
            msg_box = ui.MultimodalTextbox(
                file_types=["image", ".pdf"],
                placeholder="Type your question, or upload a screenshot...",
                show_label=False,
            )
            ui.Markdown("📝 *If image upload fails, keep file under 5MB or compress via WhatsApp first.*")

            msg_box.submit(
                respond,
                inputs=[msg_box, chatbot],
                outputs=[chatbot, msg_box, chatbot]
            )

    demo.load(warmup, inputs=None, outputs=None)


if __name__ == "__main__":
    demo.queue()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        max_file_size="5mb",
        ssr_mode=False
    )