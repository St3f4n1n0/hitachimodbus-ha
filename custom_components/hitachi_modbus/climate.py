"""Climate entity for Hitachi indoor units via ModBus Gateway."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_HOST,
    DOMAIN,
    FAN_MODES_BY_TYPE,
    HA_FAN_TO_MODBUS,
    HA_MODE_TO_MODBUS,
    HVAC_MODES_BY_TYPE,
    MODBUS_TO_HA_FAN,
    MODBUS_TO_HA_MODE,
    OFFSET_ALARM_CODE,
    OFFSET_FAN_CMD,
    OFFSET_FAN_STATUS,
    OFFSET_GAS_PIPE_TEMP,
    OFFSET_INLET_TEMP,
    OFFSET_LIQUID_PIPE_TEMP,
    OFFSET_MODE_CMD,
    OFFSET_MODE_STATUS,
    OFFSET_ONOFF_CMD,
    OFFSET_ONOFF_STATUS,
    OFFSET_OP_CONDITION,
    OFFSET_OUTLET_TEMP,
    OFFSET_TEMP_CMD,
    OFFSET_TEMP_STATUS,
    OFFSET_VALVE_OPENING,
    TEMP_RANGE_BY_TYPE,
    UNIT_TYPE_ATW,
    UNIT_TYPE_VRF,
)
from .coordinator import HitachiModbusCoordinator

_LOGGER = logging.getLogger(__name__)

# HVACMode string → HA enum
_STR_TO_HVAC: dict[str, HVACMode] = {
    "off":       HVACMode.OFF,
    "cool":      HVACMode.COOL,
    "dry":       HVACMode.DRY,
    "fan_only":  HVACMode.FAN_ONLY,
    "heat":      HVACMode.HEAT,
    "heat_cool": HVACMode.HEAT_COOL,
}
_HVAC_TO_STR: dict[HVACMode, str] = {v: k for k, v in _STR_TO_HVAC.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register the gateway device then create one ClimateEntity per unit."""
    coordinator: HitachiModbusCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Register the gateway itself so indoor units can reference it via via_device
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Hitachi",
        model="HC-A16MB",
        name=f"Hitachi HC-A ModBus Gateway ({entry.data.get(CONF_HOST, '')})",
    )

    units: list[dict] = entry.data.get("discovered_units", [])
    if not units:
        _LOGGER.warning("No units in config entry – nothing to create")
        return

    async_add_entities(
        HitachiClimateEntity(coordinator, entry, u["slot_id"], u["ou"], u["iu"],
                             u.get("unit_type", UNIT_TYPE_VRF))
        for u in units
    )


