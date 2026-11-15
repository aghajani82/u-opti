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
| Iran Panel Foreign schema | **READY on live disposable Iran RC9**: operator ran existing explicit migration with private SQLite snapshot; read-only `--review` returns READY; flags/runtime unchanged. **New future option-1 installs (trial branch)** reuse that same migration automatically *after* Node/administrator verification and *before* COMPLETE, with same-option retry on failure |
| Foreign consolidated option 2 | `smite-unified-foreign-host-recovery.py::rehearse_option2` composes the existing two journals, with 15 integration tests; **disposable-only** |
| Foreign RC9 read-only security witnesses | Existing Gateway/activation/witness adapters now admit exact RC9 **only for read-only inspection** when `SMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06`; invalid/missing source denied. RC7 legacy read-only lane remains. No actual RC9 Foreign host install/activation or Connected claim yet |
| Retained RC9 Foreign Journal | In isolated CI, an existing RC9 owner receipt is read with the exact RC9 image, refuses a substituted RC7 image or enrolled identity rollback, then safely quarantines only a fresh unpaired disposable fixture. **Starting a new RC9 Foreign journal remains explicitly disallowed** until selected option-2 stage ownership and release gates are complete |
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

#### Iran Foreign-install schema milestone — 2026-11-15

On the already-verified `03.grandoptical.ir` RC9 Panel, the operator
first confirmed `FOREIGN_INSTALL_SCHEMA=MISSING` using the **existing**
`app.foreign_install_migration --review` command. They then explicitly
ran `--migrate --confirm PREPARE-FOREIGN-INSTALL-TRIAL-SCHEMA`, which
reported `FOREIGN_INSTALL_SCHEMA=READY`. An independent immediate
`--review` also returned `READY`. Both invocations reported
`FOREIGN_INSTALL_FLAGS=UNCHANGED` and
`RUNTIME_AND_GATEWAY=UNCHANGED`. The original Smite migration makes
a SQLite online snapshot with a private, no-overwrite backup name and
only adds the reviewed Foreign tables.

Before migration, the Panel reported `SIGNED_REGISTRATION=signed`,
`SIGNED_AGENT_AUTH=signed`, but `FOREIGN_INSTALL_ENABLED=NO`,
`FOREIGN_ORIGIN_TRUST=NO` and `FOREIGN_DATABASE_SCHEMA=HOLD`.
**The schema prerequisite is now satisfied; the two runtime enable
flags remain OFF intentionally**. Do not toggle them or issue a
time-limited, one-use Foreign installation grant until the entire
approved option-2 host transaction, origin trust, durable rollback and
actual two-host Connected gates are ready.

The existing **unmodified** Smite RC9 migration, HTTP/JWT/MFA default-off
API contract, and signed grant/HMAC/replay recovery tests are now included
directly in the unified U-OPTI CI via the exact pinned
`companion-smite` checkout. This adds test coverage without a new
migration tool or changed production Panel code.

**Remaining engineering boundaries before building/using a fresh KH
host for live install:** reconcile RC9 Foreign source/journal ownership
against RC7-specific read-only adapters; connect public option 2 to
the existing, stage-owned Sanaei RO, HTTPS/443 Gateway, signed packet
and identity recovery in the correct once-only order; confirm an
independently approved signed release and rollback; then demonstrate
actual Iran↔Foreign `Connected` with stable identities and retained
FRP/Backhaul/Sanaei. Host activation remains HOLD. No changes were made
to the operational Iran Node or the foreign server by the above CI.

#### Next closure checkpoint — original migration in fresh Iran option 1 and RC9-only read-only Foreign witness

The **existing** `smite_install_finish_local_ir` now performs an exact
three-line `app.foreign_install_migration --review` after successful local
Pairing and administrator verification, only for new resumable Iran RC9
source-pinned installs. If the schema is `MISSING`, it invokes the
**original** additive Smite migration (including its existing WAL-aware
no-overwrite SQLite backup) and independently requires `READY` after
the operation. When `READY` already exists it performs two read-only
reviews without a second migration. Wrong source/role, symlinked state,
untrusted output, or migration failure HOLD before the original
`COMPLETE` checkpoint. A retry reuses the existing Pairing/Admin/Node
identity; there is no new menu, Docker lifecycle, Foreign flag enable,
Gateway rewrite, or data reversion. Tests cover failure, retry, idempotence
and unchanged runtime.

On the Foreign side, the previously **RC7-baseline-only** read-only
`smite-unified-foreign-{gateway-plan,existing-witnesses,activation-review}`
adapters and the shared `smite-node-pairing` HTTPS preflight now accept
an exact RC9 version+upstream SHA for **review only**. Any missing or
different SHA is rejected before it can become a positive witness.
The RC7 read-only lane and mutable legacy activation constraints were
preserved. Signatures, immutable digest, paused/strict Compose, Sanaei RO
and HTTPS/443 checks remain required; no release flag was changed.

