"""
src/rag/__init__.py

CustomerCore RAG (Retrieval-Augmented Generation) package.

Modules:
  hybrid_retriever  — ChromaDB dense search + BM25 with tenant isolation
  semantic_cache    — 3-layer cache (L0 embedding, L1 Redis exact, L2 vector)
  reranker          — Cross-encoder reranking of merged retrieval results
  tool_rag          — Dynamic semantic tool schema retrieval (Phase 8)
  graph_rag         — Unified B2B graph-RAG: semantic + relational traversal (Phase 8)
  router            — SLA-aware multi-model LLM routing (Phase 7)
  llm_client        — LiteLLM wrapper routing to Ollama/OpenRouter
"""