class HitachiClimateEntity(CoordinatorEntity[HitachiModbusCoordinator], ClimateEntity):
    """One Hitachi indoor unit slot exposed as a Home Assistant climate entity."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: HitachiModbusCoordinator,
        entry: ConfigEntry,
        slot_id: int,
        ou: int,
        iu: int,
        unit_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._slot_id = slot_id
        self._ou = ou
        self._iu = iu
        self._unit_type = unit_type
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_slot{slot_id}"
        self._attr_name = f"Ou{ou} Iu{iu}"

        # ── Type-specific static configuration ────────────────────────────
        hvac_strs = HVAC_MODES_BY_TYPE[unit_type]
        self._attr_hvac_modes = [_STR_TO_HVAC[m] for m in hvac_strs]

        fan_list = FAN_MODES_BY_TYPE[unit_type]
        self._attr_fan_modes = fan_list if fan_list else None

        temp_min, temp_max, temp_step = TEMP_RANGE_BY_TYPE[unit_type]
        self._attr_min_temp = temp_min
        self._attr_max_temp = temp_max
        self._attr_target_temperature_step = temp_step

        features = ClimateEntityFeature.TARGET_TEMPERATURE
        if fan_list:
            features |= ClimateEntityFeature.FAN_MODE
        self._attr_supported_features = features

    # ── Device info ────────────────────────────────────────────────────────

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_slot{self._slot_id}")},
            name=f"Hitachi Indoor Ou{self._ou} Iu{self._iu} ({self._unit_type.upper()})",
            manufacturer="Hitachi",
            model=f"Indoor unit ({self._unit_type.upper()})",
            via_device=(DOMAIN, self._entry.entry_id),
        )

    # ── Register helpers ───────────────────────────────────────────────────

    @property
    def _regs(self) -> list[int] | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._slot_id)

    def _reg(self, offset: int) -> int | None:
        regs = self._regs
        if regs is None or offset >= len(regs):
            return None
        return regs[offset]

    # ── State ──────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._regs is not None

    @property
    def hvac_mode(self) -> HVACMode | None:
        on_off = self._reg(OFFSET_ONOFF_STATUS)
        if on_off is None:
            return None
        if on_off == 0:
            return HVACMode.OFF
        mode_val = self._reg(OFFSET_MODE_STATUS)
        if mode_val is None:
            return HVACMode.OFF
        ha_str = MODBUS_TO_HA_MODE.get(mode_val, "cool")
        return _STR_TO_HVAC.get(ha_str, HVACMode.COOL)

    @property
    def fan_mode(self) -> str | None:
        if not self._attr_fan_modes:
            return None
        val = self._reg(OFFSET_FAN_STATUS)
        if val is None:
            return None
        return MODBUS_TO_HA_FAN.get(val, "auto")

    @property
    def current_temperature(self) -> float | None:
        regs = self._regs
        if regs is None:
            return None
        return HitachiModbusCoordinator.get_signed_temp(regs, OFFSET_INLET_TEMP)

    @property
    def target_temperature(self) -> float | None:
        val = self._reg(OFFSET_TEMP_STATUS)
        return float(val) if val is not None else None

    # ── Control ────────────────────────────────────────────────────────────

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_write_unit_register(
                self._slot_id, OFFSET_ONOFF_CMD, 0
            )
        else:
            ha_str = _HVAC_TO_STR.get(hvac_mode, "cool")
            modbus_mode = HA_MODE_TO_MODBUS.get(ha_str, 0)
            await self.coordinator.async_write_unit_register(
                self._slot_id, OFFSET_ONOFF_CMD, 1
            )
            await self.coordinator.async_write_unit_register(
                self._slot_id, OFFSET_MODE_CMD, modbus_mode
            )
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if not self._attr_fan_modes:
            return
        modbus_fan = HA_FAN_TO_MODBUS.get(fan_mode, 4)
        await self.coordinator.async_write_unit_register(
            self._slot_id, OFFSET_FAN_CMD, modbus_fan
        )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        await self.coordinator.async_write_unit_register(
            self._slot_id, OFFSET_TEMP_CMD, int(temp)
        )
        await self.coordinator.async_request_refresh()

    # ── Extra attributes ───────────────────────────────────────────────────

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        regs = self._regs
        if regs is None:
            return {}

        attrs: dict[str, Any] = {
            "slot_id": self._slot_id,
            "unit_type": self._unit_type,
            "ou": self._ou,
            "iu": self._iu,
        }

        for name, offset in (
            ("inlet_temperature",        OFFSET_INLET_TEMP),
            ("outlet_temperature",       OFFSET_OUTLET_TEMP),
            ("gas_pipe_temperature",     OFFSET_GAS_PIPE_TEMP),
            ("liquid_pipe_temperature",  OFFSET_LIQUID_PIPE_TEMP),
        ):
            val = HitachiModbusCoordinator.get_signed_temp(regs, offset)
            if val is not None:
                attrs[name] = val

        if OFFSET_ALARM_CODE < len(regs):
            attrs["alarm_code"] = regs[OFFSET_ALARM_CODE]

        if OFFSET_VALVE_OPENING < len(regs):
            attrs["valve_opening_pct"] = regs[OFFSET_VALVE_OPENING]

        if OFFSET_OP_CONDITION < len(regs):
            _labels = {0: "off", 1: "thermo_off", 2: "thermo_on", 3: "alarm"}
            attrs["operation_condition"] = _labels.get(
                regs[OFFSET_OP_CONDITION], str(regs[OFFSET_OP_CONDITION])
            )

        return attrs
