# Wi-Fi monitor-mode scanner — design & implementation plan

Status: **implemented**. This document is the agreed plan for the passive 802.11 ("Wi-Fi")
device scanner that now runs alongside the existing BLE scanner on the external USB Wi-Fi
adapter (`wlan1`) of a monitor-capable Fetcher Hub Pi. Operator setup is documented in
`docs/raspberry-pi.md` (§ "Wi-Fi Monitor"); this file remains the design rationale.

## Goal

Passively observe nearby Wi-Fi devices the same way the BLE observer watches BLE
advertisements: record `(timestamp, MAC, RSSI, fingerprint)` per sighting into the Pi's
SQLite database, snapshot it to the hub, and expose it through the read-only API.

Decisions already made:

- **Data model:** Option B — a **parallel `wifi_address_observations` table** with the same
  grain and primary key as `ble_address_observations`, but Wi-Fi-shaped fingerprint columns.
  The BLE path is left untouched.
- **Capture scope:** **capture everything** — all observed management/data frames (probe
  requests, beacons, probe responses, associated-client data frames), not just one frame type.
  Both presence/vendor census *and* stable-device tracking are in scope.
- **Optional per Pi:** only some Pis have a monitor-capable external adapter (the living-room
  Pi does; the front-yard Pi does **not**). The Wi-Fi monitor is therefore an **opt-in,
  per-Pi** service: a Pi without it must deploy, snapshot, prune, and ingest exactly as today,
  with no Wi-Fi unit, no `wifi_address_observations` table, and no errors. See §6.

## Safety boundary (AGENTS.md)

This is **passive, receive-only** monitoring of the user's own environment. It MUST NOT
deauth, spoof, inject, jam, or attempt association. It records ambient frames only. Because
monitor mode also hears neighbours' devices and the SSIDs their phones probe for, treat all
captured MACs, SSIDs, IEs, and RSSI histories as sensitive (per AGENTS.md) and never commit
real captures. MACs and SSIDs are **stored raw** (decision §10) for full analytical value —
this is the most sensitive at-rest choice, so the archive/DB files must stay private and
untracked.

---

## 1. Hardware feasibility (confirmed on the living-room Pi)

Verified live on `home-security-pi-livingroom` (192.168.86.125):

| Radio | Interface | Driver | Monitor mode? | Role |
| --- | --- | --- | --- | --- |
| External USB (MediaTek MT76x0) | `wlan1` / phy0 | `mt76x0u` | **Yes** (`iw phy phy0 info` lists `* monitor`) | **dedicated to sniffing** |
| Built-in (Broadcom) | `wlan0` / phy1 | brcm | **No** | keeps the Pi online (SSID `Gustav`) |

Consequences baked into this plan:

- `wlan1` is the **only** monitor-capable radio, so it is dedicated to sniffing; `wlan0`
  stays on normal Wi-Fi for connectivity/SSH. The two uses are mutually exclusive on one
  radio, so this split is mandatory, not just convenient.
- `wlan1` must be marked **unmanaged in NetworkManager**, otherwise NM fights monitor mode.
- Tooling state on the Pi today: `iw` 6.9 is installed (but `/usr/sbin` is missing from the
  non-login SSH `PATH`); `tcpdump`, `rfkill`, and `scapy` are **not** installed; the deploy
  user has **no passwordless sudo** beyond the narrow home-security sudoers rules. Regulatory
  domain should be set for Denmark (`iw reg set DK`) so channel tuning is permitted.

---

## 2. How the data fits the database (Option B)

### New Pi-side table (in the **same** `observations.sqlite3`)

Putting the table in the existing DB file means the Pi snapshot (`snapshot.py` uses
`src.backup(dst)`, a whole-file copy) picks it up **for free** — no new file to sync.

