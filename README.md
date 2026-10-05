# carbon-app

A full-stack app for tracking personal carbon emissions. Users register and log in,
log their weekly activity (driving, electricity, meals), and get a kg CO₂e estimate
built from per-category emission factors, adjusted for their region's grid mix.

## Stack

| Layer    | Tech                                              |
| -------- | ------------------------------------------------- |
| Backend  | Flask 3, SQLAlchemy, Flask-JWT-Extended, Flask-Cors, Flask-Migrate, Flask-Limiter |
| Database | SQLite by default, Postgres in production (any SQLAlchemy URL via `DATABASE_URL`) |
| Frontend | React 19 + Vite 8 + TypeScript (strict), axios    |
| Serving  | gunicorn (`backend/wsgi.py`)                     |

## Layout

```
backend/
  app.py            application factory + error handlers
  config.py         env-driven config, validated at startup
  extensions.py     db / jwt / migrate / limiter singletons (breaks the models<->app import cycle)
  factors.py        region-aware emission factor data
  models.py         User, UserSession, Footprint
  routes/
    auth.py         register, login, refresh, logout, me, forgot-password, reset-password
    account.py      email confirmation, session list/revoke, export, deletion
    footprint.py    calculate, history, summary, factors
  passwords.py      single-use tokens, generated and stored hashed
  mail.py           pluggable mailer: console in dev, SMTP in production
  wsgi.py           production entrypoint + gunicorn settings
  migrations/       Alembic history; `flask db upgrade` owns the schema
  tests/            pytest suite
frontend/
  src/
    types.ts        every API response shape, in one place
    api.ts          axios instance, withCredentials, transparent token refresh, 401 handling
    lib/footprint.ts  field definitions, input parsing, factor lookup (pure, unit-tested)
    App.tsx         session state, token verification, expiry handling, link routing
    components/     Login, Register, ForgotPassword, ResetPassword, VerifyEmail,
                    Dashboard, FootprintForm, Summary, HistoryList, Sessions,
                    AccountSettings
  preview.html        static capture of the dashboard UI
  preview-auth.html   static capture of the logged-out and reset screens
```

## Running it

Two terminals.

```bash
# 1. Backend  -> http://127.0.0.1:5000
cd backend
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
copy .env.example .env                             # then edit the secrets
flask db upgrade                                   # create/alter the schema
python app.py

# 2. Frontend -> http://localhost:5173
cd frontend
npm install
npm run dev
```

The API must allow the frontend origin. `.env.example` defaults
`CORS_ORIGINS=http://localhost:5173` to match Vite's default port. The browser
must also be allowed to send credentials, which `CORS(app, supports_credentials=True)`
handles; that is only safe because the origin list is explicit and never `*`.

### Database migrations

`flask db upgrade` is the only supported way to change the schema. `db.create_all()`
is **off by default** because it can create missing tables but never alters existing
ones, so it silently leaves populated databases broken.

```bash
cd backend
flask db upgrade                       # apply everything
flask db migrate -m "add x column"     # autogenerate a new revision
flask db downgrade                     # step back one revision
```

An existing database created before migrations existed can be adopted without
recreating it: `flask db stamp base` followed by `flask db upgrade`, after
reviewing the generated SQL.

### Configuration

Everything is read from `backend/.env`. See `.env.example` for the full list. The
ones that matter:

