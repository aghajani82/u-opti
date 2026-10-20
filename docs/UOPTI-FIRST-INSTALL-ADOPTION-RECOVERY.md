# First install and legacy U-OPTI adoption — recoverable transaction (DRAFT)

**2026-10-20** · [Central closeout Issue #47](https://github.com/aghajani82/u-opti/issues/47) · [Single Draft PR #48](https://github.com/aghajani82/u-opti/pull/48)

## New installer behavior

The source-locked `install.sh` no longer copies `VERSION`, `u-opti`,
`common.sh` and each module directly to its live path in a loop. It
downloads and syntax/feature-verifies all files from **one resolved immutable
GitHub commit SHA**, then uses the *same* reviewed, journal-backed helper
`modules/u-opti-update-transaction.py` as the interactive U-OPTI updater.

Before apt-package checks or downloads the installer checks for a previously
interrupted transaction and attempts safe recovery using its own private,
persistent `rescue.py`. Corrupt, missing or contradictory recovery data
produces **HOLD** and prevents new package changes/downloads. When a
pre-existing U-OPTI executable is detected, a normal run likewise **HOLDS**
before apt/download; it must not be silently treated as a fresh install.

**Legacy first-adoption contract:** An operator who has independently
reviewed and approved migrating an already installed U-OPTI can explicitly
select `U_OPTI_ADOPT_EXISTING=YES` for an experimental installer run. This
does **NOT** mean any existing installation has been qualified for migration
and is **NOT** a recommendation to run it on real IR/KH. It guards against
unintentional overwriting. The same preflight is repeated after downloads,
so a late change cannot bypass the guard.

For a clean install or explicitly approved old installation:

1. Verify installation and module directories are not symlinks, create
   missing directories, reserve a **persistent private** `.uopti-backup-*`
   under the U-OPTI library tree.
2. For each to-be-installed file, copy its original bytes into the private
   backup, or create an explicit 0600 `.<filename>-was-missing` marker.
   Root owner, regular-file and single-link checks block unsafe targets.
3. Apply staged candidates via journaled helper. This verifies every
   staged, original and backup file, refuses a future launcher lacking
   **recovery-before-module-import** and the restored-launcher re-exec,
   records a private `fsync`ed old/new hash manifest and rescue helper,
   then atomically swaps each live file.
4. On failure, safely restore using the journal's rescue helper when
   available, otherwise **HOLD**. Retain recovery backup for review.
5. Only after a successful transaction, persist the user's update
   channel (`INSTALL_REF`) separately and start the installed program.

## CI (offline, no root, no actual VPS)

`tests/test-uopti-first-install-adoption.py` extracts and executes the
**actual Bash installer commit block**, calling the actual Python
transaction helper through a test-only wrapper that redirects absolute
host roots to disposable temporary files. Scenarios:

- Brand new install commits all files and preserves selected update branch.
- A legacy executable **without explicit adoption consent** is rejected
  before live bytes change. Static checks confirm the early preflight runs
  **before apt-package checks and downloads**.
- Explicit legacy adoption succeeds, preserving exact previous file bytes
  and missing-file markers.
- A true `SIGKILL` to the **installer Bash parent** after the helper
  replaces two live files: an independent interpreter verifies the durable
  pending journal and restores a fresh install to its previous empty file
  set, or an adopted old installation to its exact original bytes.
- Symlink in an existing module target blocks adoption before changes.
- Existing updater source locking, hard-exit recovery, foreign-file
  tampering and signed Smite integration regression jobs remain enabled.

## Important remaining limits — NOT production ready

- `U_OPTI_ADOPT_EXISTING=YES` is **experimental**; requires prior backup,
  explicit user authorization and disposable snapshot-backed validation
  before use on a live server.
- CI exercises real Bash commit logic and real Python transaction logic
  under temp roots; no actual reboot/power failure/disk controller behavior
  was tested. A crash between directory creation and journal publication
  may require operator cleanup; safe shutdown/commit semantics under
  filesystem corruption or malicious root cannot be assumed.
- Source `INSTALL_REF` remains a post-transaction metadata write, not
  one of the journaled payload files. Its failure can leave a completed
  installation with the previous selected update channel; treat as
  an outstanding consistency issue before release.
- GitHub API reachability is required to pin a source commit. This
  resolves source consistency but not independent artifact signature
  attestation, immutable paired Smite Panel/Node image digests, or
  existing U-OPTI legacy upgrade compatibility on real systems.
- This experimental installer does not migrate legacy Docker volumes,
  Nginx vhosts, Xray inbounds, Node keys or replay state; it is a
  U-OPTI **program-file** transaction only. Smite strict first enrollment,
  safe replay recovery and **FRP-independent Backhaul** remain blockers.
- Rollout still requires negative tests against existing installations,
  real Nginx port 443 coexistence, and operator approval for a disposable
  snapshot-backed IR/KH trial.

`INSTALL_ALLOWED=NO` · `ACTIVATION_GATE=HOLD` ·
`MAIN_MERGE=NO` · `IR_KH_WRITES=NONE`.
