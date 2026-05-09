# Repository Guidelines

## Start Here

Read `README.md` first. It describes the current project status, repository layout, Raspberry Pi deployment path, and safety boundaries.

## Current Structure

- `pi/` contains Python software intended to run on the Raspberry Pi.
- `pi/pyproject.toml` and `pi/uv.lock` define the Pi package and locked environment.
- `tools/deploy-pi.sh` syncs `pi/` to the `home-security-pi` SSH target, runs `uv sync --frozen`, executes the verification script, and reads back the result.
- The remote deploy directory is code-only because deployment uses `rsync --delete`.
- `docs/raspberry-pi.md` documents the SSH alias pattern and Pi setup notes without real local infrastructure details.

Keep this simple until the project has real monitoring behavior. Prefer small, testable Python modules over a larger framework.

## Safety Boundaries

Keep the project focused on defensive, consent-oriented monitoring of the user's own home environment.

Do not implement features intended for unauthorized tracking, credential capture, intrusion, evasion, jamming, spoofing, deauthentication, pairing attacks, or surveillance outside the user's property and devices.

Treat MAC addresses, device names, RSSI histories, timestamps, packet captures, private keys, observation logs, and derived fingerprints as sensitive data. Do not check in real household identifiers or captures.

## Engineering Preferences

- Use `uv` for Pi Python dependency management.
- Keep collection, normalization, fingerprinting, storage, and presentation concerns separate.
- Prefer structured records for observations and fingerprints.
- Include source, timestamp, signal strength, confidence, and uncertainty where applicable.
- Make scanner implementations replaceable so development can proceed without live Bluetooth or Wi-Fi monitor-mode access.
- Add simulated inputs and tests before depending on live radio hardware.

## Development Workflow

- Use `rg` for repository searches.
- Check `git status --short` before editing.
- Do not overwrite unrelated user changes.
- Run `./tools/deploy-pi.sh` when changing Pi-deployed code and verify the result read back from the Pi.
- Keep Pi state, config, logs, observations, and caches outside the remote code directory.
- Document setup changes when introducing a runtime, dependency manager, service, database, hardware requirement, or OS-specific permission.

## Documentation Notes

When adding modules, include a short README or architecture note if the behavior touches hardware permissions, OS-specific setup, privacy-sensitive data, storage, or fingerprinting logic.

Future agents should be able to tell whether a feature observes devices passively, derives fingerprints, stores data, or presents alerts.
