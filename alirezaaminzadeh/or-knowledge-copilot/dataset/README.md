---
license: apache-2.0
task_categories:
  - question-answering
  - text-retrieval
language:
  - en
pretty_name: OR Knowledge Copilot Corpus
tags:
  - operations-research
  - rag
  - retrieval
  - milp
  - scheduling
  - routing
size_categories:
  - n<1K
---

# OR Knowledge Copilot Corpus

Multi-layer operations-research knowledge base used by **OR Knowledge Copilot**.

Each instance is stored as six chunks:

1. Natural language
2. Mathematical formulation
3. Pyomo template
4. MiniZinc template
5. Solver output
6. Explanation of binding constraints

## Files

- `chunks.jsonl` — retrieval units
- `qa_pairs.jsonl` — labeled questions including out-of-scope abstention cases
- `benchmark_report.json` / `eval_results.json` — published retrieval metrics
- `taxonomy.json` — domain and layer counts
- `manifest.json` — dataset identity

## Metrics

Document hit rate, keyword coverage, and abstention rate are computed by `scripts/build_assets.py` and stored in `eval_results.json`.
