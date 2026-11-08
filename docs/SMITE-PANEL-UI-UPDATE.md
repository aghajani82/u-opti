# Static Panel UI update and rollback

The existing RC7 design is retained. The Login and desktop dashboard now use **90% proportional rem density at viewports >= 1024px**, matching the approved visual references without CSS zoom or transform. The large Smite title stays and mobile (<1024px) keeps its original 16px root font and touch sizing. Sidebar width, dashboard gutters and card gaps shrink together; backend, MFA and navigation are unchanged.

## Operator flow

Update U-OPTI first. Open Docker Management → Smite Management → Install Components.

- **1:** Fresh Panel + Iran Node installation selects the existing signed RC7 image pair and automatically applies the reviewed static UI after runtime installation commits.
- **8:** Back up and update the appearance of an existing running RC7 Panel. Confirm the prompt. Refresh the browser with Ctrl+F5 afterward.
- **9:** Restore the previous UI on the same container. This also recovers an interrupted UI operation. Confirm the prompt.

The helper admits only the exact reviewed RC7 Panel image, uses the local Docker socket, rejects static bind/volume overlays and never restarts/recreates a container. Node, backend Python, environment, SQLite, pairing and tunnels are untouched. Other Panel image versions fail closed.

## Provenance

- Smite main source: `d4b318de24faff3261a93687c37c52ca6a2a0acc` (PR #55, preserving PR #47's Login branding).
- Build: https://github.com/aghajani82/Smite/actions/runs/42504320814 (all frontend validations passed).
- CI artifact: `smite-rc7-ui-only-static-preview`, id `13626906940`. Exact compiled assets from this source were reproduced and their per-file SHA-256 values independently checked before embedding in U-OPTI.
- `modules/smite-panel-ui.json` contains the exact CI static bytes in base64; original per-file manifest hashes were checked before packaging.
- Bundle SHA-256: `5affecc8ed26606931fb0ddfe360275ab2b51f5695a0e52eac8685ddfe607598`, pinned in the helper.
- Backend image selection/signature validation remains unchanged. This UI package is SHA-pinned distribution data, not a newly signed container image.

## Recovery and limits

A root-owned 0700 journal directory at `/var/lib/u-opti/smite-panel-ui` holds the prior static files before publication. Assets are staged first and `index.html` is atomically replaced last; existing hashed assets are retained for already-open tabs. Reapplying the same package is idempotent. Previous journals are archived before a later update.

A changed container ID or unrecorded index change blocks rollback rather than restoring into an unknown runtime. Backups are retained on failure. Do not delete the journal to bypass a HOLD. A failed UI step after fresh runtime installation is retried with option 8, not with another installation.

Static files persist across container restart, but a **recreate/image replacement resets the writable layer**. Re-run option 8 on a recreated compatible RC7 Panel; a new backup will be made. This feature does not alter Compose mounts to make UI files persist across image changes.

Checks use fixtures and disposable Docker containers, not live VPS state. No updater runs automatically on an existing server when U-OPTI itself is updated.

## 90% UI activation on existing IR Panel

U-OPTI's option 8 deliberately installs the **embedded reviewed static bundle**, not the latest mutable Smite GitHub `main`. A new Smite PR alone never changes the embedded U-OPTI payload. This change updates both the embedded bytes and their immutable source/hash pin.

After U-OPTI `main` includes this package, run **U-OPTI → 8) Update U-OPTI** first, then **Docker Management → Smite Management → Install / Lifecycle → 8) Update Panel appearance**. The U-OPTI updater detects changed modules even when `VERSION` remains `0.17.8` (no artificial version bump needed). The UI menu keeps the previous backup and does not restart the Panel or Node. Confirm `UI_UPDATE=PASS; source=d4b318de24faff3261a93687c37c52ca6a2a0acc; restart=NO`. If it prints `UI_UPDATE=ALREADY_CURRENT`, check `UI_SOURCE` through the read-only status helper. Refresh the browser with Ctrl+F5 and set browser zoom to **100%**. A mismatched Panel image produces HOLD; never bypass its image admission guard or overwrite service/Compose files.

For a read-only provenance check on the host:

```bash
python3 -B /usr/local/lib/u-opti/modules/smite-panel-ui.py status
```

Expected: `UI_SOURCE=d4b318de24faff3261a93687c37c52ca6a2a0acc`. Never treat the GitHub Actions preview archive itself as an authorized live install package. No live host was changed while preparing this reviewed bundle.
