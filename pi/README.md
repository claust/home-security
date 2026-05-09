# Raspberry Pi Software

This directory contains the Python software intended to run on the Raspberry Pi monitoring node.

The first milestone is intentionally small: deploy this package to the Pi, run a verification command there, and read back the result. The command writes only basic host/runtime metadata and does not collect device observations.

## Local Commands

```sh
uv run home-security-pi-verify
```

## Deployment

From the repository root:

```sh
./tools/deploy-pi.sh
```

The deploy script syncs this directory to `~/home-security-pi` on `home-security-pi`, runs `uv sync --frozen`, executes the verification command, and prints the result JSON.

The remote deploy directory is code-only. Runtime state, config, logs, observations, captures, and caches should live outside it.
