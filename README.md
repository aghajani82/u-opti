# U-OPTI

Ubuntu Server Optimization and Management Tool

U-OPTI is a Bash-based toolkit for managing, optimizing, securing, and maintaining Ubuntu servers through an interactive menu. It combines system administration, SSH/UFW/Fail2Ban hardening, Docker and Sanaei 3x-UI management, certificate automation, backup/restore, and the tested Smite integration used by this project.

## Current Version

**v0.14.4**

## Main Menu

```text
1) Update Server
2) System Optimization
3) Server Security
4) X-UI PRO Management
5) Certificate Management
6) Backup & Restore
7) Docker Management
8) Update U-OPTI
9) Uninstall U-OPTI
0) Exit
```

## Highlights in v0.14.4

- First-class Smite **Standard** and **Private Network** installation modes.
- Private Panel/Node control paths for Smite while keeping the public client entry on TCP/443.
- Private Backhaul address support with persistent compatibility overlays.
- Automatic Private Mode migration of the Backhaul data listener from public `:443` to loopback `127.0.0.1:9443` before Nginx takes ownership of public TCP/443.
- Shared TCP/443 gateway behavior: Smite Panel HTTPS by SNI and RAW/no-SNI traffic to the Backhaul data listener.
- Idempotent gateway repair: re-running the gateway setup does not unnecessarily rewrite the tunnel specification or restart Smite services.
- Transactional backup/rollback around the Private Mode gateway migration.
- Multi-instance Sanaei 3x-UI Docker management with independent Panel/API/Subscription/Metrics allocation.
- Automatic Nginx + Let's Encrypt integration, hidden Web Base Path, and generic `/PORT/PATH` forwarding for supported HTTP-style Xray transports.
- Persistent Smite compatibility overlays across container recreation and reboot.
- Safe U-OPTI self-update with staged downloads, syntax validation, backup, verification, and rollback.

For a module-by-module view, see [CATALOG.md](CATALOG.md). For version history, see [CHANGELOG.md](CHANGELOG.md).

## Installation

Install the latest stable version from `main`:

```bash
curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/main/install.sh -o /tmp/u-opti-install.sh
bash /tmp/u-opti-install.sh
```

Then run:

```bash
u-opti
```

## Smite Architecture

Smite is integrated as an independent U-OPTI subsystem. X-UI PRO and Docker 3x-UI remain independently manageable.

### Standard Mode

Standard mode keeps the original HTTPS-oriented behavior:

- Smite Panel API stays loopback-bound on the Iran server.
- The local Iran node bootstraps against the local Panel endpoint.
- Foreign nodes reach the Panel through the Panel domain on HTTPS/443.
- Existing non-private installations remain compatible because the managed connection mode defaults to `standard`.

### Private Network Mode

Private Network mode is intended for provider/internal networking between the Iran and Foreign servers.

The installer validates private IPv4 input and verifies that each server's own private address is actually configured before continuing.

Typical behavior:

```text
Iran Panel API       -> private interface :8000
Iran local node      -> 127.0.0.1:8000
Foreign -> Panel     -> Iran private IP :8000
Panel -> Foreign API -> Foreign private IP :8888
Backhaul control     -> Iran private IP :3080
Public client entry  -> Iran TCP/443
```

U-OPTI records the selected connection mode and private addresses in the managed Smite state. No control secrets are written to that state file.

Public ports `8000`, `8888`, and the Backhaul control port should remain blocked from the public Internet when Private Network mode is used.

## Smite TCP/443 Gateway

The tested Private Mode gateway keeps one public TCP/443 entry while separating HTTPS Panel traffic from RAW client traffic.

```text
Internet TCP/443
        |
        v
   Nginx stream
        |
        +-- SNI = Panel domain -> 127.0.0.1:8443 -> Smite Panel
        |
        +-- default / no SNI   -> 127.0.0.1:9443 -> Backhaul data
```

Backhaul control remains on its control port over the private network. The migration changes the Backhaul data listener only; it intentionally does not force the Backhaul control listener onto loopback.

The gateway workflow includes:

