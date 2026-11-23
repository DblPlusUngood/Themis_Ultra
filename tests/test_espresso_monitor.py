"""Tests for Bookoo Espresso Monitor parsing and connection policy."""

import importlib.util
import sys
from pathlib import Path

import pytest

PROTOCOL_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "bookoo"
    / "espresso_protocol.py"
)
spec = importlib.util.spec_from_file_location("espresso_protocol", PROTOCOL_PATH)
assert spec is not None and spec.loader is not None
espresso_protocol = importlib.util.module_from_spec(spec)
sys.modules["espresso_protocol"] = espresso_protocol
spec.loader.exec_module(espresso_protocol)

CONNECT_BACKOFF_SECONDS = espresso_protocol.CONNECT_BACKOFF_SECONDS
DEVICE_TYPE_ESPRESSO_MONITOR = espresso_protocol.DEVICE_TYPE_ESPRESSO_MONITOR
DEVICE_TYPE_SCALE = espresso_protocol.DEVICE_TYPE_SCALE
MAX_PRESSURE_BAR = espresso_protocol.MAX_PRESSURE_BAR
PUBLISH_INTERVAL_SECONDS = espresso_protocol.PUBLISH_INTERVAL_SECONDS
SLOT_BACKOFF_SECONDS = espresso_protocol.SLOT_BACKOFF_SECONDS
START_EXTRACTION_COMMAND = espresso_protocol.START_EXTRACTION_COMMAND
STOP_EXTRACTION_COMMAND = espresso_protocol.STOP_EXTRACTION_COMMAND
EspressoMonitor = espresso_protocol.EspressoMonitor
FRESH_ADVERTISEMENT_SECONDS = espresso_protocol.FRESH_ADVERTISEMENT_SECONDS
advertisement_is_fresh = espresso_protocol.advertisement_is_fresh
backoff_deadline = espresso_protocol.backoff_deadline
classify_discovery = espresso_protocol.classify_discovery
decode_pressure_packet = espresso_protocol.decode_pressure_packet
should_connect = espresso_protocol.should_connect


def test_start_and_stop_commands_match_published_protocol() -> None:
    """Command bytes are the XOR-protected packets from Bookoo's protocol table."""
    assert START_EXTRACTION_COMMAND == bytes(
        [0x02, 0x0C, 0x01, 0x00, 0x00, 0x00, 0x0F]
    )
    assert STOP_EXTRACTION_COMMAND == bytes(
        [0x02, 0x0C, 0x00, 0x00, 0x00, 0x00, 0x0E]
    )


def test_decode_pressure_is_big_endian_uint16_divided_by_100() -> None:
    """9.00 bar is byte 5-6 = 0x0384, and battery is the following byte."""
    packet = bytes([0x02, 0x1B, 0x00, 0x00, 0x03, 0x84, 87, 0x00, 0x00, 0x00])

    reading = decode_pressure_packet(packet)

    assert reading is not None
    assert reading.pressure_bar == 9.0
    assert reading.battery_percent == 87


def test_decode_accepts_rated_range_and_rejects_implausible_pressure() -> None:
    """0.00 and 20.00 bar are kept; anything above the sanity cap is dropped."""
    zero = decode_pressure_packet(bytes([0x02, 0x1B, 0x00, 0x00, 0x00, 0x00, 50]))
    ceiling = decode_pressure_packet(bytes([0x02, 0x1B, 0x00, 0x00, 0x07, 0xD0, 50]))
    too_high = decode_pressure_packet(bytes([0x02, 0x1B, 0x00, 0x00, 0x07, 0xD1, 50]))

    assert zero is not None and zero.pressure_bar == 0.0
    assert ceiling is not None and ceiling.pressure_bar == MAX_PRESSURE_BAR
    assert too_high is None


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        bytes([0x02, 0x1B, 0x00, 0x00, 0x00, 0x00]),
        bytes([0x03, 0x0B, 0x00, 0x00, 0x03, 0x84, 80]),
        bytes([0x02, 0x0C, 0x00, 0x00, 0x03, 0x84, 80]),
    ],
)
def test_decode_rejects_short_or_non_pressure_packets(packet: bytes) -> None:
    """Scale packets and truncated frames are not pressure readings."""
    assert decode_pressure_packet(packet) is None


def test_out_of_range_battery_does_not_block_pressure() -> None:
    """A battery byte above 100% is ignored, and the pressure sample is kept."""
    reading = decode_pressure_packet(
        bytes([0x02, 0x1B, 0x00, 0x00, 0x01, 0xF4, 0xFF])
    )

    assert reading is not None
    assert reading.pressure_bar == 5.0
    assert reading.battery_percent is None


