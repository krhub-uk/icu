import os
import logging
import httpx

logger = logging.getLogger("icu.alerts")


async def send_pushover_alert(component_id: str, message: str) -> None:
    """Fires only on last_run_result=CRITICAL or staleness ERROR threshold exceeded.
    Never fires on standard ERROR result codes (log panel / backlog only) — callers
    are responsible for only invoking this in those two cases.
    """
    token = os.getenv("PUSHOVER_ICU_TOKEN")
    user = os.getenv("PUSHOVER_USER_KEY")
    if not token or not user:
        logger.warning("Pushover not configured — skipping alert for %s", component_id)
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": token,
                    "user": user,
                    "title": f"ICU CRITICAL — {component_id}",
                    "message": message,
                    "priority": 1,
                },
            )
            resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — alert failures must not crash the caller
        logger.error("Pushover alert failed for %s: %s", component_id, exc)
