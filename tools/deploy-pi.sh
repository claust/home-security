#!/usr/bin/env sh
set -eu

HOST="${HOME_SECURITY_PI_HOST:-home-security-pi}"
REMOTE_DIR="${HOME_SECURITY_PI_REMOTE_DIR:-home-security-pi}"
LOCAL_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PI_DIR="$LOCAL_DIR/pi"

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required locally." >&2
  exit 1
fi

rsync -az --delete \
  --exclude '.venv/' \
  --exclude 'run-results/' \
  "$PI_DIR/" "$HOST:$REMOTE_DIR/"

ssh "$HOST" "set -eu
  export PATH=\"\$HOME/.local/bin:\$PATH\"
  cd '$REMOTE_DIR'
  if ! command -v uv >/dev/null 2>&1; then
    echo 'uv is not installed on the Raspberry Pi. Install uv first, then rerun this deploy script.' >&2
    exit 2
  fi
  uv sync --frozen
  uv run home-security-pi-verify --output run-results/latest.json
  printf '\nSaved result on Pi: ~/%s\n' '$REMOTE_DIR/run-results/latest.json'
  printf '\nResult read back from Pi:\n'
  cat run-results/latest.json
"