def test_monitor_ingest_updates_state_only_while_connected() -> None:
    """Notifications update the latest sample and are ignored after disconnect."""
    monitor = EspressoMonitor("AA:BB:CC:DD:EE:FF")
    packet = bytes([0x02, 0x1B, 0x00, 0x00, 0x03, 0x84, 64])

    assert monitor.ingest(packet) is False
    assert monitor.pressure_bar is None

    monitor.mark_connected()
    assert monitor.ingest(packet) is True
    assert monitor.pressure_bar == 9.0
    assert monitor.battery_percent == 64

    monitor.ingest(bytes([0x02, 0x1B, 0x00, 0x00, 0x03, 0xE8, 0xFF]))
    assert monitor.pressure_bar == 10.0
    assert monitor.battery_percent == 64

    monitor.mark_disconnected(now=100.0)
    assert monitor.connected is False
    assert monitor.last_disconnect_time == 100.0
    assert monitor.ingest(bytes([0x02, 0x1B, 0x00, 0x00, 0x00, 0x64, 10])) is False
    assert monitor.pressure_bar == 10.0


def test_publish_interval_keeps_one_update_per_second() -> None:
    """Live notifications are folded into a 1 Hz publish cadence."""
    monitor = EspressoMonitor("AA:BB:CC:DD:EE:FF")

    assert monitor.publish_delay(now=0.0) == 0.0
    monitor.mark_published(0.0)
    assert monitor.publish_delay(now=0.2) == pytest.approx(
        PUBLISH_INTERVAL_SECONDS - 0.2
    )
    assert monitor.publish_delay(now=PUBLISH_INTERVAL_SECONDS) == 0.0


def test_should_connect_only_when_advertising_and_backoff_elapsed() -> None:
    """A sleeping monitor is not connectable and must not take a proxy slot."""
    assert (
        should_connect(
            connected=False,
            connectable_seen=False,
            now=10.0,
            not_before=0.0,
        )
        is False
    )
    assert (
        should_connect(
            connected=True,
            connectable_seen=True,
            now=10.0,
            not_before=0.0,
        )
        is False
    )
    assert (
        should_connect(
            connected=False,
            connectable_seen=True,
            now=10.0,
            not_before=15.0,
        )
        is False
    )
    assert (
        should_connect(
            connected=False,
            connectable_seen=True,
            now=15.0,
            not_before=15.0,
        )
        is True
    )


def test_advertisement_freshness_expires() -> None:
    """A monitor that stops advertising is no longer a connect candidate."""
    assert advertisement_is_fresh(None, 10.0) is False
    assert advertisement_is_fresh(10.0, 10.0) is True
    assert advertisement_is_fresh(10.0, 10.0 + FRESH_ADVERTISEMENT_SECONDS) is True
    assert advertisement_is_fresh(10.0, 10.0 + FRESH_ADVERTISEMENT_SECONDS + 0.1) is False


def test_slot_exhaustion_backs_off_longer_than_a_normal_failure() -> None:
    """Proxy connection-slot errors wait longer than a transient connect failure."""
    assert backoff_deadline(100.0, slots_exhausted=False) == pytest.approx(
        100.0 + CONNECT_BACKOFF_SECONDS
    )
    assert backoff_deadline(100.0, slots_exhausted=True) == pytest.approx(
        100.0 + SLOT_BACKOFF_SECONDS
    )
    assert SLOT_BACKOFF_SECONDS > CONNECT_BACKOFF_SECONDS


@pytest.mark.parametrize(
    ("name", "service_uuids", "expected"),
    [
        ("BOOKOO_EM_A1B2", [], DEVICE_TYPE_ESPRESSO_MONITOR),
        ("bookoo_em", [], DEVICE_TYPE_ESPRESSO_MONITOR),
        ("BOOKOO ESPRESSO MONITOR", [], DEVICE_TYPE_ESPRESSO_MONITOR),
        (
            "",
            ["00000FFF-0000-1000-8000-00805F9B34FB"],
            DEVICE_TYPE_ESPRESSO_MONITOR,
        ),
        ("BOOKOO_SC_U1234", [], DEVICE_TYPE_SCALE),
        ("BOOKOO", ["00000ffe-0000-1000-8000-00805f9b34fb"], DEVICE_TYPE_SCALE),
        (None, ["00000ffe-0000-1000-8000-00805f9b34fb"], DEVICE_TYPE_SCALE),
        ("Kitchen speaker", [], None),
        ("BOOKOO_EM", ["00000ffe-0000-1000-8000-00805f9b34fb"], DEVICE_TYPE_ESPRESSO_MONITOR),
    ],
)
def test_classify_discovery_by_name_or_service(
    name: str | None,
    service_uuids: list[str],
    expected: str | None,
) -> None:
    """Espresso Monitors are identified without connecting; scales stay scales."""
    assert classify_discovery(name, service_uuids) == expected
