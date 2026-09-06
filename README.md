# U-OPTI

Ubuntu Server Optimization and Management Tool

U-OPTI is a lightweight Bash-based tool for managing, optimizing, and maintaining Ubuntu servers through an interactive menu.

## Current Version

**v0.11.0**

## Features

### Server Management

- Update Ubuntu packages
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

- Detect the current SSH port
- Change SSH port safely
- Validate SSH configuration before applying changes
- Verify the new SSH listener
- Automatic rollback if SSH restart or validation fails
- Backup SSH configuration before changes
- Protect against invalid or conflicting ports

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
- Backup firewall configuration before major changes
- Restore previous firewall configuration if a protected operation fails
- Deny incoming traffic by default
- Allow outgoing traffic by default

Multiple ports can be entered in a single line using spaces:

```text
2087 2096 2053 8443
```

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

### Development / Testing Version

For testing the current development branch:

```bash
curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/refactor/v0.11.0-ssh-access/install.sh -o /tmp/u-opti-install.sh
bash /tmp/u-opti-install.sh
```

After installation, run:

```bash
u-opti
```

## SSH Key Notes

When generating an SSH key pair, the private key must be stored securely.

Do not upload or commit private SSH keys to GitHub.

If a passphrase is used, keep it separate from the private key and store both securely.

## Safety

U-OPTI validates important configuration changes before applying them whenever possible.

For SSH access operations, the tool can create backups, validate the resulting configuration, verify effective authentication settings, and automatically roll back failed changes.

When enabling root key-only SSH access, keep the current SSH session open until a second SSH connection using the private key has been successfully tested.

## Development

Development work is performed on dedicated version or feature branches and tested on clean Ubuntu servers before release.

The `main` branch contains the stable release.

## License

See the repository license for details.