```sql
CREATE TABLE IF NOT EXISTS wifi_address_observations (
  id INTEGER PRIMARY KEY,
  observed_at_utc TEXT NOT NULL,
  source TEXT NOT NULL,                 -- 'wifi'
  scanner TEXT NOT NULL,                -- 'scapy'
  address_observed TEXT NOT NULL,       -- source/transmitter MAC (may be randomized)
  frame_type TEXT NOT NULL,             -- 'probe_req' | 'beacon' | 'probe_resp' | 'data' | ...
  ssid TEXT,                            -- probed/advertised SSID if present, else NULL
  rssi INTEGER,                         -- from radiotap dBm_AntSignal
  channel INTEGER,                      -- channel the frame was heard on
  is_randomized_mac INTEGER NOT NULL,   -- 1 if locally-administered bit set, else 0
  information_elements_json TEXT NOT NULL, -- ordered 802.11 tag fingerprint (JSON)
  hostname TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wifi_address_observations_address_time
  ON wifi_address_observations(address_observed, observed_at_utc);
```

### Hub-side archive table (`archive.py`)

Mirrors the BLE archive table: adds `scanner_id` + `ingested_at_utc`, same composite PK and
`INSERT OR IGNORE` dedup (one row per scanner per second per MAC).

```sql
CREATE TABLE IF NOT EXISTS wifi_address_observations (
  scanner_id TEXT NOT NULL,
  observed_at_utc TEXT NOT NULL,
  source TEXT NOT NULL,
  scanner TEXT NOT NULL,
  address_observed TEXT NOT NULL,
  frame_type TEXT NOT NULL,
  ssid TEXT,
  rssi INTEGER,
  channel INTEGER,
  is_randomized_mac INTEGER NOT NULL,
  information_elements_json TEXT NOT NULL,
  hostname TEXT NOT NULL,
  ingested_at_utc TEXT NOT NULL,
  PRIMARY KEY (scanner_id, observed_at_utc, address_observed)
);
CREATE INDEX IF NOT EXISTS idx_wifi_obs_address_time
  ON wifi_address_observations(address_observed, observed_at_utc);
CREATE INDEX IF NOT EXISTS idx_wifi_obs_scanner_time
  ON wifi_address_observations(scanner_id, observed_at_utc);
```

### `information_elements_json` (the fingerprint)

Captured from 802.11 tagged parameters — this is what survives MAC randomization. Stored as a
compact JSON object, e.g.:

```json
{
  "tag_order": [0, 1, 50, 45, 127, 221],
  "supported_rates": ["1", "2", "5.5", "11"],
  "ht_capabilities": "...",
  "ext_capabilities": "...",
  "vendor_specific": ["0017f2", "001018"]
}
```

`tag_order` (the ordered list of element IDs) plus a few key tags is a standard, reasonably
stable device fingerprint. Exact fields can be tuned during implementation; the column is an
opaque JSON blob so the schema does not change as the fingerprint evolves.

### Concurrency note

The BLE observer and the Wi-Fi observer will be **two processes writing the same SQLite
file** (on Pis where Wi-Fi is enabled). Both stores already set `PRAGMA busy_timeout = 5000`;
this plan additionally enables **WAL mode** (`PRAGMA journal_mode = WAL`) in both stores so
concurrent writers don't block on a single writer lock. Write volume is modest because each
writer is rate-limited (see §4).

### Absence on Pis without the adapter

On a Pi that doesn't run the Wi-Fi observer, the `wifi_address_observations` table is **never
created** — only the observer's `store.initialize()` creates it. So the table is genuinely
absent from those Pis' snapshots, and the rest of the pipeline must tolerate that:

- **Hub ingest** must check `sqlite_master` for `wifi_address_observations` in the attached
  snapshot and **skip** the wifi `INSERT … SELECT` when it's missing (a Pi without the adapter
  must not break `home-security-hub-fetch`). The hub archive still defines the table so that
  Pis *with* the adapter ingest into a consistent schema.
- **Snapshot manifest stats** must report zero / omit the wifi counts when the table is absent.
- **Prune** must `DELETE` from the wifi table only if it exists.

---

## 3. MAC randomization — expectation setting

Modern phones (iOS 14+, Android 10+) randomize their MAC in probe requests when not
associated. So:

- Expect many transient, locally-administered MACs (`is_randomized_mac = 1`).
- Stable MACs come mainly from **associated / IoT** devices (TVs, plugs, cameras, your own
  connected gear) and from APs.
- "Presence/vendor census" and "fingerprint-based" analysis are robust; "track one specific
  phone for weeks by MAC" is not. The `is_randomized_mac` flag and the IE fingerprint exist to
  let the analysis layer handle this honestly rather than pretending random MACs are stable.

