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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATW_OFFSET_ALARM,
    ATW_OFFSET_DHW_TEMP,
    ATW_OFFSET_DHWT_SETTEMP_CMD,
    ATW_OFFSET_DHWT_SETTEMP_ST,
    ATW_OFFSET_DHWT_STATUS,
    ATW_OFFSET_MODE_CMD,
    ATW_OFFSET_MODE_STATUS,
    ATW_OFFSET_ONOFF_CMD,
    ATW_OFFSET_ONOFF_STATUS,
    ATW_OFFSET_OP_STATE,
    ATW_OFFSET_OUTDOOR_TEMP,
    ATW_OFFSET_SYS_STATUS2,
    ATW_OFFSET_WATER_INLET_TEMP,
    ATW_OFFSET_WATER_OUTLET_TEMP,
    ATW_READ_START,
    CONF_DRY_FAN,
    CONF_HOST,
    DOMAIN,
    DRY_FAN_LOW,
    FAN_MODES_BY_TYPE,
    FAN_MODES_DRY_LOW,
    HA_FAN_TO_MODBUS,
    HA_MODE_TO_MODBUS,
    HVAC_MODES_BY_TYPE,
    LEGACY_FAN_ALIASES,
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
)
from .coordinator import HitachiModbusCoordinator
from .helpers import resolve_units

_LOGGER = logging.getLogger(__name__)

_STR_TO_HVAC: dict[str, HVACMode] = {
    "off":       HVACMode.OFF,
    "cool":      HVACMode.COOL,
    "dry":       HVACMode.DRY,
    "fan_only":  HVACMode.FAN_ONLY,
    "heat":      HVACMode.HEAT,
    "heat_cool": HVACMode.HEAT_COOL,
}
_HVAC_TO_STR: dict[HVACMode, str] = {v: k for k, v in _STR_TO_HVAC.items()}

_ATW_OP_STATE: dict[int, str] = {
    0: "off",
    1: "cool_demand_off",  2: "cool_thermo_off",  3: "cool_thermo_on",
    4: "heat_demand_off",  5: "heat_thermo_off",  6: "heat_thermo_on",
    7: "dhw_off",          8: "dhw_on",
    9: "swp_off",         10: "swp_on",           11: "alarm",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HitachiModbusCoordinator = hass.data[DOMAIN][entry.entry_id]

    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Hitachi",
        model="HC-A16MB",
        name=f"Hitachi HC-A ModBus Gateway ({entry.data.get(CONF_HOST, '')})",
    )

    units: list[dict] = resolve_units(entry)
    if not units:
        _LOGGER.warning("No units in config entry – nothing to create")
        return

    async_add_entities(HitachiClimateEntity(coordinator, entry, u) for u in units)


