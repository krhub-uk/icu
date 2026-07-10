"""
ICU Dashboard — Step 5
Adds Google OAuth login: /auth/login, /auth/callback, /auth/logout,
plus an email allowlist and a signed session cookie. Every /api/* and
/ route (except the auth routes and /health) now requires a valid
session belonging to an allowlisted email.

Two-stage safety model for controls (whole-process, matching the
current single .env/.pid pair — per-script control is a V4.9 spec
item, not built here):

  PAUSE  -> sets UNIVERSE_PROCESS=N in .env. Does NOT kill anything.
            The running script is expected to check this flag between
            iterations and exit its own loop cleanly, so any mid-flight
            file write gets a chance to finish naturally.
  RESUME -> sets UNIVERSE_PROCESS=Y in .env.
  HALT   -> only enabled once already paused. Sends SIGTERM directly to
            the PID in .pid. This is the emergency stop for a runaway
            process hammering IG/TV with bad data — immediate, no
            grace period, because protecting production from a
            corrupted API loop matters more than a clean shutdown here.
"""

import os
import signal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv

# .env lives alongside this file (icu repo root), separate from
# Universe_SS's own .env which we only ever read, never write our
# secrets into.
load_dotenv(Path(__file__).parent / ".env")

GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
SESSION_SECRET_KEY = os.environ["SESSION_SECRET_KEY"]

# Allowlist — only these emails may hold a session. Extend this list
# (or move to .env as a comma-separated var) if more people ever need
# access; for now it's just Kyle per spec's personal-scale assumption.
ALLOWED_EMAILS = {"kyle.reed.uk@gmail.com"}

app = FastAPI(title="ICU Dashboard")

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

STATIC_DIR = Path(__file__).parent / "static"

PID_FILE = Path("/opt/dev/universe_SS/.pid")
ENV_FILE = Path("/opt/dev/universe_SS/.env")

LOG_DIR = Path("/var/log/portfolio")
DEFAULT_LOG = "intraday.log"
MAX_LINES = 500  # hard ceiling regardless of what's requested


def require_session(request: Request) -> str:
    """Returns the logged-in email, or raises 401 if no valid session."""
    email = request.session.get("email")
    if not email or email not in ALLOWED_EMAILS:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return email


def get_universe_state() -> str:
    if PID_FILE.exists():
        return "RUNNING"
    try:
        if "UNIVERSE_PROCESS=N" in ENV_FILE.read_text():
            return "PAUSED"
    except FileNotFoundError:
        pass
    return "IDLE"


def set_universe_process_flag(value: str):
    """Rewrite UNIVERSE_PROCESS=Y/N in .env, preserving every other line."""
    assert value in ("Y", "N")
    if not ENV_FILE.exists():
        raise HTTPException(status_code=500, detail=".env not found on server")

    lines = ENV_FILE.read_text().splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("UNIVERSE_PROCESS="):
            new_lines.append(f"UNIVERSE_PROCESS={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"UNIVERSE_PROCESS={value}")

    ENV_FILE.write_text("\n".join(new_lines) + "\n")


def list_log_files() -> list[str]:
    """Only plain .log files (not rotated .gz archives) are tailable."""
    if not LOG_DIR.exists():
        return []
    return sorted(
        f.name for f in LOG_DIR.iterdir()
        if f.is_file() and f.suffix == ".log"
    )


def tail_file(path: Path, n: int) -> list[str]:
    """Read the last n lines of a file without loading the whole thing
    into memory for large logs — reads in chunks from the end."""
    n = max(1, min(n, MAX_LINES))
    avg_line_bytes = 200
    chunk_size = n * avg_line_bytes
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        file_size = f.tell()
        read_size = min(chunk_size, file_size)
        f.seek(file_size - read_size)
        data = f.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-n:]


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    email = request.session.get("email")
    if not email or email not in ALLOWED_EMAILS:
        html_path = STATIC_DIR / "login.html"
    else:
        html_path = STATIC_DIR / "index.html"
    return html_path.read_text()


@app.get("/health")
def health():
    # Deliberately unauthenticated — this is the plumbing check used by
    # Step 1's external confirmation and any future uptime monitoring.
    return {"status": "ok"}


@app.get("/auth/login")
async def auth_login(request: Request):
    redirect_uri = "https://icu.krhub.uk/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo or "email" not in userinfo:
        raise HTTPException(status_code=400, detail="Google did not return an email")

    email = userinfo["email"]
    if email not in ALLOWED_EMAILS:
        # Don't create a session — bounce to a plain 403 rather than
        # silently letting an unrecognised Google account in.
        return JSONResponse(status_code=403, content={"detail": f"{email} is not authorised"})

    request.session["email"] = email
    return RedirectResponse(url="/")


@app.get("/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")


@app.get("/api/whoami")
def api_whoami(request: Request):
    email = request.session.get("email")
    if not email or email not in ALLOWED_EMAILS:
        return JSONResponse(status_code=401, content={"authenticated": False})
    return {"authenticated": True, "email": email}


@app.get("/api/state")
def api_state(request: Request):
    require_session(request)
    return {"state": get_universe_state()}


@app.get("/api/logs/list")
def api_logs_list(request: Request):
    require_session(request)
    return {"files": list_log_files(), "default": DEFAULT_LOG}


@app.get("/api/logs")
def api_logs(request: Request, file: str = Query(default=DEFAULT_LOG), lines: int = Query(default=100)):
    require_session(request)
    available = list_log_files()
    if file not in available:
        raise HTTPException(status_code=400, detail=f"'{file}' is not a recognised log file")

    log_path = LOG_DIR / file
    try:
        tail = tail_file(log_path, lines)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"'{file}' not found")

    return {"file": file, "lines": tail}


@app.post("/api/control/pause")
def api_control_pause(request: Request):
    require_session(request)
    set_universe_process_flag("N")
    return {"result": "paused", "state": get_universe_state()}


@app.post("/api/control/resume")
def api_control_resume(request: Request):
    require_session(request)
    set_universe_process_flag("Y")
    return {"result": "resumed", "state": get_universe_state()}


@app.post("/api/control/halt")
def api_control_halt(request: Request):
    require_session(request)
    # Only allowed once already paused — the pill must already read PAUSED
    # (i.e. UNIVERSE_PROCESS=N) before we'll send a kill signal.
    if get_universe_state() != "PAUSED":
        raise HTTPException(
            status_code=409,
            detail="Halt is only available after Pause has been triggered."
        )
    if not PID_FILE.exists():
        raise HTTPException(status_code=404, detail="No .pid file — nothing running to halt.")

    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        raise HTTPException(status_code=500, detail=".pid file content is not a valid integer")

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        # Process already gone — clean up the stale pid file
        PID_FILE.unlink(missing_ok=True)
        return {"result": "halted", "detail": "process already exited, .pid cleared", "state": get_universe_state()}
    except PermissionError:
        raise HTTPException(status_code=500, detail=f"Permission denied sending SIGTERM to PID {pid}")

    return {"result": "halted", "detail": f"SIGTERM sent to PID {pid}", "state": get_universe_state()}
