"""Battery percentage check."""

from __future__ import annotations

from datetime import datetime

from ..models import CheckResult, CheckRuntimeState, EntitySnapshot
from .base import BaseCheck, numeric_value


class BatteryCheck(BaseCheck):
    """Evaluate a battery only when it provides a numeric percentage."""

    def evaluate(self, snapshot, snapshots, runtime, now: datetime) -> CheckResult:
        if not self.is_active(snapshots):
            return self.inactive()
        value = numeric_value(snapshot)
        if value is None:
            return self.unknown("Battery value is unavailable or non-numeric", value=getattr(snapshot, "state", None))
        unit = (snapshot.attributes.get("unit_of_measurement") or "").strip() if snapshot else ""
        if unit not in {"%", "percent"}:
            return self.unknown("Battery unit must be %", value=value)
        if value <= self.definition.params["critical_below"]:
            return CheckResult("critical", f"Battery at {value:g}%", value=value)
        if value <= self.definition.params["warning_below"]:
            return CheckResult("warning", f"Battery at {value:g}%", value=value)
        return CheckResult("ok", f"Battery at {value:g}%", value=value)
