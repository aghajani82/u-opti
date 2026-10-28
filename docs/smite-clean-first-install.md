# Smite Clean Install — first RC bootstrap integration (DRAFT / DISPOSABLE TRIAL ONLY)

## Smite × U-OPTI delivery status (2026-10-27)

The canonical cross-repository delivery board is maintained in [Smite: SMITE-UOPTI-DELIVERY-BOARD.md](https://github.com/aghajani82/Smite/blob/main/docs/SMITE-UOPTI-DELIVERY-BOARD.md). Use that board for current IR/KH milestone status, release gates, and the documented order of installation. The historical stage-by-stage draft notes below are **not** instructions to apply old preview images or merge old stacked PRs.

**Current Clean-RC IR field check:** `smite-panel:stage15-local` and `smite-node:stage15-local` are running with `SMITE_VERSION=2.0.0-rc.1`. Panel/Agent registration mode is signed, but secure Panel pairing is **disabled**, the Node is **paused + strict**, credentials are not staged, and replay enrollment is not provisioned. An active container is **not** evidence that a Node is registered in Panel. The signed-only Iran/KH name reservation change was reviewed in Smite #33; promoting its source to main **does not upgrade these locally pinned trial images**. Do not use the old IP/API-port form in signed mode, enable pairing prematurely, or rebuild the IR/KH VPS merely because CI passes. Stage an independently checked matching image/source pair and test rollback before enabling live enrollment.

This change converts the project's direction to **fresh installation
after explicit IR/KH rebuild**. It does NOT migrate any live Smite,
FRP, Backhaul, 3x-UI, credentials, inbound mappings or Docker containers.

## Explicit Clean-RC entry point (2026-10-27)

The normal Docker Management → Smite Management entry currently includes the older Private Network/EasyTier wizard. **Do not use that wizard for this Standard HTTPS/443 Signed Pairing field trial.** The clean image-pair installer has an explicit direct entry instead.

After installing U-OPTI on a disposable IR or KH host, use **Update U-OPTI** before starting the Clean-RC flow. If the host already had an older fixed-file updater, run **Update U-OPTI a second time** if the Clean-RC preflight says the broker modules are not at the required revision; it will HOLD before package or service changes until the new module list is installed. Copy the verified ZIP to that host and extract it so this directory contains `stage15-images.json`, `smite-panel-stage15.docker.tar.gz`, and `smite-node-stage15.docker.tar.gz`. Then run:

```bash
SMITE_RC_BUNDLE_DIR=/opt/smite-stage15-bundle \
SMITE_RC_SOURCE_SHA=4e16633a304db6c03f7f2911cc7d77213b0c4ec1 \
SMITE_RC_MANIFEST_SHA256=fe32c9c54714cfdb482f27112829eba13d5188e9e1e7e26c7266d8d54e85462a \
u-opti --smite-clean-rc
```

The CLI verifies the paired archive/manifest inputs **before** opening the component menu. It explicitly selects `SMITE_INSTALL_PROFILE=clean-rc`; it does not start pairing or activate a tunnel by itself.

- On **IR**, choose `1) Install Panel + Iran Node`. Clean-RC asks to prepare
  host Nginx, Certbot and the Nginx stream module before creating Smite files;
  accept this prerequisite prompt. This starts/prepares the host gateway packages
  but does **not** configure the Panel domain or request its certificate yet.
- On **KH**, choose `2) Install Foreign Node`.
- On **KH after the Foreign Node exists**, choose `4) Install Sanaei 3x-UI on Foreign Node`. If no Sanaei instance exists, the option launches the normal U-OPTI installer; after it returns, reopen option 4 to attach the selected Sanaei database read-only to the KH Node.
- Do not select option 5 (existing-IR upgrade) during a fresh install.
- Configure the IR HTTPS/443 gateway and then the KH HTTPS/443 control gateway from the Standard FRP Test Guide's gateway actions; do **not** run its legacy FRP tunnel test yet.
- Secure enrollment is a separate explicit step: `u-opti --smite-pairing`. Follow the on-screen safe order: IR pairing/check-in first, approve the KH Gateway origin on IR, then redeem and activate the KH identity.
- Create the actual FRP/XHTTP tunnel from the Smite Panel UI only after both Nodes show the expected signed/active state and Sanaei inventory is verified. Do not manually launch `frps`/`frpc` or Backhaul commands in the terminal for this path.

Use the same source SHA, manifest SHA, and exact image-pair ZIP on both disposable hosts. The ZIP SHA256 is `2bda0c80aa77ce6fa6bd1af0a4ed0d8fccfad670915dfd2f56a6120b08d19a71`. Never use these preview images on Grandoptical/production.

## First-boot Root Broker readiness regression (2026-10-28)

A fresh IR trial reported `HOLD: Root Broker activation did not pass its
systemd/socket checks` even though later read-only inspection found the
`u-opti-smite-xhttp-broker.service` active, the private root-owned UNIX socket
present with `0750/0660` permissions, and the dedicated peer group intact.
The Node broker forwarding flag remained `false`. The historical installer
hid the actual provisioner `HOLD_...` reason because its Bash filter expected
an equals sign after `HOLD`; therefore the specific original failure
cannot be proven from that captured output alone.

Source-level finding: `Type=simple` systemd start returning is **not**
proof that the Python listener has bound or begun listening. The activation
helper previously checked the socket just once. The fix uses a **bounded**
startup wait for `activating` service state, trusted socket metadata,
and a successful local UNIX connect before enabling Node forwarding. The
brief root-owned owner-only `0700` socket created under `UMask=0077`
between `bind()` and `chmod(0660)` is treated as **not yet ready**, never
as approved. Wrong owner, unsafe mode, unexpected systemd state, permanent
socket errors, or readiness timeout **still HOLD**; no grant is created and no live route is
changed. The broker also tolerates a health-check peer closing before reply.
The installer now displays the specific sanitized `HOLD_...` code without
printing keys or arbitrary helper output.

Regression coverage simulates delayed socket creation and delayed listening,
immediate wrong-owner rejection, bounded timeout, disconnected clients, and
visible sanitized failure reporting. These checks demonstrate the corrected
first-boot control logic, **not** a completed real two-VPS install. Keep the
existing IR/KH host unchanged; use a new disposable snapshot-backed clean
rebuild only after the code is merged and CI verifies the exact head, then
report the complete IR first-boot and later KH/443 pairing evidence.

## Recovering an interrupted Clean-RC IR install

If the IR installer has already started the Panel and Node but stops during the Root Broker/Node channel check, **do not rerun option 1**: the clean installer intentionally rejects existing containers/Compose files. Update U-OPTI from main, then open **Docker Management → Smite Management → 8) Resume interrupted clean-RC IR test install**.

