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

## Stage 8: real Nginx + verified TLS + Backhaul WS data (CI only)

CI job `sidecar-tls-bridge` uses `tests/test-smite-backhaul-sidecar-tls.sh`
on a GitHub-hosted pull-request runner. The test creates **no published
Docker ports** and connects **no production IR/KH servers or public domain
endpoints**: every container runs on a disposable `docker network --internal`.

- Generates a short-lived test-only root CA and a server certificate whose
  DNS Subject Alternative Name is `ir.kolbe1.ir`. Certificates and the
  token are local, ephemeral artifacts, not uploaded to the repository.
- IR Nginx test vhost terminates HTTPS on Docker-private 443 and forwards
  the generated `location = /channel` and `location ^~ /tunnel/` fragments
  into the isolated Backhaul server (synthetic upstream hostname).
- KH Nginx uses the generated HTTPS bridge fragment, with `proxy_ssl_verify on`,
  `proxy_ssl_server_name on`, `proxy_ssl_name ir.kolbe1.ir`, and a test-specific
  trusted-CA file. The production renderer and production CA bundle are
  **not** altered.
- Good CA with an unauthenticated `/channel` request produces **HTTP 401**
  from the IR Backhaul process, proving the request crossed the TLS bridge.
- Unrelated CA produces **HTTP 502** from KH Nginx, demonstrating a rejected
  upstream TLS handshake instead of insecure fallback.
- With authenticated actual Backhaul WS control and `/tunnel/<random-id>`
  data connections, an HTTP request on IR Backhaul's private data listener
  returns the exact payload from a private mock HTTP service on KH.

CI PASS: https://github.com/aghajani82/u-opti/actions/runs/38371173231

Important scope: test Nginx config includes **generated Backhaul route
fragments**, but uses synthetic test vhosts, certificates and Docker-only
address substitution. It does **not** exercise the live IR stream 443
SNI/Canary routing, the actual backend 8443 include file, external network
filters, Xray XHTTP protocol, or any production deployment and rollback.
The Sidecar remains uninstalled on IR/KH. The next step is a reviewed
production-safe install/rollback design and a strict read-only final host
preflight **before separate explicit approval** for any production changes.

## Isolated IR HTTPS XHTTP location regression (2026-10-13)

CI also exercises the actual **rendered IR XHTTP locations** inside the
disposable TLS Nginx vhost. Both `/56053/www/` and exact `/56053/www` are
requested with verification of a synthetic CA and DNS SAN
`ir.kolbe1.ir`. IR Nginx forwards to its private Backhaul data listener,
and the authenticated WebSocket tunnel reaches a synthetic HTTP service
on KH. The KH mock enforces `Host: kh.kolbe1.ir`, checking the XHTTP
renderer’s Host header rather than merely a generic tunnel endpoint.

Confirmed by CI output:

- `PASS: verified CA produced HTTP 401` (unauthenticated control reaches Backhaul)
- `PASS: wrong CA produced HTTP 502` (KH rejects untrusted upstream)
- `PASS: two Nginx proxies, verified TLS, Backhaul WS data roundtrip`
- `PASS: IR TLS Nginx XHTTP path /56053/www/ -> WS Backhaul -> KH mock`
- `PASS: IR TLS Nginx XHTTP path /56053/www -> WS Backhaul -> KH mock`

CI: https://github.com/aghajani82/u-opti/actions/runs/38373855043

**Scope limit:** This validates HTTP routing, TLS and the underlying WS data
tunnel, not Xray's application-level XHTTP negotiation or real client use.
It does not test the live stream-SNI/FRP Canary rules at public 443,
production certificate, or real IR/KH reachability. No production settings
have been changed and the live install/rollback is still not implemented.

## Stage 8 — strict final-host evidence gate (OFFLINE review only)

`modules/smite-backhaul-sidecar-preflight.py` is a **static reviewer for a
user-provided, sanitized JSON snapshot**. It neither collects live host
state nor runs Docker, Nginx, SSH, network requests, or writes. No snapshot
has been collected from the real IR/KH servers. Its output explicitly says
`NOT AUTHORIZED TO DEPLOY OR MERGE` even when every evidence flag is true.

Each role's snapshot must be younger than 15 minutes, use an offset-aware
timestamp, declare exact Smite `v0.1.7` and Backhaul `v0.7.2` versions,
carry a host-mode listener inventory, and include all role-specific review
flags. Flags are *assertions from an external reviewed collector*, not
proof independently obtained by this script.