| Variable                   | Default                | Notes                                      |
| -------------------------- | ---------------------- | ------------------------------------------ |
| `SECRET_KEY`               | dev placeholder        | Must be set in production                  |
| `JWT_SECRET_KEY`           | dev placeholder        | Must be set in production                  |
| `DATABASE_URL`             | `sqlite:///carbon.db`  | Any SQLAlchemy URL                         |
| `JWT_ACCESS_TOKEN_MINUTES` | `30`                   | Silently renewed from the refresh cookie   |
| `JWT_REFRESH_TOKEN_DAYS`   | `7`                    | After this, the user must log in again     |
| `JWT_COOKIE_SECURE`        | `true` in production   | Startup fails if off in production         |
| `CORS_ORIGINS`             | `http://localhost:5173`| Comma-separated; `*` is rejected in prod   |
| `LOGIN_RATE_LIMIT`         | `10 per minute`        | See "Rate limiting" below                  |
| `RESET_RATE_LIMIT`         | `5 per hour`           | Also covers email confirmation            |
| `DELETE_RATE_LIMIT`        | `3 per hour`           | Deletion is irreversible                  |
| `RATELIMIT_STORAGE_URI`    | `memory://`            | **Use Redis for multi-process deployments** |
| `MAIL_ENABLED` / `MAIL_HOST` | off / unset          | Must agree with each other                |
| `PUBLIC_BASE_URL`          | `http://localhost:5173` | Prefix for emailed links                 |
| `PASSWORD_RESET_TTL_MINUTES` | `30`                 | Reset token lifetime                      |
| `EMAIL_VERIFICATION_TTL_MINUTES` | `1440`            | Confirmation token lifetime               |
| `RESET_REQUIRES_VERIFIED_EMAIL` | `true`           | Refuse resets to unconfirmed addresses    |
| `CHECK_SCHEMA_ON_STARTUP`  | `true`                 | Refuse to serve a stale schema            |
| `PROXY_FIX_X_FOR`          | `0`                    | Number of trusted proxies; 0 = none      |
| `SESSION_TOUCH_INTERVAL_SECONDS` | `300`             | `last_seen_at` write frequency           |
| `BREACH_CHECK_ENABLED`     | `true`                 | Refuse known-compromised passwords        |
| `BREACH_CHECK_TIMEOUT_SECONDS` | `2`                | Fails open, so an outage cannot lock out |
| `TOTP_ENCRYPTION_KEY`      | unset                  | Fernet key for TOTP seeds. See 2FA below  |
| `TOTP_ISSUER`              | `carbon-app`           | Shown in the authenticator app            |
| `TOTP_RECOVERY_CODES`      | `10`                   | Issued at enrolment                       |
| `TOTP_DISABLE_REQUIRES_PASSWORD` | `true`           | Also require the password to turn 2FA off |
| `FLASK_ENV`                | `development`          | `production` enables the safety checks    |

`Config.validate()` refuses to start in production when the secrets are still
placeholders, when the cookie is not Secure, when `CORS_ORIGINS` is `*`, when
`AUTO_CREATE_TABLES` is on, when mail is half-configured, when
`RATELIMIT_STORAGE_URI` is `memory://` with more than one worker, or when
`TOTP_ENCRYPTION_KEY` is set but malformed. It reports every problem at once rather
than the first.

On startup it also compares the applied migration against the head and refuses to
serve if they differ, naming both revisions and telling you to run `flask db
upgrade`. This is the commonest deployment mistake in a project where
`AUTO_CREATE_TABLES` is deliberately off: pulling and forgetting the migration
otherwise produces a running app whose every request 500s on
`no such column: user.totp_secret` — an error naming a column rather than the
missing step. `flask db ...` is exempt from the check, so the command that fixes a
stale database is never the one that refuses to run. Set
`CHECK_SCHEMA_ON_STARTUP=false` to restore the old behaviour.

Frontend config is `VITE_API_URL` in `frontend/.env` (see `.env.example`).

## Sessions

Access and refresh tokens are set as **httpOnly cookies**, so page scripts and XSS
payloads cannot read them. Nothing is stored in `localStorage`.

- `POST /auth/login` sets both cookies and returns only the username. With a
  second factor armed it instead returns `mfa_required` and a five-minute
  `pending_token`, and sets **no** cookies; `POST /auth/mfa/check` then takes that
  token plus a code and sets the real cookies.
- `POST /auth/logout` clears them and is idempotent.
- `POST /auth/refresh` trades the refresh cookie for a new access cookie.
- On a `401`, the frontend tries one refresh and replays the request, so the
  30 minute access lifetime is not a hard sign-out. If the refresh also fails,
  the app logs out cleanly rather than stranding the user on a dead dashboard.
