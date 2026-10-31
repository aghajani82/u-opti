# Stage15: no-Node-restart approval evidence boundary (design review only)

**Status: BLOCKED for deployment.** This file is a concrete compatibility and
threat-model decision record, not an authorization to build, enable or expose a
new host service. No changes to IR/KH runtime, Nginx, Signed Pairing or FRP.

## Verified constraint (2026-10-31)

Current IR and KH `smite-node` image:
`sha256:cf0f3b12fc2c31cb0847fd5206304837661019d8f604853a8e956448c2576265`.
The new Smite PR #41 `POST /api/agent/approval/evidence` handler and its
Ed25519 signer are **inside the new Node image**, not available in the old
image. U-OPTI `smite-stage15-live-evidence.py` requires independently pinned,
fresh, separately signed IR owner and KH Sanaei inbound evidence; it cannot
grant based on the Panel API, a stale inventory export, or just an IR-root
signature pretending to be a Node signature.

Three existing child routes are 45121 (/45121/www), 38658 (/38658/shop)
and 28897 (/28897/blog). IR has a single FRPS process belonging to
`smite-node` (not `smite-panel`); KH has three FRPC processes belonging
to `smite-node`. Recreating either Node can interrupt all three tunnels.

The Panel Compose graph on IR contains only `smite-panel` and no
`depends_on`; Panel-only maintenance is a **separate** risk boundary. This
fact does not make any Node recreation non-disruptive.

## Choice A — preserve zero Node restarts (preferred until further review)

An optional, *newly reviewed* host-local evidence adapter would run outside
the existing containers. Such an adapter cannot be assumed safe just because
its prototype can read `ss`, `docker inspect` or Sanaei SQLite. The existing
`collect()` verifier expects Node-origin identity and cryptographic signatures.
A safe replacement needs an explicit *new* provenance/audience contract,
signed per-host root keys (distinct IR and KH), and a corresponding Root verifier
update. Do not reuse Node public-key pins or claim these are Node-signed
attestations.

Minimum proof boundaries before any code can be admitted:

1. IR Root derives an owner ID and exact socket set from the live container's
   immutable host PID/start time, its trusted persistent registry and the
   single FRPS owner process. Every 7000/45121/38658/28897 listener must belong
   to that one process, be loopback-only, and be tied to the expected live
   owner/child leases. No evidence from untrusted JSON or Panel response alone.
2. KH Root uses only the authoritative Sanaei `x-ui.db` read-only transaction,
   including the current WAL sidecars, plus local socket inspection and the
   exact FRPC/Node namespace. A single enabled VLESS/XHTTP `127.0.0.1` port
   with the exact path is required. No client UUIDs or secrets are exported.
3. The IR and KH host attestations have independent pinned Ed25519 identities,
   explicit host provenance, a fresh nonce and <=30-second expiry. Root validates
   cryptographic origin, port/path, runtime generation and a durable replay
   ledger **before** issuing a new grant.
4. Data transport is local Root-only AF_UNIX; any KH external access must be
   separately pinned HTTPS/443 behind its reviewed Nginx path and narrowly
   authorized HTTP handling. Never add an unauthenticated public endpoint,
   root shell bridge, mutable latest image, insecure TLS override or
   automatic retries of ambiguous intent.
5. Any unknown Node, process restart, container ID, inode, WAL visibility,
   lease, proxy port, origin, key, clock or replay state => HOLD, no grant.
   Keep existing TrustedGrants and routes untouched. Root-only signers are
   not allowed to write Sanaei DB, Panel DB, FRPS/FRPC, Node identity or keys.
6. Offline tests must validate the existing EvidenceHold behavior and
   injected mismatches, forged signatures, stale copies/nonce replays,
   duplicate owners/inbounds and failure after durable approval; an isolated
   two-host clone must demonstrate all three original client paths stay up.
7. The initial adapter deployment itself (new services/keys/TLS config) needs
   explicit approval, independently validated snapshots and reversible
   setup; do not enable Web Approval merely because a host is reachable.

**Until those gates are implemented and audited, no usable host adapter
exists, and `LIVE_MIGRATION_AUTHORIZED=NO`.** In particular, do not
modify `smite-stage15-live-evidence.py` to trust local unsigned facts.

## Offline host-origin signature prototype (2026-10-31, NOT DEPLOYABLE)

`modules/smite-stage15-host-evidence-offline.py` and
`tests/test-smite-stage15-host-evidence-offline.py` define a separate
**offline-only** Ed25519 host-origin envelope, NOT a Node-signed proof.
The distinct `u-opti:stage15:host-review-evidence:offline-v1` audience,
`ir_host` / `kh_host` roles, independent pins and exact runtime-generation
fields prevent a host fixture from being confused with the existing Node
attestation verifier. The offline verifier checks 30-second expiry, signature,
binding, independent keys and provided consumed nonces. Synthetic negative tests
cover signature alteration, wrong pins, stale and replayed proofs, mismatched
path/port/owner, invalid FRPS listeners and missing KH inventory facts.

