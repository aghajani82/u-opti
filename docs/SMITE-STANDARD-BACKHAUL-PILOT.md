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
- IR Nginx /56053/www/ -> local Backhaul data listener 127.0.0.1:56053
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
bash modules/smite-backhaul-standard.sh --render-ir-xhttp 56053 /56053/www kh.kolbe1.ir
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

## KH XHTTP path and Host confirmed (2026-10-12)

Actual Sanaei inbound #2 (VLESS/XHTTP, local listener 127.0.0.1:56053)
uses **Path `/56053/www`**, **Host `kh.kolbe1.ir`**, mode auto and
padding bytes 100-1000. Local `OPTIONS` with matching Host returned:

- `/56053/www/`: HTTP 200 with X-Padding header.
- `/56053/www`: HTTP 404.
- All previously assumed `/56053/web` routes returned 404.

The IR XHTTP renderer now accepts validated port/path/host arguments,
forwards `Host: kh.kolbe1.ir`, preserves the slash-terminated URI and
normalizes **only** the bare exact path upstream (without redirect).
It does not change existing FRP paths or actual server configurations.

The OPTIONS response verifies only that the *local* Xray XHTTP handler is
reachable on KH. It does **not** verify Backhaul transport or authenticated
end-to-end VLESS. These remain pending live tests after safe installation.

## Stage 2: guarded Smite node adapter candidate (NOT installed)

`modules/smite-backhaul-node-patch.py` produces a separate candidate
`core_adapters.py` for the pinned Smite v0.1.7 node. It inserts the
Standard-only spec validator **before** any existing process is removed,
retains the FRP and other adapters byte-for-byte, and prevents the original
Backhaul adapter from copying Standard tokens into its debug log. Standard
TOML is created with `O_NOFOLLOW` and file permissions `0600`.

The candidate imports `app.uopti_backhaul_standard.normalize_node_spec`.
When staged later, copy `modules/smite-backhaul-spec.py` to that container
module filename and mount it read-only alongside the patched overlay.
Neither the candidate patcher nor the module is mounted or activated yet.

```bash
python3 modules/smite-backhaul-node-patch.py ORIGINAL_CORE_ADAPTERS.py CANDIDATE_CORE_ADAPTERS.py
python3 tests/test-smite-backhaul-node-patch.py
```

Critical remaining blocker: the **Smite panel** has separate Backhaul
managers and startup/reapply/create paths; some default to `0.0.0.0` and
can spawn an additional server. These must be made Standard-aware before any
Backhaul tunnel is created from the panel. Do NOT activate the candidate
node adapter on a live Smite server yet.

## Stage 3: fail-closed panel overlay candidates (NOT installed)

`modules/smite-backhaul-panel-patch.py` prepares three **candidate** Smite
Panel v0.1.7 overlays. It does not edit running containers:

- `node_client.py`: all node-bound Standard Backhaul `apply` commands,
  including create, manual/auto Reapply and panel startup sync, are compiled
  from the canonical database tunnel spec. Node roles select IR loopback
  server versus KH loopback TLS-bridge client. A missing/invalid canonical
  opt-in source is rejected without contacting the Node.
- `main.py`: the Panel's separate Backhaul manager does not start a
  duplicate listener during startup for Standard tunnels; Smite Node owns it.
- `tunnels.py`: the Panel's older direct Backhaul manager is skipped on
  manual update, and editing a Standard tunnel cannot silently remove its
  `uopti_standard_backhaul` marker.

This is not a complete deployment: it must be reconciled with U-OPTI's existing
Panel/Node persistent overlays, installed and mounted only via a guarded opt-in
procedure, then checked against actual create/reapply/restart workflows.
An ordinary Smite UI Backhaul tunnel is **not** a Standard opt-in tunnel.

The pinned upstream Smite token helper defaults to 16 characters. Standard
mode therefore requires a separate Wizard generating and storing a longer
random token BEFORE sending any apply command; a default upstream token is
intentionally rejected by the fail-closed guard.

## Stage 4: packaged, preparation-only management — NOT activated

`modules/smite-backhaul-management.sh` introduces a fourth Smite submenu
choice: **Standard Backhaul (preparation only)**. Options 1–3 retain their
original Private Network and Standard FRP handlers without changing those
modules. Fresh installation and the *newer* U-OPTI updater bundle its Bash and
Python dependencies. Update backups include missing-file markers and a dynamic
count so a failed update can remove newly installed modules.

The menu offers:
- Read-only status, strict Standard-only role and pinned image preflight.
- Offline preparation of **candidate** Panel/Node Python overlays and Nginx
  fragments under a private, versioned staging directory. The original host
  overlays are copied for review before any patching, not replaced.
- SHA256 integrity verification and removal of **unused staging files only**.

The preflight confirms no Backhaul process or TOML, expected Docker image and
bind-mounted Node adapter, valid existing Nginx, reserved ports, live IR FRP or
KH loopback Xray, and a supported Standard role. It never opens provider ports.

**This is not operational activation or live rollback.** No running Docker
container, Nginx configuration, TLS certificate, firewall, Sanaei inbound or
FRP tunnel is changed by these commands. Stage deletion is NOT a restoration
of live production services. There is deliberately no Activate menu choice.

Important caveat: an older pre-upgrade U-OPTI updater may not fetch newly
introduced files; an end-to-end upgrade should be simulated before trying it
on production. The project version remains v0.16.0 because PR #18 is Draft.

Offline regression tests:

```bash
bash tests/test-smite-backhaul-packaging.sh
bash tests/test-smite-backhaul-management.sh
```

Next: scrutinize exact v0.7.2 control/data bind syntax, test the candidate
against the *existing* patched U-OPTI overlays on IR/KH (without modifying
them), then implement separately reviewed atomic activation and live rollback.

**Updater rollback hardening:** The fixed older updater also omitted the
Standard FRP helper files from its backup list. This branch now adds both
`smite-frp-xhttp.sh` and `smite-frp-wizard.sh` to the backup snapshot,
uses missing-file markers on upgrades from legacy installations, and verifies
its expected backup file count dynamically. On rollback, these originals are
restored or newly introduced copies are removed. No live FRP paths change.
