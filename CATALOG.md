# U-OPTI Feature Catalog

This catalog summarizes the major U-OPTI modules, their purpose, and the boundaries between related subsystems.

Current stable version: **v0.14.0**

## Core System Management

| Area | Capabilities |
| --- | --- |
| Server Update | APT update/upgrade workflow |
| System Information | Host, OS, kernel, CPU, memory, storage overview |
| Time & Date | Timezone, NTP, synchronization checks |
| Hostname | Validated hostname changes with `hostnamectl` |
| Swap | View, create, resize, disable |
| BBR | Status, compatibility, enable/disable, qdisc |
| Storage | Disk information, large files/directories, APT cache cleanup |

## Server Security

| Area | Capabilities |
| --- | --- |
| SSH Port | Safe port change, validation, listener verification, rollback |
| SSH Access | Ed25519 keys, `authorized_keys`, key-only root access, backup/restore |
| UFW | Initial firewall, rule management, SSH-port protection, rollback |
| Fail2Ban | SSH protection management |

## Certificate Management

- Certbot installation
- ACME Webroot certificate issuance
- Renewal and removal
- Apex + www alias handling where applicable
- Repair of U-OPTI-managed domain coverage
- Dedicated ACME/Nginx configuration

## X-UI PRO

X-UI PRO remains an independent U-OPTI subsystem.

- Install X-UI PRO
- Uninstall X-UI PRO
- Preserve unrelated Nginx, Docker, Smite, and Sanaei services

Smite integration does not replace or redesign X-UI PRO.

## Docker Management

Docker Management is the common entry point for:

- Docker Engine installation/status
- Docker Compose
- Sanaei 3x-UI Docker Multi-Instance
- Smite Management
- Container/Image/Volume/Network operations
- Docker cleanup

## Sanaei 3x-UI Docker Multi-Instance

Instances are stored under:

```text
/opt/3x-ui/instances/<ID>/
```

Each instance receives its own:

- Instance ID
- Domain
- Container
- Panel port
- Xray API port
- Subscription port
- Metrics port
- Hidden Web Base Path
- Data directory
- Certificate directory
- Docker Compose file
- Compatibility state
- Nginx/SSL configuration

### Compatibility Behavior

U-OPTI configures the managed Sanaei services so that:

- Panel listens on `127.0.0.1:<allocated-port>`
- Subscription listens on `127.0.0.1:<allocated-port>`
- Xray API uses the allocated per-instance port
- Metrics uses the allocated per-instance port
- Public access is handled by Nginx/HTTPS
- Hidden Web Base Path is configured through the official Sanaei `x-ui` CLI

### Fresh Instance Startup Safety

For a fresh additional instance, U-OPTI waits for the database, temporarily stops the container, writes the instance-specific settings, starts the container again, then applies and verifies Web Base Path.

This prevents a new container from trying to reuse a default Sanaei subscription port already owned by another instance.

### Xray Public Paths

U-OPTI uses the generic Nginx forwarding form:

```text
/PORT/PATH
```

This supports public path forwarding for HTTP-style Xray transports such as XHTTP, WebSocket, and HTTPUpgrade without scanning or rewriting user inbound definitions.

## Smite Management

Smite is integrated as its own lifecycle/compatibility layer.

### Install / Lifecycle

- Install Smite Panel + Iran Node
- Install Smite Foreign Node
- Show installation state
- Install Sanaei 3x-UI on a managed Smite Foreign Node

The Sanaei entry delegates to the existing U-OPTI 3x-UI installer rather than implementing a duplicate installer.

### 443 Gateway

- Panel-side gateway support
- Foreign-side gateway support
- Preserve public TCP/443 as the primary entry point in the tested architecture
- Keep backend/control services private where applicable

### Compatibility Tools

- Persistent Smite compatibility overlays
- Compose validation before activation
- Node-to-panel HTTPS/443 compatibility
- Explicit per-node control-address compatibility
- GOST/tunnel compatibility used by the tested architecture
- Image-digest migration helper with validation and rollback

### Design Boundary

**Smite is added to U-OPTI; U-OPTI is not redesigned around Smite.**

Therefore:

- X-UI PRO remains independent
- Docker 3x-UI Multi-Instance remains independent
- Removing Smite does not remove Sanaei 3x-UI
- Removing a Sanaei instance does not remove Smite
- Existing U-OPTI Nginx/SSL, backup/restore, update, uninstall, and port-allocation logic is reused instead of duplicated

## Backup & Restore

Targeted U-OPTI backups can include:

- `/etc/u-opti`
- SSH configuration
- UFW configuration
- U-OPTI-managed Fail2Ban configuration

Backup/restore operations include validation and safety backups before destructive restoration.

Provider snapshots are still recommended for full-server recovery.

## Self-Update

U-OPTI self-update provides:

- Installed/remote version comparison
- Staged downloads
- Required-file validation
- Bash syntax checks
- Pre-update backup
- Installation verification
- Automatic rollback on failure
- Automatic relaunch after successful update

Smite lifecycle, gateway, compatibility, and digest-migration modules are included in the managed update set for v0.14.0.

## Safe Uninstall

U-OPTI uninstall removes U-OPTI application files only.

It does not remove service/data installations such as:

- Nginx
- Certbot
- Docker
- X-UI PRO
- Sanaei 3x-UI
- Xray
- Smite

## v0.14.0 Validation Snapshot

The v0.14.0 Smite/Sanaei integration was validated on clean-room Ubuntu servers with:

- Smite Panel + Iran Node
- Smite Foreign Node
- TCP/443 gateway workflow
- Sanaei installation launched from Smite Foreign lifecycle
- Multiple Sanaei instances on the same Foreign server
- Independent panel/API/subscription/metrics allocation
- Loopback panel binding
- Hidden Web Base Path
- Automatic Nginx + Let's Encrypt
- Final listener verification
- No reproduction of the previous default subscription-port collision

For detailed version history, see [CHANGELOG.md](CHANGELOG.md).
