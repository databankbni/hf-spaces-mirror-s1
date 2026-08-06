"""Re-run GA/PSO/CMA-ES on the racing line with the two-motor (Urban Concept)
config wired in ("rule" mode -- the hardware-achievable one), now that
powertrain.py's efficiency-interpolation fix and the corrected BG 42x30 dCore
data are both in place. Writes to the canonical filenames.
"""

from digital_twin import optimize_ga, optimize_pso, optimize_cma

print("=== GA (two-motor, pop=50, gen=40) ===")
optimize_ga.optimize_strategy(
    segment_out_path="data/ga_segment_targets.csv",
    telemetry_out_path="data/simulated_telemetry_ga.csv",
)

print("\n=== PSO (two-motor, pop=20, gen=30) ===")
optimize_pso.optimize_strategy(
    pop_size=20, n_gen=30,
    segment_out_path="data/pso_segment_targets.csv",
    telemetry_out_path="data/simulated_telemetry_pso.csv",
)

print("\n=== CMA-ES (two-motor, pop=20, gen=30) ===")
optimize_cma.optimize_strategy(
    pop_size=20, n_gen=30,
    segment_out_path="data/cma_segment_targets.csv",
    telemetry_out_path="data/simulated_telemetry_cma.csv",
)

print("\nAll done.")