The conservative listener check rejects occupied proposed ports, missing
expected service ownership and wildcard/IPv6 conflicts. IR requires
unchanged FRP, Smite Panel/Node, Nginx stream 443, loopback HTTPS 8443,
SNI/Canary routing review, current TLS certificate and a confirmed
nonconflicting candidate include. KH requires unchanged legacy Backhaul
clients and Xray, loopback 56053, remote HTTPS route and certificate
verification evidence. The historical KH baseline is four legacy Backhaul
client configurations (IR zero), and any count change triggers review.

Offline tests: `python3 tests/test-smite-backhaul-sidecar-preflight.py`.

**Next actions requiring fresh user authorization:** build and inspect a
read-only, secret-redacting live snapshot collector; request one command at
a time on IR and KH; manually analyze real Nginx routing and process ownership;
and only then design/review an actual transactional installer/rollback.
No production changes or merge are authorized by this gate.

## Stage 9 — Live-host metadata collector (NOT RUN ON HOSTS)

`modules/smite-backhaul-sidecar-collect.py` is the separately drafted
**read-only evidence collector** for each future host. It has been
reviewed and tested exclusively with mocked inputs in GitHub Actions.
**It has NOT been executed on production IR or KH.** No deployment,
sidecar activation, service restart or production file creation occurred.

The collector has a hardcoded subprocess allowlist:

- `ss -H -l -n -t -p` (kernel TCP listener metadata only).
- `docker inspect --type container --format ... smite-node` /
  `smite-panel` (narrowly selected network mode, running status and mount
  metadata only); `docker container ls --all --format '{{.Names}}'`.
- `os.path.lexists` checks of only the known Sidecar-owned filenames,
  and a **count** of `*.toml` names in the Docker-mounted Smite backhaul
  config directory. It does **not** open or print TOML contents.

The collector never executes `docker exec`, `docker run`, `nginx -t`,
`nginx -T`, Certbot, `systemctl`, or SSH; it does not open a live network
connection, modify permissions or install anything. Python bytecode cache
creation is suppressed. The command is run with `python3 -B` when explicitly
authorized later.

Public/private nonloopback listener IPs are **masked** using constant
documentation-range IPv4/IPv6 placeholders (the literal masked values are
**not actual addresses**). All PIDs, unfamiliar process names and
container names other than own-sidecar collision status are withheld.
Exact loopback and wildcard binding classes are retained because those
matter for port safety. No tokens, passwords, config text, private keys,
certificates, domains from config, or file mount sources are printed.

**Fail-closed by design:** The collector produces the exact snapshot
shape understood by `smite-backhaul-sidecar-preflight.py`, but every
unverified fact stays `null`: runtime versions, TLS validity, SNI/Canary
continuity, Nginx config syntax, legacy tunnel continuity and certificate
state cannot be inferred from only ports/metadata. Consequently the strict
preflight reviewer will **reject a collector-only snapshot** until
additional separately reviewed read-only evidence is obtained. No boolean
is invented merely to make the snapshot pass. A reported `true` only
reflects a narrow observed item, not live deployment readiness.

When and **only when the user separately agrees** to the future
read-only host inspection, the reviewed script will be delivered by a
trusted pinned code path and executed **one host at a time**, clearly
labeled IR or KH. No `curl | bash` install and no execution of an unreviewed
PR module on production. The exact delivery/run method must be reviewed
before use.

The safety regression tests exercise fake `ss`, fake Docker metadata,
anonymization, legacy-config count without file-content reads, missing
process names, port collisions, incomplete evidence and rejection of
disallowed commands. Run on a development machine:

```bash
python3 tests/test-smite-backhaul-sidecar-collect.py
```

**Next blockers before an IR/KH action:** exact code version verification,
manual Nginx vhost/stream ownership review, production-grade atomic
install and real rollback with a fail-closed recovery plan, and explicit
separate user approval. CI success alone is insufficient.

## Stage 10 — journal-first interrupted-install recovery laboratory

`modules/smite-backhaul-sidecar-recovery-lab.py` is a **sandbox-only**
implementation of a fail-closed journal protocol. Its sole writable root
is a private, marker-protected direct child of `/tmp/uopti-bh-sandbox-*`.
It reuses the exact IR/KH Sidecar-owned allowlists and the synthetic Nginx
test hook; it **cannot modify `/etc` on any real host**, and never runs Docker,
systemctl, Nginx, Certbot, SSH or live network operations.

