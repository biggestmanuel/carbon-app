# carbon-app

A full-stack app for tracking personal carbon emissions. Users register and log in,
log their weekly activity (driving, electricity, meals), and get a kg CO₂e estimate
built from per-category emission factors, adjusted for their region's grid mix.

## Stack

| Layer    | Tech                                              |
| -------- | ------------------------------------------------- |
| Backend  | Flask 3, SQLAlchemy, Flask-JWT-Extended, Flask-Cors, Flask-Migrate, Flask-Limiter |
| Database | SQLite by default (any SQLAlchemy URL via `DATABASE_URL`) |
| Frontend | React 19 + Vite 8, axios                         |

## Layout

```
backend/
  app.py            application factory + error handlers
  config.py         env-driven config, validated at startup
  extensions.py     db / jwt / migrate / limiter singletons (breaks the models<->app import cycle)
  factors.py        region-aware emission factor data
  models.py         User, Footprint
  routes/
    auth.py         register, login, refresh, logout, me, forgot-password, reset-password
    footprint.py    calculate, history, summary, factors
  passwords.py      single-use reset tokens, stored hashed
  mail.py           pluggable mailer: console in dev, SMTP in production
  migrations/       Alembic history; `flask db upgrade` owns the schema
  tests/            pytest suite
frontend/
  src/
    api.js          axios instance, withCredentials, transparent token refresh, 401 handling
    lib/footprint.js  field definitions, input parsing, factor lookup (pure, unit-tested)
    App.jsx         session state, token verification, expiry handling
    components/     Login, Register, ForgotPassword, ResetPassword, Dashboard,
                    FootprintForm, Summary, HistoryList
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
| `RATELIMIT_STORAGE_URI`    | `memory://`            | Use Redis for multi-process deployments    |
| `FLASK_ENV`                | `development`          | `production` enables the safety checks     |

`Config.validate()` refuses to start in production when the secrets are still
placeholders, when the cookie is not Secure, when `CORS_ORIGINS` is `*`, or when
`AUTO_CREATE_TABLES` is on. It reports every problem at once rather than the first.

Frontend config is `VITE_API_URL` in `frontend/.env` (see `.env.example`).

## Sessions

Access and refresh tokens are set as **httpOnly cookies**, so page scripts and XSS
payloads cannot read them. Nothing is stored in `localStorage`.

- `POST /auth/login` sets both cookies and returns only the username.
- `POST /auth/logout` clears them and is idempotent.
- `POST /auth/refresh` trades the refresh cookie for a new access cookie.
- On a `401`, the frontend tries one refresh and replays the request, so the
  30 minute access lifetime is not a hard sign-out. If the refresh also fails,
  the app logs out cleanly rather than stranding the user on a dead dashboard.
- A password change invalidates every existing session via the `token_version`
  claim described under Password reset.
- `JWT_COOKIE_CSRF_PROTECT` is off because every state-changing request is a JSON
  POST from an allowlisted origin, which a cross-site form cannot forge and a
  cross-origin fetch cannot pass CORS preflight for. Turn it on if the API is
  ever called from a context that does allow those.

## Rate limiting

Per-route limits via Flask-Limiter, keyed by client IP:

| Route                  | Default limit |
| ---------------------- | ------------- |
| `POST /auth/login`     | 10 per minute |
| `POST /auth/register`  | 5 per hour    |
| `POST /footprint/calculate` | 120 per minute |
| `GET /footprint/history`, `/footprint/summary` | 120 per minute |

Breaches return `429` with a JSON body and `Retry-After`. The default
`memory://` storage resets on restart and is **not shared between workers**; set
`RATELIMIT_STORAGE_URI` to Redis before running more than one process, otherwise
the effective limit is multiplied by the worker count.

## API

All `/footprint/*` routes except `/footprint/factors` require a session cookie.

| Method | Path                     | Purpose                                  |
| ------ | ------------------------ | ---------------------------------------- |
| POST   | `/auth/register`         | Create an account; `email` optional      |
| POST   | `/auth/login`            | Sets cookies, returns `username`         |
| POST   | `/auth/refresh`          | New access cookie from the refresh cookie|
| POST   | `/auth/logout`           | Clears cookies                           |
| GET    | `/auth/me`               | Confirm a session; email is masked       |
| POST   | `/auth/forgot-password`  | Email a reset link; never reveals whether the address exists |
| POST   | `/auth/reset-password`   | Consume a token and set a new password   |
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
go nowhere. Email is not verified, and an address is not required to register.

## Emission factors

Defined in `backend/factors.py` and served by `/footprint/factors`, so the UI never
hardcodes them. Every entry records its region, its travel region and a **snapshot
of the exact factors used**. That snapshot is what keeps history stable: when the
factor table is updated, old entries keep scoring the way they originally did,
instead of being silently reinterpreted.

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
python -m pytest tests -q        # 163 tests
ruff check .                    # lint

cd frontend
npm test                        # 86 tests
npm run lint
npm run build
```

Backend tests live in `backend/tests/`. `test_regressions.py` is the important
one: each test corresponds to a bug reproduced against an earlier revision of
this code, so it documents behaviour that must not silently regress.
`test_migrations.py` drives the real `flask db` CLI to prove a column can be
widened on a populated database.

Frontend tests use Vitest and Testing Library. `src/test/api.test.js` covers the
credentialed request layer and the transparent refresh, which was the part
previously verified only by hand.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request to `main`:

- **Backend**: `ruff check`, `flask db check`, then pytest.
- **Frontend**: `npm test`, then `npm run build`.

`flask db check` autogenerates against a migrated database and fails if the
models have drifted from the migration history. That catches the failure this
project started with: a model edited without a matching revision, which only
breaks once deployed.

## Known limitations

- **Emission factors are static reference values.** Grid mixes shift over time and
  are not region-specific below the country level. Wire in a live data source such
  as Electricity Maps if that precision matters. The factor snapshot on each entry
  means such an update will not rewrite history.
- **Email addresses are not verified.** A user can register someone else's address,
  which means a reset link could in principle reach the wrong inbox. Full fix is a
  confirmation step before the address is trusted.
- **Diet factors are global medians, not per-country.** Car factors are a single
  global average, so fuel mix differences between countries are not modelled.
- **No account deletion or data export.** There is no way for a user to erase their
  history or take it elsewhere.
- **Rate-limit storage defaults to memory://**, which resets on restart and is not
  shared between workers. Set `RATELIMIT_STORAGE_URI` to Redis before running more
  than one process, or the effective limit multiplies by worker count.
- **Sessions are not revocable per device.** A password change kills every session,
  but there is no "log out everywhere" or per-device list.
- **No TypeScript or type checking.** ESLint and 86 tests cover behaviour, but
  nothing checks the shapes crossing the API boundary at compile time.
- **CI runs migrations against SQLite only.** A green pipeline proves the schema
  applies to an empty database, not that it will apply cleanly to production data.