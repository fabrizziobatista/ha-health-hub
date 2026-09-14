"""Generic Health Hub check implementations."""

from __future__ import annotations

from ..const import (
    CHECK_AVAILABILITY,
    CHECK_BATTERY,
    CHECK_BINARY_STATE,
    CHECK_EXPECTED_STATE,
    CHECK_FRESHNESS,
    CHECK_NUMERIC_RANGE,
    CHECK_STALE_VALUE,
)
from ..models import CheckDefinition
from .availability import AvailabilityCheck
from .base import BaseCheck
from .battery import BatteryCheck
from .binary_state import BinaryStateCheck
from .expected_state import ExpectedStateCheck
from .freshness import FreshnessCheck
from .numeric_range import NumericRangeCheck
from .stale_value import StaleValueCheck


def build_check(definition: CheckDefinition) -> BaseCheck:
    """Return the implementation selected by a validated type."""
    implementations = {
        CHECK_AVAILABILITY: AvailabilityCheck,
        CHECK_FRESHNESS: FreshnessCheck,
        CHECK_STALE_VALUE: StaleValueCheck,
        CHECK_BATTERY: BatteryCheck,
        CHECK_NUMERIC_RANGE: NumericRangeCheck,
        CHECK_EXPECTED_STATE: ExpectedStateCheck,
        CHECK_BINARY_STATE: BinaryStateCheck,
    }
    return implementations[definition.type](definition)
