---
title: TabArena
emoji: 🥇
colorFrom: green
colorTo: indigo
sdk: gradio
app_file: main.py
pinned: true
license: apache-2.0
short_description: 'Elo-ranked leaderboards for tabular ML, IID and beyond'
sdk_version: 6.22.0
---

# TabArena Leaderboard Code

This repository contains the frontend code to display TabArena leaderboard. 
The leaderboard is hosted on a HuggingFace space.

Reference:
* Website: https://tabarena.ai
* Paper: https://tabarena.ai/paper-tabular-ml-iid-study
* TabArena Codebase: https://tabarena.ai/code

# Install LB Code for Development

```bash
pip install -e ".[dev]"
# Or 
uv pip install -r pyproject.toml
```

# Reading the leaderboard programmatically

The published numbers are plain CSVs in this repo, so the cheapest way to read
them is a direct fetch (no queue, no token, `-L` because the raw path redirects
to the resolve cache):

```bash
curl -sL https://huggingface.co/spaces/TabArena/leaderboard/resolve/main/data/imputation_yes/splits_all/tasks_all/datasets_all/website_leaderboard.csv
```

The path is `data/imputation_{yes,no}/splits_{all,lite}/tasks_{...}/datasets_{...}/`
for TabArena and `data_beyondarena/subsets/{subset}/` for BeyondArena.

The Space also serves three JSON endpoints for agents, defined in `api.py`:
`list_leaderboards`, `get_tabarena_leaderboard`, `get_beyondarena_leaderboard`.
Hugging Face advertises them through the **Agents** button on the Space page,
which points at a generated `agents.md`. See AGENTS.md for the contract and its
one caveat.

# Current Steps to get results:
1. Run https://github.com/autogluon/tabarena/blob/main/scripts/run_generate_website_artifacts.py
2. Delete the current `data` folder contents in this repo to remove old results.
3. Unzip the generated `clean_website_artifacts.zip` zip file into the `data` folder in this repo.
4. Test the LB locally, otherwise you are done :)