- A password change invalidates every existing session via the `token_version`
  claim described under Password reset.
- Each login records a `user_session` row and puts its id in the token, so
  individual devices can be ended. See Account control below.
- `JWT_COOKIE_CSRF_PROTECT` is off because every state-changing request is a JSON
  POST from an allowlisted origin, which a cross-site form cannot forge and a
  cross-origin fetch cannot pass CORS preflight for. Turn it on if the API is
  ever called from a context that does allow those.

### Deploying across domains

`SameSite=Lax` is the default and works in development because cookies ignore
ports: `localhost:5173` → `localhost:5000` is the same *site*.

It stops working the moment the frontend and API sit on different registrable
domains. `app.example.com` and `api.example.com` are cross-site, and a Lax cookie
is then never sent at all. **Nothing errors.** Every login returns 200 and every
later request is unauthenticated.

For that topology set:

```
JWT_COOKIE_CROSS_SITE=true
JWT_COOKIE_SECURE=true          # required; browsers reject SameSite=None without it
```

`Config.validate()` refuses to start in production if `SameSite=None` is paired
with an insecure cookie, since the browser would silently drop it.

## Password hashing

scrypt, Werkzeug's default. It is memory-hard, so it resists GPU cracking better
than pbkdf2, and it is also cheaper here — about 140 ms per verification against
roughly 900 ms for `pbkdf2:sha256` at Werkzeug's raised default of 1,000,000
iterations.

The method is recorded inside each hash, so **accounts created before the switch
keep working with no migration and no forced password reset**. Both formats can
sit in the column at once, and a password reset rewrites the row as scrypt.

`routes/auth.py` verifies a throwaway hash when a username is unknown, so a
missing account costs the same wall time as a wrong password. That dummy uses
scrypt to match new hashes.

## Rate limiting

Per-route limits via Flask-Limiter, keyed by client IP:

| Route                  | Default limit |
| ---------------------- | ------------- |
| `POST /auth/login`     | 10 per minute |
| `POST /auth/register`  | 5 per hour    |
| `POST /auth/forgot-password`, `/account/verify-email/*` | 5 per hour (`RESET_RATE_LIMIT`) |
| `POST /auth/mfa/check` | 5 per minute (`TOTP_RATE_LIMIT`) |
| `/auth/mfa/start`, `/confirm`, `/disable`, `/recovery-codes` | 5 per hour (`TOTP_MANAGE_RATE_LIMIT`) |
| `DELETE /account/account` | 3 per hour (`DELETE_RATE_LIMIT`) |
| `POST /footprint/calculate` | 120 per minute |
| `GET /footprint/history`, `/footprint/summary` | 120 per minute |

Breaches return `429` with a JSON body and `Retry-After`.

`GET /health` is deliberately unthrottled: a load balancer polling it could get a
`429` and pull a healthy instance out of rotation, which is a self-inflicted
outage in exchange for protecting a two-key JSON response.

**Set `RATELIMIT_STORAGE_URI` to Redis before running more than one worker.** The
default `memory://` store counts per process, so a limit of 10/minute becomes 40
with four workers. That is a security control quietly not applying, not a
performance detail — so `Config.validate()` refuses to start in production when
`memory://` is combined with `WEB_CONCURRENCY` above 1, and says what to do. One
worker is still allowed, because there the limiter genuinely works.

```bash
docker compose up -d    # Postgres and Redis, for local development
```

## API

All `/footprint/*` routes except `/footprint/factors` require a session cookie.

