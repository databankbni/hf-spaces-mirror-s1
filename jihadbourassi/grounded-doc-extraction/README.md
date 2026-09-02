---
title: Grounded Document Extraction Lab
emoji: 📄
colorFrom: gray
colorTo: blue
sdk: gradio
sdk_version: 6.24.0
python_version: 3.12.12
app_file: app.py
pinned: false
license: apache-2.0
short_description: Grounded borehole PDF extraction with evidence
---

# Grounded Document Extraction Lab

A small deployed document-extraction system for public or synthetic borehole
PDFs.

The application is deliberately narrow: it extracts four fields and only accepts
a value when the system can link it back to OCR evidence and the configured
validation rules pass.

Target fields:

- borehole reference / ID
- Easting
- Northing
- final depth

The current deployed method is a deterministic **Expert / Hybrid extractor**.

## Try the live application

The Space supports three ways to build a small document basket:

1. **Try public example** - download a known public BGS borehole scan.
2. **Upload PDFs** - add public or synthetic PDFs from your machine.
3. **Explore BGS / SOBI** - search a small sample from the public BGS Onshore
   Borehole Index and select scans to process.

The demo intentionally limits a basket to **5 documents**.

After processing, the application shows:

- one summary row per document;
- extracted values;
- number of accepted fields;
- OCR and extraction latency;
- per-field status and validation;
- provenance;
- textual OCR evidence;
- the source PDF page with evidence regions highlighted;
- the structured JSON result.

## Why "grounded"?

The main design rule is:

> An extracted value should not become accepted business output unless the
> supporting evidence can be identified and validation passes.

The result contract therefore separates:

- `raw_value` - what the extractor produced;
- `accepted_value` - what the system is willing to propagate;
- `evidence` - OCR regions supporting the selected candidate;
- `evidence_traceable` - whether those references resolve back to the
  authoritative OCR document;
- `value_grounded` - whether the selected value is actually supported by source
  OCR text;
- `validation` - domain/configuration validation;
- `provenance` - whether evidence comes from the historical document body, the
  BGS wrapper, or an unknown source.

A result can therefore be technically traceable without being accepted.

For example, coordinates printed only in a BGS wrapper may be detected and
grounded but remain:

```text
status = unsupported
reason = wrapper_only
accepted_value = null