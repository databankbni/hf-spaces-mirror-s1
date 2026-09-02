---
title: Visual-Tactile Manipulation Results
emoji: 🧩
colorFrom: green
colorTo: yellow
sdk: static
pinned: false
---

# Visual-Tactile Manipulation Results

Canonical Space for the SoftVT object-soft benchmark, the restored historical TacEx Wipe visualization, and the dated RoboProgram benchmark and simulation atlas.

The retained claim is deliberately narrow: ours outperforms modified RDP and frozen DP on paired goal success, but runtime tactile-off ties normal ours. This is evidence for the hierarchy/controller treatment, not for tactile necessity.

The TacEx rollout uses an earlier method revision and is cross-benchmark context only. Its camera frames visualize a policy that consumed onboard proprioception and force history; they are not policy RGB inputs and are not pooled with SoftVT results.

The benchmark atlas is preserved under `archive/benchmark-atlas/` exactly as it appeared at revision `481ed35562d6bc542356d029ac2272f5bd4b6dc6` (snapshot 2026-08-12, repository revision `21a5c98`). It is historical repository context, not a claim about current main.
