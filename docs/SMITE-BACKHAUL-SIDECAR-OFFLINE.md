# Independent Backhaul Sidecar — OFFLINE CANDIDATE ONLY

Scope: independent Backhaul v0.7.2 without replacing or restarting the existing Smite Panel/Node, four legacy KH Backhaul TCP clients or production FRP. The user has approved offline development only, **not live activation**.

## Verified facts

- Both IR and KH `smite-node` use Docker host networking. No Sidecar has been started.
- IR Nginx public 443 is stream with SNI and a Canary map; the default chain reaches the TLS HTTP backend on loopback 8443. The existing exceptions must remain intact.
- IR HTTPS 8443 backend has two direct locations and a separate include adding two more. A read-only preliminary check found no direct collision with the proposed routes. This is **not** a deployment-safe Nginx ownership proof.
- KH Sanaei Xray: 127.0.0.1:56053, XHTTP path /56053/www/, Host kh.kolbe1.ir.
- IR 3080 currently has no listener or Docker-published port; four existing KH Backhaul TCP clients still target public IR:3080 and were observed SYN-SENT. They must **not** be deleted/restarted merely because disconnected.
- Backhaul v0.7.2 uses **exact `/channel`** for control, but `tunnelDialer()` supplies `/tunnel` to `WebSocketDialer()`, which appends `/<random-id>`. The actual data URI is **`/tunnel/<random-id>`** and Nginx must use `location ^~ /tunnel/` on both IR and KH. Sources: https://github.com/Musixal/Backhaul/blob/v0.7.2/internal/client/transport/ws.go and https://github.com/Musixal/Backhaul/blob/v0.7.2/internal/utils/network/ws_dialer.go
- The server WS source supports `127.0.0.1:56053=127.0.0.1:56053`, preserving loopback data bind. Source: https://github.com/Musixal/Backhaul/blob/v0.7.2/internal/server/transport/ws.go

## Candidate-only flow

IR: independent server with WS control/data on loopback 127.0.0.1:3080, listening on loopback 127.0.0.1:56053 for XHTTP forwarded to KH.
KH: independent client WS connects to KH Nginx loopback 127.0.0.1:13080, whose upstream is verified HTTPS to ir.kolbe1.ir:443; KH Xray stays on loopback 56053.
IR HTTP backend 8443 would eventually include two fixed WS paths plus /56053/www/. The stream 443 and its two existing maps require no designed change. No such includes have been installed.

## Offline generator

File: `modules/smite-backhaul-sidecar.py`.

- Reads only an existing regular mode-0600 token file; rejects symlinks and short or unsafe tokens. The token must be the **same** on IR and KH candidates and must never be committed.
- Emits only a new private random directory in `/tmp/uopti-backhaul-sidecar-*`, including 0600 TOML, `.candidate.yaml` Compose reference, Nginx preview fragment(s) and `NOT-INSTALLED.txt`. It does not modify live files, invoke Docker, or reload Nginx.
- IR TOML uses `[server]` and WS loopback:3080 plus loopback port mapping; KH TOML uses `[client]` and WS loopback:13080.
- The Compose candidate uses `network_mode: host`, `restart: "no"`, pinned Smite Node image digest known to include Backhaul 0.7.2, a distinct container name, and an **unprovisioned** `/etc/u-opti/backhaul-sidecar/<role>.toml` bind source. It must not be run directly. A minimal Backhaul-only image remains a future optional improvement pending digest/version verification.
- The Sidecar does not need the separately staged Smite Panel/Node Python overlays; stage 1-4 remain separate experimental paths.

On a development machine or CI, **not IR or KH**, create a random secret in a mode-0600 file using secure tools and share it securely between candidate-generation runs. Then:

    python3 modules/smite-backhaul-sidecar.py --role ir --token-file /tmp/my-private-sidecar-token
    python3 modules/smite-backhaul-sidecar.py --role kh --token-file /tmp/my-private-sidecar-token
    python3 tests/test-smite-backhaul-sidecar.py
    bash tests/test-smite-backhaul-standard.sh

The commands only produce temporary candidate files and run offline tests. Do not paste the secret or commit any emitted private TOML.

## Explicit blockers before activation

