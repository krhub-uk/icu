from fastapi import APIRouter, HTTPException
from icu_registry.db import get_pool

router = APIRouter()

STATES = ("RUNNING", "IDLE", "PAUSED", "ERROR", "HALTED")


@router.get("/api/components")
async def list_components():
    """Latest status per component joined with registry - powers the dashboard cards."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT r.component_id, r.display_name, r.log_path, r.github_repo_tag,
               r.schedule_string, r.expected_interval, r.allowed_to_run, r.endpoint_url,
               s.status, s.last_run_utc, s.last_run_result, s.version, s.received_at, s.message
        FROM process_registry r
        LEFT JOIN LATERAL (
            SELECT * FROM status_log sl
            WHERE sl.component_id = r.component_id
            ORDER BY sl.received_at DESC
            LIMIT 1
        ) s ON true
        ORDER BY r.display_name
        """
    )
    components = []
    for row in rows:
        d = dict(row)
        if d["status"] is None:
            d["status"] = "PAUSED" if not d["allowed_to_run"] else "IDLE"
        if d.get("expected_interval") is not None:
            d["expected_interval"] = str(d["expected_interval"])
        if d.get("received_at") is not None:
            d["received_at"] = d["received_at"].isoformat()
        if d.get("last_run_utc") is not None:
            d["last_run_utc"] = d["last_run_utc"].isoformat()
        components.append(d)
    return components


@router.get("/api/summary")
async def summary():
    components = await list_components()
    counts = {s: 0 for s in STATES}
    for c in components:
        if c["status"] in counts:
            counts[c["status"]] += 1
    return counts


@router.post("/api/resume-all")
async def resume_all():
    pool = get_pool()
    rows = await pool.fetch(
        """
        UPDATE process_registry
        SET allowed_to_run = true, updated_at = NOW()
        WHERE allowed_to_run = false
        RETURNING component_id
        """
    )
    return {"resumed": [r["component_id"] for r in rows]}


@router.post("/api/halt-all")
async def halt_all():
    """PATCH allowed_to_run=false for all + best-effort SIGTERM via pidfile for RUNNING components."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        UPDATE process_registry
        SET allowed_to_run = false, updated_at = NOW()
        RETURNING component_id
        """
    )
    return {"halted": [r["component_id"] for r in rows], "note": "SIGTERM via pidfile not wired - pidfile convention TBD"}
