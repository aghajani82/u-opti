# U-OPTI

Ubuntu Server Optimization and Management Tool

U-OPTI is a lightweight Bash-based tool for managing, optimizing, and maintaining Ubuntu servers through an interactive menu.

## Current Version

**v0.9.0**

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
