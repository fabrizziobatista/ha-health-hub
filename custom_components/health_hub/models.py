"""Pure Health Hub data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .const import STATUS_UNKNOWN


@dataclass(frozen=True)
class EntitySnapshot:
    """A Home Assistant entity state reduced to the fields checks need."""

    entity_id: str
    state: str | None
    last_updated: datetime | None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckDefinition:
    """Validated declarative definition of a single check."""

    id: str
    type: str
    entity_id: str
    optional: bool = False
    minimum_state_duration: timedelta = timedelta(0)
    active_when: tuple[str, tuple[str, ...]] | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SystemDefinition:
    """Validated hierarchical system definition."""

    id: str
    name: str
    icon: str | None
    checks: tuple[CheckDefinition, ...]
    children: tuple["SystemDefinition", ...]


@dataclass
class Observation:
    """One numeric observation retained only for stale-value evaluation."""

    timestamp: datetime
    value: float


@dataclass
class CheckRuntimeState:
    """Small mutable state required to stabilize and restore a check."""

    status: str = STATUS_UNKNOWN
    active: bool = True
    reason: str = "Awaiting first evaluation"
    value: Any = None
    since: datetime | None = None
    issue_opened_at: datetime | None = None
    pending_status: str | None = None
    pending_since: datetime | None = None
    invalid_since: datetime | None = None
    bad_since: datetime | None = None
    last_ok: datetime | None = None
    observations: list[Observation] = field(default_factory=list)


@dataclass(frozen=True)
class CheckResult:
    """Candidate result emitted by one generic check."""

    status: str
    reason: str
    value: Any = None
    active: bool = True
    defer: bool = False
    next_deadline: datetime | None = None


@dataclass
class SystemRuntimeState:
    """Aggregated state of one logical system."""

    status: str = STATUS_UNKNOWN
    summary: str = "Awaiting first evaluation"
    primary_issue: dict[str, Any] | None = None
    issue_count: int = 0
    critical_count: int = 0
    warning_count: int = 0
    unknown_count: int = 0
    worst_child: str | None = None
    last_ok: datetime | None = None
    last_changed_by_hub: datetime | None = None
