# U-OPTI

Ubuntu Server Optimization and Management Tool · **v0.18.0**

Manage Ubuntu servers through an interactive terminal menu: system maintenance, security, Docker, Sanaei 3x-UI, certificates, backups, and Smite tunnels.

[Installation](#installation) · [Features](#features) · [Smite, Backhaul & FRP](#smite-backhaul--frp) · [Update & recovery](#update--recovery) · [Documentation](#documentation) · [Releases](https://github.com/aghajani82/u-opti/releases)

## Installation

Run the official installer as **root** on each Ubuntu server.

```bash
curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/main/install.sh -o /tmp/u-opti-install.sh &&
bash /tmp/u-opti-install.sh
```

Open the management menu:

```bash
u-opti
```

The installer downloads U-OPTI and its managed modules from a single verified revision of `main`. Run the same command on the Iran and Foreign hosts, then choose the appropriate Smite setup from the menu below.

## Features

| Area | Available tools |
| --- | --- |
| System maintenance | Server updates, system information, time/NTP, swap, BBR/qdisc, storage, and hostname management |
| Security monitoring | System Optimization → 7: opt-in local security health reports, 10-day Xray access-log archive retention, protected daily reports; does not change running services |
| Server security | SSH ports and keys, UFW, and Fail2Ban management |
| Application management | X-UI PRO, Docker Engine/Compose, and Sanaei 3x-UI instances |
| Certificates | Let's Encrypt/Certbot, certificate validation, and managed 3x-UI certificate synchronization |
| Smite networking | Panel/Node installation, HTTPS/443 gateways, Backhaul and FRP/XHTTP, signed pairing, and console approval |
| Maintenance & recovery | U-OPTI self-update, targeted backup/restore, diagnostics, and guarded recovery tools |

For the complete module list and feature status, see the [Feature Catalog](CATALOG.md). Reserved Docker menu entries are explicitly marked as not implemented.

## Smite, Backhaul & FRP

### Fresh Iran and Foreign setup

Use two fresh Ubuntu **24.04 LTS amd64** test hosts with DNS names pointing to the corresponding servers and access to the provider consoles. The fresh Standard flow selects signed **Smite 2.0.0-rc.9**.

1. On **Iran**, open **Docker Management → Smite Management → Install Smite Components → 1) Install Panel + Iran Node**. Follow the domain and administrator prompts. Wait for `PANEL_AND_IR_INSTALL=COMPLETE`, then sign in over HTTPS and check that the Iran Node is connected.
2. In the **Smite Panel**, create the Foreign Node and copy its complete private installation packet.
3. On **Foreign**, open **Docker Management → Smite Management → Install Smite Components → 2) Install Foreign Node** and paste that packet at the hidden prompt. Follow the installer through Node, Sanaei, Gateway and signed pairing. Check for `FOREIGN_ONE_CHOICE_INSTALL=SIGNED_CONNECTED_VERIFIED` and confirm both nodes are connected in the Panel.

For a verified interrupted installation, use the same install option to resume its recorded stage. The **Install Smite Components → 7** recovery action can roll back an eligible interrupted fresh installation. Review the installer status before retrying.

### Backhaul on the RC9 pair

1. On Iran and Foreign, open **Smite Management → Tunnel Management → 1) Backhaul** and complete the signed engine setup. On Iran, choose **1** in the Backhaul setup submenu.
2. Use an eligible **loopback VLESS/XHTTP** inbound on Foreign. In Smite, use **Tunnels → Create Tunnel → Backhaul** and enter its port. Confirm the tunnel is active and test actual client traffic.
3. To remove a tunnel from both nodes and Smite, use **Tunnel Management → 7 → 1** on Iran and enter its port. To remove the Backhaul engine from Iran, remove its tunnels first and then use **7 → 2**. On Foreign, **7** removes the local engine. Active FRP can remain in place while the independent RC9 Backhaul engine is uninstalled.

### FRP on the RC9 pair

On the two paired RC9 hosts, open **Smite Management → Tunnel Management → 2) FRP — Install signed FRP engine (RC9)**. Start on Iran and enter the verified public egress IPv4 of the Foreign host. Then run the same menu on Foreign. The menu verifies completed stages and offers the next stage. WSS activation recreates the owned Smite services on each host and requires verified provider restore and console access.

After the setup reports success on both hosts, open **Smite Panel → Tunnels → Create → FRP → TCP**. Select the Iran node as server and the Foreign node as client. Use the intended loopback inbound on Foreign and the reserved loopback FRPS control port `7000`. For additional tunnels, bind each new Child to the existing FRPS Owner. Use the XHTTP approval steps below when publishing a route.

If a stage is interrupted, the exact RC9 helpers support `recover` from their own journals. Use `smite-rc7-wss-runtime.py recover --rc9 --role ir|foreign`, `smite-rc7-wss-edge.py recover --rc9` (Iran), `smite-stage15-xhttp-bridge.py recover` (Iran), or `smite-rc7-frp-enrollment.py recover --rc9 --role ir|foreign` as appropriate. Helpers are installed under `/usr/local/lib/u-opti/modules/`. Runtime, edge and enrollment recoveries also require `--snapshot-confirm SNAPSHOTS-CONSOLES-VERIFIED` at the root console. Continue from Tunnel Management option 2 after recovery.

### Create and approve an XHTTP route

Once the gateways, signed pairing, FRP setup, and Signed KH Inventory are ready:

