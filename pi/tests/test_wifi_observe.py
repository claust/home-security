from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scapy.layers.dot11 import (
    Dot11,
    Dot11Beacon,
    Dot11Elt,
    Dot11ProbeReq,
    RadioTap,
)

from home_security_pi.wifi_observe import (
    ChannelHopper,
    ObservationLimiter,
    build_observation,
    classify_frame,
    is_randomized_mac,
    record_if_due,
)
from home_security_pi.wifi_store import WifiObservationStore

RANDOMIZED_MAC = "a6:11:22:33:44:55"  # locally-administered bit set
STABLE_MAC = "a4:83:e7:00:11:22"  # universally-administered (real OUI)


class AdjustableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def probe_request(
    *,
    source: str,
    ssid: bytes = b"HomeNet",
    signal: int = -42,
) -> RadioTap:
    """Build a probe request the way a sniffed monitor frame would look.

    Serializing then re-dissecting mirrors what scapy hands the ``prn``
    callback for a real captured frame, so the radiotap signal field and the
    tagged-parameter walk are exercised exactly as in production.
    """
    frame = (
        RadioTap(present="dBm_AntSignal", dBm_AntSignal=signal)
        / Dot11(
            type=0, subtype=4, addr1="ff:ff:ff:ff:ff:ff", addr2=source, addr3=source
        )
        / Dot11ProbeReq()
        / Dot11Elt(ID=0, info=ssid)
        / Dot11Elt(ID=1, info=b"\x82\x84\x8b\x96")  # supported rates 1,2,5.5,11
        # HT capabilities is a fixed 26-byte element; use a realistic length so
        # re-dissection stays faithful to a real captured frame.
        / Dot11Elt(ID=45, info=bytes.fromhex("2d40" + "1b" * 24))
        / Dot11Elt(ID=127, info=b"\x00\x00\x08")  # extended capabilities
        / Dot11Elt(ID=221, info=b"\x00\x17\xf2\x0a\x00\x01")  # vendor specific
    )
    return RadioTap(bytes(frame))


def beacon(*, source: str, ssid: bytes = b"HomeNet") -> RadioTap:
    frame = (
        RadioTap()
        / Dot11(
            type=0, subtype=8, addr1="ff:ff:ff:ff:ff:ff", addr2=source, addr3=source
        )
        / Dot11Beacon()
        / Dot11Elt(ID=0, info=ssid)
        / Dot11Elt(ID=1, info=b"\x82\x84\x8b\x96")
    )
    return RadioTap(bytes(frame))


class IsRandomizedMacTests(unittest.TestCase):
    def test_locally_administered_bit_is_randomized(self) -> None:
        self.assertTrue(is_randomized_mac(RANDOMIZED_MAC))
        self.assertTrue(is_randomized_mac("02:00:00:00:00:01"))

    def test_universally_administered_is_not_randomized(self) -> None:
        self.assertFalse(is_randomized_mac(STABLE_MAC))
        self.assertFalse(is_randomized_mac("a4:83:e7:aa:bb:cc"))

    def test_malformed_mac_is_not_randomized(self) -> None:
        self.assertFalse(is_randomized_mac("not-a-mac"))


