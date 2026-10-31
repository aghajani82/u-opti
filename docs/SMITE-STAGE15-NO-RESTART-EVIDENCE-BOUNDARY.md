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
