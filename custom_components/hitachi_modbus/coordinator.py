"""DataUpdateCoordinator for Hitachi ModBus Gateway."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from .modbus_compat import modbus_read, modbus_write

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATW_N_BASE,
    ATW_READ_COUNT,
    ATW_READ_START,
    ATW_STRIDE,
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
    MODBUS_STRIDE,
    OFFSET_EXIST,
    TEMP_NOT_AVAILABLE,
    UNIT_TYPE_ATW,
)

_LOGGER = logging.getLogger(__name__)

# Seconds to wait before re-reading after a write.  A command written to the
# gateway is relayed to the indoor unit over H-LINK and only then mirrored into
# the status registers, so reading back immediately returns the previous value
# and makes the UI snap back to it.
POST_WRITE_REFRESH_DELAY = 3.0


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
    """Polls the HC-A(x)MB gateway and caches per-slot register blocks.

    VRF/RAC slots: §5.2.1 block  → N_BASE + slot*32 + offset  (32 regs)
    ATW slots:     §5.2.2 block  → 5000 + slot*200 + offset   (118 regs, offsets 50-167)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        unit_types: dict[int, str],
    ) -> None:
        self._host = entry.data[CONF_HOST]
        self._port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self._slave = entry.data.get(CONF_SLAVE_ID, DEFAULT_SLAVE_ID)
        self._n_base = entry.data.get(CONF_N_BASE, DEFAULT_N_BASE)
        self._unit_types: dict[int, str] = unit_types
        self._client: AsyncModbusTcpClient | None = None

        # Slots to poll: the ones picked up during discovery.  Polling the whole
        # 0..MAX_UNITS range would spend one Modbus transaction (and, on many
        # gateways, one timeout) per empty slot on every cycle.
        self._slots: list[int] = sorted(unit_types)

        # The options flow writes the polling interval to entry.options; fall
        # back to entry.data for entries created before the options flow ran.
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
            # async_request_refresh() is called right after every write; delay
            # it so the status registers have caught up, and coalesce a burst
            # of writes (mode + fan + setpoint) into a single re-read.
            request_refresh_debouncer=Debouncer(
                hass,
                _LOGGER,
                cooldown=POST_WRITE_REFRESH_DELAY,
                immediate=False,
            ),
        )

    # ── Connection ─────────────────────────────────────────────────────────

    async def _async_connect(self) -> bool:
        # Drop any half-open socket from a previous attempt before replacing it.
        if self._client is not None:
            self._client.close()
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

    def _unit_base_521(self, slot_id: int) -> int:
        """§5.2.1 base address (VRF/RAC)."""
        return self._n_base + slot_id * MODBUS_STRIDE

    def _unit_base_522(self, slot_id: int, offset: int = 0) -> int:
        """§5.2.2 absolute address for ATW (5000 + slot*200 + offset)."""
        return ATW_N_BASE + slot_id * ATW_STRIDE + offset

    async def async_write_unit_register(
        self, slot_id: int, offset: int, value: int
    ) -> None:
        """Write one register for a specific indoor unit slot.

        Automatically selects §5.2.1 (VRF/RAC) or §5.2.2 (ATW) addressing.

        Raises HomeAssistantError if the gateway rejects the write, so a
        command that did not get through surfaces in the UI instead of the
        entity quietly snapping back on the next poll.  Note that this only
        covers a refused write: a command the gateway accepts and the indoor
        unit then overrides (the fan in Dry mode, for one) still succeeds here.
        """
        if self._unit_types.get(slot_id) == UNIT_TYPE_ATW:
            address = self._unit_base_522(slot_id, offset)
        else:
            address = self._unit_base_521(slot_id) + offset

        if not await self.async_write_register(address, value):
            raise HomeAssistantError(
                f"Hitachi gateway refused writing {value} to register {address} "
                f"(slot {slot_id}, offset {offset})"
            )

    # ── DataUpdateCoordinator update ───────────────────────────────────────

    async def _async_update_data(self) -> dict[int, list[int]]:
        if not await self._ensure_connected():
            raise UpdateFailed(
                f"Cannot connect to Hitachi gateway at {self._host}:{self._port}"
            )

        data: dict[int, list[int]] = {}
        errors = 0

        for slot_id in self._slots:
            unit_type = self._unit_types.get(slot_id)

            if unit_type == UNIT_TYPE_ATW:
                # §5.2.2: read offsets 50-167 from ATW address space
                base = self._unit_base_522(slot_id, ATW_READ_START)
                count = ATW_READ_COUNT
            else:
                # §5.2.1: read 32 registers (VRF/RAC or unknown slot check)
                base = self._unit_base_521(slot_id)
                count = MODBUS_STRIDE

            try:
                result = await modbus_read(self._client, base, count, self._slave)
                if result.isError() or not result.registers:
                    errors += 1
                    continue
                regs = result.registers

                if unit_type != UNIT_TYPE_ATW:
                    # VRF/RAC: gate on EXIST flag so unknown slots are ignored
                    if len(regs) <= OFFSET_EXIST or regs[OFFSET_EXIST] != 1:
                        continue

                data[slot_id] = regs

            except (ModbusException, asyncio.TimeoutError, OSError) as exc:
                errors += 1
                _LOGGER.warning("ModBus error polling slot %d: %s", slot_id, exc)

        if not data and errors:
            # Every configured slot failed – the link is down, so tell the
            # coordinator instead of publishing an empty (but "successful")
            # update that would leave the entities showing stale values.
            raise UpdateFailed(
                f"No slot could be read from the Hitachi gateway at "
                f"{self._host}:{self._port}"
            )

        return data

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _ensure_connected(self) -> bool:
        if self._client is None or not self._client.connected:
            return await self._async_connect()
        return True

    # ── Helpers used by climate entity ─────────────────────────────────────

    @staticmethod
    def get_signed_temp(regs: list[int], offset: int) -> float | None:
        """Return the °C value at ``offset``, or None if absent/disconnected."""
        if offset >= len(regs):
            return None
        return _parse_temp(regs[offset])
