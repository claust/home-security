# Raspberry Pi Setup

Each monitor Pi runs identical software. They are distinguished by `scanner_id`,
which defaults to the Pi's hostname. Pick a stable, distinct hostname per Pi
(e.g. `pi4`, `pi02w`) before bootstrap.

Keep real host addresses, account names, private keys, and household-specific
details outside this repository. Local notes belong in the gitignored
`LOCAL-PIS.md`.

## SSH Aliases

Use one alias per Pi, named `home-security-pi<hostname>`, in `~/.ssh/config`:

```sshconfig
Host home-security-pi home-security-pi4
  HostName <pi4-lan-host-or-ip>
  User <pi-user>
  IdentityFile ~/.ssh/<project-pi-key>
  IdentitiesOnly yes

Host home-security-pi02w
  HostName <pi02w-lan-host-or-ip>
  User <pi-user>
  IdentityFile ~/.ssh/<project-pi-key>
  IdentitiesOnly yes
```

The bare `home-security-pi` alias is the default target for `tools/`. Aliasing
it to a specific Pi (above, `pi4`) gives the tools a no-flag default while
letting per-host aliases address either Pi explicitly. Override per invocation
with `HOME_SECURITY_PI_HOST=home-security-pi02w` (see below).

Install the public key on each Pi once:

```sh
ssh-copy-id -i ~/.ssh/<project-pi-key>.pub home-security-pi02w
```

After key-based login works, prefer disabling password SSH login on the Pi.

## Per-Pi Prerequisites

Before running `bootstrap-pi-systemd.sh` against a Pi, that Pi must have:

1. The project SSH key authorized for the deploy user.
2. The deploy user able to `sudo` (a password prompt is expected during
   bootstrap; subsequent deploys are non-interactive).
3. `uv` installed at `~/.local/bin/uv`. Install with:

   ```sh
   ssh home-security-pi<hostname> 'curl -LsSf https://astral.sh/uv/install.sh | sh'
   ```

   The deploy script fails fast with a clear message if `uv` is missing.

## Bootstrap And Deploy

From the repository root, target the desired Pi via `HOME_SECURITY_PI_HOST`:

```sh
# One-time, interactive (sudo password prompt for the visudo entry):
HOME_SECURITY_PI_HOST=home-security-pi02w ./tools/bootstrap-pi-systemd.sh

# Normal, non-interactive deploys:
HOME_SECURITY_PI_HOST=home-security-pi02w ./tools/deploy-pi.sh
```

If `HOME_SECURITY_PI_HOST` is unset both scripts target `home-security-pi`.

Bootstrap installs the narrow `/etc/sudoers.d/home-security-deploy` rules that
let later deploys restart services without a password.

A successful deploy ends with the verification JSON, the bluetooth-power and
BLE observer service status, and a row count from
`~/.local/state/home-security/observations.sqlite3`.

## Adding A New Monitor Pi

1. Pick a unique, stable hostname for the Pi (this becomes its `scanner_id`).
2. Add a `home-security-pi<hostname>` SSH alias and copy the project key to it.
3. Install `uv` on the Pi (see above).
4. Run bootstrap once with `HOME_SECURITY_PI_HOST` set to the new alias.
5. Run deploy with the same `HOME_SECURITY_PI_HOST` value; confirm the
   verification JSON and observer status read back cleanly.
6. From the hub, pull a first snapshot to confirm end-to-end:

   ```sh
   cd hub && uv run home-security-hub-fetch --host home-security-pi<hostname>
   ```

   The archive at `~/.local/state/home-security/archive.sqlite3` should now
   contain a row group keyed on the new `scanner_id`.

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
  snapshots, archive, inbox)
- `/var/lib/home-security/` only if a future system service requires it
