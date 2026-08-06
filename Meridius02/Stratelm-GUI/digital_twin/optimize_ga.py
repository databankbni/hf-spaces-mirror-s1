"""
Genetic Algorithm strategy optimizer for gas/glide.
Search space: v_target and v_coast for each of N segments per lap.
Evaluated via simulate.py as the fitness function.
"""

import numpy as np
import pandas as pd
from pymoo.core.problem import ElementwiseProblem
from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.optimize import minimize
from pymoo.operators.sampling.rnd import FloatRandomSampling
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM

from . import config
from . import powertrain
from . import simulate as sim_mod
from . import telemetry as telemetry_mod
from . import track as track_mod
from . import weather as weather_mod

NUM_SEGMENTS_PER_LAP = 30
V_MIN = 15.0 # km/h
V_MAX = 30.0 # km/h -- DRIVEABILITY CAP (2026-07-24). Physics is feasible higher, but
                     # under the efficiency motor-select controller the optimizer exploited
                     # 44+ km/h pulses -- outside the Urban Concept design regime and not a
                     # realistic speed for the driver. Capped at the 30 km/h design speed so
                     # the commanded pulse-and-glide stays humanly driveable.
# Default pop_size/n_gen below (50/40, not pymoo's usual small-problem defaults):
# diagnosed via save_history=True that pop=20 stays 100% feasible from gen 2 onward
# but keeps improving only incrementally through gen 30 without plateauing -- a
# real-coded GA's SBX crossover needs population diversity to make real progress,
# and 20 individuals across n_var=NUM_SEGMENTS_PER_LAP*2=60 dimensions is too thin
# (unlike PSO/CMA-ES here, which converged fine at pop=20 on the same problem --
# this is specific to crossover-based recombination, not a generic "more segments
# needs more budget" rule).

class GasGlideProblem(ElementwiseProblem):
    def __init__(self, full_track, scenario, motor, fc, lap_distance_km,
                 accel_motor=None, cruise_motor=None, motor_select_mode="rule",
                 cruise_converter=None):
        self.full_track = full_track
        self.scenario = scenario
        self.motor = motor
        self.fc = fc
        # Two-motor (Urban Concept) mode when both are set -- see simulate.py.
        # "rule" mode specifically: the only one of the two switching modes that's
        # hardware-achievable (see config.py/simulate.py docstrings); "efficiency"
        # mode is an analysis-only ceiling, never what the search should optimize
        # a real strategy against.
        self.accel_motor = accel_motor
        self.cruise_motor = cruise_motor
        self.motor_select_mode = motor_select_mode
        self.cruise_converter = cruise_converter
        # actual measured lap length (from the GPS track), NOT config.LAP_DISTANCE_KM
        # (3.7, the rulebook's rounded figure) -- using the rounded value here made
        # segment boundaries drift from their real physical location by ~24m/lap,
        # ~72m (~30% of one segment) by lap 4. This is what maps genes to physical
        # track locations, so it must match build_full_attempt_track()'s tiling exactly.
        self.lap_distance_km = lap_distance_km

        n_var = NUM_SEGMENTS_PER_LAP * 2
        xl = np.full(n_var, V_MIN)
        xu = np.full(n_var, V_MAX)
        super().__init__(n_var=n_var, n_obj=1, n_ieq_constr=1, xl=xl, xu=xu)

    def _evaluate(self, x, out, *args, **kwargs):
        # x is [v_target_0, v_coast_0, v_target_1, v_coast_1, ...]
        v_target_genes = x[0::2]
        v_coast_genes = x[1::2]
        
        # Ensure v_coast <= v_target
        v_coast_genes = np.minimum(v_coast_genes, v_target_genes)
        
        # Map genes to track array
        s_km = self.full_track["distance_km"].to_numpy()
        segment_indices = np.floor((s_km % self.lap_distance_km) / (self.lap_distance_km / NUM_SEGMENTS_PER_LAP)).astype(int)
        segment_indices = np.clip(segment_indices, 0, NUM_SEGMENTS_PER_LAP - 1)
        
        v_target_kmh = v_target_genes[segment_indices]
        v_coast_kmh = v_coast_genes[segment_indices]
        
        # Run simulation
        telemetry = sim_mod.simulate(
            self.full_track, self.scenario,
            motor=self.motor, fc=self.fc,
            accel_motor=self.accel_motor, cruise_motor=self.cruise_motor,
            motor_select_mode=self.motor_select_mode,
            v_target_kmh=v_target_kmh, v_coast_kmh=v_coast_kmh,
            cruise_converter=self.cruise_converter
        )
        
        total_time_s = telemetry["t_s"].iloc[-1]
        total_h2_m3 = telemetry["h2_cumulative_m3"].iloc[-1]
        accessory_j = telemetry["accessory_energy_cumulative_j"].iloc[-1]

        # Constraint: total_time_s <= MAX_ATTEMPT_TIME_MIN * 60
        # If constraint > 0, it's violated.
        time_violation = total_time_s - (config.MAX_ATTEMPT_TIME_MIN * 60.0)

        # Objective: minimize Art. 54e net H2 (flow-meter + accessory-battery joulemeter
        # equivalent) -- NOT just flow-meter H2 alone, since accessory energy scales with
        # elapsed time and so trades off against how much time the strategy spends gliding.
        out["F"] = total_h2_m3 + telemetry_mod.accessory_h2_equivalent_m3(accessory_j)
        out["G"] = time_violation

