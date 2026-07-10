"""
ICU Dashboard — Step 2
Adds /api/state, reading Universe_SS process state from the filesystem.
No coupling to Universe_SS code — just reads .pid / .env by convention.
"""

import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path

app = FastAPI(title="ICU Dashboard")

STATIC_DIR = Path(__file__).parent / "static"

PID_FILE = "/opt/dev/universe_SS/.pid"
ENV_FILE = "/opt/dev/universe_SS/.env"


def get_universe_state() -> str:
    if os.path.exists(PID_FILE):
        return "RUNNING"
    try:
        with open(ENV_FILE) as f:
            if "UNIVERSE_PROCESS=N" in f.read():
                return "PAUSED"
    except FileNotFoundError:
        # .env missing entirely — treat as IDLE rather than erroring
        pass
    return "IDLE"


@app.get("/", response_class=HTMLResponse)
def read_root():
    html_path = STATIC_DIR / "index.html"
    return html_path.read_text()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/state")
def api_state():
    return {"state": get_universe_state()}
