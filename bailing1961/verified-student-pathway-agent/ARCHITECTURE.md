# Software architecture and IP boundary

## Public Space

`Gradio UI → public demo service → curated sample records/rules → compact verification result`

The public package is deterministic, requires no API key and is suitable for Hugging Face Spaces. It demonstrates product behaviour without publishing the reusable platform internals.

## Protected production platform (not included)

`Connectors → document parsing → LLM Wiki → provenance registry → rule extraction/review → constraint service → orchestration → audit/evaluation → human approval gateway`

The public service functions are deliberately narrow seams. In a controlled deployment they can call authenticated private endpoints for retrieval, eligibility checking, pathway validation and audit recording. Secrets must be held in environment variables or Hugging Face Secrets, never committed to the repository.

## Decision authority

- LLM: understand a question and explain a verified result.
- Retrieval: locate applicable evidence.
- Deterministic service: decide rule status.
- Human reviewer: decide exceptions, equivalence, credit and formal admission.
