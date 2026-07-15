import json
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from icu_registry.db import get_pool
from icu_registry.models import STATUS_VALUES, RESULT_VALUES, TRIGGER_VALUES
from icu_registry.alerts import send_pushover_alert
from fastapi import APIRouter, Depends, HTTPException, Request
from icu_registry.deps import verify_api_key

router = APIRouter()
logger = logging.getLogger("icu.status")

SCHEMA_VERSION = "1.0"


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.post("/ingest/status", status_code=202, dependencies=[Depends(verify_api_key)])
async def ingest_status(request: Request):
    body = await request.json()

    schema_version = body.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        logger.warning("Rejected status push: schema_version mismatch (%r)", schema_version)
        raise HTTPException(status_code=400, detail=f"schema_version must be '{SCHEMA_VERSION}'")

    component_id = body.get("component_id")
    if not component_id:
        logger.warning("Rejected status push: missing component_id")
        raise HTTPException(status_code=400, detail="component_id is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        registered = await conn.fetchrow(
            "SELECT component_id FROM process_registry WHERE component_id = $1", component_id
        )
        if not registered:
            logger.warning("Rejected status push: unknown component_id UNKNOWN=%s", component_id)
            raise HTTPException(status_code=400, detail=f"component_id '{component_id}' is not registered")

        status = body.get("status")
        if status not in STATUS_VALUES:
            logger.warning("Invalid/missing status %r for %s - forcing ERROR", status, component_id)
            status = "ERROR"

        timestamp_utc = _parse_ts(body.get("timestamp_utc"))
        last_run_utc = _parse_ts(body.get("last_run_utc"))

        last_run_result = body.get("last_run_result")
        if last_run_result is not None and last_run_result not in RESULT_VALUES:
            last_run_result = None

        trigger = body.get("trigger")
        if trigger is not None and trigger not in TRIGGER_VALUES:
            trigger = None

        message = body.get("message")
        version = body.get("version")

        metrics = body.get("metrics")
        if metrics is not None and not isinstance(metrics, dict):
            logger.warning("Discarding malformed metrics field for %s", component_id)
            metrics = None

        health = body.get("health")
        if health is not None and not isinstance(health, dict):
            logger.warning("Discarding malformed health field for %s", component_id)
            health = None

        row = await conn.fetchrow(
            """
            INSERT INTO status_log
                (component_id, schema_version, status, timestamp_utc, version,
                 last_run_utc, last_run_result, trigger, message, metrics, health)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            RETURNING id, received_at
            """,
            component_id,
            schema_version,
            status,
            timestamp_utc,
            version,
            last_run_utc,
            last_run_result,
            trigger,
            message,
            json.dumps(metrics) if metrics is not None else None,
            json.dumps(health) if health is not None else None,
        )

    if last_run_result == "CRITICAL":
        await send_pushover_alert(component_id, message or "last_run_result=CRITICAL")

    return {"id": row["id"], "received_at": row["received_at"].isoformat(), "status_recorded": status}
