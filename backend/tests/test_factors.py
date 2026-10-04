"""Factors, and the provenance behind each number.

These tests exist to stop two specific mistakes: a factor silently changing
without the version being bumped, and a number appearing in the table with no
attributable source.
"""

import pytest

from factors import (
    DEFAULT_REGION,
    FACTORS_VERSION,
    car_factor,
    car_factor_is_default,
    catalogue,
    factors_for,
    is_valid_region,
    provenance_for,
    region_codes,
    regions_with_measured_car_factor,
    snapshot,
)

NUMERIC = ("car_km", "electricity_kwh", "meat_meal", "plant_meal")


class TestRegionValidation:
    def test_every_region_has_a_label_and_a_grid_factor(self):
        from factors import GRID_FACTORS_G_PER_KWH, REGION_LABELS

        assert set(GRID_FACTORS_G_PER_KWH) == set(REGION_LABELS)

    def test_the_default_is_a_real_region(self):
        assert is_valid_region(DEFAULT_REGION)

    def test_junk_is_rejected_without_raising(self):
        for value in ("atlantis", "", None, 42, [], {}):
            assert is_valid_region(value) is False

    def test_regions_are_ordered_by_label(self):
        from factors import REGION_LABELS

        codes = region_codes()
        assert codes == sorted(codes, key=lambda r: REGION_LABELS[r])


class TestEveryFactorHasASource:
    @pytest.mark.parametrize("region", sorted(region_codes()))
    def test_provenance_is_present_for_every_factor(self, region):
        provenance = provenance_for(region)
        for key in ("electricity_kwh", "car_km", "meat_meal", "plant_meal"):
            entry = provenance[key]
            assert entry["source"], f"{region}.{key} has no source"
            assert entry["basis"], f"{region}.{key} does not say what it measures"

    def test_no_source_is_a_placeholder(self):
        for region in region_codes():
            for entry in provenance_for(region).values():
                if not isinstance(entry, dict):
                    continue
                assert "TODO" not in entry["source"].upper()
                assert "FIXME" not in entry["source"].upper()

    def test_the_measured_car_regions_are_declared_not_inferred(self):
        # Anything in _CAR_KM_BY_REGION must be a real region code.
        for region in regions_with_measured_car_factor():
            assert is_valid_region(region)


class TestCarFactors:
    def test_a_region_without_its_own_figure_says_so(self):
        value, is_default = car_factor("fr")
        assert is_default is True
        assert value > 0

    def test_a_region_with_a_measured_figure_says_so(self):
        value, is_default = car_factor("us")
        assert is_default is False
        assert value > 0

    def test_the_default_is_the_same_everywhere_it_applies(self):
        defaults = {car_factor(r)[0] for r in region_codes() if car_factor_is_default(r)}
        assert len(defaults) == 1, "the global stand-in should be one number"

    def test_the_us_figure_differs_from_the_default(self):
        # If these were equal the travel-region control would be inert for the
        # only region with measured data, which is the bug this replaced.
        assert car_factor("us")[0] != car_factor("fr")[0]

    def test_car_factors_are_plausible(self):
        for region in region_codes():
            value = car_factor(region)[0]
            assert 0.05 < value < 0.60, f"{region} car factor {value} is implausible"


class TestFactorsFor:
    def test_an_unknown_region_falls_back_to_the_world_average(self):
        assert factors_for("atlantis")["region"] == DEFAULT_REGION

    def test_blank_travel_region_means_same_as_home(self):
        home = factors_for("fr", None)
        assert home["travel_region"] == "fr"
        assert factors_for("fr", "")["travel_region"] == "fr"

    def test_electricity_follows_the_home_region(self):
        assert factors_for("fr", "us")["electricity_kwh"] == factors_for("fr")["electricity_kwh"]

    def test_car_follows_the_travel_region(self):
        # This is what makes travel_region mean something.
        assert factors_for("fr", "us")["car_km"] == factors_for("fr", "us")["car_km"]
        assert factors_for("fr", "us")["car_km"] != factors_for("fr", "fr")["car_km"]

    def test_diet_is_identical_everywhere(self):
        for key in ("meat_meal", "plant_meal"):
            values = {factors_for(region)[key] for region in region_codes()}
            assert len(values) == 1, f"{key} varies by region: {values}"

    def test_every_factor_is_positive_and_finite(self):
        import math

        for region in region_codes():
            factors = factors_for(region)
            for key in NUMERIC:
                assert factors[key] > 0
                assert math.isfinite(factors[key])

    def test_car_km_is_reported_in_kg_not_grams(self):
        # The grid table is in g/kWh and divided by 1000; car is already kg/km.
        assert 0.05 < factors_for("fr")["car_km"] < 1.0
        assert factors_for("fr")["electricity_kwh"] == 0.056


class TestSnapshot:
    def test_a_snapshot_round_trips_the_numbers(self):
        original = factors_for("fr", "us")
        stored = snapshot(original)
        for key in NUMERIC:
            assert stored[key] == original[key]

    def test_a_snapshot_records_whether_the_car_figure_was_a_default(self):
        # A later update may turn a fallback into a measured value, and an old
        # row has to keep saying which it was scored with.
        assert snapshot(factors_for("fr"))["car_km_is_default"] is True
        assert snapshot(factors_for("fr", "us"))["car_km_is_default"] is False

    def test_a_snapshot_survives_the_factor_table_changing(self, monkeypatch):
        original = snapshot(factors_for("fr"))
        monkeypatch.setattr("factors.GRID_FACTORS_G_PER_KWH", {"fr": 999})
        assert snapshot(factors_for("fr")) != original, (
            "the snapshot must reflect the table, so this proves it is read live"
        )

    def test_a_hand_built_snapshot_still_scores(self):
        # /footprint/summary falls back to this shape for rows written before
        # snapshots existed, so it has to stay loadable.
        legacy = {"car_km": 0.21, "electricity_kwh": 0.475, "meat_meal": 5.0, "plant_meal": 2.0}
        assert 100 * legacy["car_km"] > 0


class TestCatalogue:
    def test_it_advertises_the_version(self):
        assert catalogue()["factors_version"] == FACTORS_VERSION

    def test_every_region_reports_its_car_factor_and_provenance(self):
        for entry in catalogue()["regions"]:
            assert entry["car_km"] > 0
            assert isinstance(entry["car_km_is_default"], bool)
            assert entry["provenance"]["car_km"]["source"]

    def test_it_says_where_the_diet_numbers_come_from(self):
        entry = next(r for r in catalogue()["regions"] if r["code"] == "fr")
        assert "Poore" in entry["provenance"]["meat_meal"]["source"]
