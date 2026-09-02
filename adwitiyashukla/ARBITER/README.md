---
title: ARBITER
emoji: ⚖️
colorFrom: indigo
colorTo: gray
sdk: gradio
app_file: app.py
pinned: false
license: mit
short_description: Reproduce web bugs, then prove it to an independent judge
---

# ARBITER

**Automated Reproduction of Bugs with Independent Trial Evidence Review**

ARBITER takes a bug report, opens a real browser, and tries to reproduce it. Then a second model
looks at the screenshots and the instrumentation logs and decides whether the bug actually showed
up. The second model never sees what the first one was thinking, so it cannot just take the first
one's word for it.

I built this for my master's, after reading about LLM agents that reproduce Android bug reports
and getting stuck on one thing: the agent doing the clicking is also the thing that decides
whether the clicking worked.

This Space runs the parts that need no API key, which happen to be the parts worth showing:

- Benchmark results. All ten reports, including two negative controls whose reports describe
  bugs that do not exist, with each trial's judge reasoning and the screenshots behind it.
- The frame-difference oracle, live. Drop in any screen recording and the real oracle runs on
  it, the same numpy and OpenCV code the pipeline uses. It tells a smooth transition apart from a
  janky one by measuring how concentrated the pixel change is, which is a bug class the DOM cannot
  show you because the DOM looks identical either way.
- Judge isolation, checked in front of you. Pick any recorded trial. The payload is built on
  the spot by the project's own `build_payload`, and the panel next to it checks that the actor's
  written conclusion appears nowhere inside.
- An audit of the judge. Each run's evidence reviewed against a different bug's report, which
  it cannot support. If the judge agreed with everything, this is where it would show.

My run: 8 of 8 seeded bugs reproduced, 0 false positives on the 2 controls, 30 trials, about 11
cents. The judge refused all 8 mismatched pairs in the audit.

I planted the bugs myself, which gives exact ground truth and lets the whole thing run offline,
and also makes it easier than the real world. The full list of things I know are wrong with it is
in the repo.

- Source: https://github.com/adwitiyashukla/ARBITER
- Full HTML report: https://adwitiyashukla.github.io/ARBITER/

MIT licensed.
