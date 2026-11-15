"""Tests for the config flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.husdata_h66.const import (
    CONF_CONTROLLER,
    CONF_FIRMWARE,
    CONF_REGISTERS,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DOMAIN,
)

from .conftest import ENTRY_DATA, HOST, MAC, URL

USER_INPUT = {CONF_HOST: HOST, CONF_PORT: 502, CONF_UNIT_ID: 1}


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return result["flow_id"]


async def test_user_flow(
    hass: HomeAssistant, mock_web: AiohttpClientMocker, mock_modbus: MockModbusUnit
) -> None:
    result = await hass.config_entries.flow.async_configure(
        await _start(hass), USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "H66 Rego 600"
    assert result["result"].unique_id == MAC
    assert result["data"] == ENTRY_DATA


async def test_user_flow_without_web_page(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_modbus: MockModbusUnit,
) -> None:
    aioclient_mock.get(URL, exc=TimeoutError)
    result = await hass.config_entries.flow.async_configure(
        await _start(hass), USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Husdata H66"
    assert result["result"].unique_id == f"{HOST}:502:1"
    assert result["data"][CONF_REGISTERS] == ENTRY_DATA[CONF_REGISTERS]
    assert result["data"][CONF_FIRMWARE] is None
    assert result["data"][CONF_CONTROLLER] is None


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, mock_web: AiohttpClientMocker, mock_modbus: MockModbusUnit
) -> None:
    flow_id = await _start(hass)
    mock_modbus.fail_requests(ModbusConnectionError("refused"))
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    # Recovers once the H66 answers.
    mock_modbus.fail_requests(None)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_web: AiohttpClientMocker,
    mock_modbus: MockModbusUnit,
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_configure(
        await _start(hass), USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    entry = setup_integration
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PORT: 5020}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PORT] == 5020


async def test_reconfigure_wrong_device(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    entry = setup_integration
    hass.config_entries.async_update_entry(entry, unique_id="aa:bb:cc:dd:ee:ff")
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"


async def test_options_flow(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    entry = setup_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: 60}
