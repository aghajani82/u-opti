# Smite + EasyTier Clean Rebuild Test

This document is the validation checklist for the experimental `feature/smite-easytier-private-network` branch.

## Target architecture

- Iran overlay IPv4: `10.89.10.10/24`
- Foreign overlay IPv4: `10.89.10.20/24`
- EasyTier transport: WSS over the existing Foreign Nginx TCP/443 vhost
- Foreign EasyTier WS backend: `127.0.0.1:19020`
- EasyTier RPC: `127.0.0.1:15888`
- EasyTier UDP/STUN/UPnP/hole-punching/P2P: disabled
- Provider firewall: only required public web entry ports should be exposed; EasyTier does not require a public UDP port

## Clean test order

1. Rebuild both servers and install U-OPTI from the experimental branch.
2. Install Docker through U-OPTI on both servers.
3. On the Foreign server, install/configure the managed 3x-UI instance and its TLS/443 Nginx vhost first.
4. On the Foreign server, open `Docker Management -> Smite Management -> Private Network` and initialize `Foreign / KH`.
   - EasyTier v2.6.4 is checksum-verified before installation.
   - A fresh network secret and hidden WSS path are generated.
   - The secret is stored mode 0600 and is not printed automatically.
   - U-OPTI backs up the Nginx vhost, inserts the managed WSS location, validates with `nginx -t`, reloads Nginx, and starts EasyTier.
5. On the Foreign server, use `Show Pairing Details` and explicitly type `SHOW` to reveal the temporary pairing values.
6. On the Iran server, initialize `Panel / Iran` with the Foreign domain, hidden path, and network secret.
7. Verify EasyTier connectivity (`10.89.10.10 <-> 10.89.10.20`) and confirm there are no EasyTier UDP sockets.
8. Install Smite Panel + Iran through `Install / Lifecycle` using `Private Network` mode and Iran private IP `10.89.10.10`.
9. Install the Smite Foreign node using `Private Network` mode:
   - Iran Panel private IP: `10.89.10.10`
   - Foreign private IP: `10.89.10.20`
10. Configure/reapply the Smite tunnel and verify Backhaul uses the EasyTier overlay.
11. Configure the normal U-OPTI 443 gateway/data path as required by the Smite tunnel design.
12. Verify the real client/VLESS path end to end.
13. Reboot Foreign first, validate, then reboot Iran and validate again.

## Required validation points

- `u-opti` menus load without Bash errors.
- `easytier-core --version` reports the pinned v2.6.4 build.
- EasyTier systemd service is `active` and `enabled` on both hosts.
- `smite-et0` exists with the expected overlay address on both hosts.
- Iran has an established EasyTier TCP connection to Foreign TCP/443.
- Foreign EasyTier listeners are loopback-only on 19020 and 15888.
- Iran EasyTier RPC is loopback-only on 15888.
- `ss -lunp | grep easytier` returns no EasyTier UDP socket.
- Smite nodes become healthy/active over the overlay.
- Backhaul remote address resolves to `10.89.10.10:<control-port>` where appropriate.
- Existing client/VLESS connectivity works before and after reboot.

## Safety notes

- Do not reuse test network secrets in production.
- Do not expose the pairing file in logs or screenshots unless intentionally sharing it for a disposable test.
- Existing provider/private networks are not removed automatically by the EasyTier migration helper.
- The current first clean test intentionally requires a U-OPTI-managed Foreign 3x-UI TLS/443 Nginx vhost so Nginx changes can use a known marker and safe rollback path.
- OS-level hardening for Smite internal ports is a separate follow-up; provider firewall rules should not be the only production control.
