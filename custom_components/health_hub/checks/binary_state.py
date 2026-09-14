"""Ergonomic expected-state check restricted to on/off."""

from __future__ import annotations

from .expected_state import ExpectedStateCheck


class BinaryStateCheck(ExpectedStateCheck):
    """Expected-state implementation for binary_sensor and switch entities."""
