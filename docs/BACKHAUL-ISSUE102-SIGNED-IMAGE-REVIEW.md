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

## Explicit no-recreate protection for active/enrolled FRP — all executor actions

The pre-existing disposable-host Backhaul transaction executor still uses
`docker compose up --force-recreate smite-node` to mount the Backhaul binary.
That approach **cannot** be accepted on IR/KH where signed RC7 FRP and
existing tunnels must survive. Issue #102 remains unresolved until a
separately reviewed **no-Node-recreation** architecture and two-host recovery
are proved.

The existing executor now adds a strict **fail-closed FRP guard** on all
potential Node recreation paths: install, explicit rollback, interrupted
recovery, and immediately before each `--force-recreate` subprocess.
Before altering the private transaction journal or any Node file in
rollback/recovery, it checks:

- journaled previous manifest and current manifest for enrolled FRP,
  rejecting duplicate keys, malformed schema and all unknown entries;
- the read-only host `/proc` FRPC/FRPS process observation and its
  footprint. Both must report `NOT_OBSERVED` and `ABSENT`; an observed,
  unreadable or inconsistent process inventory causes HOLD;
- saved active tunnels still independently block the existing admission.

If FRP is enrolled, reject with
`ENROLLED_FRP_NODE_RECREATE_FORBIDDEN`. If FRPC/FRPS is present or its
presence cannot be determined, reject with
`FRP_PROCESS_PRESENCE_OR_UNVERIFIED`. Missing or suspect manifest fails
closed with `FRP_RECREATE_MANIFEST_UNTRUSTED`. No automatic cleanup,
restart, stop, rollback or removal is attempted to work around HOLD.
These checks also prevent a previously prepared crash/rollback journal from
recreating an FRP Node when production FRP was enabled later.

**Boundary:** the proc scan and local manifest cannot prove continuous
network forwarding and have possible external timing races. They are
**negative safety gates**, not independent signed runtime attestations.
A successful no-FRP test-host run must still satisfy signed Node replay,
official archive provenance and operator-approved recovery prerequisites.

Most importantly, this fix **does not install Backhaul into an active FRP
Node** or change the Smite Panel's truthful `Engine not ready on both nodes`
message. An independently verified, non-disruptive topology must be designed
and tested before authorizing any Backhaul installation on Grandoptical/IR.

## RC7 image-bundled Backhaul: signed read-only no-recreate feasibility check

A review of the **exact Smite RC7 source** at
`9a1270b31e8d44f13d09b71ab6b9798410b09c12` confirms that the
Node Dockerfile's final stage copies the officially SHA-256-pinned
Backhaul v0.7.2 binary to `/usr/local/bin/backhaul`. The existing
Smite Node signed engine inventory, however, only reports `ready`
when the protected `/etc/smite-node/engine-state/engines.json`
manifest contains a matching binary SHA256. Having the executable
bundled is **not** an engine enrollment or runtime readiness proof.

The **existing** `smite-managed-backhaul-control.py` now offers a
separate opt-in *read-only* `verify-rc7-bundle --role ir|foreign`
preflight; it is not a new installer or menu item. It:

1. Checks the existing committed, reviewed RC7 WSS/443 runtime journal,
   protected Compose/runtime and pinned Node image via the existing RC7
   verification helper. Confirms the requested IR/foreign role and
   denies external mounts covering the Backhaul binary or its parents.
2. Executes only a bounded, root-owned, executable/no-writable-modes
   `/usr/local/bin/backhaul` binary SHA-256 audit **inside the existing
   smite-node** without changing the executable.
3. Runs the existing signed Node HMAC/replay health probe and a fresh
   signed `GET /api/agent/engines` on Node loopback with no proxy,
   redirect or arbitrary destination. Requires `frp=ready`,
   `backhaul=not-installed` and strict managed inventory schema.
   Consumes one durable replay nonce; no service, tunnel, binary, or
   configuration changes.
4. Returns **only fixed nonsecret status codes** and
   `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`. No raw hash,
   secrets, Node ID, process ID, tunnel specs or ingress address is printed.
   Invalid/mismatched evidence is a fixed HOLD.

