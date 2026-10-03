# Changelog

All notable changes to U-OPTI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No unreleased changes are currently documented.

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

- In Private Mode, Nginx stream now routes the Smite Panel SNI to `127.0.0.1:8443` while no-SNI / RAW TCP traffic falls back to the loopback Backhaul listener on `127.0.0.1:9443`.
- Private Mode keeps the Iran node `PANEL_ADDRESS` unchanged instead of switching it to the public domain on TCP/443.
- Backhaul `listen_ip` is intentionally left unchanged during the data-listener migration so the Backhaul control listener on port `3080` remains reachable through the private network.
- Gateway status now reports the detected connection mode and Private Mode RAW backend state.
- Certificate renewal hook installation is deferred until the final gateway verification succeeds.

### Safety

- Private Backhaul migration requires exactly one active matching Backhaul mapping and refuses ambiguous states.
- Before changing the Smite tunnel specification, U-OPTI backs up the Smite database, reapplies the panel, waits for health, and verifies the loopback Backhaul listener.
- Gateway failures restore Nginx files first to free public TCP/443, then restore the previous Smite database and Backhaul runtime.
- Re-running Configure / Repair on an already prepared Private Mode gateway is idempotent and does not rewrite the tunnel specification or restart Smite Panel / Backhaul unnecessarily.

### Validated

- Fresh automatic migration from Backhaul `*:443` to `127.0.0.1:9443` completed successfully through U-OPTI without manual SQLite changes.
- After migration, Nginx owned public TCP/443, the Panel TLS backend remained on `127.0.0.1:8443`, Backhaul data remained on `127.0.0.1:9443`, and Backhaul control remained on port `3080`.
- The Iran node kept `PANEL_ADDRESS=127.0.0.1:8000` in Private Mode.
- The Foreign node maintained established Backhaul control connections to the Iran private address on port `3080`, while Xray remained loopback-bound on port `10000`.
- Both the Smite Panel domain and the existing VLESS client configuration remained working through the shared public TCP/443 entry.
- Reboot persistence was verified for Nginx, Smite Panel, Smite nodes, Backhaul private control/data paths, Sanaei 3x-UI, and end-to-end VLESS connectivity.

## [0.14.2] - 2026-10-02

### Added

- Added optional `SMITE_BACKHAUL_ADDRESS` node metadata so Backhaul control traffic can use a dedicated private/internal address while the node keeps its normal public `ip_address` identity.
- Added persistent panel overlays for `tunnel_reapply_manager.py` and `core_health.py` so private Backhaul routing survives panel recreation, reapply, health repair, and host reboot paths.

### Changed

- Backhaul client address generation now prefers `backhaul_address` and falls back to the existing `ip_address` when no private override is configured.
- The private Backhaul address preference is applied consistently across tunnel creation, tunnel update, panel startup restore, tunnel reapply, and core-health repair paths.
- Existing read-only compatibility overlays are patched on the host before runtime patching, allowing safe upgrades from earlier U-OPTI Smite overlay versions.

### Safety

- Private Backhaul patching is limited to Backhaul branches and validates the expected replacement count for each pinned Smite `0.1.7` source file before writing.
- Patched Python source is compiled before it is persisted.
- Existing behavior remains unchanged when `SMITE_BACKHAUL_ADDRESS` is not set.

### Validated

- Smite Panel communication from the Foreign server remained working over Hetzner Private Network `10.77.10.10:8000` after removing the public `8000` firewall rule.
- Panel-to-Foreign node control remained working over `10.77.10.20:8888` after removing the public `8888` firewall rule.
- Backhaul client control moved from the Iran public IP to `10.77.10.10:3080`; the Foreign server showed established Backhaul connections to the private address.
- End-to-end VLESS connectivity remained working after removing the public `3080` firewall rule, while the public client entry remained on Iran TCP/443.

## [0.14.1] - 2026-10-02

### Fixed

- Smite Backhaul startup restore now preserves an existing custom `ports` mapping instead of rebuilding it from `public_port` / `target_port`.
- Added a persistent `/app/main.py` compatibility overlay so the reboot fix survives panel container recreation and host reboot.

### Validated

- Custom Backhaul mapping `443=127.0.0.1:10000` remained intact after recreating `smite-panel`.
- End-to-end VLESS connectivity remained working after rebooting the Iran Smite server without manual reapply or restart.

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