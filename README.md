# U-OPTI

Ubuntu Server Optimization and Management Tool · **v0.17.3**

Manage Ubuntu servers through an interactive terminal menu: system maintenance, security, Docker, Sanaei 3x-UI, certificates, backups, and Smite tunnels.

[Installation](#installation) · [Features](#features) · [Smite & FRP](#smite--frp) · [Update & recovery](#update--recovery) · [Documentation](#documentation) · [Releases](https://github.com/aghajani82/u-opti/releases)

## Installation

Run as **root** on your Ubuntu server:

```bash
curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/main/install.sh -o /tmp/u-opti-install.sh &&
bash /tmp/u-opti-install.sh
```

Open the management menu:

```bash
u-opti
```

This installs U-OPTI and its managed modules. Install and configure Docker, Smite, Sanaei, and HTTPS through their menu entries when needed.

**For the current Smite fresh-install path:** use Ubuntu **24.04 amd64** on fresh IR/KH hosts. It selects the signed **Smite 2.0.0-rc.6** candidate. Real fresh-VPS qualification is still pending; this path does not migrate an existing active Smite installation. Read the [installation and recovery guide](docs/SMITE-RC6-FRESH-INSTALL-RECOVERY.md) first.

## Features

| Area | Available tools |
| --- | --- |
| System maintenance | Server updates, system information, time/NTP, swap, BBR/qdisc, storage, and hostname management |
| Security monitoring | System Optimization → 7: opt-in local security health reports, 10-day Xray access-log archive retention, protected daily reports; does not change running services |
| Server security | SSH ports and keys, UFW, and Fail2Ban management |
| Application management | X-UI PRO, Docker Engine/Compose, and Sanaei 3x-UI instances |
| Certificates | Let's Encrypt/Certbot, certificate validation, and managed 3x-UI certificate synchronization |
| Smite networking | Panel/Node installation, HTTPS/443 gateways, FRP/XHTTP, signed pairing, and console approval |
| Maintenance & recovery | U-OPTI self-update, targeted backup/restore, diagnostics, and guarded recovery tools |

For the complete module list and feature status, see the [Feature Catalog](CATALOG.md). Reserved Docker menu entries are explicitly marked as not implemented.

## Smite & FRP

Open **Docker Management → Smite Management**.

### Fresh IR/KH setup

In **Install Components**, choose the action for the current host:

| Host / action | Menu option |
| --- | --- |
| IR: install Panel + Iran Node | **1** |
| KH: install Foreign Node | **2** |
| Recover an interrupted fresh RC6 installation | **7** |

The IR broker preparation requires the hostname `ir`. Continue through the existing Gateway, Signed Pairing, Sanaei, and Tunnel Management menus after core installation. Core installation alone does not activate pairing or publish a tunnel.

### Create and approve an XHTTP route

Once the gateways, signed pairing, FRP setup, and Signed KH Inventory are ready:

1. On **KH**, create a Sanaei VLESS/XHTTP inbound with the intended loopback port and path.
2. In **Smite Panel**, create the matching FRP tunnel and request XHTTP publication.
3. On the authenticated **IR terminal**, open the approval action **G**, review the tunnel/node/port/path, and approve with **1**.
4. Return to the same Panel dialog and submit a **fresh final publication request**.
5. Use **Verify**, then test actual VLESS/XHTTP client traffic.

Approval retains signature, request-matching, expiry, and replay checks. Passkey and independent Secure Web Approval are not part of this flow. **Backhaul is not required by FRP.**

### Other networking modes

Private Network/EasyTier, advanced tools, and legacy recovery remain separate menu paths. Backhaul Sidecar remains experimental. The [historical EasyTier validation record](docs/SMITE-EASYTIER-CLEAN-TEST.md) describes the older private-network deployment; it is not the RC6 fresh-install guide.

## Sanaei & certificates

Docker Management provides Sanaei 3x-UI multi-instance management. Managed instances live under `/opt/3x-ui/instances/<ID>/`, with their own configuration, data, and certificates.

Certificate Management can select a managed instance, validate and synchronize its certificate, and configure renewal handling. X-UI PRO and Docker-based Sanaei remain independently manageable.

Keep Xray targets and internal Smite APIs private or loopback-bound. Public web entry uses the configured Nginx HTTPS gateway; do not expose internal API or tunnel-control ports to make a failed setup appear to work. Preserve your required SSH access when configuring firewalls.

## Security Monitoring (System Optimization → 7)

After updating U-OPTI, open **2) System Optimization → 7) Security Monitoring**.
Select **1) Install / Enable** once on each server to activate a local daily security report; use **2) Run Security Check Now**, **3) View Latest Report**, **4) List Saved Reports**, **5) Open Report by Filename**, or **6) Monitoring Status** afterwards.

