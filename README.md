# ICU — Platform Command Layer

`icu.krhub.uk` — the platform command layer for `krhub-uk`. All current and future
components (Universe_SS scripts, IG API client, fintiq, future bolt-ons) register
and report through ICU. Universe_SS is the first tenant.

## Stack

- **Backend:** FastAPI (`main.py` + `icu_registry/` package)
- **DB:** Postgres — database `icu`, app user `icu_app`
- **Auth:** Google OAuth + signed session cookie (`starlette.middleware.sessions`),
  email allowlist. Every route except `/health` and `/auth/*` requires a valid,
  allowlisted session. Machine-to-machine routes (`POST /ingest/status`,
  `GET /control/{id}`) use a shared API key (`X-ICU-Key` header) instead of OAuth.
- **Tunnel:** Cloudflare, serving `icu.krhub.uk`
- **Process manager:** systemd (`icu.service`)
- **venv:** `venv/` (no dot) — `venv/bin/pip install -r requirements.txt` to rebuild

## What it does

Components push status to ICU on every state transition (`POST /ingest/status`).
ICU stores the latest state per component in Postgres, flags components as
`ERROR` if they go silent past their expected schedule (staleness detection,
60s background loop), and fires a Pushover alert on `CRITICAL` results or
staleness breaches. A dashboard at `/` shows every registered component with
live status, Pause/Resume/Run Now controls, and a tailable log panel.

Full behavioural contract (payload schema, validation rules, control model,
run result codes) is defined in `ICU_Contract_Spec_v1.2_BasketA.md` and
`ICU_BasketC_Registry_Decisions_v1.1.md` — not duplicated here to avoid drift;
those are the source of truth for how the API is supposed to behave.

## Layout

```
main.py               FastAPI app: auth, session middleware, OAuth routes,
                      dashboard route ("/"), wires icu_registry routers
                      behind the auth dependency
icu_registry/
  db.py               asyncpg pool
  deps.py             verify_api_key dependency (X-ICU-Key shared secret)
  models.py           Pydantic models, interval_to_seconds helper
  alerts.py           Pushover CRITICAL alert
  staleness.py        60s background loop
  routes/
    registry.py       POST /registry
    status.py         POST /ingest/status  ← API key auth
    control.py        GET/PATCH /control/{id}, POST /trigger/{id}, GET /logs/{id}
                      GET uses API key auth; PATCH uses session auth
    dashboard_api.py  GET /api/components, /api/summary, resume-all, halt-all
static/
  login.html          Served when no valid session
  index.html          The dashboard, served when authenticated
schema.sql            process_registry + status_log DDL
seed_universe_ss.sql  Universe_SS component registration
icu_system.sh         Stop/start/restart/status script for all ICU services
DEPLOY_RUNBOOK.md     Step-by-step deploy instructions, including the
                      mandatory checksum verification step (4a)
requirements.txt      pip freeze of current venv
```

## Endpoints

Session auth on all routes except `/health`, `/auth/*`.
API key auth (`X-ICU-Key` header) on machine-facing routes marked *.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard (or login page if unauthenticated) |
| GET | `/health` | Unauthenticated liveness check |
| GET | `/auth/login`, `/auth/callback`, `/auth/logout` | Google OAuth flow |
| GET | `/api/whoami` | Current session's email |
| POST | `/registry` | Register a new component |
| POST | `/ingest/status` * | Component status push |
| GET | `/control/{id}` * | Read `allowed_to_run` |
| PATCH | `/control/{id}` | Flip `allowed_to_run` (dashboard/human only) |
| POST | `/trigger/{id}` | Run Now — proxies to the component's `endpoint_url/trigger` |
| GET | `/logs/{id}` | Tail the component's log file |
| GET | `/api/components`, `/api/summary` | Dashboard data |
| POST | `/api/resume-all`, `/api/halt-all` | Global controls |

## Auth model — two tiers

| Route type | Auth mechanism |
|---|---|
| Dashboard / human actions | Google OAuth session cookie |
| Machine-to-machine (`/ingest/status`, `GET /control/{id}`) | `X-ICU-Key: <shared secret>` header |

`ICU_API_KEY` must be in `.env` on both the ICU server and any component that
pushes status or polls the control gate.

## Service management

```bash
./icu_system.sh stop      # graceful shutdown: universe_sync_tv → icu → postgres
./icu_system.sh start     # ordered start: postgres → icu → universe_sync_tv
./icu_system.sh restart   # stop + 3s pause + start
./icu_system.sh status    # show active/inactive for all three services
```

All three services are systemd-enabled and auto-start on boot.

## Current tenants

Universe_SS — four components (`universe_ss_eod`, `universe_ss_intraday`,
`universe_ss_weekly`, `universe_ss_sync_tv`).

`universe_ss_sync_tv` is fully wired — status push, control poll, Run Now via
trigger server on port 8001 (`universe_sync_tv.service`).

`eod`, `intraday`, `weekly` — status push and control poll wiring pending in
the Universe_SS repo. Dashboard shows their state passively from cron-pushed
status; Run Now is inert (no `endpoint_url`).

## Onboarding a new component — checklist

1. Add `.env` key `ICU_API_KEY` to the component's environment
2. Import `push_status` and `check_gate` from `icu_client.py` (or equivalent)
3. Add `X-ICU-Key` header to all ICU HTTP calls
4. Wire gate check at script start — fail open (if ICU unreachable, run anyway)
5. Push `RUNNING` status at run start, `IDLE`/`SUCCESS` or `ERROR` at completion
6. If Run Now is needed: expose `POST /trigger` endpoint on the component
7. Register via `POST /registry` (or seed SQL) — include `endpoint_url` if Run Now needed
8. `ON_DEMAND` components must have `endpoint_url` — enforced at registration
9. Smoke test: `curl -H "X-ICU-Key: <key>" https://icu.krhub.uk/control/{component_id}`
10. Verify RUNNING → IDLE state transition appears on dashboard

**Lessons learned (first onboarding — Universe_SS):**
- Machine routes need API key auth, not OAuth — headless processes can't do OAuth
- Status push calls must be in the trigger handler path, not just the `__main__` block
- `ON_DEMAND` + no `endpoint_url` = component that can never be triggered — enforce at registration
- venv naming must be consistent (`venv` not `.venv`) — mismatched shebangs cause silent failures
- Always `sha256sum` files after copy — silent truncation is real (see DEPLOY_RUNBOOK.md §4a)
- Run Now triggers the component in a thread — status push must be inside that thread, not outside it

## Deploying a change

See `DEPLOY_RUNBOOK.md`. Short version: back up, copy files in, **verify
checksums match before touching config** (step 4a — this bit us once, don't
skip it), install any new deps, dry-run with `uvicorn` in the foreground before
trusting systemd, then `./icu_system.sh restart`.

## .env keys

```
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
SESSION_SECRET_KEY
DATABASE_URL
PUSHOVER_ICU_TOKEN
PUSHOVER_USER_KEY
ICU_API_KEY
```

## ICU backlog

| Item | Detail |
|---|---|
| `PATCH /registry/{component_id}` | No API route to update registry rows — direct SQL used as one-time unblock |
| `MANUAL` schedule type | `universe_ss_sync_tv` registered as `1MO` workaround — needs a proper MANUAL type |
| Pause vs Halt distinction | Both use `allowed_to_run` boolean — no ICU bookkeeping distinguishes them |
| Global pause mechanism | Toggle all components simultaneously — not yet designed |
