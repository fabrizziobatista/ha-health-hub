"""Health Hub integration setup and efficient Home Assistant event wiring."""

from __future__ import annotations

import logging
from typing import Any

from .const import DATA_MANAGER, DATA_YAML, DOMAIN, STORE_VERSION
from .manager import HealthManager
from .models import EntitySnapshot
from .schema import ConfigValidationError, validate_config
from .store import HealthHubStore

_LOGGER = logging.getLogger(__name__)


def _snapshot(state: Any, entity_id: str) -> EntitySnapshot | None:
    if state is None:
        return None
    return EntitySnapshot(entity_id, state.state, state.last_updated, dict(state.attributes))


async def async_setup(hass: Any, config: dict[str, Any]) -> bool:
    """Retain raw YAML until the singleton config entry starts."""
    hass.data.setdefault(DOMAIN, {})[DATA_YAML] = config.get(DOMAIN)
    return True


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up a singleton Health Hub with YAML-owned systems and checks."""
    from homeassistant.core import callback
    from homeassistant.helpers.event import (
        async_track_point_in_time,
        async_track_state_change_event,
    )
    from homeassistant.helpers.storage import Store

    domain_data = hass.data.setdefault(DOMAIN, {})
    raw_yaml = domain_data.get(DATA_YAML)
    if raw_yaml is None:
        systems = ()
        _LOGGER.info("Health Hub is configured without YAML systems")
    else:
        try:
            systems = validate_config(raw_yaml)
        except ConfigValidationError as err:
            _LOGGER.error("Health Hub YAML is invalid; no systems were activated: %s", err)
            systems = ()

    def _emit(event_type: str, data: dict[str, Any]) -> None:
        hass.bus.async_fire(event_type, data)

    store = HealthHubStore(Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}"))
    manager = HealthManager(systems, store, emit=_emit)
    domain_data[DATA_MANAGER] = manager
    await manager.async_initialize(
        _snapshot(hass.states.get(entity_id), entity_id) for entity_id in manager.entity_ids()
    )

    async def _async_state_changed(event: Any) -> None:
        entity_id = event.data["entity_id"]
        await manager.async_handle_entity_update(
            _snapshot(event.data.get("new_state"), entity_id), entity_id=entity_id
        )
        _schedule_deadline()

    @callback
    def _state_changed(event: Any) -> None:
        """Bridge the synchronous HA listener into the async manager."""
        hass.async_create_task(_async_state_changed(event))

    unsub_state = (
        async_track_state_change_event(hass, list(manager.entity_ids()), _state_changed)
        if manager.entity_ids()
        else lambda: None
    )
    domain_data["unsub_state"] = unsub_state
    domain_data["unsub_deadline"] = None

    def _schedule_deadline() -> None:
        previous = domain_data.get("unsub_deadline")
        if previous:
            previous()
        deadline = manager.next_deadline()
        if deadline is None:
            domain_data["unsub_deadline"] = None
            return

        async def _async_deadline(now: Any) -> None:
            await manager.async_evaluate_due(now)
            _schedule_deadline()

        @callback
        def _deadline(now: Any) -> None:
            hass.async_create_task(_async_deadline(now))

        domain_data["unsub_deadline"] = async_track_point_in_time(hass, _deadline, deadline)

    _schedule_deadline()
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload listeners, deadline scheduler, sensors, and singleton runtime data."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if not unload_ok:
        return False
    domain_data = hass.data.get(DOMAIN, {})
    for key in ("unsub_state", "unsub_deadline"):
        callback = domain_data.pop(key, None)
        if callback:
            callback()
    domain_data.pop(DATA_MANAGER, None)
    return True
