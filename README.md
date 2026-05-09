# home-security

Local-first home security tooling for understanding electronic devices observed around the user's own home.

The project is defensive and consent-oriented. It uses approved local interfaces, currently the Raspberry Pi Bluetooth adapter, to passively observe nearby signals and write local structured results.

## Current Status

The working path is a Raspberry Pi monitoring node:

- Pi code lives in `pi/` and is managed with `uv`.
- `home-security-pi-verify` writes host/runtime metadata.
- `home-security-pi-ble-scan` passively scans BLE advertisements and writes JSON.
- systemd runs a boot-time BLE scan into `~/.local/state/home-security/ble-startup.json`.
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
- startup BLE scan: `~/.local/state/home-security/ble-startup.json`

## Services

- `bluetooth.service`: OS BlueZ service.
- `home-security-bluetooth-power.service`: clears Bluetooth rfkill soft blocks and asks BlueZ to power on the adapter.
- `home-security-ble-startup-scan.service`: runs one BLE scan after Bluetooth setup.

The bootstrap script installs narrow sudo permissions so normal deploys can run non-interactively with `sudo -n`.

## Privacy And Safety

Do not check in real household identifiers or captures. Treat MAC addresses, device names, RSSI histories, timestamps, packet captures, observation logs, private keys, and derived fingerprints as sensitive data.

Do not implement unauthorized tracking, credential capture, intrusion, evasion, jamming, spoofing, deauthentication, pairing attacks, or surveillance outside the user's property and devices.

Keep collection, normalization, fingerprinting, storage, and presentation separate. Prefer simulated inputs and tests before relying on live radio hardware.