---

## 4. Capture mechanism on the Pi

New module `pi/src/home_security_pi/wifi_observe.py`, structured to mirror `ble_observe.py`
(same separation: normalize → build observation → rate-limit → store):

1. **Interface setup** (done privileged in `ExecStartPre`, see §6):
   `nmcli device set wlan1 managed no` → `ip link set wlan1 down` →
   `iw dev wlan1 set type monitor` → `ip link set wlan1 up`.
2. **Channel hopping:** a background loop steps `wlan1` across **2.4 GHz channels 1–13**,
   dwelling ~250 ms each (`iw dev wlan1 set channel N`, or `pyroute2` to avoid shelling out).
   Receive-only, so all channels are passive. (5 GHz is intentionally out of scope — see §10;
   most phones/IoT probe on 2.4 GHz, and fewer channels means better dwell per channel.)
3. **Sniff:** `scapy.sniff(iface="wlan1", prn=on_frame, store=False, monitor=True)`.
4. **`on_frame`:** classify frame type, extract transmitter MAC, RSSI (`pkt.dBm_AntSignal`),
   current channel, SSID and tagged IEs (`Dot11Elt` walk) → build a `WifiObservation`.
5. **Rate-limit + store:** reuse the `ObservationLimiter` pattern (default one row per MAC per
   60 s) → `WifiObservationStore.insert()`.
6. **Lifecycle:** `SIGINT`/`SIGTERM` stop the sniff and channel hopper. `wlan1` is **left in
   monitor mode** when the service stops (it's dedicated to sniffing and never used for
   connectivity — see §10), so no teardown/restore step is needed.

Record dataclass (parallels `AddressObservation`):

```python
@dataclass(frozen=True)
class WifiObservation:
    observed_at_utc: datetime
    source: str            # "wifi"
    scanner: str           # "scapy"
    address_observed: str  # transmitter MAC
    frame_type: str
    ssid: str | None
    rssi: int | None
    channel: int | None
    is_randomized_mac: bool
    information_elements: dict[str, object]
    hostname: str
```

Dependency: add **`scapy`** to `pi/pyproject.toml`. (Today the only dep is `bleak`.)

---

## 5. File-by-file change list

### Pi (`pi/`)

- **`src/home_security_pi/wifi_observe.py`** (new) — capture + normalize + store + `main()`,
  args `--database`, `--interface wlan1`, `--min-interval-seconds 60`, `--channels`.
- **`src/home_security_pi/wifi_store.py`** *(or inline in wifi_observe)* — `WifiObservationStore`
  (create table, WAL, insert, `latest_observed_at`) mirroring `BLEObservationStore`.
- **`pyproject.toml`** — add `scapy` dep; add script
  `home-security-pi-wifi-observe = "home_security_pi.wifi_observe:main"`.
- **`snapshot.py`** — extend the manifest stats to also count `wifi_address_observations`
  (the data copy itself is already covered by `src.backup`). Manifest gains wifi row
  count / min / max alongside the BLE ones — **guarded** so it reports zero / omits them when
  the table is absent (Pis without the adapter).
- **`prune.py`** — also `DELETE FROM wifi_address_observations` under the same time floor,
  **only if the table exists**.
- **`systemd/home-security-wifi-monitor.service.in`** (new) — see §6.
- **`sbin/home-security-apply-systemd`** — render + `systemctl enable/restart` the new unit and
  install the NetworkManager `unmanaged-devices` drop-in **only when Wi-Fi is enabled for this
  Pi**; when it's not, ensure the unit is disabled/removed and the drop-in absent (idempotent
  cleanup, mirroring the existing legacy-unit cleanup). See §6 for the per-Pi toggle.

### Hub (`hub/`)

- **`src/home_security_hub/archive.py`** — add the `wifi_address_observations` DDL + a parallel
  `INSERT OR IGNORE … SELECT … FROM src.wifi_address_observations` in `ingest_snapshot`,
  **guarded by a `sqlite_master` check** so snapshots from Pis without the adapter (no wifi
  table) ingest cleanly. Count its rows in `snapshot_ingests` (or extend the ingest result to
  report per-table counts).
