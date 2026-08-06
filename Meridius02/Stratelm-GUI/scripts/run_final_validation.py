"""Final re-validation after the motor efficiency interpolation fix
(powertrain.py) and the DP phantom-stop fix (optimize_dp.py) -- both affect H2
cost for every algorithm, not just DP. Re-runs all four with their current
actual defaults (GA pop=50/gen=40, PSO/CMA pop=20/gen=30, all at
NUM_SEGMENTS_PER_LAP=30 on the racing line) and writes straight to the
canonical filenames, since these are the final promoted numbers.
"""

from digital_twin import optimize_ga, optimize_pso, optimize_cma, optimize_dp

print("=== DP ===")
dp_result = optimize_dp.run_dp_benchmark(telemetry_out_path="data/simulated_telemetry_dp.csv")
print(f"DP score: {dp_result['score_km_per_m3']:.1f} km/m^3, H2 {dp_result['h2_m3']*1000:.2f} L")

print("\n=== GA (pop=50, gen=40) ===")
optimize_ga.optimize_strategy(
    segment_out_path="data/ga_segment_targets.csv",
    telemetry_out_path="data/simulated_telemetry_ga.csv",
)

print("\n=== PSO (pop=20, gen=30) ===")
optimize_pso.optimize_strategy(
    pop_size=20, n_gen=30,
    segment_out_path="data/pso_segment_targets.csv",
    telemetry_out_path="data/simulated_telemetry_pso.csv",
)

print("\n=== CMA-ES (pop=20, gen=30) ===")
optimize_cma.optimize_strategy(
    pop_size=20, n_gen=30,
    segment_out_path="data/cma_segment_targets.csv",
    telemetry_out_path="data/simulated_telemetry_cma.csv",
)

print("\nAll done.")