def optimize_strategy(scenario_name="typical_january", motor_name=config.DEFAULT_MOTOR_NAME, fc_name=config.DEFAULT_FC_NAME,
                       use_two_motor=True, motor_select_mode="rule",
                       pop_size=50, n_gen=40, full_track=None, lap_distance_km=None,
                       segment_out_path=None, telemetry_out_path=None, x0=None):
    print("Loading track and models...")
    if full_track is None:
        profile_1lap = track_mod.build_racing_line_profile(save=False)
        lap_distance_km = profile_1lap["distance_km"].iloc[-1]  # actual measured lap length (racing line)
        full_track = sim_mod.build_full_attempt_track(profile_1lap)
    elif lap_distance_km is None:
        raise ValueError("lap_distance_km is required when full_track is supplied")
    scenario = weather_mod.SCENARIOS[scenario_name]
    fc = powertrain.load_fuel_cells()[fc_name]

    # Two-motor (Urban Concept) is the real current digital-twin configuration --
    # default to it so the strategy search reflects the actual powertrain, not a
    # single leftover default motor. use_two_motor=False keeps the old single-motor
    # path available (e.g. for a like-for-like comparison against a candidate motor).
    motor = accel_motor = cruise_motor = cruise_converter = None
    if use_two_motor:
        motors = powertrain.load_motors()
        accel_motor = motors[config.ACCEL_MOTOR_NAME]
        cruise_motor = motors[config.CRUISE_MOTOR_NAME]
        cruise_converter = powertrain.load_converters()[config.CRUISE_CONVERTER_NAME]
    else:
        motor = powertrain.load_motors()[motor_name]

    problem = GasGlideProblem(full_track, scenario, motor, fc, lap_distance_km,
                              accel_motor=accel_motor, cruise_motor=cruise_motor,
                              motor_select_mode=motor_select_mode,
                              cruise_converter=cruise_converter)
    
    # x0 warm-start: for tight feasible regions (e.g. stopgo + strong headwind at the 30 km/h
    # cap) a random population rarely samples the high-speed corner that finishes <35 min. Seed
    # the initial population around a known-feasible solution (perturbed copies) so the search
    # starts feasible and optimises down.
    if x0 is not None:
        x0 = np.clip(np.asarray(x0, dtype=float), V_MIN, V_MAX)
        rng = np.random.default_rng(42)
        pop0 = np.clip(x0[None, :] + rng.normal(0.0, 1.5, (pop_size, x0.size)), V_MIN, V_MAX)
        pop0[0] = x0
        sampling = pop0
    else:
        sampling = FloatRandomSampling()
    algorithm = GA(
        pop_size=pop_size,
        sampling=sampling,
        crossover=SBX(prob=0.9, eta=15),
        mutation=PM(eta=20),
        eliminate_duplicates=True
    )
    
    print(f"Starting GA optimization ({pop_size} pop, {n_gen} gen)...")
    res = minimize(
        problem,
        algorithm,
        ("n_gen", n_gen),
        seed=42,
        verbose=True
    )
    
    print("Optimization finished.")
    
    # Run best solution to get telemetry
    best_x = res.X
    if best_x is None:
        print("No feasible solution found! (Maybe time constraint too strict for the current parameters)")
        # fallback to best unfeasible if needed, but pymoo res.X is None if not feasible
        return None, None, None
        
    v_target_genes = best_x[0::2]
    v_coast_genes = best_x[1::2]
    v_coast_genes = np.minimum(v_coast_genes, v_target_genes)

    s_km = full_track["distance_km"].to_numpy()
    segment_indices = np.floor((s_km % lap_distance_km) / (lap_distance_km / NUM_SEGMENTS_PER_LAP)).astype(int)
    segment_indices = np.clip(segment_indices, 0, NUM_SEGMENTS_PER_LAP - 1)

    # the ACTUAL answer to "what is our target cruising speed" -- there isn't one
    # number, there are up to NUM_SEGMENTS_PER_LAP different (v_target, v_coast)
    # pairs, one per lap segment. This is the real, reproducible source of truth
    # (straight from the GA's own decision variables), not a value reverse-engineered
    # by eyeballing the noisy resulting speed trace.
    seg_width_km = lap_distance_km / NUM_SEGMENTS_PER_LAP
    gene_table = pd.DataFrame({
        "segment": range(NUM_SEGMENTS_PER_LAP),
        "dist_start_km": [i * seg_width_km for i in range(NUM_SEGMENTS_PER_LAP)],
        "dist_end_km": [(i + 1) * seg_width_km for i in range(NUM_SEGMENTS_PER_LAP)],
        "v_target_kmh": v_target_genes,
        "v_coast_kmh": v_coast_genes,
    })
    gene_table.to_csv(segment_out_path or "data/ga_segment_targets.csv", index=False)
    print("\nPer-segment gas/glide targets (the real answer to 'what's our cruise target') "
          "-> data/ga_segment_targets.csv:")
    print(gene_table.to_string(index=False))
    
    v_target_kmh = v_target_genes[segment_indices]
    v_coast_kmh = v_coast_genes[segment_indices]
    
    best_telemetry = sim_mod.simulate(
        full_track, scenario,
        motor=motor, fc=fc,
        accel_motor=accel_motor, cruise_motor=cruise_motor, motor_select_mode=motor_select_mode,
        v_target_kmh=v_target_kmh, v_coast_kmh=v_coast_kmh,
        cruise_converter=cruise_converter
    )

    total_dist_km = best_telemetry["s_m"].iloc[-1] / 1000.0
    total_h2_m3 = best_telemetry["h2_cumulative_m3"].iloc[-1]
    accessory_j = best_telemetry["accessory_energy_cumulative_j"].iloc[-1]
    accessory_h2_equiv_l = telemetry_mod.accessory_h2_equivalent_m3(accessory_j) * 1000
    score = telemetry_mod.h2_score_km_per_m3(total_dist_km, total_h2_m3, accessory_energy_j=accessory_j)

    print(f"Motor config: {'two-motor (' + accel_motor.name + ' + ' + cruise_motor.name + ', ' + motor_select_mode + ' mode)' if use_two_motor else motor.name}")
    print(f"Best H2 consumption (flow meter, incl. FC parasitic load): {total_h2_m3*1000:.4f} L")
    print(f"Accessory battery: {accessory_j/1000:.1f} kJ -> {accessory_h2_equiv_l:.4f} L H2-equivalent")
    print(f"Best Art. 54e net score: {score:.1f} km/m^3 H2")
    
    # Save optimized telemetry
    best_telemetry.to_csv(telemetry_out_path or "data/simulated_telemetry_ga.csv", index=False)
    
    return best_telemetry, best_x, score

if __name__ == "__main__":
    optimize_strategy()
