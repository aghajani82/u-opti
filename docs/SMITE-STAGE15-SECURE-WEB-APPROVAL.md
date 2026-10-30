# Stage15 Secure Web Approval — design and rollout HOLD (2026-10-30)

**Source branches only. NO IR/KH deployment, no public origin, no release,
no main merge, no replacement of the existing FRP owner or children.**
Grandoptical is strictly out of scope.

## Current checked facts

- U-OPTI PR #73 source SHA: `9370fcd4b44859eff7d4cb6924c3905b771a5885`.
- Smite PR #40 source SHA: `50eb4f174eef67049eff82dad194e762181f18ca`.
- Known live direct FRPS owner: `FRP-IR-KH-45121`, `45121`, `/45121/www`.
- Known shared children: `frp10` at `38658 /38658/shop`; `frp3` at
  `28897 /28897/blog`. These are operator-reported live client PASS;
  this feature's CI is not an independent live verification.

## Security boundary (required, NOT YET DEPLOYED)

1. Smite Panel displays the selected current tunnel/child, owner, lease, IR/KH,
   port/path, status and SHA256 evidence digests. It never authenticates the
   human Root approver and never receives the Root credential or signing key.
2. Existing signed Panel -> IR Node transport submits the 30-second canonical
   route request. On **explicit pre-apply missing-grant** response the IR broker
   stages an authenticated pending proposal, *not* a grant.
3. Dedicated HTTPS **different origin**, e.g. `https://review.example.invalid`
   (PLACEHOLDER ONLY), serves the independent Root-owned review UI. Root service
   listens only on a **private UNIX socket**, Nginx on its already authorized
   TLS/443 terminates that hostname. No Root TCP bind or open firewall port.
   A dedicated vhost/hostname and certificate require operator approval first.
4. Manager performs exact **WebAuthn/Passkey UV=required** assertion on that
   exact, pinned origin. Challenge is tied to the exact pending proposal digest,
   stored durable and consumed before checking the assertion. Cookies, tokens
   or a Panel session cannot replace passkey UV. Enrolment requires an explicit
   one-time local root ceremony and independent second-factor recovery policy;
   *no public enrolment route* exists.
5. Independent reviewer validates the current signed **IR owner attestation**,
   **KH XHTTP inbound attestation**, and **IR live unique lease attestation**
   using *separately pinned* Node Ed25519 public keys. Do not accept a JSON
   digest, ordinary Panel DB row or a Panel-supplied public key as proof.
   Attestations bind RP audience, kind, node ID, nonce and short expiry,
   and are checked against the exact proposed owner/child/lease/port/path.
   Invalid, stale or duplicate proof -> HOLD. Proof nonces are durably consumed
   before any grant issuance.
6. Only then root-owned code may install a fresh single-child TrustedGrant using
   exclusive creation, after a durable approval audit and exact pending request
   comparison. Existing broker verifies that grant and its separate durable
   Signed Intent nonce on publication.
7. The independent window notifies the parent **only as a UI hint**. The parent
   checks the exact popup source, origin, child, port and path and emits **one
   brand-new 30-second Signed Intent**. The Root broker, never the popup event,
   remains authoritative. On failed/ambiguous Broker result: HOLD, no retry.
8. Read-only independent status/reconciliation and route existence checks must
   precede any manual retry. Successful publish is distinct from real traffic
   verification.

## Code delivered in this isolated first milestone

U-OPTI:
- `smite-stage15-approval-evidence.py`: verifies exact schema, two
  independently pinned 32-byte Ed25519 public keys, signature, age, nonce,
  direct/shared active unique lease, FRPS single owner and KH VLESS+XHTTP
  loopback facts. This is a verifier, **not** a Node proof producer.
- `smite-stage15-web-approval.py`: isolated Passkey verifier and SQLite audit
  (single-use challenge; UV required; exact origin; spent challenge cannot be
  replayed). No HTTP service, no TrustedGrant issuance, no privileged mutation.
