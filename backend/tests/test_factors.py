"""Emission factor data integrity."""
import pytest

from factors import (
    DEFAULT_REGION,
    FACTORS_VERSION,
    REGION_LABELS,
    catalogue,
    factors_for,
    is_valid_region,
    region_codes,
)


def test_every_region_has_a_label_and_factor():
    for code in region_codes():
        assert code in REGION_LABELS, f"{code} has no display label"
        assert REGION_LABELS[code], f"{code} has an empty label"


def test_default_region_is_valid():
    assert is_valid_region(DEFAULT_REGION)


def test_unknown_region_falls_back_to_default():
    factors = factors_for("atlantis")
    assert factors["region"] == DEFAULT_REGION


def test_none_region_falls_back_to_default():
    assert factors_for(None)["region"] == DEFAULT_REGION


def test_electricity_factors_are_plausible_grid_intensities():
    """g CO2e/kWh for real grids sits roughly between 20 and 800."""
    for code in region_codes():
        grid = factors_for(code)["electricity_kwh"] * 1000
        assert 20 <= grid <= 800, f"{code} grid factor {grid} is implausible"


def test_known_grid_ordering():
    """France's nuclear-heavy grid must beat India's coal-heavy one."""
    assert factors_for("fr")["electricity_kwh"] < factors_for("in")["electricity_kwh"]
    assert factors_for("br")["electricity_kwh"] < factors_for("in")["electricity_kwh"]


def test_diet_factors_are_region_independent():
    """Poore & Nemecek medians are global; they must not drift per region."""
    for code in region_codes():
        assert factors_for(code)["meat_meal"] == 5.0
        assert factors_for(code)["plant_meal"] == 2.0


def test_all_factors_are_positive():
    for code in region_codes():
        factors = factors_for(code)
        for key in ("car_km", "electricity_kwh", "meat_meal", "plant_meal"):
            assert factors[key] > 0, f"{code}.{key} must be positive"


def test_factors_carry_a_version():
    for code in region_codes():
        assert factors_for(code)["factors_version"] == FACTORS_VERSION


def test_catalogue_matches_the_factor_data():
    cat = catalogue()
    assert cat["default_region"] == DEFAULT_REGION
    assert cat["factors_version"] == FACTORS_VERSION
    assert {r["code"] for r in cat["regions"]} == set(region_codes())
    for entry in cat["regions"]:
        assert entry["electricity_kwh"] == factors_for(entry["code"])["electricity_kwh"]


def test_catalogue_is_label_first():
    cat = catalogue()
    assert cat["regions"] == sorted(cat["regions"], key=lambda r: REGION_LABELS[r["code"]])


@pytest.mark.parametrize("bad", ["", "atlantis", "WORLD", None, 123, ["fr"]])
def test_is_valid_region_rejects_junk(bad):
    assert is_valid_region(bad) is False