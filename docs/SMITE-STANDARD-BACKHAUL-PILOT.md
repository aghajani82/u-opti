# Standard Backhaul v0.7.2 — initial design, not deployed

Work is isolated to `feature/smite-standard-backhaul`. This stage generates
only candidate configuration fragments and does not modify any server.

## Confirmed baseline

IR: Smite Standard, Nginx HTTPS:443, FRP WSS `/~!frp`,
FRP XHTTP `/18476/web`, FRPS local 7000 and 18476. Ports 3080/56053 free.
KH: Smite + Sanaei, Xray 127.0.0.1:56053 for future Backhaul.
Both Smite nodes run Backhaul v0.7.2. IR has no active Backhaul process or
TOML; historical log files may contain credentials and must remain private.

## Pilot: independent control and data

- KH Backhaul client transport=ws to local KH Nginx 127.0.0.1:13080.
- KH Nginx verifies CA, hostname, SNI on outbound HTTPS to ir.kolbe1.ir:443.
- IR HTTPS Nginx proxies fixed WS paths `/channel` and `/tunnel/*`
  to Backhaul Server WS bound 127.0.0.1:3080.
- IR Nginx /56053/web -> local Backhaul data listener 127.0.0.1:56053
  -> KH Xray 127.0.0.1:56053.
- FRP remains unchanged, public ports remain only 80 and 443.

### Security decision

Backhaul v0.7.2 native WSS client uses insecure certificate verification.
Avoid native WSS: use plain WS **only across KH loopback**, then verified
HTTPS through Nginx. All client pool/data channels must traverse that bridge.
Backhaul access also requires a secret token, never written in documentation.

### Blockers before activation

1. Pinned Smite v0.1.7 Backhaul adapter uses wildcard IR control/data binds.
   Patch only opt-in Standard Backhaul to loopback, enforce port ownership.
2. Smite panel create/reapply/startup currently points KH client at IR:3080.
   Teach it to use KH loopback bridge address 127.0.0.1:13080.
3. Add separate, atomic, rollback-safe Nginx include installation, with
   config ownership checks and `nginx -t` before reload.
4. Add persistent Smite host overlays and installer/updater/menu integration.
5. Test a real Backhaul connection, XHTTP authenticated traffic, Reapply,
   Restart, Repair, renewal, then sequential reboots IR and KH.
6. Do not merge to main until live tests and user approval.

Renderer commands (safe previews only):

```bash
bash modules/smite-backhaul-standard.sh --render-ir-control 3080
bash modules/smite-backhaul-standard.sh --render-kh-bridge ir.kolbe1.ir 13080
bash modules/smite-backhaul-standard.sh --render-ir-xhttp 56053
bash tests/test-smite-backhaul-standard.sh
```
