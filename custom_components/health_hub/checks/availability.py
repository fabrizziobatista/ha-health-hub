"""Availability check."""

from __future__ import annotations

from datetime import datetime

from ..models import CheckResult, CheckRuntimeState, EntitySnapshot
from .base import BaseCheck, is_invalid


class AvailabilityCheck(BaseCheck):
    """Evaluate missing, unknown, and unavailable entity states with grace."""

    def evaluate(self, snapshot, snapshots, runtime, now: datetime) -> CheckResult:
        if not self.is_active(snapshots):
            return self.inactive()
        if not is_invalid(snapshot):
            runtime.invalid_since = None
            return CheckResult("ok", "Entity available", value=snapshot.state)
        if runtime.invalid_since is None:
            runtime.invalid_since = now
        elapsed = now - runtime.invalid_since
        warning_after = self.definition.params["warning_after"]
        critical_after = self.definition.params["critical_after"]
        if critical_after is not None and elapsed >= critical_after:
            return CheckResult("critical", "Entity unavailable beyond critical grace", value=getattr(snapshot, "state", None))
        if elapsed >= warning_after:
            return CheckResult("warning", "Entity unavailable", value=getattr(snapshot, "state", None), next_deadline=(runtime.invalid_since + critical_after) if critical_after else None)
        return CheckResult("ok", "Entity unavailability is within grace period", value=getattr(snapshot, "state", None), defer=True, next_deadline=runtime.invalid_since + warning_after)
