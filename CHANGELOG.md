# Changelog

All notable changes to U-OPTI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No unreleased changes are currently documented.

## [0.14.5] - 2026-10-03

### Added

- Added a first-class `Image Digest Migration` entry under Smite Compatibility Tools.
- Added the existing `smite-digest-migrate.sh` helper to clean U-OPTI installation packaging and feature verification.
- Added an upgrade-safe digest-helper bootstrap/synchronization path in Docker/Smite management for machines upgraded by older U-OPTI updaters that did not yet know about the helper file.

### Changed

- Smite Compatibility Tools now separates `Persistent 443 Compatibility` from `Image Digest Migration` instead of leaving the digest helper unreachable from the interactive menu.
- Digest-helper synchronization prefers the exact installed release tag when available and falls back to the active `U_OPTI_BRANCH`/`main` source for controlled branch testing or pre-release transitions.
- Removed the stale hard-coded Docker module release header and replaced the obsolete `planned for v0.13.0` runtime message with a version-neutral `not implemented yet` message.
- Documentation and feature catalog now describe the digest migration workflow and its upgrade/bootstrap behavior explicitly.

### Fixed

- Fixed a packaging gap where `modules/smite-digest-migrate.sh` existed in the repository and documentation but was not installed by a clean U-OPTI installation.
- Fixed the first-upgrade gap where a server using the legacy fixed-file updater could receive v0.14.5 code without receiving a newly introduced helper that the old updater did not know how to download.

### Safety

- Downloaded digest helpers must be non-empty, pass `bash -n`, and contain the expected `smite_digest_migrate_existing()` entry point before U-OPTI installs or sources them.
- If helper refresh fails but the existing local helper validates, U-OPTI keeps the validated local copy instead of replacing it with unverified content.
- Digest migration itself continues to verify the running image identity, back up the Compose file, validate `docker compose config`, attempt rollback on validation failure, and confirm that container identity/start time/ImageID remain unchanged.
- Digest migration does not restart/recreate Smite containers and does not modify X-UI PRO or Sanaei 3x-UI resources.

### Validation

- Modified `docker.sh` and `install.sh` passed Bash syntax validation before promotion.
- Installer consistency checks require both the digest helper and its Docker/Smite integration markers.
- The v0.14.5 changes do not modify the previously runtime-validated Smite Private Network, shared TCP/443, Backhaul, Nginx, Sanaei 3x-UI, or VLESS data paths.

## [0.14.4] - 2026-10-03

### Added

- Added a first-class Smite Private Network installation mode for both Panel + Iran Node and Foreign Node workflows.
- Added validated IPv4 input handling for private addresses and local-interface verification before applying a server's private address.
- Added managed Smite installation state fields for connection mode, Panel private IP, and Foreign private IP.
- Added optional `SMITE_CONTROL_ADDRESS` and `SMITE_BACKHAUL_ADDRESS` generation to the node environment when Private Network mode requires them.

### Changed

- Panel + Iran installation now lets the operator choose Standard / Local or Private Network mode.
- Private Network Panel installation binds the Panel API on `0.0.0.0:8000` so it remains reachable over the server's private interface, while the local Iran node continues to bootstrap through `127.0.0.1:8000`.
- Foreign installation now lets the operator choose Standard / HTTPS or Private Network transport.
- In Private Network mode, Foreign nodes register to the Panel over the private Panel address on port `8000`, fetch the Panel CA over private HTTP, and publish their own private node-control address on port `8888`.
- Standard installation behavior remains compatible with the previous flow: the Panel stays loopback-bound and Foreign nodes use the Panel domain on HTTPS/443.
- Interactive installer variables are function-local to avoid state leaking between menu workflows.

### Fixed

- Corrected the Sanaei 3x-UI Docker menu prompt so the displayed selection range now matches all available options (`0-12`).

### Safety

- Private IPv4 input must contain four numeric octets in the `0-255` range.
- The Iran private address and Foreign private address are checked against addresses actually configured on the corresponding local server before installation proceeds.
- Existing four-argument `smite_write_state` callers remain compatible because the new connection mode defaults to `standard` and private-address fields default to empty.
- Public ports `8000` and `8888` are still expected to remain blocked by the provider/firewall when Private Network mode is used.

### Validated

