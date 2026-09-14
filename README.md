# Health Hub

Health Hub is a generic Home Assistant custom integration that turns a
declarative tree of health checks into compact enum sensors and events.

It has no built-in knowledge of a house, vendor, room, entity ID, notification
provider, or dashboard. A site supplies those details only in its own YAML.

## Status

`0.1.0` is the first functional release. It provides local evaluation,
hierarchical propagation, persistence of minimum runtime state, and event
contracts. It does not send notifications or control equipment.

Published states are:

| State | Meaning |
| --- | --- |
| `ok` | Every relevant required check is healthy. |
| `warning` | The system works, but needs attention. |
| `critical` | A confirmed functional failure or significant risk exists. |
| `unknown` | There is not enough reliable information to assess health. |

Precedence is `critical > warning > unknown > ok`.

## Installation

Install the component under:

```text
config/custom_components/health_hub/
```

Restart Home Assistant, then add **Health Hub** from **Settings → Devices &
Services**. The Config Flow creates one lifecycle/diagnostics entry. Systems
and checks remain YAML-owned.

For a private HACS custom repository, add the repository URL as an
**Integration** repository. No public HACS catalogue submission is intended.

## YAML configuration

```yaml
health_hub:
  systems:
    home:
      name: Home
      icon: mdi:home-heart
      children:
        climate:
          name: Climate
          checks:
            - id: controller_available
              type: availability
              entity_id: binary_sensor.example_controller
              warning_after: 5m
              critical_after: 30m

            - id: controller_fresh
              type: freshness
              entity_id: sensor.example_temperature
              max_age_warning: 30m
              max_age_critical: 2h

            - id: sensor_battery
              type: battery
              entity_id: sensor.example_battery
              warning_below: 20
              critical_below: 10
```

System IDs must use lowercase letters, numbers, and underscores. They are
globally unique in one configuration, making `sensor.health_<system_id>`
stable. Check IDs are unique within their system.

Each system has `name`, optional `icon`, optional `checks`, and optional
`children`. A system must contain at least one check or child.

## Checks

| Type | Purpose |
| --- | --- |
| `availability` | Missing, `unknown`, or `unavailable` entity state. |
| `freshness` | Age of `last_updated`, not `last_changed`. |
| `stale_value` | Explicit numeric observation-window check. |
| `battery` | Numeric percentage with warning/critical lower bounds. |
| `numeric_range` | Optional upper/lower warning and critical limits. |
| `expected_state` | Any expected HA state or list of states. |
| `binary_state` | Restricted expected state for `on` or `off`. |

`template` is intentionally rejected in v0.1.

All checks are required by default. Set `optional: true` when lack of data
must not make the parent `unknown`; a valid optional warning or critical still
propagates normally.

All checks may set `minimum_state_duration` to stabilize a candidate state.
`availability` and `expected_state` also support `warning_after` and optional
`critical_after` grace periods.

`stale_value` requires all of:

```yaml
- id: value_stalled
  type: stale_value
  entity_id: sensor.example_measurement
  observation_window: 6h
  minimum_changes: 2
  minimum_delta: 10
  active_when:
    entity_id: binary_sensor.example_active_window
    state: "on"
```

It is never inferred automatically.

## Entities and drill-down

Each system becomes an enum sensor without a unit or `state_class`.
Attributes remain compact: issue counts, summary, worst child, primary issue,
last known healthy timestamp, and last Hub change. Parent sensors never carry
large issue histories; open child sensors for drill-down.

Health Hub does not create devices for logical systems.

## Events

The integration emits only state transitions:

- `health_hub_status_changed`
- `health_hub_issue_opened`
- `health_hub_issue_resolved`

Payloads contain stable system/check IDs, old/new status, entity ID, concise
reason, timestamp, and recovery duration where applicable. Events are not
emitted for ordinary state updates without a health transition.

Use normal Home Assistant automations to route these events to any
notification component. Health Hub has no notification dependency.

## Persistence, restart, and performance

The Store contains only schema version, pending state, incident timestamps,
last healthy timestamps, and the minimal stale-value observations. It never
stores YAML configuration, credentials, notification payloads, or telemetry
history.

On restart the component restores that small runtime state and recalculates
from current HA entity states without replaying already-open incidents.

Entity state listeners are indexed by dependency. Freshness and stabilization
use the nearest deadline rather than global minute polling.

YAML reload is deliberately deferred to v0.2: v0.1 validates YAML atomically
at setup and never applies a partial configuration.

## Diagnostics

Config-entry diagnostics include version, systems, check IDs, aggregate state,
counts, and timestamps. Sensitive key names are redacted; raw entity attributes
and telemetry history are excluded.

## Development

```bash
python -m compileall -q custom_components
python -m unittest discover -s tests -v
```

CI additionally runs pytest, Ruff, and JSON validation.

## Roadmap

- v0.2: atomic YAML reload and maintenance mode.
- v0.3: richer diagnostics and optional controlled template escape hatch.
- No acknowledgement or direct notification delivery is planned for the core.
