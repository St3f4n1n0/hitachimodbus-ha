"""Helpers shared by the platforms for reading config entry content."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DISCOVERED_UNITS,
    CONF_UNIT_TYPES,
    UNIT_TYPE_VRF,
    UNIT_TYPES,
)


def resolve_units(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return the configured units with their effective unit type.

    Discovery stores the units in ``entry.data``; the options flow can later
    change a unit's type without re-running discovery, and records that in
    ``entry.options``.  Everything that needs to know a slot's type must go
    through here so the two never drift apart.
    """
    overrides: dict[str, str] = entry.options.get(CONF_UNIT_TYPES, {})

    units: list[dict[str, Any]] = []
    for stored in entry.data.get(CONF_DISCOVERED_UNITS, []):
        unit = dict(stored)
        slot_id = unit["slot_id"]
        unit_type = overrides.get(str(slot_id), unit.get("unit_type", UNIT_TYPE_VRF))
        if unit_type not in UNIT_TYPES:
            unit_type = UNIT_TYPE_VRF
        unit["unit_type"] = unit_type
        units.append(unit)

    return units
