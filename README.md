# U-OPTI

Ubuntu Server Optimization and Management Tool

U-OPTI is a Bash-based toolkit for managing, optimizing, securing, and maintaining Ubuntu servers through an interactive menu. It combines system administration, SSH/UFW/Fail2Ban hardening, Docker and Sanaei 3x-UI management, certificate automation, backup/restore, and the tested Smite integration used by this project.

## Current Version

**v0.14.5**

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

## Highlights in v0.14.5

- First-class Smite **Standard** and **Private Network** installation modes.
- Private Panel, node-control, and Backhaul paths while keeping the public client entry on TCP/443.
- Shared TCP/443 gateway: Panel HTTPS by SNI and RAW/no-SNI traffic to the Backhaul data listener.
- Automatic Private Mode Backhaul data migration from public `:443` to `127.0.0.1:9443` with backup, verification, idempotency, and rollback.
- Persistent Smite compatibility overlays across container recreation and reboot.
- Smite **Image Digest Migration** is now exposed from Compatibility Tools and is included in clean installs.
- Upgrade-safe digest-helper bootstrap: older U-OPTI installations can obtain the validated helper even when their legacy updater did not know about that file.
- Multi-instance Sanaei 3x-UI Docker management with independent Panel/API/Subscription/Metrics allocation.
- Automatic Nginx + Let's Encrypt integration, hidden Web Base Path, and generic `/PORT/PATH` forwarding for supported HTTP-style Xray transports.
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

Private Network mode is intended for provider/internal networking between the Iran and Foreign servers. The installer validates private IPv4 input and verifies that each server's own private address is actually configured before continuing.

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

Backhaul control remains on its control port over the private network. The migration changes the Backhaul data listener only; it intentionally leaves `listen_ip` unchanged so the control listener remains reachable through the private network.

The gateway workflow includes certificate reuse/issuance, Nginx stream configuration, database backup, Backhaul migration, listener verification, HTTPS verification, idempotent repair, and rollback of protected changes when a gateway step fails.

## Smite Compatibility Tools

Path:

```text
Docker Management
-> Smite Management
-> Compatibility Tools
```

Available groups:

```text
1) Persistent 443 Compatibility
2) Image Digest Migration
0) Back
```

### Persistent 443 Compatibility

This workflow prepares and activates the compatibility overlays used by the tested Smite 0.1.7 architecture, including node-to-panel communication, explicit node control addresses, private Backhaul address preference, tunnel restore behavior, and GOST/Backhaul compatibility.

### Image Digest Migration

The digest migration helper safely changes existing Smite Compose image references to the exact image digests validated by U-OPTI. It:

- verifies the running container already uses the validated image,
- creates a timestamped Compose backup before editing,
- validates `docker compose config` after the edit,
- rolls the Compose file back if validation fails,
- verifies container ID, start time, and ImageID remain unchanged,
- does **not** restart or recreate Smite containers,
- does **not** modify X-UI PRO or Sanaei 3x-UI resources.

Clean installs include `smite-digest-migrate.sh`. For upgrades from older U-OPTI builds whose updater did not know about this helper, the Docker/Smite compatibility workflow can safely bootstrap or refresh the helper after validating its Bash syntax and required function marker. It prefers the exact installed release tag when available and falls back to the active U-OPTI branch for controlled pre-release/testing workflows.

## Docker Management

Docker Management provides Docker Engine installation/status, Docker Compose, Sanaei 3x-UI Multi-Instance, Smite Management, and reserved Container/Image/Volume/Network/Cleanup menu entries.

The reserved Docker entries remain explicitly marked as not implemented; they are not presented as completed functionality.

## Sanaei 3x-UI Docker Multi-Instance

Managed instances are stored under:

```text
/opt/3x-ui/instances/<ID>/
```

Each instance receives managed state for its ID, domain, container, Panel port, Xray API port, Subscription port, Metrics port, hidden Web Base Path, data/certificate directories, Compose configuration, and Nginx/SSL configuration.

The management menu includes options 1 through 12 plus `0) Back`; the displayed selection range is `[0-12]`.

Public Xray HTTP-style transports are forwarded through the generic Nginx form:

```text
/PORT/PATH
```

## System and Security Management

U-OPTI includes:

- APT update/upgrade workflow.
- System information, time/NTP, swap, BBR/qdisc, storage, and hostname management.
- SSH port management with validation, listener verification, backup, and rollback.
- SSH access management with Ed25519 keys and key-only root workflows.
- UFW management with protected SSH handling and rollback.
- Fail2Ban management.
- X-UI PRO management.
- Certbot/ACME Webroot certificate management.
- Targeted U-OPTI backup and restore.

Provider snapshots are still recommended before major test or migration work.

## U-OPTI Self-Update

The updater provides installed/remote version comparison, cache-busted staged downloads, required-file validation, Bash syntax checks, pre-update backup, installed-file verification, automatic rollback on failure, and automatic relaunch into the updated U-OPTI version.

The v0.14.5 digest-helper compatibility path is deliberately upgrade-safe for installations coming from an older updater: the newly updated Docker module can validate and obtain the helper on demand even if the first legacy update did not directly download that newly introduced managed file.

## Safe Uninstall

U-OPTI uninstall removes U-OPTI application files only. It does **not** remove unrelated service/data installations such as Nginx, Certbot, Docker, X-UI PRO, Sanaei 3x-UI, Xray, or Smite.

## Validation

The core Private Network / gateway architecture was runtime-validated during the v0.14.1-v0.14.4 work, including clean Iran/Foreign installation, private Panel/node control, private Backhaul control, automatic Backhaul data migration, shared public TCP/443, Sanaei 3x-UI, end-to-end VLESS, idempotent gateway repair, and reboot persistence.

The v0.14.5 packaging cleanup is designed to preserve that runtime architecture; it adds managed access to the existing digest migration helper and upgrade-safe helper bootstrap without changing the tested Smite tunnel data path.

## Development

The `main` branch is the stable source used by the installer and self-updater. Release changes are prepared and checked before promotion to `main`.

## Documentation

- [Feature Catalog](CATALOG.md)
- [Changelog](CHANGELOG.md)
- [Releases](https://github.com/aghajani82/u-opti/releases)

## License

See the repository license for details.