### Official Backhaul executable pinning for this same read-only gate

The reviewed RC7 bundle audit previously required only a correctly formatted
SHA-256 digest for `/usr/local/bin/backhaul`. That did **not** reject a
different executable on the inspected Node. PR #121 derives the official
**extracted executable** SHA-256 separately for `amd64` and `arm64` by
rechecking each already-pinned Backhaul v0.7.2 release tarball with the
existing strict archive verifier in isolated GitHub PR CI. These are distinct
from the archive digests and now reside next to the existing archive pins
in `smite-managed-backhaul.py`.

The opt-in `verify-rc7-bundle` preflight audits the actual architecture
**inside the running container**, the exact regular-file executable
bytes, and compares them with the corresponding reviewed official binary
digest. An unsupported architecture, wrong architecture/digest pair,
unexpected JSON shape, or a syntactically valid but nonofficial digest
now fails closed *before* evaluating a multi-engine enrollment candidate.
No binary bytes or expected SHA-256 are disclosed in preflight output;
only the fixed status `RC7_BACKHAUL_BINARY_PIN=OFFICIAL_V0_7_2_ARCH_EXACT_MATCH`
may appear when the check succeeds.

This is a **byte-provenance check, not a signed image attestation** or
permission to install. It does not change any container, Nginx/443, FRP
record, active tunnel, or signed Node replay identity.

As an additional **read-only gate**, this same opt-in preflight now,
under the existing RC7 host engine lock, reads the *actual private*
`engines.json` and FRP enrollment `record.json` paths, checks duplicate-key
rejection and requires the existing RC7 verifier to accept the committed
receipt, binary digests and exact manifest binding. It runs the already
reviewed pure in-memory Backhaul-only pair planner with the observed bundled
binary digest, rejects any manifest/receipt drift on re-read, and outputs
only `RC7_FRP_RECEIPT_BINDING=COMMITTED_EXACT_MANIFEST_REVIEWED` and
`RC7_BACKHAUL_MANIFEST_PLAN=CANDIDATE_ONLY_NO_WRITE` on success. No new
menu action, network destination or live write is enabled. The private
candidate bytes and digest values are never printed. Corrupt/partial,
wrong-role, duplicate-field, mismatched FRP pin or out-of-band changed
receipts fail closed.

This does **not** independently verify the Cosign registry signature in
this action, prove the live image's build provenance, guarantee that
the API responses are signed back to the caller, establish uninterrupted
forwarding, or authorize host registration. Even the positive probe only
confirms a binary exists in a *reviewed running image*, the existing
signed Agent request/replay path works, and Backhaul is **not yet
enrolled**. It does not change the Panel UI; the message
`Engine not ready on both nodes` remains accurate.

The next separately reviewed milestone is an **exact manifest-only,
journaled and recoverable** engine enrollment in the existing mounted
Node config. It must avoid Docker Compose recreation, preserve FRP
Owner/Child, Broker/WSS and replay identity, and prove after/rollback
signed inventory on **both** test hosts before any real-host approval.
No use of `docker cp`, runtime binary injection, sidecar readiness
spoofing, or active FRP replacement is allowed.

## Critical RC7 multi-engine receipt blocker: exact manifest / FRP journal binding

The **already committed** RC7 FRP enrollment's protected `record.json` has
`new=sha256(original engines.json bytes)`, and the existing FRP `verify`
requires an **exact** SHA256 match against the **whole** running
`engines.json`. Although the pinned RC7 image already bundles Backhaul,
**writing just a new Backhaul manifest entry would immediately make FRP's
`verify` return `ENROLLMENT_MANIFEST_DRIFT`**. No amount of positive
Backhaul binary inventory checks makes that safe.

The existing Backhaul controller now has a **pure in-memory, non-installing**
`plan_rc7_backhaul_manifest_pair(existing_manifest, frp_journal,
bundled_backhaul_sha256, role=...)` helper. It accepts only a small
duplicate-key-free, strict, 8192-byte-or-less engine manifest with
existing `frp` digests; requires the exact known RC7 FRP journal
`COMMITTED`, matching role, two pinned binary digests, valid `old`,
and `journal.new == sha256(exact original manifest bytes)`. It prepares
a deterministic candidate manifest which retains every existing engine
record and inserts only the proposed Backhaul binary digest, plus
two SHA256 **planning receipts**. It does **not** read paths, access
Docker/network, change files, or enable any menu/host action.

