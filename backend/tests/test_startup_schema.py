"""Refusing to serve against a database the migrations have not reached.

The failure this prevents is not hypothetical. A `git pull` without
`flask db upgrade` leaves a running app whose every request 500s on
`no such column: user.totp_secret` -- an error naming a column rather than the
missing step, and appearing only once the migration is deployed. These tests drive
the real `flask db` CLI to build a genuinely migrated database, then check the
startup guard in both directions.
"""

import os
import sqlite3
import subprocess
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEAD = "dfe8623682a4"


@pytest.fixture
def migrated_db(tmp_path):
    """A database at the current migration head, and the env that reaches it."""
    db_path = tmp_path / "schema_check.db"
    env = dict(os.environ)
    env["FLASK_APP"] = "app.py"
    env["FLASK_ENV"] = "development"
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["AUTO_CREATE_TABLES"] = "false"
    # The secrets must be present because create_app() validates config; the guard
    # under test is not gated on production mode.
    env.setdefault("SECRET_KEY", "a" * 48)
    env.setdefault("JWT_SECRET_KEY", "b" * 48)

    result = subprocess.run(
        [sys.executable, "-m", "flask", "db", "upgrade"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return env, db_path


def _create_app(env, check_schema=True):
    """Start the app against `env`, returning the process result."""
    if not check_schema:
        # For the branch test: the throwaway database has no migration history, so
        # the stale-schema guard would fire first and mask the branch message.
        env = {**env, "CHECK_SCHEMA_ON_STARTUP": "false"}
    return subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )


def _downgrade_one(env):
    subprocess.run(
        [sys.executable, "-m", "flask", "db", "downgrade", "--", "-1"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, check=True,
    )


def test_a_single_head_is_not_a_branch(app):
    """The normal case must not trip the guard.

    Read from real metadata rather than a stand-in. An earlier version mocked
    ScriptDirectory, and the mock raised inside the guard's own broad `except`,
    which logged and returned -- so the test appeared to pass while proving
    nothing at all.
    """
    from alembic.script import ScriptDirectory

    from app import _check_single_migration_head
    from extensions import migrate

    with app.app_context():
        heads = ScriptDirectory.from_config(migrate.get_config()).get_heads()
    assert len(heads) == 1, "this repository's history should be linear"

    _check_single_migration_head(app)


def _branched_history_in(env, target):
    """Copy the migrations aside and add a second head. Returns env pointing at it.

    The new revision hangs off the current head's *parent*, not off the head
    itself. A revision pointing at the head would just extend the chain and leave
    a single head, which is not the case under test.
    """
    import shutil
    import textwrap

    from alembic.script import ScriptDirectory

    target = target / "branchy_migrations"
    shutil.copytree(os.path.join(BACKEND_DIR, "migrations"), target)

    with _app_context():
        script = ScriptDirectory.from_config(_migrate_config())
        # Revision objects, newest first. Walking the ids instead yields the
        # human-readable "id -> id, message" form Alembic also uses for display,
        # which is not a revision id at all and produces a script directory that
        # cannot be read.
        revisions = list(script.walk_revisions())
        assert len(revisions) >= 2, "the head needs a parent to branch from"
        parent_id = revisions[1].revision

    (target / "versions" / "aaaa1111bbbb2222cccc3333_branch.py").write_text(
        textwrap.dedent(f'''
        """branch probe

        Revision ID: aaaa1111bbbb
        Revises: {parent_id}
        """

        from alembic import op
        import sqlalchemy as sa

        revision = "aaaa1111bbbb"
        down_revision = "{parent_id}"
        branch_labels = None
        depends_on = None


        def upgrade():
            op.create_table("branch_probe", sa.Column("id", sa.Integer()))


        def downgrade():
            op.drop_table("branch_probe")
        ''').strip(),
        encoding="utf-8",
    )

    return {**env, "MIGRATIONS_DIR": str(target)}


def test_a_genuinely_branched_repository_is_detected(tmp_path):
    """Two heads are refused, with merge advice rather than upgrade advice.

    Builds a second revision hanging off the current head's parent in a copy of
    the migrations directory, so this goes through Alembic's real metadata reader
    rather than a stand-in.

    get_current_head() returns None for multiple heads, which the stale-schema
    guard would report as "expected: (none)" -- true, but useless, and it points
    at `flask db upgrade`, which cannot resolve a branch.
    """
    env = dict(os.environ)
    env["FLASK_ENV"] = "development"
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'branchy.db'}"
    env["AUTO_CREATE_TABLES"] = "false"
    # The throwaway database has no migration history, so the stale-schema guard
    # would fire first and mask the branch message.
    env["CHECK_SCHEMA_ON_STARTUP"] = "false"
    env.setdefault("SECRET_KEY", "a" * 48)
    env.setdefault("JWT_SECRET_KEY", "b" * 48)

    result = _create_app(_branched_history_in(env, tmp_path / "m"))

    assert result.returncode != 0
    assert "branched" in result.stderr
    # Both heads named, so an operator can see which revision collided.
    assert "aaaa1111bbbb" in result.stderr
    # The remedy is a merge. It must not tell them to run `flask db upgrade`,
    # which is the command that cannot resolve a branch.
    assert "Create a merge revision" in result.stderr


def _app_context():
    """A throwaway app context for reading migration metadata.

    Alembic's config and SQLAlchemy's engine both need one, and a real app is the
    simplest way to get it. The schema check is off, since the test database has
    no migration history.
    """
    from app import create_app
    from tests.conftest import TestConfig

    return create_app(TestConfig).app_context()


def _migrate_config():
    from extensions import migrate

    return migrate.get_config()


def test_a_branched_history_is_not_reported_as_a_stale_database(tmp_path):
    """Both guards, and which one speaks first.

    Order matters: the schema check compares against get_current_head(), which is
    None for a branch, so running it first would report "expected: (none)" and
    send the operator to `flask db upgrade` -- a command that cannot resolve a
    branch. The branch check must be asked first.
    """
    env = dict(os.environ)
    env["FLASK_APP"] = "app.py"
    env["FLASK_ENV"] = "development"
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'ordered.db'}"
    env["AUTO_CREATE_TABLES"] = "false"
    env.setdefault("SECRET_KEY", "a" * 48)
    env.setdefault("JWT_SECRET_KEY", "b" * 48)
    branched_env = _branched_history_in(env, tmp_path / "m")

    # Schema check on, so that both guards are genuinely in play and their order
    # is what decides the message the operator sees.
    result = _create_app(branched_env)

    assert result.returncode != 0
    # The branch message, not the stale-schema one.
    assert "branched" in result.stderr
    assert "out of date" not in result.stderr


