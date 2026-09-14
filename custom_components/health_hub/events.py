"""Safe event payload helpers for Health Hub."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def event_payload(
    *,
    system_id: str,
    check_id: str | None,
    old_status: str | None,
    new_status: str | None,
    entity_id: str | None,
    reason: str | None,
    timestamp: datetime,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Return the stable public event contract without entity attributes."""
    payload: dict[str, Any] = {
        "system_id": system_id,
        "check_id": check_id,
        "old_status": old_status,
        "new_status": new_status,
        "entity_id": entity_id,
        "reason": reason,
        "timestamp": timestamp.isoformat(),
    }
    if duration_seconds is not None:
        payload["duration"] = round(max(duration_seconds, 0), 3)
    return payload
