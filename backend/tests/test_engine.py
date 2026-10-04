"""Proves the suite is running on the database it claims to be on.

This exists because of a specific failure. `conftest.py` hardcoded
`SQLALCHEMY_DATABASE_URI = "sqlite://"`, which overrode the `DATABASE_URL` the CI
job set. The job was named "Backend (postgres)", it went green, and all 199 tests
inside it ran on SQLite. Nothing failed, so nothing was noticed.

A green run of this file is the receipt that the engine is the one asked for.
"""

import os
import subprocess
import sys

import pytest

from tests.conftest import TEST_DATABASE_URL

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _probe_source():
    """A one-liner that prints the URI conftest resolved, in a clean interpreter."""
    return (
        f"import sys; sys.path.insert(0, {BACKEND_DIR!r});"
        "from tests.conftest import TEST_DATABASE_URL;"
        "print(TEST_DATABASE_URL)"
    )


def _run_probe(env):
    result = subprocess.run(
        [sys.executable, "-c", _probe_source()],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _backend_name(url):
    """What SQLAlchemy reports for a URL, from the URL's own prefix.

    "postgresql+psycopg://" reports as "postgresql"; the driver suffix is not
    part of the dialect name.
    """
    return url.split("://", 1)[0].split("+", 1)[0]


def test_the_suite_runs_on_the_requested_engine(app):
    from extensions import db

    expected = _backend_name(TEST_DATABASE_URL)
    actual = db.engine.url.get_backend_name()

    assert actual == expected, (
        f"the suite is running on {actual!r} but TEST_DATABASE_URL asks for "
        f"{expected!r} ({TEST_DATABASE_URL!r})"
    )


@pytest.mark.parametrize("url,expected", [
    ("sqlite://", "sqlite"),
    ("sqlite:///./test.db", "sqlite"),
    ("postgresql+psycopg://u:p@h:5432/db", "postgresql"),
    ("postgresql://u:p@h:5432/db", "postgresql"),
    ("postgresql+psycopg2://u:p@h:5432/db", "postgresql"),
])
def test_the_dialect_is_derived_from_the_url(url, expected):
    """Guards the comparison above, which has to hold for every URL form."""
    assert _backend_name(url) == expected


def test_database_url_alone_does_not_redirect_the_suite():
    """The regression guard, in a subprocess because the value is read at import.

    conftest resolves its URI when it is imported, so this cannot be checked by
    mutating os.environ here. If it ever starts reading DATABASE_URL, a
    developer with a dev database exported would lose it to a test run.
    """
    env = dict(os.environ)
    env.pop("TEST_DATABASE_URL", None)
    env["DATABASE_URL"] = "postgresql+psycopg://u:p@nonexistent-host:5432/should-not-be-used"

    resolved = _run_probe(env)
    assert resolved == "sqlite://", (
        f"DATABASE_URL leaked into the test configuration: {resolved!r}"
    )


def test_test_database_url_is_honoured_when_set():
    """The other half: the switch has to actually work."""
    env = dict(os.environ)
    env["TEST_DATABASE_URL"] = "postgresql+psycopg://u:p@localhost:5432/carbon_test"

    assert _run_probe(env) == env["TEST_DATABASE_URL"]
