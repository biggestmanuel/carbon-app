"""The composite index behind GET /footprint/history.

An index that exists but is never used is worse than none: it costs write
throughput on every insert for nothing. These tests check the index is declared,
matches the columns the endpoint filters and orders by, and that the endpoint's
paging still behaves.

The migration side is covered in test_migrations.py, where the fixture that
drives the real `flask db` CLI already lives.
"""

from sqlalchemy import inspect as sa_inspect

INDEX_NAME = "ix_footprint_user_created"
INDEX_COLUMNS = ["user_id", "created_at", "id"]


class TestIndexExists:
    def test_it_is_declared_on_the_model(self):
        from models import Footprint

        assert INDEX_NAME in {index.name for index in Footprint.__table__.indexes}

    def test_it_covers_the_columns_the_query_uses(self):
        from models import Footprint

        index = next(i for i in Footprint.__table__.indexes if i.name == INDEX_NAME)
        # user_id filters; created_at orders; id is the tiebreak that makes the
        # sort fully covered by the index.
        assert [c.name for c in index.columns] == INDEX_COLUMNS

    def test_every_indexed_column_exists(self):
        from models import Footprint

        for column in INDEX_COLUMNS:
            assert column in Footprint.__table__.columns

    def test_it_exists_in_a_created_schema(self, app):
        from extensions import db

        with app.app_context():
            indexes = sa_inspect(db.engine).get_indexes("footprint")
            assert INDEX_NAME in {i["name"] for i in indexes}

    def test_it_is_not_unique(self, app):
        # Many rows share a user_id; a unique index would reject valid inserts.
        from extensions import db

        with app.app_context():
            indexes = sa_inspect(db.engine).get_indexes("footprint")
            index = next(i for i in indexes if i["name"] == INDEX_NAME)
            assert not index["unique"]

    def test_the_single_column_indexes_are_still_there(self, app):
        # Removing them is a separate judgement call; this pins that the
        # composite was added rather than swapped in unnoticed.
        from extensions import db

        with app.app_context():
            names = {i["name"] for i in sa_inspect(db.engine).get_indexes("footprint")}
        assert {"ix_footprint_user_id", "ix_footprint_created_at"} <= names


class TestTheEndpointStillBehaves:
    def test_history_returns_newest_first(self, client, auth_headers):
        auth_headers()
        for km in (10, 20, 30):
            client.post("/footprint/calculate", json={
                "car_km": km, "electricity_kwh": 1, "meat_meals": 1, "plant_meals": 1,
            })

        entries = client.get("/footprint/history").json["entries"]
        assert [e["car_km"] for e in entries] == [30, 20, 10]

    def test_paging_does_not_reorder_or_repeat(self, client, auth_headers):
        auth_headers()
        for km in range(5):
            client.post("/footprint/calculate", json={
                "car_km": km, "electricity_kwh": 1, "meat_meals": 1, "plant_meals": 1,
            })

        first = client.get("/footprint/history?limit=2").json["entries"]
        second = client.get("/footprint/history?limit=2&offset=2").json["entries"]

        assert [e["car_km"] for e in first] == [4, 3]
        assert [e["car_km"] for e in second] == [2, 1]
        assert not {e["id"] for e in first} & {e["id"] for e in second}

    def test_it_is_still_scoped_to_one_user(self, client, valid_payload):
        client.post("/auth/register", json={"username": "alice", "password": "correct-horse"})
        client.post("/auth/login", json={"username": "alice", "password": "correct-horse"})
        client.post("/footprint/calculate", json=valid_payload)

        client.post("/auth/register", json={"username": "bob", "password": "another-password"})
        client.post("/auth/login", json={"username": "bob", "password": "another-password"})

        # The composite index leads with user_id, so a missing equality on it
        # would show up here first.
        assert client.get("/footprint/history").json["total_entries"] == 0
