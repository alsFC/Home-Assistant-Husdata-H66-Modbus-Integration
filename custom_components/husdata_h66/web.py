"""Read the H66 home page: register map, firmware, controller and MAC address.

The H66 serves no identity or register list over Modbus, and its register
addresses can move after a firmware update or when custom registers are
added. Its home page lists all of that, so the integration reads it when a
gateway is added and every time the config entry is set up.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from husdata_h66 import (
    Register,
    VariableKind,
    make_register,
    parse_controller,
    parse_firmware_version,
    parse_registers,
)

_MAC = re.compile(r"Mac Address\s*</td>\s*<td[^>]*>\s*([0-9A-Fa-f:.-]{12,17})", re.I)
_TIMEOUT = aiohttp.ClientTimeout(total=10)


# Rego 1000 uses different variable IDs and writable ranges from Rego 600.
# The H66 web page supplies the live Modbus addresses; these definitions only
# add the correct Home Assistant semantics to the variable IDs.
_REGO1000_DEFINITIONS: dict[str, dict[str, Any]] = {
    "000E": {"key": "rego1000_air_intake", "kind": VariableKind.TEMPERATURE, "scale": 0.1, "unit": "°C"},
    "0011": {"key": "rego1000_pool_temperature", "kind": VariableKind.TEMPERATURE, "scale": 0.1, "unit": "°C"},
    "0020": {"key": "rego1000_radiator_forward_2", "kind": VariableKind.TEMPERATURE, "scale": 0.1, "unit": "°C"},
    "0021": {"key": "rego1000_indoor_2", "kind": VariableKind.TEMPERATURE, "scale": 0.1, "unit": "°C"},
    "1A09": {"key": "rego1000_fan", "kind": VariableKind.STATUS, "scale": 1},
    "1A0A": {"key": "rego1000_high_pressostat", "kind": VariableKind.STATUS, "scale": 1},
    "1A0B": {"key": "rego1000_low_pressostat", "kind": VariableKind.STATUS, "scale": 1},
    "1A0C": {"key": "rego1000_heating_cable", "kind": VariableKind.STATUS, "scale": 1},
    "1A0D": {"key": "rego1000_crank_case_heater", "kind": VariableKind.STATUS, "scale": 1},
    "1A20": {"key": "alarm", "kind": VariableKind.STATUS, "scale": 1},
    "1210": {"key": "rego1000_holiday_mode", "kind": VariableKind.STATUS, "scale": 1, "minimum": 0, "maximum": 1, "step": 1},
    "1A21": {"key": "rego1000_pump_radiator_2", "kind": VariableKind.STATUS, "scale": 1},
    "5C52": {"key": "rego1000_supp_energy_heating", "kind": VariableKind.ENERGY, "scale": 1, "unit": "kWh"},
    "5C53": {"key": "rego1000_supp_energy_hot_water", "kind": VariableKind.ENERGY, "scale": 1, "unit": "kWh"},
    "5C55": {"key": "rego1000_compressor_energy_heating", "kind": VariableKind.ENERGY, "scale": 1, "unit": "kWh"},
    "5C56": {"key": "rego1000_compressor_energy_hot_water", "kind": VariableKind.ENERGY, "scale": 1, "unit": "kWh"},
    "5C58": {"key": "rego1000_aux_energy_heating", "kind": VariableKind.ENERGY, "scale": 1, "unit": "kWh"},
    "5C59": {"key": "rego1000_aux_energy_hot_water", "kind": VariableKind.ENERGY, "scale": 1, "unit": "kWh"},
    "0203": {"key": "rego1000_room_setpoint", "minimum": 10, "maximum": 29, "step": 0.1},
    "2204": {"key": "rego1000_room_sensor_influence", "kind": VariableKind.NUMBER, "scale": 0.1, "minimum": 0, "maximum": 10, "step": 0.1},
    "0205": {"key": "rego1000_heat_curve_1_left", "minimum": 10, "maximum": 60, "step": 0.1},
    "0206": {"key": "rego1000_heat_curve_1_right", "minimum": 10, "maximum": 80, "step": 0.1},
    "6209": {"key": "rego1000_extra_hot_water", "kind": VariableKind.HOURS, "scale": 1, "unit": "h", "minimum": 0, "maximum": 48, "step": 1},
    "B20A": {"key": "rego1000_summer_mode", "kind": VariableKind.INTEGER, "scale": 1, "minimum": 0, "maximum": 2, "step": 1, "options": (0, 1, 2)},
    "2213": {"key": "rego1000_hot_water_program", "kind": VariableKind.INTEGER, "scale": 1, "minimum": 0, "maximum": 1, "step": 1, "options": (0, 1)},
    "221C": {"key": "rego1000_hot_water_time_program", "kind": VariableKind.INTEGER, "scale": 1, "minimum": 0, "maximum": 2, "step": 1, "options": (0, 1, 2)},
    "0217": {"key": "rego1000_outdoor_temp_offset", "minimum": -12, "maximum": 12, "step": 0.1},
    "0220": {"key": "rego1000_room_setpoint_2", "minimum": 13, "maximum": 29, "step": 0.1},
    "0222": {"key": "rego1000_heat_curve_2_left", "minimum": 10, "maximum": 60, "step": 0.1},
    "0223": {"key": "rego1000_heat_curve_2_right", "minimum": 10, "maximum": 80, "step": 0.1},
    "0219": {"key": "rego1000_pool_setpoint", "minimum": 5, "maximum": 40, "step": 0.1},
}


def _apply_rego1000_definitions(registers: list[Register]) -> list[Register]:
    """Apply Rego 1000 semantics while preserving live H66 addresses."""
    result: list[Register] = []
    for register in registers:
        definition = _REGO1000_DEFINITIONS.get(register.variable_id.upper())
        result.append(replace(register, **definition) if definition else register)
    return result


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
        registers = _apply_rego1000_definitions(parse_registers(page))
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
    return _apply_rego1000_definitions([
        make_register(variable_id, address, name, writable=writable)
        for variable_id, address, name, writable in data
    ])
