# Unified installer final audit — 2026-11-15

Owner request: enable Foreign option 2, merge to main, and test two fresh servers using the normal installation links. This request authorizes the work; another permission request is not the missing prerequisite.

## Verified starting state

- Smite main: `e7f76185e9a7da51d7069d5d0a829dc192cc1e06` (RC9). The Smite trial branch is already included in main.
- U-OPTI main: `aaf863a38eb256ed96d7ea5594f83a62cb3619fd`.
- U-OPTI trial start: `1214a41d3a83692086309dfd0af33233f5dbe40e`, 516 commits ahead of main.
- The successful run 43751580418 was the three-job Foreign installation client workflow, not the complete PR suite.
- PR #202 opens the complete integration checks. Initial full checks exposed stale fixtures in Broker admission, Sanaei failure propagation and legacy RC1/RC2 activation replay proof.

## Corrections committed during this audit

- Broker fixtures now bind each RC7/RC9 source to its exact managed version and upstream ref, and reject a mismatched version.
- Sanaei refusal tests explicitly require exit code 2 and retain the no-install assertions.
- Legacy activation fixtures supply retained replay proof. The RC1 test additionally checks that loss of replay proof pauses the Node instead of reporting success.
- No production security check was weakened to make these fixtures pass.

## Remaining implementation/release blockers

1. `smite_install_ir_foreign_schema_stage` migrates the schema but deliberately leaves flags unchanged. Fresh option 1 does not enable `SMITE_FOREIGN_INSTALL_ENABLED` and `SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED`, or apply the existing exact Foreign redeem/proof Nginx renderer. A working option 2 needs this Iran counterpart.
2. `smite-unified-trial-registry-pair.json` still has both release flags false. The common pair verifier requires false flags, and the trial admission returns `host_activation_allowed=False` unconditionally. Editing only the JSON flags cannot enable a valid release: all consumers and tests need one coherent, explicit release policy with the existing signature/source/digest checks retained.
3. The existing Panel upgrade host driver executes only on a disposable fixture root; it is not a real-root upgrade executor. The immediate requested scope is fresh servers, so the fresh Iran installation path should be integrated with existing schema, pairing and ingress functions rather than treating the fixture driver as a deployer.
4. Foreign Core/Identity execution uses the shared release admission and remains blocked until that release policy is complete. Preserve per-stage rollback, retained Node identity, exact TLS/443 ingress and two-way signed activation verification.
5. Full PR CI and final merged-source checks must be inspected. Two real fresh-server Connected and interruption/resume results remain pending; CI is not that evidence.

No server was changed by this audit. Main was not moved and option 2 was not activated. Existing signed image digests remain unchanged. Do not describe this branch as ready for two-server installation from main until the missing Iran integration and coherent release admission are complete.

## Post-audit integration update — 2026-11-15

This section supersedes the *implementation status* of blocker 1 above; the
original audit remains as a record of what was missing at the time.

- **Blocker 1 — code integrated on trial (host acceptance pending).**
  `smite_install_ir_foreign_schema_stage` still uses the original, backup-aware
  Smite SQLite migration. Only after signed Iran Node and administrator have
  passed, it now calls the existing
  `smite-node-pairing.py --complete-local-ir-foreign` controller. The controller
  reuses the exact `smite-unified-panel-stage._candidate_env` security flags
  and `smite-foreign-install-panel-ingress.render` TLS/443 Nginx
  redeem/status locations. No extra menu, credential issuer, Compose project,
  identity or FRP/Backhaul code was introduced. The same root-owned install
  Journal holds a private preimage+candidate receipt before two config writes.
  The staged step requires effective signed Panel flags, Nginx syntax and
  reload; on error only its original Panel env/Nginx files are compensated.
  A fully committed repeat checks current state without recurring Nginx
  reload/Panel recreation. Failed review leaves `ADMIN_CREATED` for option-1
  retry without regenerating Iran Node identity.
