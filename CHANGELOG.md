# Changelog

All notable changes to U-OPTI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.13.0] - 2026-09-15

### Added
- `u-opti --menu docker` for direct access to the Docker Management menu.
- Troubleshooting section in README.

### Fixed
- Relaunch U-OPTI inside a fresh pseudo-TTY after the 3x-UI Docker
  install to prevent broken menu rendering.
- Return to the Docker Management menu (instead of exiting U-OPTI)
  when `0` is pressed after an internal reload.
- Allow uninstall to proceed when `/etc/u-opti` does not exist.

## [0.12.0] - 2026-XX-XX

### Added
- ...
