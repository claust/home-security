# Repository Guidelines

## Start Here

Read `README.md` first. It describes the current Pi deployment, service stack, runtime output locations, and safety boundaries.

## Current Structure

- `pi/` contains Raspberry Pi Python code plus systemd assets.
- `pi/pyproject.toml` and `pi/uv.lock` define the locked Pi package.
- `pi/systemd/` contains service templates.
- `pi/sbin/home-security-apply-systemd` installs/updates the services on the Pi.
- `tools/bootstrap-pi-systemd` is the one-time interactive Pi bootstrap.
- `tools/deploy-pi` is the normal non-interactive deploy.
- `docs/raspberry-pi.md` documents SSH alias and deploy directory conventions.

Keep the project small. Prefer focused, testable Python modules over frameworks.

## Safety Boundaries

This project is only for defensive, consent-oriented monitoring of the user's own home environment.

Do not implement unauthorized tracking, credential capture, intrusion, evasion, jamming, spoofing, deauthentication, pairing attacks, or surveillance outside the user's property and devices.

Treat MAC addresses, device names, RSSI histories, timestamps, packet captures, private keys, observation logs, and derived fingerprints as sensitive. Do not check in real household identifiers or captures.

## Engineering Preferences

- Use `uv` for Pi Python dependency management.
- Keep collection, normalization, fingerprinting, storage, and presentation separate.
- Prefer structured records for observations and fingerprints.
- Include source, timestamp, signal strength, confidence, and uncertainty where applicable.
- Make scanner implementations replaceable.
- Add simulated inputs and tests before depending on live radio hardware.

## Workflow

- Use `rg` for searches.
- Check `git status --short` before editing.
- Do not overwrite unrelated user changes.
- Run tests for changed Python code.
- Run `./tools/deploy-pi` when changing Pi-deployed code or services, then verify the result read back from the Pi.
- Keep Pi state, config, logs, observations, and caches outside `~/home-security-pi`.
- Document any new hardware permission, systemd service, dependency, database, or storage behavior.
