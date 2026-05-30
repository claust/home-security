from __future__ import annotations

import argparse
import json
import signal
import socket
import subprocess
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from home_security_pi.wifi_store import (
    DEFAULT_DATABASE,
    WifiObservation,
    WifiObservationStore,
)

# 2.4 GHz channels only (decision §10): most phones/IoT probe here, and fewer
# channels means better dwell per channel. 5 GHz is intentionally out of scope.
DEFAULT_CHANNELS = tuple(range(1, 14))  # 1..13
DEFAULT_DWELL_SECONDS = 0.25
DEFAULT_MIN_INTERVAL_SECONDS = 60.0

# 802.11 management-frame subtypes we care to label explicitly.
_MGMT_SUBTYPE_NAMES = {
    0: "assoc_req",
    1: "assoc_resp",
    2: "reassoc_req",
    3: "reassoc_resp",
    4: "probe_req",
    5: "probe_resp",
    8: "beacon",
}


class Clock(Protocol):
    def __call__(self) -> datetime: ...


class WifiScanUnavailable(RuntimeError):
    """Raised when the Wi-Fi monitor cannot run on the current host."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_randomized_mac(mac: str) -> bool:
    """True when the locally-administered bit of the first octet is set.

    Modern phones randomize their MAC for probe requests by setting this bit;
    it is the honest signal that an address is not a burned-in hardware ID.
    """
    try:
        first_octet = int(mac.split(":")[0], 16)
    except (ValueError, IndexError):
        return False
    return bool(first_octet & 0b10)


def _decode_supported_rates(info: bytes) -> list[str]:
    rates: list[str] = []
    for raw in info:
        mbps = (raw & 0x7F) * 0.5
        rates.append(f"{mbps:g}")
    return rates


def _iter_elements(pkt: Any) -> list[tuple[int, bytes]]:
    """Yield ``(element_id, info_bytes)`` for each 802.11 tagged parameter.

    Sniffed frames dissect tagged parameters into specialized scapy subclasses
    (``Dot11EltRates``, ``Dot11EltHTCapabilities``, …) that do not populate the
    generic ``.info`` field, so we recover each element's on-wire TLV by
    slicing its serialized bytes. This works uniformly for generic and
    specialized elements.
    """
    dot11elt = _scapy().Dot11Elt
    elements: list[tuple[int, bytes]] = []
    element = pkt.getlayer(dot11elt)
    while isinstance(element, dot11elt):
        raw = bytes(element)
        body = raw[: len(raw) - len(bytes(element.payload))]
        if len(body) >= 2:
            declared_len = body[1]
            info = body[2 : 2 + declared_len]
            elements.append((int(element.ID), info))
        element = element.payload.getlayer(dot11elt)
    return elements


def extract_information_elements(pkt: Any) -> dict[str, object]:
    """Walk the 802.11 tagged parameters into a compact fingerprint dict.

    ``tag_order`` (the ordered element IDs) plus a few key tags is a standard,
    reasonably stable device fingerprint that survives MAC randomization.
    """
    tag_order: list[int] = []
    supported_rates: list[str] = []
    ht_capabilities: str | None = None
    ext_capabilities: str | None = None
    vendor_specific: list[str] = []

    for element_id, info in _iter_elements(pkt):
        tag_order.append(element_id)
        if element_id in (1, 50):  # Supported / Extended Supported Rates
            supported_rates.extend(_decode_supported_rates(info))
        elif element_id == 45:  # HT Capabilities
            ht_capabilities = info.hex()
        elif element_id == 127:  # Extended Capabilities
            ext_capabilities = info.hex()
        elif element_id == 221 and len(info) >= 3:  # Vendor Specific
            vendor_specific.append(info[:3].hex())

    elements: dict[str, object] = {"tag_order": tag_order}
    if supported_rates:
        elements["supported_rates"] = supported_rates
    if ht_capabilities is not None:
        elements["ht_capabilities"] = ht_capabilities
    if ext_capabilities is not None:
        elements["ext_capabilities"] = ext_capabilities
    if vendor_specific:
        elements["vendor_specific"] = vendor_specific
    return elements


def classify_frame(pkt: Any) -> str | None:
    """Return a frame-type label, or None for frames we do not record.

    Control frames (ACK/RTS/CTS) carry no useful transmitter fingerprint and
    are skipped; management subtypes get explicit names; data frames are
    labelled ``data``.
    """
    dot11 = _scapy().Dot11
    layer = pkt.getlayer(dot11)
    if layer is None:
        return None
    frame_type = int(layer.type)
    subtype = int(layer.subtype)
    if frame_type == 0:  # management
        return _MGMT_SUBTYPE_NAMES.get(subtype, f"mgmt_{subtype}")
    if frame_type == 2:  # data
        return "data"
    return None  # control frames and anything else


def extract_ssid(pkt: Any) -> str | None:
    for element_id, info in _iter_elements(pkt):
        if element_id == 0:  # SSID
            if not info:
                return None  # wildcard / broadcast probe
            try:
                return info.decode("utf-8")
            except UnicodeDecodeError:
                return info.decode("latin-1")
    return None


def extract_rssi(pkt: Any) -> int | None:
    value = getattr(pkt, "dBm_AntSignal", None)
    return value if isinstance(value, int) else None


def extract_transmitter(pkt: Any) -> str | None:
    """addr2 is the transmitter address for the frames we record."""
    dot11 = _scapy().Dot11
    layer = pkt.getlayer(dot11)
    if layer is None:
        return None
    addr = getattr(layer, "addr2", None)
    if not addr or addr == "ff:ff:ff:ff:ff:ff":
        return None
    return str(addr).lower()


def build_observation(
    pkt: Any,
    *,
    observed_at_utc: datetime,
    hostname: str,
    channel: int | None,
) -> WifiObservation | None:
    """Normalize one sniffed frame into a ``WifiObservation``.

    Returns None when the frame has no usable transmitter address or is a
    frame type we do not record (e.g. control frames).
    """
    frame_type = classify_frame(pkt)
    if frame_type is None:
        return None
    address = extract_transmitter(pkt)
    if address is None:
        return None
    return WifiObservation(
        observed_at_utc=observed_at_utc,
        source="wifi",
        scanner="scapy",
        address_observed=address,
        frame_type=frame_type,
        ssid=extract_ssid(pkt),
        rssi=extract_rssi(pkt),
        channel=channel,
        is_randomized_mac=is_randomized_mac(address),
        information_elements=extract_information_elements(pkt),
        hostname=hostname,
    )


class ObservationLimiter:
    """Rate-limit stored observations to one per address per ``min_interval``.

    Mirrors the BLE observer's limiter: an in-memory last-seen map backed by a
    DB lookup so the limit survives process restarts.
    """

    def __init__(
        self,
        store: WifiObservationStore,
        *,
        min_interval: timedelta,
        clock: Clock,
    ) -> None:
        self.store = store
        self.min_interval = min_interval
        self.clock = clock
        self._last_recorded_at: dict[str, datetime] = {}

    def should_record(self, address_observed: str) -> bool:
        now = self.clock()
        last_recorded_at = self._last_recorded_at.get(address_observed)
        if last_recorded_at is None:
            last_recorded_at = self.store.latest_observed_at(address_observed)
        return last_recorded_at is None or now - last_recorded_at >= self.min_interval

    def mark_recorded(self, address_observed: str, observed_at_utc: datetime) -> None:
        self._last_recorded_at[address_observed] = observed_at_utc


def record_if_due(
    store: WifiObservationStore,
    limiter: ObservationLimiter,
    observation: WifiObservation,
) -> bool:
    if not limiter.should_record(observation.address_observed):
        return False
    store.insert(observation)
    limiter.mark_recorded(observation.address_observed, observation.observed_at_utc)
    return True


def set_channel_via_iw(interface: str, channel: int) -> None:
    """Retune the monitor interface. Receive-only, so this is passive."""
    subprocess.run(
        ["iw", "dev", interface, "set", "channel", str(channel)],
        check=True,
        capture_output=True,
        text=True,
    )


class ChannelHopper:
    """Steps the monitor interface across the channel set in a background thread.

    Channel tuning needs ``CAP_NET_ADMIN``; if a retune fails (e.g. the
    capability is unavailable to the worker), the error is reported and the
    hopper keeps cycling — capture continues on whatever channel is current,
    so the observer degrades rather than dies.
    """

    def __init__(
        self,
        *,
        interface: str,
        channels: Sequence[int],
        dwell_seconds: float,
        stop_event: threading.Event,
        set_channel: Callable[[str, int], None] = set_channel_via_iw,
        status: Callable[[str], None] = print,
    ) -> None:
        self.interface = interface
        self.channels = list(channels)
        self.dwell_seconds = dwell_seconds
        self.stop_event = stop_event
        self.set_channel = set_channel
        self.status = status
        self._current_channel: int | None = None
        self._thread: threading.Thread | None = None

    @property
    def current_channel(self) -> int | None:
        return self._current_channel

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def join(self) -> None:
        if self._thread is not None:
            self._thread.join()

    def _run(self) -> None:
        warned = False
        while not self.stop_event.is_set():
            for channel in self.channels:
                if self.stop_event.is_set():
                    return
                try:
                    self.set_channel(self.interface, channel)
                    self._current_channel = channel
                    warned = False
                except Exception as exc:  # noqa: BLE001 - degrade, never crash
                    if not warned:
                        self.status(
                            json.dumps(
                                {
                                    "status": "channel_set_failed",
                                    "channel": channel,
                                    "error": str(exc),
                                }
                            )
                        )
                        warned = True
                self.stop_event.wait(self.dwell_seconds)


def _register_radiotap_link_type(dot11: Any) -> None:
    """Ensure scapy maps the radiotap ARPHRD (803) to the RadioTap layer.

    Importing ``scapy.layers.dot11`` normally registers this, but we register
    it explicitly too so a monitor socket reliably dissects captured frames
    regardless of scapy's import-order quirks.
    """
    try:
        from scapy.config import conf

        conf.l2types.register(803, dot11.RadioTap)
    except Exception:  # noqa: BLE001 - registration is best-effort hardening
        pass


def _scapy() -> Any:
    """Lazily import scapy's 802.11 layer namespace.

    Imported on demand (mirroring how the BLE observer imports bleak) so the
    normalization helpers can be unit-tested without a live radio and so a
    missing dependency surfaces a friendly message instead of an ImportError.
    """
    try:
        from scapy.layers import dot11 as _dot11
    except ImportError as exc:  # pragma: no cover - exercised only without scapy
        raise WifiScanUnavailable(
            "scapy is not installed. Run `uv sync --frozen` before observing."
        ) from exc
    return _dot11


def observe_wifi_addresses(
    *,
    database: Path,
    interface: str,
    channels: Sequence[int],
    dwell_seconds: float,
    min_interval_seconds: float,
    stop_event: threading.Event,
    status: Callable[[str], None] = print,
) -> None:
    try:
        from scapy.sendrecv import AsyncSniffer
    except ImportError as exc:
        raise WifiScanUnavailable(
            "scapy is not installed. Run `uv sync --frozen` before observing."
        ) from exc

    # Importing the dot11 layer has the side effect of registering the radiotap
    # link-layer type (ARPHRD 803) with scapy's L2 socket. Without it, the
    # monitor socket cannot guess the link type and delivers frames undissected
    # ("Unable to guess type ... family=803"), so nothing is ever recorded.
    # Force the import before the sniffer opens its socket.
    dot11 = _scapy()
    _register_radiotap_link_type(dot11)

    store = WifiObservationStore(database)
    store.initialize()
    limiter = ObservationLimiter(
        store,
        min_interval=timedelta(seconds=min_interval_seconds),
        clock=utc_now,
    )
    hostname = socket.gethostname()

    hopper = ChannelHopper(
        interface=interface,
        channels=channels,
        dwell_seconds=dwell_seconds,
        stop_event=stop_event,
        status=status,
    )

    def on_frame(pkt: Any) -> None:
        observed_at_utc = utc_now()
        observation = build_observation(
            pkt,
            observed_at_utc=observed_at_utc,
            hostname=hostname,
            channel=hopper.current_channel,
        )
        if observation is None:
            return
        if record_if_due(store, limiter, observation):
            status(
                json.dumps(
                    {
                        "status": "recorded",
                        "observed_at_utc": observation.observed_at_utc.isoformat(),
                        "address_observed": observation.address_observed,
                        "frame_type": observation.frame_type,
                        "ssid": observation.ssid,
                        "rssi": observation.rssi,
                        "channel": observation.channel,
                        "is_randomized_mac": observation.is_randomized_mac,
                    },
                    sort_keys=True,
                )
            )

    hopper.start()
    sniffer = AsyncSniffer(iface=interface, prn=on_frame, store=False)
    try:
        sniffer.start()
    except OSError as exc:
        stop_event.set()
        raise WifiScanUnavailable(
            f"Could not open monitor socket on {interface}: {exc}. "
            "Ensure the interface is in monitor mode and the process has "
            "CAP_NET_RAW."
        ) from exc

    try:
        while not stop_event.wait(0.5):
            if not sniffer.running:
                break
    finally:
        stop_event.set()
        try:
            sniffer.stop()
        except Exception:  # noqa: BLE001 - best-effort shutdown
            pass
        hopper.join()


def run_observer(
    *,
    database: Path,
    interface: str,
    channels: Sequence[int],
    dwell_seconds: float,
    min_interval_seconds: float,
) -> None:
    stop_event = threading.Event()

    def _handle_signal(*_args: object) -> None:
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _handle_signal)

    observe_wifi_addresses(
        database=database,
        interface=interface,
        channels=channels,
        dwell_seconds=dwell_seconds,
        min_interval_seconds=min_interval_seconds,
        stop_event=stop_event,
    )


def parse_channels(value: str) -> tuple[int, ...]:
    channels = tuple(int(part) for part in value.split(",") if part.strip())
    if not channels:
        raise argparse.ArgumentTypeError("at least one channel is required")
    return channels


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Passive 802.11 monitor-mode observer (receive-only).",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="SQLite database path for Wi-Fi address observations.",
    )
    parser.add_argument(
        "--interface",
        default="wlan1",
        help="Monitor-mode interface to sniff on.",
    )
    parser.add_argument(
        "--channels",
        type=parse_channels,
        default=DEFAULT_CHANNELS,
        help="Comma-separated 2.4 GHz channels to hop across (default 1..13).",
    )
    parser.add_argument(
        "--dwell-seconds",
        type=float,
        default=DEFAULT_DWELL_SECONDS,
        help="Seconds to dwell on each channel before hopping.",
    )
    parser.add_argument(
        "--min-interval-seconds",
        type=float,
        default=DEFAULT_MIN_INTERVAL_SECONDS,
        help="Minimum seconds between stored observations for the same MAC.",
    )
    args = parser.parse_args()

    try:
        run_observer(
            database=args.database,
            interface=args.interface,
            channels=args.channels,
            dwell_seconds=args.dwell_seconds,
            min_interval_seconds=args.min_interval_seconds,
        )
    except WifiScanUnavailable as exc:
        raise SystemExit(str(exc)) from exc


# Re-exported so callers/tests have a single import surface.
__all__ = [
    "ChannelHopper",
    "ObservationLimiter",
    "WifiObservation",
    "WifiObservationStore",
    "WifiScanUnavailable",
    "build_observation",
    "classify_frame",
    "extract_information_elements",
    "is_randomized_mac",
    "main",
    "observe_wifi_addresses",
    "record_if_due",
]


if __name__ == "__main__":
    main()
