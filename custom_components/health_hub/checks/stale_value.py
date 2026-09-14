"""Explicit numeric stale-value check."""

from __future__ import annotations

from datetime import datetime

from ..models import CheckResult, CheckRuntimeState, EntitySnapshot, Observation
from .base import BaseCheck, numeric_value


class StaleValueCheck(BaseCheck):
    """Detect a numeric value that did not change enough during a configured window."""

    def evaluate(self, snapshot, snapshots, runtime, now: datetime) -> CheckResult:
        if not self.is_active(snapshots):
            return self.inactive()
        value = numeric_value(snapshot)
        if value is None:
            return self.unknown("Stale-value source is unavailable or non-numeric", value=getattr(snapshot, "state", None))
        if not runtime.observations or runtime.observations[-1].value != value:
            runtime.observations.append(Observation(now, value))
        window = self.definition.params["observation_window"]
        earliest = now - window
        # Retain the latest value immediately before the window as a baseline.
        # Otherwise a due evaluation with no new source update forgets that an
        # unchanged value has been observed long enough to be stale.
        before_window = [item for item in runtime.observations if item.timestamp <= earliest]
        inside_window = [item for item in runtime.observations if item.timestamp > earliest]
        runtime.observations[:] = before_window[-1:] + inside_window
        if not runtime.observations or runtime.observations[0].timestamp > earliest:
            first_observation = runtime.observations[0]
            return CheckResult(
                "unknown",
                "Observation window is not complete",
                value=value,
                next_deadline=first_observation.timestamp + window,
            )
        changes = 0
        minimum_delta = self.definition.params["minimum_delta"]
        previous = runtime.observations[0].value
        for observation in runtime.observations[1:]:
            if abs(observation.value - previous) >= minimum_delta:
                changes += 1
                previous = observation.value
        if changes < self.definition.params["minimum_changes"]:
            return CheckResult("warning", f"Value changed {changes} time(s) in observation window", value=value)
        return CheckResult("ok", f"Value changed {changes} time(s) in observation window", value=value)
