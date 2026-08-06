"""One-off runner: re-run GA/PSO/CMA/DP on the QP racing line (now the default
track in optimize_ga.py/optimize_pso.py/optimize_cma.py/optimize_dp.py) and save
results under a `_racing_line` suffix, leaving the existing backbone-based
data/{ga,pso,cma,dp}_segment_targets.csv / simulated_telemetry_*.csv untouched as
the "before" comparison baseline for notebooks/Racing_Line_Strategy_Comparison.ipynb.
"""

from digital_twin import optimize_ga, optimize_pso, optimize_cma, optimize_dp

print("=== DP (racing line) ===")
dp_result = optimize_dp.run_dp_benchmark(
    telemetry_out_path="data/simulated_telemetry_dp_racing_line.csv",
)
print(f"DP racing-line score: {dp_result['score_km_per_m3']:.1f} km/m^3, H2 {dp_result['h2_m3']*1000:.2f} L")

print("\n=== GA (racing line) ===")
optimize_ga.optimize_strategy(
    pop_size=20, n_gen=30,
    segment_out_path="data/ga_segment_targets_racing_line.csv",
    telemetry_out_path="data/simulated_telemetry_ga_racing_line.csv",
)

print("\n=== PSO (racing line) ===")
optimize_pso.optimize_strategy(
    pop_size=20, n_gen=30,
    segment_out_path="data/pso_segment_targets_racing_line.csv",
    telemetry_out_path="data/simulated_telemetry_pso_racing_line.csv",
)

print("\n=== CMA-ES (racing line) ===")
optimize_cma.optimize_strategy(
    pop_size=20, n_gen=30,
    segment_out_path="data/cma_segment_targets_racing_line.csv",
    telemetry_out_path="data/simulated_telemetry_cma_racing_line.csv",
)

print("\nAll done.")
