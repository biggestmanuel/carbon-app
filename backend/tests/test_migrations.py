"""End-to-end proof that Alembic can alter a populated database.

This is the failure mode create_all() could never survive: a column was widened
in models.py, the dev database kept the old schema, and every request 500'd.
These tests drive the real `flask db` CLI against a temporary SQLite file.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def flask_db(*args, env):
    result = subprocess.run(
        [sys.executable, "-m", "flask", "db", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"flask db {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


@pytest.fixture
def migration_env():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "migrations_test.db")
    env = dict(os.environ)
    env["FLASK_APP"] = "app.py"
    env["FLASK_ENV"] = "development"
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    # Must be off, otherwise create_all() would mask what migrations do.
    env["AUTO_CREATE_TABLES"] = "false"
    return env, db_path


def _revisions(history):
    # `db history` lists newest-first as "<from> -> <to>, msg"; reverse it.
    found = []
    for line in history.splitlines():
        if "->" not in line:
            continue
        to = line.split("->")[1].split(",")[0].replace("(head)", "").strip()
        found.append(to)
    found.reverse()
    return found


def test_migrations_exist_and_form_a_chain(migration_env):
    env, _ = migration_env
    revisions = _revisions(flask_db("history", env=env))
    assert len(revisions) >= 2, f"expected an initial migration plus at least one ALTER, got {revisions}"


def test_upgrade_creates_the_expected_schema(migration_env):
    env, db_path = migration_env
    flask_db("upgrade", "head", env=env)

    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"user", "footprint", "alembic_version"} <= tables

    columns = {c[1] for c in conn.execute("PRAGMA table_info(footprint)")}
    assert {"user_id", "car_km", "electricity_kwh", "meat_meals", "plant_meals",
            "total", "region", "factors_version", "created_at"} <= columns
    conn.close()


def test_alter_preserves_data_in_a_populated_database(migration_env):
    """The core regression: widen a column on a DB that already has rows."""
    env, db_path = migration_env
    revisions = _revisions(flask_db("history", env=env))
    first, head = revisions[0], revisions[-1]

    # Stop at the first revision, so the schema is still the old shape.
    flask_db("upgrade", first, env=env)
    conn = sqlite3.connect(db_path)
    region_type = [c for c in conn.execute("PRAGMA table_info(footprint)") if c[1] == "region"][0][2]
    assert region_type != "VARCHAR(16)", f"first revision already widened: {region_type}"

    # A row holding a value that only fits the widened column.
    conn.execute("INSERT INTO user (username, password_hash, created_at) VALUES (?, ?, ?)",
                 ("migtest", "x", "2026-01-01 00:00:00"))
    conn.execute(
        "INSERT INTO footprint (user_id, car_km, electricity_kwh, meat_meals, "
        "plant_meals, total, region, factors_version, created_at) "
        "VALUES (1, 10, 20, 3, 5, 44.1, 'verylongregion', 2, '2026-01-01 00:00:00')"
    )
    conn.commit()
    conn.close()

    # Upgrade to head: the ALTER must apply without dropping the row.
    flask_db("upgrade", "head", env=env)

    conn = sqlite3.connect(db_path)
    after = [c for c in conn.execute("PRAGMA table_info(footprint)") if c[1] == "region"][0][2]
    rows = conn.execute("SELECT region, total, factors_version FROM footprint").fetchall()
    stamped = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    conn.close()

    assert after == "VARCHAR(16)", f"column was not widened (got {after})"
    assert rows == [("verylongregion", 44.1, 2)], f"data lost or altered: {rows}"
    assert stamped[0].startswith(head[:8]), f"not stamped at head: {stamped} vs {head}"


def test_downgrade_reverts_the_schema(migration_env):
    env, db_path = migration_env
    revisions = _revisions(flask_db("history", env=env))
    first = revisions[0]

    flask_db("upgrade", "head", env=env)
    flask_db("downgrade", first, env=env)

    conn = sqlite3.connect(db_path)
    region_type = [c for c in conn.execute("PRAGMA table_info(footprint)") if c[1] == "region"][0][2]
    stamped = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    conn.close()

    assert region_type != "VARCHAR(16)", f"downgrade did not revert: {region_type}"
    assert stamped[0].startswith(first[:8]), f"not stamped at first: {stamped} vs {first}"


def test_create_all_is_disabled_by_default(migration_env):
    """The app must not silently create tables when migrations are the source of truth."""
    env, db_path = migration_env
    from app import create_app

    application = create_app()
    assert application.config["AUTO_CREATE_TABLES"] is False
    assert not os.path.exists(db_path), "importing the app created a database"


def test_migration_history_is_not_ignored():
    """migrations/ must be committed or deploys silently skip the schema."""
    migrations_dir = os.path.join(BACKEND_DIR, "migrations")
    assert os.path.isdir(migrations_dir)
    versions = os.path.join(migrations_dir, "versions")
    assert os.path.isdir(versions)
    files = [f for f in os.listdir(versions) if f.endswith(".py")]
    assert files, "no migration scripts found"
    for name in files:
        assert not name.startswith("_"), f"unexpected placeholder in versions/: {name}"