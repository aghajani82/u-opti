# U-OPTI

Ubuntu Server Optimization and Management Tool

U-OPTI is a Bash-based toolkit for managing, optimizing, securing, and maintaining Ubuntu servers through an interactive menu. It combines system administration, SSH/UFW/Fail2Ban hardening, Docker and Sanaei 3x-UI management, certificate automation, backup/restore, and the tested Smite integration used by this project.

## Current Version

**v0.15.0**

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

## Highlights in v0.15.0

- Provider-independent Smite Private Network using **EasyTier v2.6.4** over **WSS/TCP 443**.
- Fixed overlay addressing: Iran `10.89.10.10/24`, Foreign `10.89.10.20/24`.
- EasyTier UDP/STUN/UPnP/hole-punching/P2P paths disabled for the validated transport profile.
- Foreign EasyTier is hidden behind the existing U-OPTI-managed Nginx TLS/443 vhost and a generated secret WSS path.
- Pairing secret is generated locally, stored mode `0600`, and only displayed after explicit `SHOW` confirmation.
- Smite Panel, Foreign node control, and Backhaul control run over the EasyTier overlay while the public client entry remains TCP/443.
- Shared TCP/443 gateway: Panel HTTPS by SNI and RAW/no-SNI traffic to the Backhaul data listener.
- Automatic Private Mode Backhaul data migration from public `:443` to `127.0.0.1:9443` with backup, verification, idempotency, and rollback.
- Upgrade-safe EasyTier module bootstrap for systems upgrading from older U-OPTI self-updaters that did not yet know about the new module pair.
- Persistent Smite compatibility overlays and tunnel restoration across container recreation and host reboot.
- Multi-instance Sanaei 3x-UI Docker management with independent Panel/API/Subscription/Metrics allocation.
- Automatic Nginx + Let's Encrypt integration, hidden Web Base Path, and generic `/PORT/PATH` forwarding for supported HTTP-style Xray transports.
- CI now validates Bash syntax, release metadata, and EasyTier packaging before promotion.
- Stable releases are automatically tagged and published from the changelog when a version bump reaches `main`.

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

## Recommended Smite Clean Installation Order

For a fresh two-server Smite Private Network deployment, use this order. It matches the validated **gateway-first** workflow and keeps the public edge limited to TCP `80` and `443`.

Example roles/domains used below:

```text
Iran / Panel server   : ir.example.com
Foreign / KH server   : kh.example.com
EasyTier Iran IP      : 10.89.10.10
EasyTier Foreign IP   : 10.89.10.20
```

### 1. Prepare both servers

Rebuild both servers with a supported Ubuntu release, update the OS, reboot if required, install U-OPTI from `main`, and install Docker on both hosts:

```text
U-OPTI
-> Docker Management
-> Install Docker
```

At the provider/firewall edge, keep only the required public service ports exposed:

```text
80/TCP   public
443/TCP  public
```

Internal Smite, Backhaul, EasyTier, and Xray service ports such as `8000`, `8888`, `3080`, `8443`, `9443`, `10000`, `15888`, and `19020` must not be opened to the public Internet.

### 2. Foreign server: install Sanaei 3x-UI first

On the Foreign/KH server:

```text
U-OPTI
-> Docker Management
-> 3x-UI Docker Management
-> Install 3x-UI in Docker
```

Configure the Foreign domain, for example `kh.example.com`, and let U-OPTI complete the managed Nginx + Let's Encrypt setup. This step is intentionally performed before EasyTier because the Foreign EasyTier WSS endpoint is inserted into the existing U-OPTI-managed TLS/443 vhost.

Do **not** use the Smite lifecycle option `Install Sanaei 3x-UI on Foreign Node` for this clean installation path; install 3x-UI directly from Docker Management as shown above.

### 3. Foreign server: initialize EasyTier Foreign / KH

```text
U-OPTI
-> Docker Management
-> Smite Management
-> Private Network
-> Initialize Foreign / KH
```

Enter the Foreign TLS domain, for example:

```text
kh.example.com
```

Then use:

```text
Show Pairing Details (Foreign)
```

and explicitly confirm with `SHOW` when requested. Keep the generated hidden path and network secret private.

Expected Foreign overlay address:

```text
10.89.10.20/24
```

### 4. Iran server: initialize EasyTier Panel / Iran

On the Iran server:

```text
U-OPTI
-> Docker Management
-> Smite Management
-> Private Network
-> Initialize Panel / Iran
```

Use the Foreign pairing values generated in the previous step:

```text
Foreign TLS domain : kh.example.com
Hidden path        : <generated Foreign hidden path>
Network secret     : <generated Foreign network secret>
```

Expected Iran overlay address:

```text
10.89.10.10/24
```

Before continuing, verify EasyTier connectivity between the two hosts. A startup ping may lose the first packet while the WSS session is still coming up; repeat the connectivity test and continue only when the overlay is stable.

