---
title: sandyland
emoji: 🌵
colorFrom: yellow
colorTo: pink
sdk: static
pinned: false
---

# Sandyland: a research hub

A place to gather research by Ola Hungerford and collaborators related to MCP,
Agent Skills, and similar topics. The styled write-ups are published as a static
site (the [`sandyland`](https://huggingface.co/spaces/olaservo/sandyland) Hugging
Face Space); the same content renders as Markdown here on GitHub.

## Research

- **[MCP · tool schemas](mcp/tool-schemas/)** — what full JSON Schema 2020-12 unlocks in an MCP tool input (SEP-2106), and whether models and providers honor those keywords when they emit a tool call: measured by a 5,040-row fidelity dataset across 24 models and three API arms ([dataset card](mcp/tool-schemas/data/dataset-card.md)). An interactive playground is coming soon; the twin TS/Python demo MCP servers are already live and keyless — point any MCP client at `https://olaservo-json-schema-2020-12-ts.hf.space/mcp` or `…-py.hf.space/mcp` and watch your own model handle the schemas.

Whenever we reference or copy content from outside this repo, we cite the original
source with a link and the author's name.
