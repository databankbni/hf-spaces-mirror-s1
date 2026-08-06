---
title: Multilingual Healthcare RAG
emoji: 📊
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 5.16.0
python_version: "3.11"
app_file: app.py
pinned: false
license: mit
short_description: Multilingual healthcare QA using RAG
---

# Multilingual Healthcare Question Answering with RAG and mT5

This system is a **multilingual healthcare question-answering platform** designed to support both English and low-resource African languages such as Amharic.

---

## 🌍 Problem Statement & Motivation

Access to reliable health information remains a critical challenge across sub-Saharan Africa. Language barriers frequently prevent communities from receiving clear, accurate health guidance in their native tongue—particularly on sensitive topics such as maternal, sexual, and reproductive health (MSRH), where the ability to ask questions privately and receive answers in one's own language can be the difference between informed decision-making and harmful misinformation.

Models trained predominantly on English-language data struggle to understand, reason, and generate fluent responses in languages such as Amharic, Tigrinya, and Oromo, leaving millions of speakers underserved by the very technology that could help them most.

This project addresses this gap by building a **multilingual medical question-answering system** capable of understanding and responding in low-resource African languages using Retrieval-Augmented Generation (RAG).

The objective is to build a multilingual model capable of accurately answering health-related questions in low-resource African languages. Using a curated dataset of healthcare question-and-answer pairs, the model:

- Understands questions posed in supported languages.
- Retrieves relevant medical context.
- Generates fluent, accurate, and contextually appropriate responses in the same language.

A strong system like this can power:

- Health worker assistant tools
- Patient education platforms
- Clinic support systems in rural and underserved communities
- AI-powered community healthcare chatbots

---

## 🧠 Architecture

- NLLB Back Translation Augmentation
- FLAN-T5 Synthetic Data Generation
- MiniLM Multilingual Embeddings
- FAISS Vector Retrieval
- Retrieval-Augmented Generation (RAG)
- mT5-Small with LoRA Fine-Tuning

---

## 🌐 Languages Supported

- English (en)
- Amharic (am)
- Tigrinya *(planned)*
- Oromo *(planned)*

---

## 🎯 Tasks

- Healthcare Question Answering
- Multilingual Information Retrieval
- Retrieval-Augmented Text Generation

---

## 📤 Outputs

The system preserves the language of the input question.

- **English Question → English Answer**
- **Amharic Question → Amharic Answer**

---

## 🔍 Explainability

To improve transparency and trustworthiness, the system returns:

- Retrieved examples from FAISS
- Similarity scores
- Source context passages used during generation

---

## ⚙️ Components

| Component | Model |
|-----------|-------|
| **Generator** | `google/mt5-small` |
| **Retriever** | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| **Vector Index** | FAISS |
| **Fine-tuning** | LoRA (PEFT) |

---

## 🚀 Use Cases

- AI-powered rural healthcare assistants
- Multilingual clinical decision support tools
- Low-resource language healthcare chatbots
- Public health information systems
- Patient education platforms
- Community health worker assistants
- Web-based multilingual healthcare consultation platform
- Cross-platform mobile healthcare assistant for Android and iOS

---

## 💻 Applications Built

Beyond the core multilingual RAG model, this project has been extended into complete end-user applications to demonstrate its practical deployment in real-world healthcare settings.

### 🌐 Web Application

A full-stack web application has been developed using modern technologies:

- **Frontend:** Next.js (TypeScript)
- **Backend API:** FastAPI (Python)
- **AI Engine:** Multilingual RAG with mT5 and FAISS

The web application enables users to:

- Ask healthcare questions in supported languages.
- Receive context-aware multilingual responses.
- View retrieved knowledge sources for explainability.
- Interact with the model through an intuitive, responsive interface.

### 📱 Mobile Application

A cross-platform mobile application has also been implemented using **React Native**, enabling multilingual healthcare assistance on Android and iOS devices.

Key features include:

- Multilingual healthcare question answering.
- Real-time communication with the FastAPI backend.
- User-friendly mobile interface.
- Accessible healthcare information for users in low-resource settings.

### 🏗️ Technology Stack

| Layer | Technology |
|--------|------------|
| Frontend | Next.js + TypeScript |
| Backend API | FastAPI |
| Mobile | React Native |
| AI Model | mT5-Small + LoRA |
| Retrieval | FAISS + MiniLM |
| Language Processing | NLLB + FLAN-T5 |

