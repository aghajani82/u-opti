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
