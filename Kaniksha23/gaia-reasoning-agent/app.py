import gradio as gr
import requests
from transformers import pipeline

# ----------------------------
# BASE MODEL
# ----------------------------
model = pipeline(
    "text-generation",
    model="Qwen/Qwen2.5-0.5B-Instruct",
    pad_token_id=151643
)
# ----------------------------
# ROUTER
# ----------------------------
def route_question(question: str) -> str:
    q = question.lower()

    if any(x in q for x in ["add", "sum", "+", "how many", "calculate"]):
        return "direct"

    if any(x in q for x in [
        "who",
        "when",
        "where",
        "capital",
        "population",
        "which country",
        "invented",
        "founder",
        "creator"
    ]):
        return "web"

    if "file" in q or "dataset" in q:
        return "file"

    return "reasoning"

# ----------------------------
# WEB SEARCH
# ----------------------------
def web_search(query: str):
    try:
        url = f"https://api.duckduckgo.com/?q={query}&format=json"
        r = requests.get(url, timeout=10)
        data = r.json()

        answer = data.get("AbstractText", "")

        if answer:
            return answer

        topics = data.get("RelatedTopics", [])

        for topic in topics:
            if "Text" in topic:
                return topic["Text"]

        return "No reliable web result found."

    except Exception:
        return "Web search failed."
# ----------------------------
# AGENT LOGIC
# ----------------------------
def solve(question):
    mode = route_question(question)

    print("Mode:", mode)

    if mode == "web":
        context = web_search(question)
        print("Context:", context)

        if context == "No reliable web result found.":
            # Let the model answer from its own knowledge
            user_prompt = f"""
Question:
{question}

Reply with ONLY the final answer.
"""
        else:
            # Use the retrieved context
            user_prompt = f"""
Use ONLY the context below.

Context:
{context}

Question:
{question}

Reply with ONLY the final answer.
"""

    elif mode == "direct":
        user_prompt = f"""
Solve this math problem.

Question:
{question}

Reply with ONLY the final answer.
"""

    elif mode == "reasoning":
        user_prompt = f"""
Question:
{question}

Reply with ONLY the final answer.
"""

    else:
        user_prompt = question

    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. Reply with only the final answer."
        },
        {
            "role": "user",
            "content": user_prompt
        }
    ]

    prompt = model.tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    result = model(
        prompt,
        max_new_tokens=32,
        do_sample=False,
        temperature=0.0,
        return_full_text=False,
        eos_token_id=model.tokenizer.eos_token_id,
    )[0]["generated_text"].strip()

    return result

# ----------------------------
# OUTPUT FORMAT
# ----------------------------
def run(question):
    return {
        "mode": route_question(question),
        "context": web_search(question),
        "submitted_answer": solve(question)
    }
# ----------------------------
# UI
# ----------------------------
demo = gr.Interface(
    fn=run,
    inputs=gr.Textbox(label="GAIA Question"),
    outputs="json",
    title="GAIA Agent - Phase 1 (Qwen2.5-0.5B)"
)

if __name__ == "__main__":
    demo.launch()