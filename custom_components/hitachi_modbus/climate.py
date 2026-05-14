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
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    FAN_MODES,
    HA_FAN_TO_MODBUS,
    HA_MODE_TO_MODBUS,
    HVAC_MODES,
    MODBUS_TO_HA_FAN,
    MODBUS_TO_HA_MODE,
    OFFSET_FAN_CMD,
    OFFSET_FAN_STATUS,
    OFFSET_INLET_TEMP,
    OFFSET_MODE_CMD,
    OFFSET_MODE_STATUS,
    OFFSET_ONOFF_CMD,
    OFFSET_ONOFF_STATUS,
    OFFSET_TEMP_CMD,
    OFFSET_TEMP_STATUS,
    TEMP_MAX,
    TEMP_MIN,
    TEMP_STEP,
)
from .coordinator import HitachiModbusCoordinator

_LOGGER = logging.getLogger(__name__)

# HVACMode string → HA enum
_STR_TO_HVAC = {
    "off": HVACMode.OFF,
    "cool": HVACMode.COOL,
    "dry": HVACMode.DRY,
    "fan_only": HVACMode.FAN_ONLY,
    "heat": HVACMode.HEAT,
    "heat_cool": HVACMode.HEAT_COOL,
}
_HVAC_TO_STR = {v: k for k, v in _STR_TO_HVAC.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one ClimateEntity per discovered indoor unit slot."""
    coordinator: HitachiModbusCoordinator = hass.data[DOMAIN][entry.entry_id]

    units: list[dict] = entry.data.get("discovered_units", [])
    if not units:
        _LOGGER.warning("No units in config entry – nothing to create")
        return

    entities = [
        HitachiClimateEntity(coordinator, entry, unit["slot_id"], unit["ou"], unit["iu"])
        for unit in units
    ]
    async_add_entities(entities)


class HitachiClimateEntity(CoordinatorEntity[HitachiModbusCoordinator], ClimateEntity):
    """Represents one Hitachi indoor unit connected via the HC-A ModBus gateway."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [_STR_TO_HVAC[m] for m in HVAC_MODES]
    _attr_fan_modes = FAN_MODES
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
    )
    _attr_min_temp = TEMP_MIN
    _attr_max_temp = TEMP_MAX
    _attr_target_temperature_step = TEMP_STEP

    def __init__(
        self,
        coordinator: HitachiModbusCoordinator,
        entry: ConfigEntry,
        slot_id: int,
        ou: int,
        iu: int,
    ) -> None:
        super().__init__(coordinator)
        self._slot_id = slot_id
        self._ou = ou
        self._iu = iu
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_slot{slot_id}"
        self._attr_name = f"Ou{ou} Iu{iu}"

    # ── Device info ────────────────────────────────────────────────────────

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_slot{self._slot_id}")},
            name=f"Hitachi Indoor Ou{self._ou} Iu{self._iu}",
            manufacturer="Hitachi",
            model="HC-A16MB indoor unit",
            via_device=(DOMAIN, self._entry.entry_id),
        )

    # ── Register helpers ───────────────────────────────────────────────────

    @property
    def _regs(self) -> list[int] | None:
        """Return the current register block for this slot, or None."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._slot_id)

    def _reg(self, offset: int) -> int | None:
        regs = self._regs
        if regs is None or offset >= len(regs):
            return None
        return regs[offset]

    # ── State properties ───────────────────────────────────────────────────

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
        ha_mode_str = MODBUS_TO_HA_MODE.get(mode_val, "cool")
        return _STR_TO_HVAC.get(ha_mode_str, HVACMode.COOL)

    @property
    def fan_mode(self) -> str | None:
        fan_val = self._reg(OFFSET_FAN_STATUS)
        if fan_val is None:
            return None
        return MODBUS_TO_HA_FAN.get(fan_val, "auto")

    @property
    def current_temperature(self) -> float | None:
        val = self._reg(OFFSET_INLET_TEMP)
        if val is None:
            return None
        return HitachiModbusCoordinator.get_signed_temp(self._regs, OFFSET_INLET_TEMP)

    @property
    def target_temperature(self) -> float | None:
        val = self._reg(OFFSET_TEMP_STATUS)
        if val is None:
            return None
        return float(val)

    # ── Control methods ────────────────────────────────────────────────────

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Turn the unit on/off and optionally change operating mode."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_write_unit_register(
                self._slot_id, OFFSET_ONOFF_CMD, 0
            )
        else:
            ha_mode_str = _HVAC_TO_STR.get(hvac_mode, "cool")
            modbus_mode = HA_MODE_TO_MODBUS.get(ha_mode_str, 0)
            # First turn on, then set mode
            await self.coordinator.async_write_unit_register(
                self._slot_id, OFFSET_ONOFF_CMD, 1
            )
            await self.coordinator.async_write_unit_register(
                self._slot_id, OFFSET_MODE_CMD, modbus_mode
            )
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        modbus_fan = HA_FAN_TO_MODBUS.get(fan_mode, 4)  # default: auto
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

    # ── Extra state attributes ─────────────────────────────────────────────

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        regs = self._regs
        if regs is None:
            return {}

        attrs: dict[str, Any] = {
            "slot_id": self._slot_id,
            "ou": self._ou,
            "iu": self._iu,
        }

        # Temperature sensors
        inlet = HitachiModbusCoordinator.get_signed_temp(regs, OFFSET_INLET_TEMP)
        if inlet is not None:
            attrs["inlet_temperature"] = inlet

        from .const import OFFSET_OUTLET_TEMP, OFFSET_GAS_PIPE_TEMP, OFFSET_LIQUID_PIPE_TEMP, OFFSET_ALARM_CODE, OFFSET_VALVE_OPENING, OFFSET_OP_CONDITION  # noqa: PLC0415

        outlet = HitachiModbusCoordinator.get_signed_temp(regs, OFFSET_OUTLET_TEMP)
        if outlet is not None:
            attrs["outlet_temperature"] = outlet

        gas = HitachiModbusCoordinator.get_signed_temp(regs, OFFSET_GAS_PIPE_TEMP)
        if gas is not None:
            attrs["gas_pipe_temperature"] = gas

        liquid = HitachiModbusCoordinator.get_signed_temp(regs, OFFSET_LIQUID_PIPE_TEMP)
        if liquid is not None:
            attrs["liquid_pipe_temperature"] = liquid

        alarm = regs[OFFSET_ALARM_CODE] if OFFSET_ALARM_CODE < len(regs) else None
        if alarm is not None:
            attrs["alarm_code"] = alarm

        valve = regs[OFFSET_VALVE_OPENING] if OFFSET_VALVE_OPENING < len(regs) else None
        if valve is not None:
            attrs["valve_opening_pct"] = valve

        op = regs[OFFSET_OP_CONDITION] if OFFSET_OP_CONDITION < len(regs) else None
        if op is not None:
            _op_labels = {0: "off", 1: "thermo_off", 2: "thermo_on", 3: "alarm"}
            attrs["operation_condition"] = _op_labels.get(op, str(op))

        return attrs
