# U-OPTI × Smite — PROJECT CLOSEOUT & CHAT HANDOFF

> **Source of truth / مرجع ادامه کار:** [U-OPTI Issue #47 — CLOSEOUT TRACKER](https://github.com/aghajani82/u-opti/issues/47)  
> **Last reviewed:** 2026-10-20  
> **Purpose:** Every new ChatGPT conversation must read this file **and Issue #47 including its latest comments**, compare the current GitHub state, then resume outstanding work. This file is a continuity guide, **not a claim of production readiness**.  
> **Project state:** `INTEGRATION / NOT RELEASE READY`. `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD` for experimental Smite RC.

## CURRENT CLOSEOUT STATUS — concise handoff (2026-10-20)

**Current workstream:** consolidate and ship, no more PR staircases. Continue ONLY existing [U-OPTI Draft #48](https://github.com/aghajani82/u-opti/pull/48), [Smite Draft #16](https://github.com/aghajani82/Smite/pull/16) and [Issue #47](https://github.com/aghajani82/u-opti/issues/47). Read newest issue comments and **recheck current PR/CI HEAD**.

**LAST VERIFIED CODE CHANGE — Managed Backhaul can coexist with pre-installed FRP:** In U-OPTI test-code HEAD `285153b0400aba1e1b6a241a1b733b9369e213b8`, [Actions run 39423755202](https://github.com/aghajani82/u-opti/actions/runs/39423755202) **completed/success, 16/16 jobs PASS**. A new dual-engine transaction test revealed `FileExistsError` when Backhaul tried to recreate the shared engine parent already used by `frpc`/`frps`. The CI-only transaction now reuses a validated private 0700 parent, **does not touch FRP files**, and rolls Backhaul back to byte-exact prior FRP Compose/registry state. Backhaul candidate summary `FRP_INSTALLED` now accurately reflects the existing engine inventory; its verifier checks the claim. Partial, writable, missing or digest-tampered FRP mount/binary **HOLDs before Backhaul stage**; **absence of FRP remains fully valid**. See [BACKHAUL-FRP-DECOUPLING-CLOSEOUT.md](BACKHAUL-FRP-DECOUPLING-CLOSEOUT.md). Later documentation commits need their own CI verification.

**PREVIOUSLY VERIFIED:** Legacy Standard OFFLINE preview no longer demands FRP 7000 or KH Xray 56053 and does not fabricate XHTTP Nginx routes. Operator chooses actual KH Sanaei inbound port/path/hostname **after Core installation**. Pin-consistent experimental Smite Panel/Node offline images, one-time Replay DB provisioning, independent marker, real disposable Docker Node recreate/replay lost-DB fail-close, and operator-declared one-way stale SQLite snapshot quarantine have CI proof. Default stable Smite `v0.1.7` untouched. **Known security gaps:** undeclared dual-volume snapshot restore cannot be automatically detected; no approved production replay-restore/key-rotation or signed image release.

**ONLY THREE REMAINING RELEASE GATES:**
1. Independently executable **real-host Backhaul engine install/rollback** with signed Node restart proof, then actual XHTTP dynamic inbound route/tunnel after KH Sanaei. Existing production install button remains **disabled**; no actual VPS actions have happened.
2. Approve immutable paired Smite distribution/source-image mapping and secure operator recovery/rotation lifecycle, preserving working stable installs.
3. Obtain explicit operator approval for snapshot-backed disposable IR/KH VPS reboot/recovery and live VLESS/XHTTP data-path regression, then review merge/release. No new microstage PRs.

**GATES:** `INSTALL_ALLOWED=NO`; `ACTIVATION_GATE=HOLD`; `MAIN_MERGE=NO`; `RELEASE_PUBLISH=NO`; `IR_KH_UNCHANGED=YES`.

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
- **2026-10-20 interrupted-updater transaction implemented as Draft PR #48, still experimental:** Real `modules/u-opti-update-transaction.py` now snapshots verified old/new file hashes into a `fsync`-durable private journal and stores its exact own recovery code before replacing installed launcher/common/VERSION/modules via atomic same-directory renames. Update backups moved from volatile `/tmp` to private persistent `/usr/local/lib/u-opti/.uopti-backup-*`. On next launch, **before sourcing modules**, a pending update is verified and safely rolled back; if successful, U-OPTI re-execs its restored original executable. On unexpected changes/tamper the process HOLDs without discarding the backup. The transaction also rejects **future candidate U-OPTI launchers missing the recovery-before-module-import guard**, so later updates cannot silently remove their own rescue path. A fully verified commit atomically renames the pending journal directory to a finished marker before cleanup. `tests/test-uopti-update-transaction.py` simulates a real abrupt `os._exit(91)` in a child interpreter after two atomic replacements, independent-process recovery, tampering HOLD and a crash during post-commit cleanup; the previous backup-retention regression now tests journal-first/legacy-fallback. See [recovery contract and limitations](UOPTI-UPDATER-INTERRUPTION-RECOVERY.md). **This updater journal passed disposable process-crash CI; this is not a real power-loss certification.** First-adoption and clean install are addressed separately below. Interrupted journal creation still fails closed/manual review; real VPS reboot/storage crashes remain untested and no paired Smite image manifest has been released.

- **2026-10-20 first installation / first explicit legacy migration addressed in the SAME Draft PR #48:** `install.sh` now performs interrupted-journal recovery before apt or downloads and refuses an existing executable unless an *explicit* `U_OPTI_ADOPT_EXISTING=YES` review/admission is selected. An incomplete install or symlink path also HOLDS. The installer creates private persistent backups (including markers for paths previously absent), then invokes the *same real* SHA-pinned, journal-backed Python helper; it no longer directly `cp`s staged files to live targets. `tests/test-uopti-first-install-adoption.py` extracts the real Bash commit block, substitutes only sandbox roots via a wrapper to the **real Python helper**, and tests fresh installation, legacy no-consent HOLD, opt-in legacy adoption preserving old backups, a **SIGKILL of the installer shell** mid-transaction followed by recovery in a separate interpreter, and symlink rejection. [Detailed scope + limitations](UOPTI-FIRST-INSTALL-ADOPTION-RECOVERY.md). **Unresolved:** real-world legacy version compatibility/snapshots, hardware filesystem power-loss, pre-journal cleanup, independent signed source/image provenance still missing, package-manager side effects of first install, and integrated Smite engine/replay setup. Verify latest HEAD CI before declaring test completion.

- **2026-10-20 atomic update-channel fix in the SAME Draft PR #48:** Both `install.sh` and interactive `u-opti` now include `INSTALL_REF` in the persistent old-state backup, including an absent-file marker for legacy installs. Both pass `--source-ref "$BRANCH"` to `modules/u-opti-update-transaction.py`, which validates the channel and journals its derived content and SHA-256 **as the last installed target** alongside `VERSION`, executable and modules. The old post-commit `INSTALL_REF.new` writes were removed. Recovery from a forced interruption after changing the channel returns exactly to the old Branch or its absence. **Old pending journals without the metadata remain supported.** The Backhaul packaging test now enforces 4 standard backup files and the source-ref flag, instead of its obsolete 3-file assumption. CI `bash-validation` and related regressions passed; see [atomic channel and Smite source/image admission audit](UOPTI-ATOMIC-CHANNEL-AND-SMITE-PAIR-ADMISSION.md). Still `NOT RELEASE READY`.
- **Smite paired-source investigation:** stable `modules/smite-install.sh` defaults to upstream `zZedix/Smite v0.1.7` with its historical registry image digests. The experimental Clean-RC path checks supplied offline archives against externally trusted source/manifest hashes and local Docker IDs, but these are **not published immutable production image digests**. Reviewed Smite Draft #16 SHA `3751aeda6f946e5e5624e5e89ab1ce554fec4460` has strict replay/bootstrap changes but is not yet an approved paired source/image release. Do not equate green CI with certified deployable images.

**Next real blocker:** select and verify ONE immutable Smite Panel+Node source/image provenance pair compatible with this U-OPTI HEAD, then finish explicit first pairing/SQLite replay-store provisioning, signed recovery and independent Backhaul. Real VPS migration, storage power cut, external registry robustness and full beginner UX still need separate admission.

## 5b. 2026-10-20 — paired Smite source-HEAD image build (completed in CI, release HOLD)

- **Critical provenance bug found in earlier Smite Stage15 build:** the old successful artifact from run `39313614098` used GitHub PR synthetic merge SHA `0fb747b0911432503643ad83efc1e8247b15aa6e`, not the exact Smite PR branch SHA. Its build can still be a valid test, but cannot be called a build *from the exact PR head*.
- **Fixed without a new micro-stage PR:** In existing [Smite Draft #16](https://github.com/aghajani82/Smite/pull/16), Stage15 workflow now checks out `github.event.pull_request.head.sha` (not `github.sha` merge) and verifies `git rev-parse HEAD` matches the expected source before building *both* Panel and Node; image manifest and artifact use that same commit. Added regression in `tests/test_stage15_offline_bundle.py`.
- **Verified exact source:** Smite PR #16 HEAD `995977d0ac9be69b6c9e3d3c257c5cd8c1abe220`, [Stage15 workflow run 39378799692](https://github.com/aghajani82/Smite/actions/runs/39378799692) **completed/success**; all five other reported PR workflows at that SHA were also completed/success. The ephemeral artifact ID `12244433473` (expires **2026-10-23T06:11:22Z**) contains *both* offline image archives with a manifest. SHA256 of `stage15-images.json` recorded from job logs: `d486dd2075b1187d735b50c18538a1002f066984962080474f3f4be6ae1e19ab`. SHA256 of the GitHub Actions artifact ZIP: `767f600e8d39b3882ff8d091f1d731d9b9f0f402dd613d464ea349b0743e1f58`. **These hashes refer to different objects.**
- **U-OPTI integration:** In ongoing U-OPTI Draft #48, strict signed FastAPI/replay + real Nginx/443 integration CI jobs were repinned to Smite exact build source SHA `995977...`. Historical compatibility jobs stay on intentionally older source commits. See [complete exact-HEAD evidence and unresolved production trust gates](SMITE-PR-HEAD-OFFLINE-IMAGE-EVIDENCE.md).
- **Still NOT a distributable production pair:** no GHCR push, no signed registry digest, no migration/rollback policy for stable v0.1.7, no real IR/KH test, and replay DB first enrollment/recovery is NOT live. `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`. **Do not tell the operator to install this temporary CI artifact as a release.**

**NEXT MOST IMPORTANT WORK:** integrate verified strict Smite paired identity/one-time durable replay DB bootstrap with explicit opt-in safe pairing; ensure permanent source/digest release contract without automatically changing stable v0.1.7. Then finish independent Backhaul and simple IR/KH flow. Approval-gated disposable snapshot VPS qualification comes later.

## 5c. 2026-10-20 — strict Replay DB one-time paired Node enrollment (lab complete)

- **Existing [Smite Draft #16](https://github.com/aghajani82/Smite/pull/16)** now includes operator-only `node/app/replay_enrollment.py`, no HTTP/startup hook or automatic strict-mode switch. Paired Node identity must already exist with 0600 permissions in an owned private 0700 persistent directory. The replay DB has a **separate** private 0700 persistent directory. The tool requires explicit `--confirm-first-provision`, durably writes a 0600 independent `replay-enrollment.json` marker **alongside the identity before SQLite**, then explicitly provisions and verifies `DurableNonceStore`. Existing marker/DB, unsafe paths and partial failures HOLD without auto-deletion or retry.
- **Why the marker matters:** if only the replay volume disappears while the identity volume persists, another first-boot call refuses to create a blank database. Signed Node request handling continues to return 503 for missing replay storage. **It does not solve loss of both volumes or rollback of a same-Node older replay DB snapshot**; these still require independent provenance and signed-traffic quarantine or authorized key rotation.
- **Smite reviewed code/image pair:** `9201722336b05e833408a0a352cfee99465da2cb` (prior to documentation-only commits). Signed Agent [CI 39395144111](https://github.com/aghajani82/Smite/actions/runs/39395144111) PASS; exact-head two-image offline build [CI 39395144038](https://github.com/aghajani82/Smite/actions/runs/39395144038) PASS, artifact `12251038624`, manifest SHA256 `f40c6553a1573c6623f03634da187fe0a403a309590871045a8c0bcada6b590f`, ZIP SHA256 `2cef44711afed60666a6ec347a8e0b156d11a40609db913d6183ea879771e557`. **Temporary expiry 2026-10-23T08:42:39Z**. No release/push/live deployment.
- **Same U-OPTI [Draft PR #48](https://github.com/aghajani82/u-opti/pull/48):** strict signed FastAPI and real Nginx 443 CI jobs now pin exact Smite `9201722...` source. FastAPI lab uses actual `provision_once` and proves missing-DB first-time bootstrap cannot be repeated while the marker survives. [CI 39395426015](https://github.com/aghajani82/u-opti/actions/runs/39395426015) **16/16 PASS**. Other historical integration baselines intentionally remain unchanged.
- **Detailed permanent admission notes:** [SMITE-FIRST-REPLAY-ENROLLMENT-ADMISSION.md](SMITE-FIRST-REPLAY-ENROLLMENT-ADMISSION.md), including the fact that U-OPTI's preview identity location and Smite's actual private Node config paths are **not** yet safely reconciled or bind-mounted.

**NEXT:** integrate reviewed KH identity + independent durable replay bind mounts into an explicit, fail-closed pairing/installer lifecycle **without** auto-enabling strict mode. Then design authenticated backup/restore and anti-rollback quarantine/key rotation before production strict traffic. Parallel release blockers remain FRP-independent Backhaul, simple novice UI and actual snapshot-backed host rehearsal.

## 5d. 2026-10-20 — KH identity and replay bind-mount admission (read-only, no activation)

- **Real existing Stage9 candidate reused:** `modules/smite-node-auth-candidate.py` already stages an inert Compose override binding U-OPTI's paired identity host directory `/etc/u-opti/smite/identities` to `/run/smite-node-identity:ro` and private Replay host directory `/var/lib/u-opti/smite-node-security/replay` to `/var/lib/smite-node/auth:rw`, with exact runtime env paths. No need to create a second installer or silently change existing Node Docker mounts.
- **New U-OPTI Draft #48 helper:** `modules/smite-node-replay-mount-admission.py` explicitly validates KH/Standard role, the known base Compose localhost:8888, paired 0600 identity, independent 0600 enrollment marker matching Node ID + **exact host replay DB path**, SQLite schema v1/quick-check and exact paired identity, private 0700 mount directories, and **byte-identical** inert Compose with read-only identity/read-write replay mounts plus matching Node environment paths. Missing/tampered/symlinked/incorrect state returns HOLD; does not run Docker, create folders or SQLite, change secrets or activate strict mode. Output always includes `DOCKER_COMPOSE_APPLY=NO` and `ACTIVATION_GATE=HOLD`.
- **Packaged via both `install.sh` and U-OPTI Update.** `tests/test-smite-node-replay-mount-admission.py` exercises real checker in temporary folders with legitimate SQLite and known candidate, then missing DB, marker tamper/loss, wrong DB Node, SQLite schema drift, role/permission faults, unsafe RO/RW mount drift and extra Compose content. [GitHub Actions run 39397328938](https://github.com/aghajani82/u-opti/actions/runs/39397328938) **16/16 PASS** for the first code commit; verify latest documentation-only HEAD CI separately.
- **Complete contract:** [SMITE-KH-REPLAY-BIND-MOUNT-ADMISSION.md](SMITE-KH-REPLAY-BIND-MOUNT-ADMISSION.md).
- **Crucial limitation:** static preflight can only verify *planned* mounts, not Docker's effective nested named-volume/host bind precedence, that the directories are really on independent persistent storage, or successful container recreation/reboot. **No actual KH activation.** Stale same-ID Replay SQLite snapshots still require explicit operator quarantine/key rotation: a matching marker and SQLite schema are not anti-rollback proof.

**NEXT:** isolated disposable Docker Node container mount/recreate proof with the paired reviewed Smite build (or safe equivalent), including mount precedence and loss of Replay volume; then authorized replay recovery/anti-rollback quarantine/key rotation and independently runnable Backhaul. Keep the one consolidation PR, preserve simple workflow. `INSTALL_ALLOWED=NO` · `ACTIVATION_GATE=HOLD`.

## 5e. 2026-10-20 — actual disposable Node Docker recreate, Replay DB persistence & loss denial (CI PASS)

- **Real Docker lifecycle, not just static Compose text:** Updated **existing** `tests/test-smite-stage24-compose-runtime.sh` and its `node-compose-hmac-rollback-isolated` GitHub Actions job inside the SAME U-OPTI Draft #48. CI now checks out the exact reviewed **Smite security SHA `9201722336b05e833408a0a352cfee99465da2cb`**, not the older `a15c462...`, builds a real local Node image, and runs the actual `app.replay_enrollment` once using synthetic paired identity and separate 0700 host paths. The marker records the exact **host DB path**, and the existing read-only U-OPTI KH checker verifies it before starting Node.
- **Effective runtime Docker mounts validated via `docker inspect`:** `node-data:/var/lib/smite-node` remains named-volume; nested `/var/lib/smite-node/auth` is a separate **RW host bind**; `/run/smite-node-identity` is a **RO host bind**. No host network or public port in CI. Real signed HMAC request works, nonce replay fails. Switching signed→paused→signed with forced container recreation retains the private identity/marker and persisted nonce, still rejects already-used nonce and permits a new nonce.
- **Negative real-node data-loss test:** On the disposable runner, stop the container and move the synthetic Replay SQLite away while keeping identity/marker; force-recreate signed Node. Signed request returns **503**, SQLite remains absent (no automatic recreation), and another explicit first enrollment is refused because independent marker survives.
- **Verified CI:** actual code commit `d65313b2b6c77fd37a2052ae792eb4082bd3f7d0`, [GitHub Actions run 39404517558](https://github.com/aghajani82/u-opti/actions/runs/39404517558) **completed/success, 16/16 PASS**. Documentation-only commits follow; verify latest HEAD CI separately.
- **Permanent details and all caveats:** [SMITE-NODE-DOCKER-RECREATE-REPLAY-CI-EVIDENCE.md](SMITE-NODE-DOCKER-RECREATE-REPLAY-CI-EVIDENCE.md).
- **What is STILL NOT tested/certified:** actual VPS reboot/storage power cut/provider snapshot restore, same-identity stale replay DB rollback, production Panel signed handshake and immutable signed image release, independent Backhaul install without FRP, or activation on IR/KH. Never infer that a CI recreated container equals a real disk power-loss test.

**NEXT:** design and negative-test **safe Replay DB restore/quarantine**, using Smite's actual HMAC timestamp window with a trustworthy clock and an explicit operator gate (no automatic DB recreation or key rotation); then Backhaul independence and simple IR→KH sequence. Keep a single U-OPTI Draft #48 and Smite Draft #16, no micro-PRs. `INSTALL_ALLOWED=NO` · `ACTIVATION_GATE=HOLD`.

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

**Current next action:** managed Backhaul's existing-FRP `FileExistsError` and false `FRP_INSTALLED=NO` stage claim are fixed with real CI test and byte-exact rollback. Finish the separately approved **real-host Backhaul executor / trusted signed runtime restart-and-rollback admission**, without requiring FRP or asking for tunnel port during engine install. After KH Sanaei create/select the actual dynamic XHTTP port/path in the separate tunnel menu. Then final trusted paired image/replay-restore release admission and snapshot-backed IR/KH VPS rehearsal. `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`; no main merge or live server changes.

## 7. Operational conventions

- Every user-facing shell command block must be prefixed with its target role **IR**, **KH** or **BOTH**. Don't give a production command while rollout is HOLD.
- The panel should be simple, attractive and beginner-friendly. Background checks should be secure, but no new mandatory wizard maze.
- Any live install/reboot, change to Nginx/443, merge into `main`, branch rewrite, PR closure or release must be separately approved. CI runs in disposable isolated GitHub runners are allowed for Draft experimental work.
- If network/CI unavailable, note unverified status instead of claiming tests passed.

**Keep this file and Issue #47 synchronized as the project is consolidated.**
