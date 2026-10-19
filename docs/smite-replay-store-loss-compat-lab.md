# Stage 6 companion — Smite Replay Store missing-file admission test

**Draft U-OPTI branch**, stacked on Draft #43, not `main`:
`feature/smite-replay-restore-compat-lab-20261019`.

The `signed-fastapi-durable-replay-isolated` PR-only CI job pins the
new reviewed Smite security source commit
`3751aeda6f946e5e5624e5e89ab1ce554fec4460`
(Draft Smite PR #16). Other prior regression jobs retain their existing
pinned source commits to avoid quietly changing unrelated baselines.

The in-process FastAPI fixture must now call
`DurableNonceStore.initialize_new(db, node_id)` explicitly, *before* its
first strict request. The test verifies:

- strict Agent request and real SQLite nonce recording after explicit
  provisioning;
- reinitialization of an existing enrolled DB is refused;
- after deleting the SQLite file, **both** the original and fresh signed
  requests are HTTP 503, including through a new FastAPI application,
  and no blank replay DB is created;
- existing Backhaul/FRP managed inventory, HMAC, independent Python
  process, journal crash/rollback and quarantine tests still run.

No DNS/TLS/443, no actual Node daemon or Docker restart, no VPS,
no production replay-store provisioner and no host engine install are
performed in this job. Simulated TLS is not attestation.

**Important:** This is intentionally a breaking *strict enrollment*
precondition compared to the previous lazy SQLite initialization. Until
a separately reviewed bootstrap/migration/recovery workflow is available,
**do not enable new strict mode on real IR/KH nodes**. A missing DB must
remain fail-closed. Never silently downgrade to legacy authentication.

`INSTALL_ALLOWED=NO`; `ACTIVATION_GATE=HOLD`. No U-OPTI/Smite
`main` merge, release, rebuild or current-server writes.
