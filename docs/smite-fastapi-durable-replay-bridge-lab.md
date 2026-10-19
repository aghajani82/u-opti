# Stage 6 — Real Smite FastAPI + persistent Replay SQLite in isolated CI

2026-10-19 · U-OPTI **Draft PR #43** stacked on Draft #42, not `main`.
No IR/KH changes. `INSTALL_ALLOWED=NO`; `ACTIVATION_GATE=HOLD`.

## What this step actually executes

The new PR-only workflow `signed-fastapi-durable-replay-isolated` pins
Smite to **a15c46288aae9849babc9c9358c68e46686bce9c**, selects
Python 3.11, and installs the reviewed Node's dependency versions.
`tests/test-smite-fastapi-durable-bridge.py` imports **real** source files
from that checkout:

- `node/app/routers/agent.py` — the Agent FastAPI router;
- `node/app/agent_auth.py` — strict request dependency and persistent
  SQLite `DurableNonceStore`;
- `node/app/node_auth.py` — exact raw-target/nonce/HMAC-SHA256 primitive;
- `node/app/engine_inventory.py` — managed engine manifest/binary gate.

The test constructs FastAPI apps with `TestClient`: **no TCP listener**,
Nginx, Docker, provider server, firewall, public 443, or real TLS session.
A transport shim marks TLS as *simulated* solely so the existing offline
verifier can evaluate the actual signed API responses. The shim does not
and cannot prove certificate or hostname verification.

## Observed gates exercised

- Strict endpoint refuses unsigned, wrong-secret, mismatched-target,
  expired and replayed HMAC requests; a fresh signed request succeeds.
- A durable SQLite replay file persists between **distinct FastAPI app
  instances**. A separate Python interpreter also opens the exact same
  replay database: a previously used nonce is rejected, a fresh one works.
  Fixture parent directories are private `0700`, identity and DB `0600`.
- Mode `legacy` returns unsigned HTTP 200 and therefore **fails**
  verifier acceptance; strict mode/managed inventory is required.
- With no enrolled engine, a correctly signed Apply command is rejected
  with HTTP 409, without invoking a tunnel adapter.
- A fixture Backhaul binary `0755` owned by the CI user, plus a
  matching trusted manifest, appears `ready` only after the test patches
  the production root-owner expectation to the disposable fixture owner.
  Modified bytes return `unavailable`. These are synthetic non-executable
  file contents; no real upstream engine install is tested.
- FRP with a valid fixture `frpc` but without a verified companion
  `frps` must never report `ready`.
- A real in-process FastAPI `/status` + `/engines` verifier gates the
  existing **disposable** host transaction: inject a crash at Manifest,
  recover to zero installed engines, simulate successful Backhaul
  enrollment, and reconstruct a new FastAPI app while preserving the
  paired identity and persistent SQLite replay store.

The saved `node/config/replay.db` used by the generic transaction
laboratory is an inert **separate model file**, not the live SQLite test
database. The SQLite test uses its own private persistent path. Real
replay DB activity changes on every signed request; hashing its live file
and requiring the hash to stay constant across a signed health check
would create false-positive drift. A future production installer must
protect its **identity/path/ownership and recovery continuity**, not
assume an actively updated replay database is immutable.

## Blocking security gaps — not ready for production

1. **Replay store loss:** the reviewed Smite `DurableNonceStore._open`
   currently creates a new SQLite database when the file is missing.
   If the previous store was lost and an old signed request is still
   inside the clock window, replay protection may lose its history.
   Production restart admission must fail closed when an enrolled
   replay DB unexpectedly disappears; design and review a deliberate
   first-enrollment initialization/restore protocol in **Smite** before
   live activation. CI success alone does not fix this.
2. A FastAPI app reconstruction and isolated second interpreter are
   **not** proof of Docker recreation, real process/network migration,
   filesystem crash durability, HMAC through Nginx, or TLS/SNI on 443.
3. The inventory Agent response exposes state, not the paired Node UUID,
   FRP/Backhaul binary SHA256 or container image digest. Continue to
   bind those externally to approved paired identity, immutable image,
   exact local files and trusted TLS transport; do not infer them from 200.
4. The host transaction's journal and file guard are still *lab models*
   with documented concurrency/race and journal-trust limitations. No
   production host executor exists or is authorized in this branch.
5. No change to FRP/Backhaul protocol ports, Xray Inbound selection,
   tunnel path mapping, Panel↔Node production mode, or U-OPTI menu.

## Next admission milestone

Treat replay persistence/initialization as an explicit lifecycle gate,
design a non-sensitive signed runtime evidence format and test Nginx
request-target preservation with disposable TLS fixtures. Then review
transaction recoverability and controlled snapshots before any
**separately approved two-VPS disposable** trial.

**Never merge to main or enable IR/KH installation based on these CI
results.**
