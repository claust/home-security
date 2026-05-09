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
  sudo -n /usr/bin/install -m 0755 \"\$PWD/sbin/home-security-apply-systemd\" /usr/local/sbin/home-security-apply-systemd
  sudo -n /usr/local/sbin/home-security-apply-systemd
  uv run home-security-pi-verify --output run-results/latest.json
  sudo -n /usr/bin/systemctl restart home-security-bluetooth-power.service
  sudo -n /usr/bin/systemctl restart home-security-ble-startup-scan.service
  printf '\nSaved result on Pi: ~/%s\n' '$REMOTE_DIR/run-results/latest.json'
  printf '\nVerification result read back from Pi:\n'
  cat run-results/latest.json
  printf '\nBluetooth power service status:\n'
  systemctl --no-pager --full status home-security-bluetooth-power.service || true
  printf '\nBLE startup scan service status:\n'
  systemctl --no-pager --full status home-security-ble-startup-scan.service || true
  printf '\nBLE startup scan result read back from Pi:\n'
  cat \"\$HOME/.local/state/home-security/ble-startup.json\"
"
