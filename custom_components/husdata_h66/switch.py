"""Switches for the Husdata H66 on/off settings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import H66ConfigEntry
from .entity import H66Entity

PARALLEL_UPDATES = 1

SWITCHES: tuple[SwitchEntityDescription, ...] = (
    SwitchEntityDescription(
        key="electric_heater_allowed",
        translation_key="electric_heater_allowed",
        entity_category=EntityCategory.CONFIG,
    ),
    SwitchEntityDescription(
        key="external_control",
        translation_key="external_control",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: H66ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        H66Switch(coordinator, d)
        for d in SWITCHES
        if d.key in coordinator.registers and coordinator.registers[d.key].writable
    )


class H66Switch(H66Entity, SwitchEntity):
    """An on/off H66 setting."""

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self.coordinator.async_set(self.entity_description.key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self.coordinator.async_set(self.entity_description.key, False)
