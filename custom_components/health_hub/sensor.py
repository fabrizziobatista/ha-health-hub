"""Enum sensor entities representing Health Hub systems."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from .const import DATA_MANAGER, DOMAIN, STATUSES


async def async_setup_entry(hass: Any, entry: Any, async_add_entities) -> None:
    """Create one compact enum sensor for every configured system."""
    manager = hass.data[DOMAIN][DATA_MANAGER]
    async_add_entities([HealthSystemSensor(manager, system_id, entry.entry_id) for system_id in manager.system_defs])


class HealthSystemSensor(SensorEntity):
    """Home Assistant adapter around one logical system managed centrally."""

    _attr_has_entity_name = True
    _attr_options = list(STATUSES)
    _attr_should_poll = False

    def __init__(self, manager: Any, system_id: str, entry_id: str) -> None:
        self._manager = manager
        self._system_id = system_id
        self._attr_unique_id = f"{entry_id}_{system_id}"
        self._attr_suggested_object_id = f"health_{system_id}"
        self._attr_name = manager.system_defs[system_id].name
        self._attr_icon = manager.system_defs[system_id].icon or "mdi:heart-pulse"
        self._attr_device_class = SensorDeviceClass.ENUM
        self._remove_listener = None

    @property
    def native_value(self) -> str:
        return self._manager.system_runtime[self._system_id].status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._manager.system_attributes(self._system_id)

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self._manager.add_listener(self._async_manager_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None

    def _async_manager_update(self, system_id: str) -> None:
        if system_id == self._system_id:
            self.async_write_ha_state()
