# U-OPTI Feature Catalog

This catalog summarizes the major U-OPTI modules, their purpose, and the boundaries between related subsystems.

Current stable version: **v0.14.5**

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

### Private Network Mode

- Iran Panel API is reachable on the provider/private interface at port `8000`.
- Iran local node continues to use `127.0.0.1:8000`.
- Foreign node reaches the Panel over the Iran private address on `8000`.
- Foreign node publishes its private control address on `8888`.
- `SMITE_BACKHAUL_ADDRESS` can direct Backhaul control to the Iran private address.
- Private IPv4 input and local interface presence are validated.

Public `8000`, `8888`, and Backhaul control should remain blocked from the public Internet in Private Network mode.

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

Backhaul control remains on its control port over the private network.

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

### v0.14.5 Packaging / Upgrade Behavior

- Clean installer includes the digest helper.
- Docker/Smite loads the helper when present and syntax-valid.
- If an older installation reaches v0.14.5 through a legacy fixed-file updater and the helper is still missing, Compatibility Tools can bootstrap it safely.
- Helper downloads must be non-empty, pass `bash -n`, and contain the expected migration entry function before installation.
- The helper loader prefers the exact installed release tag and falls back to `U_OPTI_BRANCH`/`main` for controlled branch workflows.
- If refresh fails but an existing local helper validates, U-OPTI keeps using the validated local copy instead of replacing it with an unverified download.

## Backup & Restore

Targeted backups can include `/etc/u-opti`, SSH configuration, UFW configuration, and U-OPTI-managed Fail2Ban configuration. Provider snapshots are still recommended for full-server recovery.

## Self-Update

U-OPTI self-update provides version comparison, staged/cache-busted downloads, required-file validation, Bash syntax checks, pre-update backup, installation verification, rollback, and automatic relaunch.

The v0.14.5 digest-helper bootstrap closes the first-upgrade gap for machines whose older updater did not yet know about the helper file.

## Safe Uninstall

U-OPTI removes its own application files only and leaves Nginx, Certbot, Docker, X-UI PRO, Sanaei 3x-UI, Xray, and Smite service data untouched.

## Validation Boundary

The Smite Private Network / shared-443 architecture was runtime-validated across v0.14.1-v0.14.4. v0.14.5 is a packaging and menu-integration patch around the already-existing digest migration helper and does not alter that tested tunnel data path.

For detailed version history, see [CHANGELOG.md](CHANGELOG.md).
