# Unified Smite installation — trial plan and continuation record

Updated: 2026-11-14 (Asia/Tehran)
Status: OFFLINE INTEGRATION VERIFIED — SIGNED RELEASE / LIVE HOST ACTIVATION BLOCKED
Branch: trial/unified-smite-install
Base: aaf863a38eb256ed96d7ea5594f83a62cb3619fd

## Current release decision (authoritative; older checkpoints below are historical)

- **User-facing IR option 1:** official signed Smite RC7 source `9a1270b3...`. Its existing installer verifies the exact panel/node images against the rollback journal and performs the co-located Iran node signed enrollment. It is **not** the newer unified Panel release.
- **User-facing Foreign option 2:** explicit `FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES`. No partially installed Node, code redemption or host mutation is permitted until the complete released chain is present.
- **Unified signed Smite pair:** companion `aghajani82/Smite` source `de0677d015a00160970ed57bba565adc4fafe8eb`. The [Smite build](https://github.com/aghajani82/Smite/actions/runs/43585094525) published the pair and the [U-OPTI signature review](https://github.com/aghajani82/u-opti/actions/runs/43596467307) independently verified both digests and the workflow identity. The artifact manifest matches the pinned manifest byte for byte, SHA-256 `61149003bbf966445bb25d0f94a4e666bb57b4544a5565703af55b30afa41c84`. Both `release_approved:false` and `activation_allowed:false` remain enforced.
- **IR unified Panel transaction:** `smite-unified-panel-stage.py` performs private staging; existing `smite-unified-panel-transaction.py` permits **disposable-root rehearsal and config-only rollback**, not production apply. Recent tests compare complete registered Node rows, pending Pairing codes, inbound Panel nonces, grants, signed identities and replay against sealed snapshots. This protects existing local Iran and new Foreign identities.
- **Foreign internal sequence:** one hidden private Panel-issued `smi1` packet, exact HTTPS/443 and Node name; original Sanaei read-only attachment; Gateway no-recreate witness; same signed Pairing/rollback entry points; durable one-key redemption and promotion. Its assembled internal helpers are tested offline but **not yet permitted from the public option 2**.
- **Real cross-repository offline proof:** Panel staging/rehearsal, the actual pinned Smite SQLite grant issue and idempotent redemption, and refusal to roll back Panel config after enrollment have passed alongside the existing ASGI/HTTPS/HMAC tests. This is NOT a live two-server Connected result. Verified U-OPTI CI: https://github.com/aghajani82/u-opti/actions/runs/43382017487
- **What still blocks release:** independently approved, rebuilt and signed paired Panel/Node release; exact release image/journal consistency for both choices; safely reviewed *production* Panel transactional apply/rollback; public option-2 wiring and interrupted-install recovery; isolated two-server tests proving signed bidirectional Connected and retained FRP/Sanaei/Backhaul; explicit final operator acceptance. No installation command or merge to `main` until all are proven.
- **Operational exclusions:** no changes to live IR/Grandoptical, Sanaei, Node IDs, FRP `20182`, Backhaul, firewall, or existing runtime; do not recreate running Nodes or restart FRP as part of trial.

### Continuation checkpoint — signed Iran heartbeat-aware Panel review (2026-11-14)

**Purpose:** close an existing pre-production Panel migration gap, not add
an installer option. The already-staged RC7 → unified Panel review formerly
either (a) failed on every legitimate signed Node heartbeat/replay nonce or
(b) on the real-root path skipped comparing the live databases entirely.
The existing `PanelTransaction.review()` now uses the already-established
`PanelStage.live_baseline_report()` when evaluating a real-root sealed
stage. It requires a COMMITTED+COMPLETE Iran install, original Compose
ownership, a healthy old signed runtime, installed admin, loopback Panel
HTTP 200 and certificate-verified local HTTPS/443 before considering
database continuity. The report **still says signed two-way =
NOT_CHECKED**; this separate active signed proof remains a requirement
for a production executor after any future Panel change.

A new internal, **read-only** `PanelTransaction._live_continuity()`
compares the original, private WAL-consistent Panel and replay database
snapshots to their current counterparts. It permits ONLY:
- monotonic presence changes of fresh/expired nonce records for the same
  existing signed Iran identity, without changing the expiry of a retained
  nonce, in the known inbound/replay schemas;
- `last_seen` updates for that same existing Iran Node;
- changes to the existing Iran Node's `frp_connected` /
  `frp_remote_port` **telemetry only**, not metadata role or Pairing state.

It HOLDS on any changed encrypted identity, signed Pairing code,
registration/role/status, additional reserved Foreign Node, new Foreign
grant/origin, arbitrary metadata, replay ownership, invalid schema, or
unknown nonce owner. The original offline/rehearsal rollback remains
**strict** and is not weakened. The new read-only review does not lock,
stop, recreate or mutate a running Node and cannot authorize an
already-active release. A future production executor MUST repeat runtime
and database evidence **under its own exclusive transaction lock**,
perform independently approved release admission and actual HMAC probes
after Panel reload, and HOLD if provenance/grants changed in the meantime.

The original `tests/test-smite-unified-panel-transaction.py` now
injects ordinary signed Iran heartbeat/FRP telemetry, nonce expiry and
replay transitions, as well as malicious/unsafe identity, node,
Pairing, grant, schema and gateway-witness changes. The existing GitHub
suite exercises these tests together with real disposable Docker
Panel upgrade, rollback and Foreign grant issue. This is **read-only
admission proof**, NOT a live Panel apply/rollback or two-host Connected
claim.

### Continuation checkpoint — one sealed source and real disposable Foreign grant after Panel upgrade (2026-11-14)

This iteration builds on the worker's newer release-source synchronization
and the already-green real-Docker Panel Compose rollback suite; it adds
**verification across existing components**, not another installer or UI.

1. `tests/test-smite-unified-trial-pair-admission.py` now cross-checks the
   **single committed manifest** against the Panel stage, Panel transaction,
   Foreign runtime admission, existing Foreign witnesses, Node Pairing image
   reference, selected installer and both GitHub workflow pins. It covers
   **source SHA + SHA-256(manifest) + immutable Panel/Node digests** and asserts
   `release_approved:false`, `activation_allowed:false`. Deliberate
   wrong-Panel and wrong-Node negative controls must fail. The official
   RC7 pair remains different and unchanged.
2. The existing Foreign client CI now rejects a `companion-smite` checkout
   if its actual Git commit differs from `source_commit` in the sealed
   manifest, even if someone later changes the checkout ref alone.
   Cross-repository Python/ASGI tests therefore cannot silently run against
   another Smite source after updating an image pin.
3. The existing isolated `tests/test-smite-unified-panel-docker.sh` now
   repeats the tested RC7 → newer Panel transition **after** it has already
   proved that an empty-grant rollback to RC7 preserves the original
   Iran Node container ID/start time and SQLite identity. In the renewed
   candidate Panel, it invokes the **actual bundled Smite Foreign grant
   store**, issues a scoped `smi1` grant for a newly reserved Foreign Node,
   and verifies the original Iran identity and container still exist.
   It never prints the one-use secret and **does not** revert the Panel
   after a grant exists. The whole Docker project is disposable, has no
   attached network or published ports, and is destroyed after the test.
4. GitHub Actions test evidence for the verified code:
   https://github.com/aghajani82/u-opti/actions/runs/43601511950
   (three jobs successful, including image-signature + real-Docker
   Panel upgrade/rollback and grant issuance). This is **offline/disposable
   proof only**, not approval to deploy either trial image on Iran or KH.

**Next release-critical actions:** review a production-safe, explicit
Panel-only apply/rollback executor using existing preimages and journal;
verify the new Panel through real signed Iran HMAC/Replay and HTTPS/443
witnesses before enabling Foreign issuance; separately approve a **release**
with exact signed Panel/Node images (trial signature is insufficient);
only then wire option 2 Foreign into the already-existing host
Sanaei/Gateway/identity/activation recovery chain and prove live two-way
Connected on isolated hosts. Do not weaken the hard `HOLD` or merge to
`main` on the strength of these disposable tests.

### Read-only evidence for the existing Iran installation

On an Iran host with the current trial verifier already installed, run as root:

```sh
python3 -B /usr/local/lib/u-opti/modules/smite-unified-panel-stage.py --verify-live-baseline
```

The report checks the completed install journal, Compose owner and signed
runtime, retained Iran identity and replay, an existing admin, the loopback
Panel endpoint and certificate-verified local HTTPS/443. It prints only
allowlisted values. A branch-only `INSTALL_REF` reports `UNKNOWN` for the
installed U-OPTI SHA. Use the original install output's `Verified revision`
when available.

**Field baseline accepted on 2026-11-14 for the existing Iran host.**
The operator reported exact installed U-OPTI revision
`8d9ec336af10b60c488d4d90a78325f1b4998c94`, and the install journal
reported `panel-iran / COMMITTED / COMPLETE` for Smite source
`9a1270b31e8d44f13d09b71ab6b9798410b09c12`. Both pinned RC7
containers were running and healthy in the journal's Compose project.
The loopback Panel API and certificate-verified local HTTPS/443 each
returned HTTP 200. Pairing was `ENABLED`, credentials `STAGED` and
Replay enrollment `READY`. The operator's Panel screenshot showed
`node-ir` as `Connected`.

At the installed revision the installer requires signed Node check-in,
the Panel-to-Iran HMAC status probe and the local replay probe before
advancing to `COMPLETE`. The journal supplies evidence that these gates
passed at install time. Repeat the signed probes after a Panel upgrade
to establish current bidirectional evidence for that version. The next
repository milestone is the reviewed transactional Panel upgrade for
Foreign grant issuance. The public Foreign option 2 remains on hold
pending the approved release and the live upgrade and connectivity gates.

### Panel upgrade recovery verified in isolation

The existing Panel transaction now serializes rehearsal and rollback on
the same sealed stage. Retry verifies completed checkpoints and continues
from the interrupted step. It can recognize an already-written candidate
when the checkpoint write was lost. A completed step with changed files,
pairing data or Replay state holds the transaction for review. Explicit
rollback restores owned configuration and retains the database and replay
history. The integration suite runs the pinned Smite migration against
the same disposable Panel database, interrupts it after the private
backup is saved, resumes with that same backup and exercises actual
Foreign grant issue and redeem. Both operations block later config rollback.

The production executor still needs to coordinate the running Panel and
Nginx on a disposable two-host environment before use on Iran. In
particular, capture the actual Compose owner and running Node ID, keep
grant ingress closed through migration, verify the candidate with local
and TLS probes plus signed checks, and record fresh runtime witnesses.
Signed check-ins and Replay nonces can legitimately advance on a running
host. The isolated database drift rule must not be reused as a live
reconciliation policy without distinguishing those changes from grants,
origin changes and identity changes. Keep the exact signed trial pair
separate from the independently approved release used for live activation.

## Resume/checkpoint design — Iran selected option 1 (2026-11-13)

Operator intent: **press the same option 1 again**, just like resuming a
paused video. Do not reinstall the Panel/Node, reset identity or replay,
or jump ahead when a preceding stage has not been VERIFIED.

The existing `smite-rc6-install-journal.py` stores the Panel domain and
Iran Node name for new option 1 transactions. The same installer verifies
and records the following checkpoints, with Enter to continue after a
newly completed step in an interactive terminal:

1. `PANEL_COMMITTED`: the signed Panel is healthy, answers the local API,
   and matches the original Compose project and domain.
2. `CORE_COMMITTED`: the signed-image Iran Node is running paused/strict
   under the same project and its local broker socket was verified.
3. `GATEWAY_VERIFIED`: the existing Gateway configured and TLS-verified
   `https://<panel-domain>:443/api/status`. This stage follows the paused
   Node because it sets that Node's HTTPS Panel address.
4. `PAIRING_VERIFIED`: the existing local Iran Pairing confirms signed HMAC
   in both directions and retains the original Node ID.
5. `ADMIN_CREATED`: the existing CLI created an administrator and the
   installed Panel's SQLite database contains a valid admin row.
6. `COMPLETE`: the existing optional static UI update was attempted. It
   remains available at the existing menu option 8.

Option 1 uses the original operation lock for recovery. Before the Panel
checkpoint it quarantines the unfinished fresh attempt using the original
rollback and retries with the saved inputs. After the Panel checkpoint it
rechecks Panel ownership and rolls back only an unfinished, unpaired Node:
it removes that stopped container without deleting volumes, quarantines
its files and restores the broker to its inactive/disabled state. The
completed Panel, its database, and the original Compose project survive.
If a Gateway snapshot is pending at `CORE_COMMITTED`, option 1 restores it
before verifying Docker health. Older incomplete journals without saved
inputs still require reviewed recovery. Existing post-core cursors remain
supported.

A returned checkpoint is NEVER trusted alone: a retained Gateway is
reverified by strict local HTTPS; existing signed Pairing/identity is
reverified using the original idempotent `--complete-local-ir-install`;
an admin is verified by a read-only database query. A changed completed
stage HOLDs instead of silently overwriting a live service.

Safe crash boundaries:
- After core committed, before Gateway → resume at Gateway.
- Between Gateway and signed Pairing → reverify Gateway, retry only Pairing
  with retained identity (never issue a second Node on an existing receipt).
- During/after admin creation → check actual admin record before running
  `smite admin create`; distinguish **absent** (eligible to create) from
  **unreadable/invalid DB** (HOLD). Never reset a password on retry.
- After completion → verify Gateway/Pairing/Admin and report already
  complete; never needlessly repeat the cosmetic UI patch.
- Before Panel commit → roll back the partial Panel and retry with the
  saved domain and Node name.
- After Panel commit, before Node commit → roll back only unfinished Node
  changes and restart at Node setup with the same Panel.
- Foreign option 2 is still intentionally `HOLD_BEFORE_HOST_CHANGES`
  pending a separately approved signed unified release. Apply the
  SAME journal principle to that existing path only after its complete
  identity/Pairing/rollback transaction has been released and tested.

Verification: `tests/test-smite-integrated-ir-flow.sh` exercises all
stage/error paths with zero host changes, and the **existing**
`tests/test-smite-rc6-install-journal.py` checks durable cursor order,
Docker/Compose/role drift refusal, legacy/foreign exclusion, active
installer refusal, retained identity and SQLite admin proof. The latter
now runs in the existing trial CI with sudo on a disposable filesystem.
This is not evidence of real two-server Connected, nor permission to
install on production.

## Gateway stage-local rollback without another menu (2026-11-13)

**Implemented and tested in the SAME selected option 1.** The existing
`smite-gateway.sh` is reused; its internal stage snapshot helper now
lives behind `smite_install_ir_gateway_stage`. The snapshot is taken
*before* starting Gateway package/certificate/Nginx work, in a root-only
directory under the **existing** RC7 install journal. Original file
contents/modes and absence markers are synced before publishing the
receipt. No separate wizard, option or parallel Gateway engine exists.

When any part of the Gateway step fails (early package/Nginx preparation,
write, invalid TLS, final HTTPS health witness, Node address switch,
renewal hook, state receipt or checkpoint write), the original owned
Gateway config and ACME file, FRP SNI allowlist, TLS stream/backend/map,
renewal hook and Gateway state are restored. Nginx is validated and
reloaded if it existed. The original **paused, unpaired** Node's
`PANEL_ADDRESS` and running state are verified; if Gateway changed that
runtime, only the SAME journal-owned fresh Node may be recreated to
restore the pre-stage configuration, never a signed production Node.
`IR_GATEWAY=ROLLED_BACK_RETRY_OPTION_1` is printed only after the
compensation is observed, and `GATEWAY_VERIFIED` is NOT recorded.

If rollback itself fails, `CRITICAL`/HOLD is shown, the private
snapshot remains and **no later stage starts**. After interruption,
the same option 1 calls the existing journal's `gateway-recover-ir`
admission before the healthy Node witness; a pending CORE snapshot is
restored first, whereas a snapshot left behind after a *committed*
Gateway checkpoint is discarded only after matching the exact owner.
An unexpected signed Node, different Compose owner, unsafe snapshot or
independently modified existing FRP SNI allowlist refuses compensation
instead of overwriting user data or breaking an active tunnel.

**Scope/limitations:** this compensates the Gateway's owned runtime
configuration, NOT automatic removal of downloaded apt packages or a
Let's Encrypt certificate already issued. Those are safely reusable
preparatory artifacts. Pairing uses verified identity-safe recovery and
Admin uses a read-only existing-row check to avoid rekeying or duplicate
creation. Foreign option 2 remains signed-release gated.
The current proof is **disposable offline failure injection**, not a
real production power-loss or two-host Connected test.

CI: `tests/test-smite-ir-gateway-stage-rollback.sh` runs with root-owned
temporary Nginx/Node/journal fixtures and deliberately fails in the
middle, at final TLS verification, at checkpoint write, during reload,
and with unexpected signed Node/FRP changes. The existing Iran stage
and original journal recovery tests also run. No live hosts touched.

## Iran → Panel → Foreign: one-choice audit, exact existing integration points (2026-11-13)

This section overrides old historical "next step" notes below. It records what
is **actually wired** versus what is only tested offline; do not infer a release
from green CI.

| Phase | Existing function/code | Current admission and tested outcome |
| --- | --- | --- |
| Iran selected option 1, fresh host | `smite_install_selected_fresh panel-iran` and `smite-rc6-install-journal.py` | Official RC7 source, pinned Panel+Node signed digests and exact commit journal; verified before starting services. Resumes the original owned Panel or Node checkpoint |
| Iran Gateway and local Node | `smite_install_finish_local_ir` → `smite_gateway_configure_panel`, `smite-node-pairing.py --complete-local-ir-install` | HTTPS/443 and signed bidirectional IR check before administrator creation. No extra Pairing menu action. Failures HOLD and preserve identity |
| Iran admin and appearance | `smite_install_create_admin` → existing `smite_install_ui_action apply` | Admin after signed IR check; optional static-only appearance now occurs last. UI failure points to existing menu 8 without abandoning connected Node |
| Administrator reserves Foreign Node | Companion Smite `ForeignInstallDialog`, signed grant store and explicitly migrated SQLite tables | Tested real Smite admin-issued `smi1` code, scoped 2-hour grant, exact origin/path and durable one-key redemption **in offline ASGI/DB tests**. New Panel image is NOT in official IR option 1 |
| Foreign selected option 2 | `smite_install_selected_fresh foreign` | **HOLD_BEFORE_HOST_CHANGES**: the companion signed trial image is not an approved release; cannot run the combined option on a live host |
| Foreign private intake / core | Existing `smite_install_unified_foreign_capture_packet` and `smite_install_foreign_node` | Same single hidden packet supplies panel domain, foreign domain, name and exact :443 control URL before first paused boot. Tests only; not menu-wired |
| Foreign post-core Sanaei + Gateway | `smite_install_unified_foreign_after_core` → existing Sanaei attach and Gateway configure | Now uses existing signed Pairing **release decision first**, then rechecks 2-hour grant freshness BEFORE Sanaei/Gateway. Wrong/expired/missing packet, unknown image/Compose or TLS state HOLD. No Node recreation on exact retained state; tests only |
| Foreign identity, signed activation and recovery | Existing `smite-foreign-install-client.py`, `smite-foreign-install-promotion.py`, `smite-node-pairing.py` | Private HMAC proof/identity/rollback verified offline, but **production Foreign promotion/activation and recovery are not yet menu-wired**; no real Connected claim |
| Backhaul and FRP 20182 | Pre-existing independent U-OPTI/Smite engines | No new tunnel, no restart or modifications by this project |

Verified trial CI for this audit: https://github.com/aghajani82/u-opti/actions/runs/43384638985
(two jobs green at `eeb720e9e36664ccdd8168cb4aeff1cbfe407b36`).
Companion Smite trial has independently green tests; its signed trial-pair
manifest still explicitly denies production activation.

**Remaining release-critical tasks, not repeated code redesign:** independently
approve a new exact signed Panel/Node pair that supports Foreign grants;
update the original install journal/source/image pins in both choices;
review and implement production-safe Panel schema/config transaction with
identity-preserving rollback (current Panel executor is fixture-only);
wire the existing full Foreign client/promotion/signed activation to option 2
with a retained recovery contract; verify fresh and interrupted IR/Foreign
setups on isolated hosts, including two-way Connected, RO Sanaei DB, FRP
20182 and other services untouched; then obtain operator acceptance and
merge. There is no approved one-command combined installation yet.

## User-approved outcome
- Iran: one installation entry installs Panel, HTTPS/443 Gateway and Iran Node; complete only after authenticated local Node enrollment and bidirectional checks, then administrator sign-in.
- Panel: administrator creates a Foreign Node, specifies its name and gateway domain, and obtains a single-use installation credential, proposed default validity 2 hours.
- Foreign: one entry installs Node, TLS/Gateway, installs or selects existing Sanaei, attaches its DB read-only, redeems the credential and activates signed runtime.
- No separate IR terminal origin approval or manual Pairing activation in the normal flow.
- Credential expiration affects unused enrollment only; an enrolled Node remains valid.
- Expired credential: issue replacement for the same pending Node and continue, without reinstalling.
- Existing Sanaei and standalone Sanaei installation remain supported.
- Preserve signed identities, replay protection, exact image provenance, Nginx 443 policy and existing FRP/tunnels.
- Main remains unchanged until Mohammad tests and explicitly approves the trial. Do not merge based solely on CI.
- No live host actions, rebuilds or deployment authorized by this engineering task.

## Current verified baseline
- U-OPTI #199 already integrates fresh IR Gateway + secure local enrollment + administrator creation. Reuse it, do not duplicate.
- #201 restores attachment of an existing Sanaei DB after Foreign pairing staging. User ran it successfully and reported Foreign Node Connected.
- Foreign setup remains split among install, Sanaei attachment, Gateway, IR origin approval, redemption and activation.
- Sanaei installer relaunches the top-level menu; orchestration must return to its caller instead.
- Several shell helpers return success after an error/pause: fix error propagation before composing them.
- Fresh installer deliberately refuses partial/existing state. Safe continuation must validate committed install ownership and actual host state, not just a progress flag.
- Signed RC7 runtime images are immutable. Editing Smite main alone does NOT update the running image. New enrollment backend requires a tested, signed trial image pair and matching U-OPTI pins.

## Current implementation / release checklist

- [x] Separate U-OPTI and Smite trial branches, reviewed source locks and signed trial GHCR image pair.
- [x] Admin/MFA-bound Foreign grant issue/revoke/redeem, additive SQLite tables, origin checks, and Foreign UI in companion Smite trial.
- [x] One-use two-hour `smi1` packet, no-echo terminal intake, durable identity, lost-ACK reconciliation and strict HTTPS/443 binding.
- [x] Reuse existing Sanaei attachment, Gateway, signed Pairing, image/Compose validation and rollback helpers in internal trial code.
- [x] Signed official RC7 Iran source/image/journal coherence preflight and original one-choice Iran flow.
- [x] Real cross-repository **offline** Panel rehearsal → Foreign grant issue/redeem → protected rollback, including pending Pairing/nonces and replay drift.
- [x] Trial GitHub CI for the above offline contracts; most recent signed-source and code proofs are linked in this record.
- [ ] Independently approve/publish a non-trial exact signed Panel+Node release (current trial activation is explicitly OFF).
- [ ] Adapt **existing** install journal and production Panel lifecycle to that approved release, with reviewed rollback after interruptions (do not use fixture rehearsal as production executor).
- [ ] Wire approved release to Iran option 1 and full Foreign option 2, without new public choices or extra operator steps.
- [ ] Test on isolated real Iran/Foreign hosts; verify Sanaei DB RO, TLS/443, encrypted identity retention, real two-direction `Connected`, FRP 20182 unchanged and rollback under failures.
- [ ] Resolve final CI/PRs, gain explicit acceptance of tested release and then merge safely to `main`.

## Required enrollment design
Authenticate administrator issuance using existing admin/MFA protections. Bind the grant to an exact pending Node and normalized public gateway domain; derive/validate the restricted HTTPS/443 control path. Never authorize arbitrary URLs, localhost/private/link-local destinations, redirects, wildcard origins or unrelated nodes based on a bearer code. Protect against DNS rebinding and SSRF using the existing reviewed transport policy.
Keep raw credential out of logs, shell argv, persistent plaintext plan files and URLs. Store a hash for server-side redemption. Enforce single-use and expiry atomically. Define retry semantics for a lost redemption response before implementation; never silently generate a new identity.
Authorize only this Node's origin, not a global unrestricted allowlist. Preserve HMAC and durable replay protection.
Do not copy upstream anonymous registration or disabled TLS verification.
Connection success requires Node-to-Panel and Panel-to-Node checks, not container running alone.

## Test matrix
Fresh IR; fresh KH with new Sanaei; KH with existing Sanaei; multiple Sanaei selection; interrupted download; interrupted core install; interruption after TLS/mount/credential redemption; code expired/reused/revoked/wrong role/domain; lost response; concurrent redemption; unknown compose/image drift; active Node rerun; DB read-only verification; FRP coexistence and unchanged identities; rollback failures retained for recovery.

## Continuation instructions
1. Read this file and git log on trial/unified-smite-install; inspect open related PRs and current main before changes.
2. Read repository AGENTS.md if present. Do not treat memory as evidence of completed code.
3. Continue first incomplete milestone. Keep each meaningful verified checkpoint committed to this branch.
4. Update status, tested SHA, tests, blockers and exact next step in this file.
5. Companion Smite changes go to an isolated trial branch, never main.
6. Do not publish an install command while dependency images or end-to-end verification are missing.
7. Do not claim work continues when no session is running; this record enables the next session to resume.

## Historical checkpoint — initial implementation
First implementation checkpoint (trial only): Sanaei attachment returns 2 for refusal/failure/cancellation, 3 when installation returned but attachment is pending, and 0 only after verified attachment in the signed lane. Legacy non-signed installer result is preserved. A UI pause no longer masks failure, including successful rollback after an unsuccessful attachment. No new combined installation entry is enabled yet.

Validation: 10 isolated result-code scenarios PASS; existing integrated IR ordering/failure suite PASS; 8 RC7 Foreign pairing tests PASS; shell syntax PASS. The new test is wired into integrated-ir-install CI. Full remote CI and real host installation are not yet proven.

Audited Smite fork main: 5e7a289071e446345ac27e4255994daf3446430a.
- panel/app/routers/node_pairing.py: issue default 600 seconds, API max 900; reserve accepts name/role only.
- panel/app/node_pairing_store.py: hashed single-use code, atomic consumption, encrypted per-node secret generated server-side at redemption. A lost response can strand the enrolled identity; no retry-safe install grant exists yet.
- panel/app/signed_node_origins.py: trusted origins are a private read-only file, deliberately not writable from any API. Removing the IR terminal step needs an explicit new administrator-authorized trust path, not a chmod or a generic API write to that file.
- modules/docker-3xui.sh: successful installer execs a fresh U-OPTI menu. Must gain a scoped return-to-caller mode before automatic DB attachment.

Exact next step: design and test a separate Foreign installation grant with 7200-second default and bounded expiry, exact domain/node binding, and retry-safe identity delivery. Implement it on a companion Smite trial branch without changing existing RC7 pairing semantics. Specify migration and rollback for the new trusted-origin source. Then produce signed trial images and integrate the U-OPTI flow. Do not merely increase existing pairing TTL or bypass origin checks.

No trial installation command is released: combined setup and its backend are not ready. Main and all live hosts remain unchanged.


## Continuation checkpoint — Foreign grant store (2026-11-12)
Companion branch: https://github.com/aghajani82/Smite/tree/trial/unified-smite-install
Latest companion implementation SHA: 4cff129306b456ea4390c337f0bf293e9030d11f
Detailed contract: https://github.com/aghajani82/Smite/blob/trial/unified-smite-install/docs/unified-install-trial.md

Implemented separate inert grant store and explicit additive migration. New codes default to 7200 seconds with a 7200 maximum; old RC7 codes retain 900-second maximum. Grant binds UUID, exact Foreign name, approved normalized domain and generated /smite-node/<32-hex> path. Reissue preserves same pending Gateway path. Client persists a random secret BEFORE redemption; encrypted identity, origin and code consumption commit atomically. Exact retries acknowledge the same key even after signed check-in. Different-key retries, role/domain/name drift, expired or revoked codes fail. An enrolled identity outlives grant expiry. Concurrent contenders cannot rekey. No endpoint or runtime trusted-origin fallback enabled.

Validation: 19 new SQLite tests PASS; 17 existing pairing-store tests PASS; 6 recovery-admission tests PASS; git diff --check PASS. Companion CI ran successfully on initial store commit eaacf68ed3fdf8c14071e69b6b00b86f0d18a1d7; check latest commit's CI separately before claiming latest-head success.

Next exact work: gated HTTP issuance/revocation/redeem adapters using existing administrator/MFA and trusted TLS ingress, capability/schema probe, generic secret-free failures; gated origin lookup with file/DB conflict and revocation checks; safe network DNS pinning. Then UI, client durable-secret persistence/signed lost-reply recovery, snapshots, signed trial images, and U-OPTI orchestration. Merely raising legacy TTL or trusting supplied metadata remains prohibited.
No hosts touched. Main unchanged in both repositories. No installation command yet. Resume from this checkpoint rather than recreating grant storage.


## Continuation checkpoint — authenticated HTTP adapters (2026-11-12)
Companion Smite SHA: b0e9262ef15e337779ba0d6d46256f1940fbed85
Implemented default-OFF /api/foreign-install capability, issue, revoke and redeem routes. Actual current admin JWT/auth-version/MFA checks protect admin operations. Redemption requires trusted TLS ingress proof plus grant; only a nonsecret acknowledgement is returned. Strict payloads, 8192-byte streamed body bound, no-store headers, sanitized validation and SQL failures. Schema probe uses read-only SQLite and never migrates or creates a missing DB. No network requests or origin-file writes occur in these routes.
SMITE_FOREIGN_INSTALL_ENABLED remains false. New Nginx ingress routing, DB origin trust, UI, client and signed images are NOT enabled/implemented yet.

Validation: 13 HTTP tests + 9 existing HTTP pairing + 3 MFA + 19 grant store + 17 legacy store + 6 recovery = 67 local tests PASS. Both latest-head GitHub jobs pairing-store and foreign-install-http SUCCESS on the exact companion SHA above.

New verified finding: signed_agent_transport.py uses certificate validation, no redirects and trust_env=False, but still resolves DNS through httpx without public-IP pinning. The previous plan's assumption that a reusable reviewed DNS-pinning mechanism existed is not established. Add/test one for DB-approved Foreign origins before activation; syntax-only domain validation is insufficient.

NEXT: gated DB-approved origin reader with consumed-grant/unrevoked-identity/name/role matching; deterministic denial on file/DB conflicts; retain existing file-origin behavior; public-IP DNS resolution pinning with original TLS SNI and hostname validation; negative private-IP/rebinding/redirect tests. After that UI and client durable-secret/lost-response handling, snapshots, signed image packaging and unified installer. Continue on the same branches, never main. No host install command yet.


## Continuation checkpoint — approved origins and pinned DNS (2026-11-12)
Companion Smite SHA: dd36201afe40f9edefd3aa3a9ed1afbb03ec69aa
Branch: trial/unified-smite-install (both repositories). Main unchanged.

Implemented separate default-OFF SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED.
Read-only database lookup requires a consumed, unrevoked grant, exact identity/name/
role/origin/control-path and matching consumption/approval/identity timestamps.
Expired consumed grants do not disconnect an established identity. Unsafe or
conflicting approval files, revoked identities and missing committed origin records
fail closed. Existing file approvals remain read-only; matching file/DB origins
still use the new network policy. Schema migration remains explicit.

NodeClient uses public-IP DNS pinning for database-approved Foreign requests.
Reject all DNS results if any address is non-public/special; connect to a vetted
literal IPv4/IPv6 address with original Host, SNI and certificate hostname validation.
No redirects, environment proxies, request retries or hostname re-resolution.
HTTPCore pinned at 1.0.9. Existing file-only Iran/Foreign and FRP paths are preserved.

Verification: 20 new tests + 97 existing tests = 117 local PASS. Both remote
pairing-store and foreign-install-http jobs SUCCESS on the exact SHA above.
Tests exercise actual HTTPX/HTTPCore connection/TLS setup with an offline backend;
certificate failure is simulated, not a live public-CA or two-host deployment test.
Local Smite checkout reconciled to the published commit with clean working tree.

Rollback: disable issuance only, retain origin trust and grant/origin/identity
records for established nodes. Do not disable trust or delete tables on active
enrollments. Export/recovery tooling remains outstanding. Neither flag is enabled
on live hosts. No signed trial image or runnable integrated installer yet.

NEXT EXACT WORK: admin UI for pending Foreign reservation + domain + issue/reissue
and safe one-time code presentation; durable client secret staging and signed
lost-reply verification; explicit schema/ingress provisioning and snapshot/recovery;
signed trial image pair + exact U-OPTI digest pins; unified installation orchestration.
Do not recreate the grant store/HTTP/origin/DNS work. Continue these trial branches.
No merge to main until Mohammad tests and approves. No host installation command yet.


## Continuation checkpoint — installation information UI (2026-11-12)
Companion Smite SHA: 9e4e9c4a6c21aab2d7e818075a922326b67aee2c
Implemented Foreign installation dialog behind readiness capabilities (issuance +
origin trust + browser HTTPS/443). New-node flow accepts name/domain, reserves the
Foreign Node and issues a two-hour grant. Pending rows allow same-node code reissue;
connected nodes do not offer new enrollment. Existing disabled/older Panel UI stays.

Copyable packet contract: protocol=smi1, panel_url (browser HTTPS origin), node_id,
node_name, origin, control_url, installation_code, expires_at. Validate identity,
domain/path/code/expiry before display. Secret lives only in mounted component;
expiry/close removes it. Explicit copy and pending-code revocation are supported.
Closing does not revoke the code or erase clipboard copies. No executable installer
command is displayed because client and signed images are still outstanding.

Two-request behavior: reservation success + issue failure keeps the same reserved
Node on retry. Unknown/lost reservation reply blocks blind retry and requires
refresh/reconciliation from the Node list, preventing automatic duplicate nodes.
If issuance succeeded but its reply was lost, reissue replaces the pending code.
Server-side protections still forbid replacing an already paired identity.

Validation: 9 offline React interaction tests PASS, strict scoped TypeScript PASS,
production Vite build PASS, 13 HTTP + 6 reservation + 4 legacy UI tests PASS.
All FOUR GitHub jobs SUCCESS on exact companion SHA above: frontend-compile,
api-capabilities-and-ui-invariants, foreign-install-http, pairing-store.
React tests are offline; no browser visual or live two-host installation test.
Smite local checkout reconciled to the published commit; working tree clean.

NEXT EXACT WORK: U-OPTI packet client with strict schema/endpoint validation,
root-only durable secret staging and fsync before redemption; retry the exact same
key after lost response; signed identity verification after grant expiry. Handle
expired pending grants without reinstallation. Then explicit schema/ingress setup,
snapshot/recovery, signed trial image pair and full unified installer wiring.
Continue same trial branches; no main merge or host actions. No install command yet.

## Continuation checkpoint — durable client and signed recovery (2026-11-12)
Companion Smite SHA: ef0e089dfede930817fa35df4f21dcb2f33a8e1e
Added modules/smite-foreign-install-client.py as an unexposed library: strict smi1
packet validation, duplicate-JSON-key rejection, exact HTTPS DNS/443 scope, private
staging directory, O_NOFOLLOW directory walk, owner/mode/hardlink checks, flock,
fsynced complete temporary file + no-overwrite link + directory fsync before I/O.
The grant code is memory-only. Persistent stage binds Panel/Node/name/Gateway/path
and a random secret. Same-scope reissue/retry reuses it; a changed scope, unsafe or
corrupt stage, existing live identity or expired fresh grant fails closed.

HTTPS uses one vetted public DNS address, original TLS hostname/SNI, system CA
verification, no environment proxy/redirect/automatic request retry, 8 KiB response
cap. Ambiguous redemption is followed by a new HMAC proof request to the companion
/api/node-control/installation-status endpoint. Existing expired stage uses proof
only. Proof must match every scope field. Failure retains the staged key; no rekey.
Panel proof checks the paired key, durable replay and committed grant/origin evidence,
works with issuance disabled and after grant expiry, and refuses revoked identities.
It does NOT activate/register the Node; only replay bookkeeping is written.

Tests: 15 client unit/connection-boundary tests PASS, 6 companion signed recovery
tests PASS, 1 cross-repository real ASGI/SQLite integration PASS. Integration commits
redemption, deliberately loses acknowledgement, proves after expiry with the same
key, then verifies revocation blocks recovery. Existing relevant HTTP/origin/inbound
regressions also PASS locally. CI checks the exact pinned companion SHA above.
No real public TLS or two-host deployment was exercised. DNS resolver timeout still
uses the OS resolver; connect/read timeout is 15 seconds, not a whole-operation SLA.

Boundaries: caller must run as root in production and provide a previously prepared
private staging directory and the real runtime identity path. No CLI/menu/distribution
manifest entry is enabled, no live identity is promoted, no compose/runtime change.
The new library intentionally refuses any existing live identity; post-promotion
resume requires a separate validated transaction. Existing legacy enrollment intact.

NEXT EXACT WORK: explicit Panel migration and Nginx ingress for redeem/proof; safe
staged-to-runtime identity promotion with rollback and post-promotion resume; schema/
secret/replay snapshots; signed trial images and exact pins; combined Iran/Foreign
orchestration and Sanaei return-to-caller; full fresh-host test before install command.
All changes remain on trial/unified-smite-install; never merge main before user test.

## Continuation checkpoint — Gateway-bound identity promotion (2026-11-12)
Added trial-only `modules/smite-foreign-install-promotion.py`; it is a
library, not a published install command or menu option. Existing
`smite-foreign-install-client.py` and the companion Smite SHA
`ef0e089dfede930817fa35df4f21dcb2f33a8e1e` remain unchanged.

The promotion adapter checks exact Panel hostname, Foreign Gateway domain and
control path against root-owned private U-OPTI state, Foreign Gateway state and
paused/strict managed Node .env. It rejects mismatched Node name, alternate
Gateway path, legacy/active Node or ambiguous/untrusted files. The .env's
managed parent may be non-writable 0755; identity parents must remain 0700.

A previously staged per-Node key is NEVER regenerated. A fresh signed
installation-status proof and exact scope check precede a 0600 no-overwrite
write of the Node's existing JSON identity schema (version/node_id/node_secret).
A fsynced PREPARED journal precedes the live file; a fsynced COMPLETED journal
follows it. Both remain private for crash recovery. Retries reconcile an exact
owned file without replacing it; mismatched or pre-existing live credentials
fail closed. A completed journal with a missing live identity is quarantined,
not silently restored. Replay stores, existing identities, Compose, Nginx,
FRP, Sanaei, Gateway and containers are untouched.

The helper is deliberately NOT called by any installer yet: safe staging to
identity does not establish replay continuity, runtime activation or
Panel-to-Node connectivity. No new role/flag, host install command or server
activation is enabled. Future orchestration must execute the signed trial
Node replay provisioning and bidirectional connectivity checks after this
boundary, preserving identity and replay upon any failure.

Validation: 14 offline promotion tests (including loss between prepared/link
and link/completed, live identity collisions, exact Gateway binding, tampered
journal, expired grant, no-overwrite, unsafe paths and non-writable managed
Node directory) added to push/PR trial CI. The workflow also runs the original
15 client tests and the real cross-repository ASGI recovery integration test.
Full expanded CI: workflow run 43194041014 SUCCESS at exact code commit
`0e11dcf2aba63ef8931919dce2ef8785fc5611d9`; 14 promotion tests,
15 existing client tests and the cross-repository ASGI recovery integration all
passed. Intermediate failure was a fixture affected by GitHub runner umask;
an unrelated pip network IncompleteRead was also observed on one earlier run.
No production host or signed runtime test has been performed.
No live TLS or two-host testing has been performed.

NEXT EXACT WORK: create explicit, reversible, signed-trial Panel schema,
trusted HTTPS/443 Nginx ingress for /api/foreign-install/redeem and the signed
/api/node-control/installation-status; make sure ingress proof cannot be
client-forged. Then integrate the promotion adapter with validated fresh KH
installation and replay provisioning, retain FRP and standalone Sanaei,
build/pin signed trial images and run two-host end-to-end tests. Never merge
main or touch live hosts before operator approval.

## Continuation checkpoint — explicit SQLite and tested Nginx 443 ingress (2026-11-12)

Companion Smite SHA `a9a42982ffbfdf1c60c76bf4e08f277616761775`
adds `panel/app/foreign_install_migration.py`: reviewed, explicit and
confirm-required additive grant-table migration after the existing signed
pairing/replay schema. Before first mutation an SQLite-online (WAL-aware)
0600, no-overwrite private backup is fsynced. Partial/drifted structures,
unsafe/symlink/hardlinked databases, ambiguous old backups or invalid
confirmation HOLD. Re-running a verified completed migration is read-only.
Relative `DB_PATH=./data/smite.db` works inside the real Panel working
directory. Existing identities, replay rows and flags are unchanged.
The backup alone is not an adequate restore of active enrollment: the
Panel's independent encryption key and replay history must be preserved.

New inert renderer `modules/smite-foreign-install-panel-ingress.py` admits
only the exact U-OPTI HTTPS backend that already has trusted signed
Pairing ingress. It builds exact, POST-only, 8-KiB, no-access-log locations
for grant redeem and signed installation-status. Redeem injects the
already-provisioned private Nginx pairing header; signed proof and general
root proxy REMOVE client-supplied copies of that header. No wildcard
approval, unpinned origin, unauthenticated registration or other public
port is opened. Existing FRP, signed pairing and HTTP root behavior remain
apart from stripping the otherwise untrusted ingress header. Unknown
locations, partial markers and drift HOLD. No host write, Nginx reload,
Panel restart or feature-flag enable is wired yet.

Verification: 10 new offline renderer tests and one disposable Nginx TLS
proxy test with a local mock backend plus existing 14 identity-promotion
tests, 15 client tests and real cross-repository ASGI enrollment recovery.
GitHub Actions run `43196231871` SUCCESS on exact U-OPTI SHA
`e7ef316394bbf239cbc210c314075740421ea0c4`.
Companion Smite 13 migration tests and existing HTTP/auth regressions
SUCCESS on SHA above (Node Pairing Atomic Store run `43196483303`,
Admin UI run `43196483549`). No real public TLS, signed image
activation, production host or full two-node installation has been tested.

NEXT EXACT WORK: build/pin verifiably signed trial Panel/Node images and
implement authorized transactional host provisioning with safe config
reconciliation/rollback; then connect foreign installer to the staged
identity promotion, signed replay, Gateway and Sanaei, verify Connected
in both directions and test full fresh-host/expired-token/recovery cases.
Never merge main or instruct live installation before Mohammad acceptance.

## Continuation checkpoint — real signed trial Panel/Node digests (2026-11-12)

Smite companion source SHA:
`b865be93e22153c60769f6329e6e55e781494ded`.
Completed Smite Actions run
[43197803544](https://github.com/aghajani82/Smite/actions/runs/43197803544)
SUCCESS, all 4 jobs. A separate branch-scoped workflow performed
preflight, built linux/amd64 images, pushed ONLY two immutable untagged
GHCR digests, signed each with keyless Cosign and verified the signatures.
Neither the official tag release workflow nor `main` was modified.

Exact published trial pair:
- Panel: `ghcr.io/aghajani82/smite-panel@sha256:1b03d0d865ba4abd6fe45899d2ccd6d34f300b4804acd2c6690a52b68fb26289`
- Node: `ghcr.io/aghajani82/smite-node@sha256:587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483`

Archived candidate `registry-pair.json` SHA256 independently computed
from artifact `13934051359` and matched to Smite CI output:
`e13f0708b1de5eef112b955f4b6efe4e1efa5520d404458646bb6e1e76c96608`.
The exact JSON is checked in at
`modules/smite-unified-trial-registry-pair.json` (NOT an installer
activation manifest or an official release candidate). Do not silently
replace either digest with a newer trial branch image on retry or update.

Independent tool
`modules/smite-unified-trial-pair-admission.py` validates the separate
operator-supplied manifest hash, source commit, exact branch, both images,
Sigstore trusted-root SHA, OIDC issuer and workflow identity, role/commit
annotations and the exact digest of each signature; no Docker or host write.
The real public GHCR check (not a mock) passed U-OPTI workflow
[43198492747](https://github.com/aghajani82/u-opti/actions/runs/43198492747)
with `independent-ghcr-cosign=SUCCESS`. The existing standalone unit
tests and Foreign enrollment workflow are also retained. The official
tag-based release verifier remains deliberately incompatible with these
experimental branch signatures.

Scope: trial images are linux/amd64, no auto-deploy, no feature flags enabled,
no Node/Panel recreate and no changes to live IR/Grandoptical/FRP/Sanaei.
The existing U-OPTI installer still selects its previous reviewed RC7
runtime; merely pinning this pair does NOT enable the new Foreign APIs.
This checkpoint is a signed-image provenance proof, NOT first-boot or
two-node Connected proof. Do not provide a trial host install command yet.

NEXT EXACT WORK: add an opt-in, transactionally rollbackable
Panel-side configuration executor that admits the exact digest pair,
snapshots SQLite + replay + private keys, migrates Foreign grant schema,
applies the reviewed Nginx 443 grant/proof routes, enables gated Panel
config only after all checks, and verifies the new Panel runtime.
Do not clobber the existing FRP/Backhaul 443 routes or restart unrelated
containers. Then integrate Foreign install with strict signed replay,
Gateway/Sanaei and full two-way Connected verification. Test from clean
hosts and interrupted/rollback states before asking for Mohammad's
approval to merge `main`.

## Continuation checkpoint — signed Iran Panel prepare-only transaction (2026-11-12)

Added `modules/smite-unified-panel-stage.py` with dedicated offline/host
fixture regressions in `tests/test-smite-unified-panel-stage.py`. This is
**STAGING ONLY**. It is not connected to the installation menu and does not
recreate Panel/Node, change an active Compose/Nginx, migrate SQLite schema,
enable an API, alter FRP/Backhaul, or issue a Foreign installation code.
Host activation and rollback have **not** been implemented.

Exact reviewed Smite images remain pinned:
- Panel: `ghcr.io/aghajani82/smite-panel@sha256:1b03d0d865ba4abd6fe45899d2ccd6d34f300b4804acd2c6690a52b68fb26289`
- Node: `ghcr.io/aghajani82/smite-node@sha256:587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483`
- Smite source: `b865be93e22153c60769f6329e6e55e781494ded`
- Manifest SHA256: `e13f0708b1de5eef112b955f4b6efe4e1efa5520d404458646bb6e1e76c96608`.

A real future host staging invocation requires root and an explicit
`STAGE-SIGNED-UNIFIED-PANEL-TRIAL` confirmation. It re-runs the independent
**real Cosign** verification of both digest signatures with the pinned
Sigstore root *before* creating any private transaction directory. There is
no CLI parameter to bypass image signature checking. The special mocked
admission callable is exercised only by the isolated Python tests.

The preflight requires exactly the existing signed/paired IR Panel in
Standard mode, existing private Panel pairing master key, matching Nginx
ingress token and matching Panel domain, exact reviewed RC7 Panel image in
the existing Compose service, managed U-OPTI TLS backend, unmodified
signed Pairing/FRP routing, and root-owned, non-writable configuration
paths. It also requires the existing Iran Node identity and its persistent
replay marker/HMAC key binding with the real replay SQLite store and a
verified existing Panel pairing/replay schema. Missing, partially migrated,
hardlinked, symlinked, forged or conflicting state causes a HOLD.

Only after all preflights pass is a **new, never-overwritten, mode-0700**
directory `/var/lib/u-opti/unified-panel-trial-stage` created. It holds
0600/fsynced snapshots of Panel .env and Compose, U-OPTI role state,
Nginx backend and pairing-header secret, pairing secrets, local Iran Node
identity and replay enrollment marker. Online SQLite backups are created for
both the Panel database and the Iran replay database, including committed
WAL transactions and existing Node identities/nonces. The private copies'
journal mode is normalized to DELETE and connections are closed before
they are sealed. Candidate files separately contain the exact Panel digest,
two Foreign installation feature flags and reviewed exact POST-only Nginx
ingress. They remain inert; the running Node/Panel and live DBs are untouched.

A terminal `PREPARED_ONLY` journal records file hashes, exact source and
both signed images, explicitly setting `live_write=false`. The status
verifier checks all private files and rejects extras, tampering, unknown
SQLite sidecars and incomplete crash journals. Interrupted preparation is
quarantined rather than silently retried or erased. It does not assume the
live host is still unchanged at a later apply time. No secrets are printed.

CI: 19 disposable stage/preflight/backup/replay/negative tests plus the
existing 14 Foreign promotion tests, 15 Foreign enrollment tests, real
cross-repository ASGI integration, reviewed Nginx template tests and a real
disposable Nginx TLS header-injection check were all green at source commit
`8e6ed177fa41c8eabada4b3beff7438ff3fa5912`: U-OPTI Actions
[43200772845](https://github.com/aghajani82/u-opti/actions/runs/43200772845),
both jobs SUCCESS. Tests mock the signed-review result only for isolated
fixture runs; real GHCR signature checks were independently proven in run
43198492747. No staged host invocation or server changes occurred.

NEXT EXACT WORK:
1. Implement a separately confirmed **apply/rollback executor** that
   re-verifies the signed pair and stage, takes a fresh immediately
   pre-apply Panel and Iran replay snapshot, detects live preimage drift,
   uses isolated candidate Nginx syntax/Compose review, and performs
   strictly ordered migration / exact Panel-only image & feature-flag
   activation / Nginx reload with durable rollback checkpoints.
2. On failure restore only operator-owned changes; never recreate the
   Iran Node, rotate identity, reset replay, restart FRP or modify
   the existing tunnel 20182. Any failure to prove a safe rollback
   must quarantine state and HOLD for manual recovery.
3. Then integrate the Foreign installer: consume Panel-issued two-hour
   grants, securely persist same key across interruptions, configure
   foreign Gateway/SSL/Sanaei database read-only inventory, provision
   signed replay and prove bidirectional Connected status.
4. Verify complete fresh-host and interrupted/recovery workflows on
   disposable hosts and obtain Mohammad's approval before changing
   `main` or any live Iran/Foreign server.

The `main` branches of both repos remain unmodified. No installation
or recovery commands are approved for production at this checkpoint.

## Continuation checkpoint — isolated Panel transaction and rollback rehearsal (2026-11-12)

Added `modules/smite-unified-panel-transaction.py` and
`tests/test-smite-unified-panel-transaction.py` **only on
`trial/unified-smite-install`**. This is deliberately a production
**read-only review + disposable-root rehearsal**, NOT a privileged live
apply or rollback command. Its exposed CLI accepts only `--review`,
verifies the prepared stage, re-verifies the exact signed trial Panel/Node
image pair with Cosign, requires all current private security/config
files to match their original staged preimages, checks the paired Iran
identity/replay store, rejects unexpected pre-existing Foreign grant
tables and verifies all candidate bytes against the sealed preparation.
A drifted file or unsafe stage yields HOLD without changes.

Only a Python caller explicitly injecting a disposable root and a
fixture capability may exercise `rehearse` or `rollback_rehearsal`;
root `/` is hard-denied. No Docker, Nginx, firewall, systemd or host
network commands are executed in either rehearsal. The tested sequence
uses the exact staged Panel image/Compose candidate, a fixture-local
additive SQLite schema migration, the two prepared Foreign feature flags,
and the exact reviewed HTTPS ingress configuration. The simulation
writes a **separate private, fsynced intent/completion journal** at
`var/lib/u-opti/unified-panel-trial-rehearsal` within the disposable
fixture root; it never writes into the sealed original staging
directory. Abrupt failures after Compose, schema, flags and Nginx can
be resumed for an explicit, repeatable offline rollback.

Offline rollback restores **only** the exact three owned config
preimages (Compose, Panel env, Nginx); the additive grant tables remain
present and neither the Panel SQLite DB nor Iran replay DB, HMAC keys,
signed identity or encrypted node identity is rewound. It refuses
unknown config drift, changed sealed DB backups, new Foreign
reservations, consumed/pending grant records, changed signed identity
rows, changed grant table shapes and any new replay nonce. A broken
journal or unexpected symlink yields HOLD. Rollback interruptions can
be retried without overwriting the preserved source stage.

**CI PASS:** 20 new offline transaction rehearsal/recovery/negative
tests, alongside 19 prior stage tests, 14 promotion tests, 15 client
tests, signed trial pair tests, real disposable Nginx HTTPS tests and
cross-repository ASGI integration. The companion Smite checkout in
this U-OPTI workflow is now pinned to the **exact previously published
and independently signed image source**
`b865be93e22153c60769f6329e6e55e781494ded`
(instead of the older prototype commit). GitHub Actions
[43203203311](https://github.com/aghajani82/u-opti/actions/runs/43203203311)
SUCCESS, both jobs; last tested source
`cf5a3949a6074f33a2caee50f5131b475c8eb290`.
The independent real GHCR/Cosign check remains the verified
[43198492747](https://github.com/aghajani82/u-opti/actions/runs/43198492747).

CRITICAL SCOPE: No production executor, actual container rollout,
running Panel/Node switch, real Nginx reload, host SQLite migration,
real two-server connectivity test, or automatic production rollback
exists yet. The fixture engine must NEVER be treated as permission
to activate live services. All code and signed digest pins remain
on trial branches; `main` and active hosts remain unchanged.

NEXT EXACT WORK: implement and independently gate the **actual
operator-confirmed Panel-side executor on two disposable hosts**.
Before any live write it must inspect actual Compose active overlays,
prove the current signed RC7 Panel image and Iran Node health,
recheck signatures/current file preimages, take NEW online Panel and
Iran replay/identity snapshots, validate candidate Nginx syntax and
Docker Compose offline, and enforce an exclusive operation lock and
durable recovery journal. The future executor must run the reviewed
signed trial Panel image with Foreign grants OFF, migrate the Panel
schema using the matching image source, verify it, enable flags and
apply the 443 routes only after health checks. Failure must revert
only operator-owned files and Panel image/flags, never rewind
enrollment or replay, and HOLD if rollback cannot be proved safe.
No Node recreate, FRP/Backhaul restart, existing 20182 route change,
or Sanaei DB modifications. Then wire one-command foreign install,
prove signed two-way Connected and operator-approve real host tests
before merging `main`.

## Explicit two-menu-choice acceptance and first Foreign continuation wiring (2026-11-12)

The user clarified the *final menu semantics*:

- **Option 1, Install Panel + Iran Node:** one selection on Iran installs
  pinned Smite Panel and co-located Iran Node, prepares HTTPS/443 + SSL
  Gateway, performs signed local pairing automatically, proves Iran Node
  appears Connected, then creates the Panel administrator. No separate
  Pairing option 2, no separate Gateway menu and no second install.
- **Option 2, Install Foreign Node:** one selection on the foreign server
  installs its signed Node and Nginx HTTPS/443/Let's Encrypt Gateway,
  installs Sanaei 3x-UI Docker or selects an existing trusted instance,
  attaches the Sanaei SQLite database read-only, consumes the *exact*
  two-hour, one-use credential issued by the Panel for its Node/domain,
  promotes and activates the existing staged key without rekey,
  provisions signed replay and proves authenticated bidirectional
  Connected. No return to a submenu and no manual SSH step on Iran.
- Both selections must retain original configuration, signed keys,
  FRP, Backhaul, XHTTP, Sanaei and existing instances. On failure,
  leave a truthful HOLD/recovery record, never mark partial work done.
  Do not use a second silent installation path alongside existing U-OPTI.

Current audited reality: the selected fresh **Iran** entry already chains
the existing `smite_install_panel_iran` and
`smite_install_finish_local_ir` gateway, signed local enrollment and
admin creation. Its regression is `tests/test-smite-integrated-ir-flow.sh`.
The selected fresh **Foreign** entry currently ends after core Node
installation (installed/paused), and its separate menu options 4
(Sanaei) and 6 (Gateway) do not perform the new `smi1` Foreign
grant redemption/runtime promotion. This is **not yet a one-choice
Foreign installation**, even though all its principal components exist.
The signed trial images are verified but not yet selected by the
production installer, which still pins the prior RC7 release pair.

First integration bridge committed **only on this trial branch**:
`docker_3xui_install` recognizes the scoped
`UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER=1` and returns successfully after
the existing installation instead of replacing the U-OPTI shell with
its historical Docker submenu. Without the variable, the standalone
Sanaei installer keeps its original PTY reload behavior.
`smite_install_unified_foreign_sanaei` in `modules/smite-install.sh`
reuses the existing Foreign option-4 installer and verified read-only
DB attachment: if there is no existing registered Sanaei instance,
the first invocation installs it and the helper **automatically invokes
the same attachment once more**, returning success only after verified
attachment. A missing/partial/failed attachment, unknown return code,
wrong role, old/legacy version or non-fresh transaction is HOLD. It
does not rebuild or rekey a Node itself. The helper is intentionally
**NOT YET CALLED** from option 2: actual integration must be conditional
on signed trial image provenance and a validated secure Foreign
Gateway + grant redemption + runtime promotion path before it is
advertised as complete.

Isolated regression `tests/test-smite-unified-sanaei-continuation.sh`
exercises 8 success/cancellation/error cases and validates the scoped
legacy PTY behavior. The trial workflow also runs the existing
`test-smite-integrated-ir-flow.sh` and
`test-smite-sanaei-result.sh`, plus the previous signed/ASGI/Nginx
checks. All tests require no live server access.

**NEXT (do not recreate components):**
1. Bind selected fresh installer to exact signed unified trial Panel
   and Node digests with branch-specific Cosign admission, preserving
   official RC7 verifier and standard installer.
2. Build a fail-closed Foreign menu **option-2-only coordinator** using
   existing core, Sanaei continuation, HTTPS gateway, private `smi1`
   packet enrollment, staged key promotion and strict signed Node
   activation; persist journal phases and recover without duplicate
   downloads or a second menu visit. Require exact
   Panel-issued control path; Gateway must not generate an unrelated path.
3. Upgrade the reusable Foreign Gateway and Sanaei helpers so errors
   return nonzero in unified mode. Apply safe Nginx/Compose checks and
   prove two-way Connected at completion; preserve existing traffic.
4. Test the entire one-choice Iran and Foreign user journeys in
   disposable isolated hosts, then on the two approved servers. Only
   after full review and explicit final user approval merge both
   trial branches into `main`.

This is a user acceptance contract and **first composition step**, not
a published install command. Live hosts and `main` remain unchanged.

## Continuation checkpoint — exact Panel grant to Foreign Gateway/SSL (2026-11-12)

The requested final menu semantics remain **one choice for all of Iran** and
**one choice for all of Foreign**, reusing existing installers rather than
building another parallel installer. This checkpoint closes a concrete
Foreign blocker: the existing Gateway independently generated an 8-hex
`/smite-node/<random>` path, whereas the signed Panel installation grant
pins a separate **32-hex** `/smite-node/<path>`. The Node cannot be safely
paired unless the Gateway uses the exact Panel-issued path.

New `modules/smite-unified-foreign-gateway-plan.py` (read-only):
- Reads the exact `smi1` installation packet from a secure 0600,
  regular, owner-matched `foreign-install-packet.json` beneath a
  non-symlink 0700 directory, via the existing
  `smite-foreign-install-client.py` protocol validator.
- Matches Panel domain, Foreign gateway domain, Node name, Standard role
  and fresh reviewed RC7 installation state.
- Rejects a mismatched already-installed Gateway state and any stale or
  competing Smite control location in the selected shared 3xUI/Nginx site.
  Refuses writable or symlinked site ancestors, forged packet contents,
  alternate domain/name, bad path, missing state and unsafe credentials.
- Returns **only the exact nonsecret control path**; it never prints the
  installation code, imports a key, writes Nginx or contacts the Panel.

The *existing* `smite_foreign_gateway_configure` now has a narrowly
opt-in path when a future unified installer supplies
`UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE`. It requires the existing
`SMITE_SELECTED_FRESH=1` and RC7 role, calls this read-only
admission **before any package/SSL/Nginx/Node writes**, and never
generates a second control path. Wrong role, private transport, unknown
site, malformed packet, and canceled configuration result in nonzero
HOLD. In this opt-in mode it also requires successful certificate
renewal hook and durable Gateway state write. Without the scoped
variable, the ordinary standalone Foreign Gateway workflow and
its historical warning-level handling remain available.

The existing `smite_install_unified_foreign_sanaei` created in the
previous checkpoint stays the planned option-2 Sanaei/RO-inventory
building block. **Neither this packet/Gateway branch nor that Sanaei
helper is wired to the public option-2 menu yet.** That must wait until
the installer selects the verifiably signed unified trial image pair
and the private code enrollment, signed replay promotion and Connected
proof have a tested transactional coordinator. This is a read-only
contract plus an opt-in Gateway integration hook, not a shipped
one-command Foreign install or permission for live host execution.

Validation: 10 offline tests in
`tests/test-smite-unified-foreign-gateway-plan.py` (scope, name,
domain, packet permissions, link/path conflicts, shared existing 3xUI
site, secret-free failure), and four real-function pre-write/cancel
scenarios in
`tests/test-smite-unified-gateway-menu-boundary.sh`.
Previous signed pair, durable Foreign client/promotion, real
disposable Nginx HTTPS, isolated Panel staging/rollback, Iran flow,
and Sanaei continuation tests remain in the same CI gate. GitHub
Actions [43225971283](https://github.com/aghajani82/u-opti/actions/runs/43225971283)
SUCCESS (both jobs) on code commit
`22c396cf12d6d3467f308ee4d97c954b2ac82dc9`.

NEXT EXACT WORK:
1. Connect selected fresh option 2 to the **signed unified trial
   images** and verify them independently at installation time. The
   old official RC7 installer currently pins older tag-based images;
   do not substitute trial digest without exact branch signing checks.
2. Implement the single-choice Foreign coordinator using the
   existing Node install, Sanaei-return/RO attachment and exact
   Gateway path admission. Enter the installation code once, retain
   private packet/key across interruption, consume the grant through
   the existing authenticated Panel API, promote the same identity,
   provision strict signed replay and prove two-way Connected.
3. Fix any remaining status/error masking, first-boot recovery gates
   and test fully in disposable two-host environments; preserve
   FRP 20182, existing active Sanaei, XHTTP and signed Node identity.
4. Run user-approved real Iran/Foreign tests; only after success and
   explicit final user acceptance merge both trial branches into
   `main`.

No live host, `main`, Node identity, FRP, Backhaul or Sanaei container
was changed by this checkpoint.

## Continuation checkpoint — internal signed Foreign post-core coordinator (2026-11-12)

The user explicitly wants **menu option 1** to install Panel + Iran Node + Gateway +
signed local pairing + admin in one continuous invocation, and **option 2**
to install Foreign Node + Sanaei Docker/RO DB + SSL/443 Gateway + Panel-issued
single-use enrollment + signed runtime + bidirectional Connected in one invocation.
No parallel installer, no extra menu visits. This is a target, not a claim of
current full-host readiness.

Reused existing `smite_install_unified_foreign_sanaei` (the already-tested
Sanaei installer/RO DB attachment), `smite_foreign_gateway_configure`
(with exact Panel-issued 32-hex gateway-path admission), and the existing
signed trial pair verifier in a new *internal* helper added directly to
`modules/smite-install.sh`:

- `smite_install_unified_signed_pair_review` checks the independently pinned
  trial branch manifest, its SHA256 and both live GHCR Cosign identities/role
  claims against the pinned trusted root. Requires the SHA-reviewed Cosign
  binary. Does not treat a signed image as permission to activate a host.
- `smite_install_unified_foreign_node_image_review` compares BOTH the
  immutable signed trial Node image reference and the *effective running
  image ID* against the local digest image ID. Mismatched/stale digest is HOLD.
- `smite_install_unified_foreign_after_core(packet_path)` requires
  `SMITE_SELECTED_FRESH=1`, `SMITE_INSTALL_PROFILE=clean-rc`,
  exact fresh RC7 Foreign state, loaded existing Gateway helpers, healthy
  strict/paused Node, reviewed active Compose ownership and signed trial
  pair. It verifies the private Panel-issued packet before any additional
  Sanaei/Gateway writes; reuses existing Sanaei install + read-only DB mount,
  then existing Foreign Gateway/SSL setup with the *same exact* control path,
  and verifies the retained Gateway state path still matches the grant.
  Every step returns nonzero HOLD on failure. Even successful completion
  reports only `UNIFIED_FOREIGN_SANAEI_GATEWAY=PREPARED_FOR_SIGNED_ENROLLMENT`
  and `UNIFIED_FOREIGN_CONNECTED=NOT_YET_VERIFIED`.

**Safety boundary:** This helper is NOT called from selected fresh option 2
or from another public menu entry. It cannot be used on the existing RC7
tag-pinned Node: its signed trial image preflight rejects that older digest.
The current Smite trial pair manifest still has `activation_allowed=false`,
the old RC7 pairing/activation module pins the official old Node image, and
the new Foreign grant enrollment, safe identity promotion, strict replay
activation, recovery journal and dual-direction Connected check have not
yet been wired together. Do **not** substitute images or bypass this gate
to force an installation. No real host has been changed.

Validation: New isolated, no-Docker/no-network
`tests/test-smite-unified-foreign-after-core.sh` exercises 14 scenarios:
success ordering; signature failure; wrong image reference or effective
image ID; paused state/Compose drift; incomplete Sanaei; canceled/failed
Gateway; tampered persisted Gateway path; wrong role, mode and Foreign domain.
All reject premature success, identity rotation and secret logging.
The regression deliberately asserts option 2 is still not wired and Iran
option 1 still calls its existing signed one-choice completion path.
Existing signed pair, Foreign credential/identity, isolated Nginx, real
disposable HTTPS and Iran/Sanaei regressions remain green. GitHub Actions
[43233349119](https://github.com/aghajani82/u-opti/actions/runs/43233349119):
**2/2 jobs SUCCESS** on tested source
`f4f0487b3891eda6c90240241e8b9080873f8a8c`.

**NEXT EXACT WORK — do not recreate the existing installers:**
1. Introduce a **trial-branch-only, operator-gated** signed image selector
   for fresh option 1 and option 2, enforcing the new trial OIDC identity and
   exact immutable Panel/Node digests. Maintain the official RC7 selector and
   production default unchanged, and do not deploy until explicit trial
   server readiness and review.
2. Connect the private `smi1` packet via an ephemeral 0700/0600 location
   (prefer tmpfs; no code in arguments/logs); reuse
   `smite-foreign-install-client.enroll` and the existing promotion helper,
   retaining the same secret and proof across lost reply/restart.
3. Extend exact signed replay and activation admission to the new trial
   digest **without weakening the existing RC7 gate**, retaining rollback
   and requiring real Panel-to-Foreign and Foreign-to-Panel authenticated
   Connected. Only then wire the internal coordinator into menu option 2
   and test interrupted resumption on disposable hosts.
4. Run the full two-host installation and recovery matrix; get the user's
   approval for IR/Foreign test deployments, and merge to `main` only after
   both hosts pass and the user explicitly approves.

Keep all changes on `trial/unified-smite-install` in both repos. FRP 20182,
existing Node containers, active Sanaei and both live hosts remain unchanged.

## Continuation checkpoint — one-use Foreign grant to retained identity (2026-11-12)

The existing Foreign code path now has an **internal, disposable-only**
composition phase. This does NOT add a second public installer and does
NOT enable host activation. It reuses the previously validated modules
smite-foreign-install-client.py, smite-foreign-install-promotion.py and
smite-unified-foreign-gateway-plan.py in
modules/smite-unified-foreign-identity-phase.py.

Important order and invariants:
1. Load a private, owner-only 0600 installation packet from a 0700 staging
   directory; validate the exact Panel-issued node, domain and control path.
2. Validate the already-registered managed Foreign state, Gateway settings
   and paused/strict Node environment **before** consuming the single-use
   grant. Wrong destination/configuration cannot consume a working code.
3. Use the existing real Smite grant client to durably retain one node
   secret, redeem against the authenticated Panel API and prove signed
   enrollment. If the HTTP response is lost after the Panel commits, the
   identical node secret is retained and a signed proof reconciles it.
4. Use the existing no-overwrite promotion module with a fresh Panel
   HMAC proof and its PREPARED/COMPLETED private receipts. Once promoted,
   retries skip code redemption and verify only the existing signed proof
   and durable identity receipts, even if the original 2-hour grant expired.
   The grant TTL limits redemption, never the signed runtime identity.
5. No Node startup, Compose recreate, Nginx reload, FRP, Backhaul, XHTTP,
   Sanaei modification, replay reset or Connected claim in this phase.

The Python executable exposes only inert --status. Its internal rehearsal
entry requires an injected transport and an exact private OS temporary
fixture hierarchy. Real host paths cannot be selected, even with the
fixture switch; it is not a production installation/activation command.
No one-time code or node secret is placed in argv, logs or public output.

The 12 offline scenarios in
tests/test-smite-unified-foreign-identity-phase.py cover successful HMAC
proof/promotion, idempotent retry, lost receipt, expired credential,
corrupt receipts, wrong state/Gateway/Node, inaccessible scope, missing
grant, revocation, pre-existing identity and fixture ownership.
The existing cross-repository integration test now additionally issues a
**real Smite Panel grant in isolated ASGI/SQLite**, consumes it with a
simulated lost HTTP acknowledgement, verifies exact signed HMAC replay,
promotes the same Node secret, tests expiry/retry without redemption
and proves revocation blocks another signed proof. It never uses
production domains or live hosts.
Green integration evidence:
https://github.com/aghajani82/u-opti/actions/runs/43236069532

CRITICAL: Do not attach this helper to public Smite Manager option 2 yet.
The signed trial manifest still has activation_allowed=false, the older
RC7 runtime verifier pins a different image, and a real retained-install
replay/runtime activation plus bidirectional Connected probe/rollback is
not implemented for this new signed trial pair. These are explicit HOLD
conditions, not workarounds.

NEXT EXACT WORK: audit and safely extend the exact trial image selection
and Foreign signed runtime activation/replay gates without weakening the
existing RC7 official release flow. Add a durable operation-level lock
and crash recovery across the existing Sanaei/Gateway/enrollment phases,
then connect option 2 and test both ends on disposable hosts. Keep option
1 Iran auto-pairing semantics unchanged. Only after final user-approved
Iran+Foreign host tests merge to main.

## Continuation checkpoint — new signed Foreign runtime read-only gate (2026-11-12)

Goal: bring the *already built* RC7 Foreign pairing/activation machinery
toward the exact new signed Smite unified-install Node pair without
introducing a second pairing stack, modifying production, or claiming
Connected before a real proof. The existing RC7 activation method is
not re-routed; its pinned old signed digest and rollback are unchanged.

In modules/smite-node-pairing.py, the existing
_foreign_gateway_preflight now supports a narrowly explicit
review_unified_trial=True mode for **read-only review only**. It accepts
the exact immutable separately signed trial Node digest
ghcr.io/aghajani82/smite-node@sha256:587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483
only when that mode is explicitly selected; default/old RC7 use
continues rejecting it. The review uses the SAME existing RC7 security
checks (exact paused+strict Node state, HTTPS/443 routing, managed
Compose, local health and RO Sanaei mount). The trial review does not
allow the special unattached-Sanaei recovery bypass.

New modules/smite-unified-foreign-activation-review.py is a
**read-only** caller, with CLI --review only. It independently
re-verifies both trial Panel and Node Cosign/OIDC claims with the
pinned Sigstore trusted root and SHA-bound manifest, requires
activation_allowed=False, then calls the existing RC7 gateway
security preflight with review_unified_trial=True. It validates the
paired identity + durable replay marker and SQLite history, compares
the *running* Node image ID with the locally pinned digest's image ID,
and checks effective Docker environment contains exactly one each
of paused, strict and managed settings. It returns
READY_READ_ONLY with activation_allowed=False and
bidirectional_connected=False. The remote Panel runtime is explicitly
not proven by this check.

The production CLI has no --activate, --apply, gateway mutation,
Docker recreate, Node restart, migration, key rotation, or replay
reset option. The prior official RC7 activation continues accepting
only the previously signed RC7 image.

Tests:
- Extended tests/test-smite-rc7-foreign-pairing.py using its real
  existing managed RC7 Compose/Gateway security fixtures: old image
  still works by default; new image works ONLY with explicit read-only
  flag; default and arbitrary expected_image override both refuse it;
  wrong image/caps/devices/loopback/Sanaei RO fail closed.
- New tests/test-smite-unified-foreign-activation-review.py:
  nine isolated cases with the ACTUAL signed pair verifier (injecting
  Cosign test responses), missing/bad signatures, image ID drift,
  active overlays, missing replay/identity, invalid role/mode,
  changed Nginx/Compose probe, duplicate/effective env flags and
  denial of any activation CLI.
- The same CI continues the previously green credential redemption,
  HMAC signed proof, replay/recovery and Panel ASGI contract, Iran
  one-choice ordering, existing foreign Gateway/Sanaei flows and
  independent disposable HTTPS ingress tests.

Full CI PASS:
https://github.com/aghajani82/u-opti/actions/runs/43238825374
(2/2 jobs green on source
4ec0418774874fedc63510df72c295ea7c2eb698).
No production or server tests have been executed.

**NEXT EXACT WORK:** Complete a distinctly authorized signed
trial-image activation/rollback path *without changing the old RC7
activation default*. Preserve the same promoted Foreign identity
and replay DB, use the existing managed strict/paused Compose
candidate with image-specific verified matching and a durable lock
and journal. Prove actual signed Foreign->Panel check-in and the
Panel->Foreign /api/node-control/gateway-check = gateway_ready:true
probe; false, missing and stale status must HOLD and the Node must
return to paused+strict without rotating or rewinding keys/replay.
Only then wire the full, uninterrupted single-choice Foreign
option 2 and test it on disposable two-host infrastructure. The
current trial manifest explicitly has activation_allowed:false:
do NOT bypass it. Actual host tests and merges to main still require
the user's final approval, and live FRP 20182, Backhaul, Sanaei and
both hosts must remain unchanged.

## Operator journey agreement — IR first, then Panel-issued Foreign (2026-11-12)

The user explicitly confirmed the final **two-stage user journey**. The two
hosts still use only their respective Smite Manager menu choices. There is
**one intentional Panel UI visit** between them:

1. **Iran server:** choose Smite Manager **1) Install Panel + Iran Node** once.
   Complete Panel, Nginx Gateway/SSL, local Iran Node, automatic signed
   Pairing and admin creation. Sign in to the Iran Smite Panel, open the
   **Iran Node** page and independently verify the Node was actually
   created and is **Connected**, rather than trusting a completion banner.
2. **Still in the Iran Panel:** open **Foreign Node**. Create/reserve the
   new Foreign Node, enter its exact Node name and Foreign Gateway domain,
   then request the existing one-use **smi1** installation information.
   Copy its complete JSON packet. The issuance clock is **exactly 2 hours
   (7200 seconds)**, and starts upon ISSUE on Iran, not at the beginning
   or end of Foreign installation. Prefer issuance immediately before
   moving to the Foreign terminal. Issuing a new unused code invalidates
   the prior unused code; an already enrolled identity must never be
   rotated on a retry or disconnected merely due to code expiry.
3. **Foreign server:** choose Smite Manager **2) Install Foreign Node** once,
   paste the JSON copied from Iran Panel in the same installation flow.
   The packet already carries Panel URL, Foreign domain, Node ID and
   name, exact 443 control path, one-use code and expiry; do not force
   the operator to retype these independent values and risk mismatch.
   Perform existing signed Node install, Nginx/LE SSL Gateway and Sanaei
   Docker/RO DB attachment in a safe order, then redemption, no-rekey
   promotion, replay and signed runtime check-in. No separate menus.
4. **Back in Iran Panel:** refresh **Foreign Node**. Status may say
   **Connected** ONLY after the foreign Node has genuinely completed
   signed registration **and** the Panel's live authenticated request
   to the Foreign Node succeeds over the exact HTTPS/443 route.
   A valid code, initial reservation, successful redeem, active FRP,
   old metadata or a stale heartbeat does NOT count. If the live probe
   fails, show pending/failed/reconnecting and retain signed state for
   recovery; never fake Connected.

Implementation and test checkpoint (trial only, no live host changes):

- Audited existing Smite frontend ForeignInstallDialog and
  foreignInstallContract: they ALREADY issue a strictly scoped 7200-second
  grant and render all 8 fields of a pretty-printed, multiline JSON packet
  without writing it to browser storage. Updated the trial dialog's help
  text to state the user sequence and issuance-based TTL; no UI redesign.
- New `modules/smite-unified-foreign-packet-intake.py` uses the SAME
  existing Foreign client packet parser, accepting the Panel's multiline
  JSON up to 8192 bytes, ending with an empty line. It checks Node,
  Panel, Foreign Gateway, path and remaining lifetime BEFORE a private,
  fsynced, exclusive, no-overwrite 0600 packet is staged under a
  0700 directory. Credential never appears in argv, stdout, or a log.
  This is a **disposable-fixture API only**, not a public terminal
  prompt or a production installer; the CLI exposes --status only,
  and there is no live-write route. The real menu must implement an
  echo-disabled input step before enabling the capture path on hosts.
- `tests/test-smite-unified-foreign-packet-intake.py` proves 11
  private intake scenarios: exact JSON, expiry, wrong Panel/Node/domain,
  duplicate JSON fields, overflow, missing terminator, symlink/hardlink,
  unsafe permissions, no-overwrite retry, no secret leakage and no
  host capture command.
- Extended `tests/test-smite-foreign-install-integration.py` to issue
  an actual Smite Panel grant against isolated FastAPI/SQLite, transfer
  its complete JSON through the SAME private Foreign intake API and
  use the existing no-rekey signed client/promoter with lost-ACK,
  expiry/retry and revocation tests.
- Extended actual Smite Panel
  `tests/test_signed_node_inbound_panel.py` with a focused **refresh
  truth** regression: reserved/issued pending does not call the remote
  probe or show Connected; signed check-in sets active/provisioning;
  the refreshed list remains failed when its authenticated live probe
  fails, shows Connected for a successful live response, and reverts to
  reconnecting on a subsequent timeout. The existing
  `/api/node-control/gateway-check` signed dual-direction test also
  remains mandatory.
- Trial U-OPTI CI:
  https://github.com/aghajani82/u-opti/actions/runs/43242232991
  (2/2 green); Smite HTTP and UI:
  https://github.com/aghajani82/Smite/actions/runs/43242503985
  and https://github.com/aghajani82/Smite/actions/runs/43242503734
  (all 4 jobs green).

**Remaining decisive HOLD:** the intake/identity function currently uses
disposable fixture paths and is NOT called from menu option 2. The
exact signed trial manifest still has `activation_allowed: false`;
the paused-to-signed runtime transition, retained rollback journal,
actual two-host installation, and final bidirectional live checks
remain unproven. Do not bypass this to mark a live Node Connected.
Next: design safe non-echo operator terminal input, admitted signed
runtime activation/paused rollback without Node rekey, and connect
the existing phases to the REAL Smite Manager option-2 choice only
after tested transaction/recovery on disposable hosts. Preserve Iran
option 1, FRP 20182, active Sanaei, current Node container and all
signed replay data. Merge to main only following full host tests and
explicit user acceptance.

## Checkpoint — no-echo Foreign terminal intake, real PTY proof (2026-11-12)

This step advances the user-approved **Iran Panel → one-use 2-hour JSON
→ Foreign Smite Manager option 2** journey without bypassing the trial
activation HOLD or rebuilding existing Foreign pairing components.

The existing `smite-unified-foreign-packet-intake.py` now has two narrow
reusable functions:
- `read_hidden_tty(stream)` requires a REAL terminal, disables terminal
  ECHO, ECHONL, ECHOE and ECHOK before the operator pastes the complete
  multiline JSON, applies the existing 8192-byte/40-line/blank-line
  terminator bound, and restores the original termios state in a
  `finally` block after success, malformed JSON, callback failure or
  Ctrl-C. Non-TTY pipes are not accepted as a substitute.
- `capture_disposable_hidden_tty(..., confirm_scope=...)` calls the
  existing strict `smi1` parser, passes only the NONSECRET Node name,
  ID, Panel/Gateway origins and control URL to the confirmation callback
  AFTER echo is restored, and on affirmative confirmation uses the
  existing fsynced private 0700/0600, no-overwrite packet stager.
  The installation code is never put in argv, stdout, shell history,
  logs or environment. No new pairing, identity or activation engine.

New tests in
`tests/test-smite-unified-foreign-packet-intake.py` exercise an ACTUAL
Linux pseudo-terminal with input submitted ONLY after echo was disabled,
verify no reflected bearer code, exact permission-preserving stage,
manual cancellation, incorrect destination and termios restoration
after a simulated KeyboardInterrupt; non-terminal input is rejected.
The original 11 packet validation/expiry/permission tests still run.
The actual cross-repository
`tests/test-smite-foreign-install-integration.py` now takes a REAL
Smite ASGI/SQLite-issued grant, transfers its **pretty-printed JSON
through this no-echo PTY**, confirms only nonsecret scope, and then
reuses the existing Smite HTTP redemption, signed HMAC proof, retained
identity promotion, lost-response reconciliation and expiry/revocation
checks. No external Panel, host TTY, Docker or live network is used.

GitHub Actions (both jobs SUCCESS on the tested code):
https://github.com/aghajani82/u-opti/actions/runs/43244674444

**Status: no public host input command yet.** The Python module still
exposes `--status` ONLY. Both its private capture methods accept
*disposable test fixture paths*, not production Node/host directories.
No user needs to run a command on the live IR or Foreign server. No
change to `main`, the public Smite Manager menu, existing FRP 20182,
Backhaul, Sanaei Docker, Node identity or replay database. The unified
signed image manifest remains `activation_allowed: false`.

**NEXT:** wire an explicitly fresh/owned Foreign installer-local
private packet capture at the correct stage of option 2, preserving the
nonsecret scope-confirmation and the same single paste; then implement
a reviewed, durable host recovery journal and **separately authorized**
paused-to-strict-signed runtime activation with same immutable Node ID,
without recreating Node. Require genuine Foreign→Panel signed check-in
AND Panel→Foreign verified status before the Panel refresh can display
Connected. Until the signed manifest and full recovery/dual-host tests
permit activation, the public option 2 remains unchanged and HOLD
must not be misreported as success. Merge only with final approval.

## Checkpoint — crash-safe Foreign identity-phase operation lock and journal (2026-11-12)

The user wants each Foreign Smite Manager option-2 invocation to finish from
the already-issued **two-hour Panel code** to a genuine Connected Node,
including a safe retry if SSH/network/process dies. The existing
`smite-foreign-install-client.py` already has a locked, no-rekey staged
secret and signed HMAC enrollment proof, and
`smite-foreign-install-promotion.py` already records PREPARED/COMPLETED
no-overwrite identity receipts. **Do not replace these components.**

This checkpoint adds `rehearse_transaction` to the existing
`modules/smite-unified-foreign-identity-phase.py`. It is **not a
production entrypoint**. Only a precisely scoped 0700 disposable fixture
may exercise it with injected Panel transport. Before touching the
operation journal or consuming a code, it validates the same exact
Panel-issued packet, managed Gateway and paused/strict Node state.

The private Foreign staging directory retains:
- `unified-foreign-transaction.lock` — owner-only 0600 persistent
  file with nonblocking `flock`; simultaneous executions HOLD, while
  a dead process automatically releases the kernel lock.
- `unified-foreign-transaction.json` — 0600 atomic/fsynced record of
  schema, nonsecret Node scope, SHA256 of the **exact private packet**
  and one of `INTENT` / `IDENTITY_PROMOTED_OFFLINE`. The journal
  NEVER includes the one-use code, HMAC secret or a Connected claim.

When a process dies just after the Panel commits redemption, the
`INTENT` journal and original staged identity survive. On restart, the
existing HMAC status proof and identity promotion receipts recover the
**same** key. After a successful promotion, the journal advances to
`IDENTITY_PROMOTED_OFFLINE`, yet every retry **still requires a fresh
signed proof**, even if the journal already says completed. A corrupt,
replaced, symlinked or insecure journal, changed private packet, failed
proof/revocation, missing private fixture, or concurrent invocation
HOLD. Identity, replay, FRP and existing operational services are never
rolled back, reset or overwritten by this transaction marker.

Evidence: extended
`tests/test-smite-unified-foreign-identity-phase.py` with real
interrupted-process/lost-ACK, lock-contention, code-swap, journal
corruption, revocation and no-rekey tests. The **actual** Smite ASGI
grant→HMAC proof→no-overwrite promotion integration now exercises
`rehearse_transaction` against a disposable SQLite database and
checks the committed operation receipt. Prior hidden-PTY JSON capture,
Iran one-choice path, Sanaei, SSL/443 and signed/replay checks remain
in CI.

Latest verified code and documentation CI run:
https://github.com/aghajani82/u-opti/actions/runs/43246611431
(2 of 2 jobs SUCCESS on source
`1091615f343843e9bf2f0515795d2d68768fa305`).
This is isolated test evidence, NOT a deployment proof.

**Scope of the journal:** it covers **identity redemption/promotion
only**, not the earlier Node/Sanaei/SSL/443 host install or the
later paused→signed activation/Connected verification. It does not
issue recovery permission for real hosts. The trial manifest still
explicitly has `activation_allowed: false`, and the public menu
option 2 still uses its prior selected RC7 flow. No user needs to
update U-OPTI on a live host for these tests.

NEXT: review/implement an owner-bound host operation journal covering
the existing core/Sanaei/SSL stages without duplicate service changes,
a separately admitted exact-signed trial image runtime transition with
rollback to Paused+Strict (never rekey or rewind replay), and the two
authenticated live reachability proofs before wiring and advertising
option 2 as one-choice installation complete. Retain the user-requested
Iran→Panel→Foreign order; no changes to main or production hosts until
explicitly approved real-host tests and final merge acceptance.

## Checkpoint — crash-recovery stages for owned Foreign Node/Sanaei/Gateway (2026-11-12)

The user's fixed operator journey remains:

1. Smite Manager **option 1 on Iran** completes Panel + Iran Node + SSL/443
   + local secure pairing and admin; the operator verifies Iran Node
   **Connected** inside the Panel.
2. In that Iran Panel the operator reserves the Foreign Node/domain,
   issues the one-use **7200-second** grant and copies the full `smi1`
   JSON.
3. Smite Manager **option 2 on Foreign** must eventually accept the JSON
   once and complete the already-existing signed Foreign Node, Sanaei
   Docker/RO inventory, Gateway/SSL, no-rekey enrollment, signed replay,
   and **both directions** of live Connected verification. No extra
   standalone menu visits or secondary installers.

New **rehearsal-only** component:
`modules/smite-unified-foreign-host-recovery.py`.
It is a narrow transaction envelope for the ALREADY reviewed Foreign
host-stage helpers, not another Sanaei/Docker/SSL implementation.
It does **not** execute a command against a real server. The only
CLI supports inert `--status`; no `--install`/`--activate` action.

Its internal callback contract is for *disposable owned 0700 fixture
trees only*. A future integration must bind the callbacks to existing
trusted read-only checks and approved installer actions:
- `verify_core(scope)`: strictly verify **already installed** immutable
  signed Foreign Node, Compose owner, paused+strict runtime and exact
  name/domain; never create/recreate Node here.
- `verify_sanaei(scope)`: independently verify existing registered
  Sanaei instance, attached DB RO, Node inventory and paused state.
- `verify_gateway(scope)`: independently verify current LE TLS,
  managed Nginx HTTPS/443 and exactly the Panel-issued control path,
  plus Node effective environment.
- `install_sanaei`/`install_gateway`: in a future **explicitly
  authorized fresh-host** coordinator only, call the EXISTING
  approved U-OPTI functions. These are injectable test doubles now.

The private 0600 file `unified-foreign-host-journal.json` records
only schema, SHA256 of the exact private grant, nonsecret scope and a
strict monotonic phase:
`CORE_VERIFIED` ->
`SANAEI_INTENT` ->
`SANAEI_RO_VERIFIED` ->
`GATEWAY_INTENT` ->
`GATEWAY_443_VERIFIED`.
It is fsynced and atomically replaced under the persistent 0600
`unified-foreign-host.lock` (nonblocking flock). No code/secret,
signed replay data, key or Connected claim is stored in this journal.

Safety on interruption:
- Pre-existing fully VERIFIED Sanaei/Gateway is **not reinstalled**,
  even if the journal is absent/behind.
- If a process dies *after* Sanaei/Gateway applied but *before* its
  journal phase is committed, a retry verifies the REAL external
  READY result and advances without repeating that operation.
- If an INTENT is left behind while readiness is ABSENT/DRIFT/
  ambiguous, the retry HOLDs. It never runs `--force-recreate`,
  re-installs Sanaei, reloads Nginx, or rotates identity just to clear
  a journal.
- A completed journal is **never** treated as an authoritative health
  result: independent core/Sanaei/Gateway checks rerun on every retry.
- An invalid, changed, symlinked, hardlinked or insecure journal, an
  unrelated/expired grant, non-owned test fixture, concurrent command,
  wrong domain/Node or unknown witness blocks any stage mutation.

Validation: 18 isolated recovery scenarios in
`tests/test-smite-unified-foreign-host-recovery.py`, including
interruptions after the external action, no-blind-repeat, drift after
success, journal/credential tampering, expired/incorrect grant,
contention, preexisting registered Sanaei and nonsecret permissions.
The same workflow continues the previous genuine Panel ASGI grant
redemption/HMAC proof, no-echo PTY paste, existing Sanaei/Gateway/IR
path regressions and Nginx SSL/443 fixture tests.

CI:
https://github.com/aghajani82/u-opti/actions/runs/43248094754
(two jobs SUCCESS, 18/18 new cases passed). Host activation remains
`activation_allowed:false` in the signed trial manifest.

**Status & next critical work:** This phase prepares a safe host-stage
resume **contract**, not a production host-recovery feature. The
already-built `smite_install_unified_foreign_after_core` remains
internal/unwired, and does not yet use this envelope; the new
callbacks have not been bound to actual read-only Docker/Sanaei/Nginx
inventory. Even the existing legacy Foreign Gateway may recreate the
Node during setup, so the future adapter must guarantee that this
happens only on a newly owned/paused fresh Node and NEVER while
clients/FRP are active or after signed pairing.

Next step: attach audited, exact real read-only verifier adapters
to this host-stage envelope, and simulate the existing Bash
installer callbacks in isolated two-host fixtures. After proving
interrupt/recovery, finish separate signed trial activation (currently
HOLD), rollback-to-paused, and authenticated Foreign→Panel plus
Panel→Foreign Connected probes. **Only then** wire the single option-2
entrypoint and perform user-approved trial host deployment and merge.
No modifications to main, IR, Foreign, FRP 20182, Backhaul, Sanaei,
existing Node containers, keys or replay occurred here.

## Checkpoint — existing RC7 signed host witnesses bound to recovery rehearsal (2026-11-12)

The user's accepted **one-choice Iran / one-choice Foreign** flow remains:
finish IR Panel + Gateway/SSL + local Iran Node signed Connected with
option 1; verify the Iran Node in the Panel; reserve Foreign in that Panel
and copy the exactly 7200-second one-use `smi1` JSON; paste it once
in Foreign option 2, which must eventually install Node, Sanaei Docker,
RO DB mount, SSL/443 and signed dual-direction Connected.

This checkpoint adds **the read-only evidence adapters** that the
previous host-stage transaction still lacked:
`modules/smite-unified-foreign-existing-witnesses.py`. It is a
Python library with a status-only inert CLI, never a host installer.
`bind_existing()` binds to the EXISTING verified
`smite-unified-trial-pair-admission.py` (exact immutable Panel/Node
Cosign/OIDC source SHA and trusted-root manifest;
activation_allowed=false), existing `smite-node-pairing.py`
RC7 Compose ownership/paused-strict helpers and Gateway/443
preflight, existing `smite-rc5-xhttp-sanaei-mount.py` registered
database validator and the existing safe Foreign Nginx site planner.

The three witness results support the existing
`modules/smite-unified-foreign-host-recovery.py` callback contract:

- **core(scope):** TRUE only if the exact signed unified-trial
  image reference AND running Docker image ID match, RC7 is still
  the owned Compose project, host-network Node binds API to loopback,
  CapAdd/device baseline is unmodified, engine overlays inactive,
  Node is healthy and actual Docker env, Compose env and protected
  on-disk env have the same paused+strict+managed mode, Node name,
  Foreign role and Panel address. A changed signature, domain,
  Node name, runtime ID, health or access mode returns FALSE.
- **sanaei(scope):** ABSENT only for the exact fresh
  `.sanaei-empty` 0700 owner-only empty placeholder and a
  disabled read-only mount. READY only when the existing managed
  instance **01** database directory is rooted in
  `/opt/3x-ui/instances/01/db`, its Compose mount is RO, the
  old registered database-file validator accepts it, and the
  original *read-only* container-side mountinfo + SQLite
  `mode=ro` schema proof succeeds. Otherwise DRIFT; no client
  records are queried or exported.
- **gateway(scope):** ABSENT only if there is no Gateway
  receipt, no Node control address and no existing Smite
  control location. READY only if the exact state and managed
  Nginx location use the Panel-issued 32-hex path with local
  127.0.0.1:8888 backend, deny-all and the existing full
  read-only RC7 `_foreign_gateway_preflight(...,
  review_unified_trial=True)` succeeds. That existing preflight
  validates the exact Paused/Strict Compose and the real
  certificate-verifying local HTTPS/443 response. Otherwise
  DRIFT, never assume absence or overwrite unrelated Nginx.
  This is a **local** readiness witness, not a signed live
  Panel→Foreign Connected claim.

In the new isolated test
`tests/test-smite-unified-foreign-existing-witnesses.py`,
the real signed pair admission code runs with synthetic Cosign
replies; the existing pairing read-only command interface is
mocked. Scenarios include signed-ready core, invalid signature,
image/env/Compose/health drift, exact empty Sanaei placeholder,
untrusted RO DB/schema, missing or competing Nginx control
locations, bad HTTPS response, and a full restart/recheck
transaction through the PREVIOUS host recovery envelope.
This verifies integration of the witnesses with the existing
recovery state machine without running Docker on the actual hosts.
Previous 18 host recovery, 20 identity recovery, no-echo PTY,
Smite API, IR one-choice ordering and Nginx real fixture
regressions remain in the same CI workflow.

CI: https://github.com/aghajani82/u-opti/actions/runs/43250694673
(two jobs PASS; new witnesses and prior tests green).
**No production activation, no host writes, no Node recreation.**

IMPORTANT: `bind_existing` is not called by the public Smite
Manager option 2, and the existing full Foreign host transaction
still accepts explicit injected installer callbacks ONLY under its
disposable fixture capability. This stage validates the REAL
read-only contract in an isolated harness; it does not constitute
a real two-host connected install or evidence that the host is
fully recoverable. Legacy published RC7 image continues to be
the only one accepted for legacy activation; the unified trial
manifest continues to explicitly deny host activation.

NEXT EXACT WORK: finish signed **runtime activation and rollback
admission** for the new immutable trial pair under an explicit
operator authorization, while preserving the old RC7 default.
Use a durable single ownership/lock/phase journal across
core→Sanaei→Gateway→grant redemption→identity promotion→replay
→signed runtime. Prove that an interrupted Gateway or Node
recreate on a *fresh paused-owned Node* can be reconciled
without rewinding keys, replay, saved tunnels or Sanaei state.
Then require actual Foreign→Panel signed check-in plus
Panel→Foreign signed live health checks and show Connected only
when both pass. Finally wire option 2, verify both hosts in
disposable two-host tests, and request approval for real-host
testing/merging to main. Keep FRP 20182, active Sanaei,
existing Node, main and both hosts untouched.

## Consolidation checkpoint — reuse existing one-choice Sanaei and Foreign Gateway (2026-11-12)

The operator explicitly reiterated: **finish, combine and simplify the
existing Smite/U-OPTI service**; do NOT add new features, standalone
installers, parallel engines, or additional menu visits. Continue only on
`trial/unified-smite-install`, do not touch `main` or either live host
before full signed two-host evidence and final approval.

**This stage changed only the existing install flow functions and their
regression tests. No new runtime module, public API or installation
feature was introduced.**

- `modules/smite-foreign-gateway.sh`:
  `smite_foreign_gateway_configure` now reuses the operator's already
  approved **fresh option-2 installation** when the exact private
  Panel-issued `smi1` JSON has passed existing scope/role/paused checks.
  It no longer requests the *second redundant* "Configure Gateway? [y/N]"
  confirmation. It does NOT skip the independent Panel source IPv4
  allow-list prompt/validation (required to avoid trusting a CDN IP),
  Domain/Node/Standard-mode checks, strict gate, signed packet, exact
  32-hex path validation, original Nginx/LE TLS safeguards, or failure
  returns. Standalone Gateway repair / menu option 6 still asks for
  confirmation. Gateway's existing renderer, certificate installer,
  Docker Compose and rollback code are not replaced.
- The SAME Gateway entry does not `clear` the terminal while an owned
  one-choice Foreign operation is continuing, preserving prior Node/
  Sanaei output. Independent option 6 retains the original screen.
- `modules/smite-install.sh`:
  `smite_install_sanaei_foreign` keeps prior progress visible and
  `smite_install_pause` no longer stops the caller with "Press Enter
  to return" when `UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER=1` **and**
  `SMITE_SELECTED_FRESH=1`. The isolated standalone Sanaei option 4,
  unowned/nonfresh installations and ordinary menu behaviors retain
  their original clear/pause semantics. Failure return codes remain
  unchanged, so an interrupted/invalid mount remains HOLD rather
  than reporting success.

Existing regressions were extended rather than adding another testing
framework: `tests/test-smite-unified-gateway-menu-boundary.sh`
now checks that a valid signed fresh packet reaches only the first
mocked package-boundary (no real mutation) without a second consent
prompt, but invalid packet, private mode, nonfresh role, invalid Panel
source IPv4 and independent Gateway cancellation all block safely.
`tests/test-smite-unified-sanaei-continuation.sh` now exercises the
ACTUAL Sanaei early-error and pause/clear functions to prove that
fresh scoped option-2 continuation is uninterrupted while standalone
option-4 menu/pause behavior is unchanged. The existing signed
Cosign, host recovery, foreign identity HMAC, Sanaei RO schema,
Nginx HTTPS/443 and Iran option-1 tests still run in CI.

All changes: **trial branch only**. Green GitHub Actions:
https://github.com/aghajani82/u-opti/actions/runs/43252907240
(two jobs successful on the implementation and regression tests).
No Smite source/UI changes, no new features, no `main` merge,
no real server changes, no Node/FRP/Backhaul/Sanaei restarts.

**Remaining acceptance HOLD:** the public option-2 `smite_install_selected_fresh
foreign` still ends after RC7 core and is deliberately NOT wired
to the incomplete unified Foreign post-core chain. Existing official
RC7 and independently signed trial image digests are different, and
the unified trial manifest still says `activation_allowed=false`.
The actual runtime activation, shared crash-safe single host transaction
through pairing, retained rollback, and BOTH real signed Connected
directions still require proof. Do not bypass these gates or change
`main` merely because the menu flow is simplified.

NEXT WORK IS INTEGRATION, NOT NEW FEATURES: audit the already-existing
`smite-node-pairing.py` signed runtime/rollback implementation against
the exact independently signed trial image, reuse the existing journal
and two-way verification functions with safe fresh-install ownership,
and test the full option-2 sequencing in isolated two-host fixtures.
Only after PASS and explicit user approval should final installation
run on the servers and tested changes be merged to `main`.

## Consolidation checkpoint — harden the existing signed RC7 activation/rollback (2026-11-12)

User directive: **finish and combine the existing features**; no new
Pairing engine, no new menu items, no extra UI or undocumented host
operations. This stage edits ONLY the pre-existing
`modules/smite-node-pairing.py`, its existing RC7 regression suite,
and this handoff note. No production host, main branch, FRP tunnel,
Backhaul, Sanaei or live Node was touched.

Existing RC7 Foreign activation already had complete signed
Foreign-to-Panel / Panel-to-Foreign probes, retained identity
handling, guarded Compose ownership and a paused rollback.
This checkpoint fixes a safety gap **within that existing path**:

- Share one private read-only
  `_rc7_foreign_pinned_image_verified()` check across pre-activation,
  pre-manual-rollback and post-failed-activation rollback.
  It compares the *effective running Docker image ID* against
  `docker image inspect` for the exact previously released RC7
  immutable digest, not just the text of `Config.Image`.
  A substituted/removed/mismatched image fails BEFORE any replay
  provisioning or Node recreation.
- Strengthen the existing paused rollback verifier to require
  exactly one of each effective `paused`, `strict`, and
  `managed` Docker environment value, plus the original paired
  `(node_id, node_secret)` and verified identity-bound Replay
  artifacts when provisioned. A Docker Compose exit code and
  two environment strings alone no longer prove safe rollback.
- On a signed activation success path, verify the identity and Replay
  binding again *after* the two signed communication checks; a
  mismatch enters the existing guarded rollback path rather
  than announcing Connected.
- For manual rollback, retain the original identity/replay readiness
  snapshot (when a valid paired identity exists) and check the
  same bindings after recreation. Unpaired RC7 recovery retains the
  prior behavior, but always requires exact running image and
  paused+strict+managed verification.
- An independently signed **unified trial** Node digest is NOT
  admitted by the published RC7 activation/rollback function.
  The trial manifest remains `activation_allowed:false`;
  no alternate activation CLI, release approval or bypass was added.

Extended the existing
`tests/test-smite-rc7-foreign-pairing.py` to 13 tests, without a new
test harness. Cases include exact effective image match, tampered
image/digest, duplicated/insecure runtime auth values, replay or
identity drift, refusing the different signed unified trial image
before any legacy RC7 recreate, rejected pre-activation image ID drift
before candidate/replay writes, simulated key rotation DURING
recreation, and the existing activation's automatic rollback
escalating to CRITICAL if a post-rollback identity check fails.
The previous IR one-choice, signed image/OIDC, Foreign one-use code,
signed HMAC replay, Sanaei RO and Gateway HTTPS/443 tests remain
in the same Actions workflow.

Verified green workflow on the code:
https://github.com/aghajani82/u-opti/actions/runs/43255739390
(2/2 jobs success). Previous trial image-pair signing source and
manifest were not changed.

**Still to close, no false completion claim:**
The new signed unified-install Panel/Node pair is a different digest
from published RC7 and is *review-only*. Its manifest still prohibits
host activation. The public `2) Install Foreign Node` entry does not
yet execute the complete combined Sanaei → Gateway → one-use Panel
grant → identity → signed runtime sequence. Neither a complete
disposable two-host install nor bidirectional live Connected has been
proven. Next focus: use the **existing** pairing/Compose candidate and
rollback implementation to reconcile new signed image/Panel identity
admission through an explicitly reviewed and authorized trial
release/activation boundary, without weakening official RC7. Then
test the full one-choice workflow and interrupted recovery on isolated
two-host test hosts. Only after explicit user approval run live
install tests and merge to main; leave existing clients, FRP 20182,
Sanaei, Backhaul and running Nodes unchanged.

## Consolidation checkpoint — shared immutable-image/paused witness (2026-11-12)

The trial Foreign read-only reviewer now calls the pre-existing RC7
`smite-node-pairing.py` immutable Docker image, paused/strict/managed,
identity and replay witness instead of maintaining a duplicate verifier.
The only trial-specific selector is `review_unified_trial=True`, passed
from the inert reviewer AFTER independent Panel/Node Cosign/OIDC source
verification. The original RC7 activation and rollback callers retain
their default RC7 digest and cannot select the trial image.

Existing RC7 and trial review tests now exercise this same witness using
offline fake Docker observations: exact digest vs running image,
paused auth uniqueness, original paired identity and signed replay.
Exact code checkpoint: `0dad06cdf5e2766a3947b513bc936122b1314069`.
GitHub Actions `43258784694` SUCCESS (both jobs): all trial runtime
read-only, actual shared-pairing, RC7, Panel grant, Foreign host recovery,
Sanaei, Nginx and previous integration fixture tests passed. This is
NOT a Connected or live two-server test. No new menu, API, feature,
installer, runtime activation authorization, or service change.

NEXT: keep the signed candidate manifest `activation_allowed:false`
until explicit trial runtime transition/rollback with existing Pairing
and Compose is tested, then prove both authenticated Connected directions
and interruption-safe single option-2 sequencing. Do not merge main
or touch live servers, FRP 20182, Backhaul or Sanaei before approval.

## Consolidation checkpoint — retain one-choice consent and truthful Foreign core handoff (2026-11-12)

This is a direct correction to the **existing option-1/option-2 install
choreography**, not a new installer, menu, engine or feature. The selected
fresh entry already asks for explicit install approval BEFORE mutation.
Its own Iran or Foreign core function no longer repeats an identical
approval, while keeping the existing Panel/Node/domain prompts, strict
preflight and all standalone/manual confirmation behavior.

The selected fresh Foreign core now returns immediately after its
persisted state, with `FOREIGN_CORE=READY_PAUSED_FOR_UNIFIED_CONTINUATION`
and `FOREIGN_CONNECTED=NOT_PROVEN`; it does **not** print the old
standalone `Foreign Node Install Complete` banner or the misleading
option-4/6 next-menu instructions. Selected option 2 commits the core
journal and then returns an explicit `HOLD`/nonzero while the signed
trial image cannot yet be activated. This preserves already installed
paused Node state for the existing recovery path without falsely
reporting the whole Foreign cycle finished.

A new section in the EXISTING Iran ordering regression calls the real
Iran and Foreign core functions with fail-before-mutation preflight
mocks: both keep their domain/name prompts, selected runs skip only
duplicate consent, independent Foreign still asks. The existing
Foreign phase-order regression also enforces the scoped core handoff
and truthful terminal HOLD. No new test framework introduced.

The required next work is still wiring the **same** Foreign option 2
to existing Sanaei, Gateway, Panel-issued packet, identity promotion
and signed runtime, then genuine dual-direction Connected. The
independently signed trial manifest remains activation_allowed=false:
this checkpoint does not publish a runnable unified installer or
authorize a live server trial. Do not merge main or change either
server/FRP 20182/Backhaul/Sanaei before approved full end-to-end tests.

## Consolidation checkpoint — keep same Foreign option-2 Node after Gateway (2026-11-12)

Within the **existing** internal Foreign post-core composition function
(`smite_install_unified_foreign_after_core`), the existing signed image-ID,
strict paused Node and original RC7 Compose ownership checks now run both
before Sanaei/Gateway and **after** the Gateway's existing paused Node
recreation. A Gateway receipt or HTTPS success alone is not proof that
the same reviewed paused Node remains. Any post-Gateway image/ID,
paused mode or Compose drift returns HOLD without claiming enrollment.
The existing Foreign choreography test covers four additional post-write
drift scenarios, using only offline mock Docker/Gateway observations.

No new installer, menu, pairing module or runtime feature. This is still
an internal, non-public stage: it is NOT called from option 2 until the
signed trial image activation/rollback and final connection checks are
admitted. Main, operational hosts and existing FRP/Backhaul/Sanaei
remain unchanged. No live Connected claim.

## Consolidation checkpoint — reuse one Panel-issued input for Foreign core (2026-11-12)

The **existing** `smite_install_foreign_node` now supports an **internal
fresh/trial-only** private packet input branch: when the future one-choice
coordinator supplies the same 0600 `smi1` file already used by Gateway,
the three core values (Iran Panel domain, Foreign domain, Node name)
come from the signed Panel packet **without three redundant manual
prompts**. It calls the existing Gateway packet parser and private
file guards, with an explicit pre-core expiration check and fail-closed
no-fallback behavior. Neither the installation code nor Node ID/secret
is echoed; independent installs keep their old manual prompts.

The previously existing `smite-unified-foreign-gateway-plan.py`
exposes a read-only `--precore-fields` selection (three nonsecret
validated lines only). It never redeems the credential or modifies
a server. Existing gateway/status and runtime functions remain the
same. Both existing Gateway and Foreign choreography test suites were
extended to exercise matching input, no additional prompts, expired
grant, unsafe private file, wrong origin/host, and wrong caller scope
before the mocked preflight rejects installation.

Verified implementation SHA: `5a9f0e24671a20cbcf7000bdf60666f02996056a`;
final fixture correction SHA: `609a917f5cbd34fddee115a1062cef19b5285d94`.
Full GitHub Actions `43288887582`: **2 of 2 jobs SUCCESS** on the
final exact source, including existing foreign after-core, Gateway
packet, IR local installation, Sanaei and cross-repository Panel ASGI
tests. The first test attempt failed because the old standalone
Gateway fixture had a deliberately far-future grant expiry; the fresh
pre-core test now uses a realistic one-hour unredeemed Panel grant
without weakening the actual two-hour check.

**No public option-2 packet capture or activation was enabled.**
The signed trial manifest still has `activation_allowed:false`.
The next work is connecting the existing secure hidden-terminal
packet capture to this internal core branch in the single option-2
orchestrator, then the signed runtime/rollback and two-way Connected
checks. No main merge or live host change.

## Consolidation checkpoint — single hidden Foreign packet paste, same option-2 helpers

The existing private `smite-unified-foreign-packet-intake.py` now
supports an internal `--capture-selected-foreign` invocation for the
same fresh installer's 0700 temporary workspace. It reuses the original
echo-disabled TTY reader, one-use `smi1` parser, 2-hour expiry check and
exclusive 0600 staged packet. The operator confirms only nonsecret
Panel/Foreign domain, node name and control URL after echo is restored.
There is no separate installation wizard or newly generated credential.

The existing `smite-install.sh` contains
`smite_install_unified_foreign_capture_packet`, scoped to selected fresh
Foreign installation. It passes the one private packet to the existing
Gateway's pre-core parser, which supplies the three core values without
duplicate questions. Real pseudo-terminal, cancellation, no-terminal,
expiry and nonselected-host refusal tests were added to the existing
suites. This change is code-only and is NOT called from the public
option-2 entry while the signed-trial `activation_allowed:false` gate
and runtime rollback are incomplete. Main/live hosts remain untouched.

NEXT: sign and admit the exact unified trial runtime through the
existing Pairing/Compose machinery (never RC7 fallback); then attach
this helper to the selected one-choice Foreign transaction before core
mutation, continue with the existing Sanaei/Gateway/redeem/promotion
and require actual two-direction Connected.

## Consolidation checkpoint — prebind exact Foreign 443 control URL, retain Node (2026-11-12)

In the existing **internal** one-choice option-2 flow, the Panel packet
pre-core scope now supplies the existing Node writer's fifth argument:
the exact, already-validated `https://foreign:443/smite-node/<32hex>`
control URL. This sets `SMITE_CONTROL_ADDRESS` before the very first
paused Node start. It eliminates the later need to force-recreate the
Node just to install the same metadata; no new installer/module/menu.

The existing `smite_foreign_gateway_recreate_node` now verifies the
prebound runtime control URL, paused/strict/managed flags, healthy Node,
and RC7 Compose ownership in the signed, selected **private-packet**
path. It returns `RETAINED_NO_RECREATE` without Docker mutation on an
exact match; on drift, it returns HOLD **without** fallback recreation.
The existing Gateway failure branch likewise refuses legacy force-
recreate rollback only in this scoped unified mode. Standalone Gateway
option 6 and historical/RC7 repair semantics remain unchanged.

Existing gateway and Foreign core regression suites now cover the
pre-boot address argument, no redundant env rewrite, no-recreate
success, unexpected running address, duplicate Docker env and
unchanged independent repair. Tests are offline fixtures, NOT evidence
of a live two-server installation or Connected status.

The public option 2 still pins official RC7 core and does not enable
the separately signed unified runtime: `activation_allowed:false`
continues to prohibit trial host activation. Main/live hosts, FRP,
Backhaul, Sanaei and prior identities remain unchanged. NEXT: reconcile
the existing signed Pairing/Compose runtime admission with the exact
unified trial image and test full retained rollback and two-way
Connected before public wiring and live install.

## Consolidation checkpoint — align exact Panel-issued control URL between Gateway and existing signed Pairing (2026-11-12)

Found a direct one-choice blocker: the Panel `smi1` JSON includes an
explicit `:443` in its `control_url`, and the existing fresh Foreign
Node now writes that exact address **before first boot**. The existing
Gateway formatter and the RC7 signed pairing preflight previously
formed an equivalent but **different string without `:443`**. That
would fail strict scope matching in the same option-2 lifecycle.

The existing `smite_foreign_gateway_configure` now keeps explicit
`:443` *only* for the selected fresh/private Panel-packet path.
The existing `smite-node-pairing.py` `_foreign_gateway_preflight`
checks the exact same spelling *only* in its previously read-only
`review_unified_trial` lane; default RC7 activation/rollback and
standalone Gateway repair preserve their prior checks and spelling.
The original immutable signed runtime gate remains unchanged,
`activation_allowed:false` and no new public option or activation
is introduced. Tests assert exact admission of explicit :443 and
rejection of alias spelling/drift with the correct signed trial image,
while the historical RC7 lane stays intact.

This is an offline preparation only, NOT a successful or remotely
connected installation. NEXT: reuse the signed pairing activation
transaction and rollback after reviewed admission, then full
two-direction Connected checks before exposing public option 2.

## Consolidation checkpoint — Foreign option-2 early HOLD + audited existing RC7 rollback (2026-11-12)

**User-impacting correction:** the public fresh option 2 previously
installed the *official* RC7 paused Node, committed its core journal,
then returned HOLD because the separate signed unified trial image
could not be activated. This stranded partial installs without
Sanaei/Gateway/Pairing and wasted a one-use Panel grant. It now emits
`FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES` **before** Docker,
prompting, packages, journaling, or filesystem mutations; it does not
pretend that the one-choice Foreign workflow is ready. The explicitly
selected older `clean-rc` offline/independent trial path remains
unchanged; Iran option 1 is unchanged.

**Reused existing transaction, no new engine:** both the existing
`activate_foreign_node_field_trial` failure rollback and
`rollback_node_to_paused_field_trial` now re-run
`_rc7_foreign_compose_command()` **after** the rollback force-recreate
and paused/strict, identity, replay, pinned-image proofs. The
pre-recreate `rollback=True` command alone cannot prove that Docker
relinquished the old security-candidate Compose overlay. A retained
candidate/foreign Compose label is a HOLD for manual rollback, or a
`CRITICAL` rollback-not-verified result when failed activation is
being recovered. It does not claim Connected or rotate keys.

The existing pairing and one-choice shell test suites cover a
simulate-successful Docker command which leaves the wrong active
Compose set behind, plus pre-install HOLD without host activity.
The signed unified manifest still has `activation_allowed:false`;
there is no trial image activation or any live host change.

NEXT: integrate signed unified image admission + **reviewed**
activation/rollback with the existing Pairing machinery, then
complete the menu option-2 one-choice run on isolated two-server
hosts. Only after independently confirmed bidirectional Connected
and user acceptance may it advance to main.

## Consolidation checkpoint — verify actual signed Compose after RC7 pairing (2026-11-12)

The EXISTING RC7 Foreign `activate_foreign_node_field_trial` now
reuses the EXISTING `_rc7_foreign_compose_command` helper with a
read-only `verify_active_candidate=True` selector after its signed
Compose apply and again after the signed two-way Panel proof.
The inspected, running Docker labels must show **exactly** the original
transaction-owned base Compose **plus** its original signed security
candidate; the same immutable image reference and local image ID
must still match. A successful `docker compose up` alone does not
establish this. Existing rollback handles any drift, and the
previously added post-rollback check verifies return to base-only
Compose, retained identity, replay and paused/strict runtime.

The same helper still requires base-only before normal activation,
permits [base,candidate] for reviewed rollback selection, and
rejects unrelated Compose files, project changes, and inconsistent
selector combinations. Existing tests now verify this exact
post-apply state and deliberate wrong-container-label recovery,
including that no signed HMAC/Connected claim is attempted when
the Compose witness fails. No new menu, image, installer, Pairing
endpoint, identity generation, or tunneling feature.

**This does NOT enable the unified trial image.** The signed
`activation_allowed:false` manifest remains enforced; the public
option 2 continues safe HOLD before host changes. Tests are offline,
not evidence of real bidirectional Connected. Next remains
release/admit signed unified Pairing/Compose via the SAME transaction
and two-server test on disposable hosts, with user approval before main.


## Consolidation checkpoint — same Foreign Pairing/rollback, signed trial image selected explicitly (2026-11-12)

To avoid a parallel installer or activation engine, the **existing**
`smite-node-pairing.py` `activate_foreign_node_field_trial` and
`rollback_node_to_paused_field_trial` now accept a **private, keyword-only**
`reviewed_unified_trial=True` selector. Default RC7 and RC.2 activation
and manual rollback remain unchanged and use their original digests.

The selector is gated **before** any host-changing action by the
**existing** `smite-unified-trial-pair-admission.py` manifest, SHA,
trusted-root and exact Panel+Node Cosign verification. It requires
`host_activation_allowed is True` for the frozen pair. The current
signed trial manifest explicitly says `activation_allowed:false` and
`release_approved:false`, and its verifier returns False. The new
selector therefore **always HOLDs today**, even when both image
signatures are genuine. No CLI/menu action or environment bypass was
introduced, and nobody should flip the manifest flag by hand.

Once an independently approved and signed release exists, this
same existing Pairing function is prepared to reuse the trial-only
exact Node digest, Panel-issued HTTPS/443 scope, Compose
base+security-candidate witnesses, replay/HMAC checks and failed
activation rollback with identity preserved. Offline tests confirm:
valid signatures plus an unapproved manifest HOLD **before Docker**;
invalid and overlapping selectors HOLD; a simulated approved gate
selects only the trial image review; and a simulated failed signed
proof returns through the existing rollback with trial-specific pin
and paused witness.

The release path is still **NOT ready to run**. In particular, the
Iran option 1 currently chooses the official RC7 source
`9a1270b3...` while the signed trial Panel+Node pair comes from
`b865be93...`. The signed install journal and both menu choices must
be aligned to a separately approved exact pair before allowing
any fresh host changes, followed by disposable two-server live
recovery and bidirectional Connected verification. The Foreign
public option 2 retains `HOLD_BEFORE_HOST_CHANGES`. Main,
production servers and existing FRP/Sanaei/Backhaul are untouched.

## Consolidation checkpoint — match exact selected RC7 image pair to existing install journal (2026-11-13)

The existing selected fresh-host installer now uses a read-only preflight
inside `smite-install.sh` to compare its selected RC7 source, version,
publication ref and signed Panel/Node manifest against the **original
imported `smite-rc6-install-journal.py`** constants and candidate images.
This review runs before installing Docker, pulling images, creating
containers or beginning a fresh journal. Any unsigned source/journal
drift returns HOLD.

The independently signed unified-install trial manifest is checked
separately and must remain an **unapproved, non-journal** source. The
current Iran choice still selects official RC7; the Foreign option 2
still holds BEFORE host changes until its full signed runtime/recovery
can be released and tested. This prevents mixing official Iran images
with unapproved foreign trial images in an unrecoverable transaction.
It does not by itself release an integrated image pair.

Existing Iran install test suite covers exact match, mutated journal,
unauthorized manifest approval, mismatched selected source and
pre-Docker/pre-journal ordering. No new menu, installer, engine,
installation feature or production host changes. Next: obtain an
independently approved exact paired source and align existing journal,
Pairing and two menu paths, then verify clean two-host signed
Connected and Rollback before release to main.

## Consolidation checkpoint — same exact Panel-issued HTTPS/443 scope at identity promotion (2026-11-13)

The existing `smite-foreign-install-promotion.py` identity promotion now requires the managed Node `SMITE_CONTROL_ADDRESS` to be **exactly equal** to the already verified Panel-issued `smi1` `control_url` including explicit `:443` and the reserved 32-hex path. Previously both `https://foreign/path` and the exact `https://foreign:443/path` were accepted; the alias made the final identity transaction less strict than the pre-boot Node writer, Gateway and signed Pairing admission. The Panel may continue to accept HTTPS default ports at the HTTP transport layer; this change only binds the new one-choice installer to its exact private credential scope.

Existing promotion, crash-recovery identity-phase, and *real companion Smite ASGI* offline integration tests now use the exact URL, and dedicated negative cases prove that the alias cannot promote an enrolled identity, including after a signed proof. No new menu, API, identifier, packet field, security engine or activation path. The signed trial manifest remains unapproved, selected option 2 stays HOLD before host changes, and main/live servers remain unchanged.

## Consolidation checkpoint — one real hidden-paste implementation across installer and ASGI contract (2026-11-13)

Eliminated two divergent internal no-echo intake implementations: the pre-existing disposable reader and the selected fresh option-2 reader now delegate to **one** `_capture_hidden_once` implementation inside the already existing `smite-unified-foreign-packet-intake.py`. Both retain 0700 owner-only workspace, exclusive fsynced 0600 packet, exact `smi1` parser, 2-hour TTL, secret-free scope review, no overwrites and terminal echo restoration. Expired or wrong-scope grants fail **before** offering operator confirmation, never generating an identity or network request.

The existing cross-repository Smite ASGI integration test now exercises `capture_selected_hidden_tty` (the same function the real option-2 helper invokes), then the existing `precore_fields` and actual Panel grant redemption, HMAC signed recovery and identity promotion using the SAME private packet. It additionally asserts that a no-`:443` Node env alias aborts BEFORE consuming the grant or writing the identity transaction; the exact Panel-issued scope then completes the disposable enrollment. No menu, panel API, runtime image, credential format or installer feature was added. Signed trial activation remains false; public Foreign option 2 remains HOLD before any host changes, main/live hosts unchanged.

## Consolidation checkpoint — no Panel rollback across changed existing Node state (2026-11-13)

The existing `PanelTransaction._new_enrollment()` used to compare
only `nodes.id` and `nodes.name` between its private SQLite online
snapshot and the current Panel database. This missed changes to
`metadata`, Pairing/provisioning/Connected fields or added schema
columns on an existing Node whose ID/name stayed identical. The
**same existing offline rollback** now compares complete Node rows,
failing closed *before touching any Panel/Nginx config* if anything
about a registered Node changed. It still never rewinds a database,
replay nonce or identity, and remains unreachable as a live host apply.

The existing panel-transaction suite tests metadata-only signed
check-in drift and a new Node column after the staged snapshot.
The existing cross-repository Smite ASGI integration suite additionally
compares the U-OPTI rehearsal's additive Foreign grant/origin SQLite
columns and unique/PK constraints to the **actual** pinned Smite
`foreign_install_grants.initialize_schema` output. This prevents a
separately maintained rehearsal schema silently differing from the
Panel release source. No new migration, flag, option, API or installer;
trial `activation_allowed:false` and the public option-2 HOLD remain.

## Installation integration checkpoint — Iran critical sequence before static UI (2026-11-13)

Reviewed Iran option 1 from the actual selected installer through TLS/443, RC7 image/journal verification, Panel+Iran Node core, signed local Node Pairing and admin creation. Previously the bundled optional static UI update ran **before** Iran signed Pairing and a static asset failure held the Node half-installed. The same `smite_install_finish_local_ir` now completes **Gateway → verified Iran signed Pairing → admin** before using the existing static UI updater. A cosmetic UI failure prints `IR_PANEL_STATIC_UI=REVIEW_OPTION_8` but does not misreport Pairing or require reinstall; existing UI options 8/9 provide backup/repair. Pairing/admin failures still HOLD and never produce `PANEL_AND_IR_INSTALL=COMPLETE`. Offline installer tests exercise every failure boundary and success order. No GUI redesign, new menu action, Node recreation or public host change.

## Integration checkpoint — Foreign release gate before Sanaei/Gateway, and Iran functional completion before UI (2026-11-13)

Audited **both existing selected menu choices**. Iran option 1 now completes its mandatory signed RC7 TLS/443 → Iran Node Pairing/Connected proof → administrator creation *before* attempting the existing static Panel UI patch. A static-only failure reports `IR_PANEL_STATIC_UI=REVIEW_OPTION_8` without blocking signed enrollment or forcing a fresh reinstall; real pairing/admin failure still HOLDs before any completion message. Existing UI backup/rollback remains unchanged, with no UI feature added.

The internal Foreign `smite_install_unified_foreign_after_core` previously treated **valid trial signatures alone** as sufficient to proceed to Sanaei/Gateway, despite `activation_allowed:false`. It now reuses the exact existing signed Panel+Node **release decision** from `smite-node-pairing.py`, not a second ad hoc verifier. The currently pinned unapproved trial therefore HOLDs **before Sanaei, Gateway, TLS changes or enrollment**. The original 18 simulated post-core failure/rollback sequences remain in CI, with a 19th actual-gate negative test proving that no downstream host function is called. This is not a public option-2 install or live activation.

Remaining blockers are the same concrete release steps: approved and newly signed compatible Panel+Node pair (not a hand-edited trial manifest), matching selected Iran and Foreign source/images and rollback journal, production-safe Panel transaction, full already-existing Foreign enrollment/identity/signed-activation orchestration, and isolated real-host bidirectional Connected/rollback proof. No change to main or running nodes/tunnels.
