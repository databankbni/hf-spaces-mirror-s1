---
title: MemorialWiki-4C
emoji: 🕊️
colorFrom: gray
colorTo: yellow
sdk: gradio
sdk_version: 4.44.1
python_version: "3.12"
app_file: app.py
pinned: false
short_description: Formally verified fact checking for family trees
---

# MemorialWiki-4C 🕊️

**Formal verification for digital memorials and family history.**

Online memorials are written by several family members together, and dates
and relationships get mixed up. This Space checks a standard GEDCOM
family-tree file with a symbolic logic engine and reports, in plain
language, every recorded fact that is *provably impossible* (a death before
a birth, an ancestry loop), every fact that is implausible enough to
deserve review, and every gap where information is missing.

**Prove, don't guess:** rules fire only when a problem is provable from the
known parts of the data. Partial dates never produce false alarms, and the
checker never invents a fact about a person.

## Try it in 60 seconds

1. Open **Verify a family tree**, keep the built-in demo sample selected,
   press **Run verification**, and read the findings.
2. Switch to the clean sample for a PASS, or upload your own `.ged` export
   (processed in memory only, never stored).

## Boundaries

Verification only — no advice, no storage of your data, no affiliation with
any memorial platform. The public Space carries the open rule subset; the
full platform (narrative fact extraction, privacy policy verification,
audit log, approval workflow) is a separate private system.

Part of the 4C verified-agent series (Correct / Consistent / Current /
Complete) by [bailing1961](https://huggingface.co/bailing1961).
