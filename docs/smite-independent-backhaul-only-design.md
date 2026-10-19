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

## Implemented now: verified package preparation only

- `modules/smite-managed-backhaul.py` prepares an independent
  root-private offline candidate from the **official Backhaul v0.7.2**
  AMD64/ARM64 archive. Both compressed-release SHA256 values are pinned
  to the matching GitHub release asset digests. A mismatched archive,
  unsafe tar member, symlink, unexpected ELF or invalid managed Node
  fails closed before creating any candidate.
- The candidate contains a separately SHA256-checked Linux Backhaul
  binary, an exact read-only Compose volume override and a proposed
  `engines.json` that retains the declarations of all other engines.
  The live `./config/engine-state` and existing Node Compose are not
  changed; no Node is started or restarted.
- `tests/test-smite-managed-backhaul.py` covers the no-mutation
  contract, permissions, hash tampering, path safety, independent engine
  preservation and Clean RC admission. The separate PR-only GitHub
  workflow `managed-backhaul-official-artifact` also downloads the
  actual pinned AMD64 asset, checks the executable version and validates
  a Compose merge against the exact reviewed Smite Node source.
- This preparation stage is **not** the installation menu: there is no
  active bind mount, published port, engine enrollment, signed remote
  inventory or operational rollback yet. None of the actions required
  for an actual activation are implied by a green preparation test.

## New milestone: transaction and recovery rehearsal (PR CI only)

- `modules/smite-managed-backhaul-transaction.py` takes a previously
  authenticated Backhaul candidate and rehearses activation exclusively
  inside a **marked, private directory under the GitHub Runner's temporary
  folder**. It explicitly refuses live servers, regular shell execution,
  non-PR contexts, untrusted candidates, tampered source files or
  unsupported Core profiles.
- Its journal contains the original Compose and registry bytes, their
  SHA256, file modes, and expected Backhaul outputs. The trial copies the
  binary, inserts a scoped read-only Compose mount and writes the registry
  **last**. The simulator starts no Docker service and never touches Nginx,
  FRP, Xray, Smite Panel, tunnels or public ports.
- Crash-injection tests exercise failures immediately after binary,
  Compose or registry operations. The rollback refuses out-of-band edits
  and restores the exact prior Compose bytes/mode and other engine
  declarations. Fresh registry/binary state disappears again on rollback.
- A separate real-artifact CI test feeds the official SHA256-checked v0.7.2
  AMD64 release through that temporary transaction, parses the resulting
  real Smite Compose with Docker Compose, and runs rollback. It does
  **not** recreate a container or prove the binary is active in a Node.
- This **is not yet the production installer**: the exact host transaction,
  protection against concurrent updates, runtime engine-version verification
  in Node, signed status checks, container lifecycle restart and real
  443 transport remain blocked pending separate acceptance.

## Latest milestone: pinned Smite Node inventory, isolated Docker runtime

- The PR-only `tests/test-smite-managed-backhaul-node-runtime.sh` executes
  the **exact reviewed Smite Node inventory Python module and Settings**
  inside the pinned Smite Node Docker image. The test deliberately uses
  `--network none`, `--read-only`, `--cap-drop ALL`, no exposed ports,
  an isolated temporary registry, and a read-only mount of the official
  Backhaul v0.7.2 ELF. It never starts the Smite Node API daemon,
  an engine service, or a real tunnel.
- **Before enrollment:** the embedded image Backhaul/FRP binaries do *not*
  cause `ready`; Backhaul is `not-installed` and Apply admission fails.
- **After the isolated transaction:** Backhaul is `ready`, while
  FRP/GOST/Rathole/Chisel stay independently `not-installed`. Re-creating
  the isolated Docker process gives the same signed-inventory **data**
  result. The runtime test does *not* itself send an HMAC API request;
  the existing signed Agent and Panel tests cover authentication separately.
- **Tampered executable:** a differing executable mounted in place of the
  registered Backhaul SHA returns `unavailable` and rejects Apply.
  **Malformed manifest:** fails closed rather than fabricating `ready`.
  **After rollback:** the manifest disappears and Backhaul is
  `not-installed` again even though the original image bundles binaries.
