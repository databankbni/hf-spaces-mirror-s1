---
title: CapBencher Reproduction
emoji: 📊
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 5.42.0
app_file: app.py
license: apache-2.0
tags:
  - icml2026-repro
  - paper-oCNT5PcMSQ
---

# CapBencher Reproduction

This Space presents a CPU-only reproduction for "How Can I Publish My LLM
Benchmark Without Giving the True Answers Away?" It recomputes the Bayes
accuracy cap, monotonic affine score mapping, exact one-sided binomial
contamination test, and model-merge hacking simulation from the committed
Python artifact and exposes the numeric evidence in the served pages.

The canonical machine-readable output is `evidence/bundle.json`; the visible
judge-facing measurement log is in `pages/00-measurements.md` and
`pages/01-reproduction.md`.
