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
- [ ] Inventory current U-OPTI and Smite enrollment/origin/replay paths; record exact sources.
- [ ] Define and test admin-authorized single-use enrollment bound to node UUID, foreign role, name and approved HTTPS domain/control path.
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
Branch created; baseline inspected. No runtime code changed yet.
Next: inspect fork Smite pairing schema, credential issuance/redemption and foreign origin transport policy; settle the secure grant/retry contract before wiring installation.