- Remaining acceptance: use actual installer-produced Compose to
  **recreate a live Node in a dedicated disposable host**, verify its
  HMAC-signed `/api/agent/engines` endpoint and HTTP 409 Apply,
  prove restored tunnel/service behavior after restart, then test the
  Backhaul-only 443 data path. None of those production activation gates
  has been passed by the image-level inventory test.

## Current milestone: real isolated Node service and signed Agent API

- A fresh throwaway Smite Node process is now started via the pinned Node
  Docker image plus **the exact reviewed Smite source**. The process binds
  only to **127.0.0.1 inside a Docker `--network none` namespace**.
  Docker publishes no ports, drops all Linux capabilities, has a read-only
  filesystem, and cannot contact Panel/IR/KH. The Node's Panel registration
  remains `paused`; its Agent runs with `strict` HMAC and persistent replay
  rejection.
- The real `GET /api/agent/engines` endpoint denies unsigned and
  incorrectly signed access (HTTP 401), accepts a valid signature (HTTP
  200), and rejects reused signatures across **actual Docker restarts**.
  Invalid `POST /api/agent/tunnels/apply` for an unready engine returns
  HTTP 409; no successful Apply or tunnel engine is started.
- The same Node service is tested **before independent Backhaul enrollment,
  after installing its official SHA-verified v0.7.2 binary, and after
  exact rollback**. It reports `not-installed → ready → not-installed`
  while FRP remains separately `not-installed` throughout.
- The Smite experimental branch also now guards **persisted tunnel restore**
  and internal adapter Apply in managed mode; restart cannot silently
  bypass inventory admission. Unit tests verify fail-closed restore and
  unchanged legacy behavior. Neither GitHub PR is merged.
- Still NOT established: a general-purpose production installer, live
  Compose recreation on an IR/KH VPS, an authorized public TLS/443
  datapath, tunnel throughput/latency, and a real-server crash recovery
  drill. No host activation or U-OPTI Stable/main merge is authorized.

## New milestone: simple U-OPTI Engines menu and isolated installation controller

- `U-OPTI > Docker Management > Smite Management > Independent Engines
  (Backhaul review)` is now separate from **Advanced & Legacy Tools**.
  The visible operator flow is concise: Backhaul Status, Review, Install.
  The **host Install button remains HOLD**, with a clear explanation.
  Existing legacy FRP/Backhaul menus keep their original option numbers.
- `modules/smite-managed-backhaul-control.py` provides read-only local
  `status` and `review`, checks the strict managed Smite Core and its
  configuration, and does **not** infer Ready from bundled executables.
  States are `NOT_INSTALLED`, `UNAVAILABLE`, or
  `ENROLLED_UNVERIFIED`; the last explicitly requires a signed Node
  inventory request before anyone can claim `ready`.
- The `install` and `rollback` actions are **available only to the
  disposable GitHub pull-request lab**, never to live IR/KH. Both operations
  use the existing manifest-verified transaction/rollback and an exclusive
  transaction lock. Duplicate install, protected-file drift, unknown
  Compose layout, untrusted candidates and attempts outside the CI lab
  fail closed. Installation involves NO tunnel port, path, FRP control
  connection, or repeated Smite Core deployment.
- The installer and updater include the independent menu and controller
  modules; CI checks both package manifests. A complete official
  Backhaul v0.7.2 CI round now flows through the new controller and
  separately validates Smite Node HMAC behavior before, during and after
  the lab installation.
- **Release gate:** A safe **real-host** transaction, signed post-restart
  health verification, active tunnel preservation and robust rollback
  following interrupted host Docker recreation have not been implemented
  or approved. Host install remains disabled, with no changes to Stable.

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

**HOLD:** Official release preparation and **CI-only** filesystem
transaction/rollback are verified. A real-host installer, Node runtime
activation and signed IR/KH inventory, actual Backhaul-over-443 data-flow
acceptance, VPS trial and release approval do **not** exist yet. Both PRs
must remain Draft; no real server commands are authorized.
