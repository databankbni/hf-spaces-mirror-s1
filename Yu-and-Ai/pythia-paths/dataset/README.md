---
pretty_name: Pythia Paths Evidence
license: apache-2.0
tags:
  - interpretability
  - evaluation
  - training-dynamics
  - provenance
size_categories:
  - n<1K
configs:
  - config_name: detailed_receipts
    data_files:
      - split: evidence
        path: data/evidence.jsonl
  - config_name: published_piqa_context
    data_files:
      - split: reports
        path: data/published-piqa-context.jsonl
---

# Pythia Paths Evidence

A small, revision-pinned evidence bundle for examining model-training paths
without converting a trend into authority.

Companion read-only interface: [Pythia Paths Static Space](https://huggingface.co/spaces/Yu-and-Ai/pythia-paths)
(mutable navigation; the evidence files below remain digest-pinned).

## Initial scope

- Model: `EleutherAI/pythia-70m-deduped`
- Run: the default public run only
- Context coverage: all 27 zero-shot reports in one pinned directory
- Detailed coverage: four post-outcome-selected metadata receipts
- Values: PIQA normalized accuracy and its reported standard error
- App scope: no model, training, or persistent-write action is initiated

This is not a multi-seed momentum study. The model run has 154 released
weight-checkpoint positions, while the pinned zero-shot directory has only 27
checkpoint reports. The context layer includes all 27 and records that 127
positions have no report there. It does not call itself a complete trajectory.

PIQA was hand-selected after outcomes were available from 87 tasks common to all
27 reports, omitting 86 tasks. Four reports were also selected after outcomes for
richer inspection; the other 23 still retain exact metric-source receipts. No
representativeness is claimed. Selection is explicit in every detailed row and
in the source manifest.

## Provenance

For each branch label, the bundle records the **target commit observed at the
stated review time** and reported safetensors LFS object ID, without
downloading model bytes. Every metric links to an evaluation JSON and Git blob in
a pinned commit of the official Pythia repository.

The historical evaluation JSON names a mutable branch, not an evaluated model
commit or artifact digest. Binding the reported metric to that observed branch target
is therefore `not_proven`; the two receipts remain separate.
Tokens seen are explicitly marked as derived from:

`training step × 2,097,152 tokens per step`.

## Limitations

The upstream evaluation configuration differs between the early and later
reports—including batch size, device, and an early-only `use_accelerate` flag—and
it does not pin an exact evaluation-harness revision or sample count. Metric
comparability therefore remains `not_proven`.

This bundle does not establish causality, generality across seeds, a best
checkpoint, an overall score, identity, preference, or permission for any action.
No Pile text or model-generated text is included.

The app fetches both bundled same-origin data layers and the release lock with
credentials omitted. Navigation to cited sources happens only when a visitor
chooses a link.

`release-lock.json` binds exact files and detailed values for release consistency.
The JSON Schemas validate record shape and status vocabulary only; the release
lock and digest checks bind this reviewed release. Neither mechanism is a
signature or authenticates the publisher or upstream provenance. Verify dataset
checksums from this directory:

```bash
cd dataset
shasum -a 256 -c SHA256SUMS
```
