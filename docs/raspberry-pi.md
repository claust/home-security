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

Before running `bootstrap-pi-systemd.sh` against a Pi, that Pi must have:

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
  ./tools/bootstrap-pi-systemd.sh

# Normal, non-interactive deploys (no scanner_id needed — the Pi already has it):
HOME_SECURITY_PI_HOST=home-security-pi-garage ./tools/deploy-pi.sh
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
     ./tools/bootstrap-pi-systemd.sh
   ```

8. **Deploy.** Confirms the services are healthy and verification JSON shows
   the expected `scanner_id`:

   ```sh
   HOME_SECURITY_PI_HOST=home-security-pi-<scanner_id> ./tools/deploy-pi.sh
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

`tools/deploy-pi.sh` syncs the local `pi/` directory to:

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
