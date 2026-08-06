---
title: "FINAL-Bench Quantum: An Open, Neutral Benchmark for Quantum-Computing Methods"
thumbnail:
authors:
- user: SeaWolf-AI
tags: [quantum, quantum-error-correction, benchmark, qec, vqe, qram]
---

# FINAL-Bench Quantum: An Open, Neutral Benchmark for Quantum-Computing Methods

Quantum-computing results are remarkably hard to compare. The same "logical error rate (LER)" or
"query fidelity" can mean entirely different things depending on the code, the noise model, the
hardware, and how many shots were taken. **FINAL-Bench Quantum** is our attempt to bring *one fair
yardstick* to that confusion: a suite where methods compete in five events under **identical,
published protocols**, and where every number is clearly labeled as either *measured here* or
*quoted from a source*.

🔗 **Leaderboard:** `huggingface.co/spaces/FINAL-Bench/quantum-bench-leaderboard`

## The core rule — two tracks

- **Track A (Verified).** Methods are *measured here* on one frozen, public test set and reported
  with 95% confidence intervals. These numbers **are** directly comparable.
- **Track B (Reported).** Numbers *quoted* from each paper or announcement. Codes, noise models,
  and hardware differ, so they are **not** directly comparable — and we say so plainly.

Two principles hold throughout:

1. **No quantum-advantage claims.**
2. **A simulation is labeled a simulation; real hardware is named with its chip.** When two results
   fall within each other's confidence intervals, we call it a **statistical tie** rather than
   crowning a winner.

## The five events

| Event | What it measures | One-line analogy |
|---|---|---|
| ① **QEC Decoder** | logical error rate on a rotated surface code (Stim, circuit noise) | accuracy of a quantum "spell-checker" |
| ② **Optimization** | Max-Cut quality (cut found / optimum) | finding the best answer among astronomically many |
| ③ **VQE** | molecular ground-state energy vs the exact solution | quantum energy calculation for chemistry/drugs |
| ④ **QRAM** | quantum-memory query fidelity | accuracy of a quantum "memory chip" |
| ⑤ **Simulation** | how large a circuit a classical method can handle | faking a quantum computer on a classical one |

Each event tab is organized as **A. verified measurements / B. real hardware (where available) /
C. published references**, alongside dedicated **📈 Charts** (threshold, distance-scaling, and
latency-vs-accuracy plots), **🏅 Medals** (participation by country), and **ℹ️ About**
(methodology and citation).

## How to read the tables

- **Flag** = a method's / team's origin; **By** = its authors (e.g., Tesseract = Google Quantum AI,
  PyMatching = O. Higgott).
- **✓ VERIFIED** = measured on this benchmark. **REPORTED** = quoted from a source.
- The **±value** next to a number is its 95% confidence interval. Overlapping intervals mean a tie.
- The **latency** column matters as much as accuracy — a decoder that is "accurate but slow" can be
  useless for real-time error correction, where decoding must keep pace with the QPU cycle.

## How to submit

The **📤 Submit** tab takes a method name, links (GitHub / Hugging Face), an email, and an optional
results file. Submissions are **stored privately**, reproduced under the event's fixed protocol, and
the submitter is emailed about inclusion. Listed entries appear with the same origin and author
labels as everyone else.

## Why neutrality is the whole point

A leaderboard is only useful if you can trust it. So FINAL-Bench Quantum is built on a discipline:
**include strong competitors even when they beat the host's own entries, quote sources faithfully,
and never round a simulation up into a hardware claim.** Methods from Google, IBM, NVIDIA, USTC,
Riverlane and others sit next to a Korean entry (VIDRAFT 🇰🇷) under the *same* protocol, confidence
intervals, and honesty boundaries.

Quantum computing has not yet reached the fault-tolerant era — which is exactly why a shared,
hype-free yardstick that honestly records *what has actually been measured today* is worth building.
Come and compete with your own method.

*A methods paper is in preparation. Feedback and submissions are welcome.*
