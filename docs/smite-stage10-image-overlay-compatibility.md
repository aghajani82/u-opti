# Stage 10 — Audit Smite image/overlay compatibility (DRAFT, read-only)

**Goal:** Prove that older U-OPTI host bind mounts cannot silently replace
new signed-auth modules in Panel/Node Docker images. Does NOT apply images
or deploy anything on IR/KH.

## The real compatibility issue

The existing U-OPTI `modules/smite.sh` manages persistent host overlays,
mounted over application Python files **inside** Smite. Even if an image
contains HMAC and pairing changes, an older mounted file can completely
replace the corresponding new implementation:

Panel:
- `/app/main.py`
- `/app/app/node_client.py`
- `/app/app/routers/nodes.py`
- `/app/app/routers/tunnels.py`
- `/app/app/tunnel_reapply_manager.py`
- `/app/app/routers/core_health.py`

Node:
- `/app/app/panel_client.py`
- `/app/app/core_adapters.py`

This is a source-compatibility failure, **not an automatic data migration**.
Simply removing all overlays is also unsafe: they carry operational
FRP/Backhaul modifications that need to be ported and tested first.

## Stage 10 tool

`modules/smite-auth-image-overlay-audit.py` is an entirely read-only
source-parity tool. It accepts paths to the extracted **/app directories**
of two reviewed, unpublished image candidates, the host Overlay root and
the existing Compose sources. It:

1. Checks the security-critical Panel and Node Python source modules
   are present and syntactically compilable.
2. Finds all eight known source-code overlay mounts in Compose.
3. Requires any mounted host file to be a regular, non-symlink
   source with **byte-for-byte SHA-256 parity** against the candidate
   image's corresponding file.
4. Returns HOLD for missing/invalid source, mismatched overlay, shadow
   mapping from an unexpected location or duplicate mount.
5. Prints only status labels; never prints an identity, pairing code,
   FRP/Backhaul token, source lines or file content.
6. Always reports image provenance, running Docker mount states,
   HTTPS/443 HMAC and real FRP/Backhaul client traffic as **UNVERIFIED**,
   and `AUTH_ACTIVATION=BLOCKED`, even with matching source.

Exact byte parity is a conservative **migration gate**, not necessarily the
only safe eventual strategy. FRP/Backhaul custom overlays will often fail
parity until reimplemented against the new security-aware source or moved
to a separately reviewed plugin/sidecar integration.

The standalone `u-opti --smite-pairing` preview wizard gains option 7:
run the offline source-parity check using two **manually supplied**,
absolute extracted image directories. It does not pull Docker images,
run containers or change Compose. No images or extraction directories
are invented by the wizard.

## Remaining blocks before any deployment

- Build both Panel and Node from the right reviewed Smite security branch,
  verify immutable registry digests and provenance, and compare actual
  image bytes to the reviewed candidates. Smite Stage10 adds isolated,
  unpublished build smoke checks.
- Inspect and reconcile U-OPTI host file overlays, including FRP gateway,
  Backhaul, node client and Panel main router. Keep real operational paths.
- Validate the Node image's actual service user and the selected 0600
  identity, 0700 replay directories, read-only mounts and strict-mode
  healthcheck compatibility.
- Complete Panel trusted 443 ingress, one-time Pairing rate limits,
  Panel secret master storage, Node/Panel signed registration modes and
  authenticated client control.
- Restore snapshots only within an explicitly coordinated two-host
  activation; verify FRP, Backhaul and XHTTP real traffic and rollback.
- Private mode requires an independent design/verification.

Stage9's separate INERT security Compose candidate is not automatically
included, applied, restarted or otherwise activated by this change.

**No commands are needed on IR or KH during this draft-only stage.**
