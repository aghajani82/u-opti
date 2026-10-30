# Stage15 Secure Web Approval — offline implementation and gated deployment

**State: source-only, draft PR #74 (counterpart Smite PR #41).**
**No live deployment, no public hostname, no DNS/certificate, no Nginx reload,
no FRPS/FRPC or existing Node/Panel restart, no main merge.**
Grandoptical is strictly excluded.

Parent PR immutable starting points:
- U-OPTI #73: `9370fcd4b44859eff7d4cb6924c3905b771a5885`
- Smite #40: `50eb4f174eef67049eff82dad194e762181f18ca`

## Existing live contract (operator observations; NOT retested in this turn)

- Direct owner `FRP-IR-KH-45121`: `45121 /45121/www`.
- Child `frp10`: `38658 /38658/shop`.
- Child `frp3`: `28897 /28897/blog`.
- One shared FRPS owner, FRP 0.71.0; active existing routes and signed
  pairing/replay records are strictly preserved. Do not reapply owner.

## Implemented source architecture

```text
Smite Panel Create/Verify -> signed XHTTP proposal (30 s)
            -> IR Root Broker (missing grant, no Apply)
            -> Root-only immutable queue [one pending per Child]
            -> independent HTTPS Origin (not Panel), Nginx 443 -> UNIX socket
            -> strict Host/Origin/CSRF and single-use WebAuthn UV required
            -> independent IR FRPS live owner Ed25519 attestation
            -> independent KH Sanaei SQLite read-only inbound Ed25519 attestation
            -> root-only consistent read-only transaction against the live Panel SQLite volume
               + separate Root Ed25519 lease attestation
            -> pinned signature/evidence digest/nonce/expiry verification
            -> durable audit + evidence nonce consumption
            -> root-only exclusive TrustedGrant create
            -> exact-origin popup message (UI hint only)
            -> Panel creates ONE brand-new 30 s signed intent
            -> existing IR Broker durable nonce gate and Nginx route executor
            -> Published / HOLD; no automatic ambiguous retry
```

The Panel cannot call an approval method as Root. The popup message cannot
authorize Nginx; only an already installed independent TrustedGrant can do
that. The published 30s Signed Intent is always a **new nonce**, never a
replay of the expired staged proposal. Root can review a historical proposal
for up to 600 seconds but independently re-collects current evidence before
granting. A second concurrent proposal for the same Child is HOLD.

### Root-only components (U-OPTI)

- `modules/smite-stage15-web-service.py` — real HTTP/1.1 over AF_UNIX, no TCP,
  POST exact-Origin, exact Host, no cookie, no X-Forwarded, bounded JSON,
  nonce CSP, private web review and Passkey registration pages.
- `modules/smite-stage15-web-approval.py` — Passkey UV gate, durable challenge,
  nonce/replay audit and independent evidence verification.
- `modules/smite-stage15-passkey-enrollment.py` — root TTY generates a
  short-lived, one-use registration/recovery ticket; WebAuthn credential
  registration, persisted credential bytes, signature counter, offline revoke.
  Do not expose enrollment as normal Smite login or permit no-ticket enrollment.
- `modules/smite-stage15-approval-queue.py` — authenticated immutable pending
  proposal, concurrent-child HOLD, expiry and no stale intent publication.
- `modules/smite-stage15-approval-evidence.py` — separate Node/Root public-key
  verification and exact owner/child/lease/port/path/digest match.
- `modules/smite-stage15-live-evidence.py` — fresh signed POST to separately
  pinned Node URLs; strict HTTPS/443 or IR loopback; reads **mounted, read-only**
  Panel SQLite lease records locally, never accepts a Panel HTTP claim.
- `modules/smite-stage15-web-launcher.py` — explicit root-only config;
  independently pinned keys, real live evidence provider and exclusive
  `install_grant()`. No public listener.
