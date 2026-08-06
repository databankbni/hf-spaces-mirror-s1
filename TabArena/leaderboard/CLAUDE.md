# CLAUDE.md

The primary agent guide for this repo is [`AGENTS.md`](./AGENTS.md). Read it
first; everything in it applies here, including the writing-style rules in its
"AI Writing Tropes to Avoid" section.

This file only records Claude-specific notes.

## TL;DR

* Repo: the Gradio frontend for the TabArena leaderboard, deployed as a
  Hugging Face Space. `main.py` is the entrypoint (`app_file` in the
  `README.md` frontmatter).
* Copy lives in `website_texts.py`, constants in `constants.py`, generated
  artifacts in `data/`. Never hand-edit `data/`.
* Verification bar is manual: run `python main.py` with this repo's own
  `.venv` and click through the affected tabs. No tests are configured.
* Don't commit or push without an explicit ask. Pushing here deploys the
  Space, and `data/` is tracked via Git LFS + Xet.

## Refreshing the data

`data/` is generated in the tabarena repo, not here. The `update-leaderboard`
skill in `../tabarena/.claude/skills/` drives the whole flow: it generates the
website artifacts, swaps them into this repo's `data/` (deleting the old
subtree first, otherwise stale unzipped PNGs survive), and bumps the version
history in `website_texts.py`. Invoke that skill from the tabarena repo rather
than reproducing the steps by hand, and pass it the path to this repo.