- associated offline negative tests and CI workflow. No modifications to the
  existing broker, FRPS, FRPC, Signed Pairing or existing replay ledger.

Smite:
- feature-flagged popup UX in Tunnels, enabled **only** by configured
  `VITE_STAGE15_APPROVAL_ORIGIN` on a future reviewed build. Default current
  operational flow is unchanged. A valid-origin popup notification only permits
  a *single* fresh signed publish; does not confer approval. The standalone
  service and popup message producer do NOT exist yet. Keep flag UNSET for now.

## Remaining blocking engineering

**This is NOT an end-to-end deployable web approval solution yet.**
Before any service activation or changing existing live images, implement and
review all of the following:

- Node-origin independent **read-only** attestations for IR owner, unique live
  lease and KH inventory; separate Node-held Ed25519 signing keys and securely
  pinned root-only verifier keys. Neither Panel nor browser may mint them.
  Define a read-only private proof acquisition path from Root using pinned Node
  identities; don't modify FRPS/FRPC/pairing records.
- Replace the broker's **single overwriteable** approval-request.json with a
  durable, immutable, conflict-safe per-request queue or explicit locked HOLD.
  Authenticate proposals at staging, persist received timestamp and expected
  hashes, support expiry without treating a stale intent as publishable.
- Read-only Root approval HTTP server on UNIX socket; strict Origin/Host,
  CSP, CSRF boundaries, framing restrictions, request size and method limits;
  no Panel-compatible approval endpoint; no remote enrollment endpoint.
- Independent Passkey bootstrap with durable credential storage, device
  counters/clone policy and passkey recovery procedure. Pin and test FIDO2 2.x
  APIs, including actual browser assertion with UV required and origin mismatch.
- A crash-safe state-machine that binds pending digest to verified Passkey and
  current attestation, commits audit and nonces, then root-issued grant with
  explicit recovery if interrupted. Current offline gate intentionally ends
  **BEFORE** issuing a grant.
- Read-only status/reconciliation and distinct states: Awaiting Approval,
  Approval Required, Approved, Publishing, Published, HOLD / Requires Review.
- API/UI review of exact evidence and credentials across both direct and shared
  routes; no public admin port. Fail-close on changing selection; do not confuse
  a popup signal with root proof.
- Isolated end-to-end security tests: invalid/stale owner/child/lease,
  signatures, Origin, CSRF, stolen Panel session, concurrent proposals,
  revoked/missing credential, crash recovery, no ambiguous apply retry, and
  unchanged three active routes.
- Snapshot + tested rollback of IR/KH, signed off by operator before any live
  test. A fourth route's real client PASS is still **NOT TESTED**.

## Origin and certificate approval prerequisites (do NOT activate yet)

1. Operator chooses a *new dedicated hostname* (not the ordinary Smite origin)
   and confirms DNS/TLS certificate provisioning, firewall/443 reuse and its
   intended administrative access policy.
2. Operator confirms use of Passkeys and a safe initial root-only enrolment
   ceremony (plus backup/recovery plan).
3. Read-only preflight shows the existing Nginx routing and current routes
   without changing them. Snapshot and rollback points are verified first.
4. Secure service and signed attestation sources pass CI and a disposable
   isolated E2E trial before any IR/KH live opt-in.

## Rollback

Before live rollout: do not set the UI flag or install/enable an approval
service — rollback is simply to discard these feature branches. Existing
broker/console flow and active FRP routes remain untouched.

After a future **separately approved** rollout: disable the independent
review service and remove only its reviewed Nginx vhost and opt-in Panel flag;
restore the previous reviewed Panel image and Root service configs using
a snapshot/transactional rollback plan. **Do not delete or overwrite existing
FRPS/FRPC, Signed Pairing, replay DB, trusted active route files, owners or
children.** If publication outcome is ambiguous, inspect read-only and HOLD.

## Acceptance gate

NOT MET: a fourth tunnel has not been created, approved in the browser, or
tested with a client, and the three live routes were not probed this turn.
No claim of operational availability is made.
