# Smite × U-OPTI — Root replay ledger prototype

**2026-10-26 / Source-only, no deployment or operating privileges.**

## Scope

The existing PR #52 signed XHTTP intent contract can parse and HMAC-authenticate a short-lived message, but its `seen_nonces` value is only an injected snapshot. It is **not durable** and must not be treated as sufficient replay protection for a privileged Nginx broker.

This milestone adds `modules/smite-rc5-xhttp-nonce-ledger.py`, a **root-only, offline SQLite replay ledger library**. It provides: one-time explicit bootstrap of a private root-owned database; verified version/schema/broker-instance identity; `mode=rw` (never `rwc`) connection; SQLite `BEGIN IMMEDIATE` + `PRIMARY KEY(nonce)` for atomic unique consumption; `synchronous=FULL`; and fail-closed behavior for missing, malformed, misowned, symlinked, relocated, capacity-exhausted and replayed state. It does not remove old nonces, silently restore or reinitialize a database.

An **offline-only** `authenticate_and_consume` helper verifies the HMAC message against an independently supplied `TrustedGrant` then consumes the nonce atomically. If an attacker sends a validly signed but unauthorized request, the root grant mismatches and the ledger is not consumed. On re-delivery, duplicate nonce fails even after reopening the DB or with concurrent workers.

## Broker service readiness and remaining authorization gate

- **Per-child root approval is a separate local operation.** On a clean IR install the operator may run `python3 -B /usr/local/lib/u-opti/modules/smite-rc5-xhttp-broker-provision.py --approve-grant --confirm-local-root` after comparing the exact Node IDs, FRPS owner, child/lease, selected port/path and current authenticated Signed IR/KH results. The command requires an interactive root TTY and typing `APPROVE <child-id>`; it writes one root-owned `0600` per-child grant with exclusive create and never overwrites an existing grant. It computes the canonical evidence digests used by the Panel intent.
- **Existing FRP wizard:** after an active shared FRP child is created, the Panel fetches the signed KH inbound choices, asks the operator to select one, and submits one route intent. A missing grant stops before nonce use and shows the IR command plus the exact values to review. After the root command prints PASS, use the child's XHTTP action once; an uncertain broker result is never automatically retried.
- **Evidence boundary:** the command reports `EVIDENCE_VERIFICATION=OPERATOR_ASSERTED`; it does not fetch or cryptographically validate remote proofs itself. The root operator must compare the facts with current Signed IR owner output, Signed KH XHTTP inventory and the active unique Panel lease before approving. A missing grant returns a specific pre-transaction hold before nonce consumption, so the Panel can guide the operator and a later deliberate attempt uses a fresh nonce. Other broker errors remain generic/ambiguous and must not be retried without reconciliation.
- **Revocation:** `--revoke-grant <child-id> --confirm-local-root` requires an interactive typed confirmation and removes only that child's root grant. It does not remove an existing Nginx route; route removal remains a separate reviewed local-root operation. Never treat grant revocation alone as route cleanup.
- **Provisioning:** The U-OPTI helper explicitly creates the private root-owned directory, dedicated HMAC key, broker identity, empty TrustedGrant directory, one durable ledger, pinned worker/planner, and a systemd unit. Provisioning itself remains inert. A separate `--activate-existing --confirm-local-root` action verifies these inputs, enables/starts the IR-only service, and confirms the persistent systemd state and exact Unix socket owner/mode. The service uses bounded systemd restart-on-failure policy; activation does not mount a key into Panel/Node, create grants, or change Nginx.
- **Independent authorization:** the root broker consumes a pre-installed grant and never creates one from an incoming HMAC body. The first-trial workflow uses explicit root-operator review of authenticated Signed IR/KH output and the active unique lease. The CLI validates exact IDs, path, hashes, ownership/modes and requires separate local confirmation, but the operator remains responsible for verifying remote evidence.
- **Replay atomicity:** The future broker must hold its approved host transaction lock while consuming the nonce and recording the route action's unique operation ID, before any host mutation. The ledger records *nonce consumed*, not success of a Nginx operation. A crash **after consumption** requires audited journal/reconciliation, not resending another signed Apply automatically.
- **Persistence and restore:** A local SQLite ledger cannot detect a coordinated rollback of the ledger *and* independently stored broker identity/key, a cloned VM snapshot, or root compromise. A separately anchored restore epoch/quarantine protocol must be designed before any real deployment. Nonces are deliberately not garbage collected; once capacity is reached, the broker must HOLD pending audited migration.
- **IPC:** The local broker verifies Unix `SO_PEERCRED` and checks the dedicated Node UID/GID, but deployment must still confirm the exact opt-in Node socket mount and Panel signed-intent path. No broad sudoers command, HTTP root endpoint, generic shell command, container write mount or untrusted import is allowed.
- **Nginx transaction:** Keep existing `45121` and `49328` routes unchanged. Only a separately owned include file per new inbound can be created after approved bridge, `nginx -t`, reload, rollback journal, signed owner and proxy listener proof.
- **Host trial:** Unit/CI SUCCESS is not a test on IR/KH. The first deployment test must use separate disposable fresh IR/KH snapshots plus a third Sanaei XHTTP inbound and real TLS 443 client traffic. Avoid touching Grandoptical.

## CI housekeeping (explicit planned milestone)

The number of GitHub workflows is growing. Before the next release candidate: inventory triggers and required checks in both Smite and U-OPTI, consolidate **only genuinely duplicate** pure-unit tests into a common matrix, keep independent signed security gates separate, prefer changed-path selective execution, review permissions and checkout pins, and ensure branch-protection required check names remain stable. Do not delete active CI workflows merely to make the dashboard cleaner; avoid doing so while a release gate is open.

## Roadmap from this checkpoint

1. Root ledger + offline security CI (this PR).
2. Exact root-owned key/bootstrap/restore quarantine, independently sourced TrustedGrant and local peer authentication.
3. Per-child `TrustedGrant` installation only after explicit root-operator review of current Signed IR owner proof, Signed KH inventory and unique active lease. Automated cryptographic re-fetch by the root service is not implemented; do not describe manual approval as autonomous evidence verification.
4. Signed Node orchestration + KH read-only 3x-ui mount + simple FRP wizard.
5. Clean disposable dual-VPS installation, third inbound real client test, signed compatible RC pair, explicit release approval.
