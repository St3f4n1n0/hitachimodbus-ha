"""pymodbus version-agnostic call helpers.

pymodbus has renamed the same two arguments repeatedly:
  - 2.x:   read_holding_registers(address, count, unit=N)
  - 3.0+:  read_holding_registers(address, count, slave=N)
  - 3.8+:  read_holding_registers(address, *, count=1, slave=N)  # count kw-only
  - 3.10+: read_holding_registers(address, *, count=1, device_id=N)  # slave renamed

We inspect the real signature at runtime and call accordingly.  The slave/unit/
device_id argument matters: dropping it silently addresses slave 1, which is the
factory default of the gateway and therefore fails in a way that looks like a
wiring problem rather than a bug.
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


def _slave_kwarg(params: set[str], slave: int, func: str) -> dict:
    """Return the keyword this pymodbus build uses for the slave/unit address."""
    for name in ("slave", "device_id", "unit"):
        if name in params:
            return {name: slave}
    _LOGGER.warning(
        "pymodbus %s() accepts no slave/device_id argument (parameters: %s); "
        "requests will use the client default instead of slave %d",
        func,
        sorted(params),
        slave,
    )
    return {}


async def modbus_read(client, address: int, count: int, slave: int):
    """Read holding registers regardless of pymodbus version."""
    read_params, _ = _inspect_once(client)

    kwargs: dict = {}
    if "count" in read_params:
        kwargs["count"] = count
    kwargs.update(_slave_kwarg(read_params, slave, "read_holding_registers"))

    return await client.read_holding_registers(address, **kwargs)


async def modbus_write(client, address: int, value: int, slave: int):
    """Write a single holding register regardless of pymodbus version."""
    _, write_params = _inspect_once(client)

    kwargs: dict = {"value": value}
    kwargs.update(_slave_kwarg(write_params, slave, "write_register"))

    return await client.write_register(address, **kwargs)
