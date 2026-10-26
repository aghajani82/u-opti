# Stage 27 — Real Nginx TLS/443 preservation of Signed Node HMAC

2026-10-19 · U-OPTI **Draft PR #45** on top of Draft PR #44 (never
`main`). Source-backed companion: Smite Draft PR #16 at immutable
`3751aeda6f946e5e5624e5e89ab1ce554fec4460`. Default installation
and activation remain `NO/HOLD` on IR and KH.

## Why this test exists

Older Stage 12 tests read an **inert candidate** Nginx location without
starting Nginx. Stage 26 tested actual Panel→Nginx→Node TLS/443, but
built a simplified Nginx test location and pinned the prior Smite
release candidate. This increment instead runs the *actual text* from
`modules/smite-stage12-nginx-hmac-plan.py::render` in ephemeral Nginx.
Its one and only CI-only substitution is the upstream loopback port
`127.0.0.1:8888` → `127.0.0.1:18888`; the location directive, raw
`proxy_pass` URI policy, method/size limits and ACL remain unchanged.

The runner listens **only on 127.0.0.1:443** with a temporary
certificate for `kh.stage27.test`. The actual Smite strict FastAPI
Agent listens **only on 127.0.0.1:18888**, with a mocked, inert adapter.
The paired key and the anti-replay SQLite store live under private
temporary paths. The store is explicitly initialized once using
`DurableNonceStore.initialize_new` from reviewed Smite code, *before*
the signed Node starts. Nothing writes to /etc/nginx, /etc/hosts or
a real host vhost. Nginx uses a private, disposable configuration.
No Docker/3x-UI/Xray/tunnel service executes.

## Real protocol checks

- Actual certificate-chain verification using the temporary trusted
  certificate, with SAN/hostname and SNI checks. Untrusted issuer and
  mismatched hostname must fail. Test **never** uses `verify=False`.
- Unsigned strict GET `/api/agent/status` → 401; correctly signed raw
  target → 200; the same nonce again → 401.
- Signed `GET /api/agent/tunnels/status?tunnel_id=alpha-123` →
  200 with expected read-only response. Altering just the query to
  `alpha-124` or replaying the signature → 401.
- Signed POST `/api/agent/tunnels/remove` with exactly the signed JSON
  **bytes** → success on an inert adapter. Appending a single space
  after signing and replaying the same valid body → 401.
- Unsupported HTTP method → blocked by Nginx candidate's limit policy.
- Deliberately insert an exact Nginx location that modifies the
  authenticated raw URI: the original signature now fails. A test
  redirect yields 302 and is not followed. Restore the original
  candidate and signed access succeeds again.
- Delete the replay SQLite database: another valid signed request over
  real TLS/443 produces HTTP **503**, with **no silent recreation**.

## What remains unproved

This is real Nginx and real loopback TLS, **not** actual IR↔KH network
or a real provider, DNS source address, firewall, CDN, or snapshot.
Source-IP ACL is only exercised for an admitted localhost client; no
remote denied-source simulation is claimed. One mutable temp certificate
is explicitly trusted by the CI runner, not a production trust anchor.
This test doesn't turn the Stage12 candidate into a live configuration,
validate virtual-host collisions, or assert the Panel's production client
automatically consumes this candidate. Earlier separate Stage26 tests
remain pinned to their reviewed original SHA and exercise the actual
Panel NodeClient; Stage27 is focused on exact candidate path bytes
and the hardened replay-store lifecycle.

**Never copy the sandbox certificate, hostname, key or gateway listener
to IR/KH. Production strict mode stays HOLD until independent approval,
provisioning/recovery, 443 ownership review, snapshots and dual-VPS
integration testing.**
