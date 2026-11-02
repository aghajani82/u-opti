# Console-only release checkpoint — 2026-11-01

## Published checkpoint — 2026-11-02

Status: **READY_FOR_FRESH_HOST_TEST**. This supersedes the historical HOLD
entries below. The operator moved real VPS qualification after main release.

- U-OPTI PR #75 merged: `c1025b8241d1ff28663c91256ab02c43d615f25a`.
- Smite PR #42 merged: `b46dd5d5b1011a616af69f4ee22d2c0f7cca9c66`.
- U-OPTI tested PR HEAD: `03a9d13b648cfa4cd6cd316538145fd4160351c0`,
  all 25 checks passed, including real disposable Docker rollback retention.
- Smite selected HEAD: `25ff25585be3f7ff1c8b73b39a23d0509f9a2312`,
  all 19 visible checks passed. RC6 source/images/tag remain unchanged.
- U-OPTI main CI run 41376669578: SUCCESS.
- Smite main workflow run 41376649450: SUCCESS.
- U-OPTI release workflow run 41376669681: SUCCESS.
- Published release: https://github.com/aghajani82/u-opti/releases/tag/v0.17.0
  Tag points to the U-OPTI merge SHA above; no tag was moved.
- Superseded experimental PR #74 (U-OPTI) and #41 (Smite) were closed with
  explicit selection/exclusion notes. Their branches and commits are retained.
  Foundation PR #73 and #40 were already merged; no further action taken.

Use the official main installer for **fresh Ubuntu 24.04 amd64 hosts only**.
Smite Management → Install Components → 1 for IR / 2 for KH; interrupted new
RC6 installs use option 7 and ROLLBACK-RC6. Read the recovery document first.
The recovery path quarantines files and retains stopped containers/volumes;
it is not active-host migration or automatic restoration of mixed identities.

Remaining operator qualification: real fresh IR/KH setup, public TLS, Signed
Pairing/Inventory, new Owner/Child, G/1, fresh publication, Verify/client traffic
and reboot preservation. No claim of STABLE_RELEASE_COMPLETE is made.
No IR/KH/Grandoptical deployment, restart, rebuild or firewall mutation occurred.
Existing tunnels and runtime were not accessed. No historical branch, tag,
GHCR package or artifact was deleted. Destructive cleanup remains deferred.

## Current continuation — 2026-11-02 (supersedes historical gates below)

The operator explicitly requested interrupted-RC6 rollback completion, then
main merge/release, and real Ubuntu testing **after** main distribution. Do not
request this permission again. Real VPS success is still not claimed.

The new fresh-only journal and Install Components option 7 quarantine owned
files and retain containers/volumes without deleting data. Active/paired,
completed, foreign or replaced state is refused. A rollback interrupted between
rename and checkpoint is retryable. Historical RC1 recovery is untouched.
See `docs/SMITE-RC6-FRESH-INSTALL-RECOVERY.md` for exact scope and limitations.
Local failure-injection and installation regressions pass. The dedicated CI
workflow must verify actual disposable Docker retention before merge.

Also fixed an actual installer conflict: setting DOCKER_HOST caused the existing
Compose safety helper to reject fresh installation. The selected entry now
clears ambient overrides and pins Docker commands to the local socket. A unique
transaction-scoped Node volume prevents retry from adopting archived identity.
The retained inert broker group is reused on retry without changing the broker.

Prepared U-OPTI version: 0.17.0. Application images remain immutable Smite RC6
at source 25ff25585be3f7ff1c8b73b39a23d0509f9a2312; no tag move or rebuild.
Before merging, refresh both PR HEADs and CI, and verify the new recovery job.
After merging verify main and the automated U-OPTI release; report
READY_FOR_FRESH_HOST_TEST, not STABLE_RELEASE_COMPLETE. No live host action.

## Binding product decision

Passkey and independent Secure Web Approval were rejected by the operator.
The sole approved flow is: configure Sanaei KH inbound with the intended port
and path; create the FRP child in Smite; request XHTTP publication in Panel;
review on authenticated IR terminal using Smite Management G, then 1; return
to the same Panel dialog and explicitly submit a fresh final publication request.
Verify checks the signed FRPS listener; real VLESS/XHTTP traffic remains a separate test.
No automated approval, browser popup or alternate approval domain belongs in this release.

## Selected source, not a wholesale experimental PR merge

U-OPTI foundation: PR #73 `9370fcd4b44859eff7d4cb6924c3905b771a5885`.
Smite foundation: PR #40 `50eb4f174eef67049eff82dad194e762181f18ca`.
Selected U-OPTI console/menu changes from #74 `76ae65207e613c74c7b4a65fd96225ff8d6caff9`.
Selected Smite operator UI from #41 `3969855298ce7e63ea8a3f7824a0ae20aea09b2c`.

