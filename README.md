# U-OPTI

Ubuntu Server Optimization and Management Tool

U-OPTI is a lightweight Bash-based tool for managing and optimizing Ubuntu servers through an interactive menu.

## Current Version

**v0.8.0**

## Features

U-OPTI currently provides the following functions:

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

## Installation

Run the following command on your Ubuntu server:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/main/install.sh)
