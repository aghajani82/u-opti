# CLOSEOUT — GitHub Draft PR Dependency Matrix

**Reviewed:** 2026-10-19  
**Tracker:** [U-OPTI Issue #47](https://github.com/aghajani82/u-opti/issues/47)  
**Context:** [Cross-chat handoff](PROJECT-CLOSEOUT-HANDOFF.md)  
**Status:** Inventory of PR parent branches and declared scope only; individual line-by-line diff/conflict review is **NOT COMPLETE**. No PR has been approved for merge.

## Critical insight

These 36 open Draft PRs are **not** 36 independent mergeable patches.

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

## Workstream reconciliation, not merge instructions

| Workstream | Existing PR coverage | What is still required to mark DONE |
|---|---|---|
| Auth, identity and MFA | U-OPTI #27/#29–#36; Smite #1–#9, #15/#16 | Confirm one compatible Panel+Node pair, first enrollment, safe restore/key rotation, original admin controls; no duplicate host overlay |
| Image and release provenance | U-OPTI #32, #36–#38; Smite #10, #13–#15 | Select immutable matching source + **actual image digests**, integrate installer opt-in and rollback |
| Nginx 443 signed control | U-OPTI #30/#34/#35/#42–#46; Smite #7/#9/#12 | Test actual integrated release with existing public 443 vhost and correct Panel source, not just isolated CI loopback |
| Independent engines | U-OPTI clean RC/managed FRP+Backhaul tools, Smite #11 | Remove actual Backhaul → FRP/Sidecar dependency; verify dynamic Sanaei port/path, install/uninstall independent |
| Safe state mutation | U-OPTI #39–#41 **lab-only** | Production-safe permission boundary, journal/recovery, install/update atomicity; retain current production state |
| Beginner UX | U-OPTI menus, Smite #15 | One coherent IR→KH→Sanaei→port/path→tunnel→VERIFY workflow, without wizard bloat |

## Branch merge/risk rules

1. Do NOT merge individual stacked heads directly into `main` in arbitrary order. They include their parents; overlapping PR #27 must be reconciled by blob/change review.
2. Source-level tests pinned to older Smite SHAs intentionally represent historical cases. Green jobs alone do **not** establish an integrated release baseline.
3. Do NOT close, rebase or squash existing Draft PRs, or create a new release, without an explicit separate review/approval.
4. Release qualification needs a coherent final source/image pair and actual negative/rollback test evidence. Keep `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD` until authorized.

**Next concrete audit:** inspect the remaining five PR #27 file diffs against the latest U-OPTI chain and classify keep/superseded/conflict; then audit `install.sh` and the U-OPTI updater for coherent/atomic updates. Update [Issue #47](https://github.com/aghajani82/u-opti/issues/47) and [handoff](PROJECT-CLOSEOUT-HANDOFF.md) with the result.
