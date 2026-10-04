"""travel_region, and the fact that it now changes the car factor.

This file used to assert the opposite. The form offered a "Drove somewhere else?"
selector whose hint said "Only affects driving", and it affected nothing, because
car emissions were a single global constant for every region. The control was
removed rather than left doing nothing.

Car factors are now region-keyed, with provenance, so driving abroad is scored
against where the driving happened. Only the United States has a measured
fleet-average figure of its own; every other region stands in for the documented
global default. The tests below therefore separate the two cases:

- a region with its own figure must change the total;
- a region on the default must match the same region driven at home, which is
  honest rather than a bug, and `car_km_is_default` reports it.
"""

import pytest

from factors import (
    car_factor,
    car_factor_is_default,
    factors_for,
    region_codes,
    regions_with_measured_car_factor,
)
from models import Footprint

MEASURED = regions_with_measured_car_factor()
ON_DEFAULT = [r for r in region_codes() if car_factor_is_default(r)]


class TestTravelRegionChangesTheCarFactor:
    @pytest.mark.parametrize("travel", MEASURED)
    def test_a_measured_region_changes_the_total(self, client, auth_headers, travel):
        auth_headers()
        # Car km only, so electricity and diet cannot move the total.
        payload = {
            "region": "fr",
            "car_km": 250,
            "electricity_kwh": 0,
            "meat_meals": 0,
            "plant_meals": 0,
        }

        at_home = client.post("/footprint/calculate", json=payload)
        assert at_home.status_code == 201

        abroad = client.post(
            "/footprint/calculate", json={**payload, "travel_region": travel}
        )
        assert abroad.status_code == 201

        assert at_home.json["total"] != abroad.json["total"], (
            f"driving in {travel} is scored exactly like driving at home"
        )
        assert abroad.json["travel_region"] == travel
        assert abroad.json["region"] == "fr"

    def test_electricity_still_follows_the_home_region(self):
        assert (factors_for("fr", "us")["electricity_kwh"]
                == factors_for("fr", "fr")["electricity_kwh"])

    def test_the_car_factor_is_the_travel_region_s_own(self):
        assert factors_for("fr", "us")["car_km"] == car_factor("us")[0]
        assert factors_for("fr", "fr")["car_km"] == car_factor("fr")[0]

    def test_the_factor_is_echoed_with_its_provenance_flag(self):
        assert factors_for("fr", "us")["car_km_is_default"] is False
        assert factors_for("fr", "fr")["car_km_is_default"] is True


class TestDefaultedRegionsMatchHome:
    """Honest, not a bug: a region with no measured figure is the global one."""

    @pytest.mark.parametrize("travel", ON_DEFAULT)
    def test_an_unmeasured_region_scores_the_same_as_home(self, travel):
        assert (factors_for("fr", travel)["car_km"]
                == factors_for("fr", "fr")["car_km"])

    @pytest.mark.parametrize("travel", ON_DEFAULT)
    def test_and_says_that_is_what_happened(self, travel):
        assert factors_for("fr", travel)["car_km_is_default"] is True

    def test_at_least_one_region_has_a_real_figure(self):
        # Otherwise the whole mechanism is inert again and this file is a lie.
        assert MEASURED, "no region has a measured car factor"


class TestStillInert:
    """The part that has not changed, and should not pretend otherwise."""

    def test_diet_factors_do_not_vary_by_travel_region(self):
        for key in ("meat_meal", "plant_meal"):
            assert (factors_for("fr", "us")[key] == factors_for("fr", "fr")[key])

    def test_diet_factors_are_global_medians_by_nature(self):
        # Poore & Nemecek is a global dataset. Inventing per-country diet factors
        # would mean fabricating numbers, so this stays shared on purpose.
        values = {factors_for(region)[key]
                  for region in region_codes()
                  for key in ("meat_meal", "plant_meal")}
        assert len(values) == 2, "meat and plant differ, but nothing else should"

    def test_it_is_not_stored_on_the_row(self, client, auth_headers, app):
        # The factor snapshot records the numbers used, which is what history
        # needs. The region *codes* are not kept, so history and export cannot
        # say where the driving happened. Adding them is a migration.
        auth_headers()
        client.post("/footprint/calculate", json={
            "region": "fr", "travel_region": "us",
            "car_km": 10, "electricity_kwh": 20, "meat_meals": 1, "plant_meals": 2,
        })
        with app.app_context():
            assert "travel_region" not in Footprint.__table__.columns
            row = Footprint.query.one()
            assert "travel_region" not in row.to_dict()
            # But the factors it was scored with are recorded, including whether
            # the car figure was the global stand-in.
            assert row.factors_applied["car_km"] == car_factor("us")[0]
            assert row.factors_applied["car_km_is_default"] is False


class TestParameterStillAccepted:
    def test_it_is_still_validated(self, client, auth_headers):
        auth_headers()
        res = client.post("/footprint/calculate", json={
            "region": "fr", "travel_region": "atlantis",
            "car_km": 10, "electricity_kwh": 20, "meat_meals": 1, "plant_meals": 2,
        })
        assert res.status_code == 400
        assert "travel_region" in res.json["errors"]

    def test_blank_means_same_as_home(self, client, auth_headers):
        auth_headers()
        res = client.post("/footprint/calculate", json={
            "region": "fr", "travel_region": "",
            "car_km": 10, "electricity_kwh": 0, "meat_meals": 0, "plant_meals": 0,
        })
        assert res.status_code == 201
        assert res.json["travel_region"] == "fr"
