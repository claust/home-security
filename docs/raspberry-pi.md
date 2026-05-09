# Raspberry Pi Setup

This project uses a dedicated SSH key and local SSH alias for Raspberry Pi access during development.

Keep real host addresses, account names, private keys, and household-specific details outside this repository. The private key should live in the local user's SSH directory, not in the repo.

## SSH Alias

Use the alias `home-security-pi` for the monitoring Pi. Configure it locally in `~/.ssh/config`:

```sshconfig
Host home-security-pi
  HostName <pi-lan-host-or-ip>
  User <pi-user>
  IdentityFile ~/.ssh/<project-pi-key>
  IdentitiesOnly yes
```

Install the public key on the Pi with:

```sh
ssh-copy-id -i ~/.ssh/<project-pi-key>.pub home-security-pi
```

After key-based login works, prefer disabling password SSH login on the Pi.

## Deploy Directory

`tools/deploy-pi.sh` syncs the local `pi/` directory to:

```text
~/home-security-pi
```

This remote directory is code-only. Deployment uses `rsync --delete`, so do not store durable state, local config, logs, observations, captures, calibration data, or caches there.

Use separate locations for future runtime data, such as:

- `~/.config/home-security/` for user config
- `~/.local/state/home-security/` for user-level state
- `/var/lib/home-security/` if the project later adds a system service
