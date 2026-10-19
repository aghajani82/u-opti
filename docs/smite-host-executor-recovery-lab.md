# Stage 6: disposable Host Executor / crash recovery lab (NOT DEPLOYABLE)

2026-10-19 · Built on U-OPTI PR #38 HEAD `2c1e6add`.

This change deliberately lives under `tests/lab/`, not in `modules/`
or the official U-OPTI installer inventory. Import only from the isolated
unit test. There is **no CLI**, Docker invocation, network call, SSH, daemon
restart, firewall edit or installation activation. Real VPS status is HOLD.

## Contract simulated

`tests/lab/smite_host_executor.py` refuses every working directory outside
a private disposable `/tmp/uopti-engine-txn-lab-*` root with a dedicated
`.LAB_ONLY` marker and a same-user, mode-0700 directory. Never point it at
a real Smite Node. The tests create the complete fake layout themselves.

1. Require the existing read-only Plan report to remain preview-only,
   with `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`, exact binary digests,
   candidate manifest hash and original Compose hash.
2. Acquire one nonblocking `flock` for both engines.
3. Read and record original Compose, manifest and protected identity/replay/
   tunnels/other-engine hashes. Journal previous bytes and modes plus
   expected new hashes to private JSON; `fsync` journal and directory first.
4. Write only the chosen engine's synthetic files and its **own**
   disposable Compose override, then a merged engine manifest; `fsync`
   each atomic rename. Never rewrite the other engine's binaries/override.
5. Inject crash before copy, between FRP binaries, after Compose/manifest,
   during simulated restart and after simulated signed verification.
6. On recovery, require every mutable path to equal **exactly** its recorded
   prior or expected resulting hash before restoring. External mutation
   yields HOLD and leaves evidence unchanged. Restore prior bytes and modes.
7. A test-only signed/replay oracle models runtime verification for new
   and prior states. It **does not** check a real HMAC Node endpoint.
8. Archive a completed audit journal before a second-engine transaction;
   a pending or conflicting journal always blocks further mutation.

Covered: independent Backhaul-only, FRP-only, coexistence, shared-lock
contention, crash checkpoints, exact rollback, idempotent recovery,
unrecognized symlinks, external edits, prior-health failure, missing
signed proof, and preserving the other engine.

## Not yet passed

- This lab **does not** prove that real official archives were verified
  at the point of write: prior Host Plan verification is separate.
- This lab **does not** perform a Docker Node recreate or test real signed
  Node HTTP/TLS, pairing, replay DB, public-port exposure or live tunnels.
- This lab **does not** prove atomicity on real filesystems or survive real
  power loss on VPS; it models process interruption with fault injection.
- This lab **does not** approve snapshots, console access, architecture,
  permission boundaries of actual production directories or operational
  host installation.

Next gate: independent review of production-specific path ownership,
openat/no-follow/dirfd protections, durable journal identity, replay-safe
signed Node restart, rollback of an already-installed engine, conflict-safe
journals after power loss, and two-host disposable VPS admission with
actual restore-capable snapshots. Only then decide whether to develop
a separately protected production executor. Never expose this test
laboratory through the U-OPTI install menu.

**Main, release, IR and KH must remain unchanged.**
