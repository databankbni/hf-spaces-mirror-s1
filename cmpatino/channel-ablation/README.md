---
title: Channel Ablation Experiments
emoji: 🤝
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# channel-ablation viewer

Serves channel-ablation experiment reports from a bucket mounted read-only at
`/data`. `/` opens the study overview, with dedicated results, metric-definition,
and trace-explorer views. Configure the bucket explicitly when calling
`sync.py --bucket <namespace/name> --space`.
