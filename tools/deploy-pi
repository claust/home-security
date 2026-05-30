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
  uv sync --frozen --no-dev
  sudo -n /usr/bin/install -m 0755 \"\$PWD/sbin/home-security-apply-systemd\" /usr/local/sbin/home-security-apply-systemd
  sudo -n /usr/local/sbin/home-security-apply-systemd
  uv run --no-dev home-security-pi-verify --output run-results/latest.json
  sudo -n /usr/bin/systemctl restart home-security-bluetooth-power.service
  printf '\nSaved result on Pi: ~/%s\n' '$REMOTE_DIR/run-results/latest.json'
  printf '\nVerification result read back from Pi:\n'
  cat run-results/latest.json
  printf '\nBluetooth power service status:\n'
  systemctl --no-pager --full status home-security-bluetooth-power.service || true
  printf '\nBLE observer service status:\n'
  systemctl --no-pager --full status home-security-ble-observer.service || true
  printf '\nBLE observer database tables:\n'
  python - <<'PY'
import sqlite3
from pathlib import Path
database = Path.home() / '.local/state/home-security/observations.sqlite3'
print(database)
if not database.exists():
    raise SystemExit('database does not exist')
with sqlite3.connect(database) as connection:
    rows = connection.execute(
        \"\"\"
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        \"\"\"
    ).fetchall()
    print([row[0] for row in rows])
    count = connection.execute(
        'SELECT COUNT(*) FROM ble_address_observations'
    ).fetchone()[0]
    print(f'ble_address_observations_count={count}')
PY
"
