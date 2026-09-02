---
license: apache-2.0
library_name: scikit-learn
tags:
  - retrieval
  - rag
  - operations-research
  - bm25
  - tf-idf
language:
  - en
---

# OR Knowledge Copilot Retriever

Hybrid **BM25 + word TF-IDF + character TF-IDF** index for multi-layer operations-research knowledge (formulation, code, solver traces).

This artifact is a **fitted lexical index**, not a fine-tuned transformer. It is intended for CPU Spaces and on-prem retrieval without GPU.

## Files

| File | Role |
|------|------|
| `hybrid_index.joblib` | Vectorizers, TF-IDF matrices, BM25 statistics |
| `config.json` | Vocabulary sizes and chunk count |

## Usage

```python
from ragkit.pipeline import RAGPipeline
from domain.corpus import SYNONYMS, router, PRODUCT

pipe = RAGPipeline(
    chunks_path="dataset/chunks.jsonl",
    model_path="model/hybrid_index.joblib",
    synonyms=SYNONYMS,
    product=PRODUCT,
    router=router,
)
print(pipe.ask("What spinning reserve does GridWest unit commitment enforce?").answer)
```

## Evaluation

See `eval_results.json` on the companion dataset `alirezaaminzadeh/or-knowledge-copilot-corpus`.