| Method | Path                     | Purpose                                  |
| ------ | ------------------------ | ---------------------------------------- |
| POST   | `/auth/register`         | Create an account; `email` optional      |
| POST   | `/auth/login`            | Sets cookies, or `mfa_required` + a pending token |
| POST   | `/auth/mfa/check`        | Pending token + code → real session cookies |
| GET    | `/auth/mfa/start`        | Begin enrolment; returns the secret and otpauth URI |
| POST   | `/auth/mfa/confirm`      | Turn 2FA on; returns the recovery codes, once |
| POST   | `/auth/mfa/disable`      | Turn 2FA off; needs a code *and* the password |
| GET    | `/auth/mfa/status`       | Whether 2FA is on and how many codes remain |
| POST   | `/auth/mfa/recovery-codes` | Replace the recovery codes; needs the password |
| POST   | `/auth/refresh`          | New access cookie from the refresh cookie|
| POST   | `/auth/logout`           | Clears cookies                           |
| GET    | `/auth/me`               | Confirm a session; email is masked       |
| POST   | `/auth/forgot-password`  | Email a reset link; never reveals whether the address exists |
| POST   | `/auth/reset-password`   | Consume a token and set a new password   |
| POST   | `/account/verify-email/request` | Re-send a confirmation link         |
| POST   | `/account/verify-email/confirm` | Confirm an address from its token |
| GET    | `/account/sessions`      | This account's active devices           |
| DELETE | `/account/sessions`      | Sign out everywhere                     |
| DELETE | `/account/sessions/<id>` | Sign out one device                     |
| GET    | `/account/export`        | All entries as JSON, or `?format=csv`   |
| DELETE | `/account/account`       | Delete the account; requires the password |
| POST   | `/footprint/calculate`   | Validate, calculate and store an entry   |
| GET    | `/footprint/history`     | Stored entries, newest first, paged      |
| GET    | `/footprint/summary`     | Lifetime totals per category and region  |
| GET    | `/footprint/factors`     | Region catalogue and units (public)      |
| GET    | `/health`                | Liveness check                           |

Validation on `POST /footprint/calculate` rejects anything that would corrupt the
total: non-numeric input, `NaN`, `Infinity`, negatives, values over the configured
cap, fractional meal counts, and unknown regions. Every bad field is reported at once:

```json
{
  "msg": "car_km must be a finite number; meat_meals must be a whole number",
  "errors": { "car_km": "car_km must be a finite number",
              "meat_meals": "meat_meals must be a whole number" }
}
```

## Password reset

`POST /auth/forgot-password` emails a single-use token that expires after
`PASSWORD_RESET_TTL_MINUTES`. Three properties matter:

- **It never reveals whether an address exists.** The response is identical for a
  known address, an unknown one and a malformed one, so the endpoint is not a
  user-enumeration oracle.
- **Tokens are stored hashed**, so a database leak hands over no working links.
- **Resetting revokes live sessions.** Each token carries a `token_version` claim
  checked on every request; changing the password bumps the stored version, so a
  refresh cookie captured beforehand stops working on its next use rather than
  lasting out its lifetime.

Email is off by default. With `MAIL_ENABLED=false` the link is returned in the
response as `dev_token` and also written to the log, so the flow is usable locally
with no mail account. `Config.validate()` rejects `MAIL_ENABLED` set without
`MAIL_HOST`, and the reverse, because either mistake means reset emails silently
go nowhere. An address is not required to register.

## Email confirmation

A registration form accepts any address, so anyone could register
`you@example.com`. Without confirmation, password reset would then mail a working
link to your inbox, handing over the account to whoever registered it first.

`POST /account/verify-email/request` sends a confirmation link (the dashboard
prompts for one when an address is present but unconfirmed) and
`POST /account/verify-email/confirm` consumes it. Until the address is confirmed,
`POST /auth/forgot-password` refuses to send anything.

- **The refusal is indistinguishable from success.** Same `202`, same body, same
  wording as an unknown address, so the endpoint still cannot be used to discover
  which addresses are registered or which are confirmed.
- **A failed send does not lose the account.** The address simply stays
  unconfirmed and the user can ask again.
- **Existing accounts start unverified.** The migration backfills `false`, not
  `true`: nobody has proved those addresses, and marking them confirmed would
  preserve exactly the hole the column exists to close.

Confirmation lasts `EMAIL_VERIFICATION_TTL_MINUTES` (24h) and is single-use.
Set `RESET_REQUIRES_VERIFIED_EMAIL=false` to allow resets on unconfirmed
addresses; `Config.validate()` then no longer requires working mail.

## Account control

