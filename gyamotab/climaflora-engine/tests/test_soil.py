from app.domain.models import Confidence
from app.services.soil import PROPERTY_SPECS, SoilGridsWcsProvider, UnavailableSoilProvider, texture_label


def test_v16_soilgrids_units_include_soc_and_nitrogen() -> None:
    assert PROPERTY_SPECS["soc_g_kg"]["layer"] == "soc"
    assert PROPERTY_SPECS["soc_g_kg"]["factor"] == 10.0
    assert PROPERTY_SPECS["nitrogen_g_kg"]["layer"] == "nitrogen"
    assert PROPERTY_SPECS["nitrogen_g_kg"]["factor"] == 100.0


def test_manual_values_validate_extended_soil_properties() -> None:
    values = SoilGridsWcsProvider._manual_values(
        {
            "ph": 6.7,
            "soc_g_kg": 24.5,
            "nitrogen_g_kg": 1.8,
            "clay_pct": 32,
            "drainage": "well_drained",
        }
    )
    assert values["ph"] == 6.7
    assert values["soc_g_kg"] == 24.5
    assert values["nitrogen_g_kg"] == 1.8
    assert values["drainage"] == "well_drained"

    invalid = SoilGridsWcsProvider._manual_values(
        {"ph": 0, "soc_g_kg": 5000, "nitrogen_g_kg": 500}
    )
    assert "ph" not in invalid
    assert "soc_g_kg" not in invalid
    assert "nitrogen_g_kg" not in invalid


def test_unavailable_provider_preserves_manual_extended_properties() -> None:
    profile = UnavailableSoilProvider().profile(
        47.16,
        -1.27,
        {"ph": 6.5, "soc_g_kg": 20.0, "nitrogen_g_kg": 1.5},
    )
    assert profile.provider == "USER"
    assert profile.confidence == Confidence.B
    assert profile.properties["soc_g_kg"] == 20.0
    assert profile.properties["nitrogen_g_kg"] == 1.5


def test_texture_label_remains_descriptive() -> None:
    assert texture_label({"clay_pct": 45, "sand_pct": 30, "silt_pct": 25}) == "argileux"
    assert texture_label({"clay_pct": 10, "sand_pct": 75, "silt_pct": 15}) == "sableux"
