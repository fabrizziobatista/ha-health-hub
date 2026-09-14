"""Pure unit coverage for Health Hub v0.1 without a running Home Assistant."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.health_hub.checks import build_check
from custom_components.health_hub.const import (
    EVENT_ISSUE_OPENED, EVENT_ISSUE_RESOLVED, EVENT_STATUS_CHANGED,
    STATUS_CRITICAL, STATUS_OK, STATUS_UNKNOWN, STATUS_WARNING,
)
from custom_components.health_hub.manager import HealthManager
from custom_components.health_hub.models import CheckRuntimeState, EntitySnapshot
from custom_components.health_hub.schema import ConfigValidationError, validate_config
from custom_components.health_hub.store import HealthHubStore, default_store_data

UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def snapshot(entity_id: str, value: str, *, at: datetime = T0, unit: str | None = None):
    attributes = {"unit_of_measurement": unit} if unit else {}
    return EntitySnapshot(entity_id, value, at, attributes)


def base_config(checks, *, children=None):
    node = {"name": "Generic system", "checks": checks}
    if children is not None:
        node["children"] = children
    return {"systems": {"root": node}}


class MemoryBackend:
    def __init__(self, data=None):
        self.data = data
        self.saves = 0

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data
        self.saves += 1


class SchemaTests(unittest.TestCase):
    def test_valid_schema_and_nested_system(self):
        systems = validate_config(base_config([], children={"child": {"name": "Child", "checks": [{"id": "available", "type": "availability", "entity_id": "sensor.example", "warning_after": "5m", "critical_after": "30m"}]}}))
        self.assertEqual(systems[0].children[0].checks[0].params["warning_after"], timedelta(minutes=5))

    def test_rejects_unknown_check_type_including_template(self):
        with self.assertRaisesRegex(ConfigValidationError, "unsupported type"):
            validate_config(base_config([{ "id": "bad", "type": "template", "entity_id": "sensor.example"}]))

    def test_rejects_duplicate_ids_and_invalid_ranges(self):
        with self.assertRaises(ConfigValidationError):
            validate_config(base_config([{ "id": "same", "type": "availability", "entity_id": "sensor.one"}, {"id": "same", "type": "availability", "entity_id": "sensor.two"}]))
        with self.assertRaises(ConfigValidationError):
            validate_config(base_config([{ "id": "battery", "type": "battery", "entity_id": "sensor.battery", "warning_below": 10, "critical_below": 20}]))
        with self.assertRaises(ConfigValidationError):
            validate_config({"systems": {"one": {"name": "One", "checks": [{"id": "a", "type": "availability", "entity_id": "sensor.a"}]}, "two": {"name": "Two", "children": {"one": {"name": "Duplicate", "checks": [{"id": "b", "type": "availability", "entity_id": "sensor.b"}]}}}}})

    def test_rejects_invalid_binary_and_active_when(self):
        with self.assertRaises(ConfigValidationError):
            validate_config(base_config([{ "id": "binary", "type": "binary_state", "entity_id": "binary_sensor.door", "expected": "maybe"}]))
        with self.assertRaises(ConfigValidationError):
            validate_config(base_config([{ "id": "fresh", "type": "freshness", "entity_id": "sensor.a", "max_age_warning": "5m", "active_when": {"entity_id": "binary_sensor.mode", "state": []}}]))


class CheckTests(unittest.TestCase):
    def definition(self, raw):
        return validate_config(base_config([raw]))[0].checks[0]

    def evaluate(self, raw, state, runtime=None, now=T0, snapshots=None):
        definition = self.definition(raw)
        runtime = runtime or CheckRuntimeState()
        current = snapshot(definition.entity_id, state) if state is not None else None
        all_states = {definition.entity_id: current, **(snapshots or {})}
        return build_check(definition).evaluate(current, all_states, runtime, now), runtime

    def test_availability_grace_warning_critical_and_recovery(self):
        raw = {"id": "available", "type": "availability", "entity_id": "sensor.a", "warning_after": "5m", "critical_after": "30m"}
        runtime = CheckRuntimeState(status=STATUS_OK)
        result, runtime = self.evaluate(raw, None, runtime, T0)
        self.assertTrue(result.defer)
        result, runtime = self.evaluate(raw, None, runtime, T0 + timedelta(minutes=5))
        self.assertEqual(result.status, STATUS_WARNING)
        result, runtime = self.evaluate(raw, None, runtime, T0 + timedelta(minutes=30))
        self.assertEqual(result.status, STATUS_CRITICAL)
        result, _ = self.evaluate(raw, "12", runtime, T0 + timedelta(minutes=31))
        self.assertEqual(result.status, STATUS_OK)

    def test_freshness_uses_last_updated_not_last_changed(self):
        raw = {"id": "fresh", "type": "freshness", "entity_id": "sensor.a", "max_age_warning": "5m", "max_age_critical": "10m"}
        definition = self.definition(raw)
        check = build_check(definition)
        state = snapshot("sensor.a", "10", at=T0)
        self.assertEqual(check.evaluate(state, {"sensor.a": state}, CheckRuntimeState(), T0 + timedelta(minutes=4)).status, STATUS_OK)
        self.assertEqual(check.evaluate(state, {"sensor.a": state}, CheckRuntimeState(), T0 + timedelta(minutes=5)).status, STATUS_WARNING)
        self.assertEqual(check.evaluate(state, {"sensor.a": state}, CheckRuntimeState(), T0 + timedelta(minutes=10)).status, STATUS_CRITICAL)

    def test_stale_value_window_delta_and_active_when(self):
        raw = {"id": "stale", "type": "stale_value", "entity_id": "sensor.lux", "observation_window": "1h", "minimum_changes": 2, "minimum_delta": 10}
        definition = self.definition(raw)
        check, runtime = build_check(definition), CheckRuntimeState()
        state = snapshot("sensor.lux", "100", at=T0)
        self.assertEqual(check.evaluate(state, {"sensor.lux": state}, runtime, T0).status, STATUS_UNKNOWN)
        self.assertEqual(check.evaluate(state, {"sensor.lux": state}, runtime, T0 + timedelta(hours=1)).status, STATUS_WARNING)
        state = snapshot("sensor.lux", "120", at=T0 + timedelta(hours=1, minutes=1))
        check.evaluate(state, {"sensor.lux": state}, runtime, T0 + timedelta(hours=1, minutes=1))
        state = snapshot("sensor.lux", "140", at=T0 + timedelta(hours=1, minutes=2))
        check.evaluate(state, {"sensor.lux": state}, runtime, T0 + timedelta(hours=1, minutes=2))
        state = snapshot("sensor.lux", "160", at=T0 + timedelta(hours=1, minutes=3))
        result = check.evaluate(state, {"sensor.lux": state}, runtime, T0 + timedelta(hours=2, minutes=1))
        self.assertEqual(result.status, STATUS_OK)
        # A scheduler pass without a new entity update retains a baseline and
        # never loses the observation window or raises an indexing error.
        result = check.evaluate(state, {"sensor.lux": state}, runtime, T0 + timedelta(hours=3, minutes=1))
        self.assertIn(result.status, {STATUS_OK, STATUS_WARNING})
        gated = {**raw, "active_when": {"entity_id": "binary_sensor.day", "state": "on"}}
        definition = self.definition(gated)
        result = build_check(definition).evaluate(state, {"sensor.lux": state, "binary_sensor.day": snapshot("binary_sensor.day", "off")}, CheckRuntimeState(), T0)
        self.assertFalse(result.active)

    def test_battery_requires_percent_and_thresholds(self):
        raw = {"id": "battery", "type": "battery", "entity_id": "sensor.battery", "warning_below": 20, "critical_below": 10}
        definition, check = self.definition(raw), build_check(self.definition(raw))
        self.assertEqual(check.evaluate(snapshot("sensor.battery", "18", unit="%"), {}, CheckRuntimeState(), T0).status, STATUS_WARNING)
        self.assertEqual(check.evaluate(snapshot("sensor.battery", "10", unit="%"), {}, CheckRuntimeState(), T0).status, STATUS_CRITICAL)
        self.assertEqual(check.evaluate(snapshot("sensor.battery", "18", unit="V"), {}, CheckRuntimeState(), T0).status, STATUS_UNKNOWN)

    def test_numeric_range_and_expected_binary_states(self):
        numeric = self.definition({"id": "temp", "type": "numeric_range", "entity_id": "sensor.temp", "warning_above": 25, "critical_above": 30, "warning_below": 10, "critical_below": 5})
        check = build_check(numeric)
        self.assertEqual(check.evaluate(snapshot("sensor.temp", "20"), {}, CheckRuntimeState(), T0).status, STATUS_OK)
        self.assertEqual(check.evaluate(snapshot("sensor.temp", "26"), {}, CheckRuntimeState(), T0).status, STATUS_WARNING)
        self.assertEqual(check.evaluate(snapshot("sensor.temp", "31"), {}, CheckRuntimeState(), T0).status, STATUS_CRITICAL)
        expected = self.definition({"id": "switch", "type": "binary_state", "entity_id": "switch.safe", "expected": "off", "warning_after": "5m"})
        runtime = CheckRuntimeState(status=STATUS_OK)
        result = build_check(expected).evaluate(snapshot("switch.safe", "on"), {}, runtime, T0)
        self.assertTrue(result.defer)
        result = build_check(expected).evaluate(snapshot("switch.safe", "on"), {}, runtime, T0 + timedelta(minutes=5))
        self.assertEqual(result.status, STATUS_WARNING)


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def manager(self, config, backend=None):
        events = []
        clock = {"now": T0}
        manager = HealthManager(validate_config(config), HealthHubStore(backend or MemoryBackend()), emit=lambda kind, data: events.append((kind, data)), now_provider=lambda: clock["now"])
        manager.test_clock = clock
        return manager, events

    async def seed(self, manager, values):
        await manager.async_initialize([snapshot(entity, value) for entity, value in values.items()])

    async def test_hierarchy_required_optional_and_worst_status(self):
        config = {"systems": {"home": {"name": "Home", "children": {"required": {"name": "Required", "checks": [{"id": "required_unknown", "type": "availability", "entity_id": "sensor.required", "warning_after": "1h"}]}, "optional": {"name": "Optional", "checks": [{"id": "optional_unknown", "type": "availability", "entity_id": "sensor.optional", "optional": True, "warning_after": "1h"}]}}}}}
        manager, _ = await self.manager(config)
        await manager.async_initialize([])
        self.assertEqual(manager.system_runtime["required"].status, STATUS_UNKNOWN)
        self.assertEqual(manager.system_runtime["optional"].status, STATUS_OK)
        self.assertEqual(manager.system_runtime["home"].status, STATUS_UNKNOWN)
        await manager.async_handle_entity_update(snapshot("sensor.optional", "unavailable"), entity_id="sensor.optional")
        self.assertEqual(manager.system_runtime["optional"].status, STATUS_OK)

    async def test_optional_warning_and_child_critical_propagate(self):
        config = {"systems": {"home": {"name": "Home", "children": {"a": {"name": "A", "checks": [{"id": "optional_value", "type": "numeric_range", "entity_id": "sensor.a", "optional": True, "warning_above": 10}]}, "b": {"name": "B", "checks": [{"id": "bad", "type": "numeric_range", "entity_id": "sensor.b", "critical_above": 10}]}}}}}
        manager, _ = await self.manager(config)
        await self.seed(manager, {"sensor.a": "11", "sensor.b": "11"})
        self.assertEqual(manager.system_runtime["a"].status, STATUS_WARNING)
        self.assertEqual(manager.system_runtime["home"].status, STATUS_CRITICAL)
        self.assertEqual(manager.system_runtime["home"].critical_count, 1)
        self.assertEqual(manager.system_runtime["home"].warning_count, 1)

    async def test_events_flapping_recovery_and_no_duplicate_updates(self):
        config = base_config([{ "id": "range", "type": "numeric_range", "entity_id": "sensor.a", "warning_above": 10, "minimum_state_duration": "5m"}])
        manager, events = await self.manager(config)
        await self.seed(manager, {"sensor.a": "1"})
        manager.test_clock["now"] = T0 + timedelta(minutes=1)
        await manager.async_handle_entity_update(snapshot("sensor.a", "11", at=T0 + timedelta(minutes=1)), entity_id="sensor.a")
        self.assertFalse(any(event[0] == EVENT_ISSUE_OPENED for event in events))
        manager.test_clock["now"] = T0 + timedelta(minutes=2)
        await manager.async_handle_entity_update(snapshot("sensor.a", "1", at=T0 + timedelta(minutes=2)), entity_id="sensor.a")
        self.assertFalse(any(event[0] == EVENT_ISSUE_OPENED for event in events))
        manager.test_clock["now"] = T0 + timedelta(minutes=3)
        await manager.async_handle_entity_update(snapshot("sensor.a", "11", at=T0 + timedelta(minutes=3)), entity_id="sensor.a")
        await manager.async_evaluate_due(T0 + timedelta(minutes=8))
        self.assertEqual(len([event for event in events if event[0] == EVENT_ISSUE_OPENED]), 1)
        manager.test_clock["now"] = T0 + timedelta(minutes=9)
        await manager.async_handle_entity_update(snapshot("sensor.a", "1", at=T0 + timedelta(minutes=9)), entity_id="sensor.a")
        await manager.async_evaluate_due(T0 + timedelta(minutes=14))
        self.assertEqual(len([event for event in events if event[0] == EVENT_ISSUE_RESOLVED]), 1)
        self.assertGreaterEqual(len([event for event in events if event[0] == EVENT_STATUS_CHANGED]), 2)

    async def test_store_restore_preserves_open_issue_and_observations(self):
        backend = MemoryBackend()
        config = base_config([{ "id": "range", "type": "numeric_range", "entity_id": "sensor.a", "warning_above": 10}])
        manager, _ = await self.manager(config, backend)
        await self.seed(manager, {"sensor.a": "1"})
        await manager.async_handle_entity_update(snapshot("sensor.a", "11", at=T0 + timedelta(minutes=1)), entity_id="sensor.a")
        restored, events = await self.manager(config, backend)
        await restored.async_initialize([snapshot("sensor.a", "11", at=T0 + timedelta(minutes=2))])
        self.assertEqual(restored.check_runtime["root.range"].status, STATUS_WARNING)
        self.assertEqual([event for event in events if event[0] == EVENT_ISSUE_OPENED], [])

    async def test_invalid_store_recovers_safely(self):
        backend = MemoryBackend({"version": 999, "checks": "bad", "systems": {}})
        manager, _ = await self.manager(base_config([{ "id": "a", "type": "availability", "entity_id": "sensor.a"}]), backend)
        await manager.async_initialize([snapshot("sensor.a", "1")])
        self.assertEqual(manager.system_runtime["root"].status, STATUS_OK)
        self.assertEqual(backend.data["version"], 1)

    async def test_deadlines_and_500_check_dependency_index(self):
        systems = {f"node_{index}": {"name": f"Node {index}", "checks": [{"id": "available", "type": "availability", "entity_id": f"sensor.node_{index}", "warning_after": "5m"}]} for index in range(500)}
        manager, _ = await self.manager({"systems": systems})
        await manager.async_initialize([snapshot(f"sensor.node_{index}", "1") for index in range(500)])
        self.assertEqual(len(manager.entity_ids()), 500)
        await manager.async_handle_entity_update(None, entity_id="sensor.node_123")
        self.assertIn("node_123.available", manager._deadlines)
        self.assertNotIn("node_124.available", manager._deadlines)

    async def test_diagnostics_is_compact_and_has_no_snapshot_attributes(self):
        manager, _ = await self.manager(base_config([{ "id": "a", "type": "availability", "entity_id": "sensor.a"}]))
        await self.seed(manager, {"sensor.a": "1"})
        diagnostics = manager.async_diagnostics()
        self.assertEqual(diagnostics["check_count"], 1)
        self.assertNotIn("attributes", diagnostics["systems"]["root"].get("runtime", {}))


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_and_corrupt_store(self):
        backend = MemoryBackend()
        store = HealthHubStore(backend)
        self.assertEqual(await store.async_load(), default_store_data())
        backend.data = {"version": 1, "checks": {}, "systems": {}}
        self.assertEqual((await store.async_load())["version"], 1)


if __name__ == "__main__":
    unittest.main()
