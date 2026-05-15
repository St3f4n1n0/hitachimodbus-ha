"""Switch entities for ATW-specific controls (Hitachi ModBus)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATW_OFFSET_ANTILEG_RUN_CMD,
    ATW_OFFSET_ANTILEG_STATUS,
    ATW_OFFSET_DHW_BOOST_CMD,
    ATW_OFFSET_DHW_BOOST_STATUS,
    ATW_OFFSET_DHW_DEMAND_CMD,
    ATW_OFFSET_DHW_DEMAND_STATUS,
    ATW_OFFSET_DHWT_RUN_CMD,
    ATW_OFFSET_DHWT_STATUS,
    ATW_READ_START,
    DOMAIN,
    UNIT_TYPE_ATW,
    UNIT_TYPE_VRF,
)
from .coordinator import HitachiModbusCoordinator


@dataclass(frozen=True)
class _SwitchDesc:
    key: str
    name: str
    cmd_offset: int
    status_offset: int
    icon: str


_ATW_SWITCHES: tuple[_SwitchDesc, ...] = (
    _SwitchDesc("dhwt_run",    "DHWT Run/Stop",       ATW_OFFSET_DHWT_RUN_CMD,   ATW_OFFSET_DHWT_STATUS,      "mdi:water-boiler"),
    _SwitchDesc("dhw_boost",   "DHW Boost",            ATW_OFFSET_DHW_BOOST_CMD,  ATW_OFFSET_DHW_BOOST_STATUS, "mdi:water-boiler-alert"),
    _SwitchDesc("dhw_demand",  "DHW High Demand Mode", ATW_OFFSET_DHW_DEMAND_CMD, ATW_OFFSET_DHW_DEMAND_STATUS,"mdi:water-plus"),
    _SwitchDesc("antileg_run", "AntiLegionella",       ATW_OFFSET_ANTILEG_RUN_CMD,ATW_OFFSET_ANTILEG_STATUS,   "mdi:bacteria"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HitachiModbusCoordinator = hass.data[DOMAIN][entry.entry_id]
    units: list[dict] = entry.data.get("discovered_units", [])

    async_add_entities(
        HitachiATWSwitch(coordinator, entry, u["slot_id"], u["ou"], u["iu"], desc)
        for u in units
        if u.get("unit_type", UNIT_TYPE_VRF) == UNIT_TYPE_ATW
        for desc in _ATW_SWITCHES
    )


class HitachiATWSwitch(CoordinatorEntity[HitachiModbusCoordinator], SwitchEntity):
    """Binary control for an ATW function (DHWT, DHW Boost, AntiLegionella…)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HitachiModbusCoordinator,
        entry: ConfigEntry,
        slot_id: int,
        ou: int,
        iu: int,
        desc: _SwitchDesc,
    ) -> None:
        super().__init__(coordinator)
        self._slot_id = slot_id
        self._ou = ou
        self._iu = iu
        self._desc = desc
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_slot{slot_id}_{desc.key}"
        self._attr_name = desc.name
        self._attr_icon = desc.icon

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_slot{self._slot_id}")},
        )

    def _atw_reg(self, offset: int) -> int | None:
        data = self.coordinator.data
        if data is None:
            return None
        regs = data.get(self._slot_id)
        if regs is None:
            return None
        idx = offset - ATW_READ_START
        if idx < 0 or idx >= len(regs):
            return None
        return regs[idx]

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return data is not None and self._slot_id in data

    @property
    def is_on(self) -> bool | None:
        val = self._atw_reg(self._desc.status_offset)
        return bool(val) if val is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_unit_register(
            self._slot_id, self._desc.cmd_offset, 1
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_unit_register(
            self._slot_id, self._desc.cmd_offset, 0
        )
        await self.coordinator.async_request_refresh()
