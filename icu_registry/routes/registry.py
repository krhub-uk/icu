from fastapi import APIRouter, HTTPException
from icu_registry.db import get_pool
from icu_registry.models import RegistryIn, interval_to_seconds

router = APIRouter()


@router.post("/registry", status_code=201)
async def register_component(payload: RegistryIn):
    # ON_DEMAND + no endpoint_url -> 422 (Contract Spec v1.2 §7, Basket C v1.2)
    if payload.schedule_string == "ON_DEMAND" and not payload.endpoint_url:
        raise HTTPException(
            status_code=422,
            detail="endpoint_url is required when schedule_string=ON_DEMAND — Run Now is the only wake mechanism",
        )

    # Derive expected_interval from schedule_string — never accepted from caller.
    # interval_to_seconds enforces the 15M floor and raises on invalid tags.
    try:
        seconds = interval_to_seconds(payload.schedule_string)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    interval_literal = f"{seconds} seconds" if seconds is not None else None

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT component_id FROM process_registry WHERE component_id = $1",
            payload.component_id,
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"component_id '{payload.component_id}' already registered")

        row = await conn.fetchrow(
            """
            INSERT INTO process_registry
                (component_id, display_name, endpoint_url, log_path, github_repo_tag,
                 schedule_string, expected_interval)
            VALUES ($1, $2, $3, $4, $5, $6, $7::interval)
            RETURNING component_id, display_name, endpoint_url, log_path, github_repo_tag,
                      schedule_string, expected_interval, registered_at, updated_at, allowed_to_run
            """,
            payload.component_id,
            payload.display_name,
            payload.endpoint_url,
            payload.log_path,
            payload.github_repo_tag,
            payload.schedule_string,
            interval_literal,
        )
   