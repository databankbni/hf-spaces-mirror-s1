"""
Motor / Fuel Cell / Converter models, loaded from digitized datasheet curves
(data/motor_candidates.csv, data/fc_candidates.csv).

Kept deliberately separate from vehicle.py: vehicle.py only ever produces
"required traction force/power at the wheel" -- this module answers "what
does it cost (electrical, then H2) to deliver that with a SPECIFIC
motor/FC combo". Swapping candidates here never touches vehicle.py
or simulate.py's stepping logic, which is what makes hardware_search.py's
motor x FC enumeration possible later without duplicating the physics.

The FC+supercapacitor hybrid energy system (real Maxwell BMOD0058-E016-C02
hardware) is modeled in hybrid_energy.py, not here -- this module no longer
carries a generic placeholder buffer model (see git history if you need it).
"""

import numpy as np
import pandas as pd

from . import config

MOTOR_CSV = "data/motor_candidates.csv"
FC_CSV = "data/fc_candidates.csv"


class MotorModel:
    def __init__(self, name: str, table: pd.DataFrame):
        self.name = name
        self.voltage_v = table["voltage_v"].iloc[0]
        self.table = table.sort_values("power_w").reset_index(drop=True)
        self._valid = self.table.dropna(subset=["efficiency_pct"])
        # Precompute electrical power at each measured point directly (mech_power /
        # efficiency), rather than interpolating efficiency (a ratio) and dividing at
        # query time -- see electrical_power_w()'s docstring for why that distinction
        # matters: every candidate motor's datasheet anchors its first row at (~0 W,
        # 0% efficiency), and straight-line interpolation between that and the next
        # point makes mech_power/efficiency collapse to an exact CONSTANT for the
        # whole first segment (confirmed: 192.09 W for any request between 0-170 W on
        # the default Innotec candidate) -- a pure artifact of interpolating a ratio
        # through its own degenerate point, not real motor behavior. This hits the
        # two-motor cruise candidate ("BG 42x45 dCore") even harder: its degenerate
        # segment (0.28-36 W) covers most of its 226 W operating range, exactly the
        # low-power band it's chosen for. Interpolating the derived electrical-power
        # values themselves instead gives identical results at the actual measured
        # points but a smooth ramp in between, using only the same datasheet data.
        mech = self._valid["power_w"].to_numpy(dtype=float)
        eff = self._valid["efficiency_pct"].to_numpy(dtype=float) / 100.0
        self._elec_mech_w = mech
        self._elec_power_w = np.divide(mech, eff, out=np.zeros_like(mech), where=eff > 0)

    @property
    def is_voltage_legal(self) -> bool:
        """Whole-vehicle electrical system voltage ceiling (team's global rule
        mastersheet, 2026-07: max 60V). A motor failing this is a technical-inspection
        disqualification risk, not just a design suboptimality."""
        return self.voltage_v <= config.MAX_ELECTRICAL_VOLTAGE_V

    def max_mech_power_w(self) -> float:
        return float(self.table["power_w"].max())

    def rpm_at_power(self, power_w: float) -> float:
        return float(np.interp(power_w, self.table["power_w"], self.table["rpm"]))

    def efficiency_at_power(self, power_w: float) -> float:
        eff_pct = np.interp(power_w, self._valid["power_w"], self._valid["efficiency_pct"])
        return float(eff_pct) / 100.0

    def electrical_power_w(self, mech_power_w: float) -> tuple[float, bool]:
        """Returns (electrical input power, was_clipped) -- clipped=True means the
        requested mechanical power exceeded this motor's physical capability.

        Interpolates electrical power directly from the precomputed (mech_power_w,
        elec_power_w) points (see __init__), NOT via efficiency_at_power() -- that
        would re-introduce the degenerate flat-ratio artifact this fix removes."""
        clipped = mech_power_w > self.max_mech_power_w()
        mech_power_w = min(mech_power_w, self.max_mech_power_w())
        if mech_power_w <= 0:
            return 0.0, clipped
        return float(np.interp(mech_power_w, self._elec_mech_w, self._elec_power_w)), clipped

    def rpm_range(self) -> tuple[float, float]:
        return float(self.table["rpm"].min()), float(self.table["rpm"].max())