- Clean-room Panel + Iran installation completed successfully in Private Network mode with local Panel bootstrap, private Backhaul metadata, persistent compatibility overlays, and healthy Smite containers.
- Clean-room Foreign Node installation completed successfully in Private Network mode with Panel communication over the private network, private node-control metadata, CA retrieval, registration, and compatibility overlays.
- Installation state correctly persisted `private` mode and the expected private addresses on both servers.
- The resulting Private Network installation was subsequently validated with the shared TCP/443 gateway, private Backhaul control, Sanaei 3x-UI, end-to-end VLESS traffic, and reboot persistence.

## [0.14.3] - 2026-10-03

### Added

- Added Private Mode awareness to the Smite TCP/443 gateway.
- Added automatic Backhaul data-listener migration from public TCP/443 to loopback `127.0.0.1:9443` before Nginx takes ownership of public TCP/443.
- Added Private Mode runtime detection through `SMITE_CONNECTION_MODE` and a dedicated `SMITE_GATEWAY_PRIVATE_DATA_PORT` setting, defaulting to `9443`.
- Added transactional Smite database backup and rollback helpers for Private Mode gateway migration.

### Changed

- In Private Mode, Nginx stream routes the Smite Panel SNI to `127.0.0.1:8443` while no-SNI / RAW TCP traffic falls back to `127.0.0.1:9443`.
- Private Mode keeps the Iran node `PANEL_ADDRESS` unchanged instead of switching it to the public domain on TCP/443.
- Backhaul `listen_ip` is intentionally left unchanged during the data-listener migration so the Backhaul control listener remains reachable through the private network.
- Gateway status reports connection mode and Private Mode RAW backend state.
- Certificate renewal-hook installation is deferred until final gateway verification succeeds.

### Safety

- Private Backhaul migration requires exactly one active matching Backhaul mapping and refuses ambiguous states.
- Before changing the tunnel specification, U-OPTI backs up the Smite database, reapplies the panel, waits for health, and verifies the loopback Backhaul listener.
- Gateway failures restore Nginx files first to free public TCP/443, then restore the previous Smite database and Backhaul runtime.
- Re-running Configure / Repair on an already prepared Private Mode gateway is idempotent and avoids unnecessary tunnel-spec rewrites or Smite restarts.

### Validated

- Fresh automatic migration from Backhaul `*:443` to `127.0.0.1:9443` completed successfully through U-OPTI without manual SQLite changes.
- Nginx owned public TCP/443, Panel TLS remained on `127.0.0.1:8443`, Backhaul data remained on `127.0.0.1:9443`, and Backhaul control remained on port `3080`.
- The Iran node kept `PANEL_ADDRESS=127.0.0.1:8000` in Private Mode.
- Foreign Backhaul connections remained established over the private network and Xray remained loopback-bound.
- Panel HTTPS and the existing VLESS client configuration both remained working through the shared public TCP/443 entry.
- Reboot persistence was verified for Nginx, Smite Panel/nodes, Backhaul private control/data paths, Sanaei 3x-UI, and end-to-end VLESS connectivity.

## [0.14.2] - 2026-10-02

### Added

- Added optional `SMITE_BACKHAUL_ADDRESS` node metadata so Backhaul control traffic can use a dedicated private/internal address while the node keeps its normal public identity.
- Added persistent panel overlays for tunnel reapply and core-health paths so private Backhaul routing survives panel recreation, reapply, health repair, and reboot.

### Changed

- Backhaul client address generation prefers `backhaul_address` and falls back to the existing node IP when no private override is configured.
- The preference is applied across tunnel creation/update, panel startup restore, tunnel reapply, and core-health repair paths.

### Safety

- Private Backhaul patching is limited to Backhaul branches and validates expected replacement counts for the pinned Smite 0.1.7 source before writing.
- Patched Python source is compiled before persistence.
- Existing behavior remains unchanged when `SMITE_BACKHAUL_ADDRESS` is not set.

### Validated

- Panel communication, Foreign node control, Backhaul control, and end-to-end VLESS remained working with public control ports removed and private-network paths in use.

## [0.14.1] - 2026-10-02

### Fixed

- Smite Backhaul startup restore preserves an existing custom `ports` mapping instead of rebuilding it from `public_port` / `target_port`.
- Added a persistent `/app/main.py` compatibility overlay so the reboot fix survives panel container recreation and host reboot.

