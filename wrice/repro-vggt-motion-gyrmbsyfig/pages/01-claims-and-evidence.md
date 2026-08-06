# Claims and Evidence

The machine-readable evidence bundle is `evidence/bundle.json`.

## Toy-Supported Claims

1. VGGT-Motion combines motion-aware submap construction, anchor-driven direct
   Sim(3) registration, and lightweight pose-graph optimization. The bundle
   implements deterministic versions of the submap and Sim(3) components.
2. Motion-aware submap construction uses optical-flow style static and turning
   scores to prune static redundancy while preserving a turning interval. The
   toy check preserves frames `[2, 3, 4]` as one turning submap.

## Inconclusive Claims

1. KITTI ATE improvements over VGGT-Long and other baselines were checked only
   as table-source arithmetic. The paper reports `Ours Avg.* = 18.26` and
   `VGGT-Long Avg.* = 18.28`, but no trajectories or official code were
   released for rerun.
2. Long-sequence 4Seasons, Complex Urban, and A2D2 improvements were checked
   only from table values in the paper source.
3. The topology-aware partitioning ablation was checked only from the reported
   Table 5 values.
4. Runtime speedup claims remain inconclusive because the relevant numbers are
   embedded in a figure and no runtime measurement logs were released.

The reproduction does not present paper-reported benchmark values as reproduced
measurements.
