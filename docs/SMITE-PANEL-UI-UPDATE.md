# Static Panel UI update and rollback

The original RC7 design is retained at its normal size. Only the Login image/glow and subtitle are removed; the large Smite title stays. No compact CSS remains.

## Operator flow

Update U-OPTI first. Open Docker Management → Smite Management → Install Components.

- **1:** Fresh Panel + Iran Node installation selects the existing signed RC7 image pair and automatically applies the reviewed static UI after runtime installation commits.
- **8:** Back up and update the appearance of an existing running RC7 Panel. Confirm the prompt. Refresh the browser with Ctrl+F5 afterward.
- **9:** Restore the previous UI on the same container. This also recovers an interrupted UI operation. Confirm the prompt.

The helper admits only the exact reviewed RC7 Panel image, uses the local Docker socket, rejects static bind/volume overlays and never restarts/recreates a container. Node, backend Python, environment, SQLite, pairing and tunnels are untouched. Other Panel image versions fail closed.

## Provenance

- Smite main source: `115f032761564a069d0aa2ca891e55d53a1c6ea0` (PR #47).
- Build: https://github.com/aghajani82/Smite/actions/runs/41545272945
- CI artifact: `smite-rc7-ui-only-static-preview`, id `13188691573`.
- `modules/smite-panel-ui.json` contains the exact CI static bytes in base64; original per-file manifest hashes were checked before packaging.
- Bundle SHA-256: `f61f77e3ac150b5611b8f5f05534cb7727557e1eaef8340eb3f966f2d02c7285`, pinned in the helper.
- Backend image selection/signature validation remains unchanged. This UI package is SHA-pinned distribution data, not a newly signed container image.

## Recovery and limits

A root-owned 0700 journal directory at `/var/lib/u-opti/smite-panel-ui` holds the prior static files before publication. Assets are staged first and `index.html` is atomically replaced last; existing hashed assets are retained for already-open tabs. Reapplying the same package is idempotent. Previous journals are archived before a later update.

A changed container ID or unrecorded index change blocks rollback rather than restoring into an unknown runtime. Backups are retained on failure. Do not delete the journal to bypass a HOLD. A failed UI step after fresh runtime installation is retried with option 8, not with another installation.

Static files persist across container restart, but a **recreate/image replacement resets the writable layer**. Re-run option 8 on a recreated compatible RC7 Panel; a new backup will be made. This feature does not alter Compose mounts to make UI files persist across image changes.

Checks use fixtures and disposable Docker containers, not live VPS state. No updater runs automatically on an existing server when U-OPTI itself is updated.