**Sessions.** `GET /account/sessions` lists the account's devices with a coarse
label (browser family), IP and last-seen time, marking the current one. Each can
be ended individually, or all at once. Revoking the session in use clears this
browser's cookies; revoking another leaves this one working. Lookups are scoped
by `user_id` as well as session id, so a guessed UUID cannot reach a stranger's
session.

**Export.** `GET /account/export` returns every entry as JSON, or as CSV with
`?format=csv`. Both include the factor snapshot, so the file stays meaningful
even after the factor table is updated.

**Deletion.** `DELETE /account/account` removes the account, its history and its
sessions. It requires the password again: a stolen session cookie must not be
enough to destroy someone's data. The UI additionally requires typing `DELETE`.

## Emission factors

Defined in `backend/factors.py` and served by `/footprint/factors`, so the UI never
hardcodes them. Every entry records its region and a **snapshot of the exact
factors used**. That snapshot is what keeps history stable: when the factor table
is updated, old entries keep scoring the way they originally did, instead of being
silently reinterpreted.

Only the electricity factor varies by region. Car emissions use a single global
`0.21 kg CO2e/km` and the diet factors are global medians, so those numbers are
the same everywhere.

`POST /footprint/calculate` also accepts `travel_region`, for driving that happened
somewhere other than the home grid. **It currently changes nothing**, because the
car factor is that same global constant. The API keeps the field and a test pins
the fact, but the form offers no selector for it: a control that silently does
nothing is worse than no control. Region-specific car factors would be a data
decision needing a source; when that happens `backend/tests/test_travel_region.py`
starts failing and says so.

`travel_region` exists because the two do not always match. A UK resident driving
in France pays the UK grid factor for electricity but a different fuel mix for the
driving. It defaults to the home region when omitted.

| Activity    | Factor                       |
| ----------- | ---------------------------- |
| Car travel  | 0.21 kg / km                 |
| Meat meal   | 5.00 kg                      |
| Plant meal  | 2.00 kg                      |
| Electricity | 0.056–0.713 kg / kWh by grid |

Electricity varies by region because grid carbon intensity dominates the result:
the same 200 kWh costs ~11 kg CO₂e in France and ~143 kg in India. Diet factors
are Poore & Nemecek (2018) global medians, shared across regions because the study
does not break them down reliably per country.

`/footprint/summary` recomputes the per-category split from each entry's stored
factor snapshot, so mixed-region histories are reported correctly.

## Tests

```bash
cd backend
python -m pytest tests -q        # 507 tests
ruff check .                    # lint

cd frontend
npm test                        # 175 tests
npm run test:e2e                # 16 real-browser layout tests
npm run typecheck               # tsc --noEmit, strict
npm run lint
npm run build
```

The browser tests need Chromium once: `npm run test:e2e:install`. They serve the
production build themselves and stub the API, so no backend or database is
involved and a backend outage cannot be mistaken for a layout regression.

The suite runs against in-memory SQLite by default. Point `TEST_DATABASE_URL` at
another engine to run the same tests there:

```bash
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/carbon_test pytest tests -q
```

Deliberately not `DATABASE_URL`: the fixtures drop every table between tests, so
sharing the name with the running app would let a test run destroy a real
database. Setting `TEST_DATABASE_URL` has to be a deliberate act.

The schema is built once per run and the rows are cleared between tests, which is
why a full run takes minutes rather than the ~20 it took when every test
recreated the schema.

Backend tests live in `backend/tests/`. `test_regressions.py` is the important
one: each test corresponds to a bug reproduced against an earlier revision of
this code, so it documents behaviour that must not silently regress.
`test_migrations.py` drives the real `flask db` CLI to prove a column can be
widened on a populated database. `test_schema_parity.py` compares the schema
`create_all()` produces against the one the migration chain produces, which is
the gap that let a model drift from its migrations unnoticed.

Frontend tests use Vitest and Testing Library. The pure input parsing lives in
`src/lib/footprint.ts` and is tested there directly, because a DOM test cannot
reach it: `type="number"` inputs reject the very values the parser exists to
catch. Test mocks go through `src/test/api-mock.ts` so `.mockResolvedValue`
stays type-checked.

