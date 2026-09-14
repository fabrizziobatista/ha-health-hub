"""Strict, Home-Assistant-independent YAML validation for Health Hub."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Mapping

from .const import (
    CHECK_AVAILABILITY,
    CHECK_BATTERY,
    CHECK_BINARY_STATE,
    CHECK_EXPECTED_STATE,
    CHECK_FRESHNESS,
    CHECK_NUMERIC_RANGE,
    CHECK_STALE_VALUE,
    CHECK_TYPES,
    CONF_ACTIVE_WHEN,
    CONF_CHECKS,
    CONF_CHILDREN,
    CONF_ENTITY_ID,
    CONF_ICON,
    CONF_ID,
    CONF_MINIMUM_STATE_DURATION,
    CONF_NAME,
    CONF_OPTIONAL,
    CONF_SYSTEMS,
    CONF_TYPE,
)
from .models import CheckDefinition, SystemDefinition

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_DURATION_RE = re.compile(r"^(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>s|m|h|d)$", re.I)


class ConfigValidationError(ValueError):
    """Raised when declarative Health Hub configuration is invalid."""


def parse_duration(value: object, field: str) -> timedelta:
    """Parse a duration such as ``5m`` without HA dependencies."""
    if isinstance(value, timedelta):
        result = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result = timedelta(seconds=float(value))
    elif isinstance(value, str):
        match = _DURATION_RE.fullmatch(value.strip())
        if not match:
            raise ConfigValidationError(f"{field} must use a duration such as 30s, 5m, 2h, or 1d")
        multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match["unit"].lower()]
        result = timedelta(seconds=float(match["value"]) * multiplier)
    else:
        raise ConfigValidationError(f"{field} must be a duration")
    if result.total_seconds() < 0:
        raise ConfigValidationError(f"{field} cannot be negative")
    return result


def _id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ConfigValidationError(f"{field} must use lowercase letters, numbers, and underscores")
    return value


def _entity_id(value: object, field: str) -> str:
    if not isinstance(value, str) or "." not in value or value.strip() != value:
        raise ConfigValidationError(f"{field} must be a Home Assistant entity_id")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigValidationError(f"{field} must be numeric")
    return float(value)


def _optional_duration(data: Mapping[str, Any], key: str) -> timedelta | None:
    return parse_duration(data[key], key) if key in data else None


def _active_when(value: object) -> tuple[str, tuple[str, ...]] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value).difference({"entity_id", "state"}):
        raise ConfigValidationError("active_when accepts only entity_id and state")
    entity_id = _entity_id(value.get("entity_id"), "active_when.entity_id")
    raw_state = value.get("state")
    states = (
        (raw_state,)
        if isinstance(raw_state, str)
        else tuple(raw_state)
        if isinstance(raw_state, list)
        else ()
    )
    if not states or any(not isinstance(item, str) or not item for item in states):
        raise ConfigValidationError("active_when.state must be a state string or non-empty list")
    return entity_id, states


def _validate_common(raw: Mapping[str, Any], system_id: str, seen: set[str]):
    check_id = _id(raw.get(CONF_ID), f"systems.{system_id}.checks.id")
    if check_id in seen:
        raise ConfigValidationError(f"duplicate check id {check_id} in system {system_id}")
    seen.add(check_id)
    check_type = raw.get(CONF_TYPE)
    if check_type not in CHECK_TYPES:
        raise ConfigValidationError(f"check {check_id} has unsupported type {check_type!r}")
    entity_id = _entity_id(raw.get(CONF_ENTITY_ID), f"check {check_id}.entity_id")
    optional = raw.get(CONF_OPTIONAL, False)
    if not isinstance(optional, bool):
        raise ConfigValidationError(f"check {check_id}.optional must be boolean")
    minimum = parse_duration(
        raw.get(CONF_MINIMUM_STATE_DURATION, "0s"), f"check {check_id}.minimum_state_duration"
    )
    return (
        check_id,
        check_type,
        entity_id,
        optional,
        minimum,
        _active_when(raw.get(CONF_ACTIVE_WHEN)),
    )


def _validate_check(raw: object, system_id: str, seen: set[str]) -> CheckDefinition:
    if not isinstance(raw, Mapping):
        raise ConfigValidationError(f"systems.{system_id}.checks must contain objects")
    check_id, check_type, entity_id, optional, minimum, active_when = _validate_common(
        raw, system_id, seen
    )
    common = {
        CONF_ID,
        CONF_TYPE,
        CONF_ENTITY_ID,
        CONF_OPTIONAL,
        CONF_MINIMUM_STATE_DURATION,
        CONF_ACTIVE_WHEN,
    }
    params = {key: value for key, value in raw.items() if key not in common}

    if check_type in (CHECK_AVAILABILITY, CHECK_EXPECTED_STATE, CHECK_BINARY_STATE):
        allowed = {"warning_after", "critical_after"}
        if check_type in (CHECK_EXPECTED_STATE, CHECK_BINARY_STATE):
            allowed.add("expected")
        if set(params).difference(allowed):
            raise ConfigValidationError(f"check {check_id} has unsupported parameters")
        warning = _optional_duration(params, "warning_after") or timedelta(0)
        critical = _optional_duration(params, "critical_after")
        if critical is not None and critical < warning:
            raise ConfigValidationError(
                f"check {check_id}.critical_after must not be before warning_after"
            )
        params["warning_after"], params["critical_after"] = warning, critical
        if check_type in (CHECK_EXPECTED_STATE, CHECK_BINARY_STATE):
            expected = params.get("expected")
            if check_type == CHECK_BINARY_STATE and expected not in ("on", "off"):
                raise ConfigValidationError(
                    f"binary_state check {check_id}.expected must be on or off"
                )
            if check_type == CHECK_EXPECTED_STATE:
                values = (
                    (expected,)
                    if isinstance(expected, str)
                    else tuple(expected)
                    if isinstance(expected, list)
                    else ()
                )
                if not values or any(not isinstance(item, str) or not item for item in values):
                    raise ConfigValidationError(
                        f"expected_state check {check_id}.expected must be a string or non-empty list"
                    )
                params["expected"] = values
            elif check_type == CHECK_BINARY_STATE:
                params["expected"] = (expected,)

    elif check_type == CHECK_FRESHNESS:
        if set(params).difference({"max_age_warning", "max_age_critical"}):
            raise ConfigValidationError(f"check {check_id} has unsupported parameters")
        warning, critical = (
            _optional_duration(params, "max_age_warning"),
            _optional_duration(params, "max_age_critical"),
        )
        if warning is None and critical is None:
            raise ConfigValidationError(
                f"freshness check {check_id} needs max_age_warning and/or max_age_critical"
            )
        if warning is not None and critical is not None and critical < warning:
            raise ConfigValidationError(
                f"check {check_id}.max_age_critical must not be before max_age_warning"
            )
        params["max_age_warning"], params["max_age_critical"] = warning, critical

    elif check_type == CHECK_STALE_VALUE:
        if set(params).difference({"observation_window", "minimum_changes", "minimum_delta"}):
            raise ConfigValidationError(f"check {check_id} has unsupported parameters")
        window = _optional_duration(params, "observation_window")
        changes = params.get("minimum_changes")
        if window is None or window.total_seconds() <= 0:
            raise ConfigValidationError(
                f"stale_value check {check_id}.observation_window must be positive"
            )
        if isinstance(changes, bool) or not isinstance(changes, int) or changes < 1:
            raise ConfigValidationError(
                f"stale_value check {check_id}.minimum_changes must be an integer >= 1"
            )
        delta = _number(params.get("minimum_delta"), f"stale_value check {check_id}.minimum_delta")
        if delta < 0:
            raise ConfigValidationError(
                f"stale_value check {check_id}.minimum_delta cannot be negative"
            )
        params["observation_window"], params["minimum_delta"] = window, delta

    elif check_type == CHECK_BATTERY:
        if set(params).difference({"warning_below", "critical_below"}):
            raise ConfigValidationError(f"check {check_id} has unsupported parameters")
        warning = _number(params.get("warning_below"), f"battery check {check_id}.warning_below")
        critical = _number(params.get("critical_below"), f"battery check {check_id}.critical_below")
        if not 0 <= critical <= warning <= 100:
            raise ConfigValidationError(
                f"battery check {check_id} needs 0 <= critical_below <= warning_below <= 100"
            )
        params["warning_below"], params["critical_below"] = warning, critical

    elif check_type == CHECK_NUMERIC_RANGE:
        allowed = {"warning_below", "critical_below", "warning_above", "critical_above"}
        if set(params).difference(allowed) or not params:
            raise ConfigValidationError(
                f"numeric_range check {check_id} needs one or more numeric limits"
            )
        for key in tuple(params):
            params[key] = _number(params[key], f"numeric_range check {check_id}.{key}")
        if (
            "warning_below" in params
            and "critical_below" in params
            and params["critical_below"] > params["warning_below"]
        ):
            raise ConfigValidationError(
                f"numeric_range check {check_id}.critical_below must be <= warning_below"
            )
        if (
            "warning_above" in params
            and "critical_above" in params
            and params["critical_above"] < params["warning_above"]
        ):
            raise ConfigValidationError(
                f"numeric_range check {check_id}.critical_above must be >= warning_above"
            )

    return CheckDefinition(check_id, check_type, entity_id, optional, minimum, active_when, params)


def _validate_systems(raw: object, seen: set[str]) -> tuple[SystemDefinition, ...]:
    if not isinstance(raw, Mapping) or not raw:
        raise ConfigValidationError("systems must be a non-empty mapping")
    systems: list[SystemDefinition] = []
    for system_id, value in raw.items():
        stable_id = _id(system_id, "system id")
        if stable_id in seen:
            raise ConfigValidationError(
                f"duplicate system id {stable_id}; ids must be globally unique"
            )
        seen.add(stable_id)
        if not isinstance(value, Mapping) or set(value).difference(
            {CONF_NAME, CONF_ICON, CONF_CHECKS, CONF_CHILDREN}
        ):
            raise ConfigValidationError(f"system {stable_id} has invalid properties")
        name, icon = value.get(CONF_NAME), value.get(CONF_ICON)
        if not isinstance(name, str) or not name.strip():
            raise ConfigValidationError(f"system {stable_id}.name is required")
        if icon is not None and (not isinstance(icon, str) or not icon.startswith("mdi:")):
            raise ConfigValidationError(f"system {stable_id}.icon must be an mdi icon")
        checks_raw = value.get(CONF_CHECKS, [])
        if not isinstance(checks_raw, list):
            raise ConfigValidationError(f"system {stable_id}.checks must be a list")
        check_ids: set[str] = set()
        checks = tuple(_validate_check(item, stable_id, check_ids) for item in checks_raw)
        children = _validate_systems(value[CONF_CHILDREN], seen) if CONF_CHILDREN in value else ()
        if not checks and not children:
            raise ConfigValidationError(f"system {stable_id} needs checks or children")
        systems.append(SystemDefinition(stable_id, name.strip(), icon, checks, children))
    return tuple(systems)


def validate_config(config: object) -> tuple[SystemDefinition, ...]:
    """Validate the content beneath ``health_hub:`` atomically."""
    if not isinstance(config, Mapping) or set(config).difference({CONF_SYSTEMS}):
        raise ConfigValidationError("health_hub accepts only systems in v0.1")
    return _validate_systems(config.get(CONF_SYSTEMS), set())