Reports are root-only and contain service, disk, open-port, SSH failures, Docker, firewall-counter and available Xray log indicator summaries, without raw client IPs or UUIDs. Rotation is set to 10 days only for an existing recognized U-OPTI-managed Xray log policy (or a single detected existing Xray log). Existing 3x-ui access logging is **not** enabled automatically. On systems without Sanaei/Xray, host security reports still work. The monitor does **not** block traffic, restart services, or change firewall rules.

Xray archive history is limited by rotation count and early size-based rotations; the configured 10 days are a retention target, not a guaranteed complete history. Incident snapshot backups are preserved rather than automatically deleted. [More details](docs/SECURITY-MONITOR.md).

## Update & recovery

### Update U-OPTI

Choose **Update U-OPTI** from the main menu. The updater stages and validates files, retains a pre-update backup, and supports rollback on failure.

Installations pinned to an experimental source ref retain that channel until explicitly changed. Updating U-OPTI does not by itself migrate running Smite images or reconfigure existing tunnels.

#### One-time transition from U-OPTI 0.16.7

An older **0.16.7** menu updater can abort at *Creating backup* when a module
introduced in later versions did not exist in the earlier installation. No
change pushed to GitHub can modify the updater code already running locally.
**Do not create empty placeholder modules or bypass the backup check.**

For this specific case, with an operator snapshot, root access and a reviewed
existing installation, use the official installer's **explicit legacy-adoption**
path once. It downloads one commit-pinned module set, backs up every old file
(or explicitly records absence), and applies a journal-backed transaction.
On legacy adoption it does **not** install or upgrade host packages, start
Docker containers, or alter Smite/Sanaei/Nginx. A failed integrity check must
remain HOLD, not trigger a forced re-install.

```bash
curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/main/install.sh \
  -o /root/u-opti-legacy-adopt.sh
U_OPTI_ADOPT_EXISTING=YES U_OPTI_BRANCH=main \
  bash /root/u-opti-legacy-adopt.sh
```

Run only after checking the downloaded installer source; use this **once**,
not for regular upgrades. The installed channel stays `main`. On success,
confirm `u-opti --version` and use **Update U-OPTI** (menu **8**) normally
for later releases. Persistent private backups are retained under
`/usr/local/lib/u-opti/.uopti-backup-*`; do not delete them before validating
the installation. Existing active services are not automatically upgraded.


### Recover an interrupted RC6 install

Use **Smite Management → Install Components → 7** and review the status before entering `ROLLBACK-RC6`.

The recovery path quarantines owned files and retains stopped containers and volumes. It refuses completed installations, enrolled identities, active managed state, and foreign or replaced resources. After a successful rollback, retry the appropriate fresh-install option.

This is **rollback and retry**, not an active-server migration or a full OS reset. Packages and images remain installed. Do not use the historical RC1 resume tool for RC6. See the [recovery guide](docs/SMITE-RC6-FRESH-INSTALL-RECOVERY.md) for the exact checks and retained-data locations.

### Backup & uninstall

Use **Backup & Restore** for supported U-OPTI backups, and keep a provider snapshot before significant server changes.

**Uninstall U-OPTI** removes U-OPTI application files. It does not remove unrelated service installations or their data, including Docker, Nginx, Sanaei, Xray, and Smite.

## Documentation

| Resource | Purpose |
| --- | --- |
| [Feature Catalog](CATALOG.md) | Modules, capabilities, and feature status |
| [RC6 installation & recovery](docs/SMITE-RC6-FRESH-INSTALL-RECOVERY.md) | Fresh-host requirements, rollback scope, and validation limits |
| [Stage15 release checkpoint](docs/STAGE15-CONSOLE-RELEASE-CHECKPOINT.md) | Source commits, signed images, release evidence, and remaining host tests |
| [Smite delivery board](https://github.com/aghajani82/Smite/blob/main/docs/SMITE-UOPTI-DELIVERY-BOARD.md) | Cross-repository integration tracking |
| [Historical EasyTier validation](docs/SMITE-EASYTIER-CLEAN-TEST.md) | Earlier private-network architecture and test results |
| [Changelog](CHANGELOG.md) | Detailed version history |
| [GitHub Releases](https://github.com/aghajani82/u-opti/releases) | Published versions and release notes |

## Development & validation

`main` supplies the official installer and self-updater. CI checks source syntax, security contracts, installation behavior, and recovery scenarios; relevant workflows also exercise real disposable Docker containers.

Passing CI is separate from completing a real VPS deployment. The current RC6 fresh-host path still requires operator validation of public TLS, Signed Pairing/Inventory, tunnel publication, real client traffic, and reboot persistence.