The `e2e/` tests exist because jsdom implements none of `overflow-x`,
`white-space` or `font-variant-numeric`, so a DOM test cannot tell a rendered
layout apart from a broken one — it can only read the stylesheet source and hope
the rule is not overridden later. Playwright asserts computed values and real box
geometry at 320, 768 and 1440px. It earned its place immediately: the first run
failed on `.columns` using `minmax(320px, 1fr)`, whose grid track cannot shrink
below its minimum, so every 320px-wide phone scrolled horizontally by 20px.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request to `main`:

- **Backend (sqlite)**: `ruff check`, `pip-audit`, `flask db check`, pytest.
- **Backend (postgres)**: the migrations and the full suite against Postgres 16.
- **Frontend**: lint, `npm audit`, `tsc --noEmit`, tests, build.
- **Layout (real browser)**: Chromium, the Playwright suite, and the failure
  report uploaded as an artifact. A separate job because it needs a browser
  download and a live server, and failing the fast checks on that startup cost
  would be misleading.

Five of these steps exist because of specific failures this project had:

`flask db check` autogenerates against a migrated database and fails if the
models have drifted from the migration history, catching a model edited without
a matching revision, which only breaks once deployed.

The Postgres job runs the *whole* suite, not just the migrations. It originally
did not: `conftest.py` hardcoded `SQLALCHEMY_DATABASE_URI = "sqlite://"`, which
overrode `DATABASE_URL`, so 199 tests passed on SQLite inside a job named
"Postgres". The fixture now reads `TEST_DATABASE_URL`. Three faults had already
slipped through for exactly that reason -- unquoted `user` (a reserved word),
`= 0` against a boolean column, and the driver needing a password.

`tsc --noEmit` is separate from `npm run build` because esbuild strips types
without checking them, so a successful build proves nothing about type safety.

Both audit steps exist because "0 known vulnerabilities" was a claim in a commit
message rather than anything enforced.

## Deployment

```bash
pip install -r backend/requirements.txt -r backend/requirements-prod.txt
cd backend && FLASK_APP=app.py flask db upgrade   # before serving traffic
gunicorn wsgi:app
```

`wsgi.py` exposes the app and gunicorn's settings, all overridable by environment
variable:

| Variable                  | Default         | Notes |
| ------------------------- | --------------- | ----- |
| `BIND`                    | `127.0.0.1:8000` | Loopback is correct behind a reverse proxy. Use `0.0.0.0` only with no other network boundary. |
| `WEB_CONCURRENCY`         | 2               | Processes |
| `WEB_THREADS`             | 4               | Threads share one connection pool, so prefer these over more processes |
| `WEB_TIMEOUT`             | 60              | |
| `FORWARDED_ALLOW_IPS`     | `127.0.0.1`     | Must match `PROXY_FIX_X_FOR` |
| `RATELIMIT_STORAGE_URI`   | `memory://`     | **Set this to Redis.** See Rate limiting. |

`PROXY_FIX_X_FOR` defaults to `0`, meaning no proxy is trusted. That matters:
with it unset, a client can send `X-Forwarded-Proto: https` and the app will
believe it is served over TLS, which decides the Secure cookie flag. Set it to
the real number of proxies in front of the app, and keep `FORWARDED_ALLOW_IPS`
in agreement.

## Known limitations

The list of things that used to be here and are now fixed is at the end, with the
commit that fixed each one. What remains is genuinely outstanding.

### Still outstanding

- **Emission factors are static reference values.** Grid mixes shift over time, so
  a factor set is a snapshot of one estimate rather than a live reading. A live
  source such as Electricity Maps would improve this. The per-entry factor
  snapshot means such an update will not rewrite history.
- **Diet factors are global medians, not per-country.** Poore & Nemecek is a global
  dataset and there is no reliable per-country equivalent, so inventing one would
  mean fabricating numbers. Diet factors therefore carry no region dimension at
  all.
