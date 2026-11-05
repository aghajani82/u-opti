# Issue #102 — Signed Backhaul host review (no live install)

Status: **READ ONLY / INSTALL_ALLOWED=NO / ACTIVATION_GATE=HOLD**

This is the current first gate for **Backhaul beside existing FRP**, not a
production installer or authorization to restart/recreate the RC7 Node.

## What changed

The existing `Independent Engines → Backhaul → 2 Review installation prerequisites`
may now receive independently sourced, cryptographically verified **paired
Smite registry image** evidence. No existing menu choices, Docker processes,
network routes, tunnels, Xray clients, or installed files are modified by this
review.

It reuses the existing
`modules/smite-registry-pair-admission.py:verify_pair()` verifier, which
enforces exact externally reviewed manifest SHA-256, immutable Smite source SHA,
exact signed release tag, Cosign OIDC publisher workflow identity,
signed node/panel roles and image digests. It does not automatically trust
`docker inspect`, image labels, GHCR tags, a local file alone, or the old
RC2 candidate. Cosign verification can read GHCR/Sigstore but **never**
installs or pulls the image.

## How the existing review accepts provenance

When a **genuinely independently reviewed signed pair** is available and the
operator has separate proof of the *exact* file hash/source/tag, the existing
read-only option accepts the following *optional environment variables*:

| Variable | Value / boundary |
|---|---|
| `SMITE_BH_PAIR_MANIFEST` | Local non-symlink JSON candidate, supplied by approved release review |
| `SMITE_BH_PAIR_SHA256` | Independently reviewed SHA256 of those exact bytes, not computed as proof from the same untrusted file |
| `SMITE_BH_PAIR_SOURCE_SHA` | Independently reviewed 40-character Smite source commit |
| `SMITE_BH_PAIR_PUBLISH_REF` | Exact signed `refs/tags/v...` release identity |
| `SMITE_BH_PAIR_TRUSTED_ROOT` | Optional trust-root file; existing verifier checks its reviewed SHA pin |

Provide all four required fields **in the environment of the U-OPTI process**,
then open the normal Backhaul review option 2. Alternatively, the existing
`smite-managed-engine-host-admission.py` read-only CLI accepts matching
`--signed-pair-*` arguments. No changes to server config files or launch
scripts are required.

**Do not invent these values, copy a digest from live Docker, reuse the old
RC2 sample as an RC7 proof, substitute a local image ID, or set the proof
flags based on a green CI run.** If current runtime has no suitable signed pair
release evidence, the correct result remains
`REASON=EXPECTED_NODE_DIGEST_REQUIRED` and `INSTALL_ALLOWED=NO`.

On valid Cosign proof **and** matching runtime image reference, the report
can set `SIGNED_REGISTRY_PAIR_PROOF=COSIGN_VERIFIED`; this proves only the
pair of registry references, **not** that running container bytes,
persistent replay ledger, FRP owner/child state, or prior tunnels have been
attested. Consequently `NODE_RUNTIME_BYTES_AND_REPLAY=UNVERIFIED`,
`HOST_TRANSACTION_AND_ROLLBACK=NOT_IMPLEMENTED`,
`INSTALL_ALLOWED=NO`, and `ACTIVATION_GATE=HOLD` remain unchanged.

A mismatch or incomplete proof returns a redacted fail-closed reason:
`INCOMPLETE_SIGNED_PAIR_PROOF`, `SIGNED_PAIR_PROOF_INVALID`,
`SIGNED_PAIR_IMAGE_PIN_CONFLICT`, or `NODE_IMAGE_DIGEST_MISMATCH`.
No secrets, UUIDs, tokens, full Compose files or signatures are emitted.

## Privacy-safe local preservation receipts (incremental Issue #102)

The **existing** Backhaul host review also reports two optional read-only,
local-only comparison receipts when it can validate the source:

- `SAVED_TUNNEL_REGISTRY_SHA256` / `PERSISTED_TUNNEL_REGISTRY_SHA256`:
  SHA-256 of the **exact** validated `tunnels.json` bytes, after the
  existing strict JSON/schema/ownership check. `ABSENT` means the file is
  missing, not a verified empty registry; a present `{}` produces the hash
  of those exact two bytes. Invalid, symlinked or oversized records report
  `UNVERIFIED` and the preflight remains HOLD.
