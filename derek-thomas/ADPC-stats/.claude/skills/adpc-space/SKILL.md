---
name: adpc-space
description: Work on the ADPC-stats Hugging Face Space — edit the pages, re-derive the figures from the WhatsApp export, and deploy. Use when asked to update, change, fix, rebuild, verify or push this Space or its charts, when a number on the page is questioned, or when a fresh WhatsApp export needs loading.
---

# ADPC-stats

Static Space at `https://huggingface.co/spaces/derek-thomas/ADPC-stats`, served
straight from `index.html` and `stats.html`. `origin` is the Space, so a push
deploys; there is no build step and no other environment.

## Before touching a number

Run the pipeline and read the numbers off it. Do not trust figures already on the
page, and do not re-derive them ad hoc:

```bash
python3 analysis/extract.py
```

It prints the roster timeline, session counts, sign-ups, capacity figures and the
start-hour histogram, and writes `data/derived.json`. Stdlib only, a few seconds.

If `data/_chat.txt` is missing it unzips the WhatsApp archive in `data/` itself.
For a fresh export, drop the new zip in `data/` and re-run.

## Editing the page

Charts are hand-written SVG built from the arrays at the top of the script block
in `index.html` (`DAILY`, `M`, `POLLS`, `MS`, `SHOURS`). Update an array and the
chart follows; the drawing code rarely needs touching. `stats.html` carries its
own `DAILY` and `M` — keep the two files consistent when the export is refreshed.

Two standing rules, both from review feedback:

- **Bigger means better.** Never ask a reader to invert a chart. An earlier
  version showed "days taken to add each 100 members", where the shortest bar was
  the best news; it was replaced with the roster curve on a real time axis plus
  milestone brackets underneath.
- **Every count declares what it counts and what it misses.** A "session" is a
  scheduling poll posted in the group, which undercounts play arranged by phone or
  in side chats. Where a proxy fails — poll counts collapse from November 2025 to
  March 2026 while the group stayed busy, because play moved to recurring pinned
  posts — the page says so next to the chart.

## Verifying before you push

The browser pane only runs scripts for files under the session's own working
directory; anything else opens as a static snapshot and the charts come up blank
or the page fails to open at all. So start the session in this repo when the
charts need looking at. If you are working from somewhere else, copy
`index.html` into a scratch folder inside that working directory, screenshot it
there, and delete the copy afterwards.

Check both themes (`resize_window` with `colorScheme`) — the page styles light
and dark.

Check the arithmetic on any claim you touched against `extract.py` output, not
against the previous copy of the sentence.

## Deploying

```bash
git add -A && git status --short && git commit -m "…" && git push
```

`git status --short` before committing is the guard that `data/` is still
ignored: nothing from it may ever appear in a commit. The Space is public.

`hf` CLI usage beyond this (listing Spaces, secrets, hardware) is covered by the
`hf-cli` skill.

## Known wrinkles

- The roster reconstruction ends at **510** members while WhatsApp itself reports
  **505**. The gap is how the group's founding members get seeded; the shape of
  the series is identical either way. The page uses 505 and says so.
- Start times are read from poll text only, one count per session. Counting every
  time-like string in every message instead pulls in scores, dates and player caps
  ("MAX 12 MEMBERS") — that bug is what once made the chart show games proposed at
  3 and 4am. `strip_non_times()` in `extract.py` is what keeps it out.
