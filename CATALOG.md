# U-OPTI Feature Catalog

This catalog summarizes the major U-OPTI modules, their purpose, and the boundaries between related subsystems.

Current stable version: **v0.14.4**

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

- Certbot installation.
- ACME Webroot certificate issuance.
- Renewal and removal.
- Apex + www alias handling where applicable.
- Repair of U-OPTI-managed domain coverage.
- Dedicated ACME/Nginx configuration.
- Nginx validation before reload.

## X-UI PRO

X-UI PRO remains an independent U-OPTI subsystem.

- Install X-UI PRO.
- Uninstall X-UI PRO.
- Preserve unrelated Nginx, Docker, Smite, and Sanaei services.

Smite integration does not replace or redesign X-UI PRO.

## Docker Management

Docker Management is the common entry point for:

- Docker Engine installation/status.
- Docker Compose.
- Sanaei 3x-UI Docker Multi-Instance.
- Smite Management.
- Container/Image/Volume/Network operations.
- Docker cleanup.

## Sanaei 3x-UI Docker Multi-Instance

Instances are stored under:

```text
/opt/3x-ui/instances/<ID>/
```

Each instance receives its own:

- Instance ID.
- Domain.
- Container.
- Panel port.
- Xray API port.
- Subscription port.
- Metrics port.
- Hidden Web Base Path.
- Data directory.
- Certificate directory.
- Docker Compose file.
- Compatibility state.
- Nginx/SSL configuration.

### Management Menu

```text
1) Install 3x-UI in Docker
2) Start 3x-UI
3) Stop 3x-UI
4) Restart 3x-UI
5) Update 3x-UI
6) Backup 3x-UI
7) Restore 3x-UI
8) Uninstall 3x-UI
9) Show Status
10) Sanaei 3x-UI Management
11) Nginx / SSL Configuration
12) Default Website / FakeSite
0) Back
```

### Compatibility Behavior

U-OPTI configures the managed Sanaei services so that:

- Panel listens on `127.0.0.1:<allocated-port>`.
- Subscription is kept on loopback where appropriate.
- Xray API uses the allocated per-instance port.
- Metrics uses the allocated per-instance port.
- Public access is handled by Nginx/HTTPS.
- Hidden Web Base Path is configured through the official Sanaei `x-ui` CLI.

### Fresh Instance Startup Safety

For a fresh additional instance, U-OPTI waits for the database, applies instance-specific Panel/API/Subscription/Metrics settings, restarts the container, then applies and verifies Web Base Path.

This avoids leaving a new instance on conflicting default Sanaei ports.

### Xray Public Paths

U-OPTI uses the generic Nginx forwarding form:

```text
/PORT/PATH
```

This supports public path forwarding for HTTP-style Xray transports such as XHTTP, WebSocket, and HTTPUpgrade without scanning or rewriting user inbound definitions.

## Smite Management

Smite is integrated as its own lifecycle/compatibility layer.

### Install / Lifecycle

- Install Smite Panel + Iran Node.
- Install Smite Foreign Node.
- Choose Standard or Private Network transport.
- Show managed installation state.
- Install Sanaei 3x-UI on a managed Smite Foreign Node.

The Sanaei entry delegates to the existing U-OPTI 3x-UI installer rather than implementing a duplicate installer.

### Managed Smite State

The managed state can record:

- Role.
- Connection mode.
- Panel domain.
- Panel private IP.
- Node name.
- Foreign domain.
- Foreign private IP.
- Managed Smite version/ref.

Connection mode defaults to `standard` for backward compatibility with older state callers.

### Standard Mode

Standard mode keeps the previous HTTPS-oriented behavior:

- Panel remains loopback-bound on the Iran server.
- Iran node uses the local Panel endpoint.
- Foreign node reaches the Panel through the Panel domain on HTTPS/443.

### Private Network Mode

Private Network mode uses provider/internal networking for machine-to-machine traffic.

- Iran Panel API can listen on `0.0.0.0:8000` so the private interface can reach it.
- Iran local node continues to bootstrap through `127.0.0.1:8000`.
- Foreign node reaches the Panel through the Iran private address on port `8000`.
- Foreign node publishes its own private control address on port `8888`.
- `SMITE_BACKHAUL_ADDRESS` can point Backhaul control to the Iran private address.
- Private IPv4 input is validated before installation.
- The server's own private address must exist on a local interface before installation proceeds.

