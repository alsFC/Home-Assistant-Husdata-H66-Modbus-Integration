"""Data update coordinator for the Husdata H66."""

from __future__ import annotations

from collections.abc import Coroutine
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from husdata_h66 import HusdataH66, Register
from modbus_connection import ModbusError

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

type H66ConfigEntry = ConfigEntry[H66Coordinator]

# The H66 shows a written value in its Modbus registers only after a few
# seconds (seen with the room setpoint: old value straight after the write,
# new value at the next poll 30 s later). Read back after WRITE_SETTLE, and keep showing the
# written value until a read matches it or WRITE_HOLD has passed.
WRITE_SETTLE = timedelta(seconds=10)
WRITE_HOLD = timedelta(seconds=60)


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
        # Register key -> (written value, keep it until).
        self._pending_writes: dict[str, tuple[Any, datetime]] = {}
        self._unsub_read_back: CALLBACK_TYPE | None = None

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
        return self._with_pending_writes(self.device.values)

    def _with_pending_writes(self, values: dict[str, Any]) -> dict[str, Any]:
        """Keep recently written values until the H66 reports them.

        The H66 takes a write at once, but its Modbus register shows the new
        value only seconds later. Until then a read returns the old value,
        which would make the entity jump back. A written value is kept until
        a read matches it or WRITE_HOLD has passed; after that the H66 wins.
        """
        now = dt_util.utcnow()
        for key, (value, deadline) in list(self._pending_writes.items()):
            if values.get(key) == value or now >= deadline:
                del self._pending_writes[key]
            else:
                values[key] = value
        return values

    async def async_set(self, key: str, value: float | bool) -> None:
        """Write a setting, show it at once, and read it back a bit later."""
        await self._async_write(self.device.async_set(key, value))
        self._pending_writes[key] = (value, dt_util.utcnow() + WRITE_HOLD)
        if self.data is not None:
            self.async_set_updated_data(self._with_pending_writes(dict(self.data)))

    async def async_reset_alarm(self) -> None:
        """Reset an alarm: the heat pump turns off for 10 seconds."""
        await self._async_write(self.device.async_reset_alarm())

    async def _async_write(self, write: Coroutine[Any, Any, None]) -> None:
        """Run a write, translating errors, and schedule a read-back."""
        try:
            await write
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
        self._schedule_read_back()

    @callback
    def _schedule_read_back(self) -> None:
        """Read everything once the H66 has had time to update its registers."""
        if self._unsub_read_back is not None:
            self._unsub_read_back()

        @callback
        def _read_back(_now: datetime) -> None:
            self._unsub_read_back = None
            self.config_entry.async_create_background_task(
                self.hass, self.async_refresh(), "husdata_h66 read-back"
            )

        self._unsub_read_back = async_call_later(self.hass, WRITE_SETTLE, _read_back)

    async def async_shutdown(self) -> None:
        """Cancel a pending read-back."""
        if self._unsub_read_back is not None:
            self._unsub_read_back()
            self._unsub_read_back = None
        await super().async_shutdown()
