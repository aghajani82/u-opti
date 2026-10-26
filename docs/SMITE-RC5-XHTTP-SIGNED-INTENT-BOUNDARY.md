# Smite RC5 × U-OPTI — Signed XHTTP route-intent boundary (prototype)

**Current status, 2026-10-26:** HMAC message **authentication contract only**. This is not a live Signed Node→Root broker, not a route management API, not a U-OPTI release, and not deployed. The real `45121` and `49328` field-trial XHTTP clients must remain unchanged.

## Why this separate contract exists

Smite's existing HMAC Signed Agent requests already protect Panel→Node operations and replay; they do **not** authorize root-managed Nginx file mutations. The U-OPTI RC5 Bridge installer ([PR #51](https://github.com/aghajani82/u-opti/pull/51)) controls host paths but deliberately has no remote interface. Before any integration, there must be a **separate, explicitly authorized, narrowly scoped intent** binding the particular authorized child FRP proxy to an approved Nginx path. Reusing a regular Agent signature or granting `sudo` access to the Panel/Node is not acceptable.

The offline admission code is `modules/smite-rc5-xhttp-signed-intent.py`. It exposes `admit(wire, key, expected, seen_nonces, now)`; it **cannot execute a command or mark a nonce as used**.

## Exact version-1 contract

Canonical, ASCII-only JSON (sorted keys, compact separators), including an HMAC-SHA256 lowercase hexadecimal `mac`. Signed body is the exact canonical JSON without the `mac` key. Require a dedicated 32-byte broker HMAC key that is NOT the Smite Agent HMAC key. Key material must come from separately approved local provisioning; never store it in Git or display it in logs.

Required data fields:

| Field | Contract |
|---|---|
| `schema` | Integer `1` |
| `audience` | Exact `u-opti:ir:xhttp-route:v1` |
| `action` | Exact `create` only (no arbitrary action or removal) |
| `ir_node`, `kh_node` | Strict approved paired Node IDs |
| `owner`, `child`, `lease` | Exact FRPS singleton owner, shared child and durable lease identities |
| `port`, `path` | A non-control loopback proxy port and valid XHTTP path starting with `/<port>/` |
| `owner_proof_sha256`, `kh_inventory_sha256` | Cryptographic digests bound to separately *verified* Signed IR owner proof and KH inbound inventory (digests alone do not prove authenticity) |
| `issued_at`, `expires_at` | Local epoch seconds; maximum 60 seconds TTL; +5 seconds future skew |
| `nonce` | 128-bit lowercase hexadecimal, unique to the dedicated broker replay store |
| `mac` | HMAC-SHA256 of canonical body; compare in constant time |

Reject unknown or duplicate JSON keys, malformed/noncanonical encodings, booleans where integers are expected, oversized JSON, wrong action/audience, wrong host, wrong identities, wrong owner/lease/path/evidence hashes, expired/future time, previously consumed nonce and incorrect MAC. Return an **immutable authenticated intent**, never a command.

## Non-negotiable additional gates before writing Nginx

**An authenticated message is not permission to write Nginx.** The independent root-owned `TrustedGrant` MUST already reflect authorization obtained from validated Signed KH Sanaei inbound inventory, valid Panel unique lease and Signed IR FRPS owner proof. The grant and its evidence/hash binding must NOT be constructed from the incoming request. A forged/incorrect external request cannot establish its own approval.

The future root broker must also:

1. Verify local Unix-peer credentials and pre-provisioned exact authorized service identity, never accept HTTP or an unprotected public socket. Do not expose the dedicated HMAC secret to KH, an untrusted UI or a general-purpose container.
2. Load a **durable, independent, root-owned nonce/idempotency store** and atomically consume the nonce under the shared U-OPTI engine lock *before* the first host-side effect. The offline function only checks an injected snapshot; it cannot itself prevent replay after a crash.
3. Re-verify that the requested port is a proxy on the existing **single** local FRPS `127.0.0.1:7000`, not the control port, with no public-bind FRPS sockets; confirm the dedicated Bridge is installed/committed with verified TLS 443→8443 scope.
4. Confirm exact `path` against live approved KH XHTTP inventory, not caller-reported data, plus exclusive lease/child identity, route collisions and ownership.
5. Execute only the separately reviewed, route-specific local Nginx transaction: one new owned path, `nginx -t`, scoped reload/rollback, crash journal/reconciliation and never automatic retry of ambiguous Signed KH apply.
6. Keep legacy `/etc/nginx/u-opti-smite-frp-xhttp.conf` and the working `45121`/`49328` routes unchanged. Refuse existing unmanaged routes rather than silently adopting them.

**Not implemented by this PR:** root broker socket, key provisioner, durable nonce store, trusted grant source, Smite Panel-side issuer, Signed IR Node delivery, route action orchestration, UI wizard, KH SQLite RO mount or E2E tests. Do not enable this code on the live trial hosts.

## Test plan

Run the offline Python suite in CI for HMAC tamper, explicit trusted grant identity binding, wrong-port/path, replay snapshot, nonce/time/TTL, unknown keys, malformed JSON, wrong key and fail-closed behavior. Then add the independently reviewed Smite-side issuer and cross-repo canonical vectors. Only after the broker's *complete* threat model, durable store, and least-privilege IPC pass CI should we use disposable clean IR/KH VMs for a third-inbound real-client test and consider a new signed release.

**Operator summary:** امضای درخواست و تطبیق مالک/تانل/Lease/پورت/مسیر در این مرحله فقط در تست آفلاین پیاده‌سازی می‌شود. هنوز اجازه اجرای Root، نصب روی سرور یا ویرایش Nginx از داخل پنل وجود ندارد. به تانل‌های 45121 و 49328 دست نزنید.
