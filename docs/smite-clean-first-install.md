# Smite Clean Install — first RC bootstrap integration (DRAFT / DO NOT REBUILD YET)

This change converts the project's direction to **fresh installation
after explicit IR/KH rebuild**. It does NOT migrate any live Smite,
FRP, Backhaul, 3x-UI, credentials, inbound mappings or Docker containers.

## What has changed in the real installer

The existing U-OPTI Stable path remains the default
(`SMITE_INSTALL_PROFILE=stable`, upstream Smite v0.1.7 as before).
The new `SMITE_INSTALL_PROFILE=clean-rc` is **manual preview only**,
not yet published, tested on live hosts or suitable for production.

The clean RC mode:

1. Rejects any existing Smite state file, Panel/Node Compose, detected
   containers, or old host-based security-source overlays. It is not
   an upgrader and never imports running tunnel data.
2. Requires the **same Stage15 Panel and Node offline Docker archives**,
   the trusted exact Smite source Commit and separately trusted
   GitHub Actions manifest SHA256. No floating `latest`, silent
   network pull or fallback to v0.1.7 image is allowed.
3. Checks the manifest and both archive checksums before preparing files
   and again immediately before `docker load`. After each load,
   checks the local Docker image ID against the verified manifest.
4. Uses the known v0.1.7 upstream Compose *structure as a template*
   but replaces `image:` with the exact two locally loaded RC tags.
   The app code comes only from the RC images. This cross-version
   Compose compatibility still requires real first-boot testing.
5. Skips legacy Python bind overlays, the old compatibility patches,
   and the automatic *second* Panel/Node container recreation.
   Signed-auth code is not shadowed by the v0.1.7 overlay patcher.
6. Refuses Private Network mode. Only Standard two-host logic is
   under test. Even on a fresh host, the RC starts in the security
   flags' default legacy settings until coordinated Pairing/443
   admission is complete.
7. Automatically selects Standard (HTTPS where appropriate) on the
   clean RC path, without prompting for unavailable Private Network mode.
   Summaries distinguish skipped overlays from the unchanged Stable path,
   and clearly mark the RC preview instead of mislabeling it as v0.1.7.
8. Keeps installation order deliberate: **IR Smite Panel+Node first;
   KH Smite Node second; 3x-UI afterward; only then dynamic inbound
   path/port configuration and FRP/Backhaul tunnel creation**.
   This PR does not prematurely ask the installer to build any tunnel.
9. New clean-RC KH boots in **Waiting for secure pairing** state:
   `SMITE_NODE_PANEL_AUTH_MODE=paused` avoids the old unauthenticated
   Node registration that would silently target HTTP/8000 instead of
   HTTPS/443. `SMITE_AGENT_AUTH_MODE=strict` rejects Node Agent
   requests without a paired private identity; the Compose healthcheck
   uses only localhost liveness to avoid false failure of an unpaired
   node. It does NOT fetch a CA or require the IR 443 gateway *during*
   KH installation. Provisioning/restarting signed mode is a separate
   future gate, not a second installation. Stable behavior is unchanged.
10. Clean RC disables public API docs on the IR Panel by default.

`modules/smite-clean-image-pair.py` checks paired archive inputs without
Docker, writing files, executing scripts or network access. The
installer profile performs the actual `docker load` only on explicit
operator-selected trial installation.

## Why this is still DRAFT / HOLD

- The Stage15 offline archives are ephemeral, not signed registry
  artifacts. Their manifest/Commit hashes provide byte integrity but
  do **not** independently attest build provenance.
- Fresh Panel and Node image container startup using the legacy pinned
  Compose template remains untested on disposable IR/KH. Smite's separate
  isolated CI first-boot gate passed, but it cannot prove host Compose,
  gateway, volume permissions or two-host integration. KH's paused mode
  **must never be presented as Connected** before secure pairing.
- Pairing/machine registration, admin-approved Node destinations, new
  Nginx 443/HTTP target routing, permissions for Node's private HMAC
  identity and Panel Fernet master require a coordinated two-host trial.
- **Stage24 Docker Compose cross-project gate:** In PR-only CI,
  run the actual U-OPTI `smite_install_node_files` transforms against
  the pinned-reviewed Smite Node source's upstream Compose (FRP binary
  injection intentionally stubbed, as FRP traffic is out of scope).
  The Stage9 private-root-owned secret and replay-volume overlay uses
  matching Compose environment LIST syntax, not a mapping. Validate
  real Docker Compose merge and inspect host-network baseline (no
  `ports`) before running a strict *network:none* disposable
  isolation-only override. Build the same-source Node image and exercise
  `paused -> signed -> paused -> signed` with Docker Compose up
  `--no-build`, confirming no reinstall, no insecure fallback,
  read-only credentials, Agent HMAC, nonce replay persistence, health
  and intact base Compose hash. This is **not a green light to activate
  the host-network original**, Node-to-Panel public TLS, 3x-UI, FRP,
  Backhaul or real two-host gateways.
