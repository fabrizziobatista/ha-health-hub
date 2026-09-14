"""Central Health Hub evaluator, hierarchy aggregator, and event coordinator."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import logging
from typing import Any, Callable, Iterable

from .checks import build_check
from .const import (
    EVENT_ISSUE_OPENED, EVENT_ISSUE_RESOLVED, EVENT_STATUS_CHANGED,
    STATUS_CRITICAL, STATUS_OK, STATUS_RANK, STATUS_UNKNOWN, STATUS_WARNING,
)
from .events import event_payload
from .models import (
    CheckDefinition, CheckRuntimeState, EntitySnapshot, Observation,
    SystemDefinition, SystemRuntimeState,
)
from .store import HealthHubStore

_LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


class HealthManager:
    """Evaluate only affected checks and propagate their state through a tree."""

    def __init__(
        self,
        systems: tuple[SystemDefinition, ...],
        store: HealthHubStore,
        *,
        emit: Callable[[str, dict[str, Any]], None] | None = None,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.system_roots = systems
        self.store = store
        self._emit = emit or (lambda _event, _data: None)
        self._now = now_provider
        self.snapshots: dict[str, EntitySnapshot | None] = {}
        self.system_defs: dict[str, SystemDefinition] = {}
        self.check_defs: dict[str, tuple[str, CheckDefinition]] = {}
        self.checks: dict[str, Any] = {}
        self.parents: dict[str, str | None] = {}
        self.entity_dependencies: dict[str, set[str]] = defaultdict(set)
        self.check_runtime: dict[str, CheckRuntimeState] = {}
        self.system_runtime: dict[str, SystemRuntimeState] = {}
        self._deadlines: dict[str, datetime] = {}
        self._listeners: list[Callable[[str], None]] = []
        self._index_systems(systems, parent=None)

    def _index_systems(self, systems: Iterable[SystemDefinition], parent: str | None) -> None:
        for system in systems:
            self.system_defs[system.id] = system
            self.parents[system.id] = parent
            self.system_runtime[system.id] = SystemRuntimeState()
            for definition in system.checks:
                key = self.check_key(system.id, definition.id)
                self.check_defs[key] = (system.id, definition)
                self.checks[key] = build_check(definition)
                self.check_runtime[key] = CheckRuntimeState()
                self.entity_dependencies[definition.entity_id].add(key)
                if definition.active_when:
                    self.entity_dependencies[definition.active_when[0]].add(key)
            self._index_systems(system.children, parent=system.id)

    @staticmethod
    def check_key(system_id: str, check_id: str) -> str:
        return f"{system_id}.{check_id}"

    def entity_ids(self) -> set[str]:
        return set(self.entity_dependencies)

    def add_listener(self, listener: Callable[[str], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def _notify(self, system_id: str) -> None:
        for listener in tuple(self._listeners):
            listener(system_id)

    async def async_load(self) -> None:
        """Restore only the small state needed for dedupe and stale windows."""
        data = await self.store.async_load()
        for key, raw in data["checks"].items():
            if key not in self.check_runtime or not isinstance(raw, dict):
                continue
            runtime = self.check_runtime[key]
            runtime.status = raw.get("status", STATUS_UNKNOWN)
            runtime.active = bool(raw.get("active", True))
            runtime.reason = raw.get("reason", "Awaiting first evaluation")
            runtime.value = raw.get("value")
            runtime.since = _dt(raw.get("since"))
            runtime.issue_opened_at = _dt(raw.get("issue_opened_at"))
            runtime.pending_status = raw.get("pending_status") if isinstance(raw.get("pending_status"), str) else None
            runtime.pending_since = _dt(raw.get("pending_since"))
            runtime.invalid_since = _dt(raw.get("invalid_since"))
            runtime.bad_since = _dt(raw.get("bad_since"))
            runtime.last_ok = _dt(raw.get("last_ok"))
            runtime.observations = [
                Observation(timestamp, float(item["value"]))
                for item in raw.get("observations", [])
                if isinstance(item, dict) and (timestamp := _dt(item.get("timestamp"))) is not None
                and isinstance(item.get("value"), (int, float))
            ]
        for system_id, raw in data["systems"].items():
            if system_id not in self.system_runtime or not isinstance(raw, dict):
                continue
            runtime = self.system_runtime[system_id]
            runtime.status = raw.get("status", STATUS_UNKNOWN)
            runtime.last_ok = _dt(raw.get("last_ok"))
            runtime.last_changed_by_hub = _dt(raw.get("last_changed_by_hub"))

    def set_snapshot(self, snapshot: EntitySnapshot | None, *, entity_id: str | None = None) -> None:
        """Seed or update a cached snapshot without evaluation."""
        key = entity_id or (snapshot.entity_id if snapshot else None)
        if key is None:
            raise ValueError("entity_id is required for a missing snapshot")
        self.snapshots[key] = snapshot

    async def async_initialize(self, snapshots: Iterable[EntitySnapshot | None]) -> None:
        """Load state, seed snapshots, and calculate initial entities without events."""
        await self.async_load()
        for snapshot in snapshots:
            if snapshot is not None:
                self.set_snapshot(snapshot)
        for entity_id in self.entity_ids():
            self.snapshots.setdefault(entity_id, None)
        await self._evaluate_keys(self.checks, self._now(), emit_events=False)
        await self._save()

    async def async_handle_entity_update(self, snapshot: EntitySnapshot | None, *, entity_id: str | None = None) -> None:
        """Evaluate only checks that depend on a changed entity, then ancestors."""
        key = entity_id or (snapshot.entity_id if snapshot else None)
        if key is None:
            raise ValueError("entity_id is required for a missing snapshot")
        self.snapshots[key] = snapshot
        affected = self.entity_dependencies.get(key, set())
        if not affected:
            return
        await self._evaluate_keys(affected, self._now(), emit_events=True)
        await self._save()

    async def async_evaluate_due(self, now: datetime | None = None) -> None:
        """Evaluate only checks whose next deadline has arrived."""
        now = now or self._now()
        due = {key for key, deadline in self._deadlines.items() if deadline <= now}
        if due:
            await self._evaluate_keys(due, now, emit_events=True)
            await self._save()

    def next_deadline(self) -> datetime | None:
        return min(self._deadlines.values(), default=None)

    async def _evaluate_keys(self, keys: Iterable[str], now: datetime, *, emit_events: bool) -> None:
        affected_systems: set[str] = set()
        for key in keys:
            system_id, definition = self.check_defs[key]
            check = self.checks[key]
            runtime = self.check_runtime[key]
            result = check.evaluate(self.snapshots.get(definition.entity_id), self.snapshots, runtime, now)
            self._apply_check_result(key, system_id, definition, runtime, result, now, emit_events)
            affected_systems.add(system_id)
        self._aggregate_ancestors(affected_systems, now, emit_events)

    def _apply_check_result(self, key, system_id, definition, runtime, result, now, emit_events) -> None:
        if result.next_deadline is None:
            self._deadlines.pop(key, None)
        else:
            self._deadlines[key] = result.next_deadline
        if not result.active:
            was_open = runtime.issue_opened_at
            old = runtime.status
            runtime.active, runtime.status, runtime.reason, runtime.value = False, STATUS_OK, result.reason, result.value
            runtime.pending_status = runtime.pending_since = None
            if was_open and emit_events:
                self._emit(EVENT_ISSUE_RESOLVED, event_payload(system_id=system_id, check_id=definition.id, old_status=old, new_status=STATUS_OK, entity_id=definition.entity_id, reason="Check became inactive", timestamp=now, duration_seconds=(now - was_open).total_seconds()))
            runtime.issue_opened_at = None
            return
        runtime.active = True
        if result.defer:
            return
        target = result.status
        if target != runtime.status:
            if runtime.pending_status != target:
                runtime.pending_status, runtime.pending_since = target, now
            duration = definition.minimum_state_duration
            if now - runtime.pending_since < duration:
                self._deadlines[key] = runtime.pending_since + duration
                return
            old = runtime.status
            runtime.status, runtime.since = target, now
            runtime.pending_status = runtime.pending_since = None
            self._transition_issue(system_id, definition, runtime, old, target, result.reason, now, emit_events)
        else:
            runtime.pending_status = runtime.pending_since = None
        runtime.reason, runtime.value = result.reason, result.value
        if target == STATUS_OK:
            runtime.last_ok = now

    def _transition_issue(self, system_id, definition, runtime, old, new, reason, now, emit_events) -> None:
        relevant_issue = not (definition.optional and new == STATUS_UNKNOWN)
        if new == STATUS_OK:
            if runtime.issue_opened_at and emit_events:
                self._emit(EVENT_ISSUE_RESOLVED, event_payload(system_id=system_id, check_id=definition.id, old_status=old, new_status=new, entity_id=definition.entity_id, reason=reason, timestamp=now, duration_seconds=(now - runtime.issue_opened_at).total_seconds()))
            runtime.issue_opened_at = None
            return
        if relevant_issue and runtime.issue_opened_at is None:
            runtime.issue_opened_at = now
            if emit_events:
                self._emit(EVENT_ISSUE_OPENED, event_payload(system_id=system_id, check_id=definition.id, old_status=old, new_status=new, entity_id=definition.entity_id, reason=reason, timestamp=now))

    def _aggregate_ancestors(self, systems: set[str], now: datetime, emit_events: bool) -> None:
        all_ancestors: set[str] = set()
        for system_id in systems:
            current: str | None = system_id
            while current is not None:
                all_ancestors.add(current)
                current = self.parents[current]
        depth = lambda item: self._depth(item)
        for system_id in sorted(all_ancestors, key=depth, reverse=True):
            self._aggregate_system(system_id, now, emit_events)

    def _depth(self, system_id: str) -> int:
        result, current = 0, self.parents[system_id]
        while current is not None:
            result += 1
            current = self.parents[current]
        return result

    def _aggregate_system(self, system_id: str, now: datetime, emit_events: bool) -> None:
        definition = self.system_defs[system_id]
        runtime = self.system_runtime[system_id]
        candidates: list[tuple[str, str, str | None, str | None, str]] = []
        for check in definition.checks:
            key = self.check_key(system_id, check.id)
            child = self.check_runtime[key]
            if not child.active or (check.optional and child.status == STATUS_UNKNOWN):
                continue
            candidates.append((child.status, child.reason, check.id, check.entity_id, system_id))
        for child_def in definition.children:
            child = self.system_runtime[child_def.id]
            candidates.append((child.status, child.summary, None, None, child_def.id))
        if not candidates:
            # A system that only has optional unknown or currently inactive checks
            # is healthy with respect to its relevant contract. A structurally
            # empty system is rejected by schema validation.
            status, summary, primary, worst_child = STATUS_OK, "No active issues", None, None
        else:
            worst = max(candidates, key=lambda item: STATUS_RANK[item[0]])
            status, summary = worst[0], worst[1]
            primary = None if worst[2] is None else {"check_id": worst[2], "status": worst[0], "entity_id": worst[3], "reason": worst[1], "since": self.check_runtime[self.check_key(system_id, worst[2])].since.isoformat() if self.check_runtime[self.check_key(system_id, worst[2])].since else None}
            worst_child = worst[4] if worst[2] is None else None
        # A parent reports the number of actual leaf issues below it, rather
        # than merely the number of unhealthy immediate children. This keeps a
        # compact root sensor meaningful while drill-down remains possible.
        critical = warning = unknown = 0
        for check in definition.checks:
            child = self.check_runtime[self.check_key(system_id, check.id)]
            if not child.active or (check.optional and child.status == STATUS_UNKNOWN):
                continue
            if child.status == STATUS_CRITICAL:
                critical += 1
            elif child.status == STATUS_WARNING:
                warning += 1
            elif child.status == STATUS_UNKNOWN:
                unknown += 1
        for child_def in definition.children:
            child = self.system_runtime[child_def.id]
            critical += child.critical_count
            warning += child.warning_count
            unknown += child.unknown_count
        old = runtime.status
        runtime.status, runtime.summary, runtime.primary_issue = status, summary, primary
        runtime.issue_count, runtime.critical_count, runtime.warning_count, runtime.unknown_count = critical + warning + unknown, critical, warning, unknown
        runtime.worst_child = worst_child
        if status == STATUS_OK:
            runtime.last_ok = now
        if status != old:
            runtime.last_changed_by_hub = now
            if emit_events:
                self._emit(EVENT_STATUS_CHANGED, event_payload(system_id=system_id, check_id=None, old_status=old, new_status=status, entity_id=primary.get("entity_id") if primary else None, reason=summary, timestamp=now))
            self._notify(system_id)

    async def _save(self) -> None:
        self.store.data["checks"] = {key: self._serialize_check(runtime) for key, runtime in self.check_runtime.items()}
        self.store.data["systems"] = {key: self._serialize_system(runtime) for key, runtime in self.system_runtime.items()}
        await self.store.async_save()

    @staticmethod
    def _serialize_check(value: CheckRuntimeState) -> dict[str, Any]:
        stamp = lambda item: item.isoformat() if item else None
        return {"status": value.status, "active": value.active, "reason": value.reason, "value": value.value, "since": stamp(value.since), "issue_opened_at": stamp(value.issue_opened_at), "pending_status": value.pending_status, "pending_since": stamp(value.pending_since), "invalid_since": stamp(value.invalid_since), "bad_since": stamp(value.bad_since), "last_ok": stamp(value.last_ok), "observations": [{"timestamp": item.timestamp.isoformat(), "value": item.value} for item in value.observations]}

    @staticmethod
    def _serialize_system(value: SystemRuntimeState) -> dict[str, Any]:
        stamp = lambda item: item.isoformat() if item else None
        return {"status": value.status, "last_ok": stamp(value.last_ok), "last_changed_by_hub": stamp(value.last_changed_by_hub)}

    def system_attributes(self, system_id: str) -> dict[str, Any]:
        runtime = self.system_runtime[system_id]
        stamp = lambda item: item.isoformat() if item else None
        return {"issue_count": runtime.issue_count, "critical_count": runtime.critical_count, "warning_count": runtime.warning_count, "unknown_count": runtime.unknown_count, "summary": runtime.summary, "worst_child": runtime.worst_child, "primary_issue": runtime.primary_issue, "last_ok": stamp(runtime.last_ok), "last_changed_by_hub": stamp(runtime.last_changed_by_hub)}

    def async_diagnostics(self) -> dict[str, Any]:
        """Return useful, compact, non-secret diagnostic data."""
        return {"systems": {system_id: {"status": runtime.status, "attributes": self.system_attributes(system_id), "checks": [definition.id for definition in self.system_defs[system_id].checks], "children": [child.id for child in self.system_defs[system_id].children]} for system_id, runtime in self.system_runtime.items()}, "check_count": len(self.check_runtime), "next_deadline": self.next_deadline().isoformat() if self.next_deadline() else None}
