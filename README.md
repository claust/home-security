# home-security

Local-first home security tooling for understanding electronic devices observed around a home.

The project is defensive and consent-oriented. It will use approved local interfaces, such as Bluetooth and Wi-Fi adapters, to help distinguish expected household devices from new, unusual, or uncertain signals nearby.

## Current Status

This repository is in early setup. The first working path is Raspberry Pi deployment:

- Pi-targeted Python code lives in `pi/`.
- `pi/` is managed with `uv` and locked with `pi/uv.lock`.
- `tools/deploy-pi.sh` syncs `pi/` to the Raspberry Pi code directory, runs `uv sync --frozen`, executes a verification command, and reads the result back.
- The current Pi setup notes are in `docs/raspberry-pi.md`.

The initial deployed command is:

```sh
home-security-pi-verify
```

It writes basic host/runtime metadata to `run-results/latest.json` on the Pi. It does not collect radio observations.

## Repository Layout

```text
.
├── docs/
│   └── raspberry-pi.md
├── pi/
│   ├── pyproject.toml
│   ├── uv.lock
│   └── src/home_security_pi/
└── tools/
    └── deploy-pi.sh
```

## Raspberry Pi Deployment

The local SSH alias `home-security-pi` should point at the monitoring Pi. See `docs/raspberry-pi.md` for the key and SSH config pattern.

Deploy and run the Pi verification script:

```sh
./tools/deploy-pi.sh
```

The deploy target is:

```text
~/home-security-pi
```

This deploy target is code-only. `tools/deploy-pi.sh` uses `rsync --delete`, so future state, config, calibration data, logs, observations, and caches must live outside this directory.

Suggested future locations:

- user config: `~/.config/home-security/`
- user state: `~/.local/state/home-security/`
- service data, if a system service is added later: `/var/lib/home-security/`

Private keys should live outside this repository, for example in the local user's SSH directory. Generated runtime output, virtual environments, uv caches, and local result files are ignored by Git.

## Privacy And Safety

Do not check in real household device identifiers, MAC addresses, device names, RSSI histories, timestamps, packet captures, observation logs, private keys, or derived fingerprints.

This project must not include offensive capabilities such as deauthentication, jamming, spoofing, credential capture, pairing attacks, intrusion attempts, evasion, or attempts to bypass device privacy protections.

Future observation and fingerprinting code should prefer:

- local processing and local storage by default
- conservative data retention
- structured records with source, timestamp, signal strength, confidence, and uncertainty
- simulated inputs and tests before depending on live radio hardware
- replaceable scanner implementations

## Planned Components

Keep these concerns separate as the project grows:

- Collection: BLE, Bluetooth Classic, Wi-Fi, and simulated scanners.
- Normalization: structured observation records.
- Fingerprinting: explainable confidence scoring across repeated observations.
- Storage: local persistence for observations and derived fingerprints.
- Presentation: reports, alerts, or views that make device activity understandable.
