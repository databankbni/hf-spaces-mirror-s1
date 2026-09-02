---
title: MI-064 Public Reader Guide
emoji: 📊
colorFrom: blue
colorTo: red
sdk: static
app_file: index.html
pinned: false
---

# MI-064 Public Reader Guide

Reader-facing static presentation layer for the sanitized MI-064 v3.1.2 diagnostic
methodology package.

The canonical evidence package remains the Hugging Face dataset:

https://huggingface.co/datasets/rickytzai/mi-064-local-openbook-diagnostics-staging

This Space is presentation only. It does not add raw answers, private reviewer
artifacts, transcripts, internal tables, TAB-Core, leaderboard, safety proof,
Taiwan-readiness, public benchmark authority, or model-superiority claims.

## Interactive readers

- [Laguna XS 2.1 diagnostic reader](phase4_laguna_xs_2_1_20260824.html)
- [Laguna XS 2.1 source-openbook Evidence-Pack retry reader, 2026-08-26](phase4_laguna_xs_2_1_openbook_20260826.html)
- [Laguna XS 2.1 source-openbook Evidence-Pack reader, 2026-08-25](phase4_laguna_xs_2_1_openbook_20260825.html)
- [Laguna XS 2.1 subagent web-capability smoke, 2026-08-25](phase4_laguna_xs_2_1_subagent_web_smoke_20260825.html)
- [Laguna XS 2.1 retest reader, 2026-08-24](phase4_laguna_xs_2_1_retest_20260824.html)
- [Laguna XS 2.1 Western5 review dashboard](MI064_PHASE4_LAGUNA_XS_2_1_WESTERN5_REVIEW_STATUS_20260824.html)

Laguna XS 2.1 2026-08-25 is a source-openbook / Evidence-Pack diagnostic
reader, not a web-openbook browsing run. It does not demonstrate browsing or
search capability for Laguna XS 2.1, and it is not TAB-Core, not a leaderboard,
not Taiwan-readiness approval, not a safety/alignment proof, and not a
model-quality conclusion.

Laguna XS 2.1 2026-08-26 is a source-openbook / Evidence-Pack retry diagnostic
reader with 24 canonical rows, 13 runtime-clean rows, and 11 runtime-invalid
rows after bounded retries. It is not a trusted qualitative review, TAB-Core,
leaderboard, Taiwan-readiness approval, safety/alignment proof, or model-quality
conclusion.

Laguna XS 2.1 subagent web-capability smoke 2026-08-25 routes the subject
model through `sessions_spawn` and uses a compound current-fact probe. The
child answer was factually current, but the parent-visible child history did
not expose actual search/fetch tool telemetry. It is therefore classified as
`claimed_tool_use_without_telemetry`, not completed web-openbook browsing.
