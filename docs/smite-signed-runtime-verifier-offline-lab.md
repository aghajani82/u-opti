# Stage 6 — Signed Runtime Verifier Lab (mock transport, pinned HMAC source)

2026-10-19 · U-OPTI experimental Draft PR #42 stacked on Draft #41.
NO changes to main, Release, IR/KH servers, Xray/3x-UI, ports, or running tunnels.

## What was tested

A separate PR-only CI job checks out *Smite* at exactly
`a15c46288aae9849babc9c9358c68e46686bce9c` and loads its real
`node/app/node_auth.py`. The new `tests/lab/smite_signed_runtime_probe.py`
creates signatures using that reviewed HMAC-v1 implementation, not an
independent homemade signature algorithm. The mock receiver validates
requests using the **same pinned source**. Tests check:

- trusted, lower-case FQDN origin with explicit certificate-verified
  HTTPS/443 policy; no injected path/query/userinfo, TLS downgrade,
  redirects, IP literals, or unknown host;
- strict status API refusing unsigned requests; first signed GET succeeds,
  **identical signed nonce replay is refused**, independent new nonce works;
- wrong per-Node HMAC secret is rejected and unexpected status codes,
  redirects and TLS failures fail closed;
- exact **observed Smite response shapes**:
  - `GET /api/agent/status` = `{"status":"ok","active_tunnels":0,"tunnels":[]}`
    for a quiescent fresh installation;
  - `GET /api/agent/engines` = `{"mode":"managed","engines":...}`,
    exact Backhaul/FRP/GOST/Rathole/Chisel registry with expected
    `not-installed`, `ready` or `unavailable` states;
- independent Backhaul-only, FRP-only, and coexistence inventory examples;
- chaining the mock-only verifier into the existing sandbox transaction
  commit and compensation step; an HMAC-valid response with the **wrong
  managed inventory** still triggers rollback/HOLD.

The code never sends real HTTP, opens sockets, looks up credentials on
servers, provisions engines, runs Docker or configures TLS/443.

## Essential limits and negative claims

**This is a compatibility/regression test, NOT cryptographic attestation
of a running Smite Node.** The mocked transport itself reports whether TLS
would have been verified; real TLS, DNS, SNI, proxies, certificates, Nginx
request-target preservation and replay DB persistence across real reboot
remain untested by this job.

The read-only Agent response schema at the reviewed Smite SHA **does not
include** Node UUID, binary SHA256 or executable version. Do not invent
those fields and do not assert that a `200` response proves an identity or
exact file content. The future real-host admission must combine operator-
approved pairing and trusted origin, actual TLS-enforced HMAC challenges,
file/manifest digests, container image pinning, persistent replay evidence
and authorized signed status. The existing generic lab `probe` injection
is not removed or approved for a production executor.

Smite's `node_auth.NonceWindow` used by this isolated mock is process-local.
Actual strict Node uses `agent_auth.DurableNonceStore` in SQLite; its
persistence across worker restart is covered by Smite's separate tests.
A future production integration MUST exercise the durable store and live
replay denial. No fallback to local in-memory nonces.

## Next test gates

1. Run a full offline FastAPI strict Agent endpoint check against the exact
   Smite SHA, binding sandbox recovery to real `agent_auth` and persistent
   SQLite replay semantics (but still without live ports).
2. Confirm a single Node immutable ID and read-only approved origin across
   Restart and Rollback; enforce live TLS chain/hostname and request target.
3. Make filesystem/journal controls race-resistant at a genuine host boundary,
   then test disposable two-VPS snapshot recovery and the 443 gateway before
   even considering real installer activation.
4. Keep the one-clean-rebuild milestone, no main merge or release without
   operator approval.

**INSTALL_ALLOWED=NO, ACTIVATION_GATE=HOLD, release/server unchanged.**
