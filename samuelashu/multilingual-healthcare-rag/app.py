import os
import pandas as pd
import faiss
import torch
import gradio as gr
import numpy as np

from huggingface_hub import login, hf_hub_download
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from peft import PeftModel, PeftConfig

# =====================================================
# 1. AUTHENTICATION
# =====================================================

hf_token = os.getenv("HF_TOKEN")

if hf_token is None:
    raise ValueError("HF_TOKEN not found. Add it in Hugging Face Space Secrets.")

login(token=hf_token)

# =====================================================
# 2. MODEL REPO
# =====================================================

hf_model_repo = "samuelashu/mt5-small-healthcare-qa-am-en"

# =====================================================
# 3. DOWNLOAD RETRIEVAL ASSETS
# =====================================================

faiss_path = hf_hub_download(
    repo_id=hf_model_repo,
    filename="medical_faiss.index",
    token=hf_token
)

corpus_path = hf_hub_download(
    repo_id=hf_model_repo,
    filename="retrieval_corpus.csv",
    token=hf_token
)

# =====================================================
# 4. EMBEDDING MODEL
# =====================================================

embed_model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

# =====================================================
# 5. LOAD DATA
# =====================================================

faiss_index = faiss.read_index(faiss_path)
corpus_df = pd.read_csv(corpus_path)

# =====================================================
# 6. MODEL CONFIG
# =====================================================

config = PeftConfig.from_pretrained(hf_model_repo, token=hf_token)

base_model = AutoModelForSeq2SeqLM.from_pretrained(
    config.base_model_name_or_path,
    token=hf_token,
    low_cpu_mem_usage=True
)

model = PeftModel.from_pretrained(base_model, hf_model_repo, token=hf_token)

tokenizer = AutoTokenizer.from_pretrained(hf_model_repo, token=hf_token)

# =====================================================
# 7. DEVICE
# =====================================================

device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)
model.eval()

# =====================================================
# 8. RAG PIPELINE
# =====================================================

def run_rag_pipeline(user_question):
    try:
        user_question = user_question.strip()

        if not user_question:
            return "Please enter a valid question.", "No context retrieved."

        query_vector = embed_model.encode([user_question])
        query_vector = np.array(query_vector).astype("float32")

        _, indices = faiss_index.search(query_vector, k=3)

        retrieved_chunks = []

        for idx in indices[0]:
            if 0 <= idx < len(corpus_df):
                retrieved_chunks.append(str(corpus_df.iloc[idx]["output"]))

        context_str = " ".join(retrieved_chunks)

        prompt = f"context: {context_str} question: {user_question}"

        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=512
        ).to(device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_length=128,
                num_beams=4
            )

        answer = tokenizer.decode(outputs[0], skip_special_tokens=True)

        return answer, context_str

    except Exception as e:
        return f"Error: {str(e)}", ""

# =====================================================
# 9. GRADIO UI
# =====================================================

with gr.Blocks(
    theme=gr.themes.Soft(),
    title="Multilingual Healthcare QA System"
) as demo:

    gr.Markdown("""
# 🏥 Multilingual Healthcare Question Answering System

### English • አማርኛ

An explainable **Retrieval-Augmented Generation (RAG)** system designed to improve access to reliable healthcare information in low-resource African languages.

---

## 🌍 Project Overview

Access to reliable health information remains a major challenge across many African communities. Language barriers often prevent individuals from receiving accurate and understandable medical guidance in their native language.

This project aims to bridge that gap by providing a multilingual healthcare question-answering system capable of understanding and answering health-related questions in both **English** and **Amharic (አማርኛ)**.

The system combines semantic retrieval and large language models to generate context-aware and evidence-grounded responses.

---

## 🚀 Live Production Web Application

🌐 https://multilingual-medical-question-answe.vercel.app/

---

## 🔬 Key Features

### 📚 Retrieval-Augmented Generation (RAG)
Answers are generated using relevant medical evidence retrieved from a curated healthcare knowledge base.

### 🤖 Multilingual Healthcare QA
Supports healthcare questions in:
- English
- Amharic (አማርኛ)

### 🔎 Explainable AI
Displays retrieved medical context used during answer generation.

### ⚡ Fast Semantic Search
Uses FAISS vector indexing for efficient similarity search.

### 🧠 Transformer-Based Generation
Powered by:
- mT5-Small
- LoRA Fine-Tuning
- Multilingual MiniLM Embeddings

### 🌍 Low-Resource Language Support
Designed to improve healthcare information accessibility for underserved African language communities.

---

## 💡 Example Questions

English:
- What are the symptoms of malaria?
- How can hypertension be prevented?
- What are the transmission routes of HIV?

Amharic:
- የወባ በሽታ ምልክቶች ምንድን ናቸው?
- የከፍተኛ ደም ግፊትን እንዴት መከላከል ይቻላል?
- የኤች አይ ቪ መተላለፊያ መንገዶች ምንድናቸው?
""")

    with gr.Row():

        with gr.Column(scale=1):

            input_box = gr.Textbox(
                label="🩺 Medical Question",
                lines=4,
                placeholder="""
English Example:
What are the transmission routes of HIV?

Amharic Example:
የኤች አይ ቪ መተላለፊያ መንገዶች ምንድናቸው?
"""
            )

            submit_btn = gr.Button(
                "🔍 Generate Answer",
                variant="primary"
            )

        with gr.Column(scale=1):

            output_answer = gr.Textbox(
                label="🤖 Generated Answer",
                lines=8,
                placeholder="""
Example Output:

HIV can be transmitted through:
• Unprotected sexual contact
• Blood transfusion with infected blood
• Sharing contaminated needles
• Mother-to-child transmission during pregnancy, birth, or breastfeeding

--------------------

የኤች አይ ቪ መተላለፊያ መንገዶች፦

• ያልተጠበቀ የፆታ ግንኙነት
• በተበከለ ደም መውሰድ
• በጋራ መርፌ መጠቀም
• ከእናት ወደ ልጅ በእርግዝና፣ በወሊድ ወይም በጡት ማጥባት
"""
            )

            output_context = gr.Textbox(
                label="📚 Retrieved Medical Context",
                lines=10,
                placeholder="""
Retrieved medical evidence used by the RAG system will appear here.

Example:

HIV is transmitted through contact with infected blood,
semen, vaginal fluids, rectal fluids, and breast milk.

Transmission may occur through:

• Unprotected sexual intercourse
• Sharing contaminated needles
• Blood transfusion with infected blood
• Mother-to-child transmission

The retrieved context is used as evidence to generate the final answer.
"""
            )

    submit_btn.click(
        fn=run_rag_pipeline,
        inputs=input_box,
        outputs=[
            output_answer,
            output_context
        ]
    )

# =====================================================
# 10. LAUNCH
# =====================================================

print("🚀 Starting Gradio application...")

if __name__ == "__main__":
    demo.launch()