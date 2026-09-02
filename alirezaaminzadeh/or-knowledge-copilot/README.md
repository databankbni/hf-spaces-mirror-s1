---
title: OR Knowledge Copilot
emoji: 📐
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 6.15.1
app_file: app.py
pinned: false
license: apache-2.0
short_description: Multi-layer OR RAG with citations
python_version: "3.12"
---

# OR Knowledge Copilot

Retrieve **similar operations-research instances** with layered representations:

- Natural-language statement
- Mathematical formulation
- Pyomo and MiniZinc templates
- Solver status, objective, and runtime
- Binding-constraint explanation

Hybrid retrieval (BM25 + word/char TF-IDF) with metadata filters, layer routing, and **abstention** when the corpus has no support.

**Corpus:** [or-knowledge-copilot-corpus](https://huggingface.co/datasets/alirezaaminzadeh/or-knowledge-copilot-corpus)  
**Index:** [or-knowledge-copilot-retriever](https://huggingface.co/alirezaaminzadeh/or-knowledge-copilot-retriever)
