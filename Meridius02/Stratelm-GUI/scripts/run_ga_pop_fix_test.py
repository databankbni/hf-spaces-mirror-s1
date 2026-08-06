"""Test whether scaling GA's population size with dimensionality (60 decision vars
at NUM_SEGMENTS_PER_LAP=30) closes the gap to PSO/CMA-ES on the racing line.
Diagnostic (save_history=True run) showed the pop=20 GA stays 100% feasible from
gen 2 onward but keeps improving very slowly right up to gen 30 without plateauing
-- population too small for SBX crossover to have real diversity to work with, not
a constraint-handling problem.
"""

from digital_twin import optimize_ga

print("=== GA (racing line, 30 segments, pop=50, gen=40) ===")
optimize_ga.optimize_strategy(
    pop_size=50, n_gen=40,
    segment_out_path="data/ga_segment_targets_racing_line_seg30_pop50.csv",
    telemetry_out_path="data/simulated_telemetry_ga_racing_line_seg30_pop50.csv",
)
print("\nDone.")
