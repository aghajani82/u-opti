# Changelog

All notable changes to U-OPTI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.13.0] - 2026-09-15

### Added

- Docker Management module with a full submenu, including:
  - Install Docker
  - Docker Status
  - Docker Compose
  - 3x-UI Docker Management
  - Container / Image / Volume / Network management placeholders
  - Docker cleanup placeholder
- Multi-instance 3x-UI Docker registry with per-instance `state.env`
  and `compat.env` files under `/opt/3x-ui/instances/<ID>/`.
- Per-instance port allocation for panel, Xray API, subscription, and
  metrics, with automatic conflict detection against:
  - Listening ports
  - Reserved ports from other instances
  - Legacy `/opt/3x-ui/compat.env`
  - Existing X-UI PRO installation (`webPort`, `subPort`, and live Xray
    `config.json`)
- `docker-3xui-compat.sh` compatibility helpers for Sanaei 3x-UI,
  including panel port, Web Base Path, Xray API port, subscription,
  and metrics configuration with JSON-safe database updates via
  `sqlite3` and `jq`.
- `docker-3xui-nginx.sh` module for public HTTPS access:
  - Let's Encrypt certificate issuance via ACME Webroot
  - Nginx HTTPS site generation with panel, subscription, and Xray
    path forwarding (`/PORT/PATH` including gRPC pass-through)
  - Automatic certificate renewal hook installation
  - Custom Domain support with three modes:
    - Attach to a 3x-UI instance
    - Domain + custom local port
    - SSL certificate only
- `--menu <target>` option for direct submenu access. Currently
  supports `docker` to jump straight into Docker Management. Used
  internally by the 3x-UI installer.
- FakeSite module with daily random template scheduling via systemd
  timer and an interactive template selector.
- Full uninstall routine for U-OPTI itself that leaves Docker, Nginx,
  Certbot, 3x-UI, and other services untouched.
- Safety backups before destructive operations, including 3x-UI
  uninstall, restore, and U-OPTI self-uninstall.
- Troubleshooting section in README documenting PTY relaunch,
  `--menu docker`, and uninstall behavior.

### Fixed

- **TTY / menu rendering after 3x-UI Docker install.** Installing the
  3x-UI panel inside Docker (and other heavy operations such as
  Certbot and Docker Compose) left the terminal in a corrupted state,
  causing subsequent menus to render with invisible text or missing
  prompts. U-OPTI now relaunches itself inside a fresh pseudo-TTY
  using `script -qefc "<bin> --menu docker" /dev/null` after the
  install completes, restoring the terminal state exactly as if the
  user had exited and reopened U-OPTI manually.
- **Return to Docker Management after install.** After the PTY
  relaunch, U-OPTI now lands directly on the Docker Management
  submenu instead of the main menu, preserving the user's workflow.
- **`0) Back` from Docker Management no longer exits U-OPTI.**
  Pressing `0` in the Docker Management menu now returns to the main
  menu as expected, instead of terminating the entire script.
- **Uninstall no longer blocked when `/etc/u-opti` is missing.**
  Previously, if U-OPTI had never used the backup feature, the
  uninstall routine failed at the safety-backup step and refused to
  remove the installation. U-OPTI now detects that `/etc/u-opti` does
  not exist, skips the safety backup, and proceeds with uninstall as
  expected.

### Changed

- `common.sh` now overrides the shell `clear` command with a
  self-healing wrapper (`uopti_tty_reset`) that restores termios
  settings, cursor visibility, alternate screen buffer, mouse tracking
  modes, bracketed paste, application cursor keys, and scroll region
  before clearing. This acts as a global safety net for every menu
  in U-OPTI.
- Port allocation for 3x-UI Docker instances now respects existing
  X-UI PRO configuration and running Xray config, avoiding conflicts
  with `webPort`, `subPort`, and API / metrics listeners.
- Nginx / SSL setup for 3x-UI now validates Web Base Path, rejects
  `/`, and requires a dedicated path compatible with the central
  FakeSite.

### Security

- Uninstall requires explicit `UNINSTALL` confirmation and creates a
  final safety backup before removing U-OPTI application files.
- Nginx site writes refuse to overwrite non-U-OPTI configurations
  unless the file carries the U-OPTI management marker.
- ACME challenge paths are validated through the local Nginx before
  requesting certificates.

## [0.12.0] - 2026-09-08

### Added

- Server update via APT (`apt update && apt upgrade`).
- System Optimization menu with:
  - System Information
  - Time & Date and NTP configuration
  - Swap management (view, create, resize, disable)
  - BBR management (status, compatibility, enable, disable, TCP qdisc)
  - Storage management (disk info, large files / directories, APT cache)
- Server Security menu with:
  - SSH management (safe port change, validation, rollback, UFW
    integration, systemd socket activation support)
  - SSH access management (Ed25519 key pairs, `authorized_keys`,
    key-only root access, safety backups and rollback)
  - Firewall management via UFW (initial setup, port rules,
    protected SSH port, IPv4 / IPv6 support)
  - Fail2Ban management for SSH
- X-UI PRO Management (install / uninstall via remote installer).
- Certificate Management (Certbot installation, ACME Webroot
  issuance, renewal, removal).
- Backup & Restore for U-OPTI-managed configuration under
  `/etc/u-opti`, `/etc/ssh/sshd_config`, `/etc/ufw`, and Fail2Ban.
- U-OPTI self-update:
  - Version check against the remote `VERSION` file
  - Download all required files before installation
  - Bash syntax validation on every downloaded file
  - Automatic backup of the current installation
  - File-by-file verification after install
  - Automatic rollback on any failure
  - Automatic relaunch of the newly installed U-OPTI
- Safe uninstall that preserves Nginx, Certbot, 3x-UI / Xray, Docker,
  and other server services.

### Security

- SSH port changes validate the new configuration, verify the new
  listener, and roll back automatically on failure.
- Key-only root access requires an active SSH session and at least
  one root public key before being enabled.
- UFW changes are backed up and restored on failure.
## [0.13.1] - 2026-09-17

### Added
- Automatic www / non-www alias for apex domains in the Nginx / SSL
  module. Domains entered as `example.com` now also answer on
  `www.example.com`, and vice versa.
- Certificate requests now include both the apex and www names so
  HTTPS works on both variants without manual intervention.
- ACME challenge configuration serves all generated server names.

### Changed
- `docker-3xui-nginx.sh` now uses a shared `build_server_names`
  helper for server_name generation, conflict detection, ACME
  validation, and Certbot invocation.
- Custom Domain and SSL-only modes follow the same alias rules.

## [Unreleased]
  

## [0.11.0] and earlier

- Initial development of the U-OPTI framework, menu system, and
  core system management modules.
- Early SSH, firewall, and system optimization utilities.
