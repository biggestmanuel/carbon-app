"""travel_region, and the fact that it currently changes nothing.

The form offered a "Drove somewhere else?" selector whose hint said "Only affects
driving, which burns fuel rather than grid power". It did not affect anything.
Car emissions use one global constant, `_CAR_KM`, for every region, so the travel
region is returned by factors_for() but never reaches a number.

That is pinned here on purpose. A control that silently does nothing is worse
than no control, so the frontend selector was removed. If per-region car factors
are ever added -- which is a data decision needing a source -- then this test
should start failing, and that is the moment to put the selector back and delete
the assertions that expect no difference.
"""

import pytest

from factors import factors_for, region_codes
from models import Footprint

NUMERIC_FACTORS = ("car_km", "electricity_kwh", "meat_meal", "plant_meal")


class TestTravelRegionIsInert:
    @pytest.mark.parametrize("travel", sorted(region_codes()))
    def test_no_numeric_factor_depends_on_the_travel_region(self, travel):
        home = "fr"
        same = factors_for(home, home)
        elsewhere = factors_for(home, travel)

        assert elsewhere["travel_region"] == travel
        for key in NUMERIC_FACTORS:
            assert elsewhere[key] == same[key], (
                f"{key} now varies by travel region; the frontend selector and the "
                "no-difference assertions in this file need revisiting"
            )

    def test_car_factor_is_one_global_constant(self):
        assert len({factors_for(region, region)["car_km"] for region in region_codes()}) == 1

    def test_only_electricity_varies_by_home_region(self):
        by_region = {region: factors_for(region, region) for region in region_codes()}
        assert len({f["electricity_kwh"] for f in by_region.values()}) > 1
        assert len({f["car_km"] for f in by_region.values()}) == 1
        assert len({f["meat_meal"] for f in by_region.values()}) == 1
        assert len({f["plant_meal"] for f in by_region.values()}) == 1

    def test_the_total_is_identical_whatever_the_travel_region(self, client, auth_headers):
        auth_headers()
        totals = []
        for travel in ("fr", "in", "us", "gb"):
            res = client.post("/footprint/calculate", json={
                "region": "fr",
                "travel_region": travel,
                "car_km": 250,
                "electricity_kwh": 180,
                "meat_meals": 5,
                "plant_meals": 9,
            })
            assert res.status_code == 201
            totals.append(res.json["total"])
        assert len(set(totals)) == 1, f"travel_region now changes the total: {totals}"


class TestStillAccepted:
    """The parameter stays in the API contract, it just does not bite yet."""

    def test_the_backend_still_accepts_and_echoes_it(self, client, auth_headers):
        auth_headers()
        res = client.post("/footprint/calculate", json={
            "region": "fr", "travel_region": "in",
            "car_km": 10, "electricity_kwh": 20, "meat_meals": 1, "plant_meals": 2,
        })
        assert res.status_code == 201
        assert res.json["travel_region"] == "in"
        assert res.json["region"] == "fr"

    def test_an_invalid_travel_region_is_still_rejected(self, client, auth_headers):
        auth_headers()
        res = client.post("/footprint/calculate", json={
            "region": "fr", "travel_region": "atlantis",
            "car_km": 10, "electricity_kwh": 20, "meat_meals": 1, "plant_meals": 2,
        })
        assert res.status_code == 400
        assert "travel_region" in res.json["errors"]

    def test_it_is_not_stored_on_the_row(self, client, auth_headers, app):
        # There is no column for it, so history and export cannot show it. If a
        # travel_region column is ever added, Footprint.to_dict needs it too.
        auth_headers()
        client.post("/footprint/calculate", json={
            "region": "fr", "travel_region": "in",
            "car_km": 10, "electricity_kwh": 20, "meat_meals": 1, "plant_meals": 2,
        })
        with app.app_context():
            assert "travel_region" not in Footprint.__table__.columns
            assert "travel_region" not in Footprint.query.one().to_dict()