**Limit:** these tests are entirely offline/isolated, not a Foreign
RC9 live-install proof. Public option 2 still fails before host changes;
RC9 Foreign fresh owner Journal and host-stage executor recovery,
real source-pinned issuance and signed two-way Connected, independent
release approval and actual rollback proofs remain open. The working
Iran host is not updated automatically from the trial branch.

#### Foreign choice 2 release gap after RC9 read-only alignment

The existing `smite-unified-foreign-existing-witnesses.py`,
`smite-unified-foreign-activation-review.py` and
`smite-unified-foreign-gateway-plan.py` now permit exact
`SMITE_MANAGED_VERSION=2.0.0-rc.9` with the matching signed
`SMITE_UPSTREAM_REF` **for read-only reviews**; the legacy RC7
read-only fixture remains intact. This removes an impossible version
comparison but does **not** admit a new Foreign RC9 source into the
original fresh-install Journal or authorize runtime activation. The
actual selected Foreign install/Gateway/Sanaei functions still contain
RC7-specific source/Compose-stage assumptions and require a reviewed
RC9 ownership and rollback conversion, not merely a digest swap.

The public Foreign option 2 still returns
`FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES` before host writes.
The live Iran Panel Foreign schema is already READY, but both Foreign
enable flags were OFF in the operator's last runtime check. Do not
enable them until the complete released host transaction is ready.
Next safe boundary: match exact RC9 Foreign owner/source, Compose and
Sanaei RO evidence with the existing per-stage recovery and signed
grant/identity journals; then test rollback and *actual*
Panel↔Foreign signed Connected on a disposable Foreign host.
Never leak time-limited installation codes or mutate Grandoptical,
the FRP 20182 tunnel or retained Backhaul.

#### Retained RC9 Foreign Journal guard — CI-only, no new install admission

A new regression case reuses `smite-rc6-install-journal.py` with a
**synthetic retained Foreign owner receipt**. It verifies the exact RC9
Node image/Compose project, denies a swapped RC7 image before any stop,
refuses rollback of an enrolled Node identity, and demonstrates the
original quarantine-only rollback after restoring a strictly unpaired
disposable fixture. The original `begin('foreign', source=RC9_SOURCE)`
still returns HOLD: no new RC9 Foreign install permission was introduced.

This is a prerequisite for the next integration step, **not** evidence
that the existing public option 2 can begin or resume a real Foreign
host. The source-aware Foreign stage owner and signed identity
promotion remain to be integrated with the two existing host/identity
journals before anything may reach the Panel.

#### RC9 option-2 pre-host admission and full witness composition — 2026-11-15

The existing *disposable-only* option-2 composition now calls the
original `smite-unified-foreign-gateway-plan.py::admit` **before the first
Core/Sanaei/Gateway callback**. It compares the private, Panel-issued
one-time packet against the persisted Foreign role, version, source
(`SMITE_UPSTREAM_REF` must match the exact RC9 SHA), Panel domain,
Foreign domain, node name and existing Gateway scope, without creating
credentials or starting any container. Previously this strict
packet↔state comparison was only guaranteed later by the identity
promotion path, after some simulated host stages had completed.

CI failures now inject wrong RC9 source (including the retained RC7 SHA),
missing source, mismatched role, node name and Foreign domain. Every
case HOLDs with **zero host callbacks, zero host journal creation and
zero identity redemption**. Exact RC9 passes the original host-stage
journal, signed Panel HMAC proof and once-only identity promotion; repeat
does not reinstall or rotate the key.

A further integration test wires the **actual existing read-only
signed-pair, immutable Docker image, paused/strict Compose, Sanaei RO
and HTTPS/443** witness adapter into the *same* existing option-2 Host
and Identity journals, instead of relying solely on callbacks that
return READY. It denies unsigned/source-drifted or swapped-image
fixtures before host work. The positive result is deliberately
`FOREIGN_OPTION2_OFFLINE_READY`, **not** Connected; no real host
Docker/Nginx/identity is touched. CI PASS:
[43700423929](https://github.com/aghajani82/u-opti/actions/runs/43700423929).

**Remaining to authorize creating a KH live-install host:** the
still-disallowed **new RC9 Foreign owner Journal** and its completed
host executor, exact runtime image and per-stage compensation for
Core→Sanaei RO→Gateway 443→signed Pairing; separate signed release
activation approval; required live two-server receipt and Rollback.
The public option 2 remains `HOLD_BEFORE_HOST_CHANGES`. No changes
were applied on the live Iran RC9, Grandoptical, retained FRP/Backhaul,
or U-OPTI `main`.

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