1. On **KH**, create a Sanaei VLESS/XHTTP inbound with the intended loopback port and path.
2. In **Smite Panel**, create the matching FRP tunnel and request XHTTP publication.
3. On the authenticated **IR terminal**, open the approval action **G**, review the tunnel/node/port/path, and approve with **1**.
4. Return to the same Panel dialog and submit a **fresh final publication request**.
5. Use **Verify**, then test actual VLESS/XHTTP client traffic.

Approval retains signature, request-matching, expiry, and replay checks. FRP runs independently of Backhaul.

To remove the FRP engine, use **Tunnel Management → 8** on the intended host. On Iran, the menu withdraws published FRP routes before prompting for tunnel cleanup in Smite. Remove shared Child tunnels before their Owner, then rerun **8** to complete engine removal. To publish the same port and path after reinstalling, follow the fresh approval and publication steps above.

### Other networking modes

Private Network/EasyTier and legacy Sidecar setups have their own menu paths. See the [historical EasyTier validation record](docs/SMITE-EASYTIER-CLEAN-TEST.md) for the older private-network deployment.

## Sanaei & certificates

Docker Management provides Sanaei 3x-UI multi-instance management. Managed instances live under `/opt/3x-ui/instances/<ID>/`, with their own configuration, data, and certificates.

Certificate Management can select a managed instance, validate and synchronize its certificate, and configure renewal handling. X-UI PRO and Docker-based Sanaei remain independently manageable.

Keep Xray targets and internal Smite APIs private or loopback-bound. Public web entry uses the configured Nginx HTTPS gateway; do not expose internal API or tunnel-control ports to make a failed setup appear to work. Preserve your required SSH access when configuring firewalls.

## Security Monitoring (System Optimization → 7)

After updating U-OPTI, open **2) System Optimization → 7) Security Monitoring**.
Select **1) Install / Enable** once on each server to activate a local daily security report; use **2) Run Security Check Now**, **3) View Latest Report**, **4) List Saved Reports**, **5) Open Report by Filename**, **6) Show Last 10 Days (redacted)**, or **7) Monitoring Status** afterwards.

Reports are root-only and contain service, disk, open-port, SSH failures, Docker, firewall-counter and available Xray log indicator summaries, without raw client IPs or UUIDs. Rotation is set to 10 days only for an existing recognized U-OPTI-managed Xray log policy (or a single detected existing Xray log). Existing 3x-ui access logging is **not** enabled automatically. On systems without Sanaei/Xray, host security reports still work. The monitor does **not** block traffic, restart services, or change firewall rules.

Xray archive history is limited by rotation count and early size-based rotations; the configured 10 days are a retention target, not a guaranteed complete history. Incident snapshot backups are preserved rather than automatically deleted. [More details](docs/SECURITY-MONITOR.md).

## Update & recovery

### Update U-OPTI

Choose **Update U-OPTI** from the main menu. The updater stages and validates files, retains a pre-update backup, and supports rollback on failure.

If U-OPTI was installed from the trial branch or an exact SHA, launch `U_OPTI_BRANCH=main u-opti` and choose **8) Update U-OPTI** to return to the main channel. Existing Smite installations keep their running images and tunnel configuration during a U-OPTI update.

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


### Recover an interrupted RC6/RC7/RC9 install

Use **Smite Management → Install Components → 7** and review the status before entering `ROLLBACK-RC6`.

The recovery path quarantines owned files and retains stopped containers and volumes. It refuses completed installations, enrolled identities, active managed state, and foreign or replaced resources. After a successful rollback, retry the appropriate fresh-install option.

This operation rolls back eligible install stages and retains packages and images. The [historical RC6/RC7 recovery guide](docs/SMITE-RC6-FRESH-INSTALL-RECOVERY.md) explains the original recovery scope and retained-data locations.

For the older RC7 Panel, **Install Smite Components → 8/9** applies or restores the bundled static UI. See the [RC7 UI update and rollback guide](docs/SMITE-PANEL-UI-UPDATE.md).

### Backup & uninstall

Use **Backup & Restore** for supported U-OPTI backups, and keep a provider snapshot before significant server changes.

**Uninstall U-OPTI** removes U-OPTI application files. It does not remove unrelated service installations or their data, including Docker, Nginx, Sanaei, Xray, and Smite.

## Documentation

| Resource | Purpose |
| --- | --- |
| [Feature Catalog](CATALOG.md) | Modules, capabilities, and feature status |
| [Historical RC6/RC7 installation & recovery](docs/SMITE-RC6-FRESH-INSTALL-RECOVERY.md) | Fresh-host requirements, rollback scope, and validation limits |
| [Stage15 release checkpoint](docs/STAGE15-CONSOLE-RELEASE-CHECKPOINT.md) | Source commits, signed images, release evidence, and remaining host tests |
| [Smite delivery board](https://github.com/aghajani82/Smite/blob/main/docs/SMITE-UOPTI-DELIVERY-BOARD.md) | Cross-repository integration tracking |
| [Historical EasyTier validation](docs/SMITE-EASYTIER-CLEAN-TEST.md) | Earlier private-network architecture and test results |
| [Changelog](CHANGELOG.md) | Detailed version history |
| [GitHub Releases](https://github.com/aghajani82/u-opti/releases) | Published versions and release notes |

## Development & validation

`main` supplies the official installer and self-updater. CI checks source syntax, security contracts, installation behavior, and recovery scenarios; relevant workflows also exercise real disposable Docker containers.

The maintainer verified Backhaul and FRP creation, removal, and reuse of the original port and path on the two test servers. A fresh run of the released installer on both clean hosts remains the final acceptance test.