Even if candidate construction succeeds:
- `RC7_BACKHAUL_MANIFEST_PLAN=CANDIDATE_ONLY`;
- `RC7_FRP_RECEIPT_REBIND=ATOMIC_TRANSACTION_REQUIRED`;
- `MANIFEST_WRITTEN=NO`, `FRP_JOURNAL_WRITTEN=NO`;
- `INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`.

The helper returns the digest data **to internal callers only**; neither
the menu nor any production command calls it or prints sensitive
engine records. These receipt hashes do not attest live signed health,
preserve uptime or grant authorization.

**Mandatory next transaction design:** under the shared host engine lock,
freeze a separately authenticated FRP Owner/Child and Broker/WSS baseline,
back up the exact `engines.json` and FRP `record.json` bytes to private
durable storage, and coordinate the manifest update with the FRP
journal's expected `new` digest through a fully versioned,
interruption-safe two-resource transaction. At *every* crash boundary,
an independent recovery path must restore/validate **both** previous
receipts without changing existing FRP tunnels, signing identity or
FRPS processes. Neither overwriting FRP's receipt in isolation nor
relaxing `smite-rc7-frp-enrollment.py verify_file` is acceptable.
A separately reviewed full two-host RC7-like disposable test is
required before any production activation.

## RC7 two-receipt crash/recovery rehearsal — disposable GitHub PR lab ONLY

The existing `smite-managed-backhaul-transaction.py` CI-only lab now
supports two **internal Python functions**:
`rc7_pair_apply_lab(root, backhaul_sha256, role=..., inject=...)` and
`rc7_pair_recover_lab(root)`. Neither is available via the public
installer/menu/CLI. The existing disposable PR root marker, private directory
checks and CI-only admission are mandatory before any filesystem access.

The rehearsal mirrors the two relevant *bytes-on-disk* resources inside the
temporary test root: `node/config/engine-state/engines.json` and
`rc7-frp-enrollment/record.json`. The second location is **not** the real
production FRP journal path. Both inputs must be private regular `0600`
files. The existing strict in-memory planner is reused to bind the exact
pre-change Manifest SHA256 and the COMMITTED FRP receipt's role and pinned
binary digests. The candidate retains all FRP and unrelated engine entries
and introduces only the SHA-pinned Backhaul entry.

The two internal pair-lab entry points now take the **same nonblocking,
caller-owned private `.smite-engine-transaction.lock`** used by existing
`control.exercise` in the disposable PR root. Both apply and recovery hold
this one lock for the full operation and fail closed if it is already held,
symlinked or has unsafe file permissions. The lock inode is never unlinked.
This is PR-lab serialization only: it does **not** prove production-wide
coordination with the RC7 enrollment writer, signed Node or Docker runtime.

The rehearsal records **exact old and new bytes of both files** plus their
SHA256 values in a private, fsync-backed journal *before any source write*.
It then atomically replaces each file separately with directory fsync.
Synthetic crashes at `after-journal`, `after-manifest`, and
`after-receipt` leave a recoverable record. Recovery first validates every
saved byte, private mode and hash, then validates **both** current resources
against only their allowlisted old/new bytes. Any unknown external edit or
incomplete/tampered journal fails closed **before any restore**. Only then
does recovery restore both source files byte-for-byte, verify them, and
remove the lab journal.

Recovery now reuses the original pure RC7 pair planner to recompute the
*exact* permitted candidate Manifest and derived FRP receipt from the saved
pre-change bytes, before restoring anything. Four individually correct
SHA-256 checksums are insufficient if the saved receipt binds a different
Manifest, role, FRP binary digest or unrelated engine entry. A mismatch
leaves both current files and the private recovery journal untouched with
`RC7_PAIR_RECOVERY_SEMANTIC_DRIFT`. Regression tests also recompute the
checksums of altered backup parts to ensure this is not merely a hash test.
This consistency proof does **not** authenticate the lab journal against an
attacker with write access, nor prove signed real-host FRP provenance.