- `modules/smite-stage15-web-bootstrap.py` — IR root-console one-time
  preparation of new audit/credential databases and pending queue only.
  It never creates the opt-in marker or starts the service.
- `modules/smite-stage15-approval-key-enrollment.py` — root TTY creates
  independent raw Ed25519 private key (0400) and public pin (0600).
  Existing Signed Pairing credentials and Replay DB are NOT rotated.
- `modules/smite-rc5-xhttp-root-broker.py` — **only opt-in**
  `/etc/u-opti/smite/web-approval-mode.json` switches missing-grant staging
  to immutable queue. Without this root-owned marker, original root TTY
  review remains unchanged. Neither path changes FRPS/FRPC.
- `docs/examples/stage15-web-approval.nginx.conf.example` and
  `docs/examples/u-opti-smite-web-approval.service.example`: intentionally
  inactive, placeholder-only, not included in an installer.

### Smite components

- `node/app/approval_runtime_evidence.py` reads the tracked **live**
  singleton FRPS owner and proxy port (IR) or sanitized read-only Sanaei
  inbound inventory (KH); returns a fresh independent signature, not
  user-provided facts.
- `node/app/approval_attestation.py` pins separate Node Ed25519 key path,
  rejects wrong role, port 7000, non-loopback/inactive inbound, malformed
  or forged facts. **Default OFF** without root-mounted
  `SMITE_STAGE15_APPROVAL_ATTESTATION_KEY`.
- `node/app/routers/agent.py` has a strictly Signed-Agent protected
  `POST /api/agent/approval/evidence`. Read-only, no action permission;
  not on the ordinary Panel's allowed command list.
- `frontend/src/pages/Tunnels.tsx` has default-off
  `VITE_STAGE15_APPROVAL_ORIGIN`, independent popup, exact message
  origin/source/child/port/path check and ONE fresh publication request.
  Ambiguous response -> HOLD, never retry.
- No active code updates for FRP process management, Smite pairing, Signed
  Replay schema or currently installed Node/Panel images in this feature.

## Initial deployment prerequisites — NOT AUTHORIZED / NOT PERFORMED

The following requires separate approval and a checked IR/KH snapshot first:

1. Choose **independent** admin HTTPS hostname, LE certificate and authorized
   Nginx TLS/443 vhost (no new public admin port). Decide allowed admin
   access and reverse-proxy group socket permissions. Refuse same-origin
   Panel and any HTTP production Origin.
2. Pin exact reviewed U-OPTI and Smite source/image artifacts; verify signed
   actual IR/KH configs and snapshot recovery. No rebuild/recreate/reapply
   without separate confirmation.
3. On IR and KH, root-console generate distinct Ed25519 Node approval keys
   under already-existing private `/etc/u-opti/smite/approval-keys/`:
   `python3 -B smite-stage15-approval-key-enrollment.py --generate PRIVATE PUBLIC`.
   Mount each Node's private 0400 key **read-only inside its own Node** and
   set the explicit Node-only attestation env. Transfer only **public** pins
   to the dedicated IR review service. A separately generated root lease
   signing key stays on IR. Never expose any private key to Panel JS/backend.
   Any Node maintenance/recreate requires a separate approved deployment.
4. Mount the authoritative live Panel SQLite volume read-only for Root and verify SQLite WAL sidecars, then obtain a fresh consistent read transaction of Panel tunnels
   and frp_proxy_leases on IR (including valid WAL companion files as needed).
   The review service must not query the unauthenticated Panel API or grant
   based only on the database; it corroborates live IR/KH signed attestations.
5. Root must independently configure **exact pinned** signed IR/KH Agent
   endpoints and root-only protected copies of their per-Node transport HMAC
   secrets. Signed requests are one-time; KH over approved HTTPS/443 gateway.
   Do not modify original Signed Pairing keys or Replay DB.
6. On IR only, after snapshot + authorization, run
   `python3 -B smite-stage15-web-bootstrap.py --prepare` on root TTY.
   It creates an inert private audit DB, credentials DB and immutable queue;
   **it does not install/enable anything**.
