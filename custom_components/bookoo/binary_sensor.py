"""Binary sensor platform for Bookoo scales."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never

from aiobookoo_ultra.bookooscale import BookooScale

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BookooConfigEntry, BookooCoordinator, EspressoMonitorCoordinator
from .entity import BookooEntity, EspressoMonitorEntity

# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0


@dataclass(kw_only=True, frozen=True)
class BookooBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Description for Bookoo binary sensor entities."""

    is_on_fn: Callable[[BookooScale], bool]


BINARY_SENSORS: tuple[BookooBinarySensorEntityDescription, ...] = (
    BookooBinarySensorEntityDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on_fn=lambda scale: scale.connected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BookooConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""

    coordinator = entry.runtime_data
    match coordinator:
        case EspressoMonitorCoordinator():
            async_add_entities(
                [
                    EspressoMonitorConnectedBinarySensor(
                        coordinator,
                        BINARY_SENSORS[0],
                    )
                ]
            )
        case BookooCoordinator():
            async_add_entities(
                BookooBinarySensor(coordinator, description)
                for description in BINARY_SENSORS
            )
        case _ as unreachable:
            assert_never(unreachable)


class BookooBinarySensor(BookooEntity, BinarySensorEntity):
    """Representation of an Bookoo binary sensor."""

    entity_description: BookooBinarySensorEntityDescription

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        return self.entity_description.is_on_fn(self._scale)


class EspressoMonitorConnectedBinarySensor(EspressoMonitorEntity, BinarySensorEntity):
    """Connectivity that stays available while the monitor is asleep."""

    entity_description: BookooBinarySensorEntityDescription

    @property
    def is_on(self) -> bool:
        """Return True while the GATT session is up."""
        return self._monitor.connected

    @property
    def available(self) -> bool:
        """Stay available so off means disconnected, not missing."""
        return self.coordinator.last_update_success
