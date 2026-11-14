# U-OPTI × Smite — final release and rollout acceptance

**Date:** 2026-11-14  
**Target branches:** `aghajani82/Smite:trial/unified-smite-install`,
`aghajani82/u-opti:trial/unified-smite-install`  
**Scope:** finish the existing one-choice Iran/Foreign installer, signed
HTTPS/443 pairing, retained FRP/Backhaul/Sanaei and stage-owned rollback.
**No new features, menu entries, UI or network listeners.**

## Current objectively verified state

| Item | Evidence / status |
| --- | --- |
| Smite trial source | `0f03ad84a3ad57d89b99bbfb8e3af898de77f677`; signed-trial workflow [43616884015](https://github.com/aghajani82/Smite/actions/runs/43616884015) passed |
| Signed trial Panel | `ghcr.io/aghajani82/smite-panel@sha256:a1aeac5cf280748238abadd057debdf380085366fa0c475cf619b730928a0e40` |
| Signed trial Node | `ghcr.io/aghajani82/smite-node@sha256:527d096fa6557eb8b3409c0f90c507ccf64826b02545636ebd1b9e79baaafa5b` |
| Trial manifest SHA256 | `1302dedaf492ceb79de81869efe7be10ac406e313629f4f69b47972f36ad30e0` |
| Trial release policy | `release_approved=false`, `activation_allowed=false`. Correct, deliberate HOLD. |
| Iran option 1 | Existing signed RC7 install/journal; Panel + Iran Node + HTTPS/443 Pairing stages tested, with isolated real Compose upgrade and rollback |
| Iran retained Node | Private stage binds Docker container ID, image ID, project, Created and StartedAt; stage/status and rollback fail on change |
| Iran Panel transaction | Signed sealed stage, additive schema, durable per-step cutover and owned config-only rollback; exact, restricted Docker/Compose/Nginx command driver **fixture-only** |
| Foreign host stages | Existing core/Sanaei RO/Gateway 443 recovery journal: per-stage intent, verification and compensation; immutable Node/FRP preservation |
| Foreign Pairing | Existing one-time grant, signed HMAC proof and no-overwrite identity promotion with its separate private recovery journal |
| Foreign consolidated option 2 | `smite-unified-foreign-host-recovery.py::rehearse_option2` composes the existing two journals, with 15 integration tests; **disposable-only** |
| Public Foreign menu option 2 | Explicit `FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`, unchanged |
| Production hosts / U-OPTI and Smite main | No live deployment or merge authorized by the above trial work |

## Closeout gates — in order, do not skip

### Gate 1 — release source and image pair (currently HOLD)

1. Review the complete Smite trial against the production base; merge
   only the reviewed candidate, with passing Smite and U-OPTI test evidence.
   An old trial branch SHA or untagged digest is **not** an approved release.
2. Tag the exact reviewed Smite **merged release commit** immutably. Reuse
   the existing owner-confirmed `.github/workflows/publish-images.yml`
   on that tag to build/sign the new Panel+Node pair, **not**
   `unified-install-signed-trial.yml` as a production publisher.
3. Obtain the resulting `registry-pair.json` and independent SHA256;
   verify **both** digests and OIDC/Cosign provenance with the existing
   owner-confirmed `.github/workflows/verify-candidate-images.yml`
   and U-OPTI's `smite-registry-pair-admission.py`.
4. Record an explicit, independently reviewed deployment decision and
   recovery boundary for that **new** immutable release. Do not edit
   the old signed trial manifest's false fields or assume GitHub CI
   creates deployment approval.

**Evidence required:** reviewed source commit, immutable tag, exact Panel/Node
digests, independent manifest SHA256, two signature verification results,
explicit approved-release receipt and no regressions.

### Gate 2 — Iran Panel live change (currently HOLD)

1. Make the original provider/server snapshot and offsite recovery copy;
   verify console restore capability. No FRP/Backhaul downtime consent.
2. Confirm installed U-OPTI source and signed RC7 owner journal; run
   `smite-unified-panel-stage.py --verify-live-baseline` **read-only**
   and confirm signed Iran↔Panel control, local HTTPS/443, Node ID and
   the last known FRP/Backhaul receipts.
3. Freeze a sealed staging snapshot and exact reviewed candidate; add an
   independently reviewed **production-authorized** executor using the
   existing cutover phases and fixed Panel-only driver. Do not enable
   the current disposable token on `/`.
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

**Resume from:** the two current trial heads and
`docs/UNIFIED_SMITE_INSTALL_TRIAL.md` for detailed archived test evidence;
this file is the concise remaining-work source of truth.
