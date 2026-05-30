# Raspberry Pi Setup

Each monitor Pi runs identical software. They are distinguished by `scanner_id`,
a short stable slug written once at bootstrap to
`~/.local/state/home-security/scanner-id` on the Pi. The hostname is
informational only — renaming the Pi later does not change its scanner identity.

Pick a `scanner_id` that is short, descriptive, and unlikely to change
(e.g. `pi-livingroom`, `pi-garage`). It must match `[A-Za-z0-9][A-Za-z0-9.-]*`.

Keep real host addresses, account names, private keys, and household-specific
details outside this repository. Local notes — including the
alias → scanner_id → hostname mapping — belong in the gitignored
`LOCAL-PIS.md`.

## SSH Aliases

Use one alias per Pi, named `home-security-<scanner_id>`, in `~/.ssh/config`:

```sshconfig
Host home-security-pi home-security-pi-livingroom
  HostName <livingroom-pi-lan-host-or-ip>
  User <pi-user>
  IdentityFile ~/.ssh/<project-pi-key>
  IdentitiesOnly yes

Host home-security-pi-garage
  HostName <garage-pi-lan-host-or-ip>
  User <pi-user>
  IdentityFile ~/.ssh/<project-pi-key>
  IdentitiesOnly yes
```

The bare `home-security-pi` alias is the default target for `tools/`. Aliasing
it to a specific Pi (above, `pi-livingroom`) gives the tools a no-flag default
while letting per-host aliases address either Pi explicitly. Override per
invocation with `HOME_SECURITY_PI_HOST=home-security-pi-garage` (see below).

The alias name is independent of the Pi's OS hostname; it just needs to be a
unique label in your local SSH config. Aligning it with `scanner_id` keeps the
mental model simple.

Install the public key on each Pi once:

```sh
ssh-copy-id -i ~/.ssh/<project-pi-key>.pub home-security-pi-garage
```

After key-based login works, prefer disabling password SSH login on the Pi.

## Per-Pi Prerequisites

Before running `bootstrap-pi-systemd` against a Pi, that Pi must have:

1. The project SSH key authorized for the deploy user.
2. The deploy user able to `sudo` (a password prompt is expected during
   bootstrap; subsequent deploys are non-interactive).
3. `uv` installed at `~/.local/bin/uv`. Install with:

   ```sh
   ssh home-security-pi-<scanner_id> 'curl -LsSf https://astral.sh/uv/install.sh | sh'
   ```

   The deploy script fails fast with a clear message if `uv` is missing.

## Bootstrap And Deploy

From the repository root, target the desired Pi via `HOME_SECURITY_PI_HOST` and
its identity via `HOME_SECURITY_SCANNER_ID`:

```sh
# One-time, interactive (sudo password prompt for the visudo entry).
# HOME_SECURITY_SCANNER_ID is required and gets written to
# ~/.local/state/home-security/scanner-id on the Pi:
HOME_SECURITY_PI_HOST=home-security-pi-garage \
  HOME_SECURITY_SCANNER_ID=pi-garage \
  ./tools/bootstrap-pi-systemd

# Normal, non-interactive deploys (no scanner_id needed — the Pi already has it):
HOME_SECURITY_PI_HOST=home-security-pi-garage ./tools/deploy-pi
```

If `HOME_SECURITY_PI_HOST` is unset both scripts target `home-security-pi`.

Bootstrap refuses to overwrite an existing `scanner-id` file with a different
value. To re-assign a Pi, delete
`~/.local/state/home-security/scanner-id` on the Pi first, then re-bootstrap.

Bootstrap also installs the narrow `/etc/sudoers.d/home-security-deploy` rules
that let later deploys restart services and gracefully power off the Pi
without a password.

A successful deploy ends with the verification JSON (which now includes
`scanner_id`), the bluetooth-power and BLE observer service status, and a row
count from `~/.local/state/home-security/observations.sqlite3`.

## Wi-Fi Monitor (Optional, Per-Pi)

Some Pis have a monitor-capable external USB Wi-Fi adapter; those can run a
passive 802.11 scanner alongside the BLE observer. This is **receive-only**
monitoring of your own environment (see `AGENTS.md`): it never associates,
injects, deauths, or transmits. See `docs/wifi-monitor-scanner.md` for the full
design.

The monitor is **opt-in per Pi**, gated by a marker file
`~/.local/state/home-security/wifi-monitor-interface` whose contents name the
monitor interface (e.g. `wlan1`). Enable it by passing the interface at
bootstrap:

```sh
HOME_SECURITY_PI_HOST=home-security-pi-livingroom \
  HOME_SECURITY_SCANNER_ID=pi-livingroom \
  HOME_SECURITY_PI_WIFI_INTERFACE=wlan1 \
  ./tools/bootstrap-pi-systemd
```

A Pi without the marker is completely unaffected: no `home-security-wifi-monitor`
unit, no `wlan1` handling, no `wifi_address_observations` table — it deploys,
snapshots, prunes, and ingests exactly as a BLE-only Pi. Enabling later is just
writing the marker (re-bootstrap with the env var, or
`echo wlan1 > ~/.local/state/home-security/wifi-monitor-interface`) and
redeploying.

### Hardware prerequisites

- A **dedicated** external adapter whose driver supports monitor mode
  (`iw phy <phy> info` lists `* monitor`). The living-room Pi's MediaTek
  MT76x0 (`wlan1`, driver `mt76x0u`) qualifies; the built-in Broadcom radio
  does not. The built-in radio (`wlan0`) keeps the Pi online over normal Wi-Fi
  — the monitor adapter is given over entirely to sniffing and is left in
  monitor mode even when the service stops.
