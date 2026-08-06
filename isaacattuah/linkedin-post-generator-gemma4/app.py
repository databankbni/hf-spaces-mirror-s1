"""LinkedIn Post Generator — hosted version.

Runs Gemma 4 (26B A4B) through a Hugging Face-compatible inference
endpoint. Designed to deploy as a Gradio app on Hugging Face Spaces.

Requires an HF_TOKEN environment variable (on Spaces, add it under
Settings → Variables and secrets).
"""

import logging
import os

import gradio as gr
from huggingface_hub import InferenceClient

from prompts import LENGTH_TARGETS, TONE_INSTRUCTIONS, build_prompt

logger = logging.getLogger(__name__)

MODEL_ID = "google/gemma-4-26B-A4B-it"

client = InferenceClient(
    model=MODEL_ID,
    token=os.environ.get("HF_TOKEN"),
)


def generate_post(topic: str, tone: str, length: str) -> str:
    if not topic or not topic.strip():
        return "Please enter a topic to write about."

    prompt = build_prompt(topic, tone, length)
    # 2x the word target covers the post; the extra 1024 is headroom for
    # reasoning tokens — Gemma 4 thinks before it writes, and hosted
    # providers spend that thinking from the same max_tokens budget.
    max_tokens = int(LENGTH_TARGETS[length] * 2.0) + 1024

    try:
        response = client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.8,
            top_p=0.95,
        )
        choice = response.choices[0]
        # content can be None if the budget ran out mid-reasoning, and
        # some providers return the reasoning inline in <think> tags.
        post = choice.message.content or ""
        if "</think>" in post:
            post = post.split("</think>", 1)[1]
        post = post.strip()
        if not post:
            logger.error(
                "Empty completion (finish_reason=%s) — token budget "
                "likely spent on reasoning", choice.finish_reason,
            )
            return "The model returned no text. Please try again."
        return post
    except Exception:
        logger.exception("Post generation failed")
        return "Generation failed. Please try again."


CSS = """
.container { max-width: 1200px; margin: auto; }
"""

# Gradio 6: theme and css are passed to launch(), not Blocks()
with gr.Blocks(title="LinkedIn Post Generator") as demo:
    gr.Markdown("# ✍️ LinkedIn Post Generator")
    gr.Markdown("Powered by **Gemma 4** — craft engaging posts in seconds.")

    with gr.Row():
        with gr.Column():
            topic = gr.Textbox(
                label="What's your post about?",
                placeholder="e.g. lessons learned from failing a startup, AI trends in 2026...",
                lines=4,
            )
            tone = gr.Radio(
                choices=list(TONE_INSTRUCTIONS.keys()),
                value="Conversational",
                label="Tone",
            )
            length = gr.Radio(
                choices=list(LENGTH_TARGETS.keys()),
                value="Medium (~300 words)",
                label="Length",
            )

        with gr.Column():
            output = gr.Textbox(
                label="Your LinkedIn Post",
                lines=20,
                buttons=["copy"],  # Gradio 6; formerly show_copy_button=True
            )

    generate_btn = gr.Button("Generate Post 🚀", variant="primary")

    generate_btn.click(
        fn=generate_post,
        inputs=[topic, tone, length],
        outputs=output,
    )

    gr.Examples(
        examples=[
            ["5 things I learned about AI after finishing my Master's degree",
             "Conversational", "Medium (~300 words)"],
            ["Why most companies are adopting AI the wrong way",
             "Professional", "Short (~150 words)"],
            ["The moment I realized failure was my best teacher",
             "Inspirational", "Long (~500 words)"],
        ],
        inputs=[topic, tone, length],
    )

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft(), css=CSS)