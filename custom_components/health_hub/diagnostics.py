"""Safe config-entry diagnostics for Health Hub."""

from __future__ import annotations

from typing import Any

from .const import DATA_MANAGER, DATA_YAML, DOMAIN, VERSION


async def async_get_config_entry_diagnostics(hass: Any, entry: Any) -> dict[str, Any]:
    """Return runtime structure without secrets, state attributes, or telemetry history."""
    from homeassistant.helpers.redact import async_redact_data

    manager = hass.data[DOMAIN][DATA_MANAGER]
    raw_yaml = hass.data.get(DOMAIN, {}).get(DATA_YAML) or {}
    return async_redact_data(
        {
            "version": VERSION,
            "entry_id": entry.entry_id,
            "yaml": raw_yaml,
            "runtime": manager.async_diagnostics(),
        },
        {"password", "secret", "token", "api_key", "access_token", "authorization"},
    )
