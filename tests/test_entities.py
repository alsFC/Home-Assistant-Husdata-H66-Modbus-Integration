"""Tests for setup and the entities."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit, WriteEvent
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.husdata_h66.const import CONF_REGISTERS, DOMAIN

from .conftest import MAC, URL, entity_id, home_page


def _writes(unit: MockModbusUnit) -> list[WriteEvent]:
    events: list[WriteEvent] = []
    unit.on_write(events.append)
    return events


async def test_setup_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    entry = setup_integration
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_device(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    (device,) = dr.async_entries_for_config_entry(
        dr.async_get(hass), setup_integration.entry_id
    )
    assert device.identifiers == {(DOMAIN, MAC)}
    assert device.name == "H66 Rego 600"
    assert device.manufacturer == "Husdata"
    assert device.model == "H66"
    assert device.sw_version == "360801"
    assert device.hw_version == "Rego 600"
    assert (dr.CONNECTION_NETWORK_MAC, MAC) in device.connections


@pytest.mark.parametrize(
    ("platform", "key", "state"),
    [
        ("sensor", "outdoor", "3.5"),
        ("sensor", "radiator_return", "39.5"),
        ("sensor", "hot_water_top", "53.1"),
        ("sensor", "add_heat_status", "0.0"),
        ("sensor", "alarm_code", "alarm_19"),
        ("binary_sensor", "switch_valve_1", STATE_OFF),
        ("sensor", "compressor_hours_heating", "37018"),
        ("sensor", "power_consumption", "2150"),
        ("sensor", "accumulated_consumption", "0.2"),
        ("binary_sensor", "compressor", STATE_ON),
        ("binary_sensor", "add_heat_step_1", STATE_OFF),
        ("binary_sensor", "alarm", STATE_OFF),
        ("number", "room_setpoint", "21.0"),
        ("number", "heat_curve", "6.5"),
        ("number", "heat_curve_parallel", "1.5"),
        ("number", "extra_hot_water", "0"),
        ("select", "electric_heater_max_power", "6_kw"),
        ("number", "summer_mode", "18.0"),
        ("switch", "electric_heater_allowed", STATE_ON),
    ],
)
async def test_states(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    platform: str,
    key: str,
    state: str,
) -> None:
    assert hass.states.get(entity_id(hass, platform, key)).state == state


async def test_number_limits(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    attrs = hass.states.get(entity_id(hass, "number", "room_setpoint")).attributes
    assert (attrs["min"], attrs["max"], attrs["step"]) == (5, 29, 0.5)
    attrs = hass.states.get(entity_id(hass, "number", "extra_hot_water")).attributes
    assert (attrs["min"], attrs["max"], attrs["step"]) == (0, 1440, 60)


async def test_missing_sensors_disabled_by_default(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    for key in ("radiator_forward", "indoor", "hot_water_mid", "room_sensor_influence"):
        entry = registry.async_get(entity_id(hass, "sensor", key))
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert registry.async_get(entity_id(hass, "sensor", "outdoor")).disabled_by is None


async def test_set_number(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_modbus: MockModbusUnit
) -> None:
    writes = _writes(mock_modbus)
    target = entity_id(hass, "number", "room_setpoint")
    await hass.services.async_call(
        "number", "set_value", {"entity_id": target, "value": 21.5}, blocking=True
    )
    assert [(w.address, w.values) for w in writes] == [(14, [215])]
    assert hass.states.get(target).state == "21.5"


async def test_set_number_invalid_step(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_modbus: MockModbusUnit
) -> None:
    writes = _writes(mock_modbus)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id(hass, "number", "room_setpoint"), "value": 21.25},
            blocking=True,
        )
    assert not writes


async def test_switch(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_modbus: MockModbusUnit
) -> None:
    writes = _writes(mock_modbus)
    target = entity_id(hass, "switch", "electric_heater_allowed")
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": target}, blocking=True
    )
    assert [(w.address, w.values) for w in writes] == [(21, [0])]
    assert hass.states.get(target).state == STATE_OFF


async def test_alarm_reset_button(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_modbus: MockModbusUnit
) -> None:
    writes = _writes(mock_modbus)
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": entity_id(hass, "button", "alarm_reset")},
        blocking=True,
    )
    # Writing 0 is what resets an alarm.
    assert [(w.address, w.values) for w in writes] == [(26, [0])]


async def test_unavailable_when_h66_stops_answering(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_modbus: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    target = entity_id(hass, "sensor", "outdoor")
    mock_modbus.fail_requests(ModbusConnectionError("gone"))
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(target).state == STATE_UNAVAILABLE

    mock_modbus.fail_requests(None)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "3.5"


async def test_setup_retries_when_h66_does_not_answer(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_web: AiohttpClientMocker,
    mock_modbus: MockModbusUnit,
) -> None:
    mock_modbus.fail_requests(ModbusConnectionError("refused"))
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_stored_map_used_without_web_page(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_modbus: MockModbusUnit,
) -> None:
    aioclient_mock.get(URL, exc=TimeoutError)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(entity_id(hass, "sensor", "outdoor")).state == "3.5"


async def test_moved_and_custom_registers_follow_web_page(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_modbus: MockModbusUnit,
) -> None:
    # Firmware moved Outdoor to address 50 and the user added a custom register.
    page = (
        home_page()
        .replace(
            "<td>6&nbsp;Input</td><td>Outdoor</td>",
            "<td>50&nbsp;Input</td><td>Outdoor</td>",
        )
        .replace(
            "</table></form>",
            "<tr><td>&nbsp;0099</td><td>51&nbsp;Input</td><td>My sensor</td>"
            "<td>12.3&nbsp;C</td></tr></table></form>",
        )
    )
    aioclient_mock.get(URL, text=page)
    mock_modbus.input[50] = 0x10000 - 72  # -7.2 °C
    mock_modbus.input[51] = 123
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id(hass, "sensor", "outdoor")).state == "-7.2"
    custom = hass.states.get(entity_id(hass, "sensor", "var_0099_my_sensor"))
    assert custom.state == "12.3"
    assert custom.attributes["unit_of_measurement"] == "°C"
    stored = {row[0]: row[1] for row in config_entry.data[CONF_REGISTERS]}
    assert stored["0007"] == 50
    assert stored["0099"] == 51


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_integration: MockConfigEntry,
) -> None:
    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )
    assert diagnostics["entry"]["data"]["host"] == "**REDACTED**"
    assert CONF_REGISTERS not in diagnostics["entry"]["data"]
    assert diagnostics["firmware"] == "360801"
    outdoor = next(r for r in diagnostics["registers"] if r["key"] == "outdoor")
    assert outdoor == {
        "address": 6,
        "space": "input",
        "variable_id": "0007",
        "key": "outdoor",
        "name": "Outdoor",
        "value": 3.5,
    }


async def test_swedish_names(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_web: AiohttpClientMocker,
    mock_modbus: MockModbusUnit,
) -> None:
    await hass.config.async_update(language="sv")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    names = {
        ("sensor", "outdoor"): "Utetemperatur",
        ("sensor", "compressor_hours_heating"): "Drifttid kompressor värme",
        ("binary_sensor", "pump_cold_circuit"): "Köldbärarpump",
        ("number", "heat_curve_parallel"): "Värmekurva parallellförskjutning",
        ("switch", "electric_heater_allowed"): "Elpatron tillåten",
        ("button", "alarm_reset"): "Återställ larm",
        ("sensor", "alarm_code"): "Senaste larm",
        ("select", "electric_heater_max_power"): "Elpatron max effekt",
    }
    for (platform, key), name in names.items():
        state = hass.states.get(entity_id(hass, platform, key))
        assert state.attributes["friendly_name"] == f"H66 Rego 600 {name}"


async def test_last_alarm(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    state = hass.states.get(entity_id(hass, "sensor", "alarm_code"))
    assert state.state == "alarm_19"
    assert state.attributes["code"] == 19
    assert "alarm_23" in state.attributes["options"]


async def test_select_electric_heater_max_power(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_modbus: MockModbusUnit
) -> None:
    writes = _writes(mock_modbus)
    target = entity_id(hass, "select", "electric_heater_max_power")
    assert hass.states.get(target).attributes["options"] == ["3_kw", "6_kw", "9_kw"]
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": target, "option": "9_kw"},
        blocking=True,
    )
    assert [(w.address, w.values) for w in writes] == [(22, [4])]
    assert hass.states.get(target).state == "9_kw"


async def test_replaced_number_entity_is_removed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_web: AiohttpClientMocker,
    mock_modbus: MockModbusUnit,
) -> None:
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "number",
        DOMAIN,
        f"{MAC}_electric_heater_max_power",
        config_entry=config_entry,
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(old.entity_id) is None


async def test_disabled_by_default_settings(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    for platform, key in (("switch", "external_control"), ("number", "holiday_mode")):
        entry = registry.async_get(entity_id(hass, platform, key))
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_external_control_is_write_only(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_modbus: MockModbusUnit,
) -> None:
    registry = er.async_get(hass)
    target = entity_id(hass, "switch", "external_control")
    registry.async_update_entity(target, disabled_by=None)
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()

    # The register reads 0, but that means nothing: the state starts unknown.
    state = hass.states.get(target)
    assert state.state == STATE_UNKNOWN
    assert state.attributes["assumed_state"] is True

    writes = _writes(mock_modbus)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": target}, blocking=True
    )
    assert [(w.address, w.values) for w in writes] == [(23, [1])]
    # Shows what was set, even though the register still reads back 0.
    mock_modbus.holding[23] = 0
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(target).state == STATE_ON
