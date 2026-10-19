# Stage 6 — fd-relative sandbox safety and Signed Node acceptance contract

2026-10-19. This document is for a **Draft CI-only branch** on top of
U-OPTI Host Plan-bound sandbox PR #40. It changes neither Smite runtime nor
running IR/KH servers. No host Install/Repair/Remove is enabled.

## Filesystem hardening in the disposable lab

The sandbox now uses `tests/lab/smite_fd_guard.py` for its journal, binary,
manifest, Compose, identity/replay snapshot, shared lock and archived audit
access. Every path segment is opened relative to an already opened directory
descriptor, using `O_DIRECTORY|O_NOFOLLOW`. Final reads also use
`O_NOFOLLOW`, `fstat` owner/type/hardlink checks, bounded reads and
before/after descriptor metadata comparison. Journal and binary replacements
write a private temporary file, `fsync` it, check prior inode metadata,
then use descriptor-relative `os.replace` and directory `fsync`.

If the directory is writable by group/others, a parent becomes a symlink,
a hard-linked/nonregular target appears, the shared lock conflicts, or
tracked metadata changes unexpectedly, operations **fail closed**. The
sandbox directory must remain a private mode-0700 disposable directory
with the marker, and the existing Host Plan continues to report
`INSTALL_ALLOWED=NO` and `ACTIVATION_GATE=HOLD`.

**Important limitations:** an atomic conditional-replace primitive is not
provided by Python's standard rename API; an uncooperative same-UID writer
can still race between the final file-stat and rename, even though the
operations are anchored to dirfds. Neither inode checks, content SHA-256
nor a private JSON journal is a cryptographic proof against a compromised
same-UID/root process. A production executor must run under exclusive
ownership/permissions and implement independent admission, race analysis,
trusted journal storage and recovery before deployment. This lab does NOT
claim production-safe concurrent writes.

## Signed Node runtime: required acceptance protocol (DESIGN ONLY)

The companion Smite draft branch
`feature/smite-simple-operator-ui-20261018` documents and implements
opt-in HMAC Agent request authentication, strict mode and durable replay.
The contract used by a future host executor must reflect the actual wire
protocol rather than accept a caller-supplied `{"signed": true}` flag:

1. The operator-approved Node UUID, role, hostname, trusted TLS/443 origin,
   pinned Node image, signed mode, and credential source must be independently
   identified. Never trust self-registered URLs or ordinary container health.
2. Build an authenticated request using the same canonical input as
   `node/app/node_auth.py`: HMAC-SHA256 over
   `smite-node-hmac-v1`, Node ID, method, exact raw target (including query),
   decimal timestamp, unique 16-byte-random hex nonce, and SHA256 of the
   transmitted byte body. The four `X-Smite-*` headers are sent unchanged.
3. For off-machine requests enforce certificate/hostname-verified HTTPS
   on port 443 with no redirect, no `verify=False`, no proxy fallback and no
   unsigned retry. Preserve the exact `/api/agent/...` target through Nginx.
   For approved co-located IR Node, the separate expressly pinned loopback
   origin may be used; never infer it from unsigned metadata.
4. Query read-only signed `GET /api/agent/status` and
   `GET /api/agent/engines`, ensure response status/payload matches the
   expected Node identity and managed inventory, exact engine versions and
   pinned SHA, plus unchanged identity and replay DB across the Node recreate.
   **Response schemas must be inspected against the precise reviewed Smite SHA
   before this check can be implemented.**
5. Prove the Node is actually enforcing strict auth: an unsigned request
   must fail; replaying the **same signed nonce** must fail; a new correctly
   signed request must succeed. The replay store must be persistent and
   unavailable storage must fail closed. Avoid exposing secrets, signatures,
   raw URLs or tokens in logs or public reports.
6. If any dependency is missing, mismatched, unavailable or stale,
   report HOLD; on a failed restart initiate only the independently
   journalled compensation and verify the prior signed runtime. A lost
   pairing key, invalid cert, missing replay DB or engine mismatch must
   never be treated as a mere warning.

The Smite HMAC check **authenticates inbound requests**, not standalone
HTTP responses; a 200 response or synthetic `signed: true` JSON by itself
is not proof. Node identity is bound by paired credentials, verified TLS
transport, explicit allowlisted target and negative anti-replay tests.

## Exact review references

- Smite `node/app/node_auth.py` — canonical request fields, signatures,
  90-second skew, 128-bit nonce.
- Smite `node/app/agent_auth.py` — strict Agent request guard, durable
  replay store and fail-closed 401/503.
- Smite `panel/app/agent_request_signer.py` — allowed GET targets and
  exact transmitted bytes.
- Smite `docs/node-panel-stage6-signed-client.md` and
  `docs/stage12-signed-node-origin-and-backhaul-updates.md` — certificate
  validation, approved signed origin, path preservation and rollout holds.

## Remaining release gates

Live Signed Node transport and replay tests, image digests, durable journal
trust, crash after actual power loss, correct bind-mount propagation,
restorable snapshots and emergency Console, dual disposable VPS trials,
443 ingress, full engine lifecycle and operator approval are **NOT DONE**.

**main / Release / IR / KH unchanged. Never enable host installation from
this branch.**
