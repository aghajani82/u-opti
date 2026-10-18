# Stage 14 — Frozen paired Smite/U-OPTI release review (DRAFT)

**Review-only; no published OCI image, no tag and no server changes.**
The proposed version `2.0.0-rc.0` is NOT the version running on
IR/KH and is not a deployable release.

## What was integrated

The prior U-OPTI Smite stages #28–#35 are stacked along one branch,
but admin-protected U-OPTI Panel host Overlay PR #27 was an independent
sibling based on `main`. Without deliberate integration, the old
host `/app/main.py` bind mount could overwrite the new Panel security
router protection even when the image includes it.

Stage14 copies the reviewed `smite-panel-auth-overlay.py` guard and its
offline regression tests into this stacked U-OPTI branch, wires it into
`smite_prepare_overlays` **after** the copy of `main.py` from Docker,
and includes the helper in both fresh install/update manifests.
The helper validates that admin JWT dependencies exist, is idempotent
on the new security-aware Smite source, and fails on an unknown or
partly-guarded legacy source rather than replacing it silently.

This makes the PR27 *functionality* part of the Stage14 review branch.
It does **not** close, merge or modify existing PR #27. Once the full
release is reviewed, maintainers must avoid landing duplicate changes
twice or losing other unrelated concurrent modifications.

## Source-locked cross-repo review

`release/smite-stage14-integration-review.json` records:
- Exact 40-character Smite Stage14 review commit and the U-OPTI Stage13
  dependency commit (not floating `latest` tags).
- The extra independently ported PR27 JWT overlay guard.
- The matched HMAC v1 signed gateway and machine registration targets.
- A **proposed, not published** SemVer preview `2.0.0-rc.0`.
- Explicit unresolved integration, deployment and testing requirements,
  `automatic_merge=false`, `automatic_deployment=false` and
  `activation_allowed=false`.

`tests/test-smite-stage14-integration.py` operates on source only. The
GitHub Actions `bash-validation` job checks out Smite at the **exact
manifest-pinned commit** into an isolated source subdirectory and tests
the real U-OPTI gateway HMAC bytes using Smite's actual Node verifier,
including forged payload/reused nonce rejection. It ensures the JWT
overlay patch recognizes already-secured Smite `main.py` without
accidentally modifying or disabling the signed routers.

Other U-OPTI FRP, Backhaul, Nginx, signing, Docker, and preflight
regressions continue to run in the normal CI jobs.

## Critical HOLD: not a deployable bundle

- A source hash pin and green CI are not OCI image verification. The
  installer still defaults to the legacy upstream Smite v0.1.7 image
  and must **not** be switched to security modes as if new images
  were installed. A future release needs built, signed/attested and
  immutable digest-pinned Panel+Node images with verified runtime mounts.
- The JWT overlay helper preserves the legacy path but does not resolve
  every old U-OPTI FRP/Backhaul host patch against the new image.
  The Stage10/11 source parity checks still HOLD on mismatches.
- Trusted Pairing Nginx ingress proof injection and rate limiting,
  canonical Panel→Node 443 origin ACLs, Node→Panel HMAC path routing,
  secret mount service UID, replay and Panel Fernet key backups,
  two-host cloud snapshots, rollback and live tunnel validation
  are not complete.
- No live FRP/Backhaul/XHTTP clients have been exercised with the
  signed build; no two-host reboot/restore test has been performed.
- Private Network mode is separately blocked; this is Standard only.

## No action needed on hosts yet

No `docker compose up`, image push, Nginx reload, Panel migration,
signing-key deployment or server connection is part of Stage14.

The next milestone is a coordinated integration-review branch and
a **reproducible release candidate** with immutable image digests,
after which the user may opt into a supervised disposable IR/KH test
with snapshots and rollback procedures. Do not declare security done.