All resource paths in the journal are fixed allowlisted paths,
re-rooted under the synthetic directory. Journal entries store SHA256
hashes but no token or config text. The invented IR backend's prior bytes
are kept separately in a private mock-original backup file. The sequence is:

1. Acquire an exclusive synthetic-directory lock and validate full resource
   scope, non-symlink paths, absent owned candidate files and the preexisting
   synthetic backend.
2. Persist the recovery journal **before** making any resource change, then
   persist the original synthetic backend backup, with parent-directory
   fsync after atomic file replacements.
3. Replace only allowlisted synthetic files one at a time, and retain the
   recovery journal even if all writes complete.
4. On a later, independent call, hash-check **every resource and backup before
   touching any resource**. Fail completely if any hash, path, role, owner or
   source baseline is unexpected. Reverse only exact allowlisted changes.
5. On cleanup, remove the original backup first, and the journal **last**.
   If interrupted during this finalization, a subsequent call recognizes
   fully restored resources and finishes safely without the backup.

Automated tests inject simulated process interruption before any file, after
each synthetic file replacement, during a separate rollback, after journal
creation before backup, and during final metadata cleanup. They also verify
restart/resume, exact original-content restoration, simultaneous-install
refusal, missing backup, modified journal, symlinks and edited-file drift.

Offline test command:

```bash
python3 tests/test-smite-backhaul-sidecar-recovery-lab.py
```

**IMPORTANT LIMITS:** These are simulated termination points, not real
electrical power-loss, kernel crash, filesystem-corruption or network-partition
tests. Filesystem metadata durability depends on OS/storage behavior beyond
the laboratory's model; this code must not be marketed as proven
production-power-loss-safe. It does not update any real Nginx include or
test a production atomic deploy/rollback, and it cannot restore an already
running service's prior in-memory state. An actual production installer,
operational health checks, nginx -t staging, service lifecycle management,
crash-consistent manifest recovery and real-hardware validation must still
be separately designed and explicitly approved before attempting IR/KH.

## Stage 11 — offline-only activation blueprint and backup provenance gate

`modules/smite-backhaul-sidecar-activation-plan.py` produces a **non-executable
review plan** from two independently reviewed IR/KH preflight snapshots,
private generated candidate directories, and two role-specific backup
attestation JSON documents. This module has no installation, service, network,
Nginx, Docker, filesystem-write, backup-creation or rollback execution action.

Key validations before even issuing a review blueprint:

- Both snapshots must pass the strict role-specific preflight verifier,
  including fresh timestamp, version, unchanged baseline and port ownership.
  The actual sanitized collector yields unknown flags; it **cannot pass**
  this gate without separately obtained and verified evidence.
- Stage directories must be owned by the invoking user, non-symlink, private
  and contain precisely the expected artifacts; files must be private,
  regular, reasonably sized and non-symlink. Neither token nor TOML body
  is printed or copied into the blueprint.
- The independently generated IR and KH candidate tokens must match;
  host-network Backhaul must use the expected loopback listeners,
  `transport=ws`, `skip_optz=true` and `web_port=0`.
- Nginx fragments must contain exact `/channel`, prefix `/tunnel/`,
  the expected IR XHTTP routes and KH TLS verification/SNI directives.
  Compose references the previously pinned image digest and has host
  networking, restart disabled, read-only mount and capability restrictions.
- Backup attestations must cover **exactly** the expected IR HTTPS backend,
  IR stream router and KH main Nginx config; the independently verified
  stored-backup SHA256 must match the observed original-file SHA256.
  Any missing, unknown, duplicate, tampered or unverified record blocks.
- Generated output contains only fixed allowlisted file paths, SHA256 hashes
  and manual review order. It never emits live execution commands and
  always states `REVIEW_ONLY_NO_DEPLOYMENT_AUTHORIZATION`.

Offline tests (`tests/test-smite-backhaul-sidecar-activation-plan.py`)
exercise valid **synthetic** evidence, stale/missing review, occupied
ports, legacy count drift, mismatched or missing backup digests, unsafe
TOML/Nginx/Compose changes, symlinked or public candidate files,
and confirmation that no secret appears in CLI output.

**Important distinction:** The hash-only backup attestation is not a
file backup, proof of off-host durability or proof of restoreability.
This tool does not inspect the live Nginx stream SNI exceptions or install
anything on IR/KH, and does not implement an executable production rollback.
All such work requires future independently reviewed evidence, a genuine
transactional installer and explicit approval for any host mutation.
