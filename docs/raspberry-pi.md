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
that let later deploys restart services without a password.

A successful deploy ends with the verification JSON (which now includes
`scanner_id`), the bluetooth-power and BLE observer service status, and a row
count from `~/.local/state/home-security/observations.sqlite3`.

## Adding A New Monitor Pi

1. Pick a unique, stable `scanner_id` for the Pi
   (e.g. `pi-livingroom`, `pi-garage`).
2. Add a `home-security-pi-<scanner_id>` SSH alias and copy the project key
   to it.
3. Install `uv` on the Pi (see above).
4. Run bootstrap once with both `HOME_SECURITY_PI_HOST` and
   `HOME_SECURITY_SCANNER_ID` set. This writes the scanner identity file on
   the Pi.
5. Run deploy with `HOME_SECURITY_PI_HOST` set to the new alias; confirm the
   verification JSON shows the expected `scanner_id` and observer status reads
   back cleanly.
6. From the hub, pull a first snapshot to confirm end-to-end:

   ```sh
   cd hub && uv run home-security-hub-fetch --host home-security-pi-<scanner_id>
   ```

   The archive at `~/.local/state/home-security/archive.sqlite3` should now
   contain a row group keyed on the new `scanner_id`.
7. Record the alias → scanner_id → hostname mapping in `LOCAL-PIS.md`.

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
