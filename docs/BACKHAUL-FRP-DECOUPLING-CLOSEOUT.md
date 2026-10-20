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