**This prototype accepts caller-supplied test facts and has no live observer,
no trusted process/registry or SQLite/WAL source, no server or transport, no
persistent anti-replay ledger, and no independent host root keys.** It cannot
authenticate real IR/KH runtime and must not be wired into the Root grant
writer or the Web Approval service. Returning an in-memory set of used nonces
does not provide durability. Until separately reviewed collectors, key
management, authenticated transport, durable replay and isolated clone E2E
are implemented, the host route is `HOLD`.

The current Node verifier and production signer were **not modified**;
the previous requirement for genuine Node-signed proofs remains fail-closed.
The existing live host's three FRP tunnels remain out of scope of the test.

## KH read-only runtime observation prototype (2026-10-31; offline CI only)

The source-only library `modules/smite-stage15-kh-host-observer.py` now
separately examines Docker's actual `smite-node` / `3xui-01` metadata,
the expected single Xray process and exact loopback listener, and three
existing FRPC processes, then reads Sanaei SQLite `inbounds` through a
new read-only transaction including WAL visibility. It returns only
sanitized XHTTP port/path, process generation/container identity and a hash
of the sanitized inbound view. Tests use a **temporary** SQLite database
and injected `docker inspect`, `docker top`, `ss` and `/proc` results;
they do not contact IR or KH. No raw UUID, config, password or database
is exported. It does not make signed evidence or provision a grant.

The current prototype deliberately permits only a pinned
`3xui-01` mount at `/etc/x-ui` and source `x-ui.db`, which must be verified
against the real KH Compose/Docker mount layout **before** any host trial;
unknown layouts HOLD. The current three-process FRPC requirement is a
**baseline-only** gate: a fourth tunnel may require a new reviewed expected
process count/lease reconciliation and must not be deployed with this
hardcoded three-child assertion. Identifying a mounted SQLite source does
not itself establish that it is up-to-date or authoritative; a separate
controlled freshness/recovery check and full observer audit are required.
Observations are not cryptographic Node proofs.

**Still absent:** an independently observed IR owner/registry binding,
host-key enrollment and trusted transport, durable nonce receipt, a
reviewed root host-origin verifier, real IR/KH mount/lease inventory and a
disposable-clone end-to-end rehearsal. The Root Web Approval launcher and
its existing Node-signed evidence contract are unchanged. Zero service
restarts is a design requirement, **not** a tested live result.

## IR read-only FRPS owner observation (2026-10-31; offline CI only)

`modules/smite-stage15-ir-host-observer.py` and
`tests/test-smite-stage15-ir-host-observer.py` now exercise a separate
IR observer against mocked Docker/host/process state and a temporary
owner registry. This library requires the pinned current Node image, one
healthy live `smite-node`, its exact Docker volume, one FRPS process
and four loopback sockets on 7000, 45121, 38658 and 28897 owned by
the same PID; it records Linux process start ticks, immutable container
ID and a SHA256 of the registry. It never starts, stops, recreates,
signs or publishes anything. The cross-host offline fixture test pairs
its sanitized IR facts with synthetic KH host facts through the
separate, **non-production** host-origin Ed25519 verifier. The old
Node-signed verifier still rejects those host-origin fixtures.

**Source format verified, live host not yet verified:** Smite's
`node/app/core_adapters.py` at the previously deployed Stage15 source
`8edbd4032ae657fe2bb38cd9b3290de5f1e07a54` and Smite PR #41
both use `AdapterManager._save_tunnels()` to persist the top-level
`{tunnel_id: {"core": core, "spec": spec}}` mapping directly to
`/var/lib/smite-node/tunnels.json`. There is **no** outer `"tunnels"`
wrapper. The earlier offline observer incorrectly assumed one and
would HOLD on legitimate persisted data. The corrected strict parser and
`tests/test-smite-stage15-ir-registry-lease-offline.py` now use the actual
source-defined structure, reject the wrapper, and combine one local
FRPS owner fixture with a *separate* authoritative Panel SQLite owner,
child and unique `frp_proxy_leases` fixture. Tests reject wrong owner,
stale/inactive Panel rows, missing or wrong child leases, wrong port and
mismatched Node identities. A KH-managed child may have no key in IR's
locally persisted registry; its lease lives in Panel SQLite.