7. Add root-only 0600 `/etc/u-opti/smite/web-approval-config.json`
   with schema 1, approved `origin`, `panel_origin`, `socket_path`,
   `socket_gid`, `queue_dir`, `ledger_path`, `credentials_path`,
   `broker_key_path`, `ir_public_key_path`, `kh_public_key_path`,
   `lease_public_key_path`, `lease_private_key_path`,
   `node_ir`/`node_kh` {node_id,url,secret_path} and
   `panel_live_db_path`. All paths are fixed administrator-controlled.
8. Only after independent review: activate root-owned systemd UDS service
   and Nginx example with actual hostname/certificate. Verify private
   socket parent traversal by Nginx, never chmod Root secrets or bind TCP.
9. On root TTY, run
   `python3 -B smite-stage15-passkey-enrollment.py --ticket /var/lib/u-opti/smite-web-approval/credentials.db`.
   Visit the **dedicated** HTTPS `/enroll` page and register a Passkey.
   Repeat for an independent backup Passkey, store recovery procedure offline.
   Lost/compromised Passkey recovery uses another one-time root-console
   ticket, not a Panel token. `--revoke DB CREDENTIAL_SHA256` works on
   local root TTY; only after a safe recovery credential exists.
10. After browser, CSRF, Node attestation, queue + grant E2E pass on disposable
    snapshot and explicit authorization: place root-owned 0600
    `web-approval-mode.json` with
    `{"schema":1,"enabled":true,"queue_dir":"/var/lib/u-opti/smite-xhttp-broker/approval-pending"}`.
    Activate the reviewed Smite Panel build with an exact
    `VITE_STAGE15_APPROVAL_ORIGIN`. Normal future route workflow needs no
    SSH or manual second publication request.

**No real hostname, TLS, config, socket, container, or host was changed in
the development turn.** Placeholder `https://review.example.invalid` is
used exclusively in offline tests, not as a real browser certificate.

## Rollback and interruption

- Before deployment: abandon draft PR branches. No host rollback necessary.
- After separate deployment approval: disable independent root service and
  optional root-owned web-approval-mode marker, disable UI flag, and remove
  only its dedicated reviewed Nginx vhost; restore previous pinned Panel/Node
  image only under its own protected transactional migration plan.
- **Never delete/restore/overwrite** the existing FRPS Owner/Child rows,
  FRPC, Signed Pairing, Node replay.db, broker nonce.db, existing route
  files, existing trusted grants or already active 3 XHTTP routes.
- If crash occurs after Passkey/evidence audit but before exclusive grant
  creation, or after a Broker submission with unknown answer:
  **HOLD / Requires Review**. Inspect independent audit/nonce and effective
  route state using read-only commands. No automatic grant or Nginx reapply,
  no retry of an ambiguous broker result.
- Queue and audit state are durable and should be backed up consistently.
  Rolling the approval ledger back independently is unsafe; mismatch or
  missing nonce/credential records requires quarantine and manual recovery.
- Final live acceptance requires independently validated IR/KH snapshots,
  unchanged operation of `45121`, `38658`, `28897`, and a **fourth**
  distinct FRP Shared Child created/approved/published through the UI with
  actual client VLESS+XHTTP connection. Not tested live yet.

## CI and limits

Offline CI includes signed invalid/expired/replay tests, direct/shared
evidence, immutable pending concurrency, passkey challenge/expiry/ticket,
Root readonly SQLite lease reconciliation, actual `AF_UNIX` HTTP/CSRF,
single-use grant, and Node runtime source tests. HTTP integration uses a
**deterministic fake WebAuthn authenticator** and **real** independent
Ed25519 attestations + SQLite + Unix socket. It proves no public TCP bind,
but does not substitute for physical Passkey/browser UV or real IR/KH E2E.

No source-only test proves live FRP continuity; that must be checked during
the separately approved field trial.