Public ports `8000` and `8888` are expected to remain blocked from the public Internet in this mode.

## Smite TCP/443 Gateway

### Private Mode Architecture

The tested single-entry architecture is:

```text
Internet :443
    |
    v
Nginx stream
    |
    +-- Panel SNI -> 127.0.0.1:8443 -> Smite Panel
    |
    +-- default/no-SNI -> 127.0.0.1:9443 -> Backhaul data
```

Backhaul control remains available through its control port over the private network.

### Automatic Private Gateway Preparation

U-OPTI can:

- Detect Private Mode from managed state.
- Verify the expected Smite database/tunnel state.
- Back up the Smite database before migration.
- Move the Backhaul data listener from public `:443` to loopback `127.0.0.1:9443`.
- Keep `listen_ip` unchanged so the Backhaul control listener remains reachable over the private network.
- Reapply the tunnel and verify the loopback Backhaul listener.
- Configure Nginx stream/SNI on public TCP/443.
- Verify Panel HTTPS through the shared public entry.
- Roll back Nginx and the Smite database/runtime if a protected gateway step fails.

### Idempotency

If Private Mode is already prepared correctly, re-running Configure / Repair:

- Does not rewrite the tunnel specification unnecessarily.
- Does not restart Smite Panel/Backhaul unnecessarily.
- Revalidates the gateway state and HTTPS path.

## Smite Compatibility Layer

- Persistent compatibility overlays.
- Compose validation before activation.
- Panel startup/restore compatibility.
- Tunnel reapply compatibility.
- Core-health repair compatibility.
- Private Backhaul address preference with fallback to the normal node IP.
- Context-checked source patching.
- Python compilation before persisting patched source.
- Image-digest migration helper with validation and rollback.

## Design Boundary

**Smite is added to U-OPTI; U-OPTI is not redesigned around Smite.**

Therefore:

- X-UI PRO remains independent.
- Docker 3x-UI Multi-Instance remains independent.
- Removing Smite does not remove Sanaei 3x-UI.
- Removing a Sanaei instance does not remove Smite.
- Existing U-OPTI Nginx/SSL, backup/restore, update, uninstall, and port-allocation logic is reused instead of duplicated.

## Backup & Restore

Targeted U-OPTI backups can include:

- `/etc/u-opti`.
- SSH configuration.
- UFW configuration.
- U-OPTI-managed Fail2Ban configuration.

Backup/restore operations include validation and safety backups before destructive restoration.

Provider snapshots are still recommended for full-server recovery.

## Self-Update

U-OPTI self-update provides:

- Installed/remote version comparison.
- Staged downloads.
- Required-file validation.
- Bash syntax checks.
- Pre-update backup.
- Installation verification.
- Automatic rollback on failure.
- Automatic relaunch after successful update.

Smite lifecycle, gateway, compatibility, and digest-migration modules are included in managed update handling.

## Safe Uninstall

U-OPTI uninstall removes U-OPTI application files only.

It does not remove service/data installations such as:

- Nginx.
- Certbot.
- Docker.
- X-UI PRO.
- Sanaei 3x-UI.
- Xray.
- Smite.

## v0.14.4 Validation Snapshot

The v0.14.4 architecture was validated with:

- Clean Smite Panel + Iran installation in Private Network mode.
- Clean Smite Foreign installation in Private Network mode.
- Private Panel communication.
- Private Foreign node control.
- Private Backhaul control.
- Automatic Backhaul data migration from public `:443` to `127.0.0.1:9443`.
- Nginx owning public TCP/443.
- Panel HTTPS and RAW client traffic sharing the public TCP/443 entry.
- Sanaei 3x-UI with Xray loopback binding.
- End-to-end VLESS connectivity through Iran TCP/443.
- Idempotent gateway reconfiguration.
- Reboot persistence for the tested Nginx/Smite/Backhaul/3x-UI/VLESS path.

For detailed version history, see [CHANGELOG.md](CHANGELOG.md).
For installation and operational overview, see [README.md](README.md).