- **Only the United States has a measured car factor.** Every other region stands in
  for the documented global default, which is the UK DEFRA fleet average. Those
  figures come from incompatible sources — EEA reports *new* cars under type
  approval, EPA reports a *typical* vehicle, DEFRA reports a fleet average — and
  treating them as equivalent would misrepresent them. The API reports
  `car_km_is_default: true` per region so the gap is machine-readable, and the form
  only offers travel regions whose car factor actually differs. Adding a region
  means adding an attributable figure, not another constant.
- **Rate limits need Redis in production.** The default `memory://` store counts
  per process, so N workers means N times the intended limit. The app now refuses
  to start in production when `memory://` is combined with `WEB_CONCURRENCY` above
  1, and says why. `docker compose up -d` brings up Postgres and Redis locally.
- **`/footprint/summary` is O(entries).** It walks every row to recompute the
  per-category split, because each entry carries its own factor snapshot and
  summing today's factors would misreport the breakdown. Fine for a personal
  tracker; it would need precomputed columns or a cache at a much larger scale.
  (`history()`, by contrast, now has a composite `(user_id, created_at, id)` index
  and is an index scan rather than a sort.)
- **Single-region factor granularity** means a user who moves house keeps one
  factor set per entry rather than a history of grid changes.
- **Sessions are recognisable, not identifiable.** Labels now name the platform —
  "Chrome on Windows" — and anything this account had not used from before is
  flagged. Two laptops on the same network behind the same NAT are still
  indistinguishable, and the IP is only as good as `PROXY_FIX_X_FOR`.
- **No forced password rotation.** There is a breach check against Have I Been
  Pwned when a password is chosen, but no expiry policy. Rotation schedules are
  widely considered to reduce security rather than raise it, so this is left to
  the operator rather than added by default.

### Two-factor authentication

Optional, per account, in Settings. TOTP is implemented on stdlib `hmac`, `hashlib`
and `struct` and verified against the RFC 6238 test vectors.

- A correct password alone never issues a session. With 2FA on, `POST /auth/login`
  returns a five-minute `pending_token` and no cookies; the session is minted only
  once a code verifies against it.
- The seed is **encrypted at rest** with Fernet, keyed from `TOTP_ENCRYPTION_KEY`.
  It cannot be hashed, since verification needs the original bytes, so a plaintext
  column would let anyone holding a database backup mint valid codes. Generate the
  key with:

  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  A malformed key is rejected at startup. An *absent* key is allowed: 2FA is
  opt-in, and the enrolment endpoint answers `503` with an actionable message
  rather than the app refusing to boot for a feature nobody asked for.
- Codes cannot be replayed — the spent time step is recorded and only advances.
  Recovery codes are hashed, single-use, and invalidated by a password reset.
- Disabling requires a current code *and* the password, and revokes every session.
- A wrong TOTP code, a wrong recovery code, a malformed one and a missing one all
  return the same status and body, and both lookups always run, so the response
  does not reveal which path was guessed.

### Fixed since the audit

Each of these was a documented limitation and now is not.

| Limitation | Fix |
| --- | --- |
| Duplicate `sessions` relationship orphaning rows | `Phase 1`, `User.sessions` declared once |
| `logout` 401-ing on an expired cookie and leaking its session row | `Phase 2` |
| `X-Forwarded-For` trusted for the recorded client IP | `Phase 3`, `request.remote_addr` |
| Test config hardcoded SQLite, so Postgres was never exercised | `Phase 4`, `TEST_DATABASE_URL` |
| scrypt over pbkdf2 (21m43s → 1m27s) | `Phase 5` |
| `travel_region` accepted but inert | region-keyed car factors with provenance |
| No breached-password check | HIBP k-anonymity, fails open |
| Per-process rate limits warned about nothing | `Config.validate()` refuses to start |
| `history()` filter-then-sort | composite `(user_id, created_at, id)` index |
| Sessions not readable at a glance | platform labels and familiarity flags |
| Layout asserted from CSS source, not rendering | Playwright, which found a real overflow bug |
| No 2FA | optional TOTP with recovery codes |