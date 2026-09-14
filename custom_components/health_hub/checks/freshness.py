"""Freshness check based on Home Assistant last_updated."""

from __future__ import annotations

from datetime import datetime

from ..models import CheckResult
from .base import BaseCheck, is_invalid


class FreshnessCheck(BaseCheck):
    """Determine whether an entity reported recently enough."""

    def evaluate(self, snapshot, snapshots, runtime, now: datetime) -> CheckResult:
        if not self.is_active(snapshots):
            return self.inactive()
        if is_invalid(snapshot) or snapshot.last_updated is None:
            return self.unknown(
                "No valid last_updated timestamp", value=getattr(snapshot, "state", None)
            )
        age = now - snapshot.last_updated
        warning = self.definition.params["max_age_warning"]
        critical = self.definition.params["max_age_critical"]
        if critical is not None and age >= critical:
            return CheckResult("critical", f"No update for {age}", value=snapshot.state)
        if warning is not None and age >= warning:
            deadline = snapshot.last_updated + critical if critical else None
            return CheckResult(
                "warning", f"No update for {age}", value=snapshot.state, next_deadline=deadline
            )
        deadlines = [
            snapshot.last_updated + value for value in (warning, critical) if value is not None
        ]
        return CheckResult(
            "ok",
            "Entity is fresh",
            value=snapshot.state,
            next_deadline=min(deadlines) if deadlines else None,
        )
