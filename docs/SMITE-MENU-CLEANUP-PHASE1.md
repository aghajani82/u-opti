# Smite menu cleanup — phase 1 (experimental)

**Status:** GitHub preview branch only; safe navigation refactor, not a new production Backhaul installer. Follow `docs/SMITE-BACKHAUL-2026-10-14-FIELD-VALIDATION.md` for the live field test evidence and its outstanding validation gates.

## Why this change

The previous Smite Management menu displayed a duplicate FRP guide/setup path, a legacy Backhaul offline-only path, and the unified Tunnel Wizard all at once. The Backhaul submenu contained ten mixed everyday, safety and experimental actions. The same status dashboard was linked in two places. That was confusing after the field pilot succeeded.

## New navigation

```text
Smite Management
  1) Private Network Wizard
  2) Tunnel Management (FRP / Backhaul / Rathole)
  3) Status & Diagnostics
  4) Advanced & Legacy Tools
  0) Back

Tunnel Management
  1) Backhaul — independent Sidecar management
  2) FRP — existing Standard Smite wizard
  3) Rathole — safe plan only
  4) Tunnel Control Center
  0) Back

Backhaul
  1) Sidecar status & diagnostics (read-only)
  2) Strict installed Sidecar audit (read-only)
  3) v2rayN / Android client profile fields
  4) Experimental setup & recovery tools
  0) Back

Backhaul experimental setup & recovery
  1) Explain architecture
  2) Installation safety checklist
  3) Check NEW test host (read-only)
  4) Prepare private Sidecar candidate (OFFLINE)
  5) Prepare private Nginx proposal (OFFLINE)
  6) Check both private candidates (read-only)
  7) Test VPS install / guarded rollback (CHANGES SERVER)
  0) Back
```

**No original FRP wizard, private network wizard, trial engine, Sidecar candidate builder, Nginx planner or admission script was changed.** The FRP test guide, original FRP setup wizard and legacy Backhaul staging tools remain reachable from **Advanced & Legacy Tools**. No existing tunnel, Nginx file, Docker container, Xray inbound or secret on either VPS is modified merely by this GitHub commit.

The Backhaul experimental installer retains **all** original explicit role/host approvals, ownership checks, snapshots/console requirement and `HOLD` behavior. It is not a one-click production feature; after this navigation cleanup, offline staging and token transfer **still require manual operations**. The trial server approval marker is not created or bypassed automatically.

## Verification and next steps

- Hermetic shell navigation tests must prove routes to FRP, legacy tools, Backhaul status/audit, candidate checks and guarded trial remain callable; syntactic validation of touched shell files is required.
- CI passing validates menu wiring and fixture behavior, **not** live tunnels. The operator already separately verified working FRP and Backhaul traffic after sequential test-host reboots.
- **Next phase (not yet done):** a separately reviewed, fail-closed guided setup that creates paired private proposals automatically, validates fresh-host admission, eliminates manual `/tmp` copy/paste and presents a concise plan/confirmation. No automatic install on active hosts or premature `main` merge.
- Still pending before production: trial rollback, failure/recovery and reinstall field tests, KH numeric bridge bypass checks, and post-reboot inventories.
- The independent Sidecar is managed by U-OPTI. Adding real Smite-panel centralized control is a **later** change; do not register a conflicting Smite-managed Backhaul tunnel now.

## Continuation reference

Repository: `aghajani82/u-opti` — `feature/smite-standard-backhaul` — draft PR #18. Start with this file and the field validation document, not by re-running the already successful pilot installation.
