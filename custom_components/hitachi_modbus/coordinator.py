"""DataUpdateCoordinator for Hitachi ModBus Gateway."""
from __future__ import annotations

import logging
from datetime import timedelta

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from .modbus_compat import modbus_read, modbus_write

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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
    GATEWAY_REG_TYPE,
    MAX_UNITS,
    MODBUS_STRIDE,
    OFFSET_EXIST,
    OFFSET_SYS_ADDR,
    OFFSET_UNIT_ADDR,
    TEMP_NOT_AVAILABLE,
)

_LOGGER = logging.getLogger(__name__)


def _to_signed(val: int) -> int:
    """Convert unsigned 16-bit ModBus register value to signed integer."""
    return val if val < 0x8000 else val - 0x10000


def _parse_temp(val: int) -> float | None:
    """Return °C or None when the sensor is disconnected (value ≥ 0x00FF)."""
    signed = _to_signed(val)
    if signed >= TEMP_NOT_AVAILABLE or signed <= -TEMP_NOT_AVAILABLE:
        return None
    return float(signed)




class HitachiModbusCoordinator(DataUpdateCoordinator[dict[int, list[int]]]):
    """Polls the HC-A(x)MB gateway and caches per-slot register blocks."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._host = entry.data[CONF_HOST]
        self._port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self._slave = entry.data.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID)
        self._n_base = entry.data.get(CONF_N_BASE, DEFAULT_N_BASE)
        self._client: AsyncModbusTcpClient | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )

    # ── Connection ─────────────────────────────────────────────────────────

    async def _async_connect(self) -> bool:
        self._client = AsyncModbusTcpClient(host=self._host, port=self._port)
        connected = await self._client.connect()
        if not connected:
            _LOGGER.error(
                "Cannot connect to Hitachi gateway at %s:%s", self._host, self._port
            )
        return connected

    async def async_disconnect(self) -> None:
        if self._client and self._client.connected:
            self._client.close()
        self._client = None

    # ── Gateway info ───────────────────────────────────────────────────────

    async def async_get_gateway_info(self) -> dict:
        """Read device type and firmware version registers."""
        if not await self._ensure_connected():
            return {}
        try:
            result = await modbus_read(self._client, GATEWAY_REG_TYPE, 2, self._slave)
            if result.isError():
                return {}
            return {
                "device_type": result.registers[0],
                "firmware": result.registers[1],
            }
        except ModbusException as exc:
            _LOGGER.warning("Error reading gateway info: %s", exc)
            return {}

    # ── Register read/write services ───────────────────────────────────────

    async def async_read_register(self, address: int) -> int | None:
        """Read a single raw Modbus register (exposed as HA service)."""
        if not await self._ensure_connected():
            return None
        try:
            result = await modbus_read(self._client, address, 1, self._slave)
            if result.isError():
                return None
            return result.registers[0]
        except ModbusException as exc:
            _LOGGER.error("Read register 0x%04X failed: %s", address, exc)
            return None

    async def async_write_register(self, address: int, value: int) -> bool:
        """Write a single raw Modbus register (exposed as HA service)."""
        if not await self._ensure_connected():
            return False
        try:
            result = await modbus_write(self._client, address, value, self._slave)
            return not result.isError()
        except ModbusException as exc:
            _LOGGER.error(
                "Write register 0x%04X = %d failed: %s", address, value, exc
            )
            return False

    # ── Unit-level helpers ─────────────────────────────────────────────────

    def _unit_base(self, slot_id: int) -> int:
        return self._n_base + slot_id * MODBUS_STRIDE

    async def async_write_unit_register(
        self, slot_id: int, offset: int, value: int
    ) -> bool:
        """Write one register for a specific indoor unit slot."""
        return await self.async_write_register(
            self._unit_base(slot_id) + offset, value
        )

    # ── DataUpdateCoordinator update ───────────────────────────────────────

    async def _async_update_data(self) -> dict[int, list[int]]:
        if not await self._ensure_connected():
            raise UpdateFailed(
                f"Cannot connect to Hitachi gateway at {self._host}:{self._port}"
            )

        data: dict[int, list[int]] = {}
        for slot_id in range(MAX_UNITS):
            base = self._unit_base(slot_id)
            try:
                result = await modbus_read(
                    self._client, base, MODBUS_STRIDE, self._slave
                )
                if result.isError() or not result.registers:
                    continue
                regs = result.registers
                if regs[OFFSET_EXIST] != 1:
                    continue
                data[slot_id] = regs
            except ModbusException as exc:
                _LOGGER.warning("ModBus error polling slot %d: %s", slot_id, exc)

        return data

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _ensure_connected(self) -> bool:
        if self._client is None or not self._client.connected:
            return await self._async_connect()
        return True

    # ── Helpers used by climate entity ─────────────────────────────────────

    @staticmethod
    def get_signed_temp(regs: list[int], offset: int) -> float | None:
        return _parse_temp(regs[offset])
