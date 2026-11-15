"""Read the H66 home page: register map, firmware, controller and MAC address.

The H66 serves no identity or register list over Modbus, and its register
addresses can move after a firmware update or when custom registers are
added. Its home page lists all of that, so the integration reads it when a
gateway is added and every time the config entry is set up.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from husdata_h66 import (
    Register,
    make_register,
    parse_controller,
    parse_firmware_version,
    parse_registers,
)

_MAC = re.compile(r"Mac Address\s*</td>\s*<td[^>]*>\s*([0-9A-Fa-f:.-]{12,17})", re.I)
_TIMEOUT = aiohttp.ClientTimeout(total=10)


class H66WebError(Exception):
    """The H66 home page could not be read or parsed."""


@dataclass(frozen=True, slots=True)
class H66Info:
    """What the H66 home page tells about the gateway."""

    registers: list[Register]
    firmware: str | None
    controller: str | None
    mac: str | None


def parse_mac(page: str) -> str | None:
    """Return the gateway's MAC address in Home Assistant's format, if present."""
    match = _MAC.search(page)
    return format_mac(match.group(1)) if match else None


def parse_info(page: str) -> H66Info:
    """Parse the H66 home page.

    Raises ``H66WebError`` if the page has no parameter table.
    """
    try:
        registers = parse_registers(page)
    except ValueError as err:
        raise H66WebError(str(err)) from err
    return H66Info(
        registers=registers,
        firmware=parse_firmware_version(page),
        controller=parse_controller(page),
        mac=parse_mac(page),
    )


async def async_fetch_info(hass: HomeAssistant, host: str) -> H66Info:
    """Fetch and parse the H66 home page.

    Raises ``H66WebError`` if the page cannot be read or has no parameter table.
    """
    session = async_get_clientsession(hass)
    try:
        async with session.get(f"http://{host}/", timeout=_TIMEOUT) as response:
            response.raise_for_status()
            page = await response.text(errors="replace")
    except (aiohttp.ClientError, TimeoutError) as err:
        raise H66WebError(f"cannot read http://{host}/: {err}") from err
    return parse_info(page)


def registers_to_data(registers: list[Register]) -> list[list[Any]]:
    """Serialise a register map for a config entry."""
    return [[r.variable_id, r.address, r.name, r.writable] for r in registers]


def registers_from_data(data: list[list[Any]]) -> list[Register]:
    """Rebuild a register map stored by ``registers_to_data``."""
    return [
        make_register(variable_id, address, name, writable=writable)
        for variable_id, address, name, writable in data
    ]
