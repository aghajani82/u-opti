## RC9 Foreign Node installation-code fix (2026-11-19)

The original RC7 UI package and its exact-image admission are retained unchanged.
For the **exact reviewed RC9 Panel image** `ghcr.io/aghajani82/smite-panel@sha256:f6999effd131f6b3272f8d9116b3fbae917f699bf9a29271fc5ede24cc387a2e`, menu **8) Update Panel appearance (UI only / backup first)** now chooses the **separate**, SHA-256-pinned `modules/smite-panel-ui-rc9.json` automatically. It is compiled reproducibly from reviewed Smite `main` source `f3f8d39cb66b7cf536879501ccefc74c835ae2bc` (Smite PR #59, green frontend CI run 44575937768). There is **no** Docker recreate, Node pairing change, database migration, Gateway/FRP mutation, or live host deployment during GitHub commits.

**Reason for the change:** the Foreign installation issuer on Iran Panel returned HTTP **200**, yet the older browser UI displayed `Code could not be prepared`. The old UI rejected code responses when the operator's browser clock did not fall within its exact two-hour expiry window. The reviewed Smite source removes client-clock authority from grant issuance, uses the server Date header for the UI countdown (with a conservative fallback), and shows actionable issue API statuses. The Panel server **still enforces** the actual one-use, two-hour grant, signed identity and HTTPS/443 origin. Do **not** disable backend pairing/security controls or delete/re-create an existing reserved Node.

**Existing Iran RC9 host (no rebuild):**

1. Update U-OPTI from `main` through the ordinary U-OPTI updater (an update must download this helper and the new RC9 JSON bundle).
2. Select `Docker Management → Smite Management → Install / Lifecycle → 8) Update Panel appearance (UI only / backup first)`, confirm, and require `UI_UPDATE=PASS; source=f3f8d39cb66b7cf536879501ccefc74c835ae2bc; restart=NO`. `UI_UPDATE=ALREADY_CURRENT` is acceptable only if a prior successful RC9 UI update is confirmed.
3. Refresh the Panel with Ctrl+F5, reuse the **same reserved Foreign Node** and Gateway domain, then prepare installation information again.
4. If needed, option `9) Roll back previous Panel appearance (UI only)` uses the original durable private backup. A mismatched or unknown container image is a safe **HOLD**; inspect the exact image before trying another path.

The old RC7 package and rollback behavior remain supported. U-OPTI's public Iran/Foreign installation options and signed release admission remain unchanged; upgrading U-OPTI alone does not rewrite the running Panel UI. This procedure does not imply that the Foreign host option-2 release is cleared for use.

---

# Static Panel UI update and rollback

The existing RC7 design is retained. The Login and desktop dashboard now use **90% proportional rem density at viewports >= 1024px**, matching the approved visual references without CSS zoom or transform. The large Smite title stays and mobile (<1024px) keeps its original 16px root font and touch sizing. Sidebar width, dashboard gutters and card gaps shrink together. Dashboard, Logs, Core Health, Tunnels, Iran Nodes and Foreign Nodes now expand across the available main-panel width rather than retaining centered `max-w-7xl` limits, removing large empty side bands. The outer 90%-scaled side padding and existing card gaps remain unchanged; backend, MFA and navigation are unchanged.

## Operator flow

Update U-OPTI first. Open Docker Management → Smite Management → Install Components.

- **1:** Fresh Panel + Iran Node installation selects the existing signed RC7 image pair and automatically applies the reviewed static UI after runtime installation commits.
- **8:** Back up and update the appearance of an existing running RC7 Panel. Confirm the prompt. Refresh the browser with Ctrl+F5 afterward.
- **9:** Restore the previous UI on the same container. This also recovers an interrupted UI operation. Confirm the prompt.

The helper admits only the exact reviewed RC7 Panel image, uses the local Docker socket, rejects static bind/volume overlays and never restarts/recreates a container. Node, backend Python, environment, SQLite, pairing and tunnels are untouched. Other Panel image versions fail closed.

## Provenance

- Smite main source: `5e7a289071e446345ac27e4255994daf3446430a` (PR #57, retaining PR #56's fluid Dashboard, PR #55's 90% density and PR #47's Login branding).
- Build: https://github.com/aghajani82/Smite/actions/runs/42513266989 (all frontend validations passed).
- CI artifact: `smite-rc7-ui-only-static-preview`, id `13630845198`. Exact compiled assets from this source were reproduced and their per-file SHA-256 values independently checked before embedding in U-OPTI.
- `modules/smite-panel-ui.json` contains the exact CI static bytes in base64; original per-file manifest hashes were checked before packaging.
- Bundle SHA-256: `ad92e819a4a47e80b1991b5d52e1873bb5b08db48118a86e660fe15f979286e1`, pinned in the helper.
- Backend image selection/signature validation remains unchanged. This UI package is SHA-pinned distribution data, not a newly signed container image.

## Recovery and limits

A root-owned 0700 journal directory at `/var/lib/u-opti/smite-panel-ui` holds the prior static files before publication. Assets are staged first and `index.html` is atomically replaced last; existing hashed assets are retained for already-open tabs. Reapplying the same package is idempotent. Previous journals are archived before a later update.

A changed container ID or unrecorded index change blocks rollback rather than restoring into an unknown runtime. Backups are retained on failure. Do not delete the journal to bypass a HOLD. A failed UI step after fresh runtime installation is retried with option 8, not with another installation.

Static files persist across container restart, but a **recreate/image replacement resets the writable layer**. Re-run option 8 on a recreated compatible RC7 Panel; a new backup will be made. This feature does not alter Compose mounts to make UI files persist across image changes.

Checks use fixtures and disposable Docker containers, not live VPS state. No updater runs automatically on an existing server when U-OPTI itself is updated.

## 90% UI activation on existing IR Panel

U-OPTI's option 8 deliberately installs the **embedded reviewed static bundle**, not the latest mutable Smite GitHub `main`. A new Smite PR alone never changes the embedded U-OPTI payload. This change updates both the embedded bytes and their immutable source/hash pin.

After U-OPTI `main` includes this package, run **U-OPTI → 8) Update U-OPTI** first, then **Docker Management → Smite Management → Install / Lifecycle → 8) Update Panel appearance**. The U-OPTI updater detects changed modules even when `VERSION` remains `0.17.8` (no artificial version bump needed). The UI menu keeps the previous backup and does not restart the Panel or Node. Confirm `UI_UPDATE=PASS; source=5e7a289071e446345ac27e4255994daf3446430a; restart=NO`. If it prints `UI_UPDATE=ALREADY_CURRENT`, check `UI_SOURCE` through the read-only status helper. Refresh the browser with Ctrl+F5 and set browser zoom to **100%**. A mismatched Panel image produces HOLD; never bypass its image admission guard or overwrite service/Compose files.

