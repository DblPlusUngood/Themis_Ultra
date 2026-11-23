"""Sensor platform for Bookoo."""

from collections.abc import Callable  # noqa: I001
from dataclasses import dataclass
from typing import assert_never

from aiobookoo_ultra.bookooscale import BookooScale
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorExtraStoredData,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfMass,
    UnitOfPressure,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BookooConfigEntry, BookooCoordinator, EspressoMonitorCoordinator
from .entity import BookooEntity, EspressoMonitorEntity

# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0


@dataclass(kw_only=True, frozen=True)
class BookooSensorEntityDescription(SensorEntityDescription):
    """Description for Bookoo sensor entities."""

    value_fn: Callable[[BookooScale], int | float | None]


SENSORS: tuple[BookooSensorEntityDescription, ...] = (
    BookooSensorEntityDescription(
        key="weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda scale: scale.weight,
    ),
    BookooSensorEntityDescription(
        key="flow_rate",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.MILLILITERS_PER_SECOND,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda scale: scale.flow_rate,
    ),
    BookooSensorEntityDescription(
        key="timer",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda scale: scale.timer,
    ),
    BookooSensorEntityDescription(
        key="automatic_mode_time",
        translation_key="automatic_mode_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=2,
        value_fn=lambda scale: (
            scale.automatic_mode_state.timer
            if scale.automatic_mode_state is not None
            else None
        ),
    ),
    BookooSensorEntityDescription(
        key="automatic_mode_weight",
        translation_key="automatic_mode_weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        suggested_display_precision=2,
        value_fn=lambda scale: (
            scale.automatic_mode_state.weight
            if scale.automatic_mode_state is not None
            else None
        ),
    ),
    BookooSensorEntityDescription(
        key="automatic_mode_result",
        translation_key="automatic_mode_result",
        suggested_display_precision=2,
        value_fn=lambda scale: (
            scale.automatic_mode_state.result
            if scale.automatic_mode_state is not None
            else None
        ),
    ),
)
RESTORE_SENSORS: tuple[BookooSensorEntityDescription, ...] = (
    BookooSensorEntityDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda scale: (
            scale.device_state.battery_level if scale.device_state else None
        ),
    ),
)


PRESSURE_SENSOR = SensorEntityDescription(
    key="pressure",
    device_class=SensorDeviceClass.PRESSURE,
    native_unit_of_measurement=UnitOfPressure.BAR,
    suggested_display_precision=2,
    state_class=SensorStateClass.MEASUREMENT,
)
BATTERY_SENSOR = SensorEntityDescription(
    key="battery",
    device_class=SensorDeviceClass.BATTERY,
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BookooConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""

    coordinator = entry.runtime_data
    match coordinator:
        case EspressoMonitorCoordinator():
            async_add_entities(
                [
                    EspressoMonitorPressureSensor(coordinator, PRESSURE_SENSOR),
                    EspressoMonitorBatterySensor(coordinator, BATTERY_SENSOR),
                ]
            )
        case BookooCoordinator():
            entities: list[SensorEntity] = [
                BookooSensor(coordinator, entity_description)
                for entity_description in SENSORS
            ]
            entities.extend(
                BookooRestoreSensor(coordinator, entity_description)
                for entity_description in RESTORE_SENSORS
            )
            async_add_entities(entities)
        case _ as unreachable:
            assert_never(unreachable)


class BookooSensor(BookooEntity, SensorEntity):
    """Representation of an Bookoo sensor."""

    entity_description: BookooSensorEntityDescription

    @property
    def native_value(self) -> int | float | None:
        """Return the state of the entity."""
        return self.entity_description.value_fn(self._scale)


class BookooRestoreSensor(BookooEntity, RestoreSensor):
    """Representation of an Bookoo sensor with restore capabilities."""

    entity_description: BookooSensorEntityDescription
    _restored_data: SensorExtraStoredData | None = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        self._restored_data = await self.async_get_last_sensor_data()
        if self._restored_data is not None:
            self._attr_native_value = self._restored_data.native_value
            self._attr_native_unit_of_measurement = (
                self._restored_data.native_unit_of_measurement
            )

        if self._scale.device_state is not None:
            self._attr_native_value = self.entity_description.value_fn(self._scale)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._scale.device_state is not None:
            self._attr_native_value = self.entity_description.value_fn(self._scale)
        self._async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available or self._restored_data is not None


class EspressoMonitorPressureSensor(EspressoMonitorEntity, SensorEntity):
    """Live brew pressure in bar."""

    entity_description: SensorEntityDescription

    @property
    def native_value(self) -> float | None:
        """Return the latest pressure sample."""
        return self._monitor.pressure_bar

    @property
    def available(self) -> bool:
        """Stay unavailable until the first sample arrives."""
        return super().available and self._monitor.pressure_bar is not None


class EspressoMonitorBatterySensor(EspressoMonitorEntity, RestoreSensor):
    """Battery percentage, restored while the monitor is asleep."""

    entity_description: SensorEntityDescription
    _restored_data: SensorExtraStoredData | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last battery reading."""
        await super().async_added_to_hass()
        self._restored_data = await self.async_get_last_sensor_data()
        if self._restored_data is not None:
            self._attr_native_value = self._restored_data.native_value
            self._attr_native_unit_of_measurement = (
                self._restored_data.native_unit_of_measurement
            )
        if self._monitor.battery_percent is not None:
            self._attr_native_value = self._monitor.battery_percent

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update battery when a notification includes a valid percentage."""
        if self._monitor.battery_percent is not None:
            self._attr_native_value = self._monitor.battery_percent
        self._async_write_ha_state()

    @property
    def available(self) -> bool:
        """Keep the last percentage visible while the monitor sleeps."""
        if self._monitor.connected and self._monitor.battery_percent is not None:
            return super().available
        return self._restored_data is not None
