# Stage 9 — Smite Node Docker signed-auth candidate (NOT ACTIVE)

**Status: PREPARE ONLY / DRAFT. DO NOT deploy, activate, or merge as a
complete Smite security release.** This branch follows the Stage 8
authenticated gateway-check U-OPTI draft and the stacked Smite draft PRs.

## Problem this stage addresses

The **real upstream Node Compose** mounts `./config:/etc/smite-node`,
`node-data:/var/lib/smite-node` and currently healthchecks
`GET /api/agent/status` *without authentication*. After enabling strict
Agent HMAC, this healthcheck would return HTTP 401, falsely marking
healthy Nodes as failed. The currently pinned Node Docker image also
cannot be assumed to contain the new authenticated Agent/Panel client
code until a checked build or verified code overlay is deployed.

**For that reason, Stage 9 does not restart or reconfigure Docker.**

## Offline preparation

`modules/smite-node-auth-candidate.py` verifies:

- U-OPTI saved Smite state is Standard mode with approved IR/KH role;
  Private mode is HOLD and **is not silently converted** to Standard.
- Existing Node Compose has exactly one Smite Node service, host-network
  layout and U-OPTI's hardened `127.0.0.1:8888` Uvicorn command.
- Existing pairing identity is a regular, current-root-owned 0600 JSON
  file beneath a root-owned 0700 directory. Its UUID and key syntax
  are checked but the secret is **never printed**.
- The replay directory is persistent (not /tmp), under private 0700
  host directories. It is *not* overlaid over the entire existing
  `node-data` volume.

With explicit confirmation it writes an **inert, standalone** overlay
alongside the real Node Compose:
`/opt/smite-node/docker-compose.security-candidate.yml` (0600).

The candidate defines a future strict/signed Node configuration:
- Identity directory mounted **read-only** at
  `/run/smite-node-identity`, configured via
  `SMITE_AGENT_IDENTITY_PATH`.
- Replay directory mounted read/write at
  `/var/lib/smite-node/auth`, configured via
  `SMITE_AGENT_REPLAY_DB`.
- Strict `SMITE_AGENT_AUTH_MODE=strict` and signed
  `SMITE_NODE_PANEL_AUTH_MODE=signed` (in candidate **only**).
- Minimal unauthenticated root `GET /` Docker healthcheck, which
  reports service liveness but no tunnel inventory or secrets.
  Actual signed control-plane health requires independent testing.

**Important:** The security candidate is NOT included in the current
Docker Compose command, NOT activated, and cannot secure a live Node on its
own. This project intentionally contains **no automated activation action**
in Stage 9. Never run `docker compose ... up` with this file until the
later coordinated activation playbook and image compatibility checks exist.

## Wizard and rollback

The existing standalone `u-opti --smite-pairing` preview menu gains:
- Option 4: read-only preflight.
- Option 5: type PREPARE-AUTH-ONLY to prepare private Replay and a
  non-applied candidate (no restart).
- Option 6: type DISCARD-CANDIDATE to delete ONLY an unchanged generated
  candidate. Never deletes the identity, replay data, original Compose,
  .env, original images, FRP/Backhaul settings or containers.

The original primary Docker/Smite menu and FRP/Backhaul wizards are
unchanged; fresh install and update manifests include the new helper.

## Remaining production blockers

1. Build and pin matching Smite Panel and Node images containing all
   security code (don't assume upstream pinned `0.1.7` contains it).
2. Review and integrate U-OPTI's bind-mounted `/opt/u-opti-smite/panel/main.py`,
   Node `panel_client.py`, `core_adapters.py` overlays. Those mounts may
   shadow updated code from the images, including router activation.
3. Confirm service UID/GID in both images supports **root-owned** secret
   0600 reads and SQLite writes, or provide a carefully scoped equivalent
   credential-mount design. Never loosen file permissions globally.
4. Prepare Panel Fernet master/SQLite migrations securely and coordinate
   encrypted per-Node secret lookup, revocation and backups. Complete
   the Panel→Node signed client and Node→Panel signed registration switches.
5. Verify Nginx/443 proxy forwards signed paths without unexpected
   rewriting, does not publish ports 8000/8888, and properly injects
   protected Pairing ingress proof on only the allowed endpoint.
6. Clarify actual FRP/Backhaul control/proxy routes and all signed
   status callers. Real end-to-end client traffic must pass both ways.
7. Add an **explicitly reviewed activation / rollback** procedure:
   backup/snapshot first, one server at a time, compare signed and legacy
   status, no silent security downgrade, watch real traffic and reboot.
8. Private Network mode remains separate and is intentionally blocked.

## Tests

`tests/test-smite-node-auth-candidate.py` verifies strict/legacy isolation,
private permissions, safe replay persistence, no candidate overwrite,
no data loss on discard, no mutation to the original Compose, refusal
of unsafe/symlinked identity and private mode, and packaging/menu entry.

**No commands need to be run on IR/KH during this GitHub-only stage.**