### 5. Iran server: install Smite Panel + Iran Node

```text
U-OPTI
-> Docker Management
-> Smite Management
-> Install / Lifecycle
-> Install Panel + Iran Node
```

Recommended Private Network values:

```text
Panel domain    : ir.example.com
Node name       : node-ir
Connection mode : Private Network
Private IPv4    : 10.89.10.10
```

### 6. Foreign server: install Smite Foreign Node

```text
U-OPTI
-> Docker Management
-> Smite Management
-> Install / Lifecycle
-> Install Foreign Node
```

Recommended Private Network values:

```text
Panel domain         : ir.example.com
Foreign domain       : kh.example.com
Node name            : node-kh
Connection mode      : Private Network
Iran private IPv4    : 10.89.10.10
Foreign private IPv4 : 10.89.10.20
```

### 7. Iran server: configure the TCP/443 Gateway before creating Backhaul

This is the preferred gateway-first flow:

```text
U-OPTI
-> Docker Management
-> Smite Management
-> 443 Gateway
-> Configure / Repair Panel Gateway
```

The Panel should now be reachable directly through its normal HTTPS domain, for example:

```text
https://ir.example.com
```

No temporary public `8000` exposure and no SSH port-forward are required.

The intended layout is:

```text
Internet TCP/443
        |
        v
   Nginx stream
        |
        +-- Panel SNI -> 127.0.0.1:8443 -> Smite Panel
        |
        +-- default   -> 127.0.0.1:9443 -> future Backhaul data
```

If no Backhaul tunnel exists yet, `127.0.0.1:9443` is simply reserved until the first Backhaul tunnel is created.

### 8. Foreign server: create the Xray/VLESS target

Create the desired inbound in Sanaei 3x-UI. A simple validated example is:

```text
Protocol   : VLESS
Listen IP  : 127.0.0.1
Port       : 10000
Transport  : TCP
Security   : None
Sniffing   : Off
```

Port `10000` is only a recommended example, not a requirement. Any suitable free loopback port may be used; the Backhaul custom mapping must point to the same port.

### 9. Smite Panel: create the Backhaul tunnel

Open the Smite Panel and create a tunnel with:

```text
Iran Node      : node-ir
Foreign Server : node-kh
Core           : Backhaul
Type           : TCP
Control Port   : 3080
Ports          : 443
Allow UDP      : Off
```

For the example Xray target on port `10000`, set:

```text
Advanced Settings
-> Custom Ports
443=127.0.0.1:10000
```

The Smite UI continues to use logical/public port `443`. When the U-OPTI Private Mode gateway is active, the Iran-node runtime keeps Nginx as the only public owner of TCP/443 and maps Backhaul data internally to loopback `127.0.0.1:9443`.

### 10. Final validation

Verify all of the following:

```text
- EasyTier: 10.89.10.10 <-> 10.89.10.20
- Smite Panel opens through https://ir.example.com
- Foreign Smite Node is registered and healthy
- Xray target listens only on Foreign loopback
- Backhaul tunnel is Active
- Client configuration connects end-to-end
- Public service exposure remains limited to 80/TCP and 443/TCP
```

Then reboot the Foreign server, validate again, reboot the Iran server, and repeat the final checks to confirm service and tunnel persistence.

Quick order reference:

```text
IR + Foreign: U-OPTI + Docker
        |
        v
Foreign: 3x-UI + Nginx/SSL
        |
        v
Foreign: EasyTier Foreign
        |
        v
Iran: EasyTier Panel
        |
        v
Iran: Smite Panel + Iran Node
        |
        v
Foreign: Smite Foreign Node
        |
        v
Iran: 443 Gateway
        |
        v
Foreign: Xray/VLESS loopback target
        |
        v
Smite Panel: Backhaul tunnel
        |
        v
Panel + client + reboot validation
```

## Smite Architecture

Smite is integrated as an independent U-OPTI subsystem. X-UI PRO and Docker 3x-UI remain independently manageable.

### Standard Mode

Standard mode keeps the original HTTPS-oriented behavior:

- Smite Panel API stays loopback-bound on the Iran server.
- The local Iran node bootstraps against the local Panel endpoint.
- Foreign nodes reach the Panel through the Panel domain on HTTPS/443.
- Existing non-private installations remain compatible because the managed connection mode defaults to `standard`.

### Private Network Mode — EasyTier

The supported provider-independent Private Network transport is EasyTier over WSS/TCP 443.

Validated overlay:

```text
Iran      10.89.10.10/24
Foreign   10.89.10.20/24
Transport WSS -> Foreign Nginx TLS/443 -> 127.0.0.1:19020
RPC       127.0.0.1:15888
```

Typical Smite behavior after EasyTier is initialized:

