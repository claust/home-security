# home-security

Local-first home security tooling for understanding electronic devices observed around the user's own home.

The project is defensive and consent-oriented. It uses approved local interfaces, currently the Raspberry Pi Bluetooth adapter, to passively observe nearby signals and write local structured results.

## Architecture

Three roles, separated so each can evolve independently:

- **Monitor Pi** — fixed location, continuous radio observation, writes to local SQLite. Identical software across all monitors; per-host differences (e.g., `scanner_id`) live in config. The monitor never reaches out and is stateless about delivery; it just snapshots a requested window when asked.
- **Fetcher** — pulls snapshots from monitor Pis. Two flavors produce the same artifact:
  - **Fetcher Hub** (Mac Mini, indoors, on home LAN): pulls LAN-reachable monitors directly over SSH/Wi-Fi.
  - **Drive-by Fetcher** (laptop): pulls BT-only monitors over SSH/Bluetooth PAN, queues snapshots locally, and later delivers them to the Hub.
- **Aggregator** — runs on the Fetcher Hub. Owns the merged archive, de-duplicates on ingest, and is the single source of truth for later analysis and fingerprinting.

### Retrieval flow

Both transports converge on one ingest path:

```text
LAN monitor ──(SSH/Wi-Fi)─────────────────────┐
                                              ├─► Hub inbox/ → ingest → archive.sqlite3
BT-only monitor ─(SSH/BT-PAN)─► laptop outbox/ ┘  (via rsync to Hub)
```

Each retrieval produces the same pair of files:

- `<scanner_id>__<snapshot_taken_at>.sqlite3` — SQLite backup of the monitor's observation DB.
- `<scanner_id>__<snapshot_taken_at>.json` — manifest carrying `scanner_id`, `hostname`, `snapshot_taken_at`, row count, observed-at-utc min/max, sha256, and Pi git SHA.

### Idempotent ingest

The aggregator de-duplicates on the natural key `(scanner_id, observed_at_utc, address_observed)` with `INSERT OR IGNORE`. Overlapping retrieval of the same monitor (e.g., a drive-by followed shortly by a LAN pull) is therefore safe and produces no duplicate rows.

### Path conventions

Same XDG-style layout on every machine:

| Role | Path |
| --- | --- |
| Monitor Pi: live observations | `~/.local/state/home-security/observations.sqlite3` |
| Fetcher Hub: aggregated archive | `~/.local/state/home-security/archive.sqlite3` |
| Fetcher Hub: incoming snapshots | `~/.local/state/home-security/inbox/<scanner_id>/` |
| Drive-by Fetcher: queued snapshots | `~/.local/state/home-security/outbox/<scanner_id>/` |

### Build order

1. LAN-direct fetch from the existing monitor Pi into the Hub inbox, then ingest into `archive.sqlite3`. Proves the snapshot + manifest + ingest contract end-to-end.
2. Drive-by/BT-PAN courier mode on a laptop, reusing the same snapshot + manifest format and the same Hub-side ingest.
3. Scheduled periodic LAN pulls on the Hub (systemd timer or launchd). Drive-by stays manual.

## Current Status

The working path is a Raspberry Pi monitoring node:

- Pi code lives in `pi/` and is managed with `uv`.
- `home-security-pi-verify` writes host/runtime metadata.
- `home-security-pi-ble-scan` passively scans BLE advertisements and writes JSON.
- `home-security-pi-ble-observe` continuously records BLE addresses observed to SQLite.
- systemd keeps a continuous BLE observer running against `~/.local/state/home-security/observations.sqlite3`.
- `tools/deploy-pi.sh` syncs code, installs services, restarts them, and reads back status/results.

## Layout

```text
.
├── docs/raspberry-pi.md
├── pi/
│   ├── sbin/home-security-apply-systemd
│   ├── systemd/
│   ├── pyproject.toml
│   ├── uv.lock
│   └── src/home_security_pi/
└── tools/
    ├── bootstrap-pi-systemd.sh
    └── deploy-pi.sh
```

## Raspberry Pi Deployment

Configure the local SSH alias `home-security-pi`; see `docs/raspberry-pi.md`.

Run once per Pi:

```sh
./tools/bootstrap-pi-systemd.sh
```

Deploy any later code/service changes:

```sh
./tools/deploy-pi.sh
```

Deployment syncs `pi/` to `~/home-security-pi` with `rsync --delete`. That directory is code-only. Runtime state, observations, logs, caches, and config must stay outside it.

Current runtime output:

- verification: `~/home-security-pi/run-results/latest.json`
- continuous BLE observations: `~/.local/state/home-security/observations.sqlite3`

## Development Checks

Install the commit hook once per checkout:

```sh
cd pi
uv run pre-commit install --config ../.pre-commit-config.yaml
```

Run the same checks manually:

```sh
cd pi
uv run pre-commit run --config ../.pre-commit-config.yaml --all-files
```

## Services

- `bluetooth.service`: OS BlueZ service.
- `home-security-bluetooth-power.service`: clears Bluetooth rfkill soft blocks and asks BlueZ to power on the adapter.
- `home-security-ble-observer.service`: continuously records BLE addresses observed with a one-minute minimum interval per address.

The bootstrap script installs narrow sudo permissions so normal deploys can run non-interactively with `sudo -n`.

## Privacy And Safety

Do not check in real household identifiers or captures. Treat MAC addresses, device names, RSSI histories, timestamps, packet captures, observation logs, private keys, and derived fingerprints as sensitive data.

Do not implement unauthorized tracking, credential capture, intrusion, evasion, jamming, spoofing, deauthentication, pairing attacks, or surveillance outside the user's property and devices.

Keep collection, normalization, fingerprinting, storage, and presentation separate. Prefer simulated inputs and tests before relying on live radio hardware.
