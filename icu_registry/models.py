import re
from typing import Optional, Literal
from pydantic import BaseModel

SCHEDULE_VALUES = ("15M", "1H", "4H", "1D", "1W", "1MO", "ON_DEMAND")
STATUS_VALUES = ("IDLE", "RUNNING", "PAUSED", "HALTED", "ERROR")
RESULT_VALUES = ("SUCCESS", "PARTIAL", "DEGRADED", "FAILED", "CRITICAL", "SKIPPED")
TRIGGER_VALUES = ("SCHEDULED", "MANUAL", "GATE_CHECK", "HEARTBEAT")

UNIT_SECONDS = {"M": 60, "H": 3600, "D": 86400, "W": 604800, "MO": 2592000}


def interval_to_seconds(tag: str) -> int | None:
    """Derive expected_interval (seconds) from a schedule_string. ON_DEMAND -> None.
    Enforces the 15M floor (900s). Raises ValueError on invalid tag or below-floor interval.
    """
    if tag == "ON_DEMAND":
        return None
    # MO must appear before M in alternation — prevents "1MO" matching as n=1, unit=M + trailing "O"
    match = re.match(r"^(\d+)(MO|[MHDW])$", tag)
    if not match:
        raise ValueError(f"Invalid schedule_string: {tag}")
    n, unit = int(match[1]), match[2]
    seconds = n * UNIT_SECONDS[unit]
    if seconds < 900:
        raise ValueError(f"Interval {tag} below 15M floor — out of scope for ICU")
    return seconds


class RegistryIn(BaseModel):
    component_id: str
    display_name: str
    endpoint_url: Optional[str] = None
    log_path: str
    github_repo_tag: Optional[str] = None
    schedule_string: Literal[SCHEDULE_VALUES]


class ControlPatchIn(BaseModel):
    allowed_to_run: bool


class StatusIn(BaseModel):
    schema_version: str
    component_id: str
    status: str  # validated against STATUS_VALUES in route, forced to ERROR if invalid
    timestamp_utc: Optional[str] = None
    version: Optional[str] = None
    last_run_utc: Optional[str] = None
    last_run_result: Optional[str] = None
    trigger: Optional[str] = None
    message: Optional[str] = None
    metrics: Optional[dict] = None
    health: Optional[dict] = None
