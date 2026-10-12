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

## Stage 1: fail-closed, pure Smite spec normalization (not deployed)

`modules/smite-backhaul-spec.py` provides a stateless, opt-in compiler for
Backhaul server and client specs. It requires a deliberate
`uopti_standard_backhaul=true` flag, a generated 24+ character token,
transport `ws`, one identical-port mapping and disjoint nonreserved ports.
It forces the IR control + data listener to 127.0.0.1 and KH client remote
address to the KH loopback WS bridge. It refuses public/ambiguous mappings.

This compiler **is not yet connected to Smite Panel or Node**, so a new
Backhaul tunnel created through the unmodified Smite UI would still get the
upstream wildcard/default behavior. Do not create a live Backhaul tunnel yet.

After tests pass, integrate this compiler into the persistent overlays for
Smite Panel's create/reapply/startup and Smite Node's BackhaulAdapter. The
flag will be populated by an explicit opt-in U-OPTI wizard; the existing
Private Network mode and production FRP must never call this compiler.

Test:

```bash
python3 tests/test-smite-backhaul-spec.py
```