class HitachiClimateEntity(CoordinatorEntity[HitachiModbusCoordinator], ClimateEntity):
    """One Hitachi indoor unit slot exposed as a Home Assistant climate entity."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    # TURN_ON / TURN_OFF are declared explicitly in __init__ (HA 2024.2+)
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        coordinator: HitachiModbusCoordinator,
        entry: ConfigEntry,
        unit: dict,
    ) -> None:
        super().__init__(coordinator)
        slot_id: int = unit["slot_id"]
        unit_type: str = unit["unit_type"]
        self._slot_id = slot_id
        self._ou = unit["ou"]
        self._iu = unit["iu"]
        self._unit_type = unit_type
        self._entry = entry

        self._attr_unique_id = f"{entry.entry_id}_slot{slot_id}"
        self._attr_name = f"Ou{self._ou} Iu{self._iu}"

        hvac_strs = HVAC_MODES_BY_TYPE[unit_type]
        self._attr_hvac_modes = [_STR_TO_HVAC[m] for m in hvac_strs]

        # Full list of speeds this unit type can be set to, and the reduced
        # list that applies while it is dehumidifying (see fan_modes).  Whether
        # Dry is restricted is a property of the individual indoor unit, so it
        # comes from the options flow rather than from the unit type.
        fan_list = FAN_MODES_BY_TYPE[unit_type]
        self._fan_modes: list[str] | None = fan_list or None
        self._fan_modes_dry: list[str] | None = (
            FAN_MODES_DRY_LOW if unit.get(CONF_DRY_FAN) == DRY_FAN_LOW else None
        )

        temp_min, temp_max, temp_step = TEMP_RANGE_BY_TYPE[unit_type]
        self._attr_min_temp = temp_min
        self._attr_max_temp = temp_max
        self._attr_target_temperature_step = temp_step

        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if self._fan_modes:
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
        """§5.2.1 register for VRF/RAC (index = offset directly)."""
        regs = self._regs
        if regs is None or offset >= len(regs):
            return None
        return regs[offset]

    def _atw_reg(self, offset: int) -> int | None:
        """§5.2.2 ATW register (index = offset - ATW_READ_START)."""
        regs = self._regs
        if regs is None:
            return None
        idx = offset - ATW_READ_START
        if idx < 0 or idx >= len(regs):
            return None
        return regs[idx]

    @staticmethod
    def _signed(val: int) -> int:
        return val if val < 0x8000 else val - 0x10000

    # ── State ──────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return super().available and self._regs is not None

    @property
    def hvac_mode(self) -> HVACMode | None:
        if self._unit_type == UNIT_TYPE_ATW:
            on_off = self._atw_reg(ATW_OFFSET_ONOFF_STATUS)
            if on_off is None:
                return None
            if on_off == 0:
                return HVACMode.OFF
            mode_val = self._atw_reg(ATW_OFFSET_MODE_STATUS)
            if mode_val is None:
                return HVACMode.OFF
            return HVACMode.HEAT if (mode_val & 0x01) else HVACMode.COOL

        # VRF / RAC
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
    def fan_modes(self) -> list[str] | None:
        """Speeds that can be selected right now.

        Some indoor units pin the fan to Low while dehumidifying and overwrite
        the register, so a higher speed is accepted and then silently reverts.
        Units configured that way (Dry fan = "low") offer only Low here.
        ClimateEntity validates set_fan_mode against this list, so it covers
        service calls as well as the dropdown.
        """
        if self._fan_modes and self._fan_modes_dry and self.hvac_mode == HVACMode.DRY:
            return self._fan_modes_dry
        return self._fan_modes

    @property
    def fan_mode(self) -> str | None:
        if not self._fan_modes:
            return None
        val = self._reg(OFFSET_FAN_STATUS)
        if val is None:
            return None
        mode = MODBUS_TO_HA_FAN.get(val)
        if mode is None or mode not in self._fan_modes:
            # Only genuinely unknown register values are withheld.  What the
            # unit reports is always published otherwise, even when the current
            # mode narrows the selectable list, so the state keeps showing the
            # speed the unit is really running at.
            _LOGGER.debug(
                "Slot %d reported unsupported fan register value %s",
                self._slot_id,
                val,
            )
            return None
        return mode

    @property
    def current_temperature(self) -> float | None:
        if self._unit_type == UNIT_TYPE_ATW:
            # Use actual DHW tank temperature as current temperature
            val = self._atw_reg(ATW_OFFSET_DHW_TEMP)
            if val is None:
                return None
            signed = self._signed(val)
            return float(signed) if abs(signed) < 200 else None

        regs = self._regs
        if regs is None:
            return None
        return HitachiModbusCoordinator.get_signed_temp(regs, OFFSET_INLET_TEMP)

    @property
    def target_temperature(self) -> float | None:
        if self._unit_type == UNIT_TYPE_ATW:
            # DHWT setting temperature is the user-facing setpoint
            val = self._atw_reg(ATW_OFFSET_DHWT_SETTEMP_ST)
            return float(val) if val is not None else None

        val = self._reg(OFFSET_TEMP_STATUS)
        return float(val) if val is not None else None

    # ── Control ────────────────────────────────────────────────────────────

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if self._unit_type == UNIT_TYPE_ATW:
            if hvac_mode == HVACMode.OFF:
                await self.coordinator.async_write_unit_register(
                    self._slot_id, ATW_OFFSET_ONOFF_CMD, 0
                )
            elif hvac_mode == HVACMode.HEAT:
                await self.coordinator.async_write_unit_register(
                    self._slot_id, ATW_OFFSET_ONOFF_CMD, 1
                )
                await self.coordinator.async_write_unit_register(
                    self._slot_id, ATW_OFFSET_MODE_CMD, 1
                )
            elif hvac_mode == HVACMode.COOL:
                await self.coordinator.async_write_unit_register(
                    self._slot_id, ATW_OFFSET_ONOFF_CMD, 1
                )
                await self.coordinator.async_write_unit_register(
                    self._slot_id, ATW_OFFSET_MODE_CMD, 0
                )
            await self.coordinator.async_request_refresh()
            return

        # VRF / RAC
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

    async def async_turn_on(self) -> None:
        """Start the unit, leaving its current mode untouched.

        The gateway keeps Run/Stop in a register of its own, so the previously
        selected mode survives a stop; the generic ClimateEntity fallback would
        instead force the unit into heat_cool/heat/cool.
        """
        offset = (
            ATW_OFFSET_ONOFF_CMD
            if self._unit_type == UNIT_TYPE_ATW
            else OFFSET_ONOFF_CMD
        )
        await self.coordinator.async_write_unit_register(self._slot_id, offset, 1)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Stop the unit."""
        offset = (
            ATW_OFFSET_ONOFF_CMD
            if self._unit_type == UNIT_TYPE_ATW
            else OFFSET_ONOFF_CMD
        )
        await self.coordinator.async_write_unit_register(self._slot_id, offset, 0)
        await self.coordinator.async_request_refresh()

    async def async_handle_set_fan_mode_service(self, fan_mode: str) -> None:
        """Translate retired fan speeds before Home Assistant validates them.

        ClimateEntity checks the requested speed against ``fan_modes`` here and
        raises before ``async_set_fan_mode`` runs, so an automation still asking
        for "high2" has to be rewritten at this point rather than further down.
        """
        await super().async_handle_set_fan_mode_service(
            LEGACY_FAN_ALIASES.get(fan_mode, fan_mode)
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if not self._fan_modes:
            return
        fan_mode = LEGACY_FAN_ALIASES.get(fan_mode, fan_mode)
        modbus_fan = HA_FAN_TO_MODBUS.get(fan_mode)
        if modbus_fan is None:
            raise ServiceValidationError(
                f"Fan mode '{fan_mode}' is not supported by this unit"
            )
        await self.coordinator.async_write_unit_register(
            self._slot_id, OFFSET_FAN_CMD, modbus_fan
        )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return

        if self._unit_type == UNIT_TYPE_ATW:
            # Write to DHWT setpoint (unified control in climate entity)
            await self.coordinator.async_write_unit_register(
                self._slot_id, ATW_OFFSET_DHWT_SETTEMP_CMD, int(temp)
            )
        else:
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
            "slot_id":   self._slot_id,
            "unit_type": self._unit_type,
            "ou":        self._ou,
            "iu":        self._iu,
        }

        if self._unit_type == UNIT_TYPE_ATW:
            for name, offset in (
                ("water_inlet_temperature",     ATW_OFFSET_WATER_INLET_TEMP),
                ("water_outlet_temperature",    ATW_OFFSET_WATER_OUTLET_TEMP),
                ("outdoor_ambient_temperature", ATW_OFFSET_OUTDOOR_TEMP),
                ("dhw_temperature",             ATW_OFFSET_DHW_TEMP),
            ):
                val = self._atw_reg(offset)
                if val is not None:
                    signed = self._signed(val)
                    if abs(signed) < 200:
                        attrs[name] = float(signed)

            op = self._atw_reg(ATW_OFFSET_OP_STATE)
            if op is not None:
                attrs["operation_state"] = _ATW_OP_STATE.get(op, str(op))

            sys2 = self._atw_reg(ATW_OFFSET_SYS_STATUS2)
            if sys2 is not None:
                attrs["defrosting"]    = bool(sys2 & 0x0001)
                attrs["compressor_on"] = bool(sys2 & 0x0020)

            dhwt_run = self._atw_reg(ATW_OFFSET_DHWT_STATUS)
            if dhwt_run is not None:
                attrs["dhwt_running"] = bool(dhwt_run)
            dhwt_sp = self._atw_reg(ATW_OFFSET_DHWT_SETTEMP_ST)
            if dhwt_sp is not None:
                attrs["dhwt_setpoint"] = float(dhwt_sp)

            alarm = self._atw_reg(ATW_OFFSET_ALARM)
            if alarm is not None:
                attrs["alarm_code"] = alarm

            return attrs

        # VRF / RAC
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
