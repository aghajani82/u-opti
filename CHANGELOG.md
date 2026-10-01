# Changelog

All notable changes to U-OPTI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No unreleased changes are currently documented.

## [0.14.0] - 2026-10-01

### Added

- Smite Management under Docker Management.
- Controlled Smite Panel + Iran Node installation and lifecycle workflow.
- Controlled Smite Foreign Node installation and lifecycle workflow.
- Managed Smite installation state under `/etc/u-opti/smite/state.env` without storing control secrets.
- Smite Panel TCP/443 gateway integration.
- Smite Foreign TCP/443 gateway integration.
- Persistent Smite compatibility overlays under `/opt/u-opti-smite` for the tested single-entry TCP/443 architecture.
- Separate compatibility preparation/activation logic with validation before container recreation.
- Smite Panel compatibility for explicit per-node `control_address` values so node API port 8888 does not need to be public.
- Smite Node compatibility for node-to-panel HTTPS registration through port 443.
- GOST/tunnel compatibility for forwarding to an explicit remote port such as TCP/443.
- Persistent tunnel cleanup behavior that stops active processes during normal node shutdown without deleting saved tunnel definitions.
- Controlled Smite image-digest migration helper with backup and rollback validation.
- Smite module integration with the U-OPTI installer and self-updater, including download, Bash syntax validation, backup, installation, verification, and rollback handling.
- `U_OPTI_BRANCH` override for controlled feature-branch installer/updater testing while preserving `main` as the default source.
- Smite Foreign lifecycle entry for installing Sanaei 3x-UI through the existing U-OPTI 3x-UI Multi-Instance installer.

### Changed

- Docker Management now includes a dedicated Smite Management submenu.
- Smite and Sanaei 3x-UI remain independent subsystems: the Smite lifecycle entry reuses `docker_3xui_install` instead of duplicating the installer.
- Docker 3x-UI panel settings now explicitly bind `webListen` to `127.0.0.1` together with the allocated `webPort`.
- Fresh 3x-UI compatibility configuration now temporarily stops the instance after database creation, writes instance-specific Panel/API/Subscription/Metrics settings, restarts the container, and only then applies Web Base Path through the official Sanaei CLI.
- U-OPTI self-update treats newly introduced modules as optional in pre-update backups so upgrades from older versions remain safe.

### Fixed

- Fixed a multi-instance 3x-UI startup collision where a fresh additional instance could start with Sanaei's default subscription port before U-OPTI wrote its allocated port.
- Prevented additional 3x-UI instances from colliding with an existing instance already listening on subscription port `2096`.
- Fixed the mismatch where U-OPTI displayed the Docker 3x-UI panel as loopback-only but had not written `webListen=127.0.0.1` into Sanaei settings.
- Improved failure diagnostics when a 3x-UI instance exits during compatibility configuration.

### Safety

- Smite runtime patching is context-checked and refuses to modify unknown upstream code when the expected source block is not present.
- Compose files are backed up and validated with `docker compose config` before compatibility activation.
- Smite image-digest migration validates the running image identity before rewriting Compose references and does not recreate a running service unnecessarily.
- 3x-UI public HTTPS continues to use the existing U-OPTI Nginx/SSL implementation with hidden Web Base Path and generic `/PORT/PATH` forwarding.
- X-UI PRO and existing Docker 3x-UI lifecycle behavior are not redesigned around Smite.

### Validated

- Clean-room Smite Panel + Iran installation.
- Clean-room Smite Foreign installation.
- Panel/Foreign Smite control through the tested TCP/443 gateway design.
- Smite compatibility overlays across container recreation.
- Smite → Sanaei Foreign lifecycle handoff to the existing U-OPTI 3x-UI installer.
- Multiple Sanaei 3x-UI instances on one Foreign server with independent ports.
- 3x-UI instance 04 installed directly from the GitHub branch with:
  - Panel `2056`
  - Xray API `62792`
  - Subscription `2098`
  - Metrics `11114`
  - Random hidden Web Base Path
  - Automatic Nginx + Let's Encrypt setup
- Final listener verification after compatibility configuration and restart.
- Previous default-subscription collision on `2096` no longer reproduced.

## [0.13.1] - 2026-09-17

### Added

- Automatic www/non-www alias handling for apex domains in the Nginx/SSL module.
- Certificate requests include both apex and www names where applicable.
- ACME challenge configuration serves all generated server names.
- Repair Existing Domain workflow for adding missing www/non-www coverage to existing U-OPTI-managed domains.

