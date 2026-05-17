"""Hitachi ModBus Gateway – Home Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import DOMAIN, UNIT_TYPE_VRF
from .coordinator import HitachiModbusCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE, Platform.SWITCH, Platform.NUMBER]

# ── Service schemas ────────────────────────────────────────────────────────

SERVICE_READ_REGISTER = "read_register"
SERVICE_WRITE_REGISTER = "write_register"

SERVICE_READ_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): str,
        vol.Required("address"): vol.All(int, vol.Range(min=0, max=65535)),
    }
)

SERVICE_WRITE_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): str,
        vol.Required("address"): vol.All(int, vol.Range(min=0, max=65535)),
        vol.Required("value"): vol.All(int, vol.Range(min=0, max=65535)),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hitachi ModBus from a config entry."""
    units = entry.data.get("discovered_units", [])
    unit_types = {u["slot_id"]: u.get("unit_type", UNIT_TYPE_VRF) for u in units}
    coordinator = HitachiModbusCoordinator(hass, entry, unit_types)

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register reload listener
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Register services (only once, for the first loaded entry)
    if not hass.services.has_service(DOMAIN, SERVICE_READ_REGISTER):
        _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: HitachiModbusCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()

        # Remove services when no entries remain
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_READ_REGISTER)
            hass.services.async_remove(DOMAIN, SERVICE_WRITE_REGISTER)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register read_register / write_register services."""

    async def _handle_read(call: ServiceCall) -> None:
        entry_id: str = call.data["entry_id"]
        address: int = call.data["address"]
        coordinator: HitachiModbusCoordinator = hass.data[DOMAIN].get(entry_id)
        if coordinator is None:
            _LOGGER.error("read_register: unknown entry_id %s", entry_id)
            return
        value = await coordinator.async_read_register(address)
        _LOGGER.info(
            "read_register: address=0x%04X (%d) → %s",
            address,
            address,
            value if value is not None else "error",
        )
        # Expose result as a persistent notification so it is visible in the UI
        hass.components.persistent_notification.async_create(
            f"Register 0x{address:04X} ({address}) = {value}",
            title="Hitachi ModBus – Register read",
            notification_id=f"hitachi_reg_{address}",
        )

    async def _handle_write(call: ServiceCall) -> None:
        entry_id: str = call.data["entry_id"]
        address: int = call.data["address"]
        value: int = call.data["value"]
        coordinator: HitachiModbusCoordinator = hass.data[DOMAIN].get(entry_id)
        if coordinator is None:
            _LOGGER.error("write_register: unknown entry_id %s", entry_id)
            return
        ok = await coordinator.async_write_register(address, value)
        _LOGGER.info(
            "write_register: address=0x%04X (%d) = %d → %s",
            address,
            address,
            value,
            "OK" if ok else "FAILED",
        )
        if ok:
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_READ_REGISTER, _handle_read, schema=SERVICE_READ_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_REGISTER, _handle_write, schema=SERVICE_WRITE_SCHEMA
    )