- Existing Let's Encrypt certificate reuse when available.
- Nginx stream/SNI configuration.
- Automatic Backhaul data-listener migration for Private Mode.
- Database backup before tunnel-spec changes.
- Rollback if the migrated listener or gateway validation fails.
- Final HTTPS verification before declaring the gateway ready.
- Idempotent repair behavior for an already-prepared gateway.

## Docker Management

Docker Management provides the entry point for:

- Docker Engine installation and status.
- Docker Compose.
- Sanaei 3x-UI Docker Multi-Instance.
- Smite Management.
- Container/Image/Volume/Network operations.
- Docker cleanup.

## Sanaei 3x-UI Docker Multi-Instance

Managed instances are stored under:

```text
/opt/3x-ui/instances/<ID>/
```

Each instance receives managed state for:

- Instance ID and domain.
- Container name.
- Panel port.
- Xray API port.
- Subscription port.
- Metrics port.
- Hidden Web Base Path.
- Data/certificate directories.
- Docker Compose configuration.
- Nginx/SSL configuration.

The compatibility layer configures Panel and related management services on loopback where appropriate, while Nginx provides public HTTPS access.

A fresh additional instance is configured in a controlled order so it does not start permanently on conflicting default Sanaei ports.

The 3x-UI management menu includes:

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

## System Management

U-OPTI includes:

- APT update/upgrade workflow.
- System information.
- Timezone and NTP management.
- Swap management.
- BBR and qdisc management.
- Storage inspection and cleanup.
- Validated hostname changes.

## Server Security

### SSH

- Effective SSH port detection.
- Safe SSH port changes with configuration validation.
- Listener verification after changes.
- systemd SSH socket support.
- Automatic backup and rollback on failed changes.
- UFW-aware SSH port changes.

### SSH Access

- Ed25519 key generation.
- Optional private-key passphrase protection.
- `authorized_keys` management.
- SSH access backup/restore.
- Root key-only authentication workflow.
- Effective authentication verification before and after changes.

### UFW

- Initial firewall configuration.
- Add/remove TCP rules.
- Protection for the active SSH port.
- IPv4/IPv6 support.
- Backup/rollback around protected operations.

### Fail2Ban

- Managed SSH protection and configuration.

## Certificate Management

- Certbot installation.
- Let's Encrypt certificates through ACME Webroot.
- Renewal and removal.
- U-OPTI-managed domain repair.
- Apex/www alias handling where applicable.
- Nginx validation before certificate-related reloads.

## Backup & Restore

U-OPTI provides targeted backups for its managed configuration and important server-security files. These backups are intended for configuration recovery and do not replace full provider snapshots.

Provider snapshots are recommended before major test or migration work.

## U-OPTI Self-Update

The updater provides:

- Installed/remote version comparison.
- Cache-busted staged downloads.
- Required-file validation.
- Bash syntax checks before installation.
- Pre-update backup.
- Installed-file verification.
- Automatic rollback on failure.
- Automatic relaunch into the updated U-OPTI version.

## Safe Uninstall

U-OPTI uninstall removes U-OPTI application files only. It does **not** remove unrelated service/data installations such as:

- Nginx
- Certbot
- Docker
- X-UI PRO
- Sanaei 3x-UI
- Xray
- Smite

## Validation Snapshot for v0.14.4

The v0.14.4 work was validated on the tested Iran/Foreign server architecture with:

- Clean Smite Panel + Iran installation in Private Network mode.
- Clean Smite Foreign Node installation in Private Network mode.
- Private Panel communication and Foreign node control.
- Private Backhaul control path.
- Automatic Backhaul data-listener migration to `127.0.0.1:9443`.
- Nginx owning public TCP/443 with Panel HTTPS and RAW client traffic sharing the entry point.
- Sanaei 3x-UI with Xray on loopback.
- End-to-end VLESS connectivity through Iran TCP/443.
- Re-running gateway configuration without unnecessary Smite restarts or tunnel-spec changes.
- Reboot persistence for the tested Smite/Backhaul/Nginx/3x-UI/VLESS path.

## Development

The `main` branch is the stable source used by the installer and self-updater. Changes are tested before being promoted to `main`.

## Documentation

- [Feature Catalog](CATALOG.md)
- [Changelog](CHANGELOG.md)
- [Releases](https://github.com/aghajani82/u-opti/releases)

## License

See the repository license for details.
