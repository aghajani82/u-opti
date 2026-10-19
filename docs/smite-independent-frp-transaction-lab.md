# Independent FRP: two-role binary and interrupted-install recovery (PR draft)

**Security boundary:** this is a disposable GitHub pull-request filesystem
rehearsal, NOT a usable VPS installer. Real-host Install and Rollback stay
blocked. Never copy a lab marker to a production server.

## Independent FRP preparation

- Version pinned: upstream fatedier/frp **v0.71.0** Linux AMD64/ARM64.
  Each upstream archive has a fixed reviewed SHA-256. Preparation validates
  the tarball, archive member paths/types and architecture-specific 64-bit
  ELF headers for BOTH `frpc` and `frps`.
- One private candidate contains the original verified archive,
  `frpc.bin`, `frps.bin`, both SHA-256 values, a candidate engine manifest
  and a candidate Compose read-only-mount plan. Verify re-extracts both
  binaries from the approved archive and compares exact bytes, not merely
  editable local checksum files.
- Existing Backhaul/GOST/Rathole/Chisel declarations are preserved verbatim.
  No Backhaul installer is called, and FRP does not request a transport,
  forwarded port, Xray inbound or XHTTP path. Those are Panel tunnel
  parameters selected **later**, not an engine-install prerequisite.
- Smite managed `frp: ready` requires the exact enrolled root-owned
  `/usr/local/bin/frpc` AND `/usr/local/bin/frps`, each executable,
  non-symlink and matching its SHA. Older client-only metadata reports
  `unavailable`; never accidentally ready.

## Interrupted-install CI transaction

The new `smite-managed-frp-transaction.py` requires the existing
root-private, explicitly marked GitHub PR lab under `RUNNER_TEMP`.
It cannot operate on `/opt/smite-node` or other live host directories.

Before any file change, it verifies managed strict Node, no FRP enrollment,
no active persisted tunnels, immutable prior Compose/manifest and original
Node identity digest. It creates a private journal, then in order:

1. Stage `frpc`; if interrupted, recover just this client file
2. Stage `frps`; the server binary must be present too
3. Add exact read-only mounts to the **lab-only** Compose
4. Enroll both hashes in the one managed registry **last**

At every interruption point (after journal, frpc, frps, Compose and
manifest), rollback validates all current bytes and the protected Node
identity BEFORE reverting. Any out-of-band change causes HOLD with the
journal preserved; never overwrite edits blindly. A separate shared
exclusive `.smite-engine-transaction.lock` prevents Backhaul and FRP
operators racing on the common registry/Compose.

The official-archive CI rehearsal also activates and reverts a
disposable FRP candidate, then injects a failure after frpc is staged.
These drills execute **no FRP process**, publish no 443 route, run no
Docker, and verify no tunnels. They are not runtime HMAC, live 443, VPS
snapshot or operational rollback approvals.

## Still required before a single clean VPS Rebuild

- All CI checks green for both draft branches on matching pinned commits
- Signed Smite Node API `ready` / `not-installed` after an actual
  isolated Docker Compose recreate with both mounted FRP executables
- Container-image and image/architecture parity, admin-login/MFA drill
- A reviewed production installer and host-safe journal/recovery executor
- Human-tested provider snapshots and separate console rescue for IR/KH
- A disposable two-host FRP-only test, then Backhaul and FRP coexistence
  test, correct single TLS 443 entry, dynamic Xray path/port set via Panel
- Explicit operator approval for the final one-time IR/KH Rebuild and
  any main/stable merge or release

Current U-OPTI PR #38 and Smite PR #15 remain Draft. The legacy 0.16.7
hosts and their working tunnels are not part of these CI experiments.
