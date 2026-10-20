# Backhaul independence closeout — legacy prepare fix vs real host installer

**2026-10-20 | Existing [Draft PR #48](https://github.com/aghajani82/u-opti/pull/48) | [Issue #47](https://github.com/aghajani82/u-opti/issues/47)**

**Status: BACKHAUL CANDIDATE PREPARATION DECOUPLED / LIVE INSTALL STILL HOLD.**

## Root cause and actual change

The U-OPTI repository contains TWO historically separate Backhaul tracks:

- **Legacy Standard overlay preparation** in
  `modules/smite-backhaul-management.sh`: previously required a local FRP
  server listener on `127.0.0.1:7000` on IR and a fake fixed Sanaei Xray
  listener `127.0.0.1:56053` on KH, even though the operation **only
  staged** files. It also rendered a dangerous example `ir-xhttp.conf`
  that assumed a KH inbound `56053`, `/56053/www`, and a particular KH
  domain without any operator selection.
- **Managed independent engine** in
  `modules/smite-managed-backhaul*.py` + `smite-managed-backhaul-menu.sh`:
  already prepares a pinned **Backhaul v0.7.2** artifact without installing
  FRP and with `FRP_DEPENDENCY=NONE`. It is a **CI-tested, host-read-only,
  intentionally unactivated** candidate, not a released on-host installer.
  Its security baseline is a reviewed managed/strict Smite Core; this does
  **not** require the FRP engine to be present.

### Changes in this closeout commit

1. In the **legacy offline preflight only**, remove the check requiring
   `127.0.0.1:7000` FRP and the check requiring a KH Xray listener on
   `127.0.0.1:56053`. IR only preflights the Backhaul candidate control
   port `3080`; KH retains conservative `13080` bridge reservation in
   the *old* preview. Do not modify any real running FRP, Nginx, Smite or
   Xray service.
2. Stop rendering `ir-xhttp.conf` with invented live-looking
   `56053`/`/56053/www`/KH-domain values. Instead stage **only**
   `IR-XHTTP-NOT-CONFIGURED.txt`. This is deliberately NOT an Nginx
   snippet and says to select the **actual** KH Sanaei inbound port,
   path and upstream hostname after Core and Sanaei installation.
3. Update the ordinary Backhaul wizard *overview* to display this
   deferred dynamic-port/path flow instead of telling beginners
   that `56053` and `/56053/www` are the required values.
4. Extend existing regression tests
   `tests/test-smite-backhaul-management.sh` to mock **NO FRP listener
   and NO Xray inbound** for BOTH roles, still pass the independent
   preparation/integrity tests, assert there is no fabricated
   `ir-xhttp.conf`, and leave existing live process fixtures alone.
   `tests/test-smite-tunnel-wizard.sh` requires no misleading fixed
   `56053` in the beginner overview and keeps its dynamic
   real-installed-profile test.

## Frozen five-step operator flow

1. Install Smite Core/gateway on **IR**, independent of tunnel engine.
2. Install Smite Core/gateway on **KH**, independent of tunnel engine.
3. Install Sanaei/3x-ui on KH; create its actual chosen XHTTP inbound.
4. In a **separate** route menu enter/inspect the selected inbound
   loopback port, path and hostname. No fixed `56053`; no port prompt
   during engine binary installation.
5. Choose Backhaul, FRP or both **independently**, pair/authenticate,
   apply and test tunnel only after explicit production admission.
   The shared Node Compose/manifest requires a transaction lock and
   must preserve the other engine and signed/replay storage.

The current work completes the **safe preview/UX decoupling**, not Step 5
production activation. The old legacy path is NOT to be promoted as a
general host installer: it still requires old Docker overlays and a
compatible running Smite Node. The managed path and strict signed
restore guarantees remain under review.

## 2026-10-20 — managed Backhaul **FRP coexistence** transaction bug fixed

In addition to the earlier legacy FRP/56053 prepare decoupling, this
same Draft #48 now fixes a **real CI-discovered bug** in the *managed*
Backhaul-only install/rollback rehearsal.

**Cause:** `smite-managed-backhaul-transaction.py` unconditionally
called `binary.parent.mkdir(parents=True, exist_ok=False)` on the
shared `installed` engine parent. If FRP had already created
`installed/frp/frpc` and `installed/frp/frps`, this raised
`FileExistsError`, leaving an incomplete Backhaul recovery journal.
It prevented the promised optional FRP + Backhaul coexistence.

**Fix:** reuse an existing, owner-validated **private 0700** shared engine
directory, or create it only when absent. Never chmod, delete or
overwrite the existing FRP sibling. Exact Backhaul rollback restores
the original Compose, engine registry and binary placement, retaining
both FRP executables untouched.

`smite-managed-backhaul.py` now reports `FRP_INSTALLED=YES` when
FRP is actually in the Node's existing engine manifest, instead of
always incorrectly saying NO. The stage verifier cross-checks this
field against the proposed manifest. It also rejects Backhaul
preparation on a **partial or untrusted FRP baseline**: orphan/writable/
missing FRP binds, client-only FRP metadata or checksum-mismatched
`frpc`/`frps` are HOLD. FRP absence is **fully supported**.

**Regression:** Existing
`tests/test-smite-managed-backhaul-transaction.py` creates two
simulated FRP role executables, a trusted dual-role inventory and the
corresponding read-only Compose binds, then stages/installs/rolls back
Backhaul, verifying **byte-exact FRP and Compose/registry preservation**
and independently required private permissions. Negative cases reject
writable/missing FRP mounts, a corrupted FRP binary and orphan mounts.
The first CI failures exposed the shared-parent bug and a test fixture
with wrong parent permissions; both were corrected without weakening
the security check.

**Verified latest code SHA:** `285153b0400aba1e1b6a241a1b733b9369e213b8`.
[GitHub Actions 39423755202](https://github.com/aghajani82/u-opti/actions/runs/39423755202)
**completed/success, all 16/16 jobs PASS**.

**Scope:** true dual-engine **CI filesystem transaction and exact
rollback** are now proven at a deeper level. A real-host Backhaul
executor, signed restart proof, actual dynamic XHTTP forwarding and
cross-VPS test have **not been released**. This code path still
operates ONLY in the guarded disposable GitHub PR runner and does not
change existing VPS deployments.

## 2026-10-20 — read-only **host plan** for Backhaul beside verified local FRP

**Small real defect:** `smite-managed-engine-host-admission.py`
previously reported a correctly enrolled but signed-runtime-unverified
other engine as a *hard local preflight failure*. Additionally,
`smite-managed-engine-host-plan.py` hardcoded
`OTHER_ENGINE=NOT_INSTALLED`. This wrongly prevented the operator from
preparing an **inert host transaction plan** for Backhaul if FRP was
already present—even though the already tested isolated Backhaul
transaction can preserve both FRP binaries and its registry.

**Fixed without enabling host actions:**

1. When the target Backhaul is absent and local FRP inspection confirms
   its existing readonly mounts and both SHA-pinned `frpc`/`frps`
   files, host admission now returns
   `LOCAL_PREFLIGHT=PASS_LOCAL_ONLY_INCOMPLETE`, while retaining
   `REASON=OTHER_ENGINE_SIGNED_STATUS_REQUIRED`,
   `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`.
2. The **read-only plan generator** can accept this exact combination
   (not an arbitrary spoofed status) and rechecks the official Backhaul
   archive, stage contents, original Compose hash and old engine manifest.
   Result is at most `STAGE_ADMISSION=VERIFIED_PREVIEW_ONLY`,
   `OTHER_ENGINE_LOCAL_STATE=ENROLLED_UNVERIFIED`,
   `OTHER_ENGINE_SIGNED_RUNTIME=UNVERIFIED`, with a distinct
   signed-runtime/host-executor HOLD reason.
3. Malformed or tampered FRP, a missing readonly binary mount,
   mismatched digest, unknown Core layout, a lost stage or a forged
   preflight reason stays HOLD. **Nothing starts or restarts**, no
   `docker compose` action runs, no user port is requested, and the
   prior FRP files, Compose and manifest are unmodified.

The new regression in
`tests/test-smite-managed-engine-host-plan.py` stages a synthetic
verified two-binary FRP installation, runs the **real** read-only
Backhaul candidate/plan against it, proves prior bytes unchanged and
tests forged preflight plus binary corruption. The corresponding
`tests/test-smite-managed-engine-host-admission.py` verifies the
signed-runtime HOLD is not silently lifted.

**Verified exact code HEAD:** `2bad4181f0d31203272f1aff48378ca6c532cef2`;
[GitHub Actions run 39426442327](https://github.com/aghajani82/u-opti/actions/runs/39426442327)
**completed/success, 16/16 CI jobs PASS**. The first version of the
new test fixture used literal escaped newlines; that fixture was
corrected, not the admission security logic.

**Boundary:** We can now **prepare and audit** Backhaul safely both with
FRP absent and with FRP locally verified, but this is NOT a production
installer. The other engine's *signed Node runtime and restart* is
unproven; no approved host installation/rollback runner or cloud
snapshot evidence exists. `INSTALL_ALLOWED=NO` remains mandatory.

## 2026-10-20 — three-point signed FRP lifecycle proof required in CI

The Backhaul **PR-only lifecycle** `modules/smite-managed-backhaul-lifecycle.py`
previously accepted a signed Backhaul health callback after a simulated
restart and a signed "Backhaul absent" callback after rollback, but did
**not** independently require signed FRP inventory proof when FRP was
already installed. This allowed a misleading result about the *other*
engine when adding Backhaul, despite exact byte-level rollback tests.

Now, when FRP is already present in the validated engine manifest:

1. **Before** any Backhaul mutation, a separate
   `check_other(root, "before")` callback is mandatory; missing/false
   or raised proof **HOLDs before installation**.
2. **After** Backhaul is staged and the caller's signed restart probe
   accepts it, `check_other(root, "with-backhaul")` must also pass;
   otherwise the ordinary compensating rollback runs.
3. **After** exact rollback and independent signed proof that Backhaul
   is absent again, `check_other(root, "after-rollback")` must pass;
   failure is a distinct hard HOLD, never a successful restoration.
   Returning a result reports all three phases only when they pass.

When **FRP is absent**, the old Backhaul-only path remains valid, with
no artificial FRP prerequisite or callback. Signed proof for an existing
FRP is a *separate* callback, not simply a local SHA or Docker running
flag.

The regression in `tests/test-smite-managed-backhaul-lifecycle.py`
models existing dual-role FRP files/manifest/RO mounts, verifies
preservation and ordered callback calls, then injects missing/false
prior, with-Backhaul and post-rollback proofs. This uses **synthetic
callback results and temporary filesystem**, not a production signed
Panel/Node verification or permission to deploy.

**Exact code commit** `057e609b0334395edf56f9e0a670b7ec12e65084`:
[GitHub CI 39429251440](https://github.com/aghajani82/u-opti/actions/runs/39429251440)
(check job results before treating this as full CI PASS).
No new PR, host executor, Docker restart or active tunnel was added.

**Next release gate remains:** replace the CI callback with an
operator-approved real TLS/HMAC/replay-aware **before / with Backhaul /
after rollback** probe against the actual reviewed Node and existing
FRP, with immutable image identity and authorized snapshot recovery.
The host install/rollback actions remain deliberately **disabled**.

## 2026-10-20 — REAL isolated signed FRP+Backhaul three-point Docker CI (PASS)

**Release-candidate safety gain in the existing U-OPTI Draft #48; NO production executor enabled.**

Previously the CI-only `smite-managed-backhaul-lifecycle.py` required
`check_other(root,phase)` at 3 checkpoints for existing FRP but its
*official-artifact Docker runner* supplied only the Backhaul callbacks.
The new integration **actually wires the additional callbacks** to the
already reviewed Smite signed Agent API running in isolated Docker
Compose, rather than accepting three synthetic boolean results.

In the existing `managed-backhaul-official-artifact` GitHub PR job:

1. The original **official Backhaul v0.7.2** test still stages,
   installs, tests the signed Node API and compensates a failed restart
   with exact rollback; no FRP binary is required in this first run.
2. CI downloads **official FRP v0.71.0**, validates its exact pinned
   SHA256 and extracts ONLY `frpc` and `frps` into the disposable
   root-owned 0700 lab. An explicit **FRP-only preexisting inventory**
   records their real SHA256 and read-only Docker mounts; neither
   engine is started. This test-only setup is not a host installer.
3. A second official Backhaul candidate is prepared atop that FRP
   inventory. The existing lifecycle automatically installs and
   **always rolls back** Backhaul during the rehearsal. FRP is probed
   at BEFORE, WITH-BACKHAUL, AFTER-ROLLBACK by launching the real
   checked-in `test-smite-managed-backhaul-signed-api.sh` at the
   appropriate phase, including a real container force-recreation.
4. `tests/smite-managed-backhaul-compose-fixture.py` now has an
   *explicitly isolated* `SMITE_CI_EXISTING_FRP=1` case: it refuses
   incomplete/writable/unexpected binds and checks both FRP
   `frpc`/`frps` read-only mounts alongside the optional Backhaul
   mount. It still outputs `network_mode: none`, read-only root,
   dropped capabilities and **no published ports**.
5. The signed API test requires a real HMAC-signed
   `GET /api/agent/engines` with `frp=ready` throughout; Backhaul
   is `not-installed` before/after and `ready` only during its trial.
   It checks wrong signatures/unsigned requests, rejects replayed
   nonces after Node restart and verifies zero active tunnels.
   **Do NOT submit an Apply to an already-ready FRP**; this is
   inventory/health-only, with no FRP/Backhaul tunnel starts.
6. On return, original FRP executable SHA digests, Compose and engine
   registry SHA are identical, the Backhaul binary and recovery
   journal are absent. A deliberately failed postrestart Backhaul
   probe is separately compensated, and FRP survives that rollback.

**Proof:** [U-OPTI Actions run 39431780642](https://github.com/aghajani82/u-opti/actions/runs/39431780642)
**completed/success, 16/16 jobs PASS**, source
`8e0caedd0c35bc449c5cb9ea5ca051419cb0848d`.
The official Backhaul Docker job explicitly printed
`ISOLATED_OFFICIAL_FRP_PREEXISTING_FIXTURE=PASS`,
`OFFICIAL_BACKHAUL_EXISTING_FRP_SIGNED_THREE_PHASES=PASS` and
`OFFICIAL_DUAL_ENGINE_FRP_SURVIVED_BACKHAUL_SIGNED_RECREATE_AND_ROLLBACK=PASS`.

**Limits:** This validates a real signed Agent API and checked in
container image in **network:none GitHub CI**, with synthetic pairing
credentials, older pinned reviewed signed Smite Node source overlay
and official engine archives. It does NOT prove actual WAN/TLS443,
final latest strict replay-store image pairing, real host snapshots,
production Node upgrade, dynamic Sanaei inbound or a released
host executor. Actual `install`/`rollback` on IR/KH are still
disabled, and signed image/replay restore admission remain release
blockers. No public port or live tunnel was opened.

## 2026-10-20 — official signed FRP+Backhaul CI upgraded to strict, one-time Smite Replay enrollment

**Same existing U-OPTI Draft #48. CI-only; IR/KH and stable release unchanged.**

The historical dual-engine Docker job passed with Smite code SHA
`a15c46288aae9849babc9c9358c68e46686bce9c`, which still
pre-dated the operator-confirmed, durable one-time Replay enrollment
and stale-snapshot quarantine. Its successful HMAC inventory test was
therefore **not evidence for the newer strict Replay DB lifecycle**.

The **existing** `managed-backhaul-official-artifact` workflow now
checks out **exact reviewed Smite security code SHA**
`02d05056d3a4baf577c9d3781d62af61c000f1ac`. Its shell runner
requires that SHA, and explicitly opts into the updated CI-only
`SMITE_CI_STRICT_REPLAY_BOOTSTRAP=1` behavior. On the disposable
private GitHub runner, the signed Node helper creates one synthetic
paired identity, then invokes the **real**
`python -m app.replay_enrollment --confirm-first-provision` in a
`--network none`, read-only-root, capability-dropped one-shot Docker
container, with the exact reviewed `node/app` source mounted
read-only. The identity and Replay DB directories are separate
root-owned private host binds. The original one-time marker
`replay-enrollment.json` is persisted **alongside the identity**
before SQLite is created.

Subsequent signed API probes and force-recreated Node containers
**reuse the same Replay DB and independent marker**; they do not
attempt rebootstrap. Both files must remain 0600 and nonempty.
A half-created marker/DB, unknown source SHA or wrong permissions
makes the test HOLD instead of silently resetting nonce history.

All other constraints from the real dual-engine regression remain:
official SHA-verified FRP v0.71.0 and Backhaul v0.7.2, FRP signed
`ready` at BEFORE / WITH-BACKHAUL / AFTER-ROLLBACK, backhaul staged
`not-installed → ready → not-installed`, signed HMAC verification
and nonce replay rejection through Docker recreation, byte-exact FRP
Compose/binaries/registry after rollback, **zero tunnel Apply/public
port**, and no real server changes.

**Important provenance boundary:** the PR lab still uses the
SHA256-pinned `ghcr.io/zzedix/smite-node` dependency/base image and
mounts the *reviewed newer Python application source* read-only; the
test has NOT released, installed or attested a complete new
Panel+Node production image pair built from the latest Smite Draft.
Other older CI jobs retain their own historical immutable reviewed
Smite source pins. Do NOT claim that successful signed API tests
constitute final deployable image parity.

**Integration commit:** `44a6aab0e2efd4c2184b661644923d5bcfd9fb63`.
[GitHub Actions run 39434522789](https://github.com/aghajani82/u-opti/actions/runs/39434522789)
**completed/success, all 16/16 jobs PASS** for the strict-source
code commit `44a6aab0e2efd4c2184b661644923d5bcfd9fb63`.
The official Docker job also explicitly printed
`SIGNED_NODE_OFFLINE_FIRST_REPLAY_ENROLLMENT=PASS`,
`OFFICIAL_BACKHAUL_EXISTING_FRP_SIGNED_THREE_PHASES=PASS` and
`OFFICIAL_DUAL_ENGINE_FRP_SURVIVED_BACKHAUL_SIGNED_RECREATE_AND_ROLLBACK=PASS`.

## Release blockers: do not obscure behind green CI

- No approved production host engine-install transaction/executor and
  signed cross-host postrestart admission yet. Existing managed
  install/rollback operates in marked disposable GitHub CI sandboxes.
- Real effective IR→KH TLS443 gateway route, Xray dynamic inbound and
  HMAC / replay / token remain unproven together under actual on-host
  Backhaul installation; preserve strict route collision checks.
- Still need immutable reviewed Panel+Node image release provenance,
  authorized stale Replay restore/key rotation, snapshot-backed dual-VPS
  reboot and rollback with separately granted approval.

`MAIN_MERGE=NO` · `RELEASE_PUBLISH=NO` ·
`INSTALL_ALLOWED=NO` · `ACTIVATION_GATE=HOLD` ·
`IR_KH_UNCHANGED=YES`.
