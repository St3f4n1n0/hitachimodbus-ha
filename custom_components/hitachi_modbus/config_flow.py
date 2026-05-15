"""Config flow for Hitachi ModBus Gateway integration.

Step 1 – "user":   Enter gateway IP and Modbus slave ID.
Step 2 – "units":  Confirm discovered units (Ou / Iu).
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
)

_LOGGER = logging.getLogger(__name__)

# TCP connection + per-register read timeout (seconds)
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


class HitachiModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the UI configuration flow for Hitachi ModBus Gateway."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1 – connection parameters and gateway test."""
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

    async def async_step_units(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2 – show discovered units and let the user confirm."""
        units: list[dict] = self._discovery_data["units"]
        config: dict = self._discovery_data["config"]

        if user_input is not None:
            title = f"Hitachi HC-A ModBus ({config[CONF_HOST]})"
            return self.async_create_entry(
                title=title,
                data={**config, "discovered_units": units},
            )

        unit_lines = "\n".join(
            f"Slot {u['slot_id']:2d} → Ou={u['ou']}, Iu={u['iu']}"
            for u in units
        )
        return self.async_show_form(
            step_id="units",
            data_schema=vol.Schema({}),
            description_placeholders={"unit_summary": unit_lines},
        )

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
        """Open a Modbus TCP connection and scan all 16 slots for indoor units.

        Returns:
            list[dict]  – found units (may be empty → "no_units_found")
            None        – connection or protocol error → "cannot_connect"
        """
        from pymodbus.client import AsyncModbusTcpClient  # noqa: PLC0415
        from pymodbus.exceptions import ModbusException  # noqa: PLC0415

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
            # ── TCP connect ────────────────────────────────────────────────
            try:
                connected = await asyncio.wait_for(
                    client.connect(), timeout=_CONNECT_TIMEOUT
                )
            except asyncio.TimeoutError:
                _LOGGER.error(
                    "Hitachi: TCP connection to %s:%d timed out after %gs",
                    host, port, _CONNECT_TIMEOUT,
                )
                return None

            if not connected:
                _LOGGER.error(
                    "Hitachi: TCP connect to %s:%d returned False", host, port
                )
                return None

            _LOGGER.debug("Hitachi: TCP connected, scanning %d slots…", MAX_UNITS)

            # ── Scan slots ─────────────────────────────────────────────────
            units: list[dict] = []
            gateway_responds = False  # set True on first valid Modbus response

            for slot_id in range(MAX_UNITS):
                base = n_base + slot_id * MODBUS_STRIDE
                try:
                    result = await asyncio.wait_for(
                        # positional args: pymodbus ≥3.8 made 'slave' positional-only
                        client.read_holding_registers(base, 3, slave),
                        timeout=_READ_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    _LOGGER.debug("Hitachi: slot %d read timed out", slot_id)
                    if slot_id == 0:
                        # Gateway not responding to Modbus at all – stop immediately
                        _LOGGER.error(
                            "Hitachi: gateway at %s:%d does not respond to Modbus "
                            "(slave=%d, n_base=%d). "
                            "Check slave ID and register base address.",
                            host, port, slave, n_base,
                        )
                        return None
                    continue
                except ModbusException as exc:
                    _LOGGER.debug("Hitachi: slot %d Modbus error: %s", slot_id, exc)
                    continue

                gateway_responds = True

                if result.isError():
                    _LOGGER.debug("Hitachi: slot %d returned Modbus error response", slot_id)
                    continue

                regs = result.registers
                if not regs or len(regs) < 3:
                    continue

                if regs[OFFSET_EXIST] != 1:
                    continue

                ou = regs[OFFSET_SYS_ADDR]
                iu = regs[OFFSET_UNIT_ADDR]
                _LOGGER.debug(
                    "Hitachi: slot %d → Ou=%d Iu=%d (EXIST=1)", slot_id, ou, iu
                )
                units.append({"slot_id": slot_id, "ou": ou, "iu": iu})

            return units

        except Exception as exc:  # noqa: BLE001
            _LOGGER.error(
                "Hitachi: unexpected error during discovery: %s",
                exc,
                exc_info=True,
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