### Rollback can also be interrupted — resumable CI rehearsal

A crash during **recovery itself** is independent of the three existing
Apply interruption points. The same internal, CI-only
`rc7_pair_recover_lab` now has synthetic fault injection after restoring
the original Manifest, after restoring the original FRP receipt, and after
both are byte-for-byte verified but **before** journal cleanup. Each
subsequent invocation reopens and validates the complete private four-part
journal, recomputes the exact permitted FRP/Backhaul transition and checks
the current sources belong to the old/next allowlist **before another
restore**. Tests cover both `ir` and `foreign` receipt roles, repeated
interruption, an out-of-band edit between attempts, exact unchanged
Compose/.env, and restoration of both original FRP and unrelated engine
entries. Unknown drift retains the journal and refuses further writes.

This also closes the **partial journal-deletion crash** gap in the
**disposable CI lab only**. The existing recovery first verifies the full
four-file journal, both original resources and the precise FRP receipt
semantics. Before deleting the first journal file it creates and fsyncs a
root-private `rc7-pair-recovery-complete.json` terminal seal, containing
only the role, original/next digests and the reviewed Backhaul binary
digest. Recovery can resume even if the journal has only a subset of its
files or has already been removed: it requires the original Manifest and
FRP receipt exact bytes by SHA-256, recomputes the allowed transition with
the existing pure planner, verifies each surviving journal part and refuses
unexpected paths, symlinks, unsafe file modes and drift **before unlink**.
The terminal seal remains until the journal directory has been removed
and fsynced, so the independent legacy lab cannot start while cleanup is
pending. The latest tests inject crashes after persisting the seal, after
each of five file removals, and after journal-directory removal, on **both**
IR and foreign roles; repeated restart and tampering are fail-closed.
The terminal seal is **not signed** and cannot defend against a privileged
attacker controlling the complete private PR-lab root.

This does **not** prove live two-host signed Owner/Child continuity,
concurrent external FRP verifiers at every intermediate write, production
receipt migration, provider snapshots, or a production-capable recovery
CLI. All fault-injection arguments are Python-internal and require the
existing PR lab admission; the beginner menu and production activation
remain HOLD.

The legacy disposable Backhaul file transaction and this RC7 pair
rehearsal use distinct recovery journals but share the same test-root
Manifest. They now **fail closed in both directions** whenever the opposite
journal exists (including unfinished/corrupt journals or symlinks), even
when no operation is currently holding the shared flock. Direct legacy
lab `activate`/`rollback` entries now also acquire that same lock;
`control.exercise` retains its outer lock and calls the internal
already-locked functions. The tests cover lock contention, both interrupted
journal directions, unchanged data on refusal, and clean recovery. No
automatic deletion of a competing journal is allowed. This is entirely
**disposable-PR-lab coordination** and does not qualify live RC7 migration.

**Critical limitation:** two independent file replacements are NOT one
atomic transaction. Between writes, RC7 FRP's existing verify may properly
report an inconsistency. Successful byte restoration does NOT prove
uninterrupted FRPS Owner/Child forwarding, signed replay, Broker/WSS health
or correct Provider snapshot/console. The test is **not** a real
`smite-node` engine install or an authorization to rewrite a production FRP
enrollment record. No Docker, live Nginx, Panel, tunnel, port 3080, or
systemd command is issued, and the lab never touches real
`/opt/smite-node` or `/var/lib/u-opti` production resources.

The legacy Backhaul disposable engine transaction remains separate; its
`--force-recreate` host executor must never be used when signed FRP or
saved tunnels are present. Future work must add a separately reviewed
**production-capable**, interruption-safe state machine that preserves
existing FRP signed provenance (without weakening `verify_file`),
shared lock, signed pre/post Owner and foreign Child inventories, explicit
rollback/recovery, snapshots/console and no interruption proof across
a disposable two-host RC7 WSS topology. The system continues to report
`INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`; there is no live enrollment
switch in this PR.

