# ICU — Platform Command Layer

`icu.krhub.uk` — the platform command layer for `krhub-uk`. All current and future
components (Universe_SS scripts, IG API client, fintiq, future bolt-ons) register
and report through ICU. Universe_SS is the first tenant.

## Stack

- **Backend:** FastAPI (`main.py` + `icu_registry/` package)
- **DB:** Postgres — database `icu`, app user `icu_app`
- **Auth:** Google OAuth + signed session cookie (`starlette.middleware.sessions`),
  email allowlist. Every route except `/health` and `/auth/*` requires a valid,
  allowlisted session.
- **Tunnel:** Cloudflare, serving `icu.krhub.uk`
- **Process manager:** systemd (`icu.service`)

## What it does

Components push status to ICU on every state transition (`POST /ingest/status`).
ICU stores the latest state per component in Postgres, flags components as
`ERROR` if they go silent past their expected schedule (staleness detection,
60s background loop), and fires a Pushover alert on `CRITICAL` results or
staleness breaches. A dashboard at `/` shows every registered component with
live status, Pause/Resume/Run Now controls, and a tailable log panel.

Full behavioural contract (payload schema, validation rules, control model,
run result codes) is defined in `ICU_Contract_Spec_v1.2_BasketA.md` and
`ICU_BasketC_Registry_Decisions_v1.2.md` — not duplicated here to avoid drift;
those are the source of truth for how the API is supposed to behave.

## Layout

```
main.py                    FastAPI app: auth, session middleware, OAuth routes,
                            dashboard route ("/"), wires icu_registry routers
                            behind the auth dependency
icu_registry/
  db.py                     asyncpg pool
  models.py                 Pydantic models, interval_to_seconds helper
  alerts.py                 Pushover CRITICAL alert
  staleness.py              60s background loop
  routes/
    registry.py             POST /registry
    status.py                POST /ingest/status
    control.py                GET/PATCH /control/{id}, POST /trigger/{id}, GET /logs/{id}
    dashboard_api.py           GET /api/components, /api/summary, resume-all, halt-all
static/
  login.html                Served when no valid session
  index.html                 The dashboard, served when authenticated
schema.sql                  process_registry + status_log DDL
seed_universe_ss.sql         Universe_SS component registration
DEPLOY_RUNBOOK.md            Step-by-step deploy instructions, including the
                            mandatory checksum verification step (4a)
```

## Endpoints

All behind session auth except `/health`, `/auth/*`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard (or login page if unauthenticated) |
| GET | `/health` | Unauthenticated liveness check |
| GET | `/auth/login`, `/auth/callback`, `/auth/logout` | Google OAuth flow |
| GET | `/api/whoami` | Current session's email |
| POST | `/registry` | Register a new component |
| POST | `/ingest/status` | Component status push |
| GET/PATCH | `/control/{id}` | Read/flip `allowed_to_run` |
| POST | `/trigger/{id}` | Run Now — proxies to the component's `endpoint_url/trigger` |
| GET | `/logs/{id}` | Tail the component's log file |
| GET | `/api/components`, `/api/summary` | Dashboard data |
| POST | `/api/resume-all`, `/api/halt-all` | Global controls |

## Current tenants

Universe_SS — four components (`universe_ss_eod`, `universe_ss_intraday`,
`universe_ss_weekly`, `universe_ss_sync_tv`), all cron/manual-driven with no
HTTP endpoint of their own (`endpoint_url = NULL` throughout). ICU tracks their
status and logs passively; Run Now and the staleness poll-on-wake are inert for
these. See `ICU_Cowork_Handback_v1.0.md` for the full rationale and what's
still outstanding on the Universe_SS side (status push, control poll — both
separate work in the Universe_SS repo, not blocking here).

## Deploying a change

See `DEPLOY_RUNBOOK.md`. Short version: back up, copy files in, **verify
checksums match before touching config** (step 4a — this bit us once, don't
skip it), install any new deps, dry-run with `uvicorn` in the foreground before
trusting systemd, then `systemctl restart icu.service`.

## .env keys

```
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
SESSION_SECRET_KEY
DATABASE_URL
PUSHOVER_ICU_TOKEN
PUSHOVER_USER_KEY
```