The recovery menu verifies the existing Panel/Node images, environment files and current Stage15 bundle before asking for the exact confirmation phrase. It then offers to prepare the host Nginx/Certbot/stream packages if needed, before activating the Root Broker. Activation repairs only the exact known older systemd unit whose lazy `/run/lock` paths were not marked optional, and creates only the missing, root-owned `/etc/nginx/smite-xhttp-routes` directory (mode `0755`) when `/etc/nginx` exists and passes ownership/permission checks. It does not create TrustedGrants, enable pairing, or add live route files. If recovery does not pass, stop and share the full output; do not manually enable the service or delete the partial installation.

## What has changed in the real installer

**Source status (2026-10-26):** broker, signed Node forwarding, KH read-only Sanaei mount, existing FRP wizard handoff and clean-RC broker bootstrap are implemented on U-OPTI PR #48 / Smite PR #32. Current heads `88564641ebf35f3111c87188f7ae4ee8a8885b17` (U-OPTI) and `da1c08896508a5c9b3d7601d2943575b90f5c223` (Smite) passed CI: 16/16 U-OPTI jobs plus 5 focused checks, and 12/12 Smite workflows. This status permits evaluation only on separate disposable Ubuntu trial VPSs; it does not authorize or qualify an existing IR/KH host or Grandoptical.

