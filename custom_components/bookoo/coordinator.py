"""Coordinator for Bookoo integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
import time

from aiobookoo_ultra.bookooscale import BookooScale
from aiobookoo_ultra.exceptions import BookooDeviceNotFound, BookooError
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from bleak_retry_connector import BleakNotFoundError, BleakOutOfConnectionSlotsError

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import async_ble_device_from_address

try:
    from homeassistant.components.bluetooth import (
        async_register_bleak_retry_connector,
    )
except ImportError:
    async_register_bleak_retry_connector = None

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_IS_VALID_SCALE
from .espresso_protocol import (
    COMMAND_CHARACTERISTIC_UUID,
    DATA_CHARACTERISTIC_UUID,
    START_EXTRACTION_COMMAND,
    STOP_EXTRACTION_COMMAND,
    EspressoMonitor,
    advertisement_is_fresh,
    backoff_deadline,
    should_connect,
)

SCAN_INTERVAL = timedelta(seconds=5)
MONITOR_SCAN_INTERVAL = timedelta(seconds=30)

_LOGGER = logging.getLogger(__name__)


class BookooCoordinator(DataUpdateCoordinator[None]):
    """Class to handle fetching data from the scale."""

    config_entry: BookooConfigEntry

    def __init__(self, hass: HomeAssistant, entry: BookooConfigEntry) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="bookoo coordinator",
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )

        self._address = entry.data[CONF_ADDRESS]
        self._scale = BookooScale(
            address_or_ble_device=self._address,
            name=entry.title,
            is_valid_scale=entry.data[CONF_IS_VALID_SCALE],
            notify_callback=self.async_update_listeners,
        )
        self._client: BleakClientWithServiceCache | None = None
        self._async_register_bleak_connector(entry)

    @property
    def scale(self) -> BookooScale:
        """Return the scale object."""
        return self._scale

    async def _async_update_data(self) -> None:
        """Fetch data."""

        # scale is already connected, return
        if self._scale.connected:
            return

        if self._client and self._client.is_connected:
            self._sync_scale_client(self._client)
            if hasattr(self._scale, "attach_client"):
                await self._scale.attach_client(self._client, setup_tasks=False)
            else:
                await self._scale.connect(setup_tasks=False)
            self._ensure_process_queue_task()
            return

        if not (ble_device := async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )):
            _LOGGER.debug("No BLE device available for %s", self._address)
            return

        await self._async_establish_link(ble_device)
        if self._client and self._client.is_connected:
            if hasattr(self._scale, "attach_client"):
                await self._scale.attach_client(self._client, setup_tasks=False)
            else:
                await self._scale.connect(setup_tasks=False)
            self._ensure_process_queue_task()

    async def _async_establish_link(self, ble_device: BLEDevice) -> None:
        """Establish the BLE link via the retry connector."""
        try:
            try:
                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    disconnected_callback=self._async_handle_link_loss,
                    name="bookoo",
                    timeout=20.0,
                )
            except TypeError:
                self._client = await establish_connection(
                    ble_device,
                    disconnected_callback=self._async_handle_link_loss,
                    name="bookoo",
                    timeout=20.0,
                )
        except (
            BleakError,
            BleakNotFoundError,
            BleakOutOfConnectionSlotsError,
            BookooDeviceNotFound,
            BookooError,
            TimeoutError,
        ) as ex:
            _LOGGER.debug(
                "Could not establish BLE link to scale: %s, Error: %s",
                self.config_entry.data[CONF_ADDRESS],
                ex,
            )
            self._scale.device_disconnected_handler(notify=False)
            self._client = None
            return

        self._scale.address_or_ble_device = ble_device
        self._sync_scale_client(self._client)

    def _sync_scale_client(self, client: BleakClientWithServiceCache | None) -> None:
        """Ensure the scale uses the established BLE client."""
        if client is None:
            return

        for attr_name in ("client", "_client", "bleak_client", "_bleak_client"):
            if hasattr(self._scale, attr_name):
                setattr(self._scale, attr_name, client)
        if ble_device := async_ble_device_from_address(
            self.hass, self._address, connectable=True
        ):
            for attr_name in ("device", "_device", "ble_device", "_ble_device"):
                if hasattr(self._scale, attr_name):
                    setattr(self._scale, attr_name, ble_device)

    @callback
    def _async_handle_link_loss(
        self, _client: BleakClientWithServiceCache | None = None
    ) -> None:
        """Handle link losses triggered by the retry connector."""
        self._scale.device_disconnected_handler(notify=False)
        self._client = None

    def _ensure_process_queue_task(self) -> None:
        """Ensure the processing queue task is running."""
        if not self._scale.process_queue_task or self._scale.process_queue_task.done():
            self._scale.process_queue_task = (
                self.config_entry.async_create_background_task(
                    hass=self.hass,
                    target=self._scale.process_queue(),
                    name="bookoo_process_queue_task",
                )
            )

    def _async_register_bleak_connector(self, entry: BookooConfigEntry) -> None:
        """Ensure bleak connections are routed through the retry connector."""
        if not async_register_bleak_retry_connector:
            _LOGGER.debug(
                "BLE retry connector helper is unavailable; skipping connector registration"
            )
            return

        try:
            entry.async_on_unload(
                async_register_bleak_retry_connector(
                    self.hass,
                    entry,
                    self._address,
                    self._async_handle_link_loss,
                    connectable=True,
                )
            )
        except TypeError:
            entry.async_on_unload(
                async_register_bleak_retry_connector(  # type: ignore[call-arg]
                    self.hass,
                    entry,
                    self._address,
                    self._async_handle_link_loss,
                )
            )


class EspressoMonitorCoordinator(DataUpdateCoordinator[None]):
    """Maintain one Espresso Monitor GATT session."""

    config_entry: BookooConfigEntry

    def __init__(self, hass: HomeAssistant, entry: BookooConfigEntry) -> None:
        """Initialize the coordinator from a config entry."""
        super().__init__(
            hass,
            _LOGGER,
            name="bookoo espresso monitor",
            update_interval=MONITOR_SCAN_INTERVAL,
            config_entry=entry,
        )
        self._address = entry.data[CONF_ADDRESS]
        self._monitor = EspressoMonitor(self._address)
        self._client: BleakClientWithServiceCache | None = None
        self._not_before = 0.0
        self._command_response = False
        self._publish_cancel: Callable[[], None] | None = None
        self._connect_lock = asyncio.Lock()
        self._connect_task: asyncio.Task[None] | None = None
        self._last_advertisement: float | None = None
        self._startup_probe_used = False
        self._closing = False
        self._async_register_bleak_connector(entry)
        self._async_register_bluetooth_callback(entry)

    @property
    def monitor(self) -> EspressoMonitor:
        """Return the protocol state object."""
        return self._monitor

    async def async_shutdown(self) -> None:
        """Drop the GATT session so the proxy slot is released on unload."""
        self._closing = True
        connect_task = self._connect_task
        if connect_task is not None and not connect_task.done():
            connect_task.cancel()
        self._async_cancel_publish()
        client = self._client
        self._client = None
        self._monitor.mark_disconnected(now=time.time())
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except BleakError:
                _LOGGER.debug(
                    "Error while releasing Espresso Monitor %s",
                    self._address,
                    exc_info=True,
                )

    async def async_start_extraction(self) -> None:
        """Ask the monitor to stream extraction data."""
        self._monitor.streaming = True
        await self._async_write(START_EXTRACTION_COMMAND)

    async def async_stop_extraction(self) -> None:
        """Ask the monitor to stop streaming extraction data."""
        self._monitor.streaming = False
        await self._async_write(STOP_EXTRACTION_COMMAND)

    async def _async_update_data(self) -> None:
        """Reconnect when the monitor is advertising. Never poll pressure."""
        await self._async_connect_if_needed()

    async def _async_connect_if_needed(self) -> None:
        """Open a link only while the device is connectable and backoff allows it."""
        if self._closing or self._connect_lock.locked():
            return

        async with self._connect_lock:
            if self._closing:
                return

            client = self._client
            if client is not None and not client.is_connected:
                self._client = None
                if self._monitor.connected:
                    self._monitor.mark_disconnected(now=time.time())
                    self._async_publish_now()

            ble_device = async_ble_device_from_address(
                self.hass,
                self._address,
                connectable=True,
            )
            now = time.monotonic()
            startup_probe = (
                ble_device is not None
                and self._last_advertisement is None
                and not self._startup_probe_used
            )
            connectable_seen = ble_device is not None and (
                advertisement_is_fresh(self._last_advertisement, now) or startup_probe
            )
            if not should_connect(
                connected=self._monitor.connected
                and client is not None
                and client.is_connected,
                connectable_seen=connectable_seen,
                now=now,
                not_before=self._not_before,
            ):
                return

            if startup_probe:
                self._startup_probe_used = True
            if ble_device is None:
                return
            await self._async_establish_link(ble_device)

    async def _async_establish_link(self, ble_device: BLEDevice) -> None:
        """Connect, subscribe, and resume the last start/stop command."""
        try:
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    disconnected_callback=self._async_handle_link_loss,
                    name="bookoo-espresso-monitor",
                    timeout=20.0,
                )
            except TypeError:
                client = await establish_connection(
                    ble_device,
                    disconnected_callback=self._async_handle_link_loss,
                    name="bookoo-espresso-monitor",
                    timeout=20.0,
                )
        except BleakOutOfConnectionSlotsError as ex:
            self._not_before = backoff_deadline(time.monotonic(), slots_exhausted=True)
            _LOGGER.debug(
                "No free Bluetooth connection slot for Espresso Monitor %s: %s",
                self._address,
                ex,
            )
            return
        except (
            BleakError,
            BleakNotFoundError,
            TimeoutError,
        ) as ex:
            self._not_before = backoff_deadline(time.monotonic(), slots_exhausted=False)
            _LOGGER.debug(
                "Could not connect to Espresso Monitor %s: %s",
                self._address,
                ex,
            )
            return

        self._client = client
        if not await self._async_subscribe(client):
            await self._async_drop_client(client)
            self._not_before = backoff_deadline(time.monotonic(), slots_exhausted=False)
            return

        self._monitor.mark_connected()
        self._not_before = 0.0
        self._async_publish_now()
        try:
            await self._async_write_desired_command()
        except HomeAssistantError:
            _LOGGER.debug(
                "Espresso Monitor %s rejected the initial extraction command",
                self._address,
                exc_info=True,
            )

    async def _async_subscribe(self, client: BleakClientWithServiceCache) -> bool:
        """Subscribe to extraction data when both characteristics exist."""
        if not _has_characteristic(
            client, DATA_CHARACTERISTIC_UUID
        ) or not _has_characteristic(client, COMMAND_CHARACTERISTIC_UUID):
            _LOGGER.debug(
                "Espresso Monitor characteristics missing on %s",
                self._address,
            )
            return False

        self._command_response = _write_requires_response(
            client, COMMAND_CHARACTERISTIC_UUID
        )
        try:
            await client.start_notify(DATA_CHARACTERISTIC_UUID, self._on_notify)
        except BleakError:
            _LOGGER.debug(
                "Could not subscribe to Espresso Monitor %s",
                self._address,
                exc_info=True,
            )
            return False
        return True

    async def _async_write_desired_command(self) -> None:
        """Send the command that matches the user's last start/stop choice."""
        payload = (
            START_EXTRACTION_COMMAND
            if self._monitor.streaming
            else STOP_EXTRACTION_COMMAND
        )
        await self._async_write(payload)

    async def _async_write(self, payload: bytes) -> None:
        """Write a command, trying the other write mode if the first is rejected."""
        client = self._client
        if client is None or not client.is_connected:
            raise HomeAssistantError("Espresso Monitor is not connected")

        responses = (self._command_response, not self._command_response)
        last_error: BleakError | None = None
        for response in responses:
            try:
                await client.write_gatt_char(
                    COMMAND_CHARACTERISTIC_UUID,
                    payload,
                    response=response,
                )
            except BleakError as err:
                last_error = err
                continue
            else:
                self._command_response = response
                return

        raise HomeAssistantError(
            "Could not send the command to the Espresso Monitor"
        ) from last_error

    async def _async_drop_client(self, client: BleakClientWithServiceCache) -> None:
        """Disconnect a client that never became a usable session."""
        if self._client is client:
            self._client = None
        try:
            if client.is_connected:
                await client.disconnect()
        except BleakError:
            _LOGGER.debug(
                "Error while dropping Espresso Monitor link %s",
                self._address,
                exc_info=True,
            )

    def _on_notify(self, _characteristic: object, data: bytearray) -> None:
        """Queue a notification onto the Home Assistant loop."""
        payload = bytes(data)
        self.hass.loop.call_soon_threadsafe(self._async_ingest, payload)

    @callback
    def _async_ingest(self, payload: bytes) -> None:
        """Store a pressure sample and publish it at the throttle interval."""
        if self._closing or not self._monitor.ingest(payload):
            return
        self._async_schedule_publish()

    @callback
    def _async_schedule_publish(self) -> None:
        """Publish immediately, or once when the 1 second window elapses."""
        delay = self._monitor.publish_delay(now=time.monotonic())
        if delay == 0:
            self._async_publish_now()
            return
        if self._publish_cancel is not None:
            return
        self._publish_cancel = async_call_later(
            self.hass,
            delay,
            self._async_flush_publish,
        )

    @callback
    def _async_flush_publish(self, _now: datetime) -> None:
        """Publish the newest sample held during the throttle window."""
        self._publish_cancel = None
        if self._closing:
            return
        self._monitor.mark_published(time.monotonic())
        self.async_update_listeners()

    @callback
    def _async_publish_now(self) -> None:
        """Push connection or sample changes to entities immediately."""
        self._async_cancel_publish()
        self._monitor.mark_published(time.monotonic())
        self.async_update_listeners()

    @callback
    def _async_cancel_publish(self) -> None:
        """Cancel a pending throttled publish."""
        if self._publish_cancel is not None:
            self._publish_cancel()
            self._publish_cancel = None

    def _async_handle_link_loss(
        self, _client: BleakClientWithServiceCache | None = None
    ) -> None:
        """Schedule link-loss handling on the event loop."""
        self.hass.loop.call_soon_threadsafe(self._async_finish_disconnect)

    @callback
    def _async_finish_disconnect(self) -> None:
        """Release the client and mark the monitor disconnected."""
        self._client = None
        if self._closing:
            self._monitor.mark_disconnected(now=time.time())
            return
        if not self._monitor.connected:
            return
        self._monitor.mark_disconnected(now=time.time())
        self._async_publish_now()

    @callback
    def _async_handle_bluetooth_seen(
        self,
        _service_info: object,
        _change: object,
    ) -> None:
        """Connect when the monitor wakes and starts advertising."""
        if self._closing or self._monitor.connected:
            return
        self._last_advertisement = time.monotonic()
        if self._connect_task is not None and not self._connect_task.done():
            return
        self._connect_task = self.hass.async_create_task(
            self._async_connect_if_needed(),
            name="bookoo_espresso_monitor_connect",
        )

    def _async_register_bluetooth_callback(self, entry: BookooConfigEntry) -> None:
        """Listen for advertisements without holding a connection slot."""
        try:
            unregister = bluetooth.async_register_callback(
                self.hass,
                self._async_handle_bluetooth_seen,
                {"address": self._address},
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        except (AttributeError, TypeError):
            _LOGGER.debug("Bluetooth advertisement callback is unavailable")
            return
        entry.async_on_unload(unregister)

    def _async_register_bleak_connector(self, entry: BookooConfigEntry) -> None:
        """Route this address through Home Assistant's retry connector."""
        if not async_register_bleak_retry_connector:
            return

        try:
            entry.async_on_unload(
                async_register_bleak_retry_connector(
                    self.hass,
                    entry,
                    self._address,
                    self._async_handle_link_loss,
                    connectable=True,
                )
            )
        except TypeError:
            entry.async_on_unload(
                async_register_bleak_retry_connector(  # type: ignore[call-arg]
                    self.hass,
                    entry,
                    self._address,
                    self._async_handle_link_loss,
                )
            )


def _has_characteristic(client: BleakClientWithServiceCache, uuid: str) -> bool:
    """Return True when the connected GATT server exposes uuid."""
    services = getattr(client, "services", None)
    if services is None:
        return False
    getter = getattr(services, "get_characteristic", None)
    if callable(getter):
        return getter(uuid) is not None
    characteristics = getattr(services, "characteristics", None)
    if isinstance(characteristics, dict):
        return any(
            getattr(char, "uuid", None) == uuid for char in characteristics.values()
        )
    return False


def _write_requires_response(client: BleakClientWithServiceCache, uuid: str) -> bool:
    """Prefer a write-with-response when the command characteristic offers it."""
    services = getattr(client, "services", None)
    getter = getattr(services, "get_characteristic", None)
    if not callable(getter):
        return False
    characteristic = getter(uuid)
    if characteristic is None:
        return False
    properties = {str(prop).lower() for prop in characteristic.properties}
    return any(prop == "write" or prop.endswith(".write") for prop in properties)


type BookooConfigEntry = ConfigEntry[BookooCoordinator | EspressoMonitorCoordinator]
