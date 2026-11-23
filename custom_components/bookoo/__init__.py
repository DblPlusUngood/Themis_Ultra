"""Initialize the Bookoo component."""

import sys
from pathlib import Path
from typing import assert_never

_EXTERNAL_LIB_DIR = Path(__file__).resolve().parent / "external" / "aiobookoo-Ultra"
if _EXTERNAL_LIB_DIR.exists() and str(_EXTERNAL_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTERNAL_LIB_DIR))

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import entry_device_type
from .coordinator import (
    BookooConfigEntry,
    BookooCoordinator,
    EspressoMonitorCoordinator,
)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]
MONITOR_PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: BookooConfigEntry) -> bool:
    """Set up bookoo as config entry."""

    device_type = entry_device_type(entry.data)
    match device_type:
        case "espresso_monitor":
            coordinator: BookooCoordinator | EspressoMonitorCoordinator = (
                EspressoMonitorCoordinator(hass, entry)
            )
            platforms = MONITOR_PLATFORMS
        case "scale":
            coordinator = BookooCoordinator(hass, entry)
            platforms = PLATFORMS
        case _ as unreachable:
            assert_never(unreachable)

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BookooConfigEntry) -> bool:
    """Unload a config entry."""

    if isinstance(entry.runtime_data, EspressoMonitorCoordinator):
        await entry.runtime_data.async_shutdown()

    device_type = entry_device_type(entry.data)
    match device_type:
        case "espresso_monitor":
            platforms = MONITOR_PLATFORMS
        case "scale":
            platforms = PLATFORMS
        case _ as unreachable:
            assert_never(unreachable)

    return await hass.config_entries.async_unload_platforms(entry, platforms)
