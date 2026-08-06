---
title: WikiGovern-CX
emoji: 🛡️
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 4.44.1
app_file: app.py
pinned: false
python_version: "3.12"
---

# WikiGovern-CX

**"Can we use this customer data for that?" - ask, and get an answer
with receipts.**

A verified data-governance agent for multi-brand customer data. Every
verdict is decided by rules compiled from policy and contract documents
- never by a language model - and every "no" cites the exact rule,
statement and source clause behind it.

## What it demonstrates

- **Per-record ALLOW / PARTIAL / DENY** with a full citation chain:
  rule -> policy statement -> source document and clause.
- **UNKNOWN beats ALLOW**: if the deciding information was never
  captured (e.g. consent without a date), the gate refuses to guess.
- **Formally detected rule conflicts**: this demo ships one genuine
  contradiction (a 7-year retention policy vs a partner contract's
  2-year destruction clause), found by an SMT solver with the exact
  conflicting clauses named. The agent blocks use, retains the records
  and escalates destruction to humans.
- **Governance-gated identity resolution**: cross-brand identity links
  can only make the gate stricter, never looser - a matching error
  over-blocks, it cannot leak.
- **A standing 4C audit** (Correct / Consistent / Current / Complete):
  provenance completeness, conflict scan, cross-brand semantic drift,
  staleness propagation and regulatory coverage gaps.

## How to use it

Open the **Ask the gate** tab and run the six prepared scenarios, or
build your own query (dataset, purpose, filters). Then read the
**Audit report** and **Data map** tabs. The **About** tab is a
one-page plain-language case note including safety boundaries.

## Safety notes

All customer data is **synthetic**, generated for this demo with
defects planted on purpose so the audit has real findings. No LLM sits
in any verdict path. This is a research demonstrator, not legal advice.

The compiler, conflict scanner, audit harness, approval workflow and
deployment tooling that produce these artifacts are private; this Space
ships their outputs working end to end.

*Author: Bailing Zhang | 4C verification framework*
