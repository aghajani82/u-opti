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
| Exact RC9 existing Sanaei + Foreign HTTPS/443 Gateway | Original 3xUI install, paused strict Node RO-attachment and owned Compose/HTTPS Gateway functions admit exact RC9 **only inside the selected option-2 scope**. RC7 and standalone paths retained; signature/release gate still blocks actual Foreign host mutation. Isolated CI validates source/ownership/default-off, reused stage compensation and no Node re-creation |
| New RC9 Foreign Core Journal (fixture-only) | Original `smite-rc6-install-journal.py` now models an exact source-pinned `foreign` Core owner with nonsecret Panel domain, Foreign domain, Node name/ID, control path. A new RC9 Foreign `begin` is rejected on real root `/` until the signed release + complete executor are reviewed. No one-use codes or node secrets in the journal |
| Public Foreign menu option 2 | Explicit `FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`, unchanged |
| Production hosts and U-OPTI main | Awaiting live authorization and evidence. Smite source was merged in [PR #58](https://github.com/aghajani82/Smite/pull/58). |

#### Foreign option-2 Core stage rollback — original Iran-style compensation (2026-11-15)

This integration step is now committed on the SAME trial branch, without
altering menu option 7, creating a second installer, or relaxing the signed
release HOLD. The original `smite-rc6-install-journal.py` has an internal
`recover-foreign-core` action for a fresh, **uncommitted** RC9 Foreign
Core only. It requires the original owner, exact immutable Panel-issued
packet scope and current installer lease. It reuses the ORIGINAL
`Journal.rollback` identity/grant/route/protected-DB and Docker
ownership checks to quarantine only the incomplete Core. The foreign
selected-stage shell coordinator invokes this compensation on an
interrupted Core install, failed Core commit, or unadoptable incomplete
Core receipt; it then reports RETRY_OPTION_2, never Connected.

Already COMMITTED Core, running another install, changed Panel scope,
foreign image/project, enrolled identity or rollback uncertainty fail
closed. Fully committed Node and future Sanaei/Gateway/Pairing checkpoints
are not reset by Core recovery. Original Sanaei pending attachment and
Gateway HTTPS/443 snapshot compensation remain the next existing
per-stage mechanisms to connect to the **real-root** selected option 2.

- [Original Journal and CLI recovery](https://github.com/aghajani82/u-opti/blob/trial/unified-smite-install/modules/smite-rc6-install-journal.py)
- [Existing Foreign selected-stage call site](https://github.com/aghajani82/u-opti/blob/trial/unified-smite-install/modules/smite-install.sh)
- [Core auto-rollback regression suite](https://github.com/aghajani82/u-opti/actions/runs/43720715535) — **3/3 CI PASS** (fixture-only Python + actual shell dispatch)
- The exact RC9 signed pair still has `release_approved=false` and
  `activation_allowed=false`. The public option 2 still emits
  `FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`. No real
  Foreign host was changed and no Connected witness was claimed.

**Next precise engineering work, without new capabilities:** reviewed
real-root invocation of the existing Sanaei/Gateway stage journals with
stage-scoped rollback, the already implemented original Identity
promotion journal and signed activation/rollback, then an authorized
disposable two-host Connected + restart/interruption acceptance. Only
after this may the public option-2 guard and final merge be reviewed.

#### Foreign option-2 original Sanaei/Gateway stage witnesses — 2026-11-15

Completed the next **integration-only** checkpoint on the existing branch.
The SAME original `smite-rc6-install-journal.py::foreign_resume` now
accepts the **same active installer PID** under its existing operation
lock, while still refusing a different running installer. Immediately
after the original Sanaei return/RO attachment and BEFORE HTTPS/443
Gateway changes, `smite-install.sh` requires a fresh, exact RC9
`CORE_COMMITTED` receipt from that original owner with the packet,
same active installer lease and `--attached-sanaei`. The Journal
independently checks immutable source, Node, Compose/project, current
paused+strict runtime and the actual read-only DB bind; no new
installer or second journal was introduced.

After the existing HTTPS/443 Gateway completes, the same selected
internal path additionally reuses the original read-only Sanaei mount
and Nginx/TLS local witnesses before reporting readiness for Pairing.
Drift at either boundary HOLDS without deleting or reinstalling any
previously committed Core/Sanaei/Gateway stage. Existing stage-owned
Sanaei pending rollback and Gateway pending snapshot recovery remain
the source of truth. Separate menu option 7, independent RC7 paths,
Smite main, U-OPTI main and operational hosts are untouched.

[Full three-job signed source / Foreign stage CI PASS](https://github.com/aghajani82/u-opti/actions/runs/43722010503)
at source `5365dcfbb145be189b593fa2cae6d6766f67fc6f`.
CI includes same-installer lease takeover-denial and a real-shell
option-2 post-core fixture testing owner drift, RO Sanaei drift,
TLS/443 drift, retained Gateway and honest not-Connected reporting.
These are **offline tests only**, not a live root or cross-server
Connected acceptance.

**Next closure boundary:** reuse the existing original Foreign
identity/redeem/activation journal under reviewed real-root admission,
complete per-stage failed-Pairing rollback and same-option retry, then
obtain actual signed Iran+Foreign two-way Connected and interruption
proof on the two disposable hosts. Public option 2 remains
`FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`; the sealed RC9
manifest still explicitly disallows activation. No release flag was
relaxed or production deployment authorized.

#### Foreign option-2 original signed Identity + retained private packet — 2026-11-15

This branch now composes the **existing** Foreign grant client,
HMAC-signed proof and no-overwrite identity promoter as the selected
option-2 identity stage, reusing the original locked
`unified-foreign-transaction.json` INTENT/IDENTITY_PROMOTED_OFFLINE
journal. Neither a second identity/key generator, another Pairing menu
nor a duplicate Foreign installer was added.

The original `smite-unified-foreign-identity-phase.py` has an internal
`--selected-foreign --installer-pid` route. Its root boundary is
*exactly* bound to the original installer operation journal, retained
private packet, managed `state.env`, Gateway receipt, paused/strict
Node environment and existing live identity destination. Before
reaching the grant client or creating an identity journal it reuses
`smite-node-pairing.py::_require_unified_foreign_release()`, the
original RC9 Core owner's `foreign_resume(..., attached_sanaei=True)`,
the existing HTTPS/443 Gateway/Compose/RO-Sanaei checks and immutable
Panel-issued Node/control scope. The original HMAC proof, promotion
prepared/completed receipts and identity bytes stay unchanged on
retry, including a lost redemption response. No activation/Connected
claim follows this **identity-only** stage.

The selected one-choice coordinator also reuses the existing
hidden-terminal packet reader and 0600, fsynced, no-overwrite stager,
with a **durable** owner at
`/var/lib/u-opti/rc6-install-journal/foreign-staging/foreign-install-packet.json`.
This corrects the transient temporary-fixture packet lifetime: an
interrupted selected flow must not lose its private Panel-grant source
before the original journals can resume. The real-root intake entry is
`--capture-owned-foreign`, guarded by the SAME immutable signed
release admission and exact root-owned 0700 directory/no-symlink checks.
Existing disposable rehearsal intake remains separate. No external
code, secret or Node identity appears in argv, logs or receipts.

**Important remaining gates:** the currently signed RC9 trial
manifest explicitly says `release_approved=false` and
`activation_allowed=false`. Therefore the public menu's option 2
still deliberately emits
`FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`; the new internal
root identity and private intake entries **refuse host execution**
today. The original disposable Host stage journal/witness and
post-promotion activation/rollback still need approved real-root
admission and actual two-host signed Connected proof. In particular,
an expired packet's renewal/replay after a process interruption must
retain its original, provable Host+Identity owner before enabling
live retries. Do not mark the install complete based solely on
successful signed enrollment or release signatures.

The new tests cover original-client interoperability, HMAC proof
after lost ACK, exact source and lease admission, packet privacy,
selected Core→Sanaei→Gateway→Identity call ordering, and fail-closed
release-HOLD before any host mutation. They are offline fixture
tests, **not** live Iran+Foreign acceptance. The public option 7,
Smite main, U-OPTI main, FRP, Backhaul and test hosts are unchanged.

#### Panel → Foreign option 2: two-hour grant and stage-local retry — 2026-11-15

The agreed operator sequence is **not** Foreign self-registration:
1. Finish Iran option 1 and verify its Iran Node is Connected in the
   **Iran Smite Panel**.
2. In that same Panel, reserve/create the **Foreign Node** with its exact
   Foreign HTTPS/443 domain; use the existing Foreign installation dialog
   to issue/copy its `smi1` JSON (`node_id`, `node_name`, `panel_url`,
   `origin`, `control_url`, `installation_code`, `expires_at`).
3. Paste this exact JSON once, with terminal echo disabled, **during
   Foreign Smite Manager option 2**; do not type credentials into
   argv/environment, ask KH to create a competing Node or issue a code
   outside the Iran Panel.
4. Reuse the same saved, private, still-valid 0600 packet on retries.
   The original IR Panel grants code validity for `7200` seconds **from
   issuance**, not from the beginning of KH installation.
5. If the grant expires *before redemption*, request a fresh code
   **for exactly the same reserved Node and domain** in the Iran Panel.
   The original Panel grant issuer retains the previously reserved
   `control_url` for that same Node/domain. The root-owned option-2
   intake now reuses the original 0700/0600 hidden-TTY stager and Core
   Journal read-only `foreign_resume` witness to accept only the
   same five immutable values, an expired prior code, a different fresh
   code and an unpromoted Identity `INTENT`. Drift, a live identity,
   a previously committed promotion or an unverified/partial Core
   **HOLDS**. It never reinstalls successful Core/Sanaei/Gateway,
   creates a new identity, consumes the old code or changes the
   current operation owner.
6. Use the **existing** signed Panel HMAC proof and promotion receipts.
   A completed identity must never be rekeyed/redeemed on an expired
   bearer code. Activation and the live Iran-Panel Connected witness
   are separate, still-pending acceptance checks.

The selected internal coordinator also shares Iran option 1's original
`operation.lock` across hidden input, Core, Sanaei, Gateway and
identity; concurrent installs cannot silently race ownership. Existing
legacy recovery/menu option 7 remains unchanged.

**Evidence**: source Smite tag
`e7f76185e9a7da51d7069d5d0a829dc192cc1e06`,
`frontend/src/components/ForeignInstallDialog.tsx` supplies
`ttl_seconds: 7200`, and `panel/app/foreign_install_grants.py`
enforces `DEFAULT_TTL = MAX_TTL = 7200` and reuses prior
`control_url` for the same Node and domain. U-OPTI adds original-owner
failure-injection coverage for unchanged scope, Node image/runtime
drift and no renewed-token adoption after promotion.

**Release truth**: the currently pinned signed RC9 trial manifest still
denies host activation; the public option 2 remains
`HOLD_BEFORE_HOST_CHANGES`. All evidence here is branch CI/disposable
rehearsal until an approved signed release, the real-root Host/Identity
admission and live two-server Connected test are complete. No new
PR, Workflow, feature, menu or main-branch change is requested.

#### Final internal option-2 activation closure — 2026-11-15

The branch's selected Foreign continuation now invokes the **existing**
`smite-node-pairing.py::activate_foreign_node_field_trial(
reviewed_unified_trial=True)` only **after** its original Core/Sanaei
RO/Gateway HTTPS/443 and signed Identity transaction have passed. The
original Pairing function, not a second controller, owns the single Node
security-candidate Compose recreation, HMAC replay, Panel→Foreign signed
Gateway proof, Foreign→Panel authenticated check-in and its verified
signed→paused rollback on failure. The selected wrapper accepts
`FOREIGN_CONNECTED=SIGNED_BIDIRECTIONAL_VERIFIED` only after the
original Pairing printed **both** directional PASS witnesses; Docker
healthy or an enrollment receipt alone are explicitly insufficient.

**RC9-specific correction:** the original Foreign Pairing activation and
rollback previously assumed its optional unified selector implied
`2.0.0-rc.7`; this was inconsistent with the option-2 pinned
`2.0.0-rc.9` source. The selected unified selector now requires
**exactly RC9 and source
`e7f76185e9a7da51d7069d5d0a829dc192cc1e06`**. Both activation
and its paused rollback reuse the existing signed-image,
`uopti_rc6_<id>` Compose-project/file-set checks with the RC9 digest,
rather than silently using an unowned Compose project. The official RC7
legacy selector remains unchanged. The original root-owned
`unified-foreign-transaction.json`, promotion receipts and retained
node-identity file are independently matched to the single IR Panel
issued packet immediately before Pairing activation. A swapped identity
or modified scope therefore fails before runtime mutation.

**Tests:** the existing RC7/RC9 pairing regression and new isolated
option-2 activation-order/failure tests cover exact source, no fallback
to RC7, single owned Compose candidate, HMAC/check-in witnesses and
signed→paused compensation. These tests inject mocked Docker/Panel
responses and never claim live `Connected`.

**Remaining actual release work / NOT DONE:**

- The currently pinned RC9 tag/manifest remains `release_approved=false`
  and `activation_allowed=false`. Moreover, the existing signed trial
  admission explicitly returns `host_activation_allowed=False`.
  No credible change to those bits can substitute for publishing,
  validating and approving a **new authoritative signed release**
  with a reviewed rollback procedure.
- The public Foreign option 2 still intentionally emits
  `FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`. Its internal
  Core→Sanaei→Gateway→Identity→signed activation chain is **not yet
  enabled** on live hosts. Do not bypass this with manual calls to
  the internal modules.
- A full **post-activation restart/resume** and the case where an
  installation is interrupted after identity promotion and its
  two-hour bearer code later expires still require end-to-end live
  evidence. Do not assume a completed identity automatically means
  the Foreign Node is `Connected`, and do not rekey it.
- Before merging to `main`: verify original Iran option 1 live,
  publish/approve exact signed pair, test Foreign option 2 on
  rebuildable servers including step-local interruption/rollback,
  observe authenticated two-way `Connected` **in the Iran Panel**,
  and retain the existing FRP and Sanaei installations throughout.

All work above is committed directly to
`trial/unified-smite-install`; no new GitHub PR or workflow definitions
were required.

#### Final selected Foreign menu wiring and two-hour recovery — 2026-11-15

The public **Foreign option 2** now delegates to
`smite_install_selected_foreign_fresh` and then the **existing**
`smite_install_unified_foreign_selected_stages`, in the same Smite
management menu. This reuses the RC9 Core Journal, old signed
Panel-packet intake, Sanaei RO database attachment, HTTPS/443 Gateway,
original enrolment/promotion transaction, and the original
`smite-node-pairing.py` HMAC dual-direction activation with its
verified signed→paused rollback. No second installer, extra public port,
new tunnel/FRP activity, or standalone pairing feature is introduced.
Legacy `clean-rc` and menu option 7 are not diverted.

**The public path is signed-release gated BEFORE any host write.**
A local sha256-bound manifest read first requires both
`release_approved=true` and `activation_allowed=true` (this is only
a fail-closed early rejection). After that, and *only* after that, the
original pinned Cosign bootstrap, independent verified signature/pair
release admission and exact source/journal validation occur before
the selected stage runner. The current signed prerelease
`v2.0.0-rc.9` has **both flags false** and its authoritative trial
verifier explicitly returns `host_activation_allowed=False`.
Thus public option 2 still returns
`FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES` now. Do NOT
change these flags by hand to circumvent actual reviewed publication.

**Original Iran-Panel two-hour packet:** for a new/never-enrolled
Foreign Node, the original `smi1` code must still be unexpired at
redemption; if the expiry precedes successful enrollment, request a
new code for the **same Panel-reserved Node and control URL**. If
enrollment has already written the original 0600 staged secret and
owner-bound transaction `INTENT`, an expired code cannot be
redeemed again and must not cause a rebuild. The selected option-2
coordinator now verifies the same code hash, original scope, staged
secret, exact promotion/prepared/completed receipts (where applicable)
and private identity, then resumes directly at the *original*
signed identity stage, without reinstalling Core, Sanaei or Gateway.
The original foreign Core journal independently verifies its
immutable role/source/Node scope, current paused+strict image/Compose
and Sanaei RO mount. The final signed Panel STATUS, not an expired
bearer code, confirms enrollment continuity. Missing or mismatched
INTENT/identity receipts still HOLD. A previously connected runtime
is not silently recreated merely to report `Connected`.

**Offline evidence only:** test fixtures validate original-stage ordering,
wrong source/image rejection, HMAC two-way activation requirements,
signed→paused compensation, owner PID, no new Node/rekey after expired
code, and fail-before-host-changes for public option 2. Do not treat
green GitHub tests as proof of two hosts actually Connected.

**Unchanged release blockers:** independently authorize a signed
host-installation pair (with reviewed immutable manifest and trusted
source), run the real fresh Iran+Foreign acceptance including intentional
stage interruption and retained-stage rollback, witness authenticated
Foreign `Connected` in the Iran Panel, verify restart/replay continuity,
then merge to `main` only with those records. No server rebuild is
requested before these release gates. The original legacy FRP/backhaul
and Sanaei installations remain outside the installation transaction.

#### Exact crash windows for two-hour grant — 2026-11-15

The retained private `smi1` code may expire after the original signed
enrolment but **before** one of the two original fsynced identity journals
commits. The recovery verifier now accepts only these same-scope,
cryptographically bound interruption windows: original
`INTENT + staged secret + PREPARED` without live identity, and
`INTENT + staged secret + PREPARED + live identity + COMPLETED`.
It recomputes the canonical original promotion payload digest in memory;
a forged PREPARED hash, changed secret/Node, absent INTENT or mismatched
COMPLETED still HOLD. Replaying the original code or generating another
identity is forbidden. The original enrolment/promoter must obtain a new
signed Panel STATUS witness before it can finish the retained stage. The
companion offline tests inject crashes at both boundaries.

#### Two-hour expiry before Core begins — 2026-11-15

If the Panel-issued `smi1` code expires while Foreign option 2 is
paused **before the first Core Journal transaction**, the unchanged
private 0600 packet may be replaced with a new Panel-issued code only
for the **exact same reserved Node, domain and control URL**. The
existing signed release admission remains mandatory. The original
RC9 Core Journal must not exist, all its original managed installation
targets must be absent, and none of the Host/Identity/Promotion staged
receipts or secret files may exist. This is a packet-only atomic
replacement; it never creates a Core owner or a new Node, and never
touches the running Sanaei/FRP installation. If any managed owner
already exists, the original Core Journal verifies that owner instead.
The offline tests now cover both no-write fresh-host admission and
fail-closed rejection of prior stages/managed paths.

#### Final adapter, exact live identity bytes — 2026-11-15

Immediately before any original signed Foreign Pairing activation, the
option-2 adapter now reopens the **same** private live identity via the
existing directory-FD and 0600/no-hardlink reader. It recomputes the
canonical original promoter payload from the identity returned by the
original Pairing module and checks its exact bytes and the original
`PREPARED` receipt SHA-256. Any changed secret, missing identity or
detached receipt fails closed *before* the original runtime activation.
Offline tests now exercise the adapter's **success** call chain with real
client/promoter identity receipts and only a simulated release/Pairing
side-effect, plus altered-live-secret, altered-receipt and withheld-release
rejection. This is not a live KH/IR two-server Connected result, and does
not change RC9's `activation_allowed=false` gate.

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

#### Exact RC9 reuse of original Foreign installer and fresh-core Journal — 2026-11-15

The existing U-OPTI Sanaei/3xUI Foreign continuation now recognizes
`2.0.0-rc.9` **only** in the selected fresh option-2 scope, paired to the
exact Smite source `e7f76185e9a7da51d7069d5d0a829dc192cc1e06`.
It still calls the **original** `docker_3xui_install` and original
`smite_install_sanaei_attachment_stage` (private pending snapshot,
original owned Compose, database RO probe, rollback on interruption),
without a second installer or a new user-facing option. A fresh
RC9 source mismatch is rejected before Docker calls. Independent
RC7 and stable/standalone behavior is retained.

The same original `smite-foreign-gateway.sh` functions now admit
RC9 only with an exact scope, original fresh Compose owner,
Standard HTTPS/443 and a private Panel packet. It retains the already
running paused/strict Node with its prebound exact control path, refusing
recreation or fallback to legacy anonymous metadata. Wrong source,
missing source, nonselected or wrong profile is rejected **before**
packages, certificate, Nginx or container changes. The existing
shared renewal-hook compensation and staged Nginx rollback are unchanged.

In `smite-rc6-install-journal.py`, a **new RC9 Foreign Core transaction
can now be rehearsed only under a disposable alternate root**, reusing
the existing journal `begin/status/commit/rollback` ownership model,
and binding only nonsecret Panel-issued node scope (Panel/Foreign
domains, name, Node ID and exact control path). It rejects source,
scope or role mismatch and deliberately refuses creation under
the real server root `/`: this is **not** an available live installer.
The original Host and Identity recovery journals remain the later
stage owners, including one-time grant/replay/identity preservation.
The public option 2 still returns
`FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`.

Independent GitHub Actions for these code integrations finished
**3/3 PASS**: [43702421794](https://github.com/aghajani82/u-opti/actions/runs/43702421794).
The practical blockers remain source-owned live Core executor + approved
signed release, binding Core ownership to Host/Identity stage hand-off,
and an actual two-host Iran↔Foreign authenticated Connected/rollback test
on a disposable KH server. No change to `main`, existing Iran RC9,
Grandoptical, FRP 20182, Backhaul or active Sanaei.

#### RC9 Core→Host→Identity unified handoff — disposable CI PASS

The **original** `smite-rc6-install-journal.py` fresh Foreign
Core owner is now cross-checked by the **existing**
`smite-unified-foreign-host-recovery.py::rehearse_option2`
before *any* Sanaei RO mount, Gateway HTTPS/443 or signed one-use
Panel redemption. The offline handoff compares the original durable
Core journal (COMMITTED, exact RC9 source, private nonsecret domain/name/
Node ID/control-path scope), its current on-disk Smite state using
the **same existing** packet↔state admission, and its Compose-owned
exact pinned Docker Node image. A partially installed Core, tampered
journal, stale/mismatched source, swapped RC7 Node image or unexpected
Docker owner fails before even an injected host stage callback.

CI uses the actual Core Journal with a fake Docker runner, the existing
Host-stage Sanaei/Gateway journal and real signed HMAC identity promotion
against a simulated Panel, not a second installer or replacement
credential system. A valid exact RC9 owner advances to
`FOREIGN_OPTION2_OFFLINE_READY` and retry preserves the one identity,
the original Sanaei/Gateway stages and the same signed Panel receipts.
It **never** claims live Connected or activation. The original Core
Journal's `root` ownership requirements are **unchanged** on
deployed hosts; CI adapts UID checks only inside an unprivileged
private test fixture. Full 3/3 CI PASS:
[43703802341](https://github.com/aghajani82/u-opti/actions/runs/43703802341).

This is **not yet** a real-host option-2 executor. The public option-2
branch still HOLDs before host writes, and the source's signed release
policy still has `release_approved=false` and
`activation_allowed=false`. Next: connect the existing fresh
Core→Host→Identity operations to the public menu under an independently
approved signed release and verified per-stage compensation. Then
qualify **both** roles from the same immutable U-OPTI head.
The user has expressly authorized rebuilding the **disposable Iran
test host** for this final coordinated fresh-install trial; do not
touch production Grandoptical or assume the earlier Iran RC9 receipt
already exercises the latest trial code.

**Iran/Foreign compatibility requirement at final trial:** after
option 1, signed registration/agent auth must remain signed, Foreign
schema must be READY without manual migration, and the **existing**
Foreign-install and trusted-origin Panel capabilities must be enabled
only once the exact signed Foreign release and host-runner rollback
gate are approved. The prior real Iran outputs showed both flags OFF,
and we do **not** prematurely toggle them. The operator must then be
able to reserve the KH Node, issue the private one-use packet and
complete option 2 without returning to separate menu tools.

#### Original Panel packet → RC9 Foreign Core Journal — 2026-11-15

Closed a practical one-choice Foreign mismatch **without inventing a new
packet, credential flow or installer**. The original U-OPTI Core Journal
`smite-rc6-install-journal.py` now accepts the **path** of the same
private, owner-only `foreign-install-packet.json` that the existing
Smite Panel ForeignInstallDialog issues. It calls the original
`smite-unified-foreign-gateway-plan.py::precore_fields` verifier and
derives **only** Panel/Foreign domains, Node name/ID and exact HTTPS/443
control path for its durable Core owner. No installation code or Node
secret is passed as a shell argument, printed, or copied into the Core
receipt. Wrong file mode, expired grant, conflicting operator-supplied
scope, wrong image and unapproved signed release fail before Core writes.

An internal helper in the **existing**
`modules/smite-install.sh` supplies that packet to the original
Journal `begin` only after the **existing**
`smite_install_unified_signed_pair_review` gate and exact RC9 source and
Node digest checks. It is **not an alternative installer or menu item**:
the public option 2 is still
`FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`, and the original
Journal continues to **deny RC9 Foreign begin at root `/`**. The
CI-approved/synthetic release response is confined to an isolated
shell fixture; no real host is authorized by this change.

Existing tests now cover the original 4-field user input unchanged,
the 5 nonsecret Core owner fields, TTL and private-file checks, exact
packet-to-Core-to-Host-to-Identity same-key continuation, and release
denial before either packet parsing or Journal writes. GitHub Actions
PASS 3/3:
[43705948424](https://github.com/aghajani82/u-opti/actions/runs/43705948424).

**Remaining release blockers are concrete and unchanged:** (1) complete
the real-root Foreign stage executor with step-owned restoration and
interrupted same-option resume, reusing the previously audited
Core/Sanaei RO/HTTPS Gateway/Identity functions; (2) independently
approve/publish and verify a signed image pair for **host activation** —
the current `smite-unified-trial-pair-admission.py::verify` explicitly
returns `host_activation_allowed=False`; (3) coordinate the existing
Iran Panel Foreign-install/origin trust flags (both were OFF) with that
approved release; and (4) prove actual signed Iran↔Foreign Connected,
identity continuity and rollback on the two disposable servers. A
matching fresh Iran rebuild is acceptable at that point; it is not
needed for code-only CI work. Protect Grandoptical/FRP/Backhaul.

#### Foreign RC9 Core COMMIT and read-only same-option resume — CI PASS

The ORIGINAL `smite-rc6-install-journal.py` now refuses a fresh
Foreign RC9 `COMMIT` unless the owner-private Node `.env` matches the
**same** Panel-issued nonsecret scope: exact Node name/role, HTTPS/443
Panel address, the immutable `/smite-node/<32 hex>` control path,
paused outbound registration, strict HMAC Agent authentication and
the initial unattached Sanaei inventory baseline. The checks are
read-only; the preexisting Core rollback/quarantine still owns data.

The original Journal also exposes a read-only `resume-foreign`
disposition, specific to the same signed RC9 Foreign owner and
**pre-enrollment Core stage**. It reports `CORE_PENDING` only when
no Core bytes or containers have yet been installed,
`CORE_READY_TO_COMMIT` only after a complete verified pinned Node,
and `CORE_COMMITTED` only for the exact retained owner. Partial
files, wrong source/Node, mismatched Compose project/config-files,
unhealthy or restarted Node, incorrect control address, or expired/
wrong private Panel packet HOLD **without restarting or deleting
anything**. New secret material is never copied into the Core
Journal or printed in a status receipt.

The original Host/Identity journals **remain responsible for later
Sanaei RO, Gateway/443, one-use HMAC enrollment, activation and
stage-owned compensation**; these read-only Core states are not a
replacement for those journals.

The existing internal selected Foreign Core handoff also captures the
**installer's parent BASHPID before shell command substitution**, so
its original journal retains the real process ownership lease instead
of accidentally recording the transient Python helper's PID.
An isolated test verifies that exact same-option installer PID and
that an unapproved signed release performs zero packet/Core commands.
No new systemd service, menu entry, listener, identity or live
host permission was added. No public option-2 activation has
been authorized. Tested with the actual Core Journal and its
pre-existing signed Host/Identity integration tests, including
interruption, drift, rollback refusal, exact packet reissue,
idempotence and no Node recreation. CI **3/3 PASS**:
[43707732046](https://github.com/aghajani82/u-opti/actions/runs/43707732046).

The next practical boundary is to wire the **real-root** original
Core execution and durable Host/Identity stage operations to the
single Foreign option-2 selection with safe interruption recovery,
then prove original stage rollbacks and independently publish the
host-activation approved signed pair. Current RC9 trial admission
still returns `host_activation_allowed=False` and the menu still
returns `FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`.
On the disposable Iran side, the original Foreign schema is READY;
existing Foreign enable/origin-trust flags will be coordinated only
with that release. No test VPS rebuild is needed for the offline
change. Production Grandoptical, FRP, Backhaul and `main` remain
untouched.

#### RC9 Foreign Core selected-stage execution and recovery — CI PASS, live HOLD

The existing `modules/smite-install.sh` now contains an **internal**
`smite_install_unified_foreign_core_stage` that reuses the original
`smite_install_unified_foreign_begin_core_from_panel`, original
`smite_install_foreign_node`, and original
`smite-rc6-install-journal.py begin/resume-foreign/commit` in a
**single stage**. One exact, private Panel-issued grant supplies the
Core scope. When no owner exists, the original signed release gate
is checked *before* any Core work and the signed pinned owner begins.
For a retained owner, original `resume-foreign` determines one of
three unambiguous states:

- `CORE_PENDING`: install using the existing Foreign Node installer
  and the same Compose project; ambiguous partial Core remains HOLD.
- `CORE_READY_TO_COMMIT`: commit the already verified original Node
  without running `docker up` again.
- `CORE_COMMITTED`: retain the exact signed Core, skip Node install
  and Core commit, and proceed to the later owned stages.

The internal helper prints only exact, nonsecret Core receipts; the
informational `UNIFIED_FOREIGN_IMAGE_PAIR` line cannot corrupt its
parsed owner ID. It never prints an installation code or regenerates a
Node identity. The previous stage Journal validates source,
control/443 URL, strict paused mode, immutable digest, project,
Compose file and health; different/missing/untrusted output fails.
The CI harness tests this *same shell function* with a disposable
journal path and mocked host commands. It verifies signed-release
HOLD before any action, first Core run, empty interrupted retry,
no-recreate ready/committed branches, stage errors, bad owner and
symlinked grant. Actual production journal and signed host gate are
unchanged. [Full CI 3/3 PASS](https://github.com/aghajani82/u-opti/actions/runs/43711626279).

**Important:** the function is still an **internal building block**,
not wired into the public Foreign option 2. The public menu still
returns `FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`.
The existing signed trial pair continues to deny host activation,
and the original Journal still disallows a new RC9 Foreign owner
under the real host root `/`. No VPS can be installed from this
partial code.

**Next closure work:** the original stage-owned Host Sanaei/Gateway
journal and Identity pairing journal must become a complete safe
*real-root* continuation, including a resume after Sanaei changes
the initially disabled inventory setting, interruption compensation,
one-time grant expiry/reissue for the SAME Node, and post-promotion
identity/HTTPS proof. Only then can the public option 2, separately
signed host-activation approval, and Iran Panel Foreign capability
flags be coordinated for a matched two-host test. No main merge,
rebuild or production modification is authorized by this CI result.

#### Exact Core → original Sanaei RO → original HTTPS/443 Gateway handoff, including interrupted RO resume — CI PASS

The original `smite-rc6-install-journal.py` now supports an explicitly
**read-only, post-Sanaei resume disposition** for a *previously COMMITTED*
exact RC9 Foreign Core. The original fresh pre-Core `commit` still
requires `SMITE_SANAEI_INVENTORY_ENABLED=false`; the later change to
`true` cannot masquerade as Core installation progress. For the
later, distinct `--attached-sanaei` read-only resume, both the original
Compose/project/digest/health and current Node `.env` still have to
match the immutable signed Panel-issued name, Panel HTTPS/443 domain and
exact control URL, paused registration and strict auth. In addition,
the managed Sanaei DB source must be a registered instance path and
the *effective running Node* must have exactly one RW=false bind mount
to `/run/smite-sanaei-ro` plus the matching paused/strict/managed
inventory flags. Incorrect or writeable mounts, inconsistent DB paths,
unverified inventory mode, and uncommitted Core all HOLD with no host
write or Node restart.

The **existing** `smite_install_sanaei_retained` is the precondition for
passing this read-only option in the shell coordinator. It checks the
original effective RO bind, healthy Node, registered source and
read-only SQLite schema probe. If it cannot independently prove
the attachment, the Core Journal is invoked in its original strict
mode and still refuses the changed inventory. Tests prove the
authorized `false → true` transition is **not a reinstall**, while
negative cases HOLD and retain the original Core identity.

The internal selected-stage coordinator now directly invokes the
existing `smite_install_unified_foreign_core_stage` followed by
`smite_install_unified_foreign_after_core`, which already owns the
original Sanaei and Foreign Gateway step-level compensation and exact
signed packet/443 checks. The helper explicitly stops at
`FOREIGN_IDENTITY=AWAITING_ORIGINAL_SIGNED_PAIRING` and
`FOREIGN_CONNECTED=NOT_PROVEN`. It intentionally does not invent a
separate installer, claim completion, bypass the one-time HMAC
enrollment, or enable public option 2. The original Core owner
process PID now survives nested shell command substitution and is
covered by an isolated regression. CI **3/3 PASS**:
[43713219769](https://github.com/aghajani82/u-opti/actions/runs/43713219769).

**Still HOLD, not authorized for new KH VPS install:** the public option
2 is deliberately not wired to this internal sequence and signed RC9
host release remains default-off. The final real-host Host/Identity
journal bridge, per-stage restart/rollback proof, Panel Foreign-install
and trusted-origin flags on the matched Iran RC9 release, and actual
Iran↔KH authenticated Connected/runtime-activation receipt are not yet
proved. The current retained Iran install was not rebuilt or changed;
`main`, Grandoptical, FRP 20182 and Backhaul remain unchanged.

#### Original Foreign Signed Pairing read-only handoff — CI acceptance

The existing selected option-2 **internal** Core→Sanaei-RO→Gateway-443
sequence now refuses to output its pre-pairing readiness receipt unless
the *original* Smite foreign-install promotion verifier approves the
CURRENT exact same private Panel-issued `smi1` packet, the existing
Foreign `state.env`, the retained Gateway receipt, the Nginx shared
3xUI/HTTPS control site and the current paused/strict managed Node
`.env`. The check reuses
`smite-unified-foreign-gateway-plan.py::precore_fields` (fresh TTL),
`::admit` (source-bound role/name/Panel/Foreign/443), and the
existing `smite-foreign-install-promotion.py::verify_gateway`.
It is exposed only as an internal **read-only** flag on the existing
Gateway-plan helper; the Bash one-choice pre-pairing coordinator
requires the exact nonsecret receipt
`FOREIGN_SIGNED_PAIRING_PREFLIGHT=EXACT_READ_ONLY`.

No one-time code is included in CLI arguments, state or output. Neither
the new read-only check nor its tests call the Panel redeem endpoint,
create/overwrite an identity, change Node Compose, install Sanaei,
restart Nginx or enable runtime. Incorrect source, expired or locally changed
packet, changed Gateway path, untrusted settings, or a Node no longer
in strict HMAC mode all HOLD *after retaining the already verified
Core/Sanaei/Gateway stages*. This preflight is local and does **not**
claim to prove remote Panel revocation or live connectivity. Existing CI tests exercise the actual
original parser + original promotion verifier in isolated fixtures
and the actual one-choice shell function with mocked host commands,
including fail-closed order and no false Connected receipt.

The shell handoff now also repeats the **original running** immutable
Node image-ID, owned Compose, paused/strict Node and `smite_install_sanaei_retained`
witness (effective RW=false bind plus real read-only SQLite schema)
immediately before invoking this packet/Gateway/Node admission.
A valid Gateway file cannot stand in for a verified Sanaei mount.
The only successful result is still *ready for original signed
Pairing*, not `Connected`. Three independent workflow jobs PASS:
[43715236360](https://github.com/aghajani82/u-opti/actions/runs/43715236360).

**Still unimplemented / not authorized:** a real-root, release-approved
Identity journal and one-use Panel redeem/HMAC proof handoff inside
the public option 2, stage-owned identity rollback/replay continuity
and runtime Connected proof. The old
`smite-unified-foreign-identity-phase.py` remains **disposable-only**
and the public option 2 continues
`FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`; the signed
RC9 manifest explicitly does **not** approve host activation. The
Iran Panel Foreign-enable/origin trust flags should be coordinated
only with that gate and tested from a matching fresh Iran+KH install.
Do not rebuild Iran yet, modify Grandoptical/FRP/Backhaul, or merge
to `main` on these offline results alone.

#### One-use Panel grant renewal and post-expiry original HMAC continuity — 2026-11-15

The **same original** selected Foreign option-2, Host stage journal,
private packet-intake utility, and Identity `rehearse_transaction`
have been exercised **end to end**, not just as separate unit tests.
After Sanaei RO and HTTPS/443 Host stage commit, an intentionally
failed signed Panel proof leaves `IDENTITY_INTENT` with exactly one
staged HMAC key; no live identity is written and Host/Gateway must not
be installed again. A different grant before expiry is rejected. At
expiry, the original private `smite-unified-foreign-packet-intake.py`
accepts **only a new one-use code for the exact same reserved Node,
Panel, Foreign origin and control path** with an existing unmodified
Host owner checkpoint. The next original Host and Identity journal
runs adopt the new packet, prove enrollment via the existing Panel
HMAC status endpoint, and promote the **same** key. The subsequent
retry calls *only* authenticated Panel status, never another redeem or
Sanaei/Gateway install. All receipts remain private and code/secret
free. Full CI PASS:
[43716754099](https://github.com/aghajani82/u-opti/actions/runs/43716754099).

The existing offline Host `rehearse_option2` also had a separate
continuity gap: after an original **COMPLETED** Host and promoted
Identity, expiration of the old bearer packet prevented the same
option from re-verifying its identity. Its **disposable-only** path
now permits an expired packet *solely* when BOTH original schema-2
Host and Identity journals are complete, match the exact unchanged
private packet hash/scope/expiry, and the live identity exists.
Current original Core, RO Sanaei and HTTPS/443 witnesses must all
still pass, followed by a **fresh signed HMAC Panel proof** from
the original identity module. The old bearer code is not redeemed,
no host stages rerun, a revoked signed proof still HOLDS, and an
incomplete INTENT or corrupted receipt can never bypass expiry.
Original Node secret and all Host services are unchanged. Full
CI 3/3 PASS:
[43717050291](https://github.com/aghajani82/u-opti/actions/runs/43717050291).

These are **offline/disposable acceptance tests**, not a live
activation or restored Connected claim. On a real KH server the
public option 2 and the original signed release/real-root Journal
are still HOLD. The next actual gate is a root-owned,
release-approved deployment of the ORIGINAL Identity journal and
the already integrated Host stages, followed by activation/replay
rollback proof and matched fresh Iran+KH `Connected`. The Iran Panel
Foreign enable/trust flags remain unapproved until that release.
No new features, changes to `main`, production Grandoptical,
FRP/Backhaul or existing servers.

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
