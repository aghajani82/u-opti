# U-OPTI × Smite — PROJECT CLOSEOUT & CHAT HANDOFF

> **Source of truth / مرجع ادامه کار:** [U-OPTI Issue #47 — CLOSEOUT TRACKER](https://github.com/aghajani82/u-opti/issues/47)  
> **Last reviewed:** 2026-10-19  
> **Purpose:** Every new ChatGPT conversation must read this file **and Issue #47 including its latest comments**, compare the current GitHub state, then resume outstanding work. This file is a continuity guide, **not a claim of production readiness**.  
> **Project state:** `INTEGRATION / NOT RELEASE READY`. `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD` for experimental Smite RC.

## 0. راهنمای سریع برای چت جدید / Start here

Copy this into a new chat:

> «ادامه جمع‌بندی پروژه U-OPTI و Smite. لطفاً ابتدا فایل
> `docs/PROJECT-CLOSEOUT-HANDOFF.md` را در Branch
> `feature/uopti-smite-closeout-integration-20261019`
> از مخزن `aghajani82/u-opti`، سپس GitHub Issue #47 و آخرین کامنت‌هایش
> را بخوان. وضعیت PRها و CI را مجدداً بررسی کن و از آخرین کار تأییدشده
> ادامه بده. هدف، تکمیل امنیت و کدهای نیمه‌تمام و جمع‌بندی نسخهٔ نهایی
> است؛ نه افزودن مرحله و قابلیت جدید. بدون تأیید من به `main` Merge
> نکن، Release نساز و روی IR/KH تغییری نده.»

**For the assistant:**
1. Read [this tracked file](https://github.com/aghajani82/u-opti/blob/feature/uopti-smite-closeout-integration-20261019/docs/PROJECT-CLOSEOUT-HANDOFF.md), then [Issue #47](https://github.com/aghajani82/u-opti/issues/47) and **newest comments**. Never assume a recorded PR SHA/CI result is still current; verify.
2. Check both GitHub repositories: `aghajani82/u-opti`, `aghajani82/Smite`. Respect existing Draft PR stack, do not casually duplicate/cherry-pick prior work.
3. Take **one meaningful unresolved blocker** from the central closeout queue; investigate it, implement the minimum justified change on an *explicit experimental branch*, run negative tests/regressions and verify latest-head CI. Keep beginner usability.
4. Before the chat gets long, **update this exact file and Issue #47** with completed/blocked/next tasks, exact GitHub links/SHAs/CI status. This file is the carry-forward note; progress in chat alone is not durable.

## 1. تصمیم صاحب پروژه / Product requirements — frozen

- **Two logical roles:** IR = Panel/Controller, KH = Foreign Node (the test servers may physically both be overseas). **Single exposed TLS/HTTPS 443 gateway** and normal website behavior; hidden control routes must preserve signed path/query/body.
- **No forced provider dependency, Private Network, EasyTier or FRP** for basic Smite Core. Engines and tunnels must be independent. First integrated release focuses on **FRP** and **Backhaul**; defer advanced Gost/Rathole/Chisel work unless needed for already-committed compatibility.
- **Simple beginner flow, do not ask for tunnel port/path during initial Core installation:** IR Core/gateway → KH Core/gateway → KH Sanaei/3x-UI inbound → define dynamic inbound port and path in a separate dedicated menu → create/apply the chosen tunnel → verify actual authenticated client traffic. No hardcoded `56053`; no automatic Xray inbound creation without separate approval.
- Security, backup, authentication, HMAC, MFA and rollback should operate mostly **behind the scenes**. UI must remain clean/simple. Preserve working U-OPTI SSH/Fail2ban/UFW/Nginx/certificates/Docker/3x-UI/Backup features.
- Fresh install, upgrade/repair and production migration are **different** operations; do not destroy or silently rewrite an existing Smite deployment.
- **Freeze feature creep:** finish existing defects, deduplicate and reconcile modules/menus, and publish a reviewable integrated pair rather than endlessly creating numbered stages.

## 2. GitHub baseline (verified on 2026-10-19, re-verify)

**Current consolidation home:** [U-OPTI Draft PR #48](https://github.com/aghajani82/u-opti/pull/48) on the `feature/uopti-smite-closeout-integration-20261019` branch. This is ONE continuing closeout branch, **not another micro-stage**. The earlier 36-PR inventory predates this PR, so current open-Draft count can be 37 until GitHub changes.

**Full dependency inventory:** [PROJECT-CLOSEOUT-PR-MATRIX.md](PROJECT-CLOSEOUT-PR-MATRIX.md) — explicitly distinguishes U-OPTI's separate #27 root from its #28→#46 stack, and Smite #1→#16.


### U-OPTI
- Repository: https://github.com/aghajani82/u-opti
- `main` README reports **v0.16.7**. The `main` `modules/smite-install.sh` uses **Smite upstream v0.1.7** with pinned original zzEdix container digests by default. New draft clean-RC is **not** automatically selected for normal users.
- **20 baseline Draft PRs #27–#46, plus the current consolidation Draft #48.** Standalone auth-overlay [#27](https://github.com/aghajani82/u-opti/pull/27) starts from `main`. Core contiguous stack: [#28](https://github.com/aghajani82/u-opti/pull/28) → #29 … [#38](https://github.com/aghajani82/u-opti/pull/38) (clean RC) → [#39](https://github.com/aghajani82/u-opti/pull/39) (lab transaction) → [#40](https://github.com/aghajani82/u-opti/pull/40) (plan binding) → [#41](https://github.com/aghajani82/u-opti/pull/41) (fd guard) → [#42](https://github.com/aghajani82/u-opti/pull/42) (mock signed probe) → [#43](https://github.com/aghajani82/u-opti/pull/43) (real ASGI) → [#44](https://github.com/aghajani82/u-opti/pull/44) (replay DB fail-closed integration) → [#45](https://github.com/aghajani82/u-opti/pull/45) (actual loopback Nginx TLS/443) → [#46](https://github.com/aghajani82/u-opti/pull/46) (source ACL, identity drift, recovery HOLD).
- Base code of #46 before this handoff-document addition: `a20070f4fdc7c7a38edbb2e929e4e99f79e558fb`. That exact commit passed [GitHub Actions 16/16](https://github.com/aghajani82/u-opti/actions/runs/39316139366). **Once this document is committed the HEAD changes; these green results do not certify the new HEAD.**
- GitHub comparison of #46 against main: **351 commits ahead, 108 files changed** (as observed on the documented baseline). Stacked PRs are NOT 20 independent changesets.
- Verified **overlap**: the SHA of `modules/smite-panel-auth-overlay.py` in #27 and #46 is identical: `d9b9a0533c8afff7b07821aee588a41289e3cc2c`. Don't merge the same auth overlay twice; compare other #27 changes before making an exclusion decision.

### Smite
- Repository: https://github.com/aghajani82/Smite
- **16 open Draft PRs #1–#16**, stacked in a single chain. [#15](https://github.com/aghajani82/Smite/pull/15): simplified IR/KH operator UI and opt-in MFA; [#16](https://github.com/aghajani82/Smite/pull/16): explicit fail-closed SQLite nonce-store initialization.
- Reviewed #16 source HEAD: `3751aeda6f946e5e5624e5e89ab1ce554fec4460`; 5/5 relevant workflows [were green](https://github.com/aghajani82/Smite/actions/runs/39313614098) on that commit. GitHub comparison to main: **191 commits ahead, 114 files changed**.
- Node settings in #16 still default to **`legacy`** auth/inventory for existing deployments. `strict`, signed pairing, persistent nonce DB provisioning and managed inventory are opt-in and must not be described as production-enabled.
- `DurableNonceStore.initialize_new` from #16 requires explicit first-time provisioning. Missing replay DB cannot be lazily recreated by authenticated request; source code still lacks complete approved production bootstrap/migration/key rotation/backup recovery.
- Tests pin different reviewed Smite SHAs according to their intended integration stage; **not all green jobs target the same artifact pair**. Release qualification requires a final, single consistent pair and image digest chain.

## 3. Evidence taxonomy — do not overstate

**Confirmed in isolated CI:** HMAC bad signature/replay/wrong identity; actual FastAPI request guards; persistent SQLite nonce behavior across fresh Python interpreter; synthetic host transactions/rollback; actual loopback Nginx TLS/443 path/query/body preservation and source ACL; selected disposable Docker image/rollback tests.

**NOT confirmed as a combined production release:** real cross-VPS IR↔KH access and firewall/provider routing, production 443/vhost collisions, a coordinated safe upgrade from existing installations, full host transactional rollback after power loss, trusted replay DB recovery from stale snapshots, single selected image digest/commit pair across installer/UI/Node, standalone Backhaul without FRP, and complete beginner workflow using that integrated release.

Successful CI, HTTP 200, mock transports, synthetic binaries or a temporary test certificate **do not equal** field activation approval.

## 4. Consolidation queue / کاری که واقعاً باید تمام شود

**Priority 0 — inventory and choose integrated pair (IN PROGRESS).**
- [ ] Audit dependencies and overlapping diffs for all 36 Draft PRs; resolve #27 overlap with #28–#46 chain, Smite #1–#16. Map what is mandatory vs superseded and what still needs a new implementation; no blind merge.
- [ ] Establish ONE reviewed **U-OPTI source commit + Smite source commit + immutable Panel/Node image digests** for a release-candidate trial, including a reverse rollback path. Draft SHA pinning inside unrelated tests doesn't satisfy this.
- [ ] Freeze user-facing menu shape, role-based setup ordering and advanced features deferred from first release.

**Priority 1 — security and state lifecycle (BLOCKER).**
- [ ] Integrate private Node paired-identity and **explicit pre-provisioned** replay SQLite persistent mounts into clean install; reject missing/mismatched/stale state, do not auto-create on incoming HTTP request.
- [ ] Design and test actual fail-closed backup/recovery and coordinated per-Node key rotation; do not blindly restore a stale same-Node replay DB. Establish quarantine/time-window policy, approval and safe rollback.
- [ ] Review admin JWT/MFA, Panel→Node signed TLS, Nginx source ACL, secret/log exposure, file ownership, engine SHA, immutable images and host transaction state. Verify against the **same selected images**, not mock response alone.

**Priority 2 — architecture + independent engines (BLOCKER).**
- [ ] Smite Core installs on both roles without requiring any engine. FRP and Backhaul each install/configure/uninstall independently **after** Core; no Backhaul dependence on FRP gateway/baseline.
- [ ] Dynamic user-selected KH Sanaei inbound port and XHTTP path, entered **after** KH/Sanaei setup. No fixed `56053`; no port/path prompts during Core install. No engine config implicitly starts or overwrites a different engine.
- [ ] Simplify menus, eliminate duplicate/obsolete entries carefully, keep UI approachable and advanced configuration separate. Keep role-specific errors/readiness clear.

**Priority 3 — installer, update and rollback (BLOCKER).**
- [ ] Compare `main` `install.sh` and `modules/smite-install.sh` with RC. `main` installer downloads files from mutable branch/ref separately and copies them sequentially; a crash/mid-update/mixed-ref may leave inconsistent state. Audit updater too. Design immutable reviewed source manifest, preflight, staging and rollback/recovery **without breaking stable installs**.
- [ ] Explicit clean install vs upgrade vs repair; protect existing users, current Nginx shared :443, Xray/3x-UI configuration, Docker volumes and secrets from accidental overwrite.
- [ ] Review/merge code consolidation only where shown to reduce duplication and risk. Avoid over-engineering.

**Priority 4 — final testing and release (LATER, BLOCKED BY 0–3).**
- [ ] Run a single coherent final CI + negative-tests matrix at the final paired source/image digests.
- [ ] **With separate user consent**, take snapshots on disposable IR/KH test VPSs; read-only preflight, controlled trial, actual VLESS/XHTTP authenticated traffic, reboot/rollback/reinstall, verify no unnecessary public ports.
- [ ] Confirm security, operational backup and simple UX; present full release notes and ask separately before merge/main, publishing images/releases or deploying.

### Explicit hold
`MAIN_MERGE=NO` · `RELEASE_PUBLISH=NO` · `REAL_IR_KH_WRITE=NO` · `LIVE_DEPLOY=NO` unless the user separately authorizes that action. Never share pairing secrets/tokens/private keys in docs or CI output.

## 5. Newly verified blockers / first actionable fixes

1. `aghajani82/u-opti` **main** uses original pinned Smite v0.1.7 by default, while draft strict security/fail-closed replay code lives in Smite #16; **cannot call latest hardened system installed**.
2. U-OPTI README documents that current standalone Backhaul is **not available** and Sidecar still requires a prior Smite Standard/FRP gateway baseline; violates the selected engine independence requirement.
3. Existing draft host executor in `tests/lab/smite_host_executor.py` is explicitly a lab model, not a production-ready transactional installer.
4. Multi-file install/update can be inconsistent under interruption; inspect both install and updater implementation and add non-destructive admission before real rollout.
5. Smite strict Node/Panel mode defaults legacy for compatibility; avoid stealth-changing defaults without a staged migration.

## 5a. Work actually completed toward closeout (2026-10-19)

- **PR dependency overview recorded:** [dependency matrix](PROJECT-CLOSEOUT-PR-MATRIX.md). The complete U-OPTI #27 six-file scope was checked against the newest chain: the `smite-panel-auth-overlay.py` implementation AND its `tests/test-smite-panel-auth-overlay.py` test have identical Git blob SHAs; `install.sh` and the `u-opti` updater contain its required module distribution references; `modules/smite.sh` has an equivalent guarded host-overlay hook; the latest CI includes its authentication-overlay regression. **Conclusion:** #27 has already been functionally incorporated; do not merge its original branch separately without review. No PR has been closed.
- **Actual updater bug fixed on experimental closeout branch PR #48:** The U-OPTI Update menu backed up the previous install and attempted rollback if copying new files failed, **but the failed-rollback branch deleted the recovery backup anyway**. The new branch retains its private backup if restore fails, accurately displays the recovery location and removes it only after the restore helper succeeds. `tests/test-uopti-update-rollback-retention.py` invokes the real extracted failure branch in temporary directories, checking both outcomes. **This is a focused defect fix, NOT full atomic/power-loss recovery.** Verify the latest PR #48 GitHub Actions CI before marking tested.
- **Updater source audit nuance:** The Update menu ALREADY has downloaded-file syntax/feature checks, backups and catchable-error restoration, but lacks full power-loss crash recovery and consistent source-SHA pinning on mutable branch URLs. The separate `install.sh` also writes several live files sequentially. Do **not** incorrectly claim the updater has no backup functionality.

- **2026-10-20 source consistency correction on the *same* PR #48 branch:** `install.sh` and the interactive `u-opti` update command now resolve the selected ref once using GitHub's commit metadata API; both fail closed on failed/invalid SHA, then download every file from `raw.githubusercontent.com/.../<resolved-40-hex-SHA>/...`. The stored `INSTALL_REF` retains the selected update branch/ref, preserving future deliberate updates; only each operation's downloads are immutable. `tests/test-uopti-source-pin.py` compares identical resolver source in both entrypoints and uses an isolated mocked curl for success/error/malformed JSON/ref injection, plus static guards against mutable updater URLs. **This has not yet been tested under actual production network failure, GitHub API rate-limit, crash or power loss; current operations require GitHub API availability, and that availability is a release usability concern to review.**
- **2026-10-20 interrupted-updater transaction implemented as Draft PR #48, still experimental:** Real `modules/u-opti-update-transaction.py` now snapshots verified old/new file hashes into a `fsync`-durable private journal and stores its exact own recovery code before replacing installed launcher/common/VERSION/modules via atomic same-directory renames. Update backups moved from volatile `/tmp` to private persistent `/usr/local/lib/u-opti/.uopti-backup-*`. On next launch, **before sourcing modules**, a pending update is verified and safely rolled back; if successful, U-OPTI re-execs its restored original executable. On unexpected changes/tamper the process HOLDs without discarding the backup. A fully verified commit atomically renames the pending journal directory to a finished marker before cleanup. `tests/test-uopti-update-transaction.py` simulates a real abrupt `os._exit(91)` in a child interpreter after two atomic replacements, independent-process recovery, tampering HOLD and a crash during post-commit cleanup; the previous backup-retention regression now tests journal-first/legacy-fallback. See [recovery contract and limitations](UOPTI-UPDATER-INTERRUPTION-RECOVERY.md). **Still not full production-certified atomic deployment:** new fresh `install.sh` remains sequential, first adoption from older updater is not protected, interrupted journal creation fails closed/manual review, real VPS reboot/storage crashes are untested, and no paired image manifest is released.

**Next real blocker:** verify the latest PR #48 HEAD CI for the updater transaction, then harden the *fresh installer* and first-adoption upgrade path, audit real filesystem/power-loss behavior on disposable approved VPS, and establish immutable paired U-OPTI/Smite images without production changes. Coordinate with Smite #16 first-enrollment state and the independently installable Backhaul design after that.

## 6. How to report progress after each working session

Append or refresh in **Issue #47 comments**, and update this document before leaving a long conversation:

```text
DATE:
GOAL:
BRANCH / DRAFT PR:
ACTUAL FILES MODIFIED:
TESTS (what ran, where, exact commit and CI URL):
COMPLETED (with evidence):
KNOWN UNSOLVED / HOLD:
NEXT MOST IMPORTANT ACTION:
MAIN / IR / KH / RELEASE: UNCHANGED (or exact operator-authorized details)
```

**Current next action:** verify latest CI for the updater transaction and reboot simulation, then finish guarded first-install/first-upgrade recovery, paired Smite image provenance and independent Backhaul. Keep `INSTALL_ALLOWED=NO` and `ACTIVATION_GATE=HOLD`. Then integrate a coherent paired source/image baseline, Smite strict first provisioning and independent Backhaul. Do not treat documentation alone as a completed fix. Do not treat documentation as a completed fix. If asked for “next step”, work on the highest unresolved blocker, not another arbitrary stage number.

## 7. Operational conventions

- Every user-facing shell command block must be prefixed with its target role **IR**, **KH** or **BOTH**. Don't give a production command while rollout is HOLD.
- The panel should be simple, attractive and beginner-friendly. Background checks should be secure, but no new mandatory wizard maze.
- Any live install/reboot, change to Nginx/443, merge into `main`, branch rewrite, PR closure or release must be separately approved. CI runs in disposable isolated GitHub runners are allowed for Draft experimental work.
- If network/CI unavailable, note unverified status instead of claiming tests passed.

**Keep this file and Issue #47 synchronized as the project is consolidated.**