class TestStartupRefusesAStaleDatabase:
    def test_it_refuses_when_the_database_is_behind(self, migrated_db):
        env, db_path = migrated_db
        _downgrade_one(env)

        result = _create_app(env)

        assert result.returncode != 0, "a stale schema must not boot"
        assert "out of date" in result.stderr
        # And it says what to run, since that is the whole point of refusing.
        assert "flask db upgrade" in result.stderr

    def test_the_message_names_both_versions(self, migrated_db):
        env, _db_path = migrated_db
        _downgrade_one(env)

        result = _create_app(env)

        assert HEAD in result.stderr, "should say what it expected"
        assert "applied" in result.stderr

    def test_it_boots_when_the_database_is_current(self, migrated_db):
        env, _db_path = migrated_db

        result = _create_app(env)

        assert result.returncode == 0, result.stderr

    def test_it_refuses_an_uninitialised_database(self, tmp_path):
        # A fresh file with no alembic_version table at all. `flask db upgrade`
        # creates it, so the advice is the same either way.
        env = dict(os.environ)
        env["FLASK_APP"] = "app.py"
        env["FLASK_ENV"] = "development"
        env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'empty.db'}"
        env["AUTO_CREATE_TABLES"] = "false"
        env.setdefault("SECRET_KEY", "a" * 48)
        env.setdefault("JWT_SECRET_KEY", "b" * 48)

        result = _create_app(env)

        assert result.returncode != 0
        assert "flask db upgrade" in result.stderr

    def test_a_single_head_still_boots(self, migrated_db):
        # The guard must not fire on a healthy linear history.
        env, _db_path = migrated_db
        assert _create_app(env).returncode == 0

    def test_a_database_ahead_of_the_code_also_refuses(self, migrated_db):
        # Stamping head while the code is older is just as broken as the reverse,
        # and silently serving would be worse.
        env, db_path = migrated_db
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE alembic_version SET version_num = 'nonexistent-revision'"
            )

        result = _create_app(env)

        assert result.returncode != 0
        assert "out of date" in result.stderr

    def test_the_check_can_be_turned_off(self, migrated_db):
        env, _db_path = migrated_db
        _downgrade_one(env)
        env["CHECK_SCHEMA_ON_STARTUP"] = "false"

        result = _create_app(env)

        # Off means off: the operator gets the old behaviour rather than a
        # startup they cannot get past.
        assert result.returncode == 0, result.stderr

    def test_the_migration_command_itself_is_not_blocked(self, migrated_db):
        # The chicken-and-egg case: `flask db upgrade` must still run against a
        # stale database, or the guard would make the problem unfixable.
        env, _db_path = migrated_db
        _downgrade_one(env)

        result = subprocess.run(
            [sys.executable, "-m", "flask", "db", "upgrade"],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
        )

        assert result.returncode == 0, result.stderr

        # And now the app boots, which is the point of the exemption.
        assert _create_app(env).returncode == 0

    def test_it_is_not_blocked_by_a_global_option_before_the_subcommand(self, migrated_db):
        # The regression. Flask takes global options before the subcommand, so
        # `flask --app app db upgrade` is the same command as `flask db upgrade`.
        # An earlier version matched a fixed argument position and so exempted
        # only the shortest form, which meant the guard refused the fix and then
        # told the operator to run `flask db upgrade` -- advice that failed too,
        # against the same stale database.
        for prefix in ([], ["--app", "app"], ["--app", "app.py"]):
            env, _db_path = migrated_db
            _downgrade_one(env)

            result = subprocess.run(
                [sys.executable, "-m", "flask", *prefix, "db", "upgrade"],
                cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
            )

            assert result.returncode == 0, (
                f"`flask {' '.join(prefix)} db upgrade` was blocked:\n{result.stderr}"
            )
            # Fixing it must actually leave a database the app will accept.
            assert _create_app(env).returncode == 0

    def test_the_exemption_does_not_leak_to_other_servers(self):
        # wsgi:app and the dev server must still be checked. Only the flask CLI
        # sets FLASK_RUN_FROM_CLI, which is what keeps this narrow.
        import app as app_module

        for argv in (["gunicorn", "wsgi:app"], ["python", "app.py"], ["pytest"]):
            saved = sys.argv
            sys.argv = argv
            try:
                assert app_module._is_running_a_migration_command() is False, argv
            finally:
                sys.argv = saved

    def test_it_does_not_exempt_a_non_flask_process_that_mentions_db(self):
        import app as app_module

        saved = os.environ.pop("FLASK_RUN_FROM_CLI", None)
        try:
            sys.argv = ["python", "tools/db_dump.py"]
            assert app_module._is_running_a_migration_command() is False
        finally:
            if saved is not None:
                os.environ["FLASK_RUN_FROM_CLI"] = saved
            sys.argv = ["pytest"]

    def test_fixing_it_actually_fixes_it(self, migrated_db):
        env, _db_path = migrated_db
        _downgrade_one(env)
        assert _create_app(env).returncode != 0

        subprocess.run(
            [sys.executable, "-m", "flask", "db", "upgrade"],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True, check=True,
        )

        assert _create_app(env).returncode == 0


class TestTheCheckDistinguishesFailureKinds:
    def test_an_unreachable_database_is_not_reported_as_a_stale_schema(
        self, migrated_db
    ):
        # These two look identical in an exception and mean opposite things. The
        # unreachable one is fixed by fixing the connection; telling the operator
        # to run `flask db upgrade` would send them down the wrong path entirely,
        # and would also replace a clear connection error with a confusing one.
        env, _db_path = migrated_db
        env["DATABASE_URL"] = "sqlite:////nonexistent-dir/nope.db"

        result = _create_app(env)

        assert "out of date" not in result.stderr

    def test_an_uninitialised_database_is_reported_as_needing_upgrade(self, tmp_path):
        # The contrasting case: reachable, but never migrated. Here `flask db
        # upgrade` really is the answer.
        env = dict(os.environ)
        env["FLASK_APP"] = "app.py"
        env["FLASK_ENV"] = "development"
        env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'empty.db'}"
        env["AUTO_CREATE_TABLES"] = "false"
        env.setdefault("SECRET_KEY", "a" * 48)
        env.setdefault("JWT_SECRET_KEY", "b" * 48)

        result = _create_app(env)

        assert result.returncode != 0
        assert "out of date" in result.stderr
