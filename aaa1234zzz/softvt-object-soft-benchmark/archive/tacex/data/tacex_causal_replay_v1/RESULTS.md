# Results: TacEx Wipe Scarce Replay v1

## Summary

The preregistered `Ours > RDP > DP` hypothesis **failed** on held-out data. Ours had substantially better post-shift expert-action imitation than both baselines, but the remaining order was `DP > RDP`, not `RDP > DP`. The frozen benchmark revision must not be retuned after this result.

| Method | Perception regime                                 | Train seeds | Held-out episodes | Negative-MSE score (95% hierarchical CI) | Action MSE |
| ------ | ------------------------------------------------- | ----------- | ----------------: | ---------------------------------------: | ---------: |
| Ours   | Recorded proprioception + fingertip force history | 0, 1, 2     |                75 |         -0.017886 [-0.022791, -0.013913] |   0.017886 |
| DP     | Recorded proprioception + fingertip force history | 0, 1, 2     |                75 |         -0.133205 [-0.166951, -0.100531] |   0.133205 |
| RDP    | Recorded proprioception + fingertip force history | 0, 1, 2     |                75 |         -0.145735 [-0.183021, -0.108711] |   0.145735 |

This is an offline paired action-replay result, not closed-loop task success. Expert actions are labels, and every checkpoint used eight tactile-action-labeled training episodes.

## Frozen Decision

| Preregistered condition                       | Held-out result                               | Decision |
| --------------------------------------------- | --------------------------------------------- | -------- |
| Pooled score: `Ours > RDP > DP`               | `Ours > DP > RDP`                             | Fail     |
| Ours-minus-RDP positive in at least 2/3 seeds | +0.157635, +0.136083, +0.089829; 3/3 positive | Pass     |
| RDP-minus-DP positive in at least 2/3 seeds   | -0.059249, -0.014992, +0.036652; 1/3 positive | Fail     |
| Ours-minus-RDP paired 95% CI above zero       | +0.127849 [0.087155, 0.168073]                | Pass     |
| RDP-minus-DP paired 95% CI above zero         | -0.012530 [-0.067672, 0.042402]               | Fail     |

The confidence intervals use the frozen 100,000-draw paired hierarchical bootstrap: resample train seeds, then paired episodes within selected seeds, with analysis seed 20260813.

## Per-Seed Scores

Higher negative-MSE score is better.

| Method |    Seed 0 |    Seed 1 |    Seed 2 |
| ------ | --------: | --------: | --------: |
| Ours   | -0.014904 | -0.016424 | -0.022331 |
| DP     | -0.113290 | -0.137514 | -0.148811 |
| RDP    | -0.172539 | -0.152506 | -0.112160 |

## Causal Secondary

RDP was more causally reactive than Ours despite its worse expert-action imitation. DP cannot react after its chunk is sampled under this replay protocol.

| Method | Corrective episodes (Wilson 95% CI) | Any response (Wilson 95% CI) | Mean response L2 | Mean signed XY response |
| ------ | ----------------------------------: | ---------------------------: | ---------------: | ----------------------: |
| RDP    |         41/75, 54.7% [43.4%, 65.4%] |    75/75, 100% [95.1%, 100%] |         0.111068 |               -0.001937 |
| Ours   |         28/75, 37.3% [27.3%, 48.6%] |    75/75, 100% [95.1%, 100%] |         0.015323 |               -0.006536 |
| DP     |                 0/75, 0% [0%, 4.9%] |          0/75, 0% [0%, 4.9%] |         0.000000 |                0.000000 |

Therefore this result supports a narrow claim: Ours best imitates the recorded expert actions in this held-out replay. It does not support `Ours > RDP > DP`, better causal correction than RDP, closed-loop superiority, or robustness across tactile ratios.

## Provenance

| Artifact                | SHA-256                                                            |
| ----------------------- | ------------------------------------------------------------------ |
| Frozen benchmark commit | `c676a3618435bc7a61a5a48635e5121386d5b685`                         |
| Freeze manifest         | `f840cc3558b76b9a9b1ac849297f1eec0287103a361583c021944ad600b5fe49` |
| Held-out output         | `59cdea8c14887f8068a66ecea978209a194bad054ad2f80addd5a16bad13009d` |
| Frozen analysis         | `4e531fd5144011603f66fe09ca6109156599b65105606a14509f5362199217ec` |
| Replay corpus           | `ca0ae517f6e26c63e4654e3e0141dd274ce05a6b29e173b836fe677adb4da347` |
| Episode manifest        | `5dbe44533edf55b1c9813e9e29fd4b6edd15a6bf84fa724e9ba3dc596048c39e` |
| Frozen replay script    | `af4597355ef6fa3893e09d4db646bbe22b43606fadd2604de7828844d31de5ed` |
| Frozen preregistration  | `94c2de3da1e720824bd9937efd8d922392e502668db3e720465f10806cc12eac` |

The immutable run artifacts are under `tacex-causal-replay/20260813T070643Z-b336588d-3436811-19544/tacex_causal_replay_v1` in the registered external run root. The held-out output contains nine cells: three methods by three train seeds, with the same 25 manifest-held-out episodes within each seed.

### Checkpoints

| Cell        | SHA-256                                                            |
| ----------- | ------------------------------------------------------------------ |
| DP seed 0   | `9e0284153d00eac45caf75fcef8846226952ea28c161c77f29e436de6e29f4c8` |
| DP seed 1   | `e8f9e331576da7f0406ae527f407911167953407d9667c90f89c881a5284fd88` |
| DP seed 2   | `bd641854abdcd148c0a482925de8bf30ef015083a113a4332376fd6bbb012409` |
| RDP seed 0  | `e0f8f1df8568e361d9c72f40e2ec25543462f13cf5310b80d1b744dd8432e874` |
| RDP seed 1  | `c49d14f4a9f7c3b3097eb873a3c277dbc306a04910c352c39ba9256c24f67d03` |
| RDP seed 2  | `07f223e6ab3a1ec2338510b0fc68a7cfa9c130483706765694ca944b8f0e204b` |
| Ours seed 0 | `dc04c8af4969a9772363046f1804142901426530f43d7d25d9fccef78f424ca8` |
| Ours seed 1 | `a1cf518cf4d4c41d72b1b763c4c1ab766d6e59a7727846d6923fd1f0e45074b9` |
| Ours seed 2 | `c2b95912e8edc1105ca1cb1306466acdc14b769f00a55eb6e3e56876aab663e3` |