- `NODE_CONTAINER_ID_SHA256`: SHA-256 of the validated 64-hex Docker
  container ID read from the *existing* `docker inspect` result. Missing,
  non-hex or malformed IDs remain `UNVERIFIED`, never guessed.

Neither raw Docker ID nor raw tunnel names, ports, paths, token/spec values,
secrets, environment, or image payloads are printed. These hashes are **not
signed attestations** and do **not** prove that a tunnel is reachable or
FRPS owners/children are healthy. They are local change-detection references
for a later **independently approved** before/after comparison. A comparison
must detect a missing or unverified receipt as HOLD, not as zero tunnels.
A stable hash alone cannot prove that a container was never restarted.

No new menu option or standalone installer is provided. Existing
`Independent Engines → Backhaul → Review installation prerequisites`
continues to return `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD` and
`REASON=SAVED_TUNNELS_PRESENT` for IR with existing tunnels. CI must
simulate mismatched container identity, modified stored tunnel bytes and
corrupt/private registry before this can be merged.

## IR FRP / Broker / WSS local continuity hints — read-only

The existing Backhaul option 2 report now includes **best-effort local hints**,
never live process/service health claims or restart authority:

- `FRPC_PROCESS_LOCAL`, `FRPS_PROCESS_LOCAL`: `OBSERVED_UNATTESTED`,
  `NOT_OBSERVED`, or `UNVERIFIED`. Only exact kernel `/proc/PID/comm`
  process names are read (no arguments, environment, open FDs or secrets).
  `FRPC_INSTANCE_SHA256` and `FRPS_INSTANCE_SHA256` hash sorted PID + kernel
  starttime pairs, so a changed process can be detected locally. A missing
  process is **not** proof that a tunnel is down; a matching name does not
  prove it belongs to the reviewed FRPS Owner.
- `BROKER_SOCKET_LOCAL` / `BROKER_SOCKET_ID_SHA256` (IR only): inspect
  the fixed `/run/u-opti/smite/xhttp-broker.sock` pathname and its parent.
  A root-owned `0660` socket with the expected dedicated nonzero GID
  and `0750` parent yields `PRESENT_UNATTESTED` and a hash of dev+inode.
  This does **not** connect to the socket or prove it accepts requests.
  Invalid ownership/type/mode is `UNTRUSTED`; missing is `ABSENT`.
- `WSS_EDGE_JOURNAL_LOCAL` / `WSS_EDGE_JOURNAL_SHA256` (IR only):
  hash exact strict root-owned `0600` committed RC7 WSS Edge journal bytes;
  duplicate JSON keys, malformed ownership/state and symlinks cannot claim
  `COMMITTED_LOCAL_UNATTESTED`. No peer IP or TLS secret is printed. The
  journal is **not** proof of currently healthy TLS/443.

These hints are intentionally reported beside saved-tunnel hard HOLD; they
are only inputs for later **independently authorized** before/after checks,
not a signed FRP owner/child inventory, Broker connectivity proof, WSS
end-to-end test, provider snapshot or a replacement for existing signed
health/replay probes. A changed hash is a reason for HOLD, never an automatic
restore/restart. On non-IR roles Broker/WSS fields remain `UNVERIFIED`.
No new menu entry, login UI, installation mechanism or daemon is added.

## IR offline before/after preservation comparison (Issue #102 increment)

`smite-managed-engine-host-admission.py` now exposes an **internal, pure,
non-installing** helper `compare_ir_local_preservation(before, after)`.
It accepts two separately obtained **untrusted** sanitized host review
dictionaries and returns **only** fixed allowlisted status/reason codes. The
current menu, CLI behavior, installation gates, Docker and live runtime are
unchanged. It does not read the host, network or command arguments.

