"""Does the migration chain produce the schema the models describe?

The test suite builds its database with create_all(), which means a model edited
without a matching migration revision would pass every test and only fail against
a real database. This compares the two directly.

That gap is not hypothetical: an earlier revision widened `region` in the model
while the migration chain said VARCHAR(16). SQLite does not enforce VARCHAR
length, so neither the tests nor `flask db check` noticed.

The migrated side is always SQLite, because that is what the chain can be driven
against cheaply and deterministically. The model side is read from the SQLAlchemy
metadata rather than from a live create_all() database, so this compares like with
like and does not depend on which engine the suite itself is running against --
comparing a Postgres database against a SQLite file would report every FLOAT as
DOUBLE PRECISION and TIMESTAMP as DATETIME, which says nothing about drift.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Alembic's own bookkeeping table has no ORM counterpart.
IGNORED_TABLES = {"alembic_version"}


def _flask_db(*args, env):
    result = subprocess.run(
        [sys.executable, "-m", "flask", "db", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"flask db {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="module")
def migrated_schema():
    """The schema the whole migration chain produces, as SQLite describes it."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "migrated.db")
    env = dict(os.environ)
    env.update({
        "FLASK_APP": "app.py",
        "FLASK_ENV": "development",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "AUTO_CREATE_TABLES": "false",
    })
    _flask_db("upgrade", "head", env=env)

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("sqlite_")
        }
        schema = {}
        for table in sorted(tables - IGNORED_TABLES):
            # PRAGMA table_info gives (cid, name, type, notnull, default, pk),
            # where notnull and pk are already 1/0 flags.
            schema[table] = {
                row[1]: (str(row[2]).upper(), bool(row[3]), bool(row[5]))
                for row in conn.execute(f'PRAGMA table_info("{table}")')
            }
        return schema
    finally:
        conn.close()


@pytest.fixture(scope="module")
def model_schema():
    """The schema the models describe, read from SQLAlchemy metadata.

    Column order is normalised away: a migration that reorders columns produces
    the same schema, and SQLite's batch mode rebuilds tables freely.
    """
    import models  # noqa: F401  -- importing registers the mappers on the metadata
    from extensions import db

    schema = {}
    for table in db.metadata.sorted_tables:
        if table.name in IGNORED_TABLES:
            continue
        schema[table.name] = {
            column.name: (
                str(column.type).upper(),
                not column.nullable,
                column.primary_key,
            )
            for column in table.columns
        }
    assert schema, "no tables in the model metadata; were the models imported?"
    return schema


def test_every_model_table_exists_in_the_migrations(model_schema, migrated_schema):
    missing = sorted(set(model_schema) - set(migrated_schema))
    extra = sorted(set(migrated_schema) - set(model_schema))
    assert not missing, f"tables in the models but in no migration: {missing}"
    assert not extra, f"tables created by a migration but absent from the models: {extra}"


def test_every_model_column_exists_in_the_migrations(model_schema, migrated_schema):
    missing = {}
    for table, columns in model_schema.items():
        absent = sorted(set(columns) - set(migrated_schema.get(table, {})))
        if absent:
            missing[table] = absent
    assert not missing, (
        "columns declared on a model but created by no migration: "
        f"{missing}. `flask db migrate` and review the generated script."
    )


def test_no_migration_creates_a_column_the_models_dropped(model_schema, migrated_schema):
    extra = {}
    for table, columns in migrated_schema.items():
        surplus = sorted(set(columns) - set(model_schema.get(table, {})))
        if surplus:
            extra[table] = surplus
    assert not extra, (
        f"columns created by a migration but removed from the models: {extra}"
    )


def test_column_types_and_constraints_match(model_schema, migrated_schema):
    mismatched = {}
    for table, columns in model_schema.items():
        migrated_columns = migrated_schema.get(table, {})
        for name, definition in columns.items():
            if name not in migrated_columns:
                continue  # reported by the column-existence test above
            if migrated_columns[name] != definition:
                mismatched.setdefault(table, {})[name] = (
                    definition, migrated_columns[name]
                )
    assert not mismatched, (
        "type / NOT NULL / primary-key differ between the models and the "
        f"migrations: {mismatched}"
    )


def test_the_migration_chain_is_not_empty(migrated_schema):
    """Guards the comparison above against silently inspecting nothing."""
    assert migrated_schema, "the migration chain produced no tables"
    assert {"user", "footprint", "user_session"} <= set(migrated_schema)
