"""pymodbus version-agnostic call helpers.

pymodbus has broken its API repeatedly across 2.x → 3.x → 3.8+:
  - 2.x:  read_holding_registers(address, count, unit=N)
  - 3.0+: read_holding_registers(address, count, slave=N)
  - 3.8+: read_holding_registers(address, *, count=1)  # slave removed, count keyword-only

We inspect the real signature at runtime and call accordingly.
"""
from __future__ import annotations

import inspect
import logging

_LOGGER = logging.getLogger(__name__)

# Cached after first inspection
_read_params: set[str] | None = None
_write_params: set[str] | None = None


def _inspect_once(client) -> tuple[set[str], set[str]]:
    global _read_params, _write_params
    if _read_params is None:
        _read_params = set(
            inspect.signature(client.read_holding_registers).parameters
        )
        _write_params = set(
            inspect.signature(client.write_register).parameters
        )
        _LOGGER.debug(
            "pymodbus API detected – read_holding_registers params: %s | "
            "write_register params: %s",
            _read_params,
            _write_params,
        )
    return _read_params, _write_params


async def modbus_read(client, address: int, count: int, slave: int):
    """Read holding registers regardless of pymodbus version."""
    read_params, _ = _inspect_once(client)

    kwargs: dict = {}
    if "count" in read_params:
        kwargs["count"] = count
    if "slave" in read_params:
        kwargs["slave"] = slave
    elif "unit" in read_params:
        kwargs["unit"] = slave

    return await client.read_holding_registers(address, **kwargs)


async def modbus_write(client, address: int, value: int, slave: int):
    """Write a single holding register regardless of pymodbus version."""
    _, write_params = _inspect_once(client)

    kwargs: dict = {"value": value}
    if "slave" in write_params:
        kwargs["slave"] = slave
    elif "unit" in write_params:
        kwargs["unit"] = slave

    return await client.write_register(address, **kwargs)
