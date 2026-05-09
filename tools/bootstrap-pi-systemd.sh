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

ssh -t "$HOST" "set -eu
  CODE_DIR=\"\$HOME/$REMOTE_DIR\"
  DEPLOY_USER=\"\$(id -un)\"
  SUDOERS_TMP=\"\$(mktemp)\"

  cat > \"\$SUDOERS_TMP\" <<EOF
\$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/install -m 0755 \$CODE_DIR/sbin/home-security-apply-systemd /usr/local/sbin/home-security-apply-systemd
\$DEPLOY_USER ALL=(root) NOPASSWD: /usr/local/sbin/home-security-apply-systemd
\$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart home-security-bluetooth-power.service
\$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart home-security-ble-startup-scan.service
EOF

  sudo visudo -cf \"\$SUDOERS_TMP\"
  sudo install -m 0440 \"\$SUDOERS_TMP\" /etc/sudoers.d/home-security-deploy
  rm -f \"\$SUDOERS_TMP\"

  sudo -n /usr/bin/install -m 0755 \"\$CODE_DIR/sbin/home-security-apply-systemd\" /usr/local/sbin/home-security-apply-systemd
  cd \"\$CODE_DIR\"
  sudo -n /usr/local/sbin/home-security-apply-systemd
  sudo -n /usr/bin/systemctl restart home-security-bluetooth-power.service
  sudo -n /usr/bin/systemctl restart home-security-ble-startup-scan.service

  printf 'Bootstrap complete. Future ./tools/deploy-pi.sh runs should be non-interactive.\n'
"
