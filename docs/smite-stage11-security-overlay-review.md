# Stage 11 — Offline security-aware Overlay migration review (DRAFT)

**No Smite container or host Overlay may be changed automatically by this stage.**

U-OPTI's historical runtime Overlays modify Panel and Node code for
FRP WSS/443, dynamic Backhaul ports, foreign Node control metadata
and other compatibility improvements. Simply dropping them would
risk breaking working tunnels; keeping them unchanged could shadow
the new HMAC/Persisted Pairing security modules.

## Added

`modules/smite-stage11-overlay-review.py` reads two manually supplied,
extracted and reviewed Panel/Node `/app` directories alongside existing
U-OPTI host Overlay sources. It creates a **new private 0700, review-only**
directory containing 0600 candidate source copies from the security images
and a `REVIEW.json` manifest of hashes, boolean source compatibility,
the number of missing security hooks and counts of legacy host features
that need manual migration.

Known incompatibilities are explicit, including:
- Panel main `existing_ports` Backhaul preservation patch
- Panel NodeClient custom `control_address` resolution
- Node PanelClient `SMITE_CONTROL_ADDRESS` and
  `SMITE_BACKHAUL_ADDRESS` metadata patches
- Node core adapter FRP WSS/443 compatibility
- Panel main HMAC router registration and Standard Backhaul startup guard
- Signed NodeClient canonical Backhaul dispatch

The bundle contains **proposed source from the image, NOT a semantic
automatic 3-way merge**. Any missing feature or changed host Overlay
is marked HOLD_REVIEW_REQUIRED. The manifest includes no token,
password, secret contents, or shell output of source lines.

This is intentionally more conservative than copying old files over
new ones: old application source may bypass security even when it still
makes FRP/Backhaul work. The manually reviewed final integration is
a future, separate task.

The standalone `u-opti --smite-pairing` preview menu includes option 8
to create an offline review bundle from previously extracted candidates;
no Docker run/pull/build/restart/up or changes to Compose, identity
files, live Overlays, Nginx, firewall or tunnel state.

**Approval remains blocked** even with matching source. Verify the
source image against an immutable published digest and registry provenance,
the effective Docker bind-mount map, valid TLS/443 signed paths, safe
Node secret permissions, Backhaul and FRP actual client traffic, failover,
and IR/KH snapshot rollback before any coordinated deployment.

Companion Smite Stage11 source branch ports the opt-in Backhaul
compiler and FRP/443 adapter into the new security-aware image
without claiming complete FRP/Backhaul migration.

All changes are draft-only. No user commands needed.
