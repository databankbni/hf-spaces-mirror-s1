---
title: Template Final Assignment
emoji: 🕵🏻‍♂️
colorFrom: indigo
colorTo: indigo
sdk: gradio
sdk_version: 5.25.2
app_file: app.py
pinned: false
hf_oauth: true
# optional, default duration is 8 hours/480 minutes. Max duration is 30 days/43200 minutes.
hf_oauth_expiration_minutes: 480
---

Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference
# Introduction

A Agent developed for final assignment of Agent Course on Hugging Face, evaluated on a subset of GAIA (20 level-1 questions) with 85% accuracy.

# Architecture

ReAct implemented with Langgraph

# Tools

- `bashtool`: self-implemented.
    - When output is too long, return the tail of the output and save the full output in a file.
    - When output is not too long, return the full output and do not save the output in a file.
    - Use a pipe read thread to avoid OOM.
- `websearch`: Use `DuckDuckGoSearchResults` from `langchain_community.tools`
- `readfile`: Use `ReadFileTool` from `langchain_community.tools`
- `writefile`: Use `WriteFileTool` from `langchain_community.tools`

# Context Management

- Truncated output in `bashtool`
- More to be implemented
    - long-term memory
    - compaction

# RAG

- To be implemented