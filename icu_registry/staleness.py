import asyncio
import logging
from icu_registry.db import get_pool
from icu_registry.alerts import send_pushover_alert

logger = logging.getLogger("icu.staleness")

POLL_INTERVAL_SECONDS = 60


async def _check_once():
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT r.component_id, r.expected_interval,
               s.received_at, s.status AS last_status
        FROM process_registry r
        LEFT JOIN LATERAL (
            SELECT * FROM status_log sl
            WHERE sl.component_id = r.component_id
            ORDER BY sl.received_at DESC
            LIMIT 1
        ) s ON true
        WHERE r.schedule_string <> 'ON_DEMAND'
          AND r.expected_interval IS NOT NULL
        """
    )

    for row in rows:
        component_id = row["component_id"]
        received_at = row["received_at"]
        if received_at is None:
            continue

        threshold_query = await pool.fetchval(
            """
            SELECT (NOW() - $1::timestamptz) > ($2::interval * 3)
            """,
            received_at,
            row["expected_interval"],
        )

        if threshold_query and row["last_status"] != "ERROR":
            await pool.execute(
                """
                INSERT INTO status_log
                    (component_id, schema_version, status, message, trigger)
                VALUES ($1, '1.0', 'ERROR', 'Staleness threshold exceeded', 'GATE_CHECK')
                """,
                component_id,
            )
            logger.warning("Staleness threshold exceeded for %s - synthetic ERROR row inserted", component_id)
            await send_pushover_alert(component_id, "Staleness threshold exceeded")


async def staleness_loop():
    """Runs every 60s for the lifetime of the app. Started from the FastAPI lifespan."""
    while True:
        try:
            await _check_once()
        except Exception:
            logger.exception("Staleness check cycle failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
