# Smite / U-OPTI: security release admission — reviewed RC only

**Current decision: HOLD for real IR/KH deployment and for promotion to
Stable/main.** A green GitHub CI run is evidence for the listed tests, NOT
proof of live deployment readiness. There is no authorized automatic
promotion and no real VPS was modified by these reviews.

## What has been established in disposable environments

- The **clean-rc** (default-OFF) IR Panel starts signed-only for machine
  registration/control. Its local IR Node and the KH Node start
  `paused + strict`, with liveness checks that do not require legacy
  registration. Stable v0.1.7 paths and historical menus are unchanged.
- An admin can reserve a pending Node and issue a single-use short-lived
  pairing code only when the explicit preview/migrations are available.
  Pairing a key does NOT by itself make a Node connected or ready for
  Panel commands.
- Real HTTPX, Nginx HTTPS/443 and FastAPI integration on a disposable
  GitHub runner covers signed KH check-in, signed Panel-to-Node
  status/Apply/Remove through an **inert** tunnel adapter, TLS SAN/CA
  verification, HMAC payload/nonce replay rejection and proxy rollback.
- The actual Smite Node image and the actual U-OPTI-generated KH
  Compose have separately passed a paused→signed→paused→signed
  cycle with root-owned, read-only identities and persistent nonce
  history on disposable runner-local resources.
- Signed gateway readiness and signed FRP heartbeats require completed
  authenticated check-in. Approved UUID, role and both Node names must
  match. Old FRP success metadata cannot override failed authenticated
  liveness or mislabel a pending Node.

Reviewed SHA pair at this audit:
- Smite source `75412e8ea77565b6b21a6ac7f73827b221272d6a`
- U-OPTI source `8d897ab7dd1d993640ee29a41e8b58a870c80497`

CI evidence:
- Smite: [same-SHA offline paired-image and first-boot gate](https://github.com/aghajani82/Smite/actions/runs/39209973222)
- U-OPTI: [9-job offline integration](https://github.com/aghajani82/u-opti/actions/runs/39210581333)

## Operator MFA (two-factor) safety

Smite's reviewed Panel source `708b4ae6806a35bbd9ccbca163ca0909b41ffa7c` also adds a **local QR**
to the existing password-confirmed 2FA setup (without a third-party
image service). First login stays username + password, then the admin
can opt in from Settings; subsequent logins need a TOTP or one-time
recovery code. The code field is always visible but optional until
MFA has been enabled. Input mistakes on setup/disable must not log
the administrator out. Backend real-MFA integration and frontend
client regression jobs are release gates.

Before live deployment, confirm safe restoration of the actual
Panel `SECRET_KEY`/encrypted MFA keys and database, backup of offline
recovery codes and failure handling. See Smite
`docs/operator-two-factor-guide-fa.md`. **No live MFA was enabled.**

## Independent tunnel engines — Phase 1 initial milestone

- The opt-in clean-RC Smite Core installer no longer depends on
  `smite_frp_prepare_binaries`, `smite_frp_mount_compose`, or
  `smite_frp_verify_container` for IR Panel, local IR Node, or KH Node.
  Those three host-only actions now run only in the Stable profile.
- An isolated installer regression simulates **no host FRP directory**
  and a no-engine-first-boot on both IR/KH; a separate real
  `docker compose` Node test fails if host FRP preparation or
  injection returns. The Stable regression still proves the original
  download/mount/verify sequence is invoked.
- **Not complete:** unpublished Smite Panel and Node images still
  contain bundled FRP binaries. The current frontend lists all
  engines regardless of installation state. An engine registry,
  per-engine install/uninstall and readiness, Backhaul-only real
  traffic and an independent 443 transport proof remain required.
  Smite management pairing must not silently start an FRP data path.
- No new user-facing step or extra public port is introduced.
  All tunnel engines remain disabled until individually selected and
  verified. This is an offline milestone, not live-host admission.

## Release blockers (must fail closed until all are checked)

1. **Image provenance and supply chain.** The current Docker-save
   artifacts have SHA256 manifests but have not been independently
   attested or published at verified immutable registry digests. Audit
   and pin *all* upstream Docker build downloads before promoting:
   Smite's Node image still fetches Rathole, Gost, Chisel and its
   embedded FRP binaries at build time; Backhaul has a SHA256 check,
   and U-OPTI's mounted FRP has separate hashes. Neither replaces
   end-to-end image provenance.
2. **Secret lifecycle on both hosts.** Perform backup + restore of the
   Panel Fernet master, separate per-Node HMAC identity, 0700/0600
   mounts, atomic persistent replay DB and administrative recovery.
   Exercise revocation, lost-key and failed-pairing rollback without
   revealing key material in logs.
3. **No unapproved public ingress.** Validate actual IR and KH Nginx
   `nginx -t`, correct SNI and hostname-verified 443, private ingress
   secret handling, and *no exposed direct* 8000/8888 control ports.
   Preserve the user's existing FRP/Backhaul/XHTTP locations; prove
   that old `/api/nodes` anonymous registration stays disabled
   throughout clean first boot.
4. **Full two-host lifecycle.** On disposable/snapshotted test hosts,
   install IR once, then KH once, install 3x-UI, securely reserve/pair
   Node identities, create dynamic inbound/ports/paths only afterward,
   and verify FRP, Backhaul and XHTTP real traffic in both directions
   while keeping the single 443 entry.
5. **Operation and recovery.** Demonstrate system reboot persistence,
   gateway certificate renewal, failed Node/Panel startup recovery,
   tunnel error handling, admin lockout/MFA recovery and rollback from
   signed→paused (NEVER signed→legacy) without reinstalling or
   destroying credentials.
6. **Promotion gate.** Review and explicitly approve dependencies,
   provenance, backups and real-host evidence before any merge/tag,
   publish or Stable migration. No automatic upgrade on existing VPS.

## Simple operator-facing sequence when approved

Install IR → install KH → install 3x-UI → reserve/pair securely →
choose dynamic ports/paths → create tunnel → verify connection.

A user should not need to handle HMAC keys, private Nginx includes,
SQLite migrations or advanced cryptographic controls manually.
Until all blockers above are cleared, **do not instruct the operator
to rebuild/install for the RC**.
