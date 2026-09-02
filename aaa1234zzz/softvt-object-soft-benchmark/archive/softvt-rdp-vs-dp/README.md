---
title: SoftVTBench · RDP treatment vs DP
emoji: 🫳
colorFrom: red
colorTo: blue
sdk: static
app_file: index.html
fullWidth: true
header: mini
pinned: false
short_description: "Paired SoftVTBench result: treated RDP 2/5 vs DP 0/5."
---

# SoftVTBench RDP treatment vs DP

Interactive, audit-first visualization of the exactly paired SoftVTBench
object-soft development result.

The headline is deliberately scoped: a **modified RDP treatment** scored 2/5
against 0/5 for frozen DP on five development cells. This is not confirmation
evidence and is not a claim that stock RDP beats stock DP.

`benchmark.json` is the machine-readable data rendered by the Space. The page
visualizes task 0 with SoftVTBench's unmodified, released `demo_0` fixed and
wrist camera files. That expert demonstration uses the same task/reset source
as the evaluated task-0 cell but is not the RDP trajectory; the clean raw
scored capture remains separately linked for audit. All source relationships
and hashes are recorded in `benchmark.json`. The selected benchmark camera and
the scored capture can both be downloaded directly from the page. A dedicated
slow–fast diagram shows the execution-time data flow and both update schedules;
the same structure is recorded under `slow_fast_design` in the JSON. The page
also presents the exact paired task-0 scored captures where the RDP treatment
succeeds and DP fails, with shared-reset provenance and separate downloads. The
comparison players and downloads use 512 px scored MP4s regenerated from the
benchmark's fixed agent-view camera with the performance rendering preset and
TAA. The raw-frame speckle ratios are 0.10% for RDP and 0.11% for DP, below the
3% rejection threshold. The files are stored via Git LFS with no denoising,
resizing, or web re-encoding.

The tactile section synchronizes each scored scene with its exact left and
right GelSight Mini marker-overlay streams. Its two-row timeline renders the
policy's causal binary contact gates from those marker displacements. These are
marker-motion readings, not calibrated force; neither displayed policy arm used
a force channel. All four tactile MP4 hashes and the inclusive contact-gate runs
are recorded under `tactile_visualization` in `benchmark.json`.
