"""Fixtures for Husdata H66 tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from husdata_h66 import REGO600_REGISTERS
from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.husdata_h66.const import (
    CONF_CONTROLLER,
    CONF_FIRMWARE,
    CONF_REGISTERS,
    CONF_UNIT_ID,
    DOMAIN,
)
from custom_components.husdata_h66.web import registers_to_data

HOST = "192.0.2.10"
URL = f"http://{HOST}/"
MAC = "00:11:22:33:44:55"
FIXTURES = Path(__file__).parent / "fixtures"

# Raw registers read from an H66 on firmware 360801 with a Rego 600.
CAPTURED = [
    395, 65053, 405, 471, 60, 14, 35, 65053, 531, 65053, 729, 0, 392, 510,
    210, 5, 65, 15, 510, 40, 0, 1, 2, 0, 180, 0, 1,
    1, 0, 0, 1, 1, 1, 0, 0, 19, 37018, 10760, 565, 78, 2150, 2,
]  # fmt: skip

ENTRY_DATA: dict[str, Any] = {
    CONF_HOST: HOST,
    CONF_PORT: 502,
    CONF_UNIT_ID: 1,
    CONF_REGISTERS: registers_to_data(list(REGO600_REGISTERS)),
    CONF_FIRMWARE: "360801",
    CONF_CONTROLLER: "Rego 600",
}


def home_page() -> str:
    """The H66 home page (IP and MAC address replaced)."""
    return (FIXTURES / "h66_home.html").read_text()


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    """Look up an entity id by its register key."""
    found = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{MAC}_{key}")
    assert found is not None, f"no {platform} entity for {key}"
    return found


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in every test."""


@pytest.fixture
def mock_connection() -> MockModbusConnection:
    """A mock Modbus connection answering with the captured registers."""
    connection = MockModbusConnection()
    unit = connection.for_unit(1)
    table = dict(enumerate(CAPTURED))
    unit.load_raw({"input": table, "holding": table})
    return connection


@pytest.fixture
def mock_unit(mock_connection: MockModbusConnection) -> MockModbusUnit:
    """A mock Modbus unit answering with the captured registers."""
    return mock_connection.for_unit(1)


@pytest.fixture
def mock_web(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Serve the H66 home page."""
    aioclient_mock.get(URL, text=home_page())
    return aioclient_mock


@pytest.fixture
def mock_modbus(
    mock_connection: MockModbusConnection, mock_unit: MockModbusUnit
) -> Generator[MockModbusUnit]:
    """Hand out the mock unit instead of opening real Modbus connections."""
    with (
        patch("custom_components.husdata_h66.TmodbusConnection", return_value=mock_connection),
        patch("custom_components.husdata_h66.config_flow.TmodbusConnection", return_value=mock_connection),
        patch.object(mock_connection, "close", new_callable=AsyncMock),
    ):
        yield mock_unit


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry for the H66."""
    return MockConfigEntry(
        domain=DOMAIN, title="H66 Rego 600", unique_id=MAC, data=dict(ENTRY_DATA)
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_web: AiohttpClientMocker,
    mock_modbus: MockModbusUnit,
) -> MockConfigEntry:
    """Set up the integration against the mock H66."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
