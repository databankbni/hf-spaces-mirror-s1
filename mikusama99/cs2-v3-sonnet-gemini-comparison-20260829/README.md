---
title: CS2 V3 Sonnet vs Gemini 3.5 Flash
emoji: 🧭
colorFrom: yellow
colorTo: green
sdk: static
app_file: index.html
pinned: false
---

# V3 / Five Windows

A credential-free static comparison of the previous Sonnet v3 whole-clip labels and the Gemini 3.5 Flash rerun. Every case is shown with the fixed 81-frame contract: frame 0 conditioning plus five `[1,17) ... [65,81)` windows.

The old Sonnet labels are intentionally kept as a legacy baseline; they contain one whole-clip segment. The Gemini labels contain five local segments and are shown row-by-row with the chunk evidence images. One retry did not include local chunk images in the model request; that case is marked in the gallery.
