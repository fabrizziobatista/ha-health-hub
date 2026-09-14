"""Shared primitives for generic Health Hub checks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from ..models import CheckDefinition, CheckResult, CheckRuntimeState, EntitySnapshot

INVALID_STATES = {None, "unknown", "unavailable", "none", ""}


def is_invalid(snapshot: EntitySnapshot | None) -> bool:
    """Return whether HA has no usable state for an entity."""
    return snapshot is None or snapshot.state is None or snapshot.state.lower() in INVALID_STATES


def numeric_value(snapshot: EntitySnapshot | None) -> float | None:
    """Return a finite numeric state, otherwise None."""
    if is_invalid(snapshot):
        return None
    try:
        value = float(snapshot.state)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


class BaseCheck(ABC):
    """A stateless implementation evaluated with small persisted runtime state."""

    def __init__(self, definition: CheckDefinition) -> None:
        self.definition = definition

    def is_active(self, snapshots: dict[str, EntitySnapshot | None]) -> bool:
        condition = self.definition.active_when
        if condition is None:
            return True
        entity_id, expected_states = condition
        snapshot = snapshots.get(entity_id)
        return snapshot is not None and snapshot.state in expected_states

    @abstractmethod
    def evaluate(
        self,
        snapshot: EntitySnapshot | None,
        snapshots: dict[str, EntitySnapshot | None],
        runtime: CheckRuntimeState,
        now: datetime,
    ) -> CheckResult:
        """Return a candidate state without causing side effects."""

    @staticmethod
    def inactive() -> CheckResult:
        return CheckResult(status="ok", reason="Check inactive by active_when", active=False)

    @staticmethod
    def unknown(reason: str, *, value: Any = None) -> CheckResult:
        return CheckResult(status="unknown", reason=reason, value=value)
