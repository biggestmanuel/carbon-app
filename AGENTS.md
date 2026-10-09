# AGENTS.md

Working notes for coding agents on this repository.

## After every file change, commit and push

Commit and push after every change. No batching, no "I'll do it at the end".

Each commit needs:

- A one-line summary in the imperative (`fix(mfa):`, `test(footprint):`, `docs:`).
- A body explaining **why**, not what. The diff already says what changed. The body
  should carry the reasoning that is not visible in the diff: the failure mode,
  what it looked like, or the constraint that forced the shape of the fix.
- Any security-relevant detail spelled out plainly. If a change touches
  authentication, sessions, passwords, rate limiting or tokens, the commit body is
  where the threat model goes.

Push to `main`. The tree is expected to be clean at the end of every change.

## Before committing, review for leaked secrets

Review the diff — the whole diff, including test files and fixtures — for
credentials before it is committed:

- Real API keys, tokens, passwords, private keys, certificates, connection
  strings with credentials.
- Anything that belongs in `backend/.env`. That file is gitignored and holds real
  secrets locally; it must never appear in a commit.
- Test fixtures should use obviously fake values (`"a" * 48`, a real RFC 4226
  TOTP vector, `JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP`). Placeholders that look like
  real keys get copy-pasted into production by accident.

`backend/.env` is gitignored. Confirm it stays that way:

```
git check-ignore backend/.env
git ls-files backend/.env      # must print nothing
```

Known patterns worth grepping for:

```
ghp_|github_pat_|sk-[A-Za-z0-9]{20}|AKIA[0-9A-Z]{16}|-----BEGIN
```

## Tests come before the fix

Every bug fix is preceded by a test that reproduces it. Write the test, watch it
fail for the right reason, then fix, then watch it pass. Confirm the regression
test actually catches the bug by reintroducing it if there is any doubt — a test
that passes before and after the change is not testing the change.

## Layout

- `backend/` — Flask app. `app.py` holds `create_app` and the startup guards;
  `routes/` holds blueprints; `models.py` the schema; `tests/` the pytest suite.
- `frontend/` — React + Vite + TypeScript. `src/api.ts` is the HTTP client,
  `src/types.ts` the API shapes, `src/components/` the UI.
- `frontend/e2e/` — Playwright layout tests. The API is fully stubbed, so no
  backend or database is needed to run them.

## Verifying

```
# backend, from backend/
python -m pytest tests -q
python -m ruff check .

# frontend, from frontend/
npm run lint
npx tsc --noEmit
npm test
```

The backend suite is also run against Postgres, not only SQLite. Some behaviour
differs between the two and SQLite alone will not catch it.

## Things that have bitten us

- **PowerShell.** No `&&`. Use `pushd`/`popd` or set `workdir`.
- **`localhost` vs `127.0.0.1`.** `localhost` resolves to `::1` first, and hangs
  for ~21s against Docker-published IPv4 ports. Always use `127.0.0.1`. The same
  applies in config: `RATELIMIT_STORAGE_URI` should point at `127.0.0.1`.
- **gunicorn imports `fcntl`** and cannot run on Windows at all.
- **`flask -e` is `--env-file`**, not "environment name".
- **Relative SQLite URLs** resolve against `backend/instance/`, not the CWD.
- **Stop parallel test runs and Docker containers together.** Vitest exhausts its
  thread pool and fails whichever file it happens to be on, so the failures move
  between runs. Stop the containers; do not paper over it.
- **Werkzeug's reloader respawns child processes**, so killing the listener
  leaves the parent alive.

## Things not to "fix"

- `backend/extensions.py` must **not** pass `storage_uri` to `Limiter()`. The
  constructor argument beats the app config, so `RATELIMIT_STORAGE_URI` in the
  environment would be silently ignored. There is a test for this.
- `AUTO_CREATE_TABLES` is off by design. The schema moves via Alembic only, and
  the startup guard refuses to serve against a stale database.
- `/health` is deliberately unthrottled.
- `docker compose` Redis has persistence off on purpose.

## Undocumented behaviour worth knowing

- `flask db upgrade` needs `FLASK_APP=app.py`. The startup guards exempt the
  Flask CLI, otherwise fixing a stale schema would be impossible.
- `discard_totp_counter` / `consume_totp_counter` exist because a TOTP step can
  legitimately straddle two 30-second windows. Without them, a code entered near
  a boundary would be rejected right after being accepted.