---

## ⚠️ Current Limitations

Although the proposed architecture is scalable, the current implementation was developed under significant computational constraints.

- **Limited GPU resources:** Research and model development were conducted primarily using the free Kaggle notebook environment, which provides limited GPU memory, execution time, and compute availability. These restrictions constrained experimentation, training time, and model optimization.

- **Small language model:** Due to hardware limitations, the system relies on **mT5-Small**. Larger multilingual language models containing **billions of parameters** generally demonstrate superior multilingual reasoning, contextual understanding, retrieval integration, and response generation. However, training and fine-tuning such models require significantly more GPU memory and computational resources than were available.

- **Restricted hyperparameter optimization:** Comprehensive hyperparameter tuning, multiple experimental runs, and extensive ablation studies could not be fully explored because of limited computational resources.

- **Limited dataset scale:** Although the current dataset validates the feasibility of the proposed approach, training on substantially larger multilingual healthcare corpora would likely improve robustness, generalization, and answer quality.

- **Limited language coverage:** The current implementation supports English and Amharic. Support for additional African languages such as Tigrinya, Oromo, Somali, and Afan Oromo remains future work.

- **Retrieval limitations:** The FAISS index currently employs a lightweight multilingual embedding model. Larger embedding models and domain-specific biomedical embeddings could further improve retrieval accuracy and contextual relevance.

- **Evaluation constraints:** Computational limitations restricted large-scale benchmarking and cross-language evaluation. Additional experiments across diverse healthcare datasets and expert human evaluations would provide stronger validation.

---

## 🚀 Future Improvements

With access to more powerful computational resources and research support, this system can be significantly enhanced.

Future work includes:

- Fine-tuning multilingual language models containing **billions of parameters** to improve reasoning, multilingual understanding, and response quality.
- Utilizing high-performance GPUs (A100, H100, RTX 6000 Ada, or multi-GPU clusters) to support larger batch sizes, longer training schedules, and extensive experimentation.
- Scaling training to much larger multilingual healthcare datasets covering additional African languages.
- Integrating larger multilingual embedding models to improve retrieval performance.
- Expanding support to Tigrinya, Oromo, Somali, Swahili, and other underserved African languages.
- Performing comprehensive hyperparameter optimization and systematic ablation studies.
- Integrating biomedical language models and verified clinical knowledge bases.
- Implementing hybrid retrieval techniques combining dense and sparse retrieval.
- Conducting extensive human evaluation with healthcare professionals and native speakers.
- Deploying optimized inference pipelines suitable for real-world healthcare applications.

---

## 💡 Research Perspective

This prototype demonstrates the feasibility of applying Retrieval-Augmented Generation (RAG) to multilingual healthcare question answering for low-resource African languages.

The primary limitation of this work is **computational capacity rather than technical capability**. The system was intentionally designed to be scalable, and with access to larger GPU resources, additional research funding, and institutional computational infrastructure, it can readily be extended to support substantially larger language models, broader multilingual coverage, improved retrieval mechanisms, and more rigorous experimental evaluation.

In addition to the research prototype, the system has been engineered into production-oriented web and mobile applications using **Next.js (TypeScript), FastAPI, and React Native**, demonstrating that the proposed multilingual RAG architecture is not only technically feasible but also deployable across multiple platforms for real-world healthcare accessibility.

---

## 📌 Example Output

### English Input

> What are the symptoms of malaria?

### English Output

> Common symptoms include fever, chills, headache, sweating, fatigue, nausea, vomiting, muscle pain, and weakness. If symptoms become severe, immediate medical attention is recommended.

---

### Amharic Input

> የወባ ምልክቶች ምንድን ናቸው?

### Amharic Output

> የወባ ዋና ምልክቶች ትኩሳት፣ ብርድ ማለት፣ ራስ ምታት፣ ድካም፣ ማቅለሽለሽ፣ ማስታወክ እና ጡንቻ ህመም ያካትታሉ።

---

## 📖 Citation

If you use this project in your research, please cite it appropriately and acknowledge the use of multilingual Retrieval-Augmented Generation (RAG), mT5, LoRA (PEFT), FAISS, and multilingual sentence transformers.

---

## 📄 License

This project is released under the **MIT License**.
```
