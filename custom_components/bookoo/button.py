"""Button entities for Bookoo scales."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, assert_never

from aiobookoo_ultra.bookooscale import BookooScale
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import (
    BookooConfigEntry,
    BookooCoordinator,
    EspressoMonitorCoordinator,
)
from .entity import BookooEntity, EspressoMonitorEntity

PARALLEL_UPDATES = 0


@dataclass(kw_only=True, frozen=True)
class BookooButtonEntityDescription(ButtonEntityDescription):
    """Description for bookoo button entities."""

    press_fn: Callable[[BookooScale], Coroutine[Any, Any, None]]


BUTTONS: tuple[BookooButtonEntityDescription, ...] = (
    BookooButtonEntityDescription(
        key="tare",
        translation_key="tare",
        press_fn=lambda scale: scale.tare(),
    ),
    BookooButtonEntityDescription(
        key="reset_timer",
        translation_key="reset_timer",
        press_fn=lambda scale: scale.reset_timer(),
    ),
    BookooButtonEntityDescription(
        key="start",
        translation_key="start",
        press_fn=lambda scale: scale.start_timer(),
    ),
    BookooButtonEntityDescription(
        key="stop",
        translation_key="stop",
        press_fn=lambda scale: scale.stop_timer(),
    ),
    BookooButtonEntityDescription(
        key="tare_and_start",
        translation_key="tare_and_start",
        press_fn=lambda scale: scale.tare_and_start_timer(),
    ),
    BookooButtonEntityDescription(
        key="shutdown",
        translation_key="shutdown",
        press_fn=lambda scale: scale.shutdown(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BookooConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities and services."""

    coordinator = entry.runtime_data
    match coordinator:
        case EspressoMonitorCoordinator():
            async_add_entities(
                EspressoMonitorButton(coordinator, description)
                for description in MONITOR_BUTTONS
            )
        case BookooCoordinator():
            async_add_entities(
                BookooButton(coordinator, description) for description in BUTTONS
            )
        case _ as unreachable:
            assert_never(unreachable)


class BookooButton(BookooEntity, ButtonEntity):
    """Representation of an Bookoo button."""

    entity_description: BookooButtonEntityDescription

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.entity_description.press_fn(self._scale)


@dataclass(kw_only=True, frozen=True)
class EspressoMonitorButtonEntityDescription(ButtonEntityDescription):
    """Description for Espresso Monitor button entities."""

    press_fn: Callable[[EspressoMonitorCoordinator], Coroutine[Any, Any, None]]


MONITOR_BUTTONS: tuple[EspressoMonitorButtonEntityDescription, ...] = (
    EspressoMonitorButtonEntityDescription(
        key="start_extraction",
        translation_key="start_extraction",
        press_fn=lambda coordinator: coordinator.async_start_extraction(),
    ),
    EspressoMonitorButtonEntityDescription(
        key="stop_extraction",
        translation_key="stop_extraction",
        press_fn=lambda coordinator: coordinator.async_stop_extraction(),
    ),
)


class EspressoMonitorButton(EspressoMonitorEntity, ButtonEntity):
    """Start or stop extraction streaming."""

    entity_description: EspressoMonitorButtonEntityDescription

    async def async_press(self) -> None:
        """Send the published start or stop command."""
        await self.entity_description.press_fn(self.coordinator)
