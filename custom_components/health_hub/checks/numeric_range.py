"""Generic numeric range check."""

from __future__ import annotations

from datetime import datetime

from ..models import CheckResult, CheckRuntimeState, EntitySnapshot
from .base import BaseCheck, numeric_value


class NumericRangeCheck(BaseCheck):
    """Evaluate optional warning and critical bounds without unit assumptions."""

    def evaluate(self, snapshot, snapshots, runtime, now: datetime) -> CheckResult:
        if not self.is_active(snapshots):
            return self.inactive()
        value = numeric_value(snapshot)
        if value is None:
            return self.unknown("Numeric value is unavailable or invalid", value=getattr(snapshot, "state", None))
        params = self.definition.params
        if "critical_below" in params and value <= params["critical_below"]:
            return CheckResult("critical", f"Value {value:g} is below critical limit", value=value)
        if "critical_above" in params and value >= params["critical_above"]:
            return CheckResult("critical", f"Value {value:g} is above critical limit", value=value)
        if "warning_below" in params and value <= params["warning_below"]:
            return CheckResult("warning", f"Value {value:g} is below warning limit", value=value)
        if "warning_above" in params and value >= params["warning_above"]:
            return CheckResult("warning", f"Value {value:g} is above warning limit", value=value)
        return CheckResult("ok", f"Value {value:g} is within configured range", value=value)