For this deliberately narrow IR-with-active-FRP scenario, both reports must
describe a reviewed running managed-strict IR Node; independently supplied
Cosign-verified signed-pair status; preserved saved tunnels; locally enrolled
but still **unverified** FRP; an observed local FRPS process; an intact root
Broker socket and committed WSS edge journal; and explicitly
`INSTALL_ALLOWED=NO` / `ACTIVATION_GATE=HOLD`. Each local SHA-256 must
be a strict 64-character lowercase hex digest; missing, malformed or
`UNVERIFIED` values fail closed. The FRPC process may legitimately be
absent on IR, but `NOT_OBSERVED` must be paired with `ABSENT` in both
reports. The comparator rejects changes to:

- exact persisted tunnel registry bytes;
- `smite-node` container identity (so a recreated Node cannot silently pass);
- the local FRPC/FRPS process instance pairings;
- Broker socket device/inode identity;
- RC7 WSS edge journal bytes.

Any incomplete or changed evidence yields `PRESERVATION_LOCAL=HOLD` with
a redacted fixed reason. When all matching local hints are present it returns
`PRESERVATION_LOCAL=MATCH_UNATTESTED` and
`PRESERVATION_REASON=LOCAL_HASHES_MATCH_NOT_SIGNED_HEALTH` — deliberately
**not** `PASS`, `READY`, or approval. Every return **always** contains
`SIGNED_RUNTIME_CONTINUITY=NOT_PROVEN`,
`BACKHAUL_HOST_TRANSACTION=NOT_AUTHORIZED`,
`INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`.

**Security boundary:** local report dictionaries, even when their
`SIGNED_REGISTRY_PAIR_PROOF` fields say `COSIGN_VERIFIED`, are not
authenticated by this comparison helper. The helper cannot independently
prove the release signature, running FRPS Owner/Child mapping, health,
signed replay, Broker listener responsiveness, WSS/443 availability,
continuous forwarding (zero interruption), rollback or externally verified
snapshots. A matching hash may still coexist with a short service outage.
Production decisions require independently verified live before/after signed
evidence and explicit operator recovery/rollback approval on **both** hosts.
No new install or automated recovery path is enabled.

## RC7 independently signed FRPS Owner listener verification (incremental)

The existing `smite-rc7-frp-enrollment.py` RC7 lifecycle module has a new
**read-only diagnostic action** `verify-owner --role ir`, separate from
`verify` because a fresh enrolled FRP engine need not have any owner yet.

For an already COMMITTED **IR** enrollment it first revalidates the exact
protected WSS runtime, Node image, root-owned enrollment journal/engine
manifest and pinned frpc/frps binary digests. It then performs the existing
signed HMAC/replay health check and signed `/api/agent/engines` inventory
check. **Only after those pass**, the same existing signed Node identity
creates a fresh anti-replay nonce and sends a signed GET to the existing Smite
Agent `/api/agent/frp/owners` endpoint on `127.0.0.1:8888` **inside the
reviewed Node container**. The request uses no proxy and refuses redirects.
No new Smite API or secrets are exposed.

The current Smite endpoint validates the single tracked server-mode FRPS
process, its matching PID, and a local `127.0.0.1:7000` TCP LISTEN socket.
The host side requires an exact, bounded, duplicate-key-free response with
one Owner, control port 7000, and a strictly typed, sorted, unique,
bounded list of locally observed proxy listener ports. Any missing, multiple,
malformed or inconsistent Owner leads to HOLD, not an invented success.
The output is **only**:

```text
RC7_SIGNED_FRPS_OWNER_VERIFY=PASS_SIGNED_LISTENER
FRPS_CHILD_FORWARDING=NOT_PROVEN
LIVE_CONFIG_CHANGES=NONE
```

On a failed probe, the result is a sanitized `HOLD: ...` and no raw Owner ID,
FRPS token, child specification, peer address or signed HTTP response is
printed. The signed GET **does consume a nonce in the durable Replay store**
but does not alter FRP, Node, Nginx, the Broker or any tunnel. No docker
restart/recreate, no new public port, no installation side effects. The
existing plain `verify` behavior remains unchanged and works on pre-Owner
enrollment. This diagnostic is not exposed as a new installer/menu item.

