---
title: Pythia Paths
emoji: 🔭
colorFrom: indigo
colorTo: yellow
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
short_description: See a training path without mistaking it for permission.
---

# Pythia Paths

**See the path. Do not mistake it for permission.**

Pythia Paths is a small, read-only study of language-model training trajectories.
It starts with public checkpoints and evaluations from EleutherAI's Pythia suite.

The project keeps four things separate:

1. **Observation** — what a pinned source actually reports.
2. **Derivation** — arithmetic made from those observations, with the rule shown.
3. **Interpretation** — a bounded, falsifiable claim that may still be wrong.
4. **Authority** — a separate human or project decision permitting an exact effect.

A rising line is not a vote. A checkpoint is not a person. A model output cannot
authorize more training, retention, publication, or promotion.

## What is here

- `dataset/` — two Dataset-ready evidence layers, schemas, and a release lock.
- `index.html`, `styles.css`, and `app.js` — a dependency-free Static Space.
- `PROTOCOL.md` — the evidence and branch-decision protocol.
- `PYTHIA.md` — the primary-source deep audit and corrected study roadmap.
- `tests/` — schema, provenance, and authority-boundary checks.

The first layer contains all 27 published PIQA reports in one pinned evaluation
directory for `EleutherAI/pythia-70m-deduped`. It does not fill the 127 released
checkpoint positions that lack a report there. A second layer adds branch-target
metadata observed at the stated review time and artifact-pointer metadata for
four reports hand-selected after their values were known. Those four are detail
receipts, not a representative trajectory.
Points are not joined or ranked, so the display establishes neither a smooth path
nor an honest scalar called “overall momentum.”

## Run locally

```bash
python3 -m http.server 8000
open http://localhost:8000/
```

Run the checks:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

No model is downloaded or executed. The app reads two bundled same-origin data
files and one release lock with credentials omitted. It fails closed if any
reviewed digest or exact locked field changes. It makes no automatic cross-origin
request. A visitor can choose to follow clearly labelled source links to Hugging
Face or GitHub.

The digest chain checks release consistency; it is not a signature and does not
authenticate upstream provenance. Hugging Face repository commits provide the
external release boundary.

## Published on Hugging Face

The project has two public front doors:

- [Pythia Paths Evidence — pinned commit](https://huggingface.co/datasets/Yu-and-Ai/pythia-paths-evidence/tree/62158de98be1f515917a409a4d1efdae413c7427), the evidence source;
- [Pythia Paths Static Space](https://huggingface.co/spaces/Yu-and-Ai/pythia-paths), the read-only public window.

The Space bundles the exact reviewed Dataset bytes so its runtime remains
same-origin and dependency-free. No model weights, paid inference, or persistent
compute are used.

## License

Original project code and documentation are available under Apache-2.0. Upstream
models, evaluations, and cited materials keep their own terms. No model weights
or Pile text are copied into this repository.
