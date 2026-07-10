"""
ICU Dashboard — Step 4
Adds /api/control/pause, /api/control/resume, /api/control/halt.

Two-stage safety model (whole-process, matching the current single
.env/.pid pair — per-script control is a V4.9 spec item, not built here):

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
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pathlib import Path

app = FastAPI(title="ICU Dashboard")

STATIC_DIR = Path(__file__).parent / "static"

PID_FILE = Path("/opt/dev/universe_SS/.pid")
ENV_FILE = Path("/opt/dev/universe_SS/.env")

LOG_DIR = Path("/var/log/portfolio")
DEFAULT_LOG = "intraday.log"
MAX_LINES = 500  # hard ceiling regardless of what's requested


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


@app.post("/api/control/pause")
def api_control_pause():
    set_universe_process_flag("N")
    return {"result": "paused", "state": get_universe_state()}


@app.post("/api/control/resume")
def api_control_resume():
    set_universe_process_flag("Y")
    return {"result": "resumed", "state": get_universe_state()}


@app.post("/api/control/halt")
def api_control_halt():
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
