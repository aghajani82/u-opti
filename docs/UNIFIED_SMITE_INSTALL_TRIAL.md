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