- `iw` installed on the Pi (`/usr/sbin/iw`).

### What `apply-systemd` does when enabled

- Renders and enables `home-security-wifi-monitor.service`, substituting the
  interface name from the marker.
- Installs a NetworkManager drop-in at
  `/etc/NetworkManager/conf.d/99-home-security-wifi-monitor.conf` marking the
  interface `unmanaged`, so NM never grabs it on boot.
- The unit's privileged `ExecStartPre` (root) runs
  `sbin/home-security-wifi-monitor-setup`, which hands the interface off from
  NetworkManager, sets the regulatory domain (`iw reg set DK` by default;
  override with `HOME_SECURITY_PI_WIFI_REG_DOMAIN`), and switches the adapter
  into monitor mode. The main process then runs **unprivileged** with only
  `CAP_NET_RAW` (open the monitor socket) and `CAP_NET_ADMIN` (hop channels).

The scanner passively hops 2.4 GHz channels 1–13 and records one row per MAC
per minute into the same `observations.sqlite3` (WAL mode lets the BLE and
Wi-Fi observers write the one file concurrently). A successful deploy on an
enabled Pi prints the Wi-Fi monitor service status and a
`wifi_address_observations` row count alongside the BLE one.

## Powering Down A Pi

Always shut down gracefully before pulling power — the SD card filesystem and
the live `observations.sqlite3` database can both be corrupted by mid-write
power loss. After bootstrap, the deploy user can shut down without a password:

```sh
ssh home-security-pi-<scanner_id> 'sudo -n /usr/bin/systemctl poweroff'
```

Wait for the green ACT LED to stop blinking before unplugging.

## Adding A New Monitor Pi

End-to-end checklist for onboarding a fresh Pi from a blank SD card. The
example below uses `pi-frontyard` as the chosen `scanner_id`; substitute your
own.

1. **Pick a `scanner_id`** — short, stable slug matching
   `[A-Za-z0-9][A-Za-z0-9.-]*` (e.g. `pi-frontyard`, `pi-garage`).

2. **Flash the SD card with Raspberry Pi Imager.** In the imager's settings
   pane, set:
   - Hostname: `<scanner_id>` (matching keeps things simple).
   - Username and password for the deploy user.
   - Enable SSH with public-key auth and paste the project key
     (`~/.ssh/home_security_pi_ed25519.pub`) so the Pi accepts your key on
     first boot. If you skip this, you'll need `ssh-copy-id` later (see
     step 5).
   - Wi-Fi credentials if the Pi will be wireless.

3. **Boot the Pi and find it on the LAN.** Pi OS publishes mDNS, so the Pi
   appears as `<hostname>.local`:

   ```sh
   ping <scanner_id>.local
   ```

   If the Pi reuses an IP that previously hosted a different OS (re-imaged
   hardware), prune the stale host key first:

   ```sh
   ssh-keygen -R <ip-address>
   ssh-keygen -R <scanner_id>.local
   ```

4. **Add an SSH alias.** Append to `~/.ssh/config`:

   ```sshconfig
   Host home-security-pi home-security-pi-<scanner_id>
     HostName <ip-address-or-mdns-name>
     User <pi-user>
     IdentityFile ~/.ssh/home_security_pi_ed25519
     IdentitiesOnly yes
   ```

   Listing both names on one `Host` line lets the bare `home-security-pi`
   default target this Pi while the explicit alias still works. If you have
   more than one monitor, only the most relevant Pi should share the bare
   default — give the others a standalone block.

5. **Authorize the key** (skip if you preinstalled the public key in
   step 2):

   ```sh
   ssh-copy-id -i ~/.ssh/home_security_pi_ed25519.pub <pi-user>@<ip-or-mdns>
   ```

6. **Install `uv` on the Pi** over SSH (no Pi-side password needed):

   ```sh
   ssh home-security-pi-<scanner_id> 'curl -LsSf https://astral.sh/uv/install.sh | sh'
   ```

7. **Bootstrap.** This writes `~/.local/state/home-security/scanner-id` on
   the Pi and installs the sudoers rules. Expect one sudo password prompt:

   ```sh
   HOME_SECURITY_PI_HOST=home-security-pi-<scanner_id> \
     HOME_SECURITY_SCANNER_ID=<scanner_id> \
     ./tools/bootstrap-pi-systemd
   ```

8. **Deploy.** Confirms the services are healthy and verification JSON shows
   the expected `scanner_id`:

   ```sh
   HOME_SECURITY_PI_HOST=home-security-pi-<scanner_id> ./tools/deploy-pi
   ```

9. **First snapshot from the hub** to confirm end-to-end:

   ```sh
   cd hub && uv run home-security-hub-fetch --host home-security-pi-<scanner_id>
   ```

   The archive at `~/.local/state/home-security/archive.sqlite3` should now
   contain a row group keyed on the new `scanner_id`.

10. **Record the mapping** (alias → scanner_id → hostname → IP) in the
    gitignored `LOCAL-PIS.md`.

## Deploy Directory

`tools/deploy-pi` syncs the local `pi/` directory to:

```text
~/home-security-pi
```

This remote directory is code-only. Deployment uses `rsync --delete`, so do not
store durable state, local config, logs, observations, captures, calibration
data, or caches there.

Use separate locations for runtime data:

- `~/.config/home-security/` for user config
- `~/.local/state/home-security/` for user-level state (observations,
  snapshots, archive, inbox, and the per-Pi `scanner-id` file)
- `/var/lib/home-security/` only if a future system service requires it
