"""
ICU Dashboard — Step 3
Adds /api/logs — tails a selected log file from /var/log/portfolio/.
Filenames are validated against an allowlist derived from the directory
listing, so arbitrary path traversal isn't possible via the query param.
"""

import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pathlib import Path

app = FastAPI(title="ICU Dashboard")

STATIC_DIR = Path(__file__).parent / "static"

PID_FILE = "/opt/dev/universe_SS/.pid"
ENV_FILE = "/opt/dev/universe_SS/.env"

LOG_DIR = Path("/var/log/portfolio")
DEFAULT_LOG = "intraday.log"
MAX_LINES = 500  # hard ceiling regardless of what's requested


def get_universe_state() -> str:
    if os.path.exists(PID_FILE):
        return "RUNNING"
    try:
        with open(ENV_FILE) as f:
            if "UNIVERSE_PROCESS=N" in f.read():
                return "PAUSED"
    except FileNotFoundError:
        pass
    return "IDLE"


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
def read_root():
    html_path = STATIC_DIR / "index.html"
    return html_path.read_text()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/state")
def api_state():
    return {"state": get_universe_state()}


@app.get("/api/logs/list")
def api_logs_list():
    return {"files": list_log_files(), "default": DEFAULT_LOG}


@app.get("/api/logs")
def api_logs(file: str = Query(default=DEFAULT_LOG), lines: int = Query(default=100)):
    available = list_log_files()
    if file not in available:
        raise HTTPException(status_code=400, detail=f"'{file}' is not a recognised log file")

    log_path = LOG_DIR / file
    try:
        tail = tail_file(log_path, lines)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"'{file}' not found")

    return {"file": file, "lines": tail}
