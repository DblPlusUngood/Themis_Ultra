"""Config flow for Bookoo integration."""

import logging
from typing import Any, assert_never

from aiobookoo_ultra.exceptions import (
    BookooDeviceNotFound,
    BookooError,
    BookooUnknownDevice,
)
from aiobookoo_ultra.helpers import is_bookoo_scale
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_DEVICE_TYPE, CONF_IS_VALID_SCALE, DOMAIN
from .espresso_protocol import DEVICE_TYPE_SCALE, DeviceKind, classify_discovery

_LOGGER = logging.getLogger(__name__)


class BookooConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for bookoo."""

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered: dict[str, Any] = {}
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""

        errors: dict[str, str] = {}

        if user_input is not None:
            mac = user_input[CONF_ADDRESS]
            if mac not in self._discovered_devices:
                for device in async_discovered_service_info(self.hass):
                    self._discovered_devices[device.address] = device
            discovered = self._discovered_devices.get(mac)
            if discovered is None:
                errors["base"] = "device_not_found"
            else:
                result = await self._async_handle_user_selection(
                    mac,
                    discovered,
                    errors,
                )
                if result is not None:
                    return result

        for device in async_discovered_service_info(self.hass):
            self._discovered_devices[device.address] = device

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        options = [
            SelectOptionDict(
                value=device_mac,
                label=f"{device.name} ({device_mac})",
            )
            for device_mac, device in self._discovered_devices.items()
        ]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def _async_handle_user_selection(
        self,
        mac: str,
        discovered: BluetoothServiceInfoBleak,
        errors: dict[str, str],
    ) -> ConfigFlowResult | None:
        """Create an entry for the chosen device, or record a form error."""
        kind = classify_discovery(discovered.name, discovered.service_uuids)
        match kind:
            case DeviceKind.ESPRESSO_MONITOR:
                return await self._async_create_monitor_entry(
                    mac,
                    discovered.name,
                )
            case DeviceKind.SCALE | None:
                try:
                    is_valid_bookoo_scale = await is_bookoo_scale(mac)
                except BookooDeviceNotFound:
                    errors["base"] = "device_not_found"
                except BookooError:
                    _LOGGER.exception("Error occurred while connecting to the scale")
                    errors["base"] = "unknown"
                except BookooUnknownDevice:
                    return self.async_abort(reason="unsupported_device")
                else:
                    await self.async_set_unique_id(format_mac(mac))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=discovered.name or "Bookoo",
                        data={
                            CONF_ADDRESS: mac,
                            CONF_DEVICE_TYPE: DEVICE_TYPE_SCALE.value,
                            CONF_IS_VALID_SCALE: is_valid_bookoo_scale,
                        },
                    )
                return None
            case _ as unreachable:
                assert_never(unreachable)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a discovered Bluetooth device."""

        kind = classify_discovery(discovery_info.name, discovery_info.service_uuids)
        if kind is None:
            kind = DeviceKind.SCALE
        default_name = (
            "Bookoo Espresso Monitor"
            if kind is DeviceKind.ESPRESSO_MONITOR
            else "Bookoo"
        )
        self._discovered[CONF_ADDRESS] = discovery_info.address
        self._discovered[CONF_NAME] = discovery_info.name or default_name
        self._discovered[CONF_DEVICE_TYPE] = kind

        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()

        match kind:
            case DeviceKind.ESPRESSO_MONITOR:
                return await self.async_step_bluetooth_confirm()
            case DeviceKind.SCALE:
                try:
                    self._discovered[CONF_IS_VALID_SCALE] = await is_bookoo_scale(
                        discovery_info.address
                    )
                except BookooDeviceNotFound:
                    _LOGGER.debug("Device not found during discovery")
                    return self.async_abort(reason="device_not_found")
                except BookooError:
                    _LOGGER.debug(
                        "Error occurred while connecting to the scale during discovery",
                        exc_info=True,
                    )
                    return self.async_abort(reason="unknown")
                except BookooUnknownDevice:
                    _LOGGER.debug("Unsupported device during discovery")
                    return self.async_abort(reason="unsupported_device")
                return await self.async_step_bluetooth_confirm()
            case _ as unreachable:
                assert_never(unreachable)

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle confirmation of Bluetooth discovery."""

        if user_input is not None:
            kind: DeviceKind = self._discovered[CONF_DEVICE_TYPE]
            data: dict[str, Any] = {
                CONF_ADDRESS: self._discovered[CONF_ADDRESS],
                CONF_DEVICE_TYPE: kind.value,
            }
            match kind:
                case DeviceKind.ESPRESSO_MONITOR:
                    pass
                case DeviceKind.SCALE:
                    data[CONF_IS_VALID_SCALE] = self._discovered[CONF_IS_VALID_SCALE]
                case _ as unreachable:
                    assert_never(unreachable)
            return self.async_create_entry(
                title=self._discovered[CONF_NAME],
                data=data,
            )

        self.context["title_placeholders"] = placeholders = {
            CONF_NAME: self._discovered[CONF_NAME]
        }

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders=placeholders,
        )

    async def _async_create_monitor_entry(
        self,
        mac: str,
        name: str | None,
    ) -> ConfigFlowResult:
        """Create an Espresso Monitor entry without opening a GATT connection."""
        await self.async_set_unique_id(format_mac(mac))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=name or "Bookoo Espresso Monitor",
            data={
                CONF_ADDRESS: mac,
                CONF_DEVICE_TYPE: DeviceKind.ESPRESSO_MONITOR.value,
            },
        )
