#!/usr/bin/env sh
set -eu

HOST="${HOME_SECURITY_PI_HOST:-home-security-pi}"
REMOTE_DIR="${HOME_SECURITY_PI_REMOTE_DIR:-home-security-pi}"
LOCAL_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PI_DIR="$LOCAL_DIR/pi"

if [ -z "${HOME_SECURITY_SCANNER_ID:-}" ]; then
  echo "HOME_SECURITY_SCANNER_ID must be set (e.g. pi-livingroom)." >&2
  exit 1
fi

case "$HOME_SECURITY_SCANNER_ID" in
  [A-Za-z0-9]*)
    ;;
  *)
    echo "HOME_SECURITY_SCANNER_ID must start with an alphanumeric." >&2
    exit 1
    ;;
esac

if ! printf '%s' "$HOME_SECURITY_SCANNER_ID" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9.-]*$'; then
  echo "HOME_SECURITY_SCANNER_ID may only contain letters, digits, dots and dashes." >&2
  exit 1
fi

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
  SCANNER_ID_FILE=\"\$HOME/.local/state/home-security/scanner-id\"
  SCANNER_ID_NEW=\"$HOME_SECURITY_SCANNER_ID\"

  mkdir -p \"\$(dirname \"\$SCANNER_ID_FILE\")\"
  if [ -f \"\$SCANNER_ID_FILE\" ]; then
    SCANNER_ID_OLD=\"\$(cat \"\$SCANNER_ID_FILE\")\"
    if [ \"\$SCANNER_ID_OLD\" != \"\$SCANNER_ID_NEW\" ]; then
      printf 'Refusing to overwrite scanner_id %s with %s at %s. Remove the file manually if this is intentional.\n' \"\$SCANNER_ID_OLD\" \"\$SCANNER_ID_NEW\" \"\$SCANNER_ID_FILE\" >&2
      exit 1
    fi
  else
    printf '%s\n' \"\$SCANNER_ID_NEW\" > \"\$SCANNER_ID_FILE\"
    chmod 0644 \"\$SCANNER_ID_FILE\"
  fi

  cat > \"\$SUDOERS_TMP\" <<EOF
\$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/install -m 0755 \$CODE_DIR/sbin/home-security-apply-systemd /usr/local/sbin/home-security-apply-systemd
\$DEPLOY_USER ALL=(root) NOPASSWD: /usr/local/sbin/home-security-apply-systemd
\$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart home-security-bluetooth-power.service
\$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart home-security-ble-observer.service
EOF

  sudo visudo -cf \"\$SUDOERS_TMP\"
  sudo install -m 0440 \"\$SUDOERS_TMP\" /etc/sudoers.d/home-security-deploy
  rm -f \"\$SUDOERS_TMP\"

  sudo -n /usr/bin/install -m 0755 \"\$CODE_DIR/sbin/home-security-apply-systemd\" /usr/local/sbin/home-security-apply-systemd
  cd \"\$CODE_DIR\"
  sudo -n /usr/local/sbin/home-security-apply-systemd
  sudo -n /usr/bin/systemctl restart home-security-bluetooth-power.service
  sudo -n /usr/bin/systemctl restart home-security-ble-observer.service

  printf 'Bootstrap complete. Future ./tools/deploy-pi.sh runs should be non-interactive.\n'
"
