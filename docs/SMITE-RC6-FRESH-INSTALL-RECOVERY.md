# RC6 fresh installation and interrupted-install rollback

This is a fresh-host path, not migration of an active IR/KH server.
Application source is Smite `25ff25585be3f7ff1c8b73b39a23d0509f9a2312`
with independently verified immutable RC6 images. Real Ubuntu VPS/network
qualification is still pending; the operator explicitly chose to perform that
qualification from main after repository checks. Never report it as completed.

## Normal entry

Use the official U-OPTI installer and Smite Management → Install Components:
1. IR: Install Panel + Iran Node (Ubuntu 24.04 amd64, hostname `ir`).
2. KH: Install Foreign Node (Ubuntu 24.04 amd64).

Existing files, services or managed containers are refused. The RC6 journal is
created before application installation. Images are signature checked first.
The selected installer clears ambient Docker overrides; the Compose guard uses
the local socket. Each new attempt has its own Compose project and Node volume.
Historical RC1 recovery and legacy option 4 are not repurposed.

After core installation use the existing menus for Gateway, Signed Pairing,
Sanaei, FRP Owner/Child and Signed Inventory. Approval remains Panel request →
authenticated terminal G → 1 → explicit fresh final publication → Verify and
real client test. Pairing, TLS and FRP are not automatically approved by install.

## Interrupted installation

Do not rerun the old RC1 resume tool or manually delete files/volumes.
Open Install Components → **7) Recover interrupted RC6 install**.
Read status and enter `ROLLBACK-RC6` only for that interrupted fresh attempt.

The recovery command refuses an installer still running, a completed install,
foreign/replaced containers, an activated Node authentication mode, Panel nodes,
tunnels/leases, TrustedGrants, routes or later security configuration. A failed
validation is HOLD, not permission to remove state manually.

Before changes it durably records container IDs and filesystem device/inode
identities. It disables restart only for owned paused containers, stops and
renames them, and quarantines files by same-filesystem rename. If it prepared the
broker, its unit must exactly match the provisioner's expected bytes before the
unit is disabled. No database, certificate, identity, replay volume or container
is deleted. Interrupted rollback resumes from its saved plan and fails closed
on replacement or ambiguous paths.

After `RC6_ROLLBACK=PASS_DATA_RETAINED`, repeat option 1 or 2. This is rollback
and retry, not continuation of a half-written configuration. Previous images,
packages, the inert broker group, archived files and stopped containers remain.
A new attempt uses a new Node volume; retained identity data is never silently
adopted. This does not promise a pristine OS or uninstall Docker/Nginx packages.

Recovery records: `/var/lib/u-opti/rc6-install-journal/` (root only).
Retained paths: original filename plus `.rc6-rollback-uopti_rc6_<id>`.
Retained containers: `smite-panel-uopti_rc6_<id>` / `smite-node-uopti_rc6_<id>`.
Never restore an individual archived database into a different identity or
replay installation. Archives require a separately reviewed restore plan.

## Verification boundary

Local failure-injection tests exercise rollback, retry, crash between rename and
journal completion, identity/path substitution, live-installer refusal and
active-state refusal. CI also uses actual Docker to prove retained container,
restart-policy and volume bytes. Existing image first-boot/authentication and
replay tests remain. These tests do not replace the operator's fresh VPS,
public TLS, signed enrollment, real VLESS/XHTTP, or reboot tests.
