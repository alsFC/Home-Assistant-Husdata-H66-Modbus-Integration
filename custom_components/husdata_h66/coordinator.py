"""Data update coordinator for the Husdata H66."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from husdata_h66 import HusdataH66, Register
from modbus_connection import ModbusError

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

type H66ConfigEntry = ConfigEntry[H66Coordinator]


class H66Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls all H66 registers; data is the values keyed by register key."""

    config_entry: H66ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: H66ConfigEntry,
        device: HusdataH66,
        *,
        firmware: str | None,
        controller: str | None,
        mac: str | None,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.device = device
        self.firmware = firmware
        self.controller = controller
        self.mac = mac

    @property
    def device_key(self) -> str:
        """Stable identifier of the gateway (the config entry unique id)."""
        return self.config_entry.unique_id or self.config_entry.entry_id

    @property
    def registers(self) -> dict[str, Register]:
        """The register map, keyed by register key."""
        return self.device.registers

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            report = await self.device.async_update()
        except ModbusError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if not report.complete:
            error = "; ".join(str(err) for err in report.failed.values())
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": error},
            )
        return self.device.values

    async def async_set(self, key: str, value: float | bool) -> None:
        """Write a setting, then read everything back."""
        try:
            await self.device.async_set(key, value)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.async_refresh()