Both selected branches target main and retain the reviewed Stage15 foundation.
They do not include the experimental branch's approval services, Passkey labs,
Node attestation additions, broker web-marker/queue hook, or preview image tools.
Smite also removes the optional browser approval code rather than only hiding it
behind an empty build-time origin. Console-only policy tests reject reintroduction.
U-OPTI keeps the existing broker from #73 and adds G/1, role navigation and guards
against legacy image upgrade/rollback on existing FRP/WSS state.
Old experimental branches and historical releases are preserved for provenance;
they are not candidates for default installation.

## Completed checkpoint

- Separate local worktrees and release/stage15-console-only-20261101 branches.
- Selected console flow, manual publication, Verify feedback and compact sidebar.
- Local frontend typecheck/build and seven UI contract tests passed.
- Local root review (14), broker (30), nonce ledger (10), signed intent (9),
  KH inventory (16), guided roles (6) and existing menu regressions passed.
- New policy tests: three U-OPTI and two Smite checks passed.
- No live host action, restart, main merge, tag move, version bump, stable
  publication, old PR closure, artifact deletion or branch deletion.

## RC6 checkpoint — 2026-11-01 (supersedes earlier PR-body status)

Status: **HOLD_WITH_EXACT_BLOCKERS**. The operator has authorized candidate
publication and subsequent main merge/final release after technical gates pass.
No further permission is needed for those authorized repository actions.
Live IR/KH and Grandoptical changes remain prohibited.

Selected Smite PR #42 HEAD: `25ff25585be3f7ff1c8b73b39a23d0509f9a2312`.
Selected U-OPTI PR #75 parent before this checkpoint:
`ddc08a98200baa429743959508a8f218d23cdc57`. The commit containing this document
and its later descendants are the continuation point; refresh HEAD and CI.
Both selected PRs are still draft and unmerged. Main bases remain Smite
`4f91c5f341e810e545d75e93719c6ae3aaca69f3` and U-OPTI
`f989863b7d5ee3043122ffc7ebcb1925bf6fe144`. VERSION remains 0.16.7.

### Published and independently verified

- Immutable tag/prerelease: https://github.com/aghajani82/Smite/releases/tag/v2.0.0-rc.6
  targets the exact Smite HEAD above. Do not move/rebuild this tag.
- Publisher: https://github.com/aghajani82/Smite/actions/runs/41301898391 — PASS.
- Panel: `ghcr.io/aghajani82/smite-panel@sha256:1e5b34652abe24c5c1971dbbdb579bb270c6c571d289198ed15cd0373da1a0f4`
- Node: `ghcr.io/aghajani82/smite-node@sha256:60a7027b56b17ceb46348f7e107a3361723a95a9b1712634dc8d90b31f928388`
- Exact manifest is committed at `modules/smite-selected-candidate.json`.
  SHA-256: `26d4a50e23b6707b414a81ae9b2ca4aaa45e491481d2eb487010dcb7540ab04c`.
  Candidate booleans remain false; do not alter signed provenance semantics.
- Publisher ZIP artifact 13081652784 expires 2026-11-08T11:28:17Z.
  SHA-256: `8b81cca7de56a82b6d6eff5f32e6077fa015583a7dc00a3fcd7b764e746705c1`.
  ZIP and extracted manifest hashes were independently computed and matched.
- Independent real Cosign verification:
  https://github.com/aghajani82/Smite/actions/runs/41321919595 — PASS.
  Logs report immutable digest signatures and same reviewed source/tag verified;
  `INDEPENDENT_REAL_COSIGN_GATE=PASS`, `DEPLOYMENT_AUTHORIZED=NO`.
- Anonymous registry verification/pull, image labels, real container first boot,
  official FRP bytes and Node identity/replay/paused rollback:
  https://github.com/aghajani82/u-opti/actions/runs/41322198699 — PASS.
  Prior run 41322076001 failed because the archived first-boot fixture expected
  rc.0. The fixture now checks exact rc.6; authentication assertions are intact.
  This is Ubuntu 24.04 CI, NOT a real VPS network install or reboot test.

### Bounded installer changes in this draft

Fresh menu entries prepare the exact signed RC6 pair with templates and CLI from
its immutable source. Cosign 3.0.6 is privately downloaded and hash checked.
Existing or partial install paths (including broken symlinks), existing Smite
containers, unavailable Docker state, or failed signature/hash checks refuse
installation. Docker is restricted to the local socket. RC6 variables are scoped
so historical RC1 recovery/upgrade paths keep their original pins. Existing
explicit offline clean-RC behavior is retained. No active-host migration exists.

