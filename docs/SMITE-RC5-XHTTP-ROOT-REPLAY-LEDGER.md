# Smite × U-OPTI — Root replay ledger prototype

**2026-10-26 / Source-only, no deployment or operating privileges.**

## Scope

The existing PR #52 signed XHTTP intent contract can parse and HMAC-authenticate a short-lived message, but its `seen_nonces` value is only an injected snapshot. It is **not durable** and must not be treated as sufficient replay protection for a privileged Nginx broker.

This milestone adds `modules/smite-rc5-xhttp-nonce-ledger.py`, a **root-only, offline SQLite replay ledger library**. It provides: one-time explicit bootstrap of a private root-owned database; verified version/schema/broker-instance identity; `mode=rw` (never `rwc`) connection; SQLite `BEGIN IMMEDIATE` + `PRIMARY KEY(nonce)` for atomic unique consumption; `synchronous=FULL`; and fail-closed behavior for missing, malformed, misowned, symlinked, relocated, capacity-exhausted and replayed state. It does not remove old nonces, silently restore or reinitialize a database.

An **offline-only** `authenticate_and_consume` helper verifies the HMAC message against an independently supplied `TrustedGrant` then consumes the nonce atomically. If an attacker sends a validly signed but unauthorized request, the root grant mismatches and the ledger is not consumed. On re-delivery, duplicate nonce fails even after reopening the DB or with concurrent workers.

## Security obligations still OPEN before any privileged broker

- **No root IPC endpoint or process was added.** This is a local library, not a running signed bridge between Smite Panel and U-OPTI. The user-facing Add Inbound action still cannot auto-write Nginx.
- **Provisioning:** A reviewed U-OPTI installer must explicitly create a dedicated private directory and one ledger per unique root broker identity. A dedicated HMAC broker key must be provisioned separately from the existing Smite Agent secret; never accept key/config from unauthenticated callers. Do not auto-initialize on any network request, error, reinstall or restore.
- **Independent authorization:** The future root broker must derive its `TrustedGrant` independently from validated Signed IR owner proof, Signed KH inventory, durable unique child lease and host FRPS runtime; never construct it from the incoming HMAC body, an unverified Panel UI field or a raw file path.
- **Replay atomicity:** The future broker must hold its approved host transaction lock while consuming the nonce and recording the route action's unique operation ID, before any host mutation. The ledger records *nonce consumed*, not success of a Nginx operation. A crash **after consumption** requires audited journal/reconciliation, not resending another signed Apply automatically.
- **Persistence and restore:** A local SQLite ledger cannot detect a coordinated rollback of the ledger *and* independently stored broker identity/key, a cloned VM snapshot, or root compromise. A separately anchored restore epoch/quarantine protocol must be designed before any real deployment. Nonces are deliberately not garbage collected; once capacity is reached, the broker must HOLD pending audited migration.
- **IPC:** Future Unix domain transport requires real `SO_PEERCRED` verification and allowlisted IR signed Node identity with least-privilege process isolation; no broad sudoers command, HTTP root endpoint, generic shell command, container write mount or untrusted import.
- **Nginx transaction:** Keep existing `45121` and `49328` routes unchanged. Only a separately owned include file per new inbound can be created after approved bridge, `nginx -t`, reload, rollback journal, signed owner and proxy listener proof.
- **Host trial:** Unit/CI SUCCESS is not a test on IR/KH. The first deployment test must use separate disposable fresh IR/KH snapshots plus a third Sanaei XHTTP inbound and real TLS 443 client traffic. Avoid touching Grandoptical.

## CI housekeeping (explicit planned milestone)

The number of GitHub workflows is growing. Before the next release candidate: inventory triggers and required checks in both Smite and U-OPTI, consolidate **only genuinely duplicate** pure-unit tests into a common matrix, keep independent signed security gates separate, prefer changed-path selective execution, review permissions and checkout pins, and ensure branch-protection required check names remain stable. Do not delete active CI workflows merely to make the dashboard cleaner; avoid doing so while a release gate is open.

## Roadmap from this checkpoint

1. Root ledger + offline security CI (this PR).
2. Exact root-owned key/bootstrap/restore quarantine, independently sourced TrustedGrant and local peer authentication.
3. Authorized root broker transaction state machine and idempotent recovery tied to U-OPTI's managed Nginx snippets; this must be reviewed with the existing bridge installer.
4. Signed Node orchestration + KH read-only 3x-ui mount + simple FRP wizard.
5. Clean disposable dual-VPS installation, third inbound real client test, signed compatible RC pair, explicit release approval.