### Validated

- Custom Backhaul mapping remained intact after recreating `smite-panel` and end-to-end VLESS remained working after reboot.

## [0.14.0] - 2026-10-01

### Added

- Smite Management under Docker Management.
- Controlled Smite Panel + Iran and Foreign Node lifecycle workflows.
- Managed Smite state under `/etc/u-opti/smite/state.env` without control secrets.
- Smite Panel/Foreign TCP/443 gateway integration.
- Persistent Smite compatibility overlays under `/opt/u-opti-smite`.
- Explicit node control-address, HTTPS/443 node-to-panel, GOST/remote-port, tunnel-persistence, and image-digest compatibility helpers.
- `U_OPTI_BRANCH` override for controlled feature-branch testing.
- Smite Foreign lifecycle handoff to the existing Sanaei 3x-UI Multi-Instance installer.

### Changed

- Docker Management gained a dedicated Smite submenu.
- Smite and Sanaei 3x-UI remain independent subsystems; the Smite lifecycle reuses the existing 3x-UI installer.
- 3x-UI panel settings explicitly bind `webListen` to loopback together with the allocated web port.
- Fresh 3x-UI compatibility configuration applies instance-specific Panel/API/Subscription/Metrics settings before final Web Base Path verification.

### Fixed

- Fixed multi-instance 3x-UI startup/default subscription-port collisions.
- Fixed the mismatch between displayed loopback-only panel behavior and the actual Sanaei `webListen` setting.
- Improved failure diagnostics during 3x-UI compatibility configuration.

### Safety

- Smite runtime patching is context-checked and refuses unknown upstream code.
- Compose files are backed up and validated before compatibility activation.
- Digest migration validates running image identity and does not restart/recreate running services.
- 3x-UI public HTTPS continues to reuse U-OPTI Nginx/SSL logic.

### Validated

- Clean-room Smite Panel/Iran and Foreign installs, shared TCP/443 control paths, persistent overlays, Smite-to-Sanaei lifecycle handoff, and multiple Sanaei instances with independent ports were validated.

## [0.13.1] - 2026-09-17

### Added

- Automatic www/non-www alias handling for apex domains in Nginx/SSL and certificate requests.
- Repair Existing Domain workflow for adding missing www/non-www certificate coverage.

### Changed

- `docker-3xui-nginx.sh` uses shared server-name logic across conflict checks, ACME validation, and Certbot invocation.

## [0.13.0] - 2026-09-15

### Added

- Docker Management with Docker Engine/Compose, 3x-UI Multi-Instance, container/image/volume/network menu structure, cleanup, FakeSite, safe uninstall, and hostname management.
- Per-instance 3x-UI state, port allocation, compatibility helpers, Nginx/SSL integration, hidden Web Base Path, and generic Xray `/PORT/PATH` forwarding.

### Fixed

- Heavy Docker/Certbot operations can relaunch U-OPTI in a fresh pseudo-TTY to avoid terminal/menu corruption.
- Docker `0) Back` returns to the main menu.
- Installer/self-update downloads use cache-busting query parameters.

### Security

- U-OPTI uninstall requires confirmation and a final safety backup when state exists.
- Nginx site writes protect non-U-OPTI configurations and ACME paths are validated before certificate issuance.

## [0.12.0] - 2026-09-08

### Added

- Server update, system optimization, SSH/UFW/Fail2Ban security, X-UI PRO, certificate management, backup/restore, safe self-update, and safe uninstall foundations.

### Security

- SSH port changes validate configuration/listeners and roll back failures.
- Root key-only access requires an active session and at least one installed root public key.
- UFW protected operations use backup/restore safety.

## [0.11.1] - 2026-09-07

### Changed

- Improved time/date synchronization, menu Back handling, X-UI PRO uninstall, and self-update completion/restart behavior.

### Safety

- Added downloaded-module validation, Bash syntax checks, update backups, and rollback support.

## [0.11.0] - 2026-09-06

### Added

- SSH Access Management focused on Ed25519 keys, `authorized_keys`, SSH access backup/restore, password management, key-only root authentication, validation, and rollback.

## [0.10.0] and earlier

- Initial U-OPTI framework and interactive menu system.
- Early system optimization, SSH, firewall, X-UI PRO, and certificate-management utilities.
