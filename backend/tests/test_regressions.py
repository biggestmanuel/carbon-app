"""Regression tests. Each test named test_regression_* corresponds to a bug
that was reproduced against the original code and confirmed before fixing."""
import math

from flask import current_app

from models import Footprint, User
from factors import factors_for


# --- Bug: float("nan") / float("inf") were accepted and produced a NaN or
# --- Infinity total, which is not even valid JSON. -------------------------
def test_regression_nan_is_rejected(client, auth_headers, valid_payload):
    auth_headers()
    valid_payload["car_km"] = float("nan")
    res = client.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 400
    assert "car_km" in res.json["errors"]


def test_regression_infinity_is_rejected(client, auth_headers, valid_payload):
    auth_headers()
    valid_payload["electricity_kwh"] = float("inf")
    res = client.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 400
    assert "electricity_kwh" in res.json["errors"]


def test_regression_nan_string_is_rejected(client, auth_headers, valid_payload):
    auth_headers()
    valid_payload["car_km"] = "NaN"
    res = client.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 400


# --- Bug: negative inputs produced negative emissions (-1450 kg CO2). ------
def test_regression_negative_inputs_rejected(client, auth_headers, valid_payload):
    auth_headers()
    valid_payload.update({"car_km": -5000, "meat_meals": -50})
    res = client.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 400
    assert len(res.json["errors"]) == 2


def test_regression_huge_inputs_rejected(client, auth_headers, valid_payload):
    auth_headers()
    valid_payload["car_km"] = 10**12
    res = client.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 400


# --- Bug: rows were written but there was no way to read them back. -------
def test_regression_history_returns_saved_entries(client, auth_headers, valid_payload):
    auth_headers()
    client.post("/footprint/calculate", json=valid_payload)
    body = client.get("/footprint/history").json
    assert body["total_entries"] == 1
    assert body["entries"][0]["car_km"] == 100


def test_regression_history_is_scoped_per_user(client, valid_payload):
    client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
    client.post("/footprint/calculate", json=valid_payload)

    # A second user must never see the first user's entries.
    client.post("/auth/register", json={"username": "bob", "password": "another-password"})
    client.post("/auth/login", json={"username": "bob", "password": "another-password"})
    assert client.get("/footprint/history").json["total_entries"] == 0

    client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
    assert client.get("/footprint/history").json["total_entries"] == 1


def test_regression_summary_aggregates(client, auth_headers, valid_payload):
    auth_headers()
    client.post("/footprint/calculate", json=valid_payload)
    client.post("/footprint/calculate", json=valid_payload)

    body = client.get("/footprint/summary").json
    assert body["entries"] == 2
    # world electricity factor is 0.475; see factors.py
    expected = 100 * 0.21 + 200 * 0.475 + 3 * 5.0 + 5 * 2.0
    assert math.isclose(body["total"], expected * 2, rel_tol=1e-6)


# --- Bug: a single-character password was accepted. ------------------------
def test_regression_short_password_rejected(client):
    res = client.post("/auth/register", json={"username": "bob", "password": "x"})
    assert res.status_code == 400
    assert "password" in res.json["msg"]


def test_regression_oversized_password_rejected(client):
    res = client.post("/auth/register", json={"username": "bob", "password": "a" * 500})
    assert res.status_code == 400


def test_regression_username_charset_enforced(client):
    res = client.post("/auth/register", json={"username": "bad name!", "password": "correct-horse"})
    assert res.status_code == 400


def test_regression_username_is_trimmed(client):
    res = client.post("/auth/register", json={"username": "  carol  ", "password": "correct-horse"})
    assert res.status_code == 201
    with current_app.app_context():
        assert User.query.filter_by(username="carol").one()


# --- Bug: float meal values were truncated by the Integer column on strict  ---
# --- databases, so `total` no longer matched the stored inputs. -------------
def test_regression_fractional_meals_rejected(client, auth_headers, valid_payload):
    auth_headers()
    valid_payload["meat_meals"] = 2.7
    res = client.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 400
    assert "whole number" in res.json["errors"]["meat_meals"]


def test_regression_stored_total_matches_stored_inputs(client, auth_headers, valid_payload):
    auth_headers()
    client.post("/footprint/calculate", json=valid_payload)
    with current_app.app_context():
        row = Footprint.query.one()
        factors = factors_for(row.region)
        expected = (row.car_km * factors["car_km"]
                    + row.electricity_kwh * factors["electricity_kwh"]
                    + row.meat_meals * factors["meat_meal"]
                    + row.plant_meals * factors["plant_meal"])
        assert math.isclose(row.total, expected, rel_tol=1e-6)


# --- Bug: the access token was returned in the JSON body and the frontend   ---
# --- kept it in localStorage, so any XSS could read it. --------------------
def test_regression_token_never_in_response_body(client):
    client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    res = client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
    assert res.status_code == 200
    assert "access_token" not in res.json
    assert "eyJ" not in res.get_data(as_text=True)  # no raw JWT anywhere in the body


# --- Bug: create_all() cannot alter a table, so a schema change silently    ---
# --- left populated databases broken. Covered end-to-end by test_migrations.py.