## Two-host RC7 no-recreate orchestration — disposable paired lab ONLY

The existing internal transaction code now has an additional **CI-only
Python entry** `rc7_two_host_rehearsal_lab(ir_root, foreign_root,
backhaul_sha256, observe=..., inject=...)` (not exposed by a menu or CLI).
It requires **two distinct PR-runner private roots**, each containing an
exactly bound, role-specific `COMMITTED` RC7 FRP receipt/Manifest pair.
It takes and holds **both existing shared engine locks** in deterministic
IR → foreign order, checks **both role receipts and the baseline** before
mutating either root, and rejects pending recovery journals or completion
seals. Active saved-tunnel identities are represented in the test by
synthetic immutable owner/child data for `20182`, `optical` and `nahavi`.
Broker/replay and Node Compose/.env are synthetic protected byte fixtures,
not real live runtime observations.

In the isolated test it applies the exact reviewed Manifest/receipt
transition to IR, observes a synthetic phase, applies to foreign, observes
again, and **always** recovers both roots in reverse order under the same
two engine locks. It verifies the exact original FRP/other engine receipts
and protected bytes again after recovery. A simulated failure after IR,
during the foreign receipt transition, after both transitions, or from a
negative synthetic observation must either produce an **exact two-host
rollback** or **HOLD with recovery journals retained for manual inspection**
when independent protected evidence has drifted. Both roles are tested.
The module itself invokes **no** Docker, Compose restart, FRPS, network,
Nginx, signed Agent API or credential exchange. Neither fixture indicates
live Owner/Child or packet-forwarding continuity; the result explicitly
reports `SIGNED_OWNER_CHILD_CONTINUITY=NOT_PROVEN`, as well as
`INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`.

This review narrows the two-host coordination/test gap without claiming
a distributed atomic commit, a real authenticated owner/child probe or
a production-safe live installer. A **real isolated two-host RC7 WSS
topology with real signed health and forwarding checks before/during/after**
remains required, followed by real-host transaction design and independent
operator approval. The existing force-recreate disposable host executor
is not reused for active FRP environments.

## Two live, disposable Smite Nodes + FRP TCP — private GitHub CI ONLY

The existing `managed-backhaul-official-artifact` PR job now additionally
exercises a **real pinned Smite Node API in two Docker containers** with
distinct persistent private signed identities and Replay DBs. The containers
share a *Docker internal-only bridge*, with no published host ports, host
networking, external Panel, live IR or Grandoptical connection. Official
SHA-256 pinned FRP 0.71.0 `frpc`/`frps` and Backhaul v0.7.2 binaries
are mounted read-only from validated archives. The foreign container runs
an isolated local TCP echo service, FRPC connects to FRPS on the IR
container, and a fresh challenge must travel end-to-end over TCP port
20182 **inside the private network** at each review boundary. This is
not the production tunnel identified by that port number.

The paired lab's observation callback makes real signed HMAC GET requests
to both running Node API services, requires `frp=ready` and the expected
Backhaul `not-installed` / `ready` inventory states, checks unauthorized
and replayed requests fail with 401, verifies Node status, confirms the TCP
forwarding still passes, and independently compares both Docker IDs and
`StartedAt` fields to prove **no Node container recreation or restart**
during the filesystem transition. The same checks occur before, after the
IR receipt transition, after both transitions, and after exact rollback;
another pass injects a crash during foreign manifest replacement and
requires compensated recovery while the existing real FRP forwarding and
both Node API processes persist.

The **actual FRPS processes are launched inside disposable Docker containers**,
and the genuine signed Node API and durable Replay data are used. This
narrows the gap left by #124's synthetic callback: HMAC, Replay, real
FRP 0.71.0 control and private TCP forwarding are observed in CI. Still,
the artificial `node-data` Owner/Child/Broker fixtures consumed by the
internal lab coordinator are not signed; **the CI tests do not prove
production WSS-over-443, external Owner/Child API claims, Nginx/Sanaei
coexistence, XHTTP Bridge, Broker socket continuity, real stored tunnels,
provider snapshots/console recovery, or a deployment-ready transaction**.
The original `INSTALL_ALLOWED=NO` and `ACTIVATION_GATE=HOLD` remain
mandatory and no live installation entry is enabled.

## Real private WSS/TLS/443 — two signed Nodes without recreation (CI ONLY)

The existing PR-only pinned-official-artifact job now extends its real
two-Node FRP 0.71.0 test: a **third disposable Nginx TLS container** is
built from the repository's existing FRP WSS lab Dockerfile and joins the
same Docker **internal-only** bridge. There are **no host published ports**.
The IR Node still runs real FRPS bound to the isolated bridge (internal
7000). The foreign Node's real FRPC uses `transport.protocol=wss` and
connects to the Nginx sidecar on **443 inside Docker**; Nginx proxies the
FRP Upgrade path `/~!frp` to the IR FRPS. The temporary CA is provisioned
inside the private foreign fixture, with real TLS certificate and hostname
checking (positive test and a negative *same-address* wrong-SNI test).

At the same four stages as the existing #125 test, and at rollback after
a deliberately interrupted foreign Manifest replacement, the CI checks:
- genuine signed HMAC inventory/status on **both** running Smite Nodes,
  including refused unsigned and replayed requests;
- real TCP challenge crossing **FRPC -> WSS/TLS/443 -> Nginx -> FRPS**
  and returning through the same foreign echo endpoint;
- CA/hostname TLS validation, no published Docker host ports, and the
  exact unchanged container IDs and StartedAt timestamps on both Nodes
  **and** the Nginx sidecar;
- exact original FRP receipt and Manifest bytes after two-host recovery.

The Nginx test uses an ephemeral self-signed CA and its own new private
container, **not** the live RC7 shared Nginx configuration, production
domain, Sanaei service or public network. Synthetic broker and
Owner/Child fixtures still are *not* signed management evidence. A
positive result explicitly **does not** prove public WSS/443 coexistence,
foreign peer source restrictions, Broker socket/XHTTP continuity, live
signed Owner/Child route state, saved tunnel availability through every
instant or deployment safety. The existing host authorization remains
`INSTALL_ALLOWED=NO` / `ACTIVATION_GATE=HOLD`; keep Issue #102 open.

### Cross-Node signed identity negative proof during real WSS/FRP test

The real two-Node PR-only WSS/TLS 443 and FRP 0.71.0 forwarding lane now
also issues a **valid HMAC request signed with this Node's own ephemeral
key but claiming the other CI Node's ID**. The actual signed Node endpoint
must return HTTP 401 before accepting the correct own-identity signed
request. This is enforced in every before/after-IR/after-both/rollback
probe, including the injected foreign transaction failure and recovery.
The persistent actual Node identity/replay binding cannot be mistaken
for interchangeable two-host credentials. Failed cross-role identity
does not authorize an engine operation or restart any Node.

A signed `/api/agent/engines` result is **not** a signed FRPS Owner/Child
runtime proof: the isolated FRPS/FRPC processes are started outside
Smite's production tracked-owner workflow. Broker/XHTTP signed runtime
continuity and true Owner/Child proof remain separate mandatory gates.
This test does not unlock real-host installation.

## Signed tracked FRPS Owner: real loopback process and API (PR CI only)

The older pinned Smite source used by the existing dual-Node WSS/443
forwarding test does **not** contain the actual signed
`GET /api/agent/frp/owners` route. The full CI suite may pass while
claiming only signed **engine availability**, never tracked Owner
health. To close this gap without silently changing the existing WSS
experiment's source/image, the same PR-only official-artifact job now
checks out a **separately immutable** reviewed Smite RC7 source
(`115f032761564a069d0aa2ca891e55d53a1c6ea0`) and executes its
real Agent Owner router, strict HMAC, persistent SQLite Replay and
`frp_owner_status.active_signed_frps_owners` inside a throwaway,
`--network none` Docker container. FRPS **v0.71.0 is the exact
SHA-pinned official executable** extracted earlier in that job, and
runs as a *real tracked process* listening on `127.0.0.1:7000`.

The read-only signed endpoint must return exactly one owner only when
its adapter's tracked process PID owns that loopback LISTEN socket;
unsigned, bad HMAC, an opposite Node ID and repeated nonce must be
rejected. Wrong PID, client-mode config, missing tracked adapter and
terminated real FRPS must produce an empty Owner set, even with a
well-formed valid signature. The response never prints FRP tokens,
Node secrets or owner private data. This **does not** exercise the
production AdapterManager's actual FRP start operation: its
in-memory manager entries are synthetic, but the signed endpoint,
HMAC/Replay implementation and PID/socket are genuine.

This is narrower than a two-host **tracked** Owner/Child management
trial. The separate existing isolated WSS test still starts FRPS and
FRPC outside Smite's tracked adapter, and there remains **no signed
foreign-Child route proof, no genuine Broker/XHTTP socket continuity,
no real-host attestation or production-safe receipt migration**.
Passing this test cannot change `INSTALL_ALLOWED=NO` or
`ACTIVATION_GATE=HOLD`. Do not deploy Backhaul on IR/Grandoptical.

## Signed managed Foreign Child over real CI WSS — existing Agent apply

The existing two-Node private WSS/TLS/443 trial previously launched
the foreign `frpc` with `docker exec -d`; this checked live packet
forwarding, but **never exercised Smite's real signed FRP child
creation/restore tracking or saved tunnel state**. It could not prove
the existing Node's actual signed FRP Child management route.

The existing official-artifact PR job now reuses its already checked-out
immutable Smite `115f032761564a069d0aa2ca891e55d53a1c6ea0`
(which implements strict shared-FRPS WSS preflight) **for the foreign
Node only**, without changing the signed IR or image digest. The
ephemeral Nginx gateway retains its private port 443 and obtains an
additional private dotted DNS alias `ci-uopti-wss.local`; its temporary
CA cert explicitly covers both names. That CA is mounted read-only
as the disposable foreign Node's system trust bundle. The existing
foreign echo service stays on loopback.

**Version-bound replay identity:** the newer signed Smite source requires
an independently authenticated `key_binding` in its strict Replay
enrollment marker. The first paired CI experiment had provisioned both
roles with the older Smite bootstrap while running the newer foreign
Agent; that correctly failed closed at signed API preflight. The CI now
provisions the foreign role using the **same SHA-pinned newer Smite
source** that later authenticates its requests. The IR role retains
its older SHA-pinned bootstrap. No marker is rewritten after boot,
no nonce or key is reset, and production enrollment migration still
requires separate review.

Instead of starting `frpc` outside Smite, the test makes one **actual
strict HMAC-signed POST** to the foreign Node's existing
`/api/agent/tunnels/apply` for one disposable
`mode=client` / `shared_frps_owner=ci-owner` child. Smite's
real `AdapterManager` invokes its real `FrpAdapter.apply`,
validates WSS/443 and starts FRPC 0.71.0 with a private token.
During every stage of the RC7 Manifest + FRP receipt pair apply and
rollback, the test now requires a **real signed GET** on the
existing `/api/agent/tunnels/status` to report active FRP; an
unsigned GET, cross-node signed identity and reused nonce must 401.
It independently proves a unique FRPC process with the exact reviewed
command-line has an **ESTABLISHED TCP connection to the private TLS
gateway on 443**, its PID and create-time remain unchanged, the
durable `tunnels.json` remains byte-identical and an actual TCP
payload still traverses `FRPC -> private Nginx WSS/443 -> FRPS`.

This replaces the previous **untracked foreign client** proof, not
production deployment. The IR `frps` remains externally launched
within the disposable container; the separately verified #128
signed-tracked Owner endpoint uses an isolated live loopback FRPS,
**not** a simultaneous shared real two-host tracked owner.
It does not prove an actual public 443 gateway, XHTTP/Broker inode
health, foreign Sanaei client service, live saved tunnels or a safe
production transaction. `INSTALL_ALLOWED=NO` and
`ACTIVATION_GATE=HOLD` remain required. No real IR/Grandoptical,
user proxy or FRP configuration is modified.

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
