# Smite + EasyTier Clean Rebuild Validation

This document records the clean-room validation completed for U-OPTI v0.15.0 and the provider-independent Smite Private Network architecture.

## Target architecture

- Iran overlay IPv4: `10.89.10.10/24`
- Foreign overlay IPv4: `10.89.10.20/24`
- EasyTier transport: WSS over the existing Foreign Nginx TCP/443 vhost
- Foreign EasyTier WS backend: `127.0.0.1:19020`
- EasyTier RPC: `127.0.0.1:15888`
- EasyTier UDP/STUN/UPnP/hole-punching/P2P: disabled
- Smite Panel private API: `10.89.10.10:8000`
- Foreign Smite control API: `10.89.10.20:8888`
- Backhaul control path: `10.89.10.10:3080`
- Final Iran public entry: Nginx TCP/443
- Final Panel TLS backend: `127.0.0.1:8443`
- Final Backhaul data backend: `127.0.0.1:9443`
- Foreign Xray test target: `127.0.0.1:10000`
- Provider firewall during validation: public TCP `80` and `443` only

## Clean test order

1. Rebuild both servers and install U-OPTI from the EasyTier feature branch.
2. Install Docker through U-OPTI on both servers.
3. On the Foreign server, install/configure the managed 3x-UI instance and its TLS/443 Nginx vhost first.
4. On the Foreign server, open `Docker Management -> Smite Management -> Private Network` and initialize `Foreign / KH`.
   - EasyTier v2.6.4 is checksum-verified before installation.
   - A fresh network secret and hidden WSS path are generated.
   - The secret is stored mode `0600` and is not printed automatically.
   - U-OPTI backs up the Nginx vhost, inserts the managed WSS location, validates with `nginx -t`, reloads Nginx, and starts EasyTier.
5. On the Foreign server, use `Show Pairing Details` and explicitly type `SHOW` to reveal pairing values.
6. On the Iran server, initialize `Panel / Iran` with the Foreign domain, hidden path, and network secret.
7. Verify EasyTier connectivity (`10.89.10.10 <-> 10.89.10.20`) and confirm there are no EasyTier UDP sockets.
8. Install Smite Panel + Iran through `Install / Lifecycle` using `Private Network` mode and Iran private IP `10.89.10.10`.
9. Install the Smite Foreign node using `Private Network` mode:
   - Iran Panel private IP: `10.89.10.10`
   - Foreign private IP: `10.89.10.20`
10. Create the Backhaul tunnel with control port `3080` and test mapping `443=127.0.0.1:10000`.
11. Verify Backhaul client connections use `10.89.10.10:3080` over the EasyTier overlay.
12. Configure the U-OPTI Smite 443 gateway.
13. Verify automatic Backhaul data migration to `127.0.0.1:9443` and Nginx ownership of public TCP/443.
14. Verify public Smite Panel HTTPS and end-to-end VLESS.
15. Reboot Foreign first and validate tunnel restoration, EasyTier, 3x-UI/Xray, and VLESS.
16. Reboot Iran and validate Nginx, Smite, EasyTier, Backhaul, Panel HTTPS, and VLESS again.

## Completed validation results

- `u-opti` menus loaded without Bash errors.
- Docker installed and remained active on both hosts.
- Foreign Sanaei 3x-UI remained healthy with Panel/API/Subscription/Metrics listeners on loopback.
- EasyTier v2.6.4 installed successfully from checksum-verified release assets.
- EasyTier systemd service was `active` and `enabled` on both hosts.
- `smite-et0` used `10.89.10.10/24` on Iran and `10.89.10.20/24` on Foreign.
- Iran established the real EasyTier transport to the Foreign public address on TCP/443.
- No EasyTier UDP sockets were present.
- Overlay ping was successful with 0% packet loss after initialization settled.
- Clean Smite Panel + Iran installation completed directly in Private Network mode.
- Clean Foreign Smite node installation completed directly in Private Network mode.
- Foreign node registration used `http://10.89.10.10:8000` and succeeded.
- Panel-to-Foreign control metadata used `http://10.89.10.20:8888`.
- Backhaul control used `10.89.10.10:3080` and established multiple TCP connections from Foreign.
- Xray target remained loopback-only on `127.0.0.1:10000`.
- Before gateway activation, the test VLESS client connected successfully through Backhaul public `:443`.
- Gateway activation moved the Backhaul data mapping to `127.0.0.1:9443=127.0.0.1:10000`.
- Final Iran listener ownership was:
  - Nginx public `0.0.0.0:443` / `[::]:443`
  - Nginx Panel backend `127.0.0.1:8443`
  - Backhaul data `127.0.0.1:9443`
  - Backhaul control `*:3080`, blocked at the provider edge
- `https://<panel-domain>/api/status` returned HTTP 200.
- Smite Panel opened normally through the public HTTPS domain.
- End-to-end VLESS remained connected after gateway activation.
- Foreign reboot restored EasyTier, Smite node, 3x-UI/Xray, persisted Backhaul client state, and active Backhaul control connections.
- Iran reboot restored EasyTier, Smite Panel/Iran node, Nginx shared 443 gateway, Backhaul control/data listeners, public Panel HTTPS, and end-to-end VLESS.
- Both servers booted the updated Ubuntu kernel successfully during the persistence phase.
- Provider firewall exposure during final validation was limited to public TCP `80` and `443` on both hosts.

## Release hardening and packaging checks

- Clean installer includes `smite-private-network.sh` and `smite-easytier.sh`.
- Docker/Smite loading no longer depends on the retired experimental WireGuard peer helper.
- An upgrade-safe EasyTier pair bootstrap covers the first-hop gap from older fixed-file U-OPTI updaters.
- Downloaded bootstrap files must be non-empty, pass `bash -n`, and contain the expected menu entry functions before activation.
- The exact installed release tag is preferred; the active branch is only the fallback used for controlled branch testing or when the release tag is unavailable.
- The Private Network wrapper restores the caller's previous umask after leaving the EasyTier submenu.
- Repository CI validates Bash syntax, release metadata, and EasyTier packaging.

## Safety notes

- Do not reuse test network secrets in production.
- Do not expose pairing data in logs or screenshots unless intentionally sharing it for a disposable test.
- Existing provider/private networks are not removed automatically by the EasyTier migration helper.
- Foreign EasyTier initialization intentionally requires a U-OPTI-managed 3x-UI TLS/443 Nginx vhost so Nginx changes can use a known marker and rollback path.
- Internal Smite listeners (`8000`, `8888`, Backhaul control) must remain blocked from the public Internet. The validated deployment relied on provider firewall rules to expose only `80` and `443` publicly.

## Release conclusion

The clean-room v0.15.0 architecture passed installation, private-overlay connectivity, Smite registration, Backhaul, shared TCP/443 gateway, public Panel HTTPS, end-to-end VLESS, and sequential reboot persistence on both servers.
