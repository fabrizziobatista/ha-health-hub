"""Constants for Health Hub."""

from __future__ import annotations

DOMAIN = "health_hub"
VERSION = "0.1.0"

CONF_SYSTEMS = "systems"
CONF_NAME = "name"
CONF_ICON = "icon"
CONF_CHECKS = "checks"
CONF_CHILDREN = "children"
CONF_ID = "id"
CONF_TYPE = "type"
CONF_ENTITY_ID = "entity_id"
CONF_OPTIONAL = "optional"
CONF_MINIMUM_STATE_DURATION = "minimum_state_duration"
CONF_ACTIVE_WHEN = "active_when"

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_CRITICAL = "critical"
STATUS_UNKNOWN = "unknown"
STATUSES = (STATUS_OK, STATUS_WARNING, STATUS_CRITICAL, STATUS_UNKNOWN)
STATUS_RANK = {STATUS_OK: 0, STATUS_UNKNOWN: 1, STATUS_WARNING: 2, STATUS_CRITICAL: 3}

CHECK_AVAILABILITY = "availability"
CHECK_FRESHNESS = "freshness"
CHECK_STALE_VALUE = "stale_value"
CHECK_BATTERY = "battery"
CHECK_NUMERIC_RANGE = "numeric_range"
CHECK_EXPECTED_STATE = "expected_state"
CHECK_BINARY_STATE = "binary_state"
CHECK_TYPES = (
    CHECK_AVAILABILITY,
    CHECK_FRESHNESS,
    CHECK_STALE_VALUE,
    CHECK_BATTERY,
    CHECK_NUMERIC_RANGE,
    CHECK_EXPECTED_STATE,
    CHECK_BINARY_STATE,
)

EVENT_STATUS_CHANGED = "health_hub_status_changed"
EVENT_ISSUE_OPENED = "health_hub_issue_opened"
EVENT_ISSUE_RESOLVED = "health_hub_issue_resolved"

DATA_MANAGER = "manager"
DATA_YAML = "yaml"
STORE_VERSION = 1
