"""
ICU Dashboard — Step 1
Minimal FastAPI app serving a single static HTML page.
No auth, no data, no process control yet — just proving the pipe works
end to end: FastAPI -> uvicorn -> nginx -> Cloudflare Tunnel -> icu.krhub.uk
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path

app = FastAPI(title="ICU Dashboard")

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
def read_root():
    html_path = STATIC_DIR / "index.html"
    return html_path.read_text()


@app.get("/health")
def health():
    return {"status": "ok"}
