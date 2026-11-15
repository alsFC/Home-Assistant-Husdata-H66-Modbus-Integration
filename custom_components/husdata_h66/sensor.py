"""Sensors for the Husdata H66."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from husdata_h66 import ALARM_CODES, VariableKind

from .binary_sensor import BINARY_SENSORS
from .button import BUTTONS
from .coordinator import H66ConfigEntry, H66Coordinator
from .entity import H66Entity
from .number import NUMBERS
from .select import SELECTS
from .switch import SWITCHES

PARALLEL_UPDATES = 0


def _temperature(key: str, **kwargs) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        **kwargs,
    )


def _hours(key: str) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


SENSORS: tuple[SensorEntityDescription, ...] = (
    _temperature("radiator_return"),
    _temperature("radiator_forward"),
    _temperature("heat_carrier_return"),
    _temperature("heat_carrier_forward"),
    _temperature("brine_in"),
    _temperature("brine_out"),
    _temperature("outdoor"),
    _temperature("indoor"),
    _temperature("hot_water_top"),
    _temperature("hot_water_mid"),
    _temperature("hot_gas"),
    _temperature("heating_setpoint"),
    _temperature("hot_water_setpoint"),
    SensorEntityDescription(
        key="add_heat_status",
        translation_key="add_heat_status",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="alarm_code",
        translation_key="alarm_code",
        device_class=SensorDeviceClass.ENUM,
        options=[f"alarm_{code}" for code in ALARM_CODES],
        # The last alarm that triggered, not an active one ("Alarm" is that).
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _hours("compressor_hours_heating"),
    _hours("compressor_hours_hot_water"),
    _hours("aux_heater_hours_heating"),
    _hours("aux_heater_hours_hot_water"),
    SensorEntityDescription(
        key="power_consumption",
        translation_key="power_consumption",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="accumulated_consumption",
        translation_key="accumulated_consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        # Restarts at 0 when the H66 boots.
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="room_sensor_influence",
        translation_key="room_sensor_influence",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)

# Registers some other platform turns into an entity.
_OTHER_PLATFORMS = {
    d.key
    for group in (BINARY_SENSORS, BUTTONS, NUMBERS, SELECTS, SWITCHES)
    for d in group
}

# For registers this integration doesn't know, e.g. custom registers.
_GENERIC: dict[VariableKind, dict] = {
    VariableKind.TEMPERATURE: {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    VariableKind.PERCENT: {
        "native_unit_of_measurement": PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    VariableKind.ENERGY: {
        "device_class": SensorDeviceClass.ENERGY,
        "native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    VariableKind.HOURS: {
        "device_class": SensorDeviceClass.DURATION,
        "native_unit_of_measurement": UnitOfTime.HOURS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    VariableKind.MINUTES: {
        "device_class": SensorDeviceClass.DURATION,
        "native_unit_of_measurement": UnitOfTime.MINUTES,
    },
    VariableKind.POWER: {
        "device_class": SensorDeviceClass.POWER,
        "native_unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
    },
}


def _generic_descriptions(coordinator: H66Coordinator) -> list[SensorEntityDescription]:
    known = {d.key for d in SENSORS} | _OTHER_PLATFORMS
    return [
        SensorEntityDescription(
            key=key, name=register.name, **_GENERIC.get(register.kind, {})
        )
        for key, register in coordinator.registers.items()
        if key not in known
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: H66ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    descriptions = [d for d in SENSORS if d.key in coordinator.registers]
    descriptions += _generic_descriptions(coordinator)
    async_add_entities(
        (H66LastAlarmSensor if d.key == "alarm_code" else H66Sensor)(coordinator, d)
        for d in descriptions
    )


class H66Sensor(H66Entity, SensorEntity):
    """A read-only H66 value."""

    entity_description: SensorEntityDescription

    def __init__(
        self, coordinator: H66Coordinator, description: SensorEntityDescription
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description)
        if (
            description.device_class is SensorDeviceClass.TEMPERATURE
            and coordinator.data.get(description.key) is None
        ):
            # The H66 reports -48.3 °C for a sensor that isn't connected.
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> float | int | None:
        """Return the value."""
        value = self.value
        if isinstance(value, bool):
            return int(value)
        return value


class H66LastAlarmSensor(H66Sensor):
    """The last alarm that triggered, even if no alarm is active now."""

    @property
    def native_value(self) -> str | None:
        """Return the alarm, or None for a code Husdata doesn't list."""
        code = self.value
        return f"alarm_{code}" if code in ALARM_CODES else None

    @property
    def extra_state_attributes(self) -> dict[str, int | None]:
        """Expose the raw alarm code."""
        return {"code": self.value}
