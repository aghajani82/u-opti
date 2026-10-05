# U-OPTI Feature Catalog

This catalog summarizes the major U-OPTI modules, their purpose, and the boundaries between related subsystems.

Current stable version: **v0.15.2**

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
- Sanaei 3x-UI Docker Multi-Instance certificate sync into each instance's `/root/cert` mount.
- Per-instance Certbot deploy hooks for automatic renewal synchronization and targeted container restart.
- Certificate/domain/private-key, bind-mount, source-copy, and container readability verification.

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

## Smite Private Setup Wizard

Starting with v0.15.1, the recommended Smite entry is:

```text
U-OPTI
-> Docker Management
-> Smite Management
```

Smite Management opens the 10-step Private Setup Wizard directly. The Wizard verifies actual runtime state and guides the operator between KH/Foreign and IR/Panel.

### Wizard controls

```text
1-10   Open step / available actions
.1-.10 Show read-only details for a step
n      Show next recommended step
r      Refresh progress
0      Back
```

Progress markers:

```text
[✓] verified
[~] next recommended step
[ ] pending
```

Only one step is marked `[~]` at a time.

### Verified 10-step workflow

```text
1. BOTH  -> Docker
2. KH    -> 3x-UI
3. KH    -> EasyTier Foreign
4. IR    -> EasyTier Panel
5. IR    -> Smite Panel + Iran Node
6. KH    -> Smite Foreign Node
7. IR    -> Panel 443 Gateway
8. KH    -> Xray/VLESS loopback
9. PANEL -> Backhaul
10. BOTH -> Final + Reboot tests
```

Runtime verification includes Docker/Compose/service health, 3x-UI state, EasyTier role/connectivity, Smite nodes, Panel HTTPS/TCP443 gateway, Xray loopback binding, active Backhaul evidence, and Linux boot-ID based post-reboot validation.

Step 8 intentionally refuses wildcard/public listeners such as `*:10000`; the configured Xray target must be bound to loopback (`127.0.0.1` or `::1`) before the step is marked complete.

The Wizard does not store or display EasyTier secrets, Backhaul tokens, VLESS UUIDs, or other credentials.

## Smite Install / Lifecycle

Underlying lifecycle actions remain reusable by the Wizard:

- Install Smite Panel + Iran Node.
- Install Smite Foreign Node.
- Choose Standard or Private Network transport.
- Show managed installation state.
- Reuse the existing 3x-UI installer when appropriate.

### Managed State

The state can record role, connection mode, Panel domain/private IP, node name, Foreign domain/private IP, managed Smite version/ref, verified Xray loopback port, and reboot-validation boot IDs. Connection mode defaults to `standard` for backward compatibility.

## Standard Mode

- Panel remains loopback-bound on the Iran server.
- Iran node uses the local Panel endpoint.
- Foreign node reaches the Panel through the Panel domain on HTTPS/443.

## Private Network Mode — EasyTier

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

### Private Network actions

The Wizard can open the existing EasyTier status, Foreign initialization, explicit pairing display, Iran initialization, restart, connectivity test, migration, tunnel reapply, and repair actions.

Security and safety behavior:

- EasyTier release assets are pinned to v2.6.4 and checksum-verified before installation.
- Network secret and pairing data are stored under `/etc/u-opti/smite/easytier/` with restricted permissions.
- Pairing secret is not printed automatically; explicit `SHOW` confirmation is required.
- Nginx integration backs up the selected vhost, inserts a managed block at the U-OPTI Xray marker, validates with `nginx -t`, reloads, and restores on failure.

## Smite TCP/443 Gateway

Preferred Private Mode layout:

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

The v0.15.1 gateway-first flow allows this gateway to be configured before the first Backhaul tunnel exists. In that state Nginx already owns public TCP/443, Panel HTTPS is live through `127.0.0.1:8443`, and `127.0.0.1:9443` is reserved for future Backhaul data.

When the first Backhaul tunnel is created, the runtime hook keeps the Smite UI's logical port `443` while attaching the actual data listener to `127.0.0.1:9443`.

Existing Backhaul-first installations retain the older validated migration path that backs up the Smite DB, moves Backhaul data from public `:443` to loopback `9443`, verifies the listener, and rolls back protected changes on failure.

### Hardened ACME readiness probe

The local Gateway ACME test:

- forces `--noproxy '*'`,
- uses IPv4 loopback explicitly,
- retries during fresh Nginx package/reload timing,
- performs a bounded mid-retry reload,
- fails before Certbot if the local challenge file cannot be served correctly.

## Smite Compatibility Tools

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

## v0.15.1 Packaging / Upgrade Behavior

Older U-OPTI versions use a fixed self-update file list. v0.15.1 therefore keeps the existing validated on-demand bootstrap model for module families that a legacy updater does not yet know about.

The Smite Wizard bootstrap uses:

```text
install-smite-wizard.sh
modules/smite-setup-progress.sh
modules/smite-setup-progress-ui.sh
modules/smite-setup-progress-actions.sh
modules/smite-setup-progress-flow.sh
modules/smite-setup-progress-compact-ui.sh
modules/smite-gateway-acme-robust.sh
```

When a v0.15.0 server receives the new `docker.sh`, opening Smite Management prepares the Wizard bundle on demand, validates every module with `bash -n` and required entry points, installs the direct `u-opti-smite-setup` command, and then opens the Wizard.

The existing EasyTier and digest-helper bootstraps remain in place for their own legacy-upgrade gaps.

## Backup & Restore

Targeted backups can include `/etc/u-opti`, SSH configuration, UFW configuration, and U-OPTI-managed Fail2Ban configuration. Provider snapshots are still recommended for full-server recovery.

## Self-Update

U-OPTI self-update provides version comparison, staged/cache-busted downloads, required-file validation, Bash syntax checks, pre-update backup, installation verification, rollback, and automatic relaunch.

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

v0.15.1 was validated through a complete two-host Private Network deployment with live 10-step Wizard verification, gateway-first public TCP/443, hardened ACME issuance, Xray loopback enforcement, Backhaul, Panel HTTPS, end-to-end VLESS, and sequential reboot persistence on both Foreign and Iran hosts. The final clean deployment was also exercised successfully on Ubuntu 26.x.

For release-specific notes, see [docs/RELEASE-v0.15.1.md](docs/RELEASE-v0.15.1.md).

For detailed version history, see [CHANGELOG.md](CHANGELOG.md).