def load_motors(path: str = MOTOR_CSV, include_illegal: bool = False) -> dict:
    """By default, excludes motors exceeding the 60V whole-vehicle voltage ceiling
    (team's global rule mastersheet, 2026-07) -- e.g. the Mitsubishi M2096D-III (96V)
    is a technical-inspection disqualification risk, not just a suboptimal choice, so
    it must not be silently selectable by hardware_search.py or anything else later.
    Pass include_illegal=True only for an explicit side-by-side comparison/report."""
    df = pd.read_csv(path)
    motors = {name: MotorModel(name, group) for name, group in df.groupby("motor_name")}
    if include_illegal:
        return motors
    excluded = [m.name for m in motors.values() if not m.is_voltage_legal]
    if excluded:
        print(f"powertrain.load_motors(): excluding {excluded} -- exceeds "
              f"{config.MAX_ELECTRICAL_VOLTAGE_V}V vehicle electrical limit (technical-inspection risk)")
    return {name: m for name, m in motors.items() if m.is_voltage_legal}


class FuelCellModel:
    def __init__(self, name: str, rated_power_w: float, table: pd.DataFrame):
        self.name = name
        self.rated_power_w = rated_power_w
        self.table = table.dropna(subset=["efficiency_pct"]).sort_values("power_w").reset_index(drop=True)

    def has_efficiency_curve(self) -> bool:
        return len(self.table) > 0

    def efficiency_at_power(self, elec_power_w: float) -> float:
        t = self.table
        eff_pct = np.interp(elec_power_w, t["power_w"], t["efficiency_pct"])
        return float(eff_pct) / 100.0

    def h2_mass_flow_kg_s(self, elec_power_w: float) -> float:
        """Electrical power OUT of the FC -> H2 mass consumption rate, via Art. 54e's NCV."""
        if elec_power_w <= 0:
            return 0.0
        eff = self.efficiency_at_power(elec_power_w)
        chemical_power_w = elec_power_w / eff
        return chemical_power_w / (config.H2_NCV_KJ_PER_KG * 1000.0)  # kJ/kg -> J/kg

    def h2_volume_flow_m3_s(self, elec_power_w: float) -> float:
        mass_flow_kg_s = self.h2_mass_flow_kg_s(elec_power_w)
        density_kg_m3 = config.H2_DENSITY_G_PER_L_STP  # g/L numerically equals kg/m^3
        return mass_flow_kg_s / density_kg_m3


def load_fuel_cells(path: str = FC_CSV) -> dict:
    df = pd.read_csv(path)
    result = {}
    for name, group in df.groupby("fc_name"):
        result[name] = FuelCellModel(name, group["rated_power_w"].iloc[0], group)
    return result


DCDC_CSV = "data/dcdc_candidates.csv"


class ConverterModel:
    """DC/DC buck converter between the 48V bus and a lower-voltage motor rail --
    e.g. the two-motor Urban Concept's accel motor (48V) sits directly on the bus,
    but the cruise motor (24V) needs a step-down, and that conversion has its own
    loss on top of the motor's own electrical_power_w(). See config.CRUISE_CONVERTER_NAME
    for why the candidate efficiency points are extrapolations past their datasheets'
    validated load range, not real light-load measurements."""

    def __init__(self, name: str, table: pd.DataFrame):
        self.name = name
        self.output_v = float(table["output_v"].iloc[0])
        self.rated_power_w = float(table["rated_power_w"].iloc[0])
        self.table = table.sort_values("power_w").reset_index(drop=True)

    def efficiency_at_power(self, output_power_w: float) -> float:
        eff_pct = np.interp(output_power_w, self.table["power_w"], self.table["efficiency_pct"])
        return float(eff_pct) / 100.0

    def input_power_w(self, output_power_w: float) -> float:
        """Power that must be drawn from the upstream (48V) bus to deliver
        output_power_w at this converter's output rail."""
        if output_power_w <= 0:
            return 0.0
        return output_power_w / self.efficiency_at_power(output_power_w)


def load_converters(path: str = DCDC_CSV) -> dict:
    df = pd.read_csv(path)
    return {name: ConverterModel(name, group) for name, group in df.groupby("converter_name")}


    # NOTE: a generic ideal-buffer model (capacity/charge/discharge/round-trip-eff
    # PLACEHOLDER params, see config.py's BUFFER_* constants) used to live here.
    # Removed 2026-07-25: it was never instantiated anywhere in the codebase --
    # the real hybrid FC+supercapacitor system (hybrid_energy.py, using the actual
    # Maxwell BMOD0058-E016-C02 datasheet) is what's actually simulated now. The
    # BUFFER_* config constants stay (Stratelm-GUI's vehicle spec sheet still
    # surfaces them, explicitly tagged PLACEHOLDER, as an acknowledged gap).
