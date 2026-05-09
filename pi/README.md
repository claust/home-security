# Raspberry Pi Software

Python package and systemd assets for the Raspberry Pi monitoring node.

## Commands

```sh
uv run home-security-pi-verify
uv run home-security-pi-ble-scan --timeout 10
uv run home-security-pi-ble-observe
```

`home-security-pi-ble-scan` passively listens for BLE advertisements. It does not connect, pair, spoof, jam, deauthenticate, or transmit attack traffic.
`home-security-pi-ble-observe` runs continuously and records BLE addresses observed to `~/.local/state/home-security/observations.sqlite3`.

## Services

`systemd/` contains templates installed by `sbin/home-security-apply-systemd`:

- `home-security-bluetooth-power.service`: unblocks Bluetooth with `/usr/sbin/rfkill unblock bluetooth`, then asks `bluetoothctl` to power on the adapter.
- `home-security-ble-observer.service`: continuously records BLE address observations to `~/.local/state/home-security/observations.sqlite3`.

## Deployment

From the repository root:

```sh
./tools/bootstrap-pi-systemd.sh   # once per Pi
./tools/deploy-pi.sh              # normal deploy
```

The remote code directory is `~/home-security-pi` and is managed with `rsync --delete`. Keep runtime state, logs, config, observations, captures, and caches outside it.

Useful Bluetooth checks on the Pi:

```sh
/usr/sbin/rfkill list
bluetoothctl show
systemctl status home-security-bluetooth-power.service
systemctl status home-security-ble-observer.service
```
