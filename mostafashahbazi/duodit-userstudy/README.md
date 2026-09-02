---
title: Duodit Userstudy
emoji: 🐠
colorFrom: red
colorTo: red
sdk: gradio
sdk_version: 6.18.0
python_version: '3.13'
app_file: app.py
pinned: false
---

## Result storage

The app saves a local CSV/JSONL backup and can also commit completed submissions to a Hugging Face Dataset repo.

Set this Space secret:

- `HF_TOKEN` with write access to create/update a dataset repo.

All non-secret settings have defaults:

- `HF_DATASET_REPO_ID`: defaults to `<SPACE_AUTHOR_NAME>/<SPACE_REPO_NAME>-results` on Spaces, or `mostafashahbazi/duodit-user-study-results` locally.
- `HF_RESULTS_DIR`: defaults to `data/submissions`.
- `HF_DATASET_PRIVATE`: defaults to `true`.
- `HF_DATASET_NAMESPACE`: optional override for the default dataset namespace.
- `HF_RESULTS_REPO_NAME`: optional override for the default dataset repo name.

Each completed participant submission is stored as one JSONL file in the dataset repo. This avoids concurrent users overwriting one shared file.

Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference
