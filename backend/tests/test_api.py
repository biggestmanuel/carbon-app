import math

from flask import current_app


# --- Registration ---------------------------------------------------------
def test_register_returns_201(client):
    res = client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    assert res.status_code == 201


def test_register_never_returns_the_hash(client):
    res = client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    # Method-agnostic on purpose: this used to assert "pbkdf2" was absent, which
    # silently stopped meaning anything once the hash switched to scrypt. Any
    # hash prefix, or the column name, means a leak.
    for marker in ("pbkdf2", "scrypt", "password_hash", "argon2", "hashlib"):
        assert marker not in res.text, f"{marker!r} appeared in the register response"


def test_duplicate_username_returns_409(client):
    client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    res = client.post("/auth/register", json={"username": "alice", "password": "other-password"})
    assert res.status_code == 409


def test_register_requires_both_fields(client):
    assert client.post("/auth/register", json={"username": "alice"}).status_code == 400
    assert client.post("/auth/register", json={"password": "correct-horse"}).status_code == 400


def test_register_rejects_non_json_body(client):
    res = client.post("/auth/register", data="not json", content_type="application/json")
    assert res.status_code == 400


# --- Login ----------------------------------------------------------------
def test_login_sets_httponly_cookies(client):
    client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    res = client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
    assert res.status_code == 200
    assert res.json["username"] == "alice"

    cookies = res.headers.getlist("Set-Cookie")
    assert cookies, "login must set cookies"
    access = next(c for c in cookies if c.startswith("access_token_cookie"))
    assert "HttpOnly" in access, "access cookie must be httpOnly"
    assert "SameSite" in access


def test_login_sets_a_refresh_cookie(client):
    client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    res = client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
    cookies = res.headers.getlist("Set-Cookie")
    assert any(c.startswith("refresh_token_cookie") for c in cookies)


def test_login_with_wrong_password_is_401(client):
    client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    res = client.post("/auth/login", json={"username": "alice", "password": "wrong-password"})
    assert res.status_code == 401
    assert res.json["msg"] == "Bad credentials"


def test_login_unknown_user_is_401(client):
    res = client.post("/auth/login", json={"username": "nobody", "password": "correct-horse"})
    assert res.status_code == 401


# --- Session lifecycle ----------------------------------------------------
def test_me_returns_the_authenticated_user(logged_in):
    res = logged_in.get("/auth/me")
    assert res.status_code == 200
    assert res.json["username"] == "alice"


def test_me_requires_a_session(client):
    assert client.get("/auth/me").status_code == 401


def test_refresh_issues_a_new_access_cookie(logged_in):
    res = logged_in.post("/auth/refresh")
    assert res.status_code == 200
    assert any(c.startswith("access_token_cookie")
               for c in res.headers.getlist("Set-Cookie"))


def test_refresh_requires_a_refresh_cookie(client):
    # Logged out entirely: no cookie, so no refresh.
    assert client.post("/auth/refresh").status_code == 401


def test_logout_clears_the_cookies(client):
    client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
    assert client.get("/auth/me").status_code == 200

    res = client.post("/auth/logout")
    assert res.status_code == 200
    cleared = res.headers.getlist("Set-Cookie")
    assert any('access_token_cookie=""' in c or "access_token_cookie=;" in c for c in cleared)

    # Session is gone.
    assert client.get("/auth/me").status_code == 401


def test_logout_is_idempotent(client):
    assert client.post("/auth/logout").status_code == 200
    assert client.post("/auth/logout").status_code == 200


# --- CORS -----------------------------------------------------------------
def test_cors_allows_credentials_on_allowed_origin(client):
    client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
    res = client.post("/auth/login", json={"username": "alice", "password": "correct-horse"},
                      headers={"Origin": "http://localhost:5173"})
    assert res.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
    assert res.headers.get("Access-Control-Allow-Credentials") == "true"


def test_cors_does_not_allow_unknown_origin(client):
    res = client.post("/auth/login", json={"username": "x", "password": "correct-horse"},
                      headers={"Origin": "http://evil.example"})
    assert res.headers.get("Access-Control-Allow-Origin") != "http://evil.example"


# --- Authorisation --------------------------------------------------------
def test_calculate_requires_auth(client, valid_payload):
    assert client.post("/footprint/calculate", json=valid_payload).status_code == 401


# --- Calculation ----------------------------------------------------------
def test_calculate_total_and_breakdown(logged_in, valid_payload):
    res = logged_in.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 201
    factors = 0.21 * 100 + 0.475 * 200 + 5.0 * 3 + 2.0 * 5
    assert math.isclose(res.json["total"], factors, rel_tol=1e-6)
    breakdown = res.json["breakdown"]
    assert math.isclose(sum(breakdown.values()), res.json["total"], rel_tol=1e-6)
    assert set(breakdown) == {"car", "electricity", "meat", "plant"}


def test_calculate_allows_zero(logged_in, valid_payload):
    valid_payload.update({"car_km": 0, "electricity_kwh": 0, "meat_meals": 0, "plant_meals": 0})
    res = logged_in.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 201
    assert res.json["total"] == 0


def test_calculate_accepts_numeric_strings(logged_in, valid_payload):
    valid_payload.update({"car_km": "10", "electricity_kwh": "20"})
    res = logged_in.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 201
    assert res.json["inputs"]["car_km"] == 10


def test_calculate_reports_all_bad_fields_at_once(logged_in, valid_payload):
    valid_payload.update({"car_km": "abc", "meat_meals": None, "plant_meals": -1})
    res = logged_in.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 400
    assert set(res.json["errors"]) == {"car_km", "meat_meals", "plant_meals"}


def test_calculate_rejects_booleans(logged_in, valid_payload):
    valid_payload["car_km"] = True
    assert logged_in.post("/footprint/calculate", json=valid_payload).status_code == 400


def test_calculate_missing_fields_lists_them(logged_in, valid_payload):
    del valid_payload["car_km"]
    res = logged_in.post("/footprint/calculate", json=valid_payload)
    assert res.status_code == 400
    assert "car_km" in res.json["msg"]


def test_calculate_ignores_unknown_fields(logged_in, valid_payload):
    valid_payload["surprise"] = 999
    assert logged_in.post("/footprint/calculate", json=valid_payload).status_code == 201


def test_empty_payload_object(logged_in):
    assert logged_in.post("/footprint/calculate", json={}).status_code == 400


# --- Region-aware factors -------------------------------------------------
def test_factors_endpoint_is_public(client):
    res = client.get("/footprint/factors")
    assert res.status_code == 200
    body = res.json
    assert body["default_region"] == "world"
    assert body["factors_version"] >= 1
    assert any(r["code"] == "fr" for r in body["regions"])
    assert all("label" in r and "electricity_kwh" in r for r in body["regions"])


def test_region_defaults_to_world(logged_in, valid_payload):
    res = logged_in.post("/footprint/calculate", json=valid_payload)
    assert res.json["region"] == "world"


def test_region_changes_the_electricity_factor(logged_in, valid_payload):
    valid_payload["electricity_kwh"] = 200
    valid_payload["car_km"] = 0
    valid_payload["meat_meals"] = 0
    valid_payload["plant_meals"] = 0

    world = logged_in.post("/footprint/calculate", json=dict(valid_payload))
    france = logged_in.post("/footprint/calculate", json={**valid_payload, "region": "fr"})

    # France's grid is far cleaner, so the same kWh costs much less carbon.
    assert france.json["total"] < world.json["total"] / 5
    assert math.isclose(world.json["total"], 200 * 0.475, rel_tol=1e-6)
    assert math.isclose(france.json["total"], 200 * 0.056, rel_tol=1e-6)


def test_region_is_stored_with_the_entry(logged_in, valid_payload):
    logged_in.post("/footprint/calculate", json={**valid_payload, "region": "de"})
    entry = logged_in.get("/footprint/history").json["entries"][0]
    assert entry["region"] == "de"
    assert entry["factors_version"] >= 1


def test_invalid_region_is_rejected(logged_in, valid_payload):
    res = logged_in.post("/footprint/calculate", json={**valid_payload, "region": "atlantis"})
    assert res.status_code == 400
    assert "region" in res.json["errors"]


def test_blank_region_falls_back_to_world(logged_in, valid_payload):
    res = logged_in.post("/footprint/calculate", json={**valid_payload, "region": ""})
    assert res.status_code == 201
    assert res.json["region"] == "world"


def test_summary_reports_each_entries_own_region(logged_in):
    base = {"car_km": 0, "electricity_kwh": 200, "meat_meals": 0, "plant_meals": 0}
    logged_in.post("/footprint/calculate", json={**base, "region": "fr"})
    logged_in.post("/footprint/calculate", json={**base, "region": "in"})

    body = logged_in.get("/footprint/summary").json
    assert set(body["regions"]) == {"fr", "in"}
    # France 0.056 + India 0.713 = 0.769 per kWh, times 200 kWh each entry.
    assert math.isclose(body["breakdown"]["electricity"], 200 * (0.056 + 0.713), rel_tol=1e-6)


def test_summary_reports_factors_versions(logged_in, valid_payload):
    logged_in.post("/footprint/calculate", json=valid_payload)
    body = logged_in.get("/footprint/summary").json
    assert len(body["factors_versions"]) == 1


# --- History / summary ----------------------------------------------------
def test_history_is_empty_for_new_user(logged_in):
    body = logged_in.get("/footprint/history").json
    assert body == {"entries": [], "total_entries": 0, "limit": 50, "offset": 0}


def test_history_orders_newest_first(logged_in, valid_payload):
    for km in (1, 2, 3):
        logged_in.post("/footprint/calculate", json={**valid_payload, "car_km": km})
    entries = logged_in.get("/footprint/history").json["entries"]
    assert [e["car_km"] for e in entries] == [3, 2, 1]


def test_history_paginates(logged_in, valid_payload):
    for _ in range(5):
        logged_in.post("/footprint/calculate", json=valid_payload)

    page = logged_in.get("/footprint/history?limit=2&offset=0").json
    assert len(page["entries"]) == 2
    assert page["total_entries"] == 5

    rest = logged_in.get("/footprint/history?limit=2&offset=4").json
    assert len(rest["entries"]) == 1


def test_history_rejects_bad_pagination(logged_in):
    assert logged_in.get("/footprint/history?limit=abc").status_code == 400


def test_history_clamps_oversized_limit(logged_in):
    assert logged_in.get("/footprint/history?limit=99999").json["limit"] == 200


def test_summary_for_new_user_is_zeroed(logged_in):
    body = logged_in.get("/footprint/summary").json
    assert body["entries"] == 0
    assert body["total"] == 0


# --- Misc -----------------------------------------------------------------
def test_health_endpoint(client):
    assert client.get("/health").json == {"status": "ok"}


def test_unknown_route_returns_json_404(client):
    res = client.get("/nope")
    assert res.status_code == 404
    assert res.json["msg"] == "Not found"


def test_wrong_method_returns_json_405(client):
    res = client.get("/auth/login")
    assert res.status_code == 405
    assert res.json["msg"] == "Method not allowed"


def test_token_expiry_is_configured(app):
    assert app.config["JWT_ACCESS_TOKEN_EXPIRES"] is not None
    assert current_app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds() > 0


def test_tokens_are_not_read_from_localstorage_style_body(client):
    """The client has no token to send; the cookie is the only credential."""
    assert client.get("/auth/me").status_code == 401
