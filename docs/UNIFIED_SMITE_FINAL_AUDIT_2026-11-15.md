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
