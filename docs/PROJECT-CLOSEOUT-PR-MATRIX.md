# CLOSEOUT — GitHub Draft PR Dependency Matrix

**Reviewed:** 2026-10-21 (final source-closeout reconciliation on U-OPTI Draft #48)  
**Tracker:** [U-OPTI Issue #47](https://github.com/aghajani82/u-opti/issues/47)  
**Context:** [Cross-chat handoff](PROJECT-CLOSEOUT-HANDOFF.md)  
**Status:** Inventory of PR parent branches and declared scope only; individual line-by-line diff/conflict review is **NOT COMPLETE**. No PR has been approved for merge.

## Critical insight

The original 36 Draft PRs (U-OPTI #27–#46 and Smite #1–#16) are **not** 36 independent mergeable patches. U-OPTI **#48** is the additional ongoing consolidation PR, not another numbered stage.

- **U-OPTI**: [#27](https://github.com/aghajani82/u-opti/pull/27) is a separate root based on `main`. [#28](https://github.com/aghajani82/u-opti/pull/28) → ... → [#46](https://github.com/aghajani82/u-opti/pull/46) is a stacked chain based on the previous PR's head. Evidence of overlap: the auth overlay `modules/smite-panel-auth-overlay.py` in #27 and #46 has identical Git blob SHA `d9b9a0533c8afff7b07821aee588a41289e3cc2c`. Do not merge it twice or mark all #27 code redundant without checking the remaining files.
- **Smite**: [#1](https://github.com/aghajani82/Smite/pull/1) → ... → [#16](https://github.com/aghajani82/Smite/pull/16) form a single stacked chain from `main`.
- `main` U-OPTI still selects older stable Smite images and is intentionally unaffected by the draft security/RC stack.

## U-OPTI Draft chain

| PR | Base | Reviewed intent / area |
|---|---|---|
| [#27](https://github.com/aghajani82/u-opti/pull/27) | main | Admin JWT host overlay; **parallel root** |
| [#28](https://github.com/aghajani82/u-opti/pull/28) | main | Standard Node localhost 8888 only; **main chain root** |
| [#29](https://github.com/aghajani82/u-opti/pull/29) | #28 | Node pairing preparation wizard |
| [#30](https://github.com/aghajani82/u-opti/pull/30) | #29 | Paired gateway readiness |
| [#31](https://github.com/aghajani82/u-opti/pull/31) | #30 | Inert auth Compose candidates |
| [#32](https://github.com/aghajani82/u-opti/pull/32) | #31 | Image vs overlay compatibility preflight |
| [#33](https://github.com/aghajani82/u-opti/pull/33) | #32 | Offline overlay review bundles |
| [#34](https://github.com/aghajani82/u-opti/pull/34) | #33 | Signed Agent Nginx path-preserving candidate |
| [#35](https://github.com/aghajani82/u-opti/pull/35) | #34 | Dual-host read-only admission |
| [#36](https://github.com/aghajani82/u-opti/pull/36) | #35 | Paired preview + missing admin overlay integration |
| [#37](https://github.com/aghajani82/u-opti/pull/37) | #36 | Paired offline archive integrity |
| [#38](https://github.com/aghajani82/u-opti/pull/38) | #37 | Clean fresh RC install, avoids repeated install |
| [#39](https://github.com/aghajani82/u-opti/pull/39) | #38 | **LAB** host executor journal/crash recovery |
| [#40](https://github.com/aghajani82/u-opti/pull/40) | #39 | **LAB** plan-bound Compose recovery |
| [#41](https://github.com/aghajani82/u-opti/pull/41) | #40 | **LAB** fd-relative path protection |
| [#42](https://github.com/aghajani82/u-opti/pull/42) | #41 | **Mock-only** signed runtime checker |
| [#43](https://github.com/aghajani82/u-opti/pull/43) | #42 | Real ASGI FastAPI + SQLite replay tests |
| [#44](https://github.com/aghajani82/u-opti/pull/44) | #43 | Explicit replay DB lifecycle compatibility |
| [#45](https://github.com/aghajani82/u-opti/pull/45) | #44 | Real isolated Nginx TLS443 HMAC path/query/body tests |
| [#46](https://github.com/aghajani82/u-opti/pull/46) | #45 | Real loopback source ACL, identity drift, recovery HOLD, and **this documentation** |

## Smite Draft chain

| PR | Base | Reviewed intent / area |
|---|---|---|
| [#1](https://github.com/aghajani82/Smite/pull/1) | main | Admin API authorization |
| [#2](https://github.com/aghajani82/Smite/pull/2) | #1 | Node HMAC envelope and enrollment design |
| [#3](https://github.com/aghajani82/Smite/pull/3) | #2 | Atomic pairing and encrypted key store |
| [#4](https://github.com/aghajani82/Smite/pull/4) | #3 | JWT-gated pairing API |
| [#5](https://github.com/aghajani82/Smite/pull/5) | #4 | Pairing admin preview UI |
| [#6](https://github.com/aghajani82/Smite/pull/6) | #5 | Signed Agent APIs + SQLite replay |
| [#7](https://github.com/aghajani82/Smite/pull/7) | #6 | Actual signed Panel NodeClient HTTPS443 |
| [#8](https://github.com/aghajani82/Smite/pull/8) | #7 | Signed Node registration/check-in |
| [#9](https://github.com/aghajani82/Smite/pull/9) | #8 | Admin-only Node operations + scoped gateway |
| [#10](https://github.com/aghajani82/Smite/pull/10) | #9 | Unpublished isolated security image builds |
| [#11](https://github.com/aghajani82/Smite/pull/11) | #10 | Backhaul signed dispatch + optional FRP WSS |
| [#12](https://github.com/aghajani82/Smite/pull/12) | #11 | Pinned signed Node control origins |
| [#13](https://github.com/aghajani82/Smite/pull/13) | #12 | Paired version source/release contract |
| [#14](https://github.com/aghajani82/Smite/pull/14) | #13 | Offline Panel+Node image bundles |
| [#15](https://github.com/aghajani82/Smite/pull/15) | #14 | Simplified IR/KH UI and opt-in MFA |
| [#16](https://github.com/aghajani82/Smite/pull/16) | #15 | Explicit first-time SQLite replay provision, no request-time reinit |

## Actual parallel PR #27 overlap resolution (reviewed)

Six changed files in U-OPTI #27 were compared to the newest U-OPTI chain:

| File | Finding in #46/#48 chain |
|---|---|
| `modules/smite-panel-auth-overlay.py` | **Byte-for-byte same Git blob**, SHA `d9b9a0533c8afff7b07821aee588a41289e3cc2c` |
| `tests/test-smite-panel-auth-overlay.py` | **Byte-for-byte same Git blob**, SHA `89621bb7d2bafdd2680472ca4d5d0326fba2fd29` |
| `install.sh` | Contains exact module download/package list entry |
| `u-opti` | Contains original overlay source and download/update mapping entries |
| `modules/smite.sh` | Runs the same fail-closed `smite-panel-auth-overlay.py` hook after host overlay copy; comments differ because Stage14 integrated it |
| `.github/workflows/ci.yml` | Performs `tests/test-smite-panel-auth-overlay.py` inside Stage14 integrated compatibility/regression CI; placement differs |

**Verdict:** No independent #27 merge is needed for its intended admin-overlay behavior. Keep the existing Draft for history; no PR closure/rebase/merge has been authorized. This is functional/code equivalence evidence, not a proof that all other merged-together code is production ready.

**Ongoing one-branch closeout:** [U-OPTI Draft #48](https://github.com/aghajani82/u-opti/pull/48) (stacked on #46), beginning with the real updater rollback-backup retention fix and offline regression. Any further needed fixes should be collected there where possible, rather than per-topic Draft PRs.

## Workstream reconciliation, not merge instructions

| Workstream | Source/CI closeout status | Remaining external gate |
|---|---|---|
| Auth, identity and MFA | **SOURCE/CI COMPLETE:** paired HMAC, durable Replay enrollment/key binding, stale-restore HOLD/witness, encrypted Panel pairing store, Fernet all-row decryptability regression, original admin controls retained | Real snapshot-backed Panel master + old→new Node UUID recovery rehearsal on approved disposable hosts |
| Image and release provenance | **SOURCE/CI COMPLETE:** exact source pins, paired unpublished images, manual-only digest-only publisher, keyless certificate SHA/repo/trigger policy, independent U-OPTI pair admission | Owner-authorized real GHCR candidate publish and independent real Cosign/provenance verification |
| Nginx 443 signed control | **SOURCE/CI COMPLETE:** isolated real Nginx TLS443 HMAC/path/query/body and signed Agent regressions | Actual integrated IR/KH public 443 route/SNI/firewall verification during field trial |
| Independent engines | **SOURCE/CI COMPLETE:** FRP and Backhaul independent package/control paths, shared transaction lock, official artifacts, coexistence, exact rollback, signed restart lifecycle; new explicit Backhaul disposable-host executor is packaged but menu remains HOLD | Approved two-host Backhaul install + dynamic Sanaei XHTTP/443/reboot/reconnect/rollback trial |
| Safe state mutation | **SOURCE/CI COMPLETE:** durable U-OPTI update/first-adoption journal, SIGKILL recovery, engine journal/rollback, drift refusal and signed prior-runtime recovery | Real VPS filesystem/reboot/snapshot behavior under owner-approved trial |
| Beginner UX | **READY FOR FINAL FIELD VALIDATION:** simple existing menu remains unchanged; install button intentionally HOLD | Enable only after field evidence, then one IR→KH→Sanaei→port/path→tunnel→VERIFY flow; no new wizard |

## Final consolidation audit — 2026-10-21

Current top-of-stack relationships were re-checked directly through GitHub:

- U-OPTI #48: base = `feature/smite-stage28-ingress-identity-recovery-20261019` (Draft #46 head), final closeout branch = `feature/uopti-smite-closeout-integration-20261019`; GitHub reports `mergeable=true`.
- Smite #16: base = `feature/smite-simple-operator-ui-20261018` (Draft #15 head), final closeout branch = `feature/smite-strict-replay-store-admission-20261019`; GitHub reports `mergeable=true`.
- These top branches contain their stacked ancestors in Git history. Therefore final release review should use **one consolidated top-head→main diff per repository**, not a sequence of dozens of overlapping merges.
- No base ref was retargeted and no PR was merged/closed/rebased during this audit. The eventual retarget/full-diff review is an **owner-authorized release action after field evidence**, not a source-development TODO.

## Branch merge/risk rules

1. Do NOT merge individual stacked heads directly into `main` in arbitrary order. They include their parents; overlapping PR #27 must be reconciled by blob/change review.
2. Source-level tests pinned to older Smite SHAs intentionally represent historical cases. Green jobs alone do **not** establish an integrated release baseline.
3. Do NOT close, rebase or squash existing Draft PRs, or create a new release, without an explicit separate review/approval.
4. Release qualification needs a coherent final source/image pair and actual negative/rollback test evidence. Keep `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD` until authorized.

**Final closeout boundary (2026-10-21):** the immutable updater source lock, durable updater/first-adoption transaction, strict Replay lifecycle/recovery admission, image-pair signing/admission contracts, FRP-independent Backhaul transaction/rollback, exact candidate Node digest host binding and explicit disposable-host Backhaul executor now exist in Draft #48/#16 with CI coverage. Historical rows above are retained for dependency/audit context and must not be read as today's TODO list.

No additional source feature is required before external qualification. The only remaining actions are authorization-bound: **(1)** publish and independently verify one real digest-only signed Panel+Node candidate, **(2)** exercise the packaged executor on approved snapshot-backed disposable IR/KH and verify 443/dynamic XHTTP/reboot/rollback/recovery, then **(3)** explicitly approve menu enablement, main merge and release. Until then keep `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`, `MAIN_MERGE=NO`, `RELEASE_PUBLISH=NO`.