**Important distinction:** proving the IR Owner and its local listeners is
not proving live foreign FRPC children, individual child/port grants,
end-to-end XHTTP over WSS/443, zero disconnection, continuous forwarding,
safe Backhaul coexistence, or rollback. Separate authenticated Panel/foreign
node child inventories, an independent trusted baseline and a disposable
real shared-WSS transaction test are still required. `INSTALL_ALLOWED=NO`
and `ACTIVATION_GATE=HOLD` stay mandatory for existing FRP tunnels.
This diagnostic is not a request to execute any command on IR or Grandoptical.

## RC7 bundled-FRP compatibility in the existing Backhaul offline preparer

The Backhaul v0.7.2 **offline stage** originally assumed that every enrolled
FRP engine supplies two external read-only host binary mounts. RC7 has a
different, already-reviewed layout: the signed `smite-node` image itself
bundles both pinned `frpc` and `frps`, with **no** FRP binary bind mounts.

The existing `smite-managed-backhaul.py` candidate preparer now distinguishes
the two formats without migrating or touching the running Node:

- The legacy externally mounted FRP branch still demands **both** readonly
  frpc/frps mounts, private executable files and matching recorded SHA256.
  A partial, writable, corrupted or mixed mount remains HOLD; no fallback.
- An RC7 image-bundled FRP branch is admitted **for offline candidate
  preparation only** if the existing manifest pins both engine binary
  digests, the reviewed base Node Compose has a **fixed
  `ghcr.io/aghajani82/smite-node@sha256:<digest>` reference**, and the
  existing RC7 enrollment helper's private root-owned journal is COMMITTED
  for the exact IR or foreign role, with journal-manifest digest binding.
  An absent, incomplete, misbound or invalid journal fails closed. No
  candidate is prepared on an unknown/mutable Node image.
- The preparer preserves original FRP manifest entries byte-for-byte in the
  candidate, writes only within the private staging directory, and adds
  **only** an inert Backhaul binary/manifest/Compose-overlay proposal.
  There is no FRP binary reinstall, engine re-enrollment, Node recreation,
  FRPS restart, Nginx change or tunnel creation.

This is **local enrollment proof**, not signed live runtime approval. The
separately reviewed RC7 `verify --role` and `verify-owner --role ir` still
have distinct duties; neither locally generated candidate nor a green
offline test can prove live FRPC Child reachability, snapshot availability,
two-host recovery, or uninterrupted service.

The Backhaul form's `3080` is a *future tunnel control port setting*;
offline candidate preparation **never binds/opens 3080**, uses no public
ports, and does not assert its availability. Public port/path collision
checks belong to the later independently authorized tunnel publication.

**Production status unchanged:** the existing host executor still uses
`docker compose --force-recreate` in its disposable test lane and the
live IR has saved FRP tunnels. Neither this fix nor a successful stage
can lift `SAVED_TUNNELS=EXISTING_DO_NOT_RESTART`,
`INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`, or the requirement
for explicit operator signoff after verified two-host recovery.

## Production blockers still OPEN — do not bypass

- Actual IR/Grandoptical running Node digest and complete signed RC7 runtime
  inventory must be checked independently; two-host operator approval required.
- `SAVED_TUNNELS=EXISTING_DO_NOT_RESTART` is a **hard HOLD**. Three current
  FRP tunnels (`20182`, `optical`, `nahavi`) must remain unchanged.
  `SAVED_TUNNELS=UNKNOWN` means no observation, **not zero tunnels**.
- Existing `smite-managed-backhaul-host-executor.py` is **disposable-host
  test only** and requires `SAVED_TUNNELS=ZERO`; it may force-recreate
  `smite-node`. Do not call it, relax the guard, or adapt Sidecar test-host
  markers for the live servers.
- An explicitly proved real-host transaction still needs independent backup
  and recovery-console proof for **both** hosts, byte-exact FRP owner/child,
  signed Node health + replay, Broker socket, 443/TLS and rollback
  before/after, plus isolated real shared-WSS regression.
- No Backhaul public port/XHTTP inbound or Nginx route should be created
  until all these gates pass and the operator approves the deployment.

The PR changes only this read-only signed-provenance bridge and negative/positive
CI tests. **It is not acceptance of Issue #102 as complete.**
