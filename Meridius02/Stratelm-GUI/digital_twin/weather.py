"""
Air density and wind-relative airspeed model for the Lusail attempt (2027-01-10).

Two things affect drag force with weather -- air density (rho) and the
vehicle's airspeed relative to the moving air -- NOT the drag coefficient.
CdA is a fixed shape property of the body (see config.AERO_CDA_CFD) and does
not change with conditions on the day.

The attempt date is ~1.5 years out, so no real forecast exists yet. Values
below are January climate normals for Doha/Lusail, Qatar (sources in
C:\\Users\\Terano\\.claude\\plans\\hey-u-can-read-fizzy-pizza.md), packaged as
three named scenarios so the strategy optimizer can be checked for
robustness across them instead of tuned against one guessed number.
"""

import math
from dataclasses import dataclass

R_D = 287.05    # J/(kg*K), specific gas constant, dry air
R_V = 461.495   # J/(kg*K), specific gas constant, water vapor


@dataclass(frozen=True)
class WeatherScenario:
    name: str
    temperature_c: float            # air temperature
    relative_humidity: float        # 0-1
    pressure_hpa: float             # station/sea-level pressure
    wind_speed_kmh: float           # sustained wind speed
    wind_from_bearing_deg: float    # meteorological convention: direction wind blows FROM, clockwise from North
    confidence: str                 # which sub-values are measured vs guessed
    source: str


def saturation_vapor_pressure_hpa(temperature_c: float) -> float:
    """Buck equation for saturation vapor pressure, valid -40..50 C. Returns hPa."""
    return 6.1121 * math.exp((18.678 - temperature_c / 234.5) * (temperature_c / (257.14 + temperature_c)))


def air_density(scenario: WeatherScenario) -> float:
    """Moist-air density in kg/m^3 via ideal gas law (dry-air + water-vapor partial pressures)."""
    t_k = scenario.temperature_c + 273.15
    p_sat = saturation_vapor_pressure_hpa(scenario.temperature_c)
    p_vapor_hpa = scenario.relative_humidity * p_sat
    p_dry_hpa = scenario.pressure_hpa - p_vapor_hpa
    return (p_dry_hpa * 100) / (R_D * t_k) + (p_vapor_hpa * 100) / (R_V * t_k)


def headwind_component_kmh(scenario: WeatherScenario, track_heading_deg: float) -> float:
    """
    Positive = headwind (adds to drag), negative = tailwind (reduces drag),
    along the vehicle's direction of travel only.

    Only the fore-aft component is used: Cd=0.1 is a single frontal value with
    no yaw-dependence data, so crosswind's effect on drag magnitude is not
    modeled here, only the along-heading component.
    """
    wind_travel_bearing = (scenario.wind_from_bearing_deg + 180.0) % 360.0
    angle_diff = math.radians(wind_travel_bearing - track_heading_deg)
    # wind's own travel vector projected onto vehicle heading; a wind moving
    # the same way as the vehicle is a TAILWIND, so negate for headwind sign
    return -scenario.wind_speed_kmh * math.cos(angle_diff)


def relative_airspeed_kmh(vehicle_speed_kmh: float, scenario: WeatherScenario, track_heading_deg: float) -> float:
    """Effective airspeed the drag force should use (vehicle ground speed + headwind component)."""
    return vehicle_speed_kmh + headwind_component_kmh(scenario, track_heading_deg)


# --- Named scenarios -----------------------------------------------------
# Sourced from January climate normals for Doha / Lusail, Qatar (nearest
# stations with public records; Lusail itself has no long-running station).
# Wind: prevailing winter "Shamal" is NW/NNW, mean bearing ~351 deg; 78.8% of
# observations fall in the 5-15 knot band (~9-28 km/h), with Dec-Mar the
# highest wind-power months of the year in this region.

WEATHER_CALM = WeatherScenario(
    name="calm",
    temperature_c=17.5,
    relative_humidity=0.65,
    pressure_hpa=1015.0,
    wind_speed_kmh=9.0,      # ~5 kt, low end of the observed 5-15 kt band
    wind_from_bearing_deg=351.0,
    confidence=(
        "wind speed: MEASURED (low end of published range) | "
        "temp/humidity: MEASURED climate normal | "
        "pressure: PLACEHOLDER (low confidence, no Jan-specific normal found)"
    ),
    source="weather-and-climate.com Lusail/Doha Jan normals; Qatar wind-rose study (ResearchGate)",
)

WEATHER_TYPICAL_JAN = WeatherScenario(
    name="typical_january",
    temperature_c=17.7,
    relative_humidity=0.65,
    pressure_hpa=1015.0,
    wind_speed_kmh=17.0,     # Doha Jan average (~9 kt)
    wind_from_bearing_deg=351.0,
    confidence=(
        "wind speed/direction: MEASURED (published average + wind-rose) | "
        "temp/humidity: MEASURED climate normal | "
        "pressure: PLACEHOLDER (low confidence)"
    ),
    source="weather-and-climate.com; Windfinder Doha station statistics",
)

WEATHER_SHAMAL_STRONG = WeatherScenario(
    name="shamal_strong",
    temperature_c=14.0,      # Shamal advects cooler, drier continental air behind the front
    relative_humidity=0.50,
    pressure_hpa=1018.0,     # Shamal onset typically follows a high-pressure push
    wind_speed_kmh=28.0,     # upper end of the 5-15 kt band (~15 kt)
    wind_from_bearing_deg=351.0,
    confidence=(
        "wind speed: MEASURED (upper end of published band) | "
        "temp/humidity/pressure shift: PLACEHOLDER (meteorologically reasonable, "
        "not station-verified for Shamal days specifically)"
    ),
    source="MDPI Qatar wind-energy-potential study (winter Shamal dominance, Dec-Mar peak wind power)",
)

SCENARIOS = {
    "calm": WEATHER_CALM,
    "typical_january": WEATHER_TYPICAL_JAN,
    "shamal_strong": WEATHER_SHAMAL_STRONG,
}
