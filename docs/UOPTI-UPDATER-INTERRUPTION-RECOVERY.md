# U-OPTI updater: durable interrupted-update transaction (experimental)

**Date:** 2026-10-20 · [closeout Draft PR #48](https://github.com/aghajani82/u-opti/pull/48) · [tracker Issue #47](https://github.com/aghajani82/u-opti/issues/47)

## What actually changed

The interactive `u-opti` Update menu still downloads every candidate file from
one verified immutable Git commit SHA and runs its legacy completeness, feature
and syntax checks. The prior install is still backed up before the update,
but the backup directory is now **persistent under**
`/usr/local/lib/u-opti/.uopti-backup-*`, not volatile `/tmp`.

After backup verification, the new `modules/u-opti-update-transaction.py`
takes over the file-replacement phase:

1. Validate the private stage and backup, current installed bytes, each old/new
   module name, root owner and every source SHA256. Refuse unexpected changes.
   Also reject a future candidate `u-opti` launcher that lacks recovery-before-
   source and a re-exec of the restored binary, so an update cannot silently
   disable its own crash recovery.
2. Create `/usr/local/lib/u-opti/.uopti-update-pending` (private 0700)
   containing `rescue.py` (a copy of the exact currently executing helper)
   and `manifest.json` (old/new hashes, modes, backup path). Write, `fsync`
   both files and their directories **before** modifying live files.
3. Replace `u-opti`, `common.sh`, `VERSION`, then the modules one by one
   using a same-directory temporary file, `fsync`, `os.replace` and parent
   directory `fsync`. No installed target is truncated with ordinary `cp`.
4. Verify every installed target matches the candidate hash. Atomically rename
   the *directory* `.uopti-update-pending` → `.uopti-update-finished` before
   removing the journal. A crash while cleaning the finished record therefore
   cannot destroy the last copy of recovery metadata while still marked pending.
5. On U-OPTI start, *before sourcing any Bash module*, detect a pending journal.
   Execute its private pinned `rescue.py recover` to preflight all backup files
   and all current installed hashes. Recover the old set using atomic writes.
   Unknown/mismatched file, missing backup, corrupt journal or unsafe path:
   **HOLD and do not load any modules**; do not erase the backup.
   When restoration succeeds, **re-exec the restored original `u-opti`** with
   the same CLI arguments rather than mixing the new launcher in memory
   with modules restored from the older version.

Ordinary in-process update errors use the same journal recovery first, and
retain the backup if recovery cannot complete. The existing older Bash
restore remains a fallback only when no transaction was armed.

## Disposable CI evidence

`tests/test-uopti-update-transaction.py` imports the **real** new helper
under temporary directories and verifies:

- Full new multi-file commit with 0755/0644 modes and no pending record;
- Deliberate child-process `os._exit(91)` immediately after the second
  atomic installed-file replacement; a completely new Python process restores
  all previous bytes from persistent backup and removes newly introduced files;
- A tampered backup file or foreign modified installed file **fails closed**
  and retains the journal, without overwriting unknown state;
- Hard exit during *finished* directory cleanup leaves no pending rollback
  even though cleanup remains; installed new files retain their exact hashes;
- Damaged/unrecognized pending journal refuses recovery;
- U-OPTI startup recovery call is physically before the first module source,
  and the new recovery helper is distributed in the installer.

`tests/test-uopti-update-rollback-retention.py` was updated to test the
real journal-first plus legacy fallback branch. CI includes source SHA locking
and all prior Smite/FRP/Backhaul regressions.

## Important scope limitations (NOT READY to deploy)

- **Only the revised interactive U-OPTI updater** receives this transaction.
  The separate `install.sh` **fresh install** still does sequential live
  copying and has NOT been converted to a crash-safe deployment. Do not
  recommend rebuilding an existing server with it under this preview.
- A host already running the *old* updater has no power-loss journal; the
  upgrade that installs the new helper for the first time is **not retroactively
  protected** by the new code. Migrating existing servers requires a separate
  approved, snapshot-backed first-update plan.
- A crash **before the journal is fully written** may leave a private pending
  directory without valid metadata; this deliberately fails closed and needs
  human review. Files are not modified before the manifest is durable.
- A `finished` marker remaining after a crash is harmless for the tested
  file set but should be audited before the next update. A valid, current
  `u-opti` executable is required to reach startup recovery; external disk
  corruption or unavailable Python are not automatically recoverable.
- A *full-power-loss* hardware/virtualized-storage guarantee (disk cache,
  filesystem semantics, RAID, actual reboot) has **not** been verified.
  CI simulates abrupt process death only.
- The source SHA is pinned during download, but there is not yet a
  release-signed manifest, container digest pair, or approved Smite strict
  first-enrollment/replay-store migration.
- Same-UID/root adversarial writes, disk exhaustion, future arbitrary new
  file layouts, and multi-process installer/update races beyond the
  helper's flock are not production-certified.
- The module loader's legacy FRP bundle self-heal remains independent; it is
  not part of this updater journal. Nginx, UFW, Xray, 3x-UI and live tunnel
  state are **never** modified by the updater transaction test.

**Release gates remain**
`MAIN_MERGE=NO` · `INSTALL_ALLOWED=NO` · `ACTIVATION_GATE=HOLD` ·
`IR_KH_CHANGES=NONE`.

**Next:** extend a similarly guarded recoverability policy to fresh installs
and release admission, exercise real root filesystem/disk/reboot on separately
approved disposable snapshot-backed VPS, then pair exact Smite Panel+Node
image digests, strict replay lifecycle and independent FRP/Backhaul architecture.
