"""Helpers shared by the platforms for reading config entry content."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DISCOVERED_UNITS,
    CONF_DRY_FAN,
    CONF_UNIT_TYPES,
    DEFAULT_DRY_FAN,
    DRY_FAN_OPTIONS,
    UNIT_TYPE_VRF,
    UNIT_TYPES,
)


def resolve_units(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return the configured units with their effective settings applied.

    Discovery stores the units in ``entry.data``; the options flow can later
    change a unit's type and its Dry-mode fan behaviour without re-running
    discovery, and records those in ``entry.options``.  Everything that needs
    to know a slot's settings must go through here so the two never drift
    apart.
    """
    type_overrides: dict[str, str] = entry.options.get(CONF_UNIT_TYPES, {})
    dry_fan_overrides: dict[str, str] = entry.options.get(CONF_DRY_FAN, {})

    units: list[dict[str, Any]] = []
    for stored in entry.data.get(CONF_DISCOVERED_UNITS, []):
        unit = dict(stored)
        slot = str(unit["slot_id"])

        unit_type = type_overrides.get(slot, unit.get("unit_type", UNIT_TYPE_VRF))
        if unit_type not in UNIT_TYPES:
            unit_type = UNIT_TYPE_VRF
        unit["unit_type"] = unit_type

        dry_fan = dry_fan_overrides.get(slot, DEFAULT_DRY_FAN)
        if dry_fan not in DRY_FAN_OPTIONS:
            dry_fan = DEFAULT_DRY_FAN
        unit[CONF_DRY_FAN] = dry_fan

        units.append(unit)

    return units