1. Inventory all service/container/network-namespace owners for IR 3080, IR 56053, KH 13080, KH 56053; verify there are no wildcard bind collisions or transient listeners.
2. Audit actual Nginx HTTP include insertion points and all exact/prefix/regex location priorities, including Stream SNI/Canary exceptions. Validate candidate configs using `nginx -t` in an isolated namespace before review.
3. Verify actual Sidecar binary/entrypoint/version in the pinned digest independently; do not assume the image works as an isolated runtime merely because it includes `backhaul -v`.
4. Design atomic creation of secret/Config/Compose/Nginx paths and a genuine **live** rollback that restores precise originals and never touches Smite or FRP.
5. Before rollout, verify reverse proxy TLS validation, WebSocket upgrades for exact `/channel` and prefix `/tunnel/<random-id>`, and all client pool traffic over verified KH bridge.
6. Require **separate user approval** before starting a container, creating any network route, changing a service, deploying configs, or touching production.
7. Test authenticated end-to-end XHTTP, health checks, reconnect, restore, cert renewal and sequential reboots. Do not merge PR to main before these and explicit approval.

## Source audit and revised Compose safety (offline)

At upstream Smite v0.1.7, `node/Dockerfile` explicitly builds Backhaul v0.7.2
and copies its executable into `/usr/local/bin/backhaul`:
https://github.com/zZedix/Smite/blob/v0.1.7/node/Dockerfile .
The candidate now uses this absolute entrypoint and Compose long-syntax bind
mount with `bind.create_host_path: false` so a nonexistent host config is not
silently created as a directory. **Important:** this proves upstream Dockerfile
intent, not the binary or entrypoint inside the exact live image digest. An
independent digest/runtime verification remains mandatory before activation.

## Strict offline port-conflict audit

`modules/smite-backhaul-sidecar-audit.py` reads a **user-supplied** JSON
listener snapshot (it never scans a server). It requires host networking,
IR's existing Nginx 443 + loopback 8443 and FRPS loopback 7000, or KH's
existing loopback Xray 56053; it rejects any occupied proposed new listener
port on *any* IP interface (IR 3080 and 56053; KH 13080), malformed snapshots,
duplicate entries, or missing expected service owners. This is conservative:
even binding an unrelated IP on the same port causes a review blocker.

Example simulated IR snapshot, with no actual service discovery:

```json
{
  "role": "ir",
  "network_mode": "host",
  "listeners": [
    {"address":"0.0.0.0","port":443,"owner":"nginx"},
    {"address":"127.0.0.1","port":8443,"owner":"nginx"},
    {"address":"127.0.0.1","port":7000,"owner":"frps"}
  ]
}
```

Run offline: `python3 modules/smite-backhaul-sidecar-audit.py --role ir --snapshot ./inventory-ir.json`.
PASS means only that the supplied static snapshot met structural expectations;
it does NOT prove a live server is unchanged or activate any service.

## Rollback safety model (NOT an executable live rollback)

`modules/smite-backhaul-sidecar-rollback.py` validates an offline JSON
manifest with an exact allowlist of candidate-owned resources per role and a
separate simulated observed-state JSON. New Sidecar TOML, Compose, Nginx include
fragments and KH bridge config can only be removed when their recorded
`applied_sha256` matches the observed file's digest. The sole IR existing-file
edit contemplated is `/etc/nginx/conf.d/u-opti-smite-panel-backend.conf`, and
it requires a matching backed-up original `before_sha256` and `backup_sha256`.

Any unknown path, changed checksum, missing backup, incomplete manifest or
unexpected container identity fails closed. Only the specifically named
`uopti-backhaul-sidecar-ir` or `uopti-backhaul-sidecar-kh` would ever be in
scope for a future authorized container stop. Smite containers, Smite backhaul
configs, FRP processes, Xray and the Nginx stream router are NEVER rollback
targets. The current script **does not remove files, restore backups,
stop containers or reload Nginx**; it prints hypothetical operations only.

Actual activation and reversal still require a separately reviewed and approved
transactional installer with pre-change backups, atomic file ownership and
safe Nginx config validation. There is **no approved live rollback yet**.

Offline regression commands:

```bash
python3 tests/test-smite-backhaul-sidecar-audit.py
python3 tests/test-smite-backhaul-sidecar-rollback.py
```

**Production IR and KH remain untouched; PR #18 remains a draft.**

## GitHub-hosted image and Compose smoke test (2026-10-13)

