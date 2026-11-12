# Unified Smite installation — trial plan and continuation record

Updated: 2026-11-12 (Asia/Tehran)
Status: DESIGN / IMPLEMENTATION STARTED — NOT READY FOR HOST INSTALLATION
Branch: trial/unified-smite-install
Base: aaf863a38eb256ed96d7ea5594f83a62cb3619fd

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

## Milestones
- [x] Create isolated U-OPTI branch from current main.
- [x] Persist this plan before implementation.
- [x] Inventory current U-OPTI and Smite enrollment/origin/replay paths; record exact sources.
- [x] First implementation checkpoint: explicit Sanaei attachment result codes and isolated regressions.
- [x] Implement and test the inert installation-grant store: UUID/name/domain binding, 2-hour expiry and atomic identity/origin commit. Gated HTTP administrator authorization is implemented; UI remains pending.
- [ ] Implement companion Smite trial branch: authenticated issuance/revocation, atomic redemption, safe origin authorization and UI.
- [ ] Handle credential loss/retry/expired/revoked codes without duplicate identities or secret logging.
- [ ] Build and verify signed trial images; bind installer to their exact digests.
- [ ] Integrate existing Iran flow and verified continuation.
- [ ] Integrate Foreign installer with structured failure propagation and Sanaei return-to-caller.
- [ ] Reconcile completed phases; refuse drift; resume incomplete phases without destructive reinstall or rekey.
- [ ] Simplify ordinary menu entries; preserve advanced recovery access and standalone Sanaei.
- [ ] Test positive, negative, retry and rollback paths; full applicable CI.
- [ ] Publish exact trial installation command only when runnable.
- [ ] Mohammad tests fresh Iran and Foreign; record output and limitations.
- [ ] Merge only after explicit user acceptance.

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

## Latest checkpoint
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
