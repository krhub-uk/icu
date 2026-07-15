# ICU — Deploy Runbook (Postgres → live)

Run all of this over SSH on `ubuntu-server`. Everything below assumes the repo lives at `/opt/dev/icu/` and the service is managed by systemd.

## 0. Find your actual service name
```bash
systemctl list-units --type=service | grep -i icu
```
Substitute whatever comes back (e.g. `icu.service`) everywhere you see `<icu-service>` below.

---

## 1. Postgres install
```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

## 2. Create the `icu` database + app user
```bash
sudo -u postgres psql
```
```sql
CREATE USER icu_app WITH PASSWORD 'choose-a-strong-password';
CREATE DATABASE icu OWNER icu_app;
\q
```

---

## 3. Back up what's live before touching it
```bash
cd /opt/dev/icu
sudo systemctl stop <icu-service>          # stop the service before editing its files
cp main.py main.py.bak-$(date +%s)
cp -r static static.bak-$(date +%s)
cp .env .env.bak-$(date +%s)
```

## 4. Copy the new code in
From wherever you pulled/cloned the `icu_deploy/` output (or `git pull` if you've committed it to `krhub-uk/icu`):
```bash
cp icu_deploy/main.py /opt/dev/icu/main.py
cp -r icu_deploy/icu_registry /opt/dev/icu/icu_registry
cp icu_deploy/index.html /opt/dev/icu/static/index.html
cp icu_deploy/schema.sql /opt/dev/icu/schema.sql
cp icu_deploy/seed_universe_ss.sql /opt/dev/icu/seed_universe_ss.sql
```
Your existing `login.html`, `.env`, `.gitignore`, `.git` — untouched by this.

### 4a. Verify every copy landed intact — don't skip this
Files can silently truncate or corrupt in transit (this bit us on `index.html` during the first deploy of this build — the copy looked fine, the file just quietly cut off mid-script with no error from `cp`). Before restarting anything, checksum the source and destination for every file you just copied:
```bash
sha256sum icu_deploy/main.py icu_deploy/index.html icu_deploy/schema.sql icu_deploy/seed_universe_ss.sql \
          icu_deploy/icu_registry/*.py icu_deploy/icu_registry/routes/*.py
sha256sum /opt/dev/icu/main.py /opt/dev/icu/static/index.html /opt/dev/icu/schema.sql /opt/dev/icu/seed_universe_ss.sql \
          /opt/dev/icu/icu_registry/*.py /opt/dev/icu/icu_registry/routes/*.py
```
Every hash in the first block must exactly match its counterpart in the second. If even one differs, re-copy that specific file and check again — don't proceed to step 5 until every hash matches. This is the single check that would have caught the `index.html` bug immediately instead of an hour of browser debugging.

## 5. Add the new `.env` keys (don't overwrite the file)
Open `/opt/dev/icu/.env` and append:
```
DATABASE_URL=postgresql://icu_app:choose-a-strong-password@localhost:5432/icu
PUSHOVER_ICU_TOKEN=<new ICU app token>
PUSHOVER_USER_KEY=<existing, same as Universe_SS>
```
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET_KEY` stay as they are.

## 6. Install the new Python deps into the existing venv
```bash
source venv/bin/activate
pip install asyncpg httpx python-dotenv
deactivate
```

## 7. Load the schema, then seed Universe_SS
```bash
psql "postgresql://icu_app:choose-a-strong-password@localhost:5432/icu" -f schema.sql
```
`seed_universe_ss.sql` already reflects the real layout (`eod`, `intraday`, `weekly`, `sync_engine_tv` — `NULL` endpoints, log paths under `/var/log/portfolio/`). Re-check it's still accurate if the cron schedule or log locations have changed since this was written. Then:
```bash
psql "postgresql://icu_app:choose-a-strong-password@localhost:5432/icu" -f seed_universe_ss.sql
```

## 8. Dry run before trusting systemd with it
```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```
Watch the console. You want to see it start clean with no tracebacks — the app connects to Postgres and kicks off the staleness loop on startup, so this is where a bad `DATABASE_URL` or missing table would surface immediately. Ctrl+C once you've confirmed it's healthy.

## 9. Flip the switch
```bash
sudo systemctl daemon-reload   # only needed if you edited the unit file itself
sudo systemctl start <icu-service>
sudo systemctl status <icu-service>
```

## 10. Verify
```bash
curl -s https://icu.krhub.uk/health
```
Then in a browser: hit `https://icu.krhub.uk/`, confirm it bounces to Google login (or straight to the dashboard if you've got a session already), and once in, the dashboard loads with the two Universe_SS rows from the seed showing IDLE/PAUSED (no status pushed yet, so that's expected — see the note on this in the README about first-load display).

Optional: push a test status payload to confirm ingest works end-to-end —
```bash
curl -X POST https://icu.krhub.uk/ingest/status \
  -H "Content-Type: application/json" \
  --cookie "session=<your session cookie>" \
  -d '{"schema_version":"1.0","component_id":"universe_ss_enrichment","status":"IDLE","last_run_utc":"2026-07-14T06:00:01Z","last_run_result":"SUCCESS"}'
```
(`/ingest/status` sits behind the same session gate as everything else, so you'd need a valid cookie for this — easier to just watch it happen naturally next time the script runs and pushes on its own, if it already does. If Universe_SS doesn't push status yet, that's a separate follow-up, not required to get ICU live.)

---

## If something goes wrong
```bash
sudo systemctl status <icu-service>
sudo journalctl -u <icu-service> -n 100 --no-pager
```
Roll back fast if needed:
```bash
sudo systemctl stop <icu-service>
cp main.py.bak-<timestamp> main.py
rm -rf icu_registry
cp static.bak-<timestamp>/index.html static/index.html
cp .env.bak-<timestamp> .env
sudo systemctl start <icu-service>
```
