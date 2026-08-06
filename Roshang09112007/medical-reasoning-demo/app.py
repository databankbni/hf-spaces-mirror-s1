import gradio as gr
from transformers import AutoTokenizer, AutoModelForCausalLM, TextIteratorStreamer
import torch
import time
from threading import Thread

MODEL_NAME = "Qwen/Qwen2.5-0.5B-Instruct"

SYSTEM_PROMPT = (
    "You are a medical reasoning assistant built for research and educational "
    "demonstration purposes. Provide clear, structured clinical reasoning "
    "(possible differentials, relevant considerations, and next steps) but "
    "always remind the user this is not a substitute for professional medical advice."
)

print(f"Loading model: {MODEL_NAME} ...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    torch_dtype=torch.float32,
    device_map="auto",
)
print("Model loaded.")

DISCLAIMER = (
    "\n\n---\n"
    "⚠️ **Disclaimer:** This is a research/demo project (AutoScientist Challenge). "
    "It is not a certified medical device and should not be used for real diagnosis "
    "or treatment decisions. Always consult a licensed healthcare professional."
)


def medical_reasoning(question, history):
    if not question or not question.strip():
        yield "Please enter a medical question to get started."
        return

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        for turn in history:
            if isinstance(turn, dict):
                messages.append(turn)
    messages.append({"role": "user", "content": question})

    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    streamer = TextIteratorStreamer(
        tokenizer, skip_prompt=True, skip_special_tokens=True
    )

    generation_kwargs = dict(
        **inputs,
        streamer=streamer,
        max_new_tokens=150,
        do_sample=False,       # greedy = faster, no sampling overhead
        num_beams=1,
        repetition_penalty=1.1,
    )

    try:
        start = time.time()
        thread = Thread(target=model.generate, kwargs=generation_kwargs)
        thread.start()

        partial = ""
        for new_text in streamer:
            partial += new_text
            yield partial

        elapsed = time.time() - start
        yield partial + f"\n\n_Generated in {elapsed:.1f}s by {MODEL_NAME}_" + DISCLAIMER
    except Exception as e:
        yield (
            f"⚠️ Something went wrong while generating a response:\n\n`{str(e)}`\n\n"
            "Try shortening your question or asking again in a moment."
        )


EXAMPLES = [
    "A 45-year-old presents with sudden chest pain radiating to the left arm. What are the key differentials?",
    "What is the recommended first-line treatment for type 2 diabetes?",
    "Explain the pathophysiology of sepsis in simple terms.",
    "What are the warning signs of a stroke, and what is the immediate response?",
]

THEME = gr.themes.Soft(
    primary_hue="teal",
    secondary_hue="blue",
)

with gr.Blocks(title="Medical Reasoning Mini") as demo:
    gr.Markdown(
        """
        # 🏥 Medical Reasoning Mini
        **Fine-tuned Llama 3.3 70B + LoRA research project — running on a lightweight model in this free demo Space**

        Built for the **AutoScientist Challenge** · LoRA rank 64, alpha 128 · 20K synthetic medical conversations
        Benchmark: Win rate 31% → 70% · Science win rate 22% → 78%
        """
    )

    chatbot = gr.ChatInterface(
        fn=medical_reasoning,
        examples=EXAMPLES,
        chatbot=gr.Chatbot(height=420, label="Medical Reasoning Assistant"),
        textbox=gr.Textbox(
            placeholder="Ask a clinical or medical reasoning question...",
            lines=2,
        ),
        title=None,
        description=None,
    )

    gr.Markdown(
        "🔗 [Model on Hugging Face](https://huggingface.co/Roshang09112007/adaption-air-bench-healthcare-es) · "
        "📄 Research demo only — not for real medical use."
    )

if __name__ == "__main__":
    demo.launch(theme=THEME)
