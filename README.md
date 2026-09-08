# U-OPTI

Ubuntu Server Optimization and Management Tool

U-OPTI is a lightweight Bash-based tool for managing, optimizing, securing, and maintaining Ubuntu servers through an interactive menu.

## Current Version

**v0.12.0**

## Main Menu

```text
1) Update Server
2) System Optimization
3) Server Security
4) X-UI PRO Management
5) Certificate Management
6) Backup & Restore
7) Update U-OPTI
8) Uninstall U-OPTI
0) Exit
```

## Features

### Server Management

- Update Ubuntu packages with APT
- Display system information
- Manage system time and timezone
- Check and configure NTP synchronization

### Swap Management

- View swap information
- Create swap
- Resize swap
- Disable swap

### BBR Management

- Check BBR status
- Check BBR compatibility
- Load the BBR kernel module
- Enable BBR
- Disable BBR
- Configure TCP qdisc

### Storage Management

- View disk information
- Find large files
- Find large directories
- Clean APT cache

### SSH Management

- Detect the effective SSH port
- Change SSH port safely
- Validate SSH configuration before applying changes
- Verify the new SSH listener
- Support systemd SSH socket activation
- Back up SSH configuration before changes
- Automatic rollback if SSH configuration, restart, or final verification fails
- Protect against invalid or conflicting ports
- Detect active UFW before changing the SSH port
- Warn when the new SSH port is not allowed by UFW
- Optionally allow the new SSH port in UFW before continuing
- Automatically restore the previous UFW configuration if the SSH change fails
- Preserve UFW active state during firewall rollback

### SSH Access Management

- Check current SSH access configuration
- Detect effective root SSH authentication settings
- Generate Ed25519 SSH key pairs
- Optional private-key passphrase protection
- Display SSH key fingerprints
- Display public keys for safe installation
- Add public keys to `authorized_keys`
- Validate public keys before installation
- List installed public keys
- Display key fingerprints
- Remove selected public keys
- Automatically back up `authorized_keys` before changes
- Create full SSH access backups
- Restore previous SSH access configuration
- Create safety backups before restore operations
- Validate restored SSH configuration
- Automatic rollback when restore validation fails
- Change the password of the target user
- Enable root key-only SSH authentication
- Disable root password authentication
- Disable root keyboard-interactive authentication
- Keep public key authentication enabled
- Verify effective SSH authentication settings before and after changes
- Require an active SSH session before enabling key-only access
- Require at least one root public key before enabling key-only access

### Firewall Management

U-OPTI uses UFW for firewall management.

- Check firewall status
- View configured firewall rules
- Configure the initial firewall
- Automatically detect the current SSH port
- Automatically allow HTTP (80/tcp)
- Automatically allow HTTPS (443/tcp)
- Add multiple TCP ports at once
- Remove multiple TCP ports at once
- Protect the current SSH port from accidental removal
- Support IPv4 and IPv6 firewall rules
- Back up firewall configuration before major changes
- Restore previous firewall configuration if a protected operation fails
- Deny incoming traffic by default
- Allow outgoing traffic by default

Multiple ports can be entered in a single line using spaces:

```text
2087 2096 2053 8443
```

### Backup & Restore

U-OPTI provides a lightweight, targeted backup system for important U-OPTI and server-security configuration.

Backups can include:

- `/etc/u-opti`
- `/etc/ssh/sshd_config`
- `/etc/ufw`
- U-OPTI-managed Fail2Ban SSH configuration

Backup operations include:

- Create backup
- List backups
- Restore backup
- Create a safety backup before restore
- Validate backup archives before restoration

U-OPTI backups are not intended to replace full-server snapshots. Provider snapshots remain the preferred method for full server recovery.

### X-UI PRO Management

- Install X-UI PRO
- Uninstall X-UI PRO
- Use the managed X-UI PRO installation workflow
- Preserve unrelated Nginx and server services during U-OPTI uninstall

### Certificate Management

- Install Certbot
- Issue Let's Encrypt certificates using ACME Webroot
- Renew certificates
- Remove certificates
- Use dedicated ACME configuration per domain
- Keep existing Nginx site configuration separate from certificate issuance

### U-OPTI Self-Update

- Check the installed and remote U-OPTI version
- Avoid unnecessary updates when versions are equal
- Reject invalid version formats
- Download all required files before installation
- Validate downloaded files
- Run Bash syntax checks before installation
- Back up the current U-OPTI installation
- Verify installed files after update
- Automatically restore the previous installation if the update fails
- Automatically restart U-OPTI using the newly installed version after a successful update

### Safe Uninstall

U-OPTI uninstall requires explicit confirmation and creates a final safety backup before removing the U-OPTI application files.

The uninstall process removes only U-OPTI itself and keeps unrelated server services such as Nginx, Certbot, X-UI/Xray, and Docker untouched.

## Installation

### Stable Version

Install the latest stable version from the `main` branch:

```bash
curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/main/install.sh -o /tmp/u-opti-install.sh
bash /tmp/u-opti-install.sh
```

After installation, run:

```bash
u-opti
```

## Safety

U-OPTI validates important configuration changes before applying them whenever possible.

For SSH operations, the tool can create backups, validate the resulting configuration, verify effective settings and listeners, and automatically roll back failed changes.

When UFW is active, SSH port changes include an additional firewall safety check before applying the new port.

When enabling root key-only SSH access, keep the current SSH session open until a second SSH connection using the private key has been successfully tested.

Do not upload or commit private SSH keys to GitHub.

If a passphrase is used for a private SSH key, keep the passphrase separate from the private key and store both securely.

## Development

Development work is performed on dedicated version or feature branches and tested on clean Ubuntu servers before release.

The `main` branch contains the stable release.

## License

See the repository license for details.
