# Hub Software

Python package for the hub: pulls observation snapshots from monitor Pis and consolidates them into a local archive.

## Commands

```sh
uv run home-security-hub-fetch
uv run home-security-hub-fetch --host home-security-pi-livingroom
```

`home-security-hub-fetch` SSHes to a monitor Pi, invokes `home-security-pi-snapshot` remotely, copies the snapshot and manifest pair to the local inbox, verifies the sha256, and ingests the rows into the archive. After a successful ingest it asks the Pi to prune observations covered by the snapshot (subject to the Pi's `--keep-last-days` safety floor, default 14). Pass `--no-prune` to skip the prune step.

## Defaults

- Archive: `~/.local/state/home-security/archive.sqlite3`
- Inbox: `~/.local/state/home-security/inbox/<scanner_id>/`
- Target host: SSH alias `home-security-pi` (override with `--host` or `HOME_SECURITY_PI_HOST`)

## Idempotent ingest

The archive de-duplicates on the natural key `(scanner_id, observed_at_utc, address_observed)` with `INSERT OR IGNORE`. Running the fetch repeatedly, or pulling the same scanner via two transports (LAN and drive-by), is therefore safe.
