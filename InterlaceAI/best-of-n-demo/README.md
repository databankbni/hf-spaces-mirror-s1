---
title: Best-of-N
emoji: 🎯
colorFrom: blue
colorTo: gray
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
short_description: 45.3% to 66.5% on GSM8K, frozen 0.5B, no training
---

# Best-of-N

Inference-time compute for any language model. Sample N reasoning trajectories
from a **frozen** model and select among them. No weights are modified.

This page is static and runs entirely in your browser. It shows the measured
results from the published GSM8K dataset — 200 problems, 128 trajectories each,
25,600 in total. Nothing is generated here.

Drag N and two lines separate: the answers the model *reached* (coverage) and
the answer it actually *returned* (majority vote). The distance between them is
the part of the problem that is selection rather than knowledge, and it is what
inference-time compute has left to attack.

```bash
pip install "bestofn[math]"
```

- Package: https://pypi.org/project/bestofn/
- Model card: https://huggingface.co/InterlaceAI/best-of-n
- Code and raw trajectories: https://github.com/voidlinestudios12-jpg/Interlace-AI

**Withdrawn:** an earlier version of this page reported results on AIME 2024
and credited a trained verifier with a 16.6-point gain over majority voting.
Those measurements came from version 1.0.0, which had defects in answer
extraction and in the handling of truncated trajectories; they are not
reproducible with the corrected implementation and should not be cited. The
verifier was never published. Everything here is GSM8K, measured with
`bestofn` 1.1.5, and reproducible from the published dataset.

Apache 2.0 · Alejandro Areces Rivera · Interlace AI
