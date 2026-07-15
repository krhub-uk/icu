"""
ICU — Platform Command Layer
Step 6: replaces the Universe_SS-specific single-process control model
(UNIVERSE_PROCESS flag in .env + SIGTERM via .pid) with the generic
multi-component process_registry in Postgres. Auth (Google OAuth,
signed session cookie, email allowlist) from Step 5 is unchanged and
now gates every ICU route, not just the old Universe_SS ones.

NOTE: Universe_SS's own script still needs its poll logic updated to
call GET /control/{component_id} instead of reading its local .env
flag — that change lives in the Universe_SS repo, not here. Until
that ships, Pause/Run Now update the ICU database correctly but the
running Universe_SS process won't react to them yet.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv

# .env lives alongside this file (icu repo root), separate from
# Universe_SS's own .env which we only ever read, never write our
# secrets into.
load_dotenv(Path(__file__).parent / ".env")

from icu_registry.db import init_pool, close_pool
from icu_registry.staleness import staleness_loop
from icu_registry.routes import registry, status, control, dashboard_api

GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
SESSION_SECRET_KEY = os.environ["SESSION_SECRET_KEY"]

# Allowlist — only these emails may hold a session. Extend this list
# (or move to .env as a comma-separated var) if more people ever need
# access; for now it's just Kyle per spec's personal-scale assumption.
ALLOWED_EMAILS = {"kyle.reed.uk@gmail.com"}

STATIC_DIR = Path(__file__).parent / "static"


def require_session(request: Request) -> str:
    """Returns the logged-in email, or raises 401 if no valid session.
    Used as a FastAPI dependency on every ICU registry route below."""
    email = request.session.get("email")
    if not email or email not in ALLOWED_EMAILS:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return email


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    task = asyncio.create_task(staleness_loop())
    yield
    task.cancel()
    await close_pool()


app = FastAPI(title="ICU — Platform Command Layer", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# All ICU registry routes require a valid, allowlisted session.
_auth_dep = [Depends(require_session)]
app.include_router(registry.router, dependencies=_auth_dep)
app.include_router(status.router, dependencies=_auth_dep)
app.include_router(control.router, dependencies=_auth_dep)
app.include_router(dashboard_api.router, dependencies=_auth_dep)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
