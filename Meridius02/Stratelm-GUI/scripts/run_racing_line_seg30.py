"""Re-run GA/PSO/CMA on the racing line with NUM_SEGMENTS_PER_LAP bumped 15->30,
testing whether finer segment resolution lets them capture the gain DP already
confirmed (+5.5%) instead of getting boxed in by the racing line's multi-apex
curvature (see notebooks/Racing_Line_Strategy_Comparison.ipynb "Finding" cell).
Saves under `_seg30` so the 15-segment racing-line results stay on disk for
comparison too.
"""

from digital_twin import optimize_ga, optimize_pso, optimize_cma

print("=== GA (racing line, 30 segments) ===")
optimize_ga.optimize_strategy(
    pop_size=20, n_gen=30,
    segment_out_path="data/ga_segment_targets_racing_line_seg30.csv",
    telemetry_out_path="data/simulated_telemetry_ga_racing_line_seg30.csv",
)

print("\n=== PSO (racing line, 30 segments) ===")
optimize_pso.optimize_strategy(
    pop_size=20, n_gen=30,
    segment_out_path="data/pso_segment_targets_racing_line_seg30.csv",
    telemetry_out_path="data/simulated_telemetry_pso_racing_line_seg30.csv",
)

print("\n=== CMA-ES (racing line, 30 segments) ===")
optimize_cma.optimize_strategy(
    pop_size=20, n_gen=30,
    segment_out_path="data/cma_segment_targets_racing_line_seg30.csv",
    telemetry_out_path="data/simulated_telemetry_cma_racing_line_seg30.csv",
)

print("\nAll done.")
