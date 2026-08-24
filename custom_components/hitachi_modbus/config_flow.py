"""Config flow for Hitachi ModBus Gateway integration.

Step 1 – "user":        IP address, slave ID, register base.
Step 2 – "units":       Summary of discovered units (Ou / Iu).
Step 3 – "unit_types":  Select VRF / RAC / ATW for each unit.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_HOST,
    CONF_N_BASE,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE_ID,
    DEFAULT_N_BASE,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE_ID,
    DOMAIN,
    MAX_UNITS,
    MODBUS_STRIDE,
    OFFSET_EXIST,
    OFFSET_SYS_ADDR,
    OFFSET_UNIT_ADDR,
    UNIT_TYPE_VRF,
    UNIT_TYPES,
)

_LOGGER = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 5.0

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_SLAVE_ID, default=DEFAULT_SLAVE_ID): vol.All(
            int, vol.Range(min=1, max=247)
        ),
        vol.Optional(CONF_N_BASE, default=DEFAULT_N_BASE): vol.In([2000, 20000]),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            int, vol.Range(min=5, max=3600)
        ),
    }
)

# Key used to store the type selection for each slot in the form
def _type_key(slot_id: int) -> str:
    return f"type_slot_{slot_id}"


class HitachiModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the UI configuration flow for Hitachi ModBus Gateway."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_data: dict[str, Any] = {}

    # ── Step 1: connection ─────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            discovered = await self._async_discover(user_input)
            if discovered is None:
                errors["base"] = "cannot_connect"
            elif not discovered:
                errors["base"] = "no_units_found"
            else:
                self._discovery_data = {
                    "config": user_input,
                    "units": discovered,
                }
                return await self.async_step_units()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    # ── Step 2: confirm discovered units ──────────────────────────────────

    async def async_step_units(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return await self.async_step_unit_types()

        units: list[dict] = self._discovery_data["units"]
        unit_lines = "\n".join(
            f"Slot {u['slot_id']:2d} → Ou={u['ou']}, Iu={u['iu']}"
            for u in units
        )
        return self.async_show_form(
            step_id="units",
            data_schema=vol.Schema({}),
            description_placeholders={"unit_summary": unit_lines},
        )

    # ── Step 3: unit type selection ────────────────────────────────────────

    async def async_step_unit_types(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """One dropdown per discovered unit: VRF / RAC / ATW."""
        units: list[dict] = self._discovery_data["units"]
        config: dict = self._discovery_data["config"]

        if user_input is not None:
            # Attach chosen type to each unit dict
            for unit in units:
                unit["unit_type"] = user_input.get(
                    _type_key(unit["slot_id"]), UNIT_TYPE_VRF
                )
            title = f"Hitachi HC-A ModBus ({config[CONF_HOST]})"
            return self.async_create_entry(
                title=title,
                data={**config, "discovered_units": units},
            )

        # Build a schema with one selector per unit
        schema_fields: dict = {}
        for unit in units:
            schema_fields[
                vol.Required(_type_key(unit["slot_id"]), description={"suggested_value": UNIT_TYPE_VRF})
            ] = vol.In(UNIT_TYPES)

        # Description lists the discovered units as context
        unit_lines = "\n".join(
            f"• Slot {u['slot_id']}: Ou={u['ou']}, Iu={u['iu']}"
            for u in units
        )

        return self.async_show_form(
            step_id="unit_types",
            data_schema=vol.Schema(schema_fields),
            description_placeholders={"unit_summary": unit_lines},
        )

    # ── Options flow ───────────────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HitachiModbusOptionsFlow:
        return HitachiModbusOptionsFlow(config_entry)

    # ── Discovery ──────────────────────────────────────────────────────────

    async def _async_discover(
        self, config: dict[str, Any]
    ) -> list[dict] | None:
        from pymodbus.client import AsyncModbusTcpClient  # noqa: PLC0415
        from pymodbus.exceptions import ModbusException  # noqa: PLC0415
        from .modbus_compat import modbus_read  # noqa: PLC0415

        host: str = config[CONF_HOST]
        port: int = config.get(CONF_PORT, DEFAULT_PORT)
        slave: int = config.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID)
        n_base: int = config.get(CONF_N_BASE, DEFAULT_N_BASE)

        _LOGGER.debug(
            "Hitachi discovery: connecting to %s:%d slave=%d n_base=%d",
            host, port, slave, n_base,
        )

        client = AsyncModbusTcpClient(host=host, port=port, timeout=5)

        try:
            try:
                connected = await asyncio.wait_for(
                    client.connect(), timeout=_CONNECT_TIMEOUT
                )
            except asyncio.TimeoutError:
                _LOGGER.error(
                    "Hitachi: TCP connection to %s:%d timed out", host, port
                )
                return None

            if not connected:
                _LOGGER.error("Hitachi: TCP connect to %s:%d returned False", host, port)
                return None

            _LOGGER.debug("Hitachi: TCP connected, scanning %d slots…", MAX_UNITS)

            units: list[dict] = []
            gateway_responds = False
            timeouts = 0

            for slot_id in range(MAX_UNITS):
                base = n_base + slot_id * MODBUS_STRIDE
                try:
                    result = await asyncio.wait_for(
                        modbus_read(client, base, 3, slave),
                        timeout=_READ_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    _LOGGER.debug("Hitachi: slot %d read timed out", slot_id)
                    timeouts += 1
                    if slot_id == 0:
                        _LOGGER.error(
                            "Hitachi: gateway at %s:%d does not respond to Modbus "
                            "(slave=%d, n_base=%d).",
                            host, port, slave, n_base,
                        )
                        return None
                    continue
                except ModbusException as exc:
                    _LOGGER.debug("Hitachi: slot %d Modbus error: %s", slot_id, exc)
                    continue

                gateway_responds = True

                if result.isError():
                    continue

                regs = result.registers
                if not regs or len(regs) < 3 or regs[OFFSET_EXIST] != 1:
                    continue

                units.append({
                    "slot_id": slot_id,
                    "ou": regs[OFFSET_SYS_ADDR],
                    "iu": regs[OFFSET_UNIT_ADDR],
                })
                _LOGGER.debug(
                    "Hitachi: slot %d → Ou=%d Iu=%d", slot_id,
                    regs[OFFSET_SYS_ADDR], regs[OFFSET_UNIT_ADDR],
                )

            if not units and not gateway_responds:
                # Nothing ever came back from the gateway: report a connection
                # problem rather than "no indoor units configured".
                _LOGGER.error(
                    "Hitachi: gateway at %s:%d never answered a register read "
                    "(slave=%d, n_base=%d, %d timeouts).",
                    host, port, slave, n_base, timeouts,
                )
                return None

            return units

        except Exception as exc:  # noqa: BLE001
            _LOGGER.error(
                "Hitachi: unexpected error during discovery: %s", exc, exc_info=True
            )
            return None
        finally:
            client.close()


class HitachiModbusOptionsFlow(config_entries.OptionsFlow):
    """Allow changing scan interval after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.data.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_interval
                    ): vol.All(int, vol.Range(min=5, max=3600))
                }
            ),
        )
