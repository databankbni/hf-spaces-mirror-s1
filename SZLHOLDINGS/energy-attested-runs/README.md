---
title: Energy-Attested Inference Runs
emoji: ⚡
colorFrom: yellow
colorTo: green
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
short_description: Signed inference receipts - honest energy (measured OR null)
tags:
  - governance
  - attestation
  - dsse
  - energy
  - inference-receipt
  - verify-it-yourself
---


<div align="center">
<p>

[![governed](https://img.shields.io/badge/governed-SZL%20Holdings-3af4c8?style=flat-square)](https://huggingface.co/SZLHOLDINGS)
[![Λ](https://img.shields.io/badge/Λ-Conjecture%201%20advisory-d7b96b?style=flat-square)](https://a-11-oy.com)
[![license](https://img.shields.io/badge/license-apache--2.0-7e8aa3?style=flat-square)](https://huggingface.co/spaces/SZLHOLDINGS/energy-attested-runs)

</p>
</div>
<!-- SZL-ESTATE-CARD:v2:START -->
<p align="center"><a href="https://a-11-oy.com/"><img src="https://huggingface.co/spaces/SZLHOLDINGS/README/resolve/main/assets/estate-banner-v2.svg" alt="SZL Holdings — governed, receipted, verifiable" width="100%"></a></p>
<p align="center">
  <a href="https://github.com/szl-holdings/.github/tree/main/doctrine"><img src="https://img.shields.io/badge/doctrine-v11%20LOCKED-0B1F3A?style=flat-square" alt="doctrine v11"></a>
  <a href="https://a-11-oy.com/"><img src="https://img.shields.io/badge/evidence%20wall-LIVE%20%C2%B7%20verify%20in%20browser-3AF4C8?style=flat-square" alt="live evidence wall"></a>
  <a href="https://huggingface.co/datasets/SZLHOLDINGS/szl-lake"><img src="https://img.shields.io/badge/szl--lake-offline%20verifiable-C9B787?style=flat-square" alt="szl-lake offline verifiable"></a>
  <a href="https://huggingface.co/spaces/SZLHOLDINGS/holographic"><img src="https://img.shields.io/badge/estate%20map-holographic-5B8DEE?style=flat-square" alt="holographic estate map"></a>
</p>
<p align="center"><sub>Part of the <a href="https://huggingface.co/SZLHOLDINGS">SZL Holdings</a> governed estate — claims are designed to carry checkable receipts. Verification proves integrity &amp; origin, never accuracy or performance.</sub></p>
<!-- SZL-ESTATE-CARD:v2:END -->

# ⚡ Energy-Attested Inference Runs

**Run a routed inference → get a signed receipt of its tokens, cost, and energy
— where every field is honestly labelled `MEASURED` or `UNAVAILABLE`. A joule is
never fabricated.**

This is a live demo of SZL Holdings' **energy-attested inference receipt**: the
cheap, honest "receipt tier" of AI trust (not zkML, not a TEE) — a small,
replayable, hash-chained, signable record of what a governed inference actually
cost and consumed.

---

## Why this exists (the real gap)

Energy/cost research **measures** inference (WattGPU, EnerInfer) but does not
**attest** it, and dishonest providers can over-count tokens ("Token Inflation").
A **signed energy + token + cost receipt** is the direct, honest countermeasure.
Almost nobody ships this as a runnable artifact — so we did.

## What you're actually using

- A **local, deterministic mock route** (`local/mock-deterministic-v1`) so the
  Space runs with **zero downloads** and no external model call. It is clearly
  labelled as a mock everywhere.
- **Real** receipt mechanics wrapped around it:
  - **Real token counts** (a deterministic, model-agnostic regex splitter —
    honestly *not* a specific model's BPE count, and the receipt says so).
  - **Honest energy metering.** The Space tries NVML. On HF CPU hardware there
    is no NVML energy counter, so `energy.joules` is `null` and
    `energy.label` is `"UNAVAILABLE (no NVML on this host)"`. **No joule is ever
    fabricated.** On GPU hardware with NVML, `energy.joules` becomes a real
    measured board-level value.
  - **Honest cost.** `cost.usd` is a number *only* when you supply a real
    per-1k-token rate; otherwise it is `null` / `"UNPRICED"`.
  - A **SHA-256 hash chain** (`prev ← digest`) across the session's receipts.
  - A **real ECDSA-P256 signature** (over the DSSE PAE) when a signing key is
    present, else an **UNSIGNED-honest** envelope. A signature is never faked.

## Verify it yourself

Click **"Verify this receipt"** — it runs the **same dependency-free verifier**
published in SZL's open
[`governed-receipt-spec`](https://github.com/szl-holdings/governed-receipt-spec):
it validates each receipt against the JSON Schema, recomputes the DSSE PAE
content hash, and re-walks the `prev ← digest` chain. Receipts emitted here are
**field-aligned with that spec** and pass its verifier.

## Honesty brand (non-negotiable)

- Energy = **measured joules OR honest `null`** — never a fabricated joule.
- `Λ = Conjecture 1` — advisory floor, **never** labelled "green"/"proven".
- Receipts are **signed or UNSIGNED-honest** — never a faked signature.
- This is an audit **receipt**, **not** zero-knowledge and **not** a proof of the
  underlying computation. It proves *what the runtime decided/recorded*.

## The estate

- **Companion dataset** (append-only sample receipts from this Space):
  [`SZLHOLDINGS/energy-attested-runs`](https://huggingface.co/datasets/SZLHOLDINGS/energy-attested-runs)
- **Open spec + offline verifier:**
  [`governed-receipt-spec`](https://github.com/szl-holdings/governed-receipt-spec)
- **Estate:** [a-11-oy.com](https://a-11-oy.com) ·
  [SZLHOLDINGS on Hugging Face](https://huggingface.co/SZLHOLDINGS)

---

*Apache-2.0 · © 2026 SZL Holdings. Built on the ideas in `governed-inference-meter`,
`szl-energy-attest`, and `szl-receipt`.*

---

## SZL Estate

Part of the **SZL Holdings** governed-AI estate — *governed AI you can prove*: every decision carries a signed, checkable receipt.

- **Flagship:** [a11oy command console → a-11-oy.com](https://a-11-oy.com)
- **Orgs:** [GitHub · szl-holdings](https://github.com/szl-holdings) · [Hugging Face · SZLHOLDINGS](https://huggingface.co/SZLHOLDINGS)
- **Related Spaces:** [🧾 guardrail-receipt](https://huggingface.co/spaces/SZLHOLDINGS/guardrail-receipt) · [✅ governed-receipt-verifier](https://huggingface.co/spaces/SZLHOLDINGS/governed-receipt-verifier) · [🔀 llm-router-live](https://huggingface.co/spaces/SZLHOLDINGS/llm-router-live)

**Status:** responding as of 2026-07-09 (HF Space root probe, this session).

<sub>Doctrine v11 · Λ = Conjecture 1 (advisory — never "green"/theorem; open) · honest by design · public data only.</sub>

---

<div align="center">

**[🛡️ SZLHOLDINGS on Hugging Face →](https://huggingface.co/SZLHOLDINGS)**   ·   **[a-11-oy.com →](https://a-11-oy.com)**   ·   **[Estate hub — live →](https://szlholdings-szl-estate-live.static.hf.space)**

### Governed AI you can prove.

<sub>SLSA: L1 honest · L2 attested · L3 roadmap. Λ = Conjecture 1 (advisory, never a theorem). Trust ceiling 0.97 — never 100%. Labels honest by default: MEASURED / REPORTED / MODELED / HEURISTIC / UNKNOWN / UNAVAILABLE. locked-proven = exactly 8 {F1,F4,F7,F11,F12,F18,F19,F22}.</sub>

</div>