class FrameNormalizationTests(unittest.TestCase):
    def test_probe_request_normalizes_to_observation(self) -> None:
        pkt = probe_request(source=RANDOMIZED_MAC)
        observed_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

        obs = build_observation(
            pkt, observed_at_utc=observed_at, hostname="pi-livingroom", channel=6
        )

        assert obs is not None
        self.assertEqual(obs.source, "wifi")
        self.assertEqual(obs.scanner, "scapy")
        self.assertEqual(obs.address_observed, RANDOMIZED_MAC)
        self.assertEqual(obs.frame_type, "probe_req")
        self.assertEqual(obs.ssid, "HomeNet")
        self.assertEqual(obs.rssi, -42)
        self.assertEqual(obs.channel, 6)
        self.assertTrue(obs.is_randomized_mac)
        self.assertEqual(obs.hostname, "pi-livingroom")

    def test_information_elements_capture_fingerprint(self) -> None:
        pkt = probe_request(source=RANDOMIZED_MAC)
        obs = build_observation(
            pkt,
            observed_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
            hostname="h",
            channel=1,
        )
        assert obs is not None
        ies = obs.information_elements
        self.assertEqual(ies["tag_order"], [0, 1, 45, 127, 221])
        self.assertEqual(ies["supported_rates"], ["1", "2", "5.5", "11"])
        self.assertEqual(ies["ht_capabilities"], "2d40" + "1b" * 24)
        self.assertEqual(ies["ext_capabilities"], "000008")
        self.assertEqual(ies["vendor_specific"], ["0017f2"])

    def test_wildcard_probe_has_no_ssid(self) -> None:
        pkt = probe_request(source=RANDOMIZED_MAC, ssid=b"")
        obs = build_observation(
            pkt,
            observed_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
            hostname="h",
            channel=1,
        )
        assert obs is not None
        self.assertIsNone(obs.ssid)

    def test_beacon_from_stable_mac(self) -> None:
        pkt = beacon(source=STABLE_MAC)
        obs = build_observation(
            pkt,
            observed_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
            hostname="h",
            channel=11,
        )
        assert obs is not None
        self.assertEqual(obs.frame_type, "beacon")
        self.assertEqual(obs.address_observed, STABLE_MAC)
        self.assertFalse(obs.is_randomized_mac)

    def test_control_frame_is_skipped(self) -> None:
        # Type 1 = control (e.g. ACK); carries no usable fingerprint.
        pkt = RadioTap() / Dot11(type=1, subtype=13, addr1=STABLE_MAC)
        self.assertIsNone(classify_frame(pkt))
        obs = build_observation(
            pkt,
            observed_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
            hostname="h",
            channel=1,
        )
        self.assertIsNone(obs)


class StoreTests(unittest.TestCase):
    def test_initialize_creates_single_wifi_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state/observations.sqlite3"
            WifiObservationStore(database).initialize()

            with sqlite3.connect(database) as connection:
                tables = sorted(
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                )
        self.assertEqual(tables, ["wifi_address_observations"])

    def test_records_address_once_per_minute(self) -> None:
        started_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        clock = AdjustableClock(started_at)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            store = WifiObservationStore(database)
            store.initialize()
            limiter = ObservationLimiter(
                store, min_interval=timedelta(seconds=60), clock=clock
            )

            def obs_at(moment: datetime):
                pkt = probe_request(source=RANDOMIZED_MAC)
                return build_observation(
                    pkt, observed_at_utc=moment, hostname="h", channel=6
                )

            self.assertTrue(record_if_due(store, limiter, obs_at(clock())))

            clock.current = started_at + timedelta(seconds=59)
            self.assertFalse(record_if_due(store, limiter, obs_at(clock())))

            clock.current = started_at + timedelta(seconds=60)
            self.assertTrue(record_if_due(store, limiter, obs_at(clock())))

            with sqlite3.connect(database) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM wifi_address_observations"
                ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_persists_information_elements_and_randomized_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            store = WifiObservationStore(database)
            store.initialize()
            obs = build_observation(
                probe_request(source=RANDOMIZED_MAC),
                observed_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
                hostname="h",
                channel=3,
            )
            assert obs is not None
            store.insert(obs)

            with sqlite3.connect(database) as connection:
                row = connection.execute(
                    """
                    SELECT is_randomized_mac, channel, information_elements_json
                    FROM wifi_address_observations
                    """
                ).fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 3)
        self.assertIn('"tag_order"', row[2])


class ChannelHopperTests(unittest.TestCase):
    def test_cycles_channels_and_tracks_current(self) -> None:
        calls: list[int] = []
        stop = threading.Event()

        def fake_set(_iface: str, channel: int) -> None:
            calls.append(channel)
            if len(calls) >= 3:
                stop.set()

        hopper = ChannelHopper(
            interface="wlan1",
            channels=[1, 6, 11],
            dwell_seconds=0,
            stop_event=stop,
            set_channel=fake_set,
            status=lambda _m: None,
        )
        hopper.start()
        hopper.join()

        self.assertEqual(calls, [1, 6, 11])
        self.assertEqual(hopper.current_channel, 11)

    def test_survives_set_channel_failure(self) -> None:
        calls: list[int] = []
        stop = threading.Event()

        def failing_set(_iface: str, channel: int) -> None:
            calls.append(channel)
            if len(calls) >= 3:
                stop.set()
            raise OSError("CAP_NET_ADMIN missing")

        hopper = ChannelHopper(
            interface="wlan1",
            channels=[1, 6, 11],
            dwell_seconds=0,
            stop_event=stop,
            set_channel=failing_set,
            status=lambda _m: None,
        )
        hopper.start()
        hopper.join()

        self.assertEqual(len(calls), 3)
        self.assertIsNone(hopper.current_channel)


if __name__ == "__main__":
    unittest.main()