- **`src/home_security_hub/manifest.py`** — accept the new wifi stat fields if the manifest
  schema is validated.

### API (`api/`)

- **`src/home_security_api/db.py`** + routers — **separate `/wifi/*` routes** (decision §10):
  new query helpers and a dedicated router (`/wifi/observations`, `/wifi/addresses`, …) over
  `wifi_address_observations`, with its own Wi-Fi-shaped response model. BLE endpoints stay
  exactly as-is. Vendor breakdown for Wi-Fi needs an **OUI** lookup (first 3 MAC octets) — a
  *different* namespace from the BLE `company_identifiers` table (see §7).
- **`tests/conftest.py`** — extend the mirrored schema fixture with the wifi table.

### Tools / docs

- **`tools/deploy-pi`** — restart the wifi unit and read back its table count **only when
  Wi-Fi is enabled for the target Pi** (otherwise the restart would fail on a Pi with no unit).
- **`tools/bootstrap-pi-systemd`** — accept the per-Pi Wi-Fi opt-in (env/flag, §6), write the
  enable marker on the Pi, and add the wifi service to the `/etc/sudoers.d/` restart rules
  (only when enabled) so deploys stay non-interactive.
- **`docs/raspberry-pi.md`** — document the external adapter, monitor-mode setup, the NM
  `unmanaged-devices` drop-in, and the regulatory-domain requirement.

---

## 6. Enablement (per Pi), privileges & systemd

### Per-Pi opt-in

The Wi-Fi monitor is gated by a **per-Pi enable marker**, mirroring the existing `scanner-id`
convention: a state file `~/.local/state/home-security/wifi-monitor-interface` whose contents
name the monitor interface (e.g. `wlan1`). It is written once at bootstrap (from an env flag,
e.g. `HOME_SECURITY_PI_WIFI_INTERFACE=wlan1`) and persists across deploys.

`apply-systemd` reads the marker and:

- **marker present** → render + enable + restart `home-security-wifi-monitor.service`, install
  the NM `unmanaged-devices` drop-in, and substitute the interface name into the unit;
- **marker absent** → ensure the unit is `disable --now`d and removed and the NM drop-in is
  absent (idempotent, mirroring the existing `home-security-ble-startup-scan` cleanup).

So the front-yard Pi (no marker) is completely unaffected: no unit, no `wlan1` handling, no
wifi table — it behaves exactly as it does today. Enabling later is just writing the marker and
redeploying. A safety nicety for the prototype phase: `apply-systemd` can additionally verify
the named interface actually reports `monitor` in `iw phy … info` before enabling, and warn
(not enable) otherwise — so a marker on a Pi whose adapter can't sniff fails loudly instead of
crash-looping.

### Privileges & systemd

Monitor mode + channel hopping need `CAP_NET_RAW` (raw socket sniff) and `CAP_NET_ADMIN`
(set type/channel). Plan: run the main process as the **deploy user** with ambient caps, and
do the one-time privileged interface switch in a root `ExecStartPre` (the `+` prefix runs that
line as root regardless of `User=`).

