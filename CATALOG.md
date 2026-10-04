# U-OPTI Feature Catalog

This catalog summarizes the major U-OPTI modules, their purpose, and the boundaries between related subsystems.

Current stable version: **v0.15.0**

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
- Nginx validation before reload.

## X-UI PRO

X-UI PRO remains an independent U-OPTI subsystem. Smite integration does not replace or redesign it.

## Docker Management

Docker Management is the common entry point for:

- Docker Engine installation/status.
- Docker Compose.
- Sanaei 3x-UI Docker Multi-Instance.
- Smite Management.
- Reserved Container/Image/Volume/Network/Cleanup entries.

Reserved Docker entries that are not implemented are explicitly labeled as such at runtime.

## Sanaei 3x-UI Docker Multi-Instance

Instances are stored under:

```text
/opt/3x-ui/instances/<ID>/
```

Each instance receives its own ID, domain, container, Panel/API/Subscription/Metrics ports, hidden Web Base Path, data/certificate directories, Docker Compose file, compatibility state, and Nginx/SSL configuration.

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

The prompt range is `[0-12]`.

### Compatibility Behavior

- Panel and related management services are kept on loopback where appropriate.
- Public management access is handled through Nginx/HTTPS.
- Hidden Web Base Path is configured through the Sanaei CLI.
- Instance-specific settings are applied in a controlled startup order to avoid default-port collisions.
- HTTP-style Xray transports use the generic public form `/PORT/PATH`.

## Smite Management

Smite is an independent U-OPTI lifecycle/compatibility layer.

### Install / Lifecycle

- Install Smite Panel + Iran Node.
- Install Smite Foreign Node.
- Choose Standard or Private Network transport.
- Show managed installation state.
- Install Sanaei 3x-UI on a managed Foreign node by delegating to the existing 3x-UI installer.

### Managed State

The state can record role, connection mode, Panel domain/private IP, node name, Foreign domain/private IP, and managed Smite version/ref. Connection mode defaults to `standard` for backward compatibility.

### Standard Mode

- Panel remains loopback-bound on the Iran server.
- Iran node uses the local Panel endpoint.
- Foreign node reaches the Panel through the Panel domain on HTTPS/443.

### Private Network Mode — EasyTier

The supported provider-independent private transport is EasyTier v2.6.4 over WSS/TCP 443.

Validated overlay:

```text
Iran      10.89.10.10/24
Foreign   10.89.10.20/24
Foreign WS backend 127.0.0.1:19020
EasyTier RPC       127.0.0.1:15888
```

Behavior:

- Foreign EasyTier is exposed only through a generated hidden WSS path in the existing U-OPTI-managed TLS/443 Nginx vhost.
- Iran EasyTier connects to the Foreign domain on TCP/443 using that hidden path.
- EasyTier UDP/STUN/UPnP/hole-punching/P2P are disabled in the validated profile.
- Iran Panel API is reachable on `10.89.10.10:8000`.
- Iran local node continues to bootstrap through `127.0.0.1:8000`.
- Foreign node reaches the Panel through `10.89.10.10:8000`.
- Foreign node publishes its control address as `http://10.89.10.20:8888`.
- `SMITE_BACKHAUL_ADDRESS=10.89.10.10` directs Backhaul control across the overlay.
- EasyTier service and interface state persist across reboot.

Public `8000`, `8888`, and Backhaul control ports must remain blocked from the public Internet. The validated provider edge exposed only TCP `80` and `443` on both servers.

### Private Network Menu

```text
1) Status
2) Initialize Foreign / KH
3) Show Pairing Details (Foreign)
4) Initialize Panel / Iran
5) Start / Restart EasyTier
6) Connectivity Test
7) Migrate Existing Smite Role
8) Reapply Active Tunnels (Panel)
9) Repair EasyTier / Nginx
0) Back
```

Security and safety behavior:

- EasyTier release assets are pinned to v2.6.4 and checksum-verified before installation.
- Network secret and pairing data are stored under `/etc/u-opti/smite/easytier/` with restricted permissions.
- Pairing secret is not printed automatically; explicit `SHOW` confirmation is required.
- Nginx integration backs up the selected vhost, inserts a managed block at the U-OPTI Xray marker, validates with `nginx -t`, reloads, and restores on failure.
- The compatibility wrapper restores the caller's previous umask after leaving the EasyTier submenu.