CI workflow `.github/workflows/ci.yml` includes a dedicated
`sidecar-image-smoke` job on a GitHub-hosted `ubuntu-latest` runner.

- `docker compose ... config --quiet` succeeded for **both** independent IR
  and KH candidate Compose files generated using a temporary test-only token.
- `docker pull --platform linux/amd64` fetched the explicitly pinned
  `ghcr.io/zzedix/smite-node` image digest.
- `docker run --rm --network none --read-only --cap-drop ALL` ran **only**
  `/usr/local/bin/backhaul -v`, which printed **`v0.7.2`**.
- No live IR/KH server was accessed, and no real tunnel service was started.

Successful job: https://github.com/aghajani82/u-opti/actions/runs/38366411281

This clears the pinned-image binary existence/version and Compose syntax
questions, **not** the following: actual WS/TLS traffic, Nginx runtime
integration, host port ownership at the instant of deployment, or any
executable installer/rollback transaction. Sidecar remains NOT INSTALLED.

## Stage 6: synthetic file transaction and rollback (offline-only)

`modules/smite-backhaul-sidecar-sandbox.py` now performs a **real write and
reversal of candidate files only inside a specially marked private
`/tmp/uopti-bh-sandbox-*` directory**. The sandbox requires an exact
`OFFLINE MOCK ONLY` marker and refuses other roots, symlinks, unknown
paths and any role outside IR/KH. It does not run a container, inspect live
ports or execute Nginx. Host `/etc` is NEVER used; all `/etc/...`
resource paths are re-rooted under the synthetic temporary directory.

Test fixture uses an invented Nginx 8443 backend with a deliberately unique
`# UOPTI_SIDECAR_TEST_HOOK` marker. There is no such assumed marker in the
real host config, and the offline simulator must NEVER be pointed at IR/KH.
Simulation applies candidate TOML, Compose and Nginx fragments as private
files using per-file atomic replacement, records an exact SHA256 manifest,
saves the original synthetic backend, then checks the rollback allowlist
and reverses the transaction with a content-identical restoration.

Regression tests cover both roles, failure injection at every file-write
step, second-install refusal, symlinked parent directory refusal, drift
detection (rollback must stop without overwriting an altered file), exact
restoration of synthetic prior state and retained isolation. CI runs:

    python3 tests/test-smite-backhaul-sidecar-sandbox.py

**This is NOT a production installer or a production rollback mechanism.**
In particular, it does not cover a power loss during the commit/rollback,
production Nginx include editing, service ownership, or any real container
lifecycle. A separately approved installation transaction and production
backups must be designed and reviewed before testing on live servers.

## Stage 7: live WS process/HTTP roundtrip on GitHub-hosted private network

CI job `sidecar-ws-transport` runs **real Backhaul v0.7.2 server and client
processes** from the pinned image digest, **only** on GitHub's disposable runner
with an internal Docker network, no published ports and no live IR/KH access.
It generates both TOML configs with a one-use 64-hex-character token; strictly
for this container-to-container test, its synthetic copy changes IR bind to
container-only `0.0.0.0:3080`, data listener to container-only
`0.0.0.0:56053` and KH remote to the Docker-internal IR name.
Production Sidecar candidates **remain loopback-only**.

The KH container also runs a temporary Python HTTP endpoint bound to its own
loopback `127.0.0.1:56053`; the IR container requests
`http://127.0.0.1:56053/health` over the Backhaul data listener and receives
exactly `uopti-isolated-ws-roundtrip-ok`. This confirms authentic WS control
and data traffic in a hermetic Docker environment, **not** the public
TLS bridge, Nginx stream/HTTP routing or Xray authentication.

The source audit also found that Backhaul's default `skip_optz=false` tries
to update **host TCP sysctl settings**; the Sidecar generator now writes
`skip_optz = true` for both roles, with regression assertions. The container
test uses the GitHub runner's UID to read mode-0600 private bind-mounted
TOML while dropping all Linux capabilities. All test containers and networks
are removed on completion or failure.

Successful CI including real isolated traffic:
https://github.com/aghajani82/u-opti/actions/runs/38369512541

**No production deployment or end-to-end IR↔KH tunnel has taken place.**
Next blockers: reproduce the final two-Nginx verified-TLS WS bridge entirely
in a sandbox; implement and separately review a true production-safe install
and rollback. Require explicit user approval before any host action.
