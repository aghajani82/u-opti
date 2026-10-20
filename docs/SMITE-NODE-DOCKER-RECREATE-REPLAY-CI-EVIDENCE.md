# Real isolated Docker Node persistence, replay-loss and mount precedence — CI evidence

**Date:** 2026-10-20  
**One integration Draft:** [U-OPTI #48](https://github.com/aghajani82/u-opti/pull/48)  
**Tracker:** [Issue #47](https://github.com/aghajani82/u-opti/issues/47)  
**CI source commit:** `d65313b2b6c77fd37a2052ae792eb4082bd3f7d0`  
**Actual run:** [GitHub Actions 39404517558](https://github.com/aghajani82/u-opti/actions/runs/39404517558) — **completed/success, 16 of 16 jobs PASS**.

## What changed (actual runtime exercise, not just static claims)

Updated the **existing** `tests/test-smite-stage24-compose-runtime.sh` and its
existing `node-compose-hmac-rollback-isolated` CI job; no new independent
stage PR or new operator-facing wizard.

The test previously built an older Smite Node source, whose strict replay
bootstrap lifecycle was not equivalent to the newest one-time enrollment.
The Docker job now explicitly checks out reviewed Smite code
`9201722336b05e833408a0a352cfee99465da2cb`
—the same code in the earlier signed FastAPI and Stage15 reviewed offline
Panel/Node image build. The test **builds** an actual Node image locally in a
disposable GitHub runner; no registry publish, host networking, production
port, live Panel or IR/KH actions are involved.

A real explicit, operator-gated Smite `app.replay_enrollment` invocation
runs **before** starting strict Node in a one-shot Docker process with
`--network none`, all capabilities dropped and just two synthetic host
directories mounted. Using those actual host paths ensures its independent
private `replay-enrollment.json` records the **host replay DB path**
required by U-OPTI's read-only KH admission logic—not an incompatible
container-only path. CI verifies marker and SQLite permissions 0600, tests
the real U-OPTI private mount/DB admission, then proceeds.

## Verified real Docker sequence

1. Run the existing U-OPTI clean-KH installer file/layout transformations
   against a temporary directory. If installer code attempts host FRP
   injection, **HOLD**. Keep the base Compose file's SHA unchanged.
2. Build real reviewed Smite Node image locally from exact source SHA.
   Explicitly enroll a synthetic paired identity once and create separate
   private marker and Replay SQLite. Static admission validates the
   **real** data while no Node process is using SQLite.
3. Start **paused + strict** Node Compose under CI `network_mode: none`:
   without mounted pairing credentials, signed API remains unavailable
   with 503.
4. Recreate **signed + strict** Node Compose. Inspect Docker's actual
   `Mounts` via `docker inspect`: the existing
   `node-data:/var/lib/smite-node` parent volume is still a **named
   volume**, the nested `/var/lib/smite-node/auth` is a separate RW
   bind mount, and `/run/smite-node-identity` is a RO bind mount.
   The signed status request succeeds once, identical nonce replay is
   rejected (401), an unsigned request gets 401 and the secret path
   cannot be written from the container.
5. Recreate the container in paused mode and then back to signed mode
   **without reinstalling the Node image or changing host storage**.
   Paused status remains 503; signed status refuses the **old nonce**
   and accepts a new nonce. Identity and independent marker SHA remain
   unchanged and the original SQLite nonce history persists.
6. In this **disposable test only**, stop the signed container and move
   the temporary Replay DB aside; **retain** identity and enrollment
   marker. Recreate the signed container. Its signed request now
   returns **503**; Docker/Node do not create a replacement database.
   Explicitly attempting one-time enrollment again is rejected by the
   already-present marker. Neither signed traffic nor the enrollment
   tool can silently reset replay protection.

The test retains its previous engine-inventory assertions that bundled
FRP/Backhaul binaries are **not** automatically enrolled or startable.
No real tunnel, Nginx ingress, public port or VPS traffic was opened.

## Real evidence and boundaries

- The run contains 16 successful U-OPTI CI jobs. The main new proof is
  the disposable `node-compose-hmac-rollback-isolated` job. Existing
  real-Nginx/443, FastAPI replay, first-install crash recovery and
  FRP/Backhaul regression jobs still passed.
- This validates **container deletion/recreation on a single CI runner**
  and actual Docker nested mount precedence with the reviewed source.
  It is NOT an actual cloud-host reboot/power-loss or physical storage
  persistence test.
- Host identity, marker and Replay DB were synthetic CI secrets/data.
  The live default Smite `v0.1.7` installation and both actual server
  roles remain **unchanged**.
- The separate offline read-only mount admission rejects active WAL,
  journal files or a WAL-mode store; the active Node runtime can write
  normal SQLite transactions, but only the offline preflight inspects
  quiescent files.
- A same-identity replay database recovered from a **stale snapshot**
  can still omit already-used nonces even if all schema, mount and
  identity checks pass. A trusted-time quarantine covering the signer
  acceptance window or coordinated authenticated key rotation still
  requires explicit design, negative tests and operator approval.
- No trusted signed image registry distribution, coordinated live Panel
  replay recovery, GHCR release, migration from stable `v0.1.7` or
  independent Backhaul workflow has been completed.

## What to do next

1. **Implement/review a clearly bounded replay restore safety policy**
   for older snapshots and independent loss of identity/replay state;
   refuse auto-reinitialization and avoid unsafe automatic key rotation.
   Ground the quarantine interval in the actual reviewed Smite HMAC
   timestamp validation rather than an invented fixed duration.
2. Consolidate **Backhaul Standard without FRP prerequisites**, while
   retaining dynamic inbound mapping after KH Sanaei setup.
3. Finish one simple IR→KH operator flow and a coordinated immutable
   release/source-image manifest.
4. Only with separate operator approval, test actual snapshot-backed
   disposable VPS reboot, downtime, restore and rollback before any
   release, merge or production activation.

**Gates:** `INSTALL_ALLOWED=NO` · `ACTIVATION_GATE=HOLD` ·
`MAIN_MERGE=NO` · `RELEASE_PUBLISH=NO` ·
`IR_KH_UNCHANGED=YES`.
