"""
Gradio Space - the "instant demo" flavor of Hugging Face Spaces.
----------------------------------------------------------------
No Docker, no server config. You push app.py + requirements.txt and Hugging Face
builds and serves the web UI automatically.

This Space has two tabs:
  1. Greet   - the classic one-liner from the PDF (works with zero setup / no key).
  2. Ask AI  - a Gemini-backed text box, so students see a *real* GenAI demo.

The model key is read from GEMINI_API_KEY or GOOGLE_API_KEY. On Hugging Face you add
it under Settings -> Variables and secrets (see this folder's parent README). Locally,
it is picked up from ../../../module3_agents/.env.

Run locally:  python app.py   ->  http://localhost:7860
"""

import os

import gradio as gr

# Optional local convenience: load ../../../module3_agents/.env if python-dotenv is
# installed. On HF the secret is injected by the platform, so this is a no-op there.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def greet(name: str) -> str:
    """The PDF's hello-world function - proves the Space is live with zero dependencies."""
    return f"Hello, {name}!"


def ask_ai(prompt: str) -> str:
    """Send the prompt to Gemini and return the response."""
    if not prompt or not prompt.strip():
        return "Please type a prompt first."
    if not API_KEY:
        return (
            "No model key found. On Hugging Face, add GOOGLE_API_KEY under "
            "Settings -> Variables and secrets. Locally, set it in your .env."
        )
    # Imported lazily so the Greet tab still works even if google-genai is missing.
    from google import genai

    client = genai.Client(api_key=API_KEY)
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )
        return response.text
    except Exception as exc:  # noqa: BLE001
        return f"Error calling Gemini: {exc}"


with gr.Blocks(title="GenAI Gradio Space") as demo:
    gr.Markdown("# GenAI Gradio Space\nA Hugging Face Spaces demo (Gradio SDK).")

    with gr.Tab("Greet"):
        name_in = gr.Textbox(label="Your name")
        greet_out = gr.Textbox(label="Greeting")
        gr.Button("Greet").click(greet, inputs=name_in, outputs=greet_out)

    with gr.Tab("Ask AI"):
        prompt_in = gr.Textbox(label="Prompt", lines=3, placeholder="Explain serverless...")
        ai_out = gr.Textbox(label="Gemini says", lines=6)
        gr.Button("Ask").click(ask_ai, inputs=prompt_in, outputs=ai_out)


if __name__ == "__main__":
    # server_name=0.0.0.0 makes it reachable inside a container / Space.
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