New isolated control-flow tests cover IR/KH dispatch, refusal cases, cancellation
and legacy scoping. They mock host operations and are not end-to-end installation.
Local update file-list (7), source pin (4), first-install adoption (9), update
transaction (11), rollback retention (3) tests passed. Clean-install, pending IR,
Nginx preflight, registry admission, guided-role and console-only tests passed.
Observe CI on the commit containing these new installer changes before promotion.

### Exact remaining gates

1. **RC6 partial-install recovery is not qualified.**
   `modules/smite-clean-ir-resume.sh` requires rc.1 environment versions, local
   image tags and the old offline archive. It must NOT be used for RC6. The new
   entry deliberately refuses existing/partial state. A minimal authenticated
   recovery/rollback path and failure-injection tests are required before main
   promotion. Selected RC6 error/cancel paths now return nonzero even after a
   successful UI pause; state-save/admin errors also refuse success. Historical
   menu return conventions remain unchanged. Early dependency-failure tests
   exercise both real entry functions. This is not transaction recovery.
2. **Fresh-host wizard/end-to-end qualification remains incomplete.** Existing
   role screens safely navigate and use HOLD where signed state is unproven.
   Qualify IR-first/KH-first, pairing, inventory, owner/child, G/1, fresh publish,
   restart/reboot persistence and rollback. Do not equate process presence with
   signed approval or replay protection.
3. **Real clean Ubuntu 24.04 VPS test remains PENDING**, to be performed by the
   operator after repository preparation. Five-tunnel live success is operator
   reported; it is not evidence of installation from main on a fresh host.
4. Main merge, final version/changelog/release trigger review, final stable release
   and post-merge CI remain undone. U-OPTI main VERSION/CHANGELOG/release.yml edits
   can publish automatically. Do not call the current RC6 prerelease stable.
5. Complete GHCR/transient artifact reference and rollback inventory before any
   cleanup. Retain experimental/history branches and old PRs until supersession
   is proved. No branch/tag/artifact deletion or old PR closure has occurred.

### Historical preservation

Archive: https://github.com/aghajani82/Smite/releases/tag/archive-stage15-reviewed-8edbd403-v1

Original outer ZIP SHA-256:
`55a4f55ebe6f14929c65fb05da96b60ea49f58480b3db9a46bf23c1395273575`.
Original inner ZIP SHA-256:
`d250b0fd27ae362bc4008b9e62208f94ae92fb71273d66bee83c9bcdcd1f75d9`.
Archive manifest SHA-256:
`5f909e4fa5c7b3428eaa4e33a4024ea6740fec828388762c3765a590c4267f1d`.
Preserve exact bytes without rebuild; this archive never replaces RC6 images.

## Resume protocol

Refresh remote branch HEADs and CI before edits. Continue from the selected
release branches, not #74/#41 wholesale. Record each completed work unit as an
independent commit. Never assume rate-limit reset resumes work automatically;
the operator will send a continuation message. The last pushed commit plus this
file is the recovery point if the interactive session stops.

Preserve Grandoptical, all existing tunnels including the newly successful field
test, FRPS Owner, FRPCs, Signed Pairing, Replay, TrustedGrants and Nginx state.
No new mandatory Backhaul dependency and no automatic public ports.

## Continuation — 2026-11-02

Remote HEAD 6619733e92403e1641d897ad2f0450da12dc4b00 had 23/25 checks
successful. Two failures were diagnosed, not waived:
- bash-validation job 124896332597: wizard-preservation pin still expected the
  installer before the reviewed RC6 entry. Re-reviewed bounded diff and updated
  only that file's blob pin; all independent wizard pins remain unchanged.
- anonymous-signed-pair job 124896332237: isolated dispatcher fixture ran as
  non-root. It now runs with sudo on the disposable Actions runner. The real
  root guard remains unchanged. Signature, image pull, real first boot and
  identity/replay checks passed before that fixture failed.

Local selected dispatch, legacy clean install, pending IR, historical RC1 resume,
Nginx prerequisite, console-only and role-guard regressions passed after fixes.
Smite selected HEAD remains 25ff25585be3f7ff1c8b73b39a23d0509f9a2312;
all 19 checks visible on that commit (including publisher jobs) were successful.
Observe the new U-OPTI commit's CI before declaring those failures resolved.
Partial RC6 recovery and real fresh-host testing remain blockers. No live host,
merge, stable release, tag move or historical deletion in this continuation.
