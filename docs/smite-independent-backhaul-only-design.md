# Phase 1 / Backhaul-only — independent engine install contract (DRAFT)

> Review-only design. This document does **not** install Backhaul, publish an
> image, restart Docker/Nginx, change IR/KH, enable firewall rules, or approve
> production deployment. U-OPTI Stable and Smite main are unchanged.

## Operator experience (two simple steps; no repeat of Smite install)

**1. U-OPTI > Smite Management > Engines > Backhaul > Install**

Perform the same independent local install once on **IR**, once on **KH**.
Each server is configured locally; no SSH transfer or FRP bootstrap is
required. Smite Panel/Nodes were installed once in the previous Core stage;
the Backhaul installer must NOT re-run Core or ask for a tunnel port, Xray
path, token, domain, 3x-UI inbound, or other engine installation.

The wizard shows only:
- Current Backhaul status: Not installed / Ready / Unavailable.
- One choice: Review installation -> Confirm, with a brief rollback summary.
- Existing ready installations: Verify / Repair / Remove (never overwrite
  silently). Other engines are not affected.

**2. Smite Panel > Create Tunnel > Backhaul**

Choose paired IR + KH, see their signed readiness state, then configure the
real 3x-UI inbound port/path. Smite stores the tunnel and dispatches signed
commands only after the selected engine is ready on *both* Nodes. No silent
FRP fallback, default inbound 8080, or automatic Backhaul tunnel creation
during installation.

## Ownership / trust boundaries

- **U-OPTI owns software lifecycle:** official version-pinned Backhaul
  artifact acquisition, independent SHA256 allow-list per CPU architecture,
  immutable root-owned local binary, Compose read-only bind mount,
  installation verification, repair, uninstall and exact rollback.
- **Smite owns tunnel lifecycle:** signed per-Node engine inventory, approved
  Node identity and TLS control transport, tunnel spec, start/stop/reapply,
  and visible tunnel state. The engine installer never writes Smite's
  tunnel database or starts an unrelated tunnel.
- **Node inventory is not a Docker binary scan:** the managed Node checks
  `/etc/smite-node/engine-state/engines.json` (root-owned 0700 directory,
  0600 file) and verifies the pinned binary at
  `/usr/local/bin/backhaul` is regular, root-owned, executable,
  non-group-writable, and matches the registered SHA256. Schema remains
  `{"schema":1,"engines":{"backhaul":{"sha256":"<sha256>"}}}`.
- No manifest enrollment occurs before the binary is trusted and mounted.
  A missing, mismatched or malformed artifact remains `not-installed`
  or `unavailable`; Apply is rejected with HTTP 409. Never silently
  mark an installed engine `ready`.
- The trial must use immutable reviewed Smite Panel/Node images and restore
  original Compose and manifest when rollback is requested. The installer
  must not require host FRP, a running FRP daemon, private-network overlay,
  or a pre-existing Backhaul tunnel. Stable's old FRP paths are untouched.

## Fail-closed installation transaction (to implement)

1. **Preflight without mutation:** explicitly verify clean-RC managed
   profile, valid Node installation, supported architecture, official
   artifact checksum from a separately reviewed pin, host paths,
   available disk, Compose merge and current backup state. No remote
   "latest" binary and no build-time trust of an unverified download.
2. **Prepare:** stage root-owned versioned host artifacts privately.
   Safely journal SHA256 + ownership/modes for existing Compose/manifest.
   Refuse symlinks, concurrent installers, mismatched existing binaries,
   unsafe permissions and silent overwrites.
3. **Activate locally with consent:** add only this Backhaul read-only
   bind mount to the specific Smite Node service; run
   `docker compose config` and perform one controlled Node recreation,
   **not a Smite reinstall**. Do not change Smite Panel, other engine
   bindings, signed pairing keys or replay-state volumes.
4. **Enroll only after verification:** atomically write a new manifest
   containing the preserved declarations plus Backhaul SHA256. Inspect
   Node's actual engine inventory locally, and after signed pairing
   require a signed Panel inventory response. No standalone public
   socket is opened by installing the binary.
5. **Rollback:** on any failed step, undo only Backhaul's new manifest
   entry/mount/artifact, restore the exact previous Compose and state,
   recreate Node only when required, retain pairing and replay database,
   and report success/failure without revealing secrets.

## Data transport: 80/443 only

- The initial transport candidate is **Backhaul WebSocket through the
  existing SNI/TLS Nginx 443 gateway**, with strict exact-path routing
  to loopback services. Reuse the isolated existing Backhaul WS
  transport/Nginx evidence; never assume raw Backhaul TCP/3080 can share
  public 443 without an explicit compatible routing layer.
- No additional public 3080, 7000, 18081 or Xray inbound listeners
  should be opened as part of the engine install. The tunnel wizard
  may only activate a verified transport after checking Nginx,
  TLS hostname, route ownership, port collision and loopback target.
- The binary being `ready` proves only install integrity, **not**
  that WS over 443 works end to end.

## Backhaul-Only acceptance gates

- Empty Core: Smite IR/KH paired, Backhaul/FRP/GOST/Rathole/Chisel all
  not-installed and no motor automatically starts.
- Backhaul installed independently on IR and KH; signed inventory shows
  Backhaul ready on both while FRP remains not-installed on both.
- A Backhaul Apply before install, unsigned Apply, malicious manifest,
  binary tamper, invalid Node pairing, wrong selected KH and replay
  all fail closed without starting any engine.
- Test Backhaul's **real** control and data via the **existing HTTPS 443
  gateway** with an actual 3x-UI inbound and flexible (not hard-coded)
  port/path, including a reboot and tunnel reconnect on disposable hosts.
- Uninstall/reinstall or rollback one engine without changing signed
  Node identity, Smite Core, saved tunnel specs or any other engine;
  demonstrate repair and no unnecessary repeated installation.
- Review published-image provenance, backup/restore, restricted network
  exposure, least privileges and operator-friendly Persian/English
  errors before any version promotion.

**HOLD:** No verified per-arch Backhaul release digest, no independent
per-engine installer implementation, no real signed dual-Node inventory
after installation, no 443 data-flow acceptance, no IR/KH VPS trial,
and no explicit release approval yet. Both PRs must remain Draft.