```text
Iran Panel API       -> 10.89.10.10:8000
Iran local node      -> 127.0.0.1:8000
Foreign -> Panel     -> 10.89.10.10:8000
Panel -> Foreign API -> 10.89.10.20:8888
Backhaul control     -> 10.89.10.10:3080
Public client entry  -> Iran TCP/443
```

The Foreign EasyTier role listens only on loopback for its WebSocket backend. The Iran role connects to the Foreign TLS domain through the generated hidden path. The validated profile disables EasyTier UDP/STUN/UPnP/hole-punching/P2P behavior and keeps the real transport on TCP/443.

U-OPTI records EasyTier state under `/etc/u-opti/smite/easytier/`. The network secret is stored separately with restricted permissions and is not written into the normal Smite state file.

Public ports `8000`, `8888`, and Backhaul control ports must remain blocked from the public Internet. The validated deployment exposed only public TCP `80` and `443` at the provider edge.

### EasyTier Menu

Path:

```text
Docker Management
-> Smite Management
-> Private Network
```

The menu provides status, Foreign initialization, explicit pairing display, Iran initialization, restart, connectivity testing, migration helpers, tunnel reapply, and repair.

The Foreign initialization workflow requires an existing U-OPTI-managed 3x-UI TLS/443 Nginx vhost so the hidden WSS location can be inserted using a known marker with backup, `nginx -t`, reload, and rollback behavior.

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

Backhaul control remains on its control port over the EasyTier overlay. The gateway can be configured before the first Backhaul tunnel exists; in that flow `127.0.0.1:9443` is reserved until Backhaul is created, while Smite continues to use logical/public port `443`. Existing installations that already have an active Backhaul tunnel still retain the validated migration path from public `:443` to loopback `127.0.0.1:9443`.

The gateway workflow includes certificate reuse/issuance, Nginx stream configuration, listener verification, HTTPS verification, idempotent repair, and rollback of protected changes when a gateway step fails. Legacy active-tunnel migrations also retain database backup and rollback protection.

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

## Upgrade-Safe EasyTier Bootstrap

Clean v0.15.0 installs include both:

```text
modules/smite-private-network.sh
modules/smite-easytier.sh
```

Older U-OPTI self-updaters use a fixed managed-file list, so the first upgrade to v0.15.0 may update `docker.sh` before those two newly introduced files exist locally. The Smite Private Network entry handles that first-hop gap by downloading the pair together, validating both with `bash -n` and required function markers, preferring the exact installed release tag, falling back to the active branch when needed, and keeping a previously validated local pair if refresh is temporarily unavailable.

This bootstrap path also removes the old experimental WireGuard peer-helper dependency from Docker/Smite loading.

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

The v0.14.5 digest-helper path and v0.15.0 EasyTier pair bootstrap deliberately cover first-upgrade gaps created by older fixed-file updaters without requiring operators to reinstall U-OPTI manually.

## Safe Uninstall

U-OPTI uninstall removes U-OPTI application files only. It does **not** remove unrelated service/data installations such as Nginx, Certbot, Docker, X-UI PRO, Sanaei 3x-UI, Xray, Smite, or the operator's server data.

## Validation

v0.15.0 was validated from clean Ubuntu 24.04.5 servers through the complete production path:

- clean U-OPTI feature installation,
- Docker installation on Iran and Foreign,
- Sanaei 3x-UI + Nginx/Let's Encrypt on Foreign,
- EasyTier Foreign and Iran initialization,
- real EasyTier transport from Iran public IP to Foreign public TCP/443 with no EasyTier UDP sockets,
- `10.89.10.10 <-> 10.89.10.20` overlay connectivity,
- clean Smite Panel/Iran and Foreign installation directly in Private Network mode,
- Backhaul control over `10.89.10.10:3080`,
- Xray target on Foreign loopback,
- automatic gateway migration to Nginx public `:443`, Panel `127.0.0.1:8443`, and Backhaul data `127.0.0.1:9443`,
- public Smite Panel HTTPS,
- end-to-end VLESS before and after gateway activation,
- Foreign reboot persistence,
- Iran reboot persistence,
- final end-to-end VLESS and Panel HTTPS after both reboots.

The validated provider firewall exposed only public TCP `80` and `443` on both servers.

## Development

The `main` branch is the stable source used by the installer and self-updater. Feature work is validated on dedicated branches and promoted through a pull request. The repository CI checks Bash syntax and release metadata, and the release workflow publishes a tagged GitHub release when a new version reaches `main`.

## Documentation

- [Feature Catalog](CATALOG.md)
- [Smite + EasyTier Clean Rebuild Validation](docs/SMITE-EASYTIER-CLEAN-TEST.md)
- [Changelog](CHANGELOG.md)
- [Releases](https://github.com/aghajani82/u-opti/releases)

## License

See the repository license for details.
