"""Regression tests. Each test named test_regression_* corresponds to a bug
that was reproduced against the original code and confirmed before fixing."""
import math

from flask import current_app

from factors import DEFAULT_REGION, factors_for
from models import Footprint, User


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
    # Read from the factor table rather than hardcoded, so a factor update does
    # not read as a regression.
    factors = factors_for(DEFAULT_REGION)
    expected = (
        valid_payload["car_km"] * factors["car_km"]
        + valid_payload["electricity_kwh"] * factors["electricity_kwh"]
        + valid_payload["meat_meals"] * factors["meat_meal"]
        + valid_payload["plant_meals"] * factors["plant_meal"]
    )
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


# --- Bug: `sessions` was declared twice on User. The second declaration won,  ---
# --- and it had passive_deletes=True, the setting that leaves rows behind on  ---
# --- SQLite because ON DELETE CASCADE is ignored unless foreign_keys is on.  ---
# --- The endpoint's own test still passed, because delete_account() deletes   ---
# --- sessions with an explicit bulk query first. These tests delete through   ---
# --- the ORM alone, which is what any future caller would do.                ---
def test_regression_no_relationship_is_declared_twice(app):
    """A duplicate declaration cannot be seen on the mapper.

    SQLAlchemy collapses a repeated `sessions = db.relationship(...)` into a
    single mapper entry, keeping the last one, so `len(relationships)` is the
    same either way. The only way to catch it is to read the assignment targets
    out of the source.
    """
    import ast
    import pathlib

    import models as models_module

    tree = ast.parse(pathlib.Path(models_module.__file__).read_text(encoding="utf-8"))

    seen: dict[tuple[str, str], int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            # `name = db.relationship(...)`
            call = stmt.value
            if not (
                isinstance(call, ast.Call)
                and getattr(call.func, "attr", None) == "relationship"
            ):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    key = (node.name, target.id)
                    seen[key] = seen.get(key, 0) + 1

    duplicates = {f"{cls}.{name}": count for (cls, name), count in seen.items() if count > 1}
    assert not duplicates, (
        f"relationship(s) declared more than once on the same class: {duplicates}. "
        "The last declaration silently wins."
    )

    with app.app_context():
        assert ("User", "footprints") in seen
        assert ("User", "sessions") in seen


def test_regression_both_relationships_delete_their_children(app):
    from sqlalchemy import inspect

    with app.app_context():
        for name in ("footprints", "sessions"):
            rel = inspect(User).relationships[name]
            assert rel.passive_deletes is False, (
                f"{name} has passive_deletes={rel.passive_deletes}; SQLite ignores "
                "ON DELETE CASCADE unless PRAGMA foreign_keys is on, so children "
                "would be orphaned"
            )


def test_regression_deleting_a_user_orphans_no_sessions(app):
    from extensions import db
    from models import UserSession
    from passwords import hash_password

    with app.app_context():
        user = User(username="alice", password_hash=hash_password("correct-horse"))
        db.session.add(user)
        db.session.flush()
        user.start_session(user_agent="laptop", ip_address="127.0.0.1")
        user.start_session(user_agent="phone", ip_address="127.0.0.1")
        db.session.add(
            Footprint(
                user_id=user.id,
                car_km=10,
                electricity_kwh=20,
                meat_meals=1,
                plant_meals=1,
                total=30.0,
                region="world",
                factors_version=2,
            )
        )
        db.session.commit()
        user_id = user.id

        assert UserSession.query.filter_by(user_id=user_id).count() == 2

        # No explicit child cleanup: rely on the relationship alone.
        db.session.delete(user)
        db.session.commit()

        assert User.query.filter_by(id=user_id).count() == 0
        assert UserSession.query.filter_by(user_id=user_id).count() == 0, (
            "user_session rows outlived the user"
        )
        assert Footprint.query.filter_by(user_id=user_id).count() == 0, (
            "footprint rows outlived the user"
        )


def test_regression_deleting_a_user_leaves_other_users_rows(app):
    from extensions import db
    from models import UserSession
    from passwords import hash_password

    with app.app_context():
        alice = User(username="alice", password_hash=hash_password("correct-horse"))
        bob = User(username="bob", password_hash=hash_password("another-password"))
        db.session.add_all([alice, bob])
        db.session.flush()
        alice.start_session(user_agent="alice-laptop", ip_address="127.0.0.1")
        bob.start_session(user_agent="bob-laptop", ip_address="127.0.0.2")
        db.session.commit()
        bob_id = bob.id

        db.session.delete(alice)
        db.session.commit()

        # The cascade must not reach past the deleted user.
        assert UserSession.query.filter_by(user_id=bob_id).count() == 1

