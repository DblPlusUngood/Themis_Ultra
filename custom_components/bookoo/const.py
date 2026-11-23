"""Constants for component."""

from collections.abc import Mapping
from typing import Any, Literal

from .espresso_protocol import DEVICE_TYPE_ESPRESSO_MONITOR, DEVICE_TYPE_SCALE

DOMAIN = "bookoo"
CONF_IS_VALID_SCALE = "is_valid_scale"
CONF_DEVICE_TYPE = "device_type"

DeviceType = Literal["scale", "espresso_monitor"]


def entry_device_type(data: Mapping[str, Any]) -> DeviceType:
    """Return the stored device type, defaulting existing entries to a scale."""
    if data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_ESPRESSO_MONITOR:
        return "espresso_monitor"
    return "scale"
