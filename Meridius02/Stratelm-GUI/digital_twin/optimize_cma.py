"""
Covariance Matrix Adaptation Evolution Strategy (CMA-ES) optimizer for gas/glide.
Search space: v_target and v_coast for each of N segments per lap.
Evaluated via simulate.py as the fitness function.
Serves as a comparison to the GA and PSO strategies.
"""

import numpy as np
import pandas as pd
from pymoo.core.problem import ElementwiseProblem
from pymoo.algorithms.soo.nonconvex.cmaes import CMAES
from pymoo.optimize import minimize

from . import config
from . import powertrain
from . import simulate as sim_mod
from . import telemetry as telemetry_mod
from . import track as track_mod
from . import weather as weather_mod

NUM_SEGMENTS_PER_LAP = 30
V_MIN = 15.0 # km/h
V_MAX = 30.0 # km/h -- DRIVEABILITY CAP (2026-07-24), see optimize_ga.py: under the
                     # efficiency motor-select controller the optimizer exploited 44+ km/h
                     # pulses, outside the Urban Concept design regime and not realistic for
                     # the driver. Capped at the 30 km/h design speed for a driveable plan.

class GasGlideProblem(ElementwiseProblem):
    def __init__(self, full_track, scenario, motor, fc, lap_distance_km,
                 accel_motor=None, cruise_motor=None, motor_select_mode="rule",
                 cruise_converter=None):
        self.full_track = full_track
        self.scenario = scenario
        self.motor = motor
        self.fc = fc
        self.accel_motor = accel_motor
        self.cruise_motor = cruise_motor
        self.motor_select_mode = motor_select_mode
        self.cruise_converter = cruise_converter
        self.lap_distance_km = lap_distance_km

        n_var = NUM_SEGMENTS_PER_LAP * 2
        xl = np.full(n_var, V_MIN)
        xu = np.full(n_var, V_MAX)
        super().__init__(n_var=n_var, n_obj=1, n_ieq_constr=1, xl=xl, xu=xu)

    def _evaluate(self, x, out, *args, **kwargs):
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
        time_violation = total_time_s - (config.MAX_ATTEMPT_TIME_MIN * 60.0)

        out["F"] = total_h2_m3 + telemetry_mod.accessory_h2_equivalent_m3(accessory_j)
        out["G"] = time_violation

def optimize_strategy(scenario_name="typical_january", motor_name=config.DEFAULT_MOTOR_NAME, fc_name=config.DEFAULT_FC_NAME,
                       use_two_motor=True, motor_select_mode="rule",
                       pop_size=20, n_gen=30, full_track=None, lap_distance_km=None,
                       segment_out_path=None, telemetry_out_path=None, x0=None):
    print("Loading track and models...")
    if full_track is None:
        profile_1lap = track_mod.build_racing_line_profile(save=False)
        lap_distance_km = profile_1lap["distance_km"].iloc[-1]
        full_track = sim_mod.build_full_attempt_track(profile_1lap)
    elif lap_distance_km is None:
        raise ValueError("lap_distance_km is required when full_track is supplied")
    scenario = weather_mod.SCENARIOS[scenario_name]
    fc = powertrain.load_fuel_cells()[fc_name]

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
    
    # Using CMA-ES instead of GA/PSO
    # Note: CMA-ES usually handles population size automatically based on dimensions,
    # but we can pass it if we want. Pymoo CMAES doesn't always take pop_size directly
    # like GA does without specific parameters, but we can usually omit it or use restarts.
    # To be safe and let CMA-ES choose optimal lambda (pop size):
    # x0 warm-start: at the 30 km/h driveability cap the feasible region (finish <=35 min)
    # is a narrow high-speed corner; CMA-ES started from the mid-range never reaches it. Seed
    # the initial mean with a known-feasible solution (e.g. GA's genes) so it starts inside the
    # feasible region and refines there. sigma kept small so early samples don't scatter out of it.
    if x0 is not None:
        x0 = np.clip(np.asarray(x0, dtype=float), V_MIN, V_MAX)
        algorithm = CMAES(x0=x0, sigma=0.8, pop_size=pop_size)
    else:
        algorithm = CMAES(pop_size=pop_size)

    print(f"Starting CMA-ES optimization ({n_gen} gen){' [warm-started from x0]' if x0 is not None else ''}...")
    res = minimize(
        problem,
        algorithm,
        ("n_gen", n_gen),
        seed=42,
        verbose=True
    )
    
    print("Optimization finished.")
    
    best_x = res.X
    if best_x is None:
        print("No feasible solution found!")
        return None, None, None
        
    v_target_genes = best_x[0::2]
    v_coast_genes = best_x[1::2]
    v_coast_genes = np.minimum(v_coast_genes, v_target_genes)

    s_km = full_track["distance_km"].to_numpy()
    segment_indices = np.floor((s_km % lap_distance_km) / (lap_distance_km / NUM_SEGMENTS_PER_LAP)).astype(int)
    segment_indices = np.clip(segment_indices, 0, NUM_SEGMENTS_PER_LAP - 1)

    seg_width_km = lap_distance_km / NUM_SEGMENTS_PER_LAP
    gene_table = pd.DataFrame({
        "segment": range(NUM_SEGMENTS_PER_LAP),
        "dist_start_km": [i * seg_width_km for i in range(NUM_SEGMENTS_PER_LAP)],
        "dist_end_km": [(i + 1) * seg_width_km for i in range(NUM_SEGMENTS_PER_LAP)],
        "v_target_kmh": v_target_genes,
        "v_coast_kmh": v_coast_genes,
    })
    gene_table.to_csv(segment_out_path or "data/cma_segment_targets.csv", index=False)
    print("\nPer-segment gas/glide targets (from CMA-ES) -> data/cma_segment_targets.csv:")
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
    
    best_telemetry.to_csv(telemetry_out_path or "data/simulated_telemetry_cma.csv", index=False)
    
    return best_telemetry, best_x, score

if __name__ == "__main__":
    optimize_strategy(pop_size=20, n_gen=30)
