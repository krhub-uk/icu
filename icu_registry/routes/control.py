import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
import httpx
from icu_registry.db import get_pool
from icu_registry.models import ControlPatchIn

router = APIRouter()
logger = logging.getLogger("icu.control")


@router.get("/control/{component_id}")
async def get_control(component_id: str):
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT allowed_to_run FROM process_registry WHERE component_id = $1", component_id
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"component_id '{component_id}' not registered")
    return {"allowed_to_run": row["allowed_to_run"]}


@router.patch("/control/{component_id}")
async def patch_control(component_id: str, payload: ControlPatchIn):
    pool = get_pool()
    row = await pool.fetchrow(
        """
        UPDATE process_registry
        SET allowed_to_run = $2, updated_at = NOW()
        WHERE component_id = $1
        RETURNING component_id, allowed_to_run, updated_at
        """,
        component_id,
        payload.allowed_to_run,
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"component_id '{component_id}' not registered")
    return dict(row)


@router.post("/trigger/{component_id}")
async def trigger_component(component_id: str):
    pool = get_pool()
    reg = await pool.fetchrow(
        "SELECT endpoint_url, allowed_to_run FROM process_registry WHERE component_id = $1",
        component_id,
    )
    if not reg:
        raise HTTPException(status_code=404, detail=f"component_id '{component_id}' not registered")

    if not reg["allowed_to_run"]:
        raise HTTPException(status_code=409, detail="component is paused (allowed_to_run=false)")

    if not reg["endpoint_url"]:
        raise HTTPException(status_code=422, detail="component has no endpoint_url - cannot trigger")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{reg['endpoint_url']}/trigger")
        return {"triggered": True, "component_status_code": resp.status_code, "component_response": resp.text}
    except httpx.HTTPError as exc:
        logger.error("Trigger call failed for %s: %s", component_id, exc)
        raise HTTPException(status_code=502, detail=f"could not reach component endpoint: {exc}") from exc


@router.get("/logs/{component_id}")
async def get_logs(component_id: str, lines: int = 50):
    pool = get_pool()
    reg = await pool.fetchrow(
        "SELECT log_path FROM process_registry WHERE component_id = $1", component_id
    )
    if not reg:
        raise HTTPException(status_code=404, detail=f"component_id '{component_id}' not registered")

    log_path = Path(reg["log_path"])
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"log file not found: {log_path}")

    try:
        with log_path.open("r", errors="replace") as f:
            all_lines = f.readlines()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not read log file: {exc}") from exc

    tail = all_lines[-lines:] if lines > 0 else all_lines
    return {"component_id": component_id, "log_path": str(log_path), "lines": [l.rstrip("\n") for l in tail]}