For a read-only provenance check on the host:

```bash
python3 -B /usr/local/lib/u-opti/modules/smite-panel-ui.py status
```

Expected: `UI_SOURCE=5e7a289071e446345ac27e4255994daf3446430a`. Never treat the GitHub Actions preview archive itself as an authorized live install package. No live host was changed while preparing this reviewed bundle.

## Full-width dashboard correction (PR #56)

At browser zoom **100%** with the 90% desktop layout, the dashboard width now fills the content area's usable width. It does not retain the previous centered `max-w-7xl mx-auto` constraint. Internal metric card gaps and outer main padding remain proportional, and the Login is unchanged. Browser checks cover 1366, 1600, and 1920 desktop widths, mobile, dark/light, and EN/FA. After U-OPTI updates the newly pinned static bundle, reapply UI-only option 8, confirm source, then Ctrl+F5. Do not recreate the Panel or touch Node/FRP/Backhaul for a UI update.

## Full-width operator pages correction (PR #57)

The original centered max-width remained in five pages after the Dashboard fix. Only the top-level wrappers of Logs, Core Health, Tunnels, Iran Nodes, and Foreign Nodes were changed to the same `w-full min-w-0` layout as Dashboard; Settings was already correct. The login, sidebar, root 90% density, outer padding, card gaps and all runtime/API behavior remain unchanged. Source: Smite `5e7a289071e446345ac27e4255994daf3446430a`; reviewed main UI CI run `42513266989`; artifact `13630845198`; screenshot/browser assertions check 80 route combinations in addition to Login and Dashboard. The U-OPTI SHA-pinned static package must be updated and option 8 reapplied after a U-OPTI update. No live changes occur as part of this source-only PR.

## Repair Foreign pairing after the temporary suspension

Fresh Iran option 1 installs the clock-safe RC9 UI after signed Foreign enrollment and Gateway preparation. On an existing RC9 Iran Panel, update U-OPTI and rerun **Install Panel + Iran Node** (option 1). It resumes from the saved checkpoint and applies the same UI package. Wait for `IR_PANEL_STATIC_UI=RC9_PAIRING_READY` and `PANEL_AND_IR_INSTALL=COMPLETE`, then refresh the Panel and prepare installation information for the same reserved Foreign Node. Update U-OPTI on Foreign before selecting **Install Foreign Node** (option 2). Use the Panel-issued packet in the Foreign installer.
