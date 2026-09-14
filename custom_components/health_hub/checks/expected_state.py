"""Expected-state check."""

from __future__ import annotations

from datetime import datetime

from ..models import CheckResult, CheckRuntimeState, EntitySnapshot
from .base import BaseCheck, is_invalid


class ExpectedStateCheck(BaseCheck):
    """Check that an entity remains in one configured expected state."""

    def evaluate(self, snapshot, snapshots, runtime, now: datetime) -> CheckResult:
        if not self.is_active(snapshots):
            return self.inactive()
        if is_invalid(snapshot):
            runtime.bad_since = None
            return self.unknown("Expected-state entity is unavailable", value=getattr(snapshot, "state", None))
        expected = self.definition.params["expected"]
        if snapshot.state in expected:
            runtime.bad_since = None
            return CheckResult("ok", "Entity is in expected state", value=snapshot.state)
        if runtime.bad_since is None:
            runtime.bad_since = now
        elapsed = now - runtime.bad_since
        warning_after = self.definition.params["warning_after"]
        critical_after = self.definition.params["critical_after"]
        if critical_after is not None and elapsed >= critical_after:
            return CheckResult("critical", f"Unexpected state {snapshot.state!r}", value=snapshot.state)
        if elapsed >= warning_after:
            return CheckResult("warning", f"Unexpected state {snapshot.state!r}", value=snapshot.state, next_deadline=(runtime.bad_since + critical_after) if critical_after else None)
        return CheckResult("ok", "Unexpected state is within grace period", value=snapshot.state, defer=True, next_deadline=runtime.bad_since + warning_after)