The exact-head Smite preview bundle is available from [Stage15 workflow run 40314745761](https://github.com/aghajani82/Smite/actions/runs/40314745761), artifact `smite-stage15-offline-images-da1c08896508a5c9b3d7601d2943575b90f5c223`, artifact ID `12645917689`. The uploaded ZIP digest is `sha256:ba94e9547871a52c8dae13a71b3fc6de342e14cfedaacfa6b5bc91ba5dac45ea`; retention expires 2026-10-29 11:26 UTC. It is an **untrusted, temporary test artifact**, not a signed registry release. Verify the archive digest and the inner source/manifest digests before use. Root grant approval for each test child remains an interactive operator action; evidence is operator-asserted.

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
- **Independent engines, phase 1 / Core only:** U-OPTI's opt-in
  `clean-rc` Smite Panel and IR/KH Node installers **do not download,
  install, mount or version-check host FRP binaries**. Core can start
  paused/signed-only with **zero selected tunnel engines**; no FRP
  service is enabled by the fresh default database. Stable retains
  its existing pinned FRP preparation, mounts and verification.
  IMPORTANT: current *unpublished Smite preview images still bundle*
  FRP and Backhaul binaries internally: this is a removal of the
  mandatory **host FRP installer dependency**, not yet a fully minimal
  core-only image. Engine installation/activation and public 443 tunnel
  data transport remain subsequent gated phases, not active features.
- **Stage28 IR firstboot unsigned-registration closure:** Clean-RC
  Panel now explicitly boots with `SMITE_NODE_REGISTRATION_MODE=signed`
  and `SMITE_PANEL_AGENT_AUTH_MODE=signed`, while the pairing-preview
  API remains disabled until separately migrated and backed up. The
  local **Iran Node**, like the KH Node, boots `paused + strict` with
  an unauthenticated local-only liveness healthcheck. The IR installer
  does **not** wait for a fake legacy active Node registration or
  write an unapproved local control address. Both IR and KH remain
  pending until explicit admin-approved signed enrollment. A dedicated
  inert regression test checks the actual installer-generated Panel and
  Iran Node files and explicitly verifies that the stable install
  profile remains unchanged. This is still an unpublished review-only
  image, NOT permission to deploy or bypass the two-host acceptance.
- **Stage27 fail-closed gateway/FRP/status hardening:** Both cross-project
  CI branches now pin identical reviewed Smite source SHA `75412e8ea77565b6b21a6ac7f73827b221272d6a`.
  Signed gateway readiness requires a genuine authenticated check-in,
  matching the administrator-approved `Node.name` AND
  `Node.metadata.node_name` individually; a changed name never
  triggers an Agent probe. A signed FRP heartbeat cannot mark a paired
  but pending Node connected. Signed Nodes without completed check-in
  remain "waiting-for-pairing" in listings; the old FRP heartbeat hint
  must never override a failed live signed Agent status check.
  Existing legacy runtime modes were not enabled or changed. Unit,
  integration, and negative security tests exercise these cases.
- **Stage26 real outbound HTTPS/443 CI gate:** In disposable PR CI
  run actual `Smite/panel/app/node_client.py` HMAC requests over
  hostname/certificate-verified HTTPS/443 through an independent
  temporary loopback-only Nginx gateway to the genuine
  `Smite/node/app/routers/agent.py` strict authentication middleware.
  The Node's adapter is an inert in-memory fixture: status, Apply and
  Remove are authenticated, but **no FRP/Backhaul tunnel is started**.
  Check that a paired but pending KH receives no commands; approved
  signed-checkin KH can receive exactly scoped commands, while HMAC
  replay, body tamper, unknown CA, path rewrite and HTTP redirect
  fail closed. All modifications, including the ephemeral DNS host
  mapping and TLS listener, are restricted to and cleaned up on the
  GitHub runner. This is NOT real two-host deployment.
- **Stage25 two-direction HMAC admission guard:** Both isolated
  U-OPTI test jobs use the SAME reviewed Smite source SHA
  `0ba7fe4f174817a3822cf7efa09c495903fbee9c`. The real Panel signed NodeClient now refuses
  to send any command until the Node is `active` with
  `provisioning=signed_checkin`, established by real HMAC registration.
  The independently admin-approved UUID, role and name must match
  the registered Node and metadata; stale legacy `active`, paired-only
  `pending`, name drift and missing trusted origins fail closed.
  The existing full TLS/443 inbound test still runs, and its runner now
  executes exact Smite outbound NodeClient regression tests as well.
  No real Panel-to-KH TLS/443 gateway connectivity is asserted.
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