- **Isolated evidence:** the existing `test-smite-local-ir-install.py` now
  checks real original renderer output, exact two HTTP locations, idempotence,
  interrupted-step recovery, failed Nginx compensation and tampered-receipt
  HOLD. `test-smite-ir-foreign-schema-stage.sh` verifies that schema migration
  precedes the existing Foreign runtime/ingress step, with a HOLD on missing
  post-migration readiness. The Foreign client integration run
  [43755920318](https://github.com/aghajani82/u-opti/actions/runs/43755920318)
  reports successful direct tests. These are isolated tests, **not** live IR/KH
  Connected proof.
- **Byte-level wizard safety:** only the intentionally edited
  `modules/smite-install.sh` hash was reviewed and re-pinned in
  `tests/test-smite-wizard-preservation.sh`. The separate Docker, Private
  Network, EasyTier and legacy wizard pins remain unchanged.
- **Blockers 2/4 remain genuinely closed:** candidate flags stay
  `release_approved=false`, `activation_allowed=false`, and the independent
  admission still says `host_activation_allowed=false`. A signature check
  over two candidate images is not an authorization to enable production or
  assert Foreign `Connected`.
- **Blocker 3:** retained Panel *upgrade* executor remains disposable-only;
  it is not part of the newly integrated **fresh-install** lane.
- **Blocker 5:** complete PR #202 19-job workflow and two independently
  witnessed real-host signed/restart/rollback results are separate gates.
  The prior complete-suite Backhaul two-host runner exposed a manual-review
  HOLD; never weaken FRP or recovery rules merely to turn this green.

**Do not rebuild live hosts or merge trial into main based on these offline
results.** The code closure is not the signed release or real two-host
acceptance.

## Post-audit safeguard — 2026-11-16 (Iran option 1 retained completed stage)

A further integration review found that the **already completed** original
Iran Foreign flags/443 stage would fall through to the normal installer
`docker compose up --force-recreate smite-panel` if its effective runtime
flags subsequently drifted while its sealed `complete` receipt and two
config snapshots still matched. This violates the established completed-stage
read-only retry contract.

The existing `smite-node-pairing.py::_fresh_ir_foreign_ready_config` now
**HOLDs before any service mutation** when an already-sealed completed
checkpoint has mismatched effective Panel flags. It preserves the original
Journal, Panel env, Nginx bytes, signed identity and completion receipt, and
requires reviewed repair instead of automatically recreating Panel. The
existing fresh/incomplete-stage compensation and retry path is untouched.
`tests/test-smite-local-ir-install.py` now simulates this exact runtime drift
with original fixture configs and asserts zero Panel recreation, zero Nginx
reload and unchanged sealed inputs.

This does not remove the release/host blockers: RC9 still has
`release_approved=false` and `activation_allowed=false`, real Foreign
option 2 remains HOLD, and no new IR/KH Connected or restart/interruption
proof has been collected. Full PR checks must be evaluated on the **new
branch head**, not conflated with a previous green commit. Production
Grandoptical, IR/KH hosts, FRP/Backhaul and `main` are unchanged.

## Signed pair release-policy contract preparation — 2026-11-16

The final PR CI on the previous head `0d19279769ede8fd6a9ee09d9d1249d9176c6c9f` finished **9/9 workflow SUCCESS**, including the complete **19/19 CI** and the Foreign client CI. This is still offline evidence.

The ORIGINAL `smite-registry-pair-admission.verify_pair` now supports two **explicitly selected** policies without changing its immutable source, publisher OIDC identity, two digest checks, independently pinned manifest hash or Sigstore trust-root verification:
- `candidate` (default and all existing read-only review CLIs): requires both policy flags **false** and returns no host approval.
- `host_release` (internal activation gate only): requires both flags **true**, a pinned trusted root and matching independently supplied exact manifest digest. The existing `smite-unified-trial-pair-admission.verify` requires a separate `require_host_release=True` selector to obtain `verified_host_release_pair`. The EXISTING original Pairing activation calls this stricter release contract. The preserved original RC6/RC9 journal separately requires policy bits to agree and exact independently pinned digest/source/image owner.

The existing RC9 manifest still has **false/false**. The original Smite image publisher still emits only a **NON-activating candidate**; it has not issued an approved host release, and its two signed image digests do **not** sign the deployment decision. A future host release requires a separate reviewed publisher/owner decision, an immutable new manifest hash and coordinated pinned consumers; changing two flags alone cannot pass this code. A synthetic approved manifest appears **only in offline negative/positive regression fixtures**, never on an operational host.

**Still HOLD:** real-root Foreign option 2, two-host independently witnessed signed `Connected`, restart/interruption recovery, and final `main` merge. No production hosts/FRP/Backhaul/Sanaei changed by this policy preparation.

## Public two-option menu dispatch closure — 2026-11-16

A direct review of the original `show_smite_install_menu` exposed a user-visible
legacy dispatch problem: `SMITE_INSTALL_PROFILE` is shell-inherited, and an
environment left as `clean-rc` diverted BOTH public options 1 and 2 into
`smite_install_panel_iran` / `smite_install_foreign_node`, bypassing the
new one-choice RC9 stage coordinator. This could mislead the operator and
violate the expectation that the **same two public menu options** own all
previously integrated pairing, HTTPS/443 and recovery stages.

Only the EXISTING menu entry call sites now scope `SMITE_INSTALL_PROFILE=stable`
for public option 1 and option 2, so `smite_install_selected_fresh` selects
its integrated RC9 paths and its existing fail-closed Foreign release HOLD.
The legacy `clean-rc` direct helper, old recovery menu option 7 and all other
wizard paths remain intact. No menu entry, permission, port, identity,
or install feature is added.

The EXISTING `test-smite-unified-foreign-after-core.sh` now executes the
actual public menu twice from a simulated inherited legacy profile and checks
`panel-iran:stable` / `foreign:stable`, no error, and restoration of the
original shell profile. The reviewed install-script blob is re-pinned only
in the existing wizard-preservation guard. This is an offline shell
regression, not proof of host `Connected`.

**Release remains HOLD:** the RC9 manifest still has
`release_approved=false`, `activation_allowed=false`.
No servers, FRP/Backhaul/Sanaei, Smite source, or `main` changed.

## Owner-signed host-release proof — preparation on trial, 2026-11-16

A security review identified a missing distinction in the previous
`required_policy="host_release"` code: two valid **image** signatures,
matching true/true manifest flags and a locally pinned manifest hash still
do not prove that the *owner signed the deployment decision*. The existing
common admission now additionally requires a non-symlinked, single-link
pinned Sigstore **bundle of the exact approved-manifest bytes**, verified
through `cosign verify-blob` against the original trusted Sigstore root,
exact `aghajani82/u-opti` existing review-workflow identity, GitHub OIDC
issuer, independently pinned review commit SHA and
`workflow_dispatch` trigger. No wildcard signer or unsigned flag is
accepted. Candidate read-only verification remains identical.

The EXISTING `.github/workflows/smite-unified-trial-signed-pair-review.yml`
now has an **owner-only manual dispatch** mode, separate from its unchanged
read-only push mode: independently recheck the two signed RC9 image digests,
validate explicit owner consent and exact reviewed U-OPTI source,
produce deterministic true/true approval bytes, require a separately
precomputed exact approved SHA256, keylessly sign and verify those bytes,
and upload the manifest + Sigstore bundle for independent code review.
No new workflow, image build, code feature, public port, server change
or automatic deployment is introduced.

**Current decision remains HOLD.** The pinned trial manifest is still
`false/false`; NO owner-approved release manifest or bundle has been
issued, and the host activation gate has no pinned manual workflow SHA,
bundle SHA or signed approval file. A synthetic true/true fixture with a
mocked Cosign runner is NOT real approval. Before live test, independently
review the manual workflow result, exact approved manifest/bundle hashes,
the signed identity and the U-OPTI pinned consumers. Only a future
explicitly reviewed U-OPTI branch change may select those exact reviewed
assets. A green CI on this preparation does not authorize Foreign option 2.

The end goal remains the two original one-choice entries with stage-owned
resume/rollback, followed by actual independently witnessed two-host
signed `Connected`, retained FRP/Backhaul/Sanaei and final merge.

## Release-workflow trigger correction — same trial branch, 2026-11-16

GitHub `workflow_dispatch` requires the workflow file to exist on the
repository's **default branch**. The owner-signing reviewer only exists
on `trial/unified-smite-install`, and `main` must not be changed before
final acceptance. Therefore the earlier manual-dispatch intent could
not actually be executed; that design has been superseded.

The SAME existing signed-pair review Workflow now uses its current
`push` trigger for a narrowly guarded owner approval:
- An inert, explicit request at
  `docs/RC9_OWNER_RELEASE_APPROVAL_REQUEST.json` is committed with
  `approved=false`. This does **not** authorize installation or signing.
- Only a subsequent **owner-originated commit modifying that one
  existing file and NO other source/workflow file** is eligible to run
  the original workflow's approval job. Its strict JSON content must
  have `approved=true`, exact immutable Smite source, exact candidate
  SHA-256, precomputed approved true/true manifest SHA-256 and
  `fresh-two-host-rc9` scope.
- The job independently verifies both original GHCR signatures,
  derives exactly the pinned approved manifest, uses keyless GitHub
  OIDC to sign the **manifest bytes**, verifies its bundle using
  `cosign verify-blob`, then publishes ONLY the signed approval
  artifact. Both signer and consumer now require
  `--certificate-github-workflow-trigger=push` with a pinned exact
  U-OPTI workflow commit SHA. The existing read-only push review is
  unaffected; no Workflow file or server outside the trial changes.
- A successful manual owner edit and signing run is STILL NOT an
  automatic deployment: its actual approval manifest, reviewed bundle
  hash and signer commit SHA must be separately pinned into all
  existing U-OPTI host consumers after code review, followed by a
  real two-host acceptance run and final `main` review.

**Current status: request default `approved=false`, no owner
approval issued, no activation authorized.** This corrects an
unusable trial-only dispatch design without touching `main`,
creating a new Workflow, or broadening any Smite user-facing feature.

## Owner approval replay guard and independently computed hash — 2026-11-16

A follow-up audit of the **existing** RC9 release gate confirmed that
the frozen false/false candidate's exact SHA-256 still matches its
reviewed pin. Deterministic reserialization as true/true with the
existing canonical sorted JSON and trailing newline produces the exact
`a2c368a9f7da64e0494b8c6534cdccd2f4a11974927983fe298596b41ffcef2f`
SHA already in the owner request. This is an offline calculation, **not
an approved release**.

One missing fail-closed condition was fixed in that SAME existing
workflow: a request push must be a strict first
`approved=false → approved=true` transition and all six other pinned
fields must remain unchanged from its direct parent commit. A second
push merely changing the formatting of an already true request cannot
issue a second owner signature. The existing single-path commit
restriction and owner/account branch checks remain in force.

The existing release-admission test suite now recomputes the approved
manifest SHA directly from the committed candidate and checks all
request/workflow identity pins. Another offline regression simulates
two successful image signature verifications followed by a failed
`cosign verify-blob`, and requires an unconditional HOLD before any
host authorization. No extra workflow/menu/service or feature.

**Evidence:** previous head `c8b24084` completed 9/9 PR workflows
and 19/19 CI jobs SUCCESS, while the existing signed-pair branch
review completed successfully with the owner approval job SKIPPED.
The current release request stays `approved=false`, with no owner
blob issued and no approved U-OPTI runtime bundle pinned. Real
Foreign option 2 remains HOLD. The exact-head checks for this
commit must be recorded separately; do not claim real two-server
Connected or restart/rollback proof from CI.

## Owner release: entire-push review, not last-commit only — 2026-11-16

The existing owner-only signing job previously checked only
`HEAD^..HEAD` and loaded the request's prior value at `HEAD^`.
If an operator pushed **several commits together**, including unrelated
verifier/workflow/source edits followed by a final false→true approval-file
commit, this checked only that last commit and could omit the prior
changes from the mandatory release review.

The original job now fetches the original full history, explicitly checks
`github.event.before` as a real, nonzero, immutable 40-hex commit and
requires it to be an ancestor of `github.sha`. The entire incoming push
must change exactly `docs/RC9_OWNER_RELEASE_APPROVAL_REQUEST.json`;
the original request at the **before-push** commit must be
`approved=false`, all immutable fields identical, and the latest request
must be `approved=true`. New branch creation, force-push/reset, unknown
base, multi-file or multi-commit code-change pushes fail closed.
Existing owner, scope, signed blob, OIDC identity and two independently
signed images remain unchanged. The original test suite now explicitly
asserts the full-push predecessor/diff rather than the old one-commit
comparison.

This is a defect correction in the **same existing** review workflow and
same branch/PR; no new features or host authorization. The request and
candidate flags remain `false/false` and `approved=false` respectively.
No operational host, `main` or current signed identity changed.

## Trial owner sign-off run — selection-failure correction, 2026-11-16

The explicit two-disposable-host approval was recorded as the
SINGLE-file commit `2c5e4a55b945f1d27eedde978befcf8117bfb9f6`
after its parent passed 9/9 workflows and 19/19 CI jobs. The
existing real GitHub Actions run
`43808451226` **skipped** `owner-approved-release` despite
GitHub showing `actor=aghajani82`, event `push`, exact intended
commit message and a verified one-file request diff. Therefore
**NO OWNER-SIGNED RELEASE WAS ISSUED** on that run; a green
`independent-ghcr-cosign` alone is not release approval.

The job-level condition depended on
`github.event.head_commit.modified`; the actual Contents-API push did
not match that filename list. The existing job now uses an EXACT,
owner-authored release-approval commit **message** for selection,
while its unmodified fail-closed shell gate independently checks the
owner, branch, direct commit subject, entire incoming push range,
single exact request file, prior false→current true, no other pin
changes, signed source/digests, and downstream Cosign OIDC
verification. A spoofed message without the original signed consent
cannot pass the shell gate. This is a trigger-fix in the SAME workflow,
not a second release facility or a feature.

To avoid signing an already-true replay request, this correction commit
also returns the sole request to `approved=false`. The approved
two-test-host intent remains valid, and the next attempt must be a
separate approval-file-only commit with the exact message. Until a
real `owner-approved-release` SUCCESS and separately verified
Sigstore artifact exist, the host-release gate still HOLDS. No
server, `main`, FRP, Backhaul or Sanaei state changed.

## RC9 owner-signed host-release issued and independently retained — 2026-11-16

**Issued, signature VERIFIED; deployment not yet executed.** After explicit
owner approval limited to the two disposable Iran/Foreign hosts, the
original signing workflow successfully ran at
[GitHub Actions run 43808835299](https://github.com/aghajani82/u-opti/actions/runs/43808835299)
with both `owner-approved-release` and `independent-ghcr-cosign` SUCCESS.
The exact signer/OIDC workflow commit is
`521449e0c4112ef4d8c42b78da3d0778ae256b6e`,
GitHub actor `aghajani82`, trigger `push`, branch
`trial/unified-smite-install`. The single request file
`docs/RC9_OWNER_RELEASE_APPROVAL_REQUEST.json` changed strictly from
`approved=false` to `approved=true`; all source/digest/scope pins
remained unchanged.

Original immutable signed Smite v2.0.0-rc.9 source:
`e7f76185e9a7da51d7069d5d0a829dc192cc1e06`.
Panel `sha256:f6999effd131f6b3272f8d9116b3fbae917f699bf9a29271fc5ede24cc387a2e`;
Node `sha256:3df3c9d40c338ab87205bbe93e9ab9bd94eb4051558c4429fdd09f876b76b2c2`.
The original public **candidate** still has both policy flags false
and remains in place for all existing read-only tests.

The issued true/true manifest, WITH its original signed Sigstore bundle,
was downloaded by the reviewer from the existing GitHub Actions
artifact `14199846104`, then examined outside the GitHub runner:
- `docs/rc9-release-evidence/approved-manifest.json`: SHA256
  `a2c368a9f7da64e0494b8c6534cdccd2f4a11974927983fe298596b41ffcef2f`;
- `docs/rc9-release-evidence/approved.sigstore.json`: SHA256
  `d63e3d38248eb4dba9ddcb9f585c27b915247edd151ea8d689e418b49b246586`.
- Original ZIP: SHA256
  `789f2da74d1a9acd4948c7e938e34e75eb8858967c53d65b624ffbe66e278ca2`,
  [artifact run](https://github.com/aghajani82/u-opti/actions/runs/43808835299);
  temporary run artifact expires 2026-11-23T05:14:10Z.
- Independent inspection verified the exact SHA256 digest in the bundle,
  ECDSA signature over the approved manifest, the Sigstore certificate
  SAN for U-OPTI's original reviewed workflow, GitHub OIDC issuer,
  push trigger, repository and exact signing commit. The GitHub runner
  additionally used Cosign 3.0.6 with the original pinned Sigstore
  root and returned `OWNER_RELEASE_BLOB_SIGNATURE=VERIFIED_NO_DEPLOYMENT`.
  Repository evidence files preserve both signed sources after the
  temporary ZIP expires.

The EXISTING release-admission regression checks these evidence hashes,
manifest-to-candidate byte-equivalence except for the two policy bits,
the bundle's exact message digest and the untouched false/false trial
candidate. No feature, PR, Workflow or host operation was created.

**Important remaining execution gates:** The original U-OPTI installed
Foreign option 2 is NOT automatically enabled merely by issuing the
owner's signed release. Its current candidate-only preflight and original
root-owned activation/rollback stages still require a coherent exact
approved-bundle pin and reviewed two-test-host boundaries. DO NOT hand
swap manifest flags or run an unsupported private Python entrypoint.
Only after those same original consumers adopt and independently
verify the exact approved manifest/bundle/workflow SHA, and the fresh
Iran/Foreign baselines are reviewed, may host installation be attempted.
Two-host signed `Connected`, restart/interruption rollback and
retained FRP/Backhaul/Sanaei verification remain unproven. Keep
`main` unchanged and PR #202 Draft.
