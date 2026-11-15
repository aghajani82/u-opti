# U-OPTI × Smite — final release and rollout acceptance

**Date:** 2026-11-15  
**Source:** Smite `main` at the tagged RC9 commit and U-OPTI
`trial/unified-smite-install`  
**Scope:** finish the existing one-choice Iran/Foreign installer, signed
HTTPS/443 pairing, retained FRP/Backhaul/Sanaei and stage-owned rollback.
**No new features, menu entries, UI or network listeners.**

## Current objectively verified state

| Item | Evidence / status |
| --- | --- |
| Smite RC9 source | `e7f76185e9a7da51d7069d5d0a829dc192cc1e06`, [v2.0.0-rc.9](https://github.com/aghajani82/Smite/releases/tag/v2.0.0-rc.9) |
| Signed RC9 Panel | `ghcr.io/aghajani82/smite-panel@sha256:f6999effd131f6b3272f8d9116b3fbae917f699bf9a29271fc5ede24cc387a2e` |
| Signed RC9 Node | `ghcr.io/aghajani82/smite-node@sha256:3df3c9d40c338ab87205bbe93e9ab9bd94eb4051558c4429fdd09f876b76b2c2` |
| RC9 manifest SHA256 | `f242e24710d87cef2a48a562d0fd3f16c37d553fb1cb9a8888d3de3cb4fc8e60` |
| RC9 evidence | [Publisher](https://github.com/aghajani82/Smite/actions/runs/43631138363), [independent Cosign](https://github.com/aghajani82/Smite/actions/runs/43631412672), [U-OPTI signatures](https://github.com/aghajani82/u-opti/actions/runs/43632177646), [U-OPTI rehearsal](https://github.com/aghajani82/u-opti/actions/runs/43632177665) |
| RC9 candidate policy | `release_approved=false`, `activation_allowed=false` |
| Iran option 1 | **Live disposable RC9 installed on `03.grandoptical.ir`** using U-OPTI `6946540`; operator SSH read-only audit confirms journal `COMMITTED/COMPLETE`, pinned Panel/Node images both `healthy`, signed Pairing/replay and DB identity PASS, loopback Panel/Node and HTTPS/443 HTTP 200, Nginx syntax PASS; provided UI screenshot displays `node-ir` Connected. **Not tested:** power-loss resume/restart continuity. **main:** still RC7; no in-place adoption of RC7 journal |
| Iran retained Node | Private stage binds Docker container ID, image ID, project, Created and StartedAt; stage/status and rollback fail on change |
| Iran Panel transaction | Signed sealed stage, additive schema, durable per-step cutover and owned config-only rollback; exact, restricted Docker/Compose/Nginx command driver **fixture-only** |
| Foreign host stages | Existing core/Sanaei RO/Gateway 443 recovery journal: per-stage intent, verification and compensation; immutable Node/FRP preservation |
| Foreign Pairing | Existing one-time grant, signed HMAC proof and no-overwrite identity promotion with its separate private recovery journal |
| Foreign consolidated option 2 | `smite-unified-foreign-host-recovery.py::rehearse_option2` composes the existing two journals, with 15 integration tests; **disposable-only** |
| Public Foreign menu option 2 | Explicit `FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`, unchanged |
| Production hosts and U-OPTI main | Awaiting live authorization and evidence. Smite source was merged in [PR #58](https://github.com/aghajani82/Smite/pull/58). |

## Closeout gates — in order, do not skip

### Gate 1 — release source and image pair

RC9 candidate publication and independent verification passed. Deployment
approval and the recovery boundary still require a separate decision bound
to the exact pair and the intended host.

### Gate 2A — disposable fresh Iran RC9 (live install PASS; interruption proof outstanding)

Use only after the full pinned CI run passes. On the **designated disposable Iran test host** (not Grandoptical), confirm backups/rebuild window, source pin, Docker ownership and valid DNS/TLS. Fresh option 1 must install the *same* signed RC9 Panel/Node digest pair, configure Gateway on HTTPS/443, perform the original signed local Iran Pairing and create the admin account in one journaled path. Evidence must include both healthy pinned containers, Panel API RC9 over loopback and valid HTTPS, the Iran Node showing `Connected`, signed Panel↔Node probes, stable identity, and correct retry from each completed checkpoint after an interruption. Capture a redacted report, never credentials or one-time codes.

The trial branch is **not** approved for production. Do not rebuild or upgrade the live RC7 installation simply because CI passed; testing a fresh RC9 install does not prove the separately gated Panel-only RC7→RC9 cutover.

#### Iran operator acceptance — 2026-11-15 (read-only SSH transcript and UI screenshot)

The operator rebuilt the **disposable Iran test host**, installed from U-OPTI source
`6946540f5ac5de5d05477da085ae247a1bdb6fb2` with a new Panel domain
`03.grandoptical.ir`, and submitted the following observed results:

| Existing check | Observed |
| --- | --- |
| U-OPTI `INSTALL_REF` | `6946540f5ac5de5d05477da085ae247a1bdb6fb2` |
| Role / mode / Smite source | `panel-iran` / `standard` / RC9 `e7f76185e9a7da51d7069d5d0a829dc192cc1e06` |
| Original resumable install Journal | Source matches RC9, `COMMITTED` / `COMPLETE` / `panel-iran` |
| Smite Panel image | Exact pinned RC9 image, running, Docker healthy |
| Smite Iran Node image | Exact pinned RC9 image, running, Docker healthy |
| Pairing and replay | `PANEL_PAIRING=ENABLED`, `CREDENTIALS=STAGED`, `REPLAY_ENROLLMENT=READY` |
| Original Panel SQLite identity | Signed, active `node-ir` check passed in read-only query |
| Service endpoints | Loopback Panel `/api/status` HTTP 200; Node `/healthz` HTTP 200; Nginx `-t` PASS; certificate-validated localhost-resolved `https://03.grandoptical.ir/api/status` HTTP 200 |
| Admin browser page | User screenshot shows Panel RC9 and `node-ir` with `Connected` |

This is **operator-supplied live evidence**, not an independently captured
signed server witness. The browser `Connected` is consistent with the
reviewed signed NodeClient liveness path, but was not accompanied by an
independently exported two-way HMAC/replay receipt. Crash/power-loss
resume, identity continuity across restart, and a real two-server Foreign
connection remain unproven. Do not rebuild this verified Iran host while
preparing the Foreign path.

#### Foreign choice 2 release gap exposed by comparing the current modules

The already existing trial adapters `smite-unified-foreign-existing-witnesses.py`,
`smite-unified-foreign-activation-review.py`, and
`smite-unified-foreign-gateway-plan.py` still require
`SMITE_MANAGED_VERSION=2.0.0-rc.7` on the Foreign host even though the
signed unified trial Node image is RC9. Their successful disposable test
runs **do not** admit a brand-new RC9 Foreign source/journal or a live
unified install. The public Foreign menu option 2 remains explicitly
`FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`.

Next safe boundary: read-only review of **existing IR Panel Foreign-install
capability flags and database schema**, and fresh Foreign host Docker,
Nginx, Sanaei RO DB and current U-OPTI state, without exposing passwords,
one-time grant codes or identity files. Only then reconcile Foreign
source/journal ownership and existing stage-by-stage rollback/activation
before any live test. Preserve FRP/Backhaul and Grandoptical.

### Gate 2 — Iran Panel live change (currently HOLD)

1. Make the original provider/server snapshot and offsite recovery copy;
   verify console restore capability. No FRP/Backhaul downtime consent.
2. Confirm installed U-OPTI source and signed RC7 owner journal; run
   `smite-unified-panel-stage.py --verify-live-baseline` **read-only**
   with the reviewed U-OPTI module set. It requires the exact RC7 API version
   over loopback and HTTPS/443, signed Iran↔Panel control and an unchanged
   Node fingerprint across the probes. The signed read consumes a normal
   replay nonce. Record the existing FRP/Backhaul receipts separately.
   Share the status output only and keep private snapshots on the host.
3. Freeze a sealed staging snapshot and exact reviewed candidate; add an
   independently reviewed **production-authorized** executor using the
   existing cutover phases and fixed Panel-only driver. Do not enable
   the current disposable token on `/`. The existing cutover `--review`
   checks this baseline and the sealed preimages together with the fixed
   Panel-only command plan. Success reports release HOLD.
4. After each stage verify its durable journal, Panel-only service
   change and unchanged Iran Node Docker ID/StartedAt and signed replay.
   Migration runs only while Panel is actually stopped.
5. Verify the **real** Panel API/version and authenticated two-way signed
   control on the installed server. Test failure/interruption rollback
   with owned Nginx/env/Compose restoration only; never rewind grant,
   identity or replay DBs or recreate the Iran Node.

**Evidence required:** source/owner/pair pin, private stage and transaction
receipts, original-vs-candidate Panel health, signed two-way proof and
unchanged Node/FRP/Backhaul records. The disposable CI cannot replace this.

### Gate 3 — Foreign one-choice activation (currently HOLD)

1. Ensure the approved **new** Node digest is the one running on the
   intended new Foreign host, paused/strict. Keep Grandoptical legacy
   FRP tunnel `FRP-IR-Grandoptical-20182` untouched.
2. Connect public option 2 to the **existing** signed grant packet,
   host recovery journal, core, readonly Sanaei inventory and exact
   Gateway 443 route, then signed identity journal; preserve locks,
   one-time code privacy, original node identity and error compensation.
   Do not silently rerun a completed Sanaei/Gateway stage or consume a
   code before independent host verification.
3. Complete the approved runtime activation with no new public ports
   and prove Panel↔Foreign signed `Connected`, including after a
   restart/resume. Verify retained Node/FRP/Backhaul/Sanaei DB.
4. Test the documented rollback of **each** stage, including interrupted
   operations, without losing existing FRP tunnels, credentials or
   private databases. Release-review status must not imply connected.

**Evidence required:** paired Node ID, exact approved origin/control URL,
signed two-way online handshake, retained component receipts, precise
stage journals and rollback observation.

### Gate 4 — final merge and publication

- Only when Gates 1–3 pass, merge the reviewed completed work to
  `main`, run the full final CI against the merged SHA, publish the
  installation command pinned to that immutable source and verify
  the user-facing one-choice options 1 and 2.
- Confirm no unresolved PRs or failed workflows, no leaked secrets or
  stale trial image pins, and no new service beyond the existing scope.
- Preserve original live state and snapshots until final acceptance.

## Safety invariant

An internal test, matching SHA256, healthy Docker container, signed **trial**
image, or GitHub Actions success is **not** production approval or a
two-host `Connected` witness. Until the above evidence exists, leave
`activation_allowed=false`, `release_approved=false` and
`FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES` unchanged.

**Resume from:** the RC9 tag and the U-OPTI trial head and
`docs/UNIFIED_SMITE_INSTALL_TRIAL.md` for detailed archived test evidence;
this file is the concise remaining-work source of truth.