```ini
[Unit]
Description=Home Security Wi-Fi monitor-mode scanner
After=network.target NetworkManager.service

[Service]
Type=simple
User=@HOME_SECURITY_PI_USER@
WorkingDirectory=@HOME_SECURITY_PI_CODE_DIR@
Environment=PATH=@HOME_SECURITY_PI_HOME@/.local/bin:/usr/local/bin:/usr/sbin:/usr/bin:/bin
# Privileged one-time interface setup (root via '+'):
ExecStartPre=+/usr/bin/nmcli device set @HOME_SECURITY_PI_WIFI_INTERFACE@ managed no
ExecStartPre=+/usr/sbin/iw reg set DK
ExecStartPre=+/usr/sbin/ip link set @HOME_SECURITY_PI_WIFI_INTERFACE@ down
ExecStartPre=+/usr/sbin/iw dev @HOME_SECURITY_PI_WIFI_INTERFACE@ set type monitor
ExecStartPre=+/usr/sbin/ip link set @HOME_SECURITY_PI_WIFI_INTERFACE@ up
# Main process: unprivileged user + just the caps it needs at runtime:
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN
ExecStart=/usr/bin/env uv run --no-dev home-security-pi-wifi-observe \
  --interface @HOME_SECURITY_PI_WIFI_INTERFACE@ \
  --database @HOME_SECURITY_PI_STATE_DIR@/observations.sqlite3 \
  --min-interval-seconds 60
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Persistent NM hand-off (so NM never grabs `wlan1` on boot before the service starts), installed
by `apply-systemd` to `/etc/NetworkManager/conf.d/99-home-security-wifi-monitor.conf`:

```ini
[keyfile]
unmanaged-devices=interface-name:@HOME_SECURITY_PI_WIFI_INTERFACE@
```

Open implementation question: whether ambient `CAP_NET_ADMIN` reliably lets the unprivileged
process retune channels via `iw`/nl80211, or whether channel hopping should also run via a
privileged helper. To be settled during the prototype.

---

## 7. Vendor lookup (OUI) — follow-up

Wi-Fi vendor attribution uses the IEEE **OUI** (first 3 octets of the MAC), a different
registry from the BLE `company_identifiers` company IDs. This needs a new `oui_identifiers`
table and a refresh tool analogous to `tools/home-security-vendors-refresh`. Treated as a
**follow-up** after core capture works; randomized MACs have a locally-administered OUI and
won't resolve to a real vendor anyway (the `is_randomized_mac` flag covers that case).

---

## 8. Testing

Follow AGENTS.md ("add simulated inputs and tests before depending on live radio hardware"):

- `pi/tests/test_wifi_observe.py` — build synthetic frames with Scapy
  (`RadioTap()/Dot11()/Dot11ProbeReq()/Dot11Elt()`), assert normalization → `WifiObservation`
  (MAC, RSSI, SSID, IE fingerprint, randomized-bit detection), and storage/rate-limit behaviour
  using the `AdjustableClock` pattern from `test_ble_observe.py`.
- `hub/tests/test_archive.py` — add wifi snapshot ingest + dedup cases.
- `api/tests/` — endpoint coverage over the wifi table.

No live radio in CI; all tests use synthetic frames / fixture DBs.

---

## 9. Phased delivery

1. **Prototype (throwaway):** a script that sets `wlan1` to monitor mode, hops channels, and
   Scapy-sniffs for a minute on the living-room Pi — confirm we actually capture probe requests
   and can read RSSI/IEs. Validates the open privilege/channel questions before building.
2. **Core capture:** `wifi_observe.py` + `WifiObservationStore` + WAL + tests.
3. **Service & deploy:** systemd unit, NM drop-in, `apply-systemd`, `deploy-pi`, sudoers.
4. **Pipeline:** snapshot stats + hub archive ingest + prune, with tests.
5. **API:** read endpoints + `conftest` schema.
6. **Follow-ups:** OUI vendor table + refresh tool; web frontend surfacing; privacy controls
   (denylist/hashing).

---

## 10. Resolved decisions

- **Channel set:** **2.4 GHz only, channels 1–13**, ~250 ms dwell. 5 GHz is out of scope for
  now (most phones/IoT probe on 2.4 GHz; fewer channels = better per-channel dwell; avoids
  DFS/regulatory complications). Revisit if 5 GHz-only devices turn out to matter.
- **Privacy at rest:** **store MACs and SSIDs raw** — maximum analytical value (exact OUI
  vendor lookup, human-readable identification). Accepted trade-off: this is the most sensitive
  option, so DB/archive files stay private and untracked (see Safety boundary).
- **API surface:** **separate `/wifi/*` routes** with their own response model; BLE endpoints
  unchanged.
- **Radio state on stop:** **leave `wlan1` in monitor mode** — it's dedicated to sniffing and
  never used for connectivity, so no restore/teardown step.

### Still to settle during implementation

- Exact IE fields captured into `information_elements_json` (tuned against real frames in the
  prototype).
- Whether the unprivileged worker can retune channels via ambient `CAP_NET_ADMIN`, or whether
  channel hopping needs a privileged helper (§6).
- Rate-limit interval and whether to rate-limit per `(MAC, frame_type)` vs per `MAC`.