**IR live observation (read-only, 2026-10-31):** The operator verified
that `smite-node-data` mounted at `/var/lib/smite-node` holds a flat
`tunnels.json` with exactly one persisted FRP server whose `spec.mode`
is `server` and `spec.bind_port` is 7000. Its **actual key is a UUID**,
not the human-facing `FRP-IR-KH-45121` alias previously hardcoded
in the offline observer. The observer now requires an explicit pinned
`owner_id`; it never guesses it from a display name. A missing/mismatched
Panel lease still HOLDS. The operator audit did **not** independently
verify the matching Panel `tunnels.id`, the `frp_proxy_leases.owner_tunnel_id`,
the Node's cryptographic identity, or real client traffic. It does **not**
prove that an IR registry entry is an authoritative active child lease,
nor that a given child is linked to the FRPS Owner. The `node_id`
input is not independently pinned to a trusted root identity yet.
Before any future host-based signing or Web Approval, review the
actual in-container registry format, compare it with the authoritative
Panel SQLite live leases in an atomic read boundary, review the real
IR/KH mount paths, and implement durable nonce receipts. All unknown,
stale or competing observations must HOLD. No runnable live adapter,
secret key provisioning, network listener or grant integration exists.

## IR owner Panel/Node mode compatibility (operator-verified 2026-10-31)

Further read-only IR audits confirmed that the UUID-keyed Node registry
contains exactly one `frp` owner with `spec.mode="server"` and
`spec.bind_port=7000`; the Panel stores the same UUID as an active
FRP tunnel, with two linked child leases at 28897 and 38658. The Panel
owner's `spec` **omits** the `mode` key, but its `bind_port` is
the **integer** 7000 (not a string). This is compatible with Smite's
`panel/app/routers/tunnels.py` flow: Panel persists the operator
spec and creates a separate Node `server_spec` whose mode is set to
`server` before the signed apply.

The earlier ad-hoc read-only audit reported
`OWNER_SERVER_7000=False` solely because it required
`Panel.spec.mode == "server"`, a condition NOT enforced by the
underlying `smite-stage15-live-evidence.py::_lease`. That report was a
**false HOLD due to an over-strict diagnostic**, not evidence the FRPS
listener or child lease was broken.

To prevent regression, `_lease` now accepts *only* absent
`Panel.spec.mode` or an explicit `"server"` mode, while still requiring
the exact integer control port `7000`, unique active owner/child records,
matching IR/KH identities, owner UUID and child lease association, and
a fresh coherent read-only SQLite transaction. Explicit `"client"`,
`null`, or any other mode and malformed/missing/wrong bind port HOLD
closed. The **Node registry still independently requires**
`spec.mode="server"`, and the live FRPS PID/listener checks are unchanged.
These changes do not authorize Web Approval or a fourth tunnel.

## Three-route lease schema and uniqueness guard (2026-10-31)

Offline regression fixtures now cover the **direct** owner route
`45121 /45121/www` (no child lease) and the two **shared** child routes
`38658 /38658/shop` and `28897 /28897/blog` (one child lease per
`iran_node_id,remote_port`) as three distinct admission cases for the
same UUID-identified FRPS owner. The IR Node's flat registry contains
only that owner; never invent child registry entries to make the tests
pass. An extra lease for the direct port or a mismatched child-owner
association fails closed. These are synthetic fixtures only and do not
prove real client connectivity or the future fourth route.

The live `_lease` verifier previously checked the necessary columns and
matching lease row but did **not actually verify the unique index**, despite
saying it did. It now requires a non-partial SQLite UNIQUE index whose
key columns are exactly `(iran_node_id,remote_port)`, read as part
of the existing read-only transaction. Missing, partial, or incorrectly
keyed indexes cause `LEASE_UNIQUE_INDEX_MISSING` without schema
migration or writes. This matches Smite's `FrpProxyLease` model
`uq_frp_ir_remote_port`. The actual live IR Panel index structure
still needs read-only operator verification before enabling Web Approval.
A green GitHub test only validates test fixtures.

## Choice B — approved bounded maintenance (no zero-downtime guarantee)

If the operator accepts a brief interruption instead, review exact signed
new images first, rehearse rollback on disposable clones, and separately
schedule IR and KH Node container maintenance. Node/FRPS and KH FRPC may
restart; never auto-reapply the existing owner or restore old replay/nonce
DBs. Confirm all three real clients, owner/child leases and signed proof
after each step. This choice **requires explicit operator approval**; it
must not be triggered by a wizard option or a green CI check.

## What can safely proceed now

- Independent IR Root reviewer source and pinned offline image download.
- Static lint/CI, precise impact-map and immutable backup inventory.
- Physical Passkey test only in a separately isolated environment with
  mock signed evidence and **no live grant/publish** (not equivalent to E2E).
- No IR/KH apply, new Node image, DNS, Nginx, broker marker, new public port,
  Passkey enrollment for production, live fourth route, PR merge or release.
- Grandoptical must remain untouched.
