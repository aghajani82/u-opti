# U-OPTI Standard FRP Wizard: clean rebuild plan

STATUS: EXPERIMENTAL. Branch: fix/smite-frp443-persistence. Draft PR #16.
Do not merge to main or delete the known-good snapshots until the new clean install passes end-to-end.

## Live working result (2026-10-12)

The existing IR hostname and TLS/443 supported real VLESS/XHTTP traffic from v2rayN through IR Nginx -> FRPS data port -> FRP WSS -> KH FRPC -> KH Sanaei Xray. v2rayN displayed approximately 141 ms. The decisive client setting was ALPN = http/1.1. Blank ALPN failed in this tested setup. Do not assume HTTP/2 is supported by this IR Nginx gateway.

The KH Xray inbound was loopback TCP/13914, VLESS/XHTTP, mode auto, security none, and path /13914/web. The IR gateway MUST preserve the original /13914/web request URI when sending it to FRP. Xray normalizes the trailing slash internally: OPTIONS /13914/web/ returns 200 and X-Padding on both KH and IR, whereas a plain GET /13914/web can return 404 even when transport routing is healthy. OPTIONS tests do not verify VLESS authentication.

KH FRPC reconnected successfully over native WSS/443 after Smite Node restart. IR FRPS listened on local-only TCP/7000 and exposed the forwarded data port on localhost. Full host reboot and completely fresh install still need verification.

## Before destroying any host

1. Take separately verified snapshots of IR and KH. Export encrypted off-server backups for Smite panel/node data, Sanaei database and client records, certificates, U-OPTI settings and recovery credentials. Verify restore access; snapshots alone do not guarantee recovery.
2. Check emergency provider console and SSH access. Rebuilding may replace SSH host keys and cause downtime. Never paste VLESS UUIDs or FRP tokens into shared logs.
3. Prefer new disposable test servers over destroying known-good working hosts. If reusing hosts, expect outage and keep snapshots.
4. Install the experiment with U_OPTI_BRANCH set to this test branch or a recorded commit. Installer persists the selected source in INSTALL_REF so the menu Update will use the same source after logout/reboot. Never accidentally install main during the test.
5. Do not expose public TCP/7000, 8000, 8888 or the Xray loopback inbound port. Use public TLS/443 and necessary ACME/SSH rules.

## New menu

U-OPTI -> 7) Docker Management -> 5) Smite Management -> 3) Standard FRP Setup Wizard (IR/KH, experimental)

This wizard is independent of the original 10-step Private/EasyTier Wizard. It reuses the tested Standard Smite installers and gateways. FRP tunnel creation remains in the real Smite Panel UI, not an invented configuration editor.

### Logical IR (Panel + Iran Node)

Step 1: check Docker, Node, Panel, gateway, FRP WSS overlay and XHTTP timer.
Step 2: install Smite Panel + Iran Node using Standard mode. Fresh installer automatically prepares and mounts FRP v0.71.0 WSS overlays; no direct compatibility shell calls are required.
Step 3: configure IR Smite HTTPS/443 gateway. This prepares the WSS upgrade route /~!frp and the managed XHTTP include/timer.
Step 4: verify current service and tunnel state.
Step 5: after KH is ready, create an FRP TCP tunnel in the Panel: Iran node server, Foreign node client, local FRPS bind port 7000; forwarded TCP port identical to the KH Sanaei XHTTP inbound port.
Step 6: test HTTPS OPTIONS to /PORT/web/ over IR 443: expect 200 and X-Padding. This is a routing probe only.
Step 7: display the tested v2rayN profile with ALPN = http/1.1.
Step 8: see the separate reboot, recovery and backup checks.

### Logical KH (Foreign Node + Docker Sanaei)

Step 1: prerequisites and node status.
Step 2: install Standard Foreign Smite Node AFTER IR Panel HTTPS is ready. Installer automatically prepares and mounts FRPC WSS overlay.
Step 3: configure KH HTTPS/443 control gateway.
Step 4: open the existing Docker 3x-UI menu and install Sanaei, sharing the same KH domain and TLS/443 vhost.
Step 5: in Sanaei, create VLESS XHTTP inbound listening on 127.0.0.1:PORT, path /PORT/web, mode auto, security none. Then create the matching FRP TCP tunnel in Smite UI.
Step 6: test KH loopback XHTTP with OPTIONS http://127.0.0.1:PORT/PORT/web/ (expect 200 and X-Padding).
Step 7: client profile recipe.
Step 8: reboot/recovery checklist.

The forwarded port is operator-selected, not hardcoded to 13914. Do not change the existing private-mode configuration.

## Tested v2rayN profile

Protocol: VLESS; client UUID from KH Sanaei
Server: existing IR Panel hostname
Port: 443
Transport: XHTTP
Path: /PORT/web
Mode: auto
XHTTP Extra: {"mode":"auto","xPaddingBytes":"100-1000"}
Security: tls (TLS termination on IR)
SNI: IR Panel hostname
Fingerprint: chrome
ALPN: http/1.1 (required for currently verified gateway)
Host: empty
KH inbound security: none

The key connection fix was HTTP/1.1 ALPN, not modifying the Sanaei inbound.

## Required tests before production or merging the Draft PR

- Verify Panel, both Smite Nodes, KH shared Sanaei/control HTTPS and client VLESS work on new installs.
- Verify actual FRPC login success and proxy success after Smite UI tunnel create. A successfully applied configuration is not proof of connection.
- Verify FRPS TCP/7000 and forwarded TCP data ports bind to IR loopback only. Ensure KH Xray binds to loopback only.
- Check automatic XHTTP route creation/removal and repair/rollback, renewal dry-run and Nginx validity.
- Reboot IR alone and re-verify; reboot KH alone and re-verify; check FRP retry, routes and client data again.
- Perform security review of public fixed FRP WebSocket route, peer IP allowlisting, FRP token exposure/rotation and XHTTP forwarded-port policy. These checks are NOT replaced by unit tests.
- Retain the original 10-step Private Wizard unchanged.
