"""Small versioned persistence boundary for Health Hub runtime state."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Protocol

from .const import STORE_VERSION


class StoreBackend(Protocol):
    """Minimum subset of HA Store used by this wrapper."""

    async def async_load(self) -> Any: ...
    async def async_save(self, data: Any) -> None: ...


def default_store_data() -> dict[str, Any]:
    return {"version": STORE_VERSION, "checks": {}, "systems": {}}


class HealthHubStore:
    """Validate Store content and persist only runtime state, never YAML config."""

    def __init__(self, backend: StoreBackend) -> None:
        self._backend = backend
        self.data = default_store_data()

    async def async_load(self) -> dict[str, Any]:
        loaded = await self._backend.async_load()
        if loaded is None:
            self.data = default_store_data()
        elif (
            not isinstance(loaded, Mapping)
            or loaded.get("version") != STORE_VERSION
            or not isinstance(loaded.get("checks"), Mapping)
            or not isinstance(loaded.get("systems"), Mapping)
        ):
            self.data = default_store_data()
        else:
            self.data = {
                "version": STORE_VERSION,
                "checks": deepcopy(dict(loaded["checks"])),
                "systems": deepcopy(dict(loaded["systems"])),
            }
        return deepcopy(self.data)

    async def async_save(self) -> None:
        await self._backend.async_save(deepcopy(self.data))