## Smite TCP/443 Gateway

Tested Private Mode layout:

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

Backhaul control remains on its control port over the EasyTier overlay.

U-OPTI can detect Private Mode, back up the Smite database, move Backhaul data from public `:443` to `127.0.0.1:9443`, preserve the control listener, configure Nginx stream/SNI, verify the final state, and roll back protected changes on failure. Re-running an already-prepared gateway is idempotent and avoids unnecessary tunnel-spec rewrites or service restarts.

## Smite Compatibility Tools

```text
Docker Management
-> Smite Management
-> Compatibility Tools

1) Persistent 443 Compatibility
2) Image Digest Migration
0) Back
```

### Persistent 443 Compatibility

- Persistent Smite overlays.
- Compose validation before activation.
- Node-to-panel HTTPS/443 compatibility.
- Explicit per-node control-address compatibility.
- Private Backhaul address preference with normal IP fallback.
- Startup, reapply, and core-health persistence paths.
- Context-checked Python patching and compile-before-persist behavior.

### Image Digest Migration

The managed helper is `modules/smite-digest-migrate.sh`.

Safety properties:

- Running image identity must match the validated image.
- Compose file is backed up before a reference change.
- `docker compose config` is checked after the edit.
- Automatic Compose rollback is attempted on validation failure.
- Container ID, `StartedAt`, and ImageID are checked to remain unchanged.
- Smite containers are not restarted or recreated by the migration helper.
- X-UI PRO and Sanaei 3x-UI resources are not modified.

## v0.15.0 Packaging / Upgrade Behavior

Clean installs include:

```text
modules/smite-digest-migrate.sh
modules/smite-private-network.sh
modules/smite-easytier.sh
```

Older U-OPTI versions use a fixed self-update file list. v0.15.0 therefore keeps the existing digest-helper bootstrap and adds an EasyTier pair bootstrap in Docker/Smite management. The EasyTier bootstrap:

- treats the wrapper and EasyTier implementation as one validated pair,
- requires both files to be non-empty,
- runs `bash -n` on both files,
- verifies `show_smite_private_network_menu()` and `show_smite_easytier_menu()` markers,
- prefers the exact installed release tag,
- falls back to the active `U_OPTI_BRANCH`/`main` source,
- stages both files before activation,
- keeps an already validated local pair if refresh is temporarily unavailable.

The obsolete experimental `smite-private-peer.sh` / WireGuard peer-loader dependency is no longer part of Docker/Smite loading.

## Backup & Restore

Targeted backups can include `/etc/u-opti`, SSH configuration, UFW configuration, and U-OPTI-managed Fail2Ban configuration. Provider snapshots are still recommended for full-server recovery.

## Self-Update

U-OPTI self-update provides version comparison, staged/cache-busted downloads, required-file validation, Bash syntax checks, pre-update backup, installation verification, rollback, and automatic relaunch.

New helper/module families that were unknown to a legacy fixed-file updater use validated on-demand bootstrap paths so the first upgrade can complete without a manual reinstall.

## Release Automation and CI

Repository CI validates:

- Bash syntax for `install.sh`, `u-opti`, `lib/common.sh`, and all shell modules,
- semantic VERSION format,
- VERSION consistency with README, catalog, and changelog,
- EasyTier clean-install packaging and bootstrap entry points.

When a version bump reaches `main`, the release workflow extracts that version's changelog section, creates tag `v<version>`, and publishes the matching GitHub release if it does not already exist.

## Safe Uninstall

U-OPTI removes its own application files only and leaves Nginx, Certbot, Docker, X-UI PRO, Sanaei 3x-UI, Xray, Smite service data, and operator data untouched.

## Validation Boundary

v0.15.0 was validated from clean Ubuntu 24.04.5 servers through Docker, Sanaei 3x-UI, Nginx/Let's Encrypt, EasyTier WSS/TCP443 overlay, clean Smite Private Network installation, Backhaul, shared public TCP/443, Xray/VLESS, and sequential reboot persistence on both Foreign and Iran hosts.

For detailed test order and observed invariants, see [docs/SMITE-EASYTIER-CLEAN-TEST.md](docs/SMITE-EASYTIER-CLEAN-TEST.md).

For detailed version history, see [CHANGELOG.md](CHANGELOG.md).
