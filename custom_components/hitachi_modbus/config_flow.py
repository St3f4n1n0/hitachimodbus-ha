"""Config flow for Hitachi ModBus Gateway integration.

Step 1 – "user":   Enter gateway IP and Modbus slave ID.
Step 2 – "units":  Confirm or refine the discovered units (Ou / Iu).
"""
from __future__ import annotations

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
)
from .coordinator import HitachiModbusCoordinator

_LOGGER = logging.getLogger(__name__)

# ── Step 1 schema ──────────────────────────────────────────────────────────

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
    _discovery_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1 – connection parameters and gateway test."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Prevent duplicate entries for the same gateway IP
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            # Try to connect and discover units
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
            description_placeholders={
                "default_port": str(DEFAULT_PORT),
                "default_slave": str(DEFAULT_SLAVE_ID),
            },
        )

    async def async_step_units(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2 – show discovered units and let the user confirm."""
        units: list[dict] = self._discovery_data["units"]
        config: dict = self._discovery_data["config"]

        if user_input is not None:
            # User confirmed – store config entry
            title = f"Hitachi HC-A ModBus ({config[CONF_HOST]})"
            return self.async_create_entry(
                title=title,
                data={**config, "discovered_units": units},
            )

        # Build a read-only summary schema to display discovered units
        unit_lines = "\n".join(
            f"Slot {u['slot_id']:2d} → Ou={u['ou']}, Iu={u['iu']}" for u in units
        )

        return self.async_show_form(
            step_id="units",
            data_schema=vol.Schema({}),
            description_placeholders={"unit_summary": unit_lines},
        )

    # ── Options flow (re-configure scan interval) ──────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HitachiModbusOptionsFlow:
        return HitachiModbusOptionsFlow(config_entry)

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _async_discover(
        self, config: dict[str, Any]
    ) -> list[dict] | None:
        """Connect to the gateway and return discovered unit list, or None on error."""
        # Build a temporary coordinator just for discovery
        from homeassistant.config_entries import ConfigEntry  # noqa: PLC0415

        class _FakeEntry:
            data = config

        coordinator = HitachiModbusCoordinator(self.hass, _FakeEntry())  # type: ignore[arg-type]
        try:
            units = await coordinator.async_discover_units()
            return units
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Gateway discovery failed: %s", exc)
            return None
        finally:
            await coordinator.async_disconnect()


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
                    vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                        int, vol.Range(min=5, max=3600)
                    )
                }
            ),
        )