### Changed

- `docker-3xui-nginx.sh` uses a shared server-name helper for server name generation, conflict detection, ACME validation, and Certbot invocation.
- Custom Domain and SSL-only modes use the same alias rules.

## [0.13.0] - 2026-09-15

### Added

- Docker Management module with:
  - Install Docker
  - Docker Status
  - Docker Compose
  - 3x-UI Docker Management
  - Container/Image/Volume/Network management
  - Docker cleanup
- Multi-instance 3x-UI Docker registry with per-instance `state.env` and `compat.env` files under `/opt/3x-ui/instances/<ID>/`.
- Per-instance port allocation for panel, Xray API, subscription, and metrics with conflict detection against listeners, registered instances, legacy Docker state, and X-UI PRO.
- `docker-3xui-compat.sh` helpers for panel, Web Base Path, Xray API, subscription, and metrics configuration.
- `docker-3xui-nginx.sh` for public HTTPS access, Let's Encrypt issuance, hidden panel paths, subscription forwarding, and generic Xray `/PORT/PATH` forwarding.
- Custom Domain support with instance, custom-local-port, and SSL-only modes.
- `--menu <target>` direct submenu access, including `docker`.
- FakeSite module with daily random template scheduling and interactive template selection.
- Full U-OPTI uninstall routine that leaves Docker, Nginx, Certbot, 3x-UI, and other services untouched.
- Safety backups before destructive operations such as 3x-UI uninstall, restore, and U-OPTI self-uninstall.
- Hostname Management under System Optimization using validated `hostnamectl set-hostname` workflow.

### Fixed

- Heavy Docker/Certbot operations no longer leave subsequent menus with a corrupted terminal state; U-OPTI can relaunch itself inside a fresh pseudo-TTY.
- After a 3x-UI install, U-OPTI can return directly to Docker Management instead of requiring a manual exit/reopen.
- `0) Back` from Docker Management returns to the main menu instead of exiting the script.
- U-OPTI uninstall no longer fails when `/etc/u-opti` does not yet exist.
- Installer and self-update downloads use cache-busting query parameters to reduce stale-file problems from intermediate caches.

### Changed

- `common.sh` includes a self-healing terminal reset wrapper used by menu clears.
- 3x-UI Docker allocation respects existing X-UI PRO configuration and running Xray listeners.
- 3x-UI Nginx/SSL setup validates hidden Web Base Path and keeps FakeSite behavior separate.

### Security

- U-OPTI uninstall requires explicit confirmation and creates a final safety backup when U-OPTI state exists.
- Nginx site writes refuse to overwrite non-U-OPTI configurations unless the file carries the U-OPTI management marker.
- ACME challenge paths are validated through local Nginx before certificate issuance.

## [0.12.0] - 2026-09-08

### Added

- Server update through APT.
- System Optimization menu with system info, time/NTP, swap, BBR, storage, and hostname management foundations.
- Server Security menu with SSH management, SSH access management, UFW firewall management, and Fail2Ban.
- X-UI PRO Management.
- Certificate Management with Certbot and ACME Webroot.
- Backup & Restore for U-OPTI-managed server/security configuration.
- U-OPTI self-update with version validation, staged downloads, Bash syntax validation, backups, verification, rollback, and automatic relaunch.
- Safe U-OPTI uninstall that preserves unrelated server services.

### Security

- SSH port changes validate the new configuration, verify the listener, and roll back automatically on failure.
- Key-only root access requires an active SSH session and at least one installed root public key.
- UFW changes are backed up and restored on protected-operation failure.

## [0.11.1] - 2026-09-07

### Changed

- Improved time/date synchronization workflow.
- Added Back handling to BBR, Fail2Ban, and Certificate Management prompts.
- Added X-UI PRO uninstall support.
- Improved U-OPTI self-update completion and automatic restart behavior.

### Safety

- Added downloaded-module validation, Bash syntax checks, update backups, and rollback support.

## [0.11.0] - 2026-09-06

### Added

- SSH Access Management focused on Ed25519 key generation, `authorized_keys`, SSH access backup/restore, password management, and key-only root authentication.
- Safe SSH configuration validation and rollback.

## [0.10.0] and earlier

- Initial U-OPTI framework and interactive menu system.
- Early system optimization, SSH, firewall, X-UI PRO, and certificate-management utilities.
