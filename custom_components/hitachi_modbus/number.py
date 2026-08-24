"""Number entities for ATW temperature setpoints (Hitachi ModBus)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATW_OFFSET_ANTILEG_SETTEMP_CMD,
    ATW_OFFSET_ANTILEG_SETTEMP_ST,
    ATW_OFFSET_COOL_ECO_OFFSET_CMD,
    ATW_OFFSET_COOL_ECO_OFFSET_ST,
    ATW_OFFSET_COOL_SETTEMP_CMD,
    ATW_OFFSET_COOL_SETTEMP_ST,
    ATW_OFFSET_HEAT_ECO_OFFSET_CMD,
    ATW_OFFSET_HEAT_ECO_OFFSET_ST,
    ATW_OFFSET_HEAT_SETTEMP_CMD,
    ATW_OFFSET_HEAT_SETTEMP_ST,
    ATW_READ_START,
    DOMAIN,
    UNIT_TYPE_ATW,
)
from .coordinator import HitachiModbusCoordinator
from .helpers import resolve_units


@dataclass(frozen=True)
class _NumberDesc:
    key: str
    name: str
    cmd_offset: int
    status_offset: int
    min_value: float
    max_value: float
    icon: str


_ATW_NUMBERS: tuple[_NumberDesc, ...] = (
    _NumberDesc(
        "circuit1_heat_settemp",
        "Circuit 1 Heating Setpoint",
        ATW_OFFSET_HEAT_SETTEMP_CMD,
        ATW_OFFSET_HEAT_SETTEMP_ST,
        min_value=0.0,
        max_value=80.0,
        icon="mdi:radiator",
    ),
    _NumberDesc(
        "circuit1_cool_settemp",
        "Circuit 1 Cooling Setpoint",
        ATW_OFFSET_COOL_SETTEMP_CMD,
        ATW_OFFSET_COOL_SETTEMP_ST,
        min_value=0.0,
        max_value=80.0,
        icon="mdi:snowflake-thermometer",
    ),
    _NumberDesc(
        "heat_eco_offset",
        "Circuit 1 Heat ECO Offset",
        ATW_OFFSET_HEAT_ECO_OFFSET_CMD,
        ATW_OFFSET_HEAT_ECO_OFFSET_ST,
        min_value=1.0,
        max_value=10.0,
        icon="mdi:leaf-circle",
    ),
    _NumberDesc(
        "cool_eco_offset",
        "Circuit 1 Cool ECO Offset",
        ATW_OFFSET_COOL_ECO_OFFSET_CMD,
        ATW_OFFSET_COOL_ECO_OFFSET_ST,
        min_value=1.0,
        max_value=10.0,
        icon="mdi:leaf-circle-outline",
    ),
    _NumberDesc(
        "antileg_settemp",
        "AntiLegionella Setting Temperature",
        ATW_OFFSET_ANTILEG_SETTEMP_CMD,
        ATW_OFFSET_ANTILEG_SETTEMP_ST,
        min_value=0.0,
        max_value=80.0,
        icon="mdi:thermometer-alert",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HitachiModbusCoordinator = hass.data[DOMAIN][entry.entry_id]
    units: list[dict] = resolve_units(entry)

    async_add_entities(
        HitachiATWNumber(coordinator, entry, u["slot_id"], u["ou"], u["iu"], desc)
        for u in units
        if u["unit_type"] == UNIT_TYPE_ATW
        for desc in _ATW_NUMBERS
    )


class HitachiATWNumber(CoordinatorEntity[HitachiModbusCoordinator], NumberEntity):
    """Numeric setpoint for an ATW function (DHWT temperature, AntiLegionella…)."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 1.0

    def __init__(
        self,
        coordinator: HitachiModbusCoordinator,
        entry: ConfigEntry,
        slot_id: int,
        ou: int,
        iu: int,
        desc: _NumberDesc,
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
        self._attr_native_min_value = desc.min_value
        self._attr_native_max_value = desc.max_value

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
        return (
            super().available and data is not None and self._slot_id in data
        )

    @property
    def native_value(self) -> float | None:
        val = self._atw_reg(self._desc.status_offset)
        return float(val) if val is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write_unit_register(
            self._slot_id, self._desc.cmd_offset, int(value)
        )
        await self.coordinator.async_request_refresh()
