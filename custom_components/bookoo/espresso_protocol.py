"""Bookoo Espresso Monitor BLE protocol.

The byte layout comes from Bookoo's published Espresso Monitor protocol:
service ``0x0FFF``, commands on ``0xFF01``, extraction data on ``0xFF02``.
Pressure is a big-endian uint16 holding bar * 100. The next byte is the
battery percentage. Command packets end with an XOR checksum.

https://github.com/BooKooCode/OpenSource/blob/main/espresso_monitor/protocols.md
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

MONITOR_SERVICE_UUID = "00000fff-0000-1000-8000-00805f9b34fb"
SCALE_SERVICE_UUID = "00000ffe-0000-1000-8000-00805f9b34fb"
COMMAND_CHARACTERISTIC_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
DATA_CHARACTERISTIC_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"

PRODUCT_NUMBER = 0x02
EXTRACTION_DATA_TYPE = 0x1B
COMMAND_TYPE = 0x0C

MAX_PRESSURE_BAR = 20.0
PUBLISH_INTERVAL_SECONDS = 1.0
CONNECT_BACKOFF_SECONDS = 10.0
SLOT_BACKOFF_SECONDS = 30.0
FRESH_ADVERTISEMENT_SECONDS = 60.0
MODEL = "Espresso Monitor"


class DeviceKind(StrEnum):
    """Bluetooth devices this integration can set up."""

    SCALE = "scale"
    ESPRESSO_MONITOR = "espresso_monitor"


DEVICE_TYPE_SCALE = DeviceKind.SCALE
DEVICE_TYPE_ESPRESSO_MONITOR = DeviceKind.ESPRESSO_MONITOR


def _checksum(body: bytes) -> int:
    """XOR every byte, matching Bookoo's command checksum."""
    value = 0
    for byte in body:
        value ^= byte
    return value


def build_extraction_command(*, start: bool) -> bytes:
    """Build a start or stop extraction command."""
    body = bytes(
        (
            PRODUCT_NUMBER,
            COMMAND_TYPE,
            0x01 if start else 0x00,
            0x00,
            0x00,
            0x00,
        )
    )
    return body + bytes((_checksum(body),))


START_EXTRACTION_COMMAND = build_extraction_command(start=True)
STOP_EXTRACTION_COMMAND = build_extraction_command(start=False)


@dataclass(frozen=True, kw_only=True)
class PressureReading:
    """One decoded extraction-data notification."""

    pressure_bar: float
    battery_percent: int | None


def decode_pressure_packet(data: bytes | bytearray) -> PressureReading | None:
    """Decode an extraction-data notification.

    Returns None for truncated frames, non-pressure packets, and pressure
    values above the sanity cap. A battery byte outside 0-100 does not
    discard the pressure sample.
    """
    if len(data) < 7 or data[0] != PRODUCT_NUMBER or data[1] != EXTRACTION_DATA_TYPE:
        return None

    pressure_bar = ((data[4] << 8) | data[5]) / 100
    if pressure_bar > MAX_PRESSURE_BAR:
        return None

    battery_byte = data[6]
    battery_percent = battery_byte if battery_byte <= 100 else None
    return PressureReading(
        pressure_bar=pressure_bar,
        battery_percent=battery_percent,
    )


class EspressoMonitor:
    """Latest sample and connection flags for one Espresso Monitor."""

    model = MODEL

    def __init__(self, address: str) -> None:
        """Store the Bluetooth address. Streaming starts enabled."""
        self.address = address
        self.pressure_bar: float | None = None
        self.battery_percent: int | None = None
        self.connected = False
        self.streaming = True
        self.last_disconnect_time: float | None = None
        self._last_publish_at: float | None = None

    @property
    def mac(self) -> str:
        """Return the Bluetooth address used for the device registry."""
        return self.address

    def mark_connected(self) -> None:
        """Record an active GATT session."""
        self.connected = True

    def mark_disconnected(self, *, now: float | None = None) -> None:
        """Record link loss without clearing the last sample."""
        self.connected = False
        if now is not None:
            self.last_disconnect_time = now

    def ingest(self, data: bytes | bytearray) -> bool:
        """Apply a notification when the link is up. Return True if it parsed."""
        if not self.connected:
            return False
        reading = decode_pressure_packet(data)
        if reading is None:
            return False
        self.pressure_bar = reading.pressure_bar
        if reading.battery_percent is not None:
            self.battery_percent = reading.battery_percent
        return True

    def publish_delay(self, *, now: float) -> float:
        """Seconds until the next Home Assistant state publish is due."""
        if self._last_publish_at is None:
            return 0.0
        return max(0.0, PUBLISH_INTERVAL_SECONDS - (now - self._last_publish_at))

    def mark_published(self, now: float) -> None:
        """Remember when listeners were last notified."""
        self._last_publish_at = now


def preferred_advertisement_time(
    service_info_time: float | None,
    callback_time: float | None,
) -> float | None:
    """Prefer the scanner's last-seen time over a change-only callback.

    Home Assistant does not invoke advertisement callbacks again while the
    payload is unchanged, so a callback timestamp goes stale on a monitor
    that keeps advertising the same name and services.
    """
    if service_info_time is not None:
        return service_info_time
    return callback_time


def should_retry_extraction_command(
    *,
    connected: bool,
    command_pending: bool,
    closing: bool,
) -> bool:
    """Return True when a failed start/stop should be sent again on the open link."""
    return connected and command_pending and not closing


def battery_available(
    *,
    connected: bool,
    has_live_battery: bool,
    has_cached_value: bool,
    coordinator_success: bool,
) -> bool:
    """Keep the last battery percentage visible after the monitor sleeps."""
    if connected and has_live_battery:
        return coordinator_success
    return has_cached_value


def advertisement_is_fresh(
    last_seen: float | None,
    now: float,
    *,
    limit: float = FRESH_ADVERTISEMENT_SECONDS,
) -> bool:
    """Return True when an advertisement arrived inside the fresh window."""
    return last_seen is not None and now - last_seen <= limit


def should_connect(
    *,
    connected: bool,
    connectable_seen: bool,
    now: float,
    not_before: float,
) -> bool:
    """Return True only when an advertisement is waiting and backoff has elapsed.

    A monitor that is asleep does not advertise as connectable. Skipping the
    attempt leaves the proxy connection slot free.
    """
    if connected or not connectable_seen:
        return False
    return now >= not_before


def backoff_deadline(now: float, *, slots_exhausted: bool) -> float:
    """Return the monotonic time of the next connection attempt."""
    delay = SLOT_BACKOFF_SECONDS if slots_exhausted else CONNECT_BACKOFF_SECONDS
    return now + delay


def classify_discovery(
    name: str | None,
    service_uuids: Iterable[str],
) -> DeviceKind | None:
    """Classify a discovery from its advertised name and service UUIDs.

    The Espresso Monitor name (``BOOKOO_EM`` / ``Espresso Monitor``) and
    service ``0x0FFF`` win over the scale matchers so a monitor is never
    validated as a Themis scale.
    """
    folded = (name or "").casefold()
    uuids = {uuid.casefold() for uuid in service_uuids}
    monitor_name = folded.startswith("bookoo_em") or "espresso monitor" in folded
    if monitor_name or MONITOR_SERVICE_UUID in uuids:
        return DeviceKind.ESPRESSO_MONITOR
    if folded.startswith("bookoo") or SCALE_SERVICE_UUID in uuids:
        return DeviceKind.SCALE
    return None