- **Stage22 signed registration transaction guard:** Smite's
  authentic signed Node check-in no longer marks a reserved KH active
  before Panel FRP return-configuration admission completes. An invalid
  or incomplete FRP host/token/port must return HTTP 503 while preserving
  `pending` / `reserved_for_pairing`; only after the FRP settings
  pass may a new HMAC-signed, nonce-fresh check-in mark KH active.
  Unit and real Nginx/TLS integration tests are tied to exact reviewed
  Smite source SHA `5e7dc25be8109e3260ab078466b508d827abfe94`. No live server activated.
- **Stage21 isolated Node-to-Panel HMAC transition:** Reuses
  the real Stage20 Nginx SNI/TLS and authentic Smite Panel pairing API.
  Adds the real reviewed `Smite/node/app/node_auth.py` signer with signed
  registration routed unchanged through Nginx to the real
  `Smite/panel/app/routers/signed_nodes.py` and persisted replay store.
  The pending KH record must stay pending after OTP redemption; only the
  signed valid Node check-in can mark it active. Unsigned, forged-key,
  modified-body, stale timestamp, wrong role, replayed nonce and
  unexpected request-target probes must fail closed. The signed mode is
  **only switched on in ephemeral CI process environment**, never on
  IR/KH or the operator's Compose files. This does NOT demonstrate
  in-container identity mount, 3x-UI, FRP/Backhaul or real two-server
  readiness.
- **Stage20 real isolated pair gateway lab:** Draft PR CI checks out
  a pinned reviewed Smite commit and exercises the REAL JWT-admin and
  pairing FastAPI routers through REAL ephemeral Nginx stream/SNI/TLS,
  certificate and hostname verified, with only loopback ports.
  Verifies admin reservation/issue, private ingress proof replacement,
  replay/method/body-size denial, backend proof bypass denial,
  non-pairing fallback preservation, malformed config HOLD and
  temporary lab Nginx reload/rollback. **No two-host, public 443,
  Docker, VPS or production security mode activation.**
- **Stage19 IR pairing/443 gateway plan (OFFLINE ONLY):** The existing
  Standard installer already sets `PANEL_HOST=127.0.0.1`, so no
  installer behavior is changed. New `smite-stage19-pairing-443-plan.py`
  prepares a private 0700 directory containing a disabled-by-default
  Panel pairing environment candidate, an independently generated Fernet
  master, Nginx ingress proof stored in a dedicated 0600 include, and
  exact-path `/api/node-pairing/redeem` location for the EXISTING
  loopback TLS 8443 backend. No second TLS listener is created. Files
  are never automatically installed, loaded, logged or uploaded; Stage19
  refuses overwrite and exposes no secret in stdout. Real IR validation
  of TLS, Nginx include permissions, gateway path, 8000 isolation,
  backups, and both endpoints remains HOLD. No VPS was touched.
- **Stage18 secure pre-registration bridge:** In Smite's disabled-by-default
  pairing preview, an authenticated admin can reserve a **pending**
  Foreign Node from the Servers page using just a name. The Panel issues
  a Node UUID without insecure Node HTTP registration, and its existing
  one-use Pair action can issue a code scoped to this UUID. On KH, the
  installed Node stays paused until separate TLS/443 pairing and signed
  activation. A genuine HMAC-signed check-in (not reserving or issuing a
  code) is required before the Panel can clear "Waiting for pairing".
  This path has offline API/CI tests; it has NOT been activated on IR/KH.
- The earlier Nginx security and FRP/Backhaul compatibility stages
  contain pending changes; they are not all activated automatically by
  this clean RC bootstrap.
- Full FRP/Backhaul/XHTTP data traffic, 3x-UI integration,
  creation/removal of tunnels, reboot, provider snapshots and
  rollback have NOT passed live acceptance.
- A new build/Artifact should be independently verified, supported
  with reviewed immutable image publication, and integrated into a
  final installer/release before instructing the user to rebuild.

## CI acceptance for this PR

`tests/test-smite-clean-install.sh` uses fake gzip Docker archives,
real SHA verifier and a **mock Docker function**. It asserts:
- IR loads exactly two images, KH loads only Node
- Correct image IDs must match manifest; a mismatched digest HOLDS
- No old state or Private mode can trigger a clean install
- No legacy host Python overlays or second Docker recreation
- No v0.1.7 image pull in clean RC mode (legacy CLI and Compose
  templates are still downloaded, and pinned FRP binaries prepared)
- Interactive IR/KH clean setup automatically selects Standard with no
  unsupported Private choice; Stable still presents its historic choice
  and fails closed on invalid input; no Docker/network calls occur in
  these input-flow tests.
- The original stable image pull + overlay path is still intact

`tests/test-smite-clean-image-pair.py` checks manifest integrity,
wrong source/digest and intentional no-fallback behavior.

**Do not rebuild yet.** The precise recommendation to rebuild comes
only after a separate successfully verified full install and
connectivity rehearsal; this draft code is not that proof.
