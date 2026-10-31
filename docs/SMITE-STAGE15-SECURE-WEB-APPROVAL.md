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


## Final pre-deployment review for proposed approve.kolbe1.ir (NOT ACTIVATED)

`approve.kolbe1.ir` is proposed only. Independent passkey Origin is exactly
`https://approve.kolbe1.ir` and must differ from the currently deployed
Smite Panel Origin. Do not publish DNS, request a live certificate, configure
Nginx or set `VITE_STAGE15_APPROVAL_ORIGIN` in this PR.

**Read-only IR preflight before approval:** record `nginx -T` and
`nginx -t` outputs (do not reload), inspect all `listen 443` /
`server_name` entries for duplicate `approve.kolbe1.ir`, verify the
current Panel domain and current numeric XHTTP route includes are intact.
Check existing wildcard/default server and TLS certificate paths; certificate
must belong to the new host. Nginx SNI virtual host reuses *existing*
443; no extra public listening port. Record read-only `ss -lntp`,
`getent group`/Nginx worker GID, Socket parent traversal and group.
If DNS is Cloudflare-proxied, explicitly review origin/TLS, access control,
WebAuthn Host/Origin forwarding and trust boundary first; do not assume proxy
mode. These live checks were NOT performed from GitHub CI.

**Fix in source:** choose a separate runtime directory
`/run/u-opti-smite-review`, mode `0750`; the launcher sets ONLY this
directory and `web-approval.sock` to the approved Nginx worker GID.
Socket mode is `0660`; the independent Root audit, credential and HMAC
files remain `0600/0400` inside separate `0700` Root directories.
Broker's `/run/u-opti/smite/xhttp-broker.sock` and its GID are untouched.
Review systemd `RuntimeDirectory` / `ReadWritePaths` / sandbox before
activation; `Restart=no` deliberately requires manual reconciliation if
the root review service crashes. Never chmod secrets to Nginx's group.
Use explicit static templates in `docs/examples/` only after approval.

### Expired queue / uncertain result

Expired proposals are **never garbage-collected, overwritten or retried**.
They remain visible as HOLD until an exceptional, independent reconciliation.
For a proposal older than ten minutes, the root-only CLI
`smite-stage15-approval-reconcile.py --close-expired SHA256` may create
a durable closure receipt **only** if all current root-side read-only checks
prove: root grant absent, route file absent, transaction journal absent,
original signed nonce unconsumed in the broker ledger, and `nginx -T`
contains no matching route/path. It requires local IR root TTY and an
explicit `REVIEW SHA256` confirmation. Any incomplete or uncertain
inspection, route or journal found, consumed nonce, or changed Nginx
configuration -> HOLD, no deletion and no reapplication.
`closed-<digest>.json` preserves the decision; the original
`proposal-<digest>.json` remains for audit. A subsequent *new* signed
intent for the child may stage only after a verified closure. This
exceptional root recovery flow is **not** part of normal tunnel creation.

### Lease consistency and freshness

The approval root collector must read the **authoritative live mounted**
Panel SQLite database read-only, not a periodically exported or cached file.
Production config calls this `panel_live_db_path`; a stale export path is
not a supported source. Each review opens one new SQLite `mode=ro`
connection and one bounded (`<=3 s`) consistent `BEGIN` transaction:
schema, `quick_check`, owner/child identity, status and unique lease
read within the same transaction. It rejects changed source inode,
non-regular/symlink paths, unavailable WAL, changed or incompatible
schema and uncommitted/invalid state. The read-only mount must expose
consistent SQLite WAL/SHM companion files where needed; do not copy a
live `*.db` independently of its WAL into the reviewer.
The source mount identity, exact Docker volume and ability to see a
harmless **committed** lease change must be verified read-only at rollout:
the application cannot cryptographically prove that an operator supplied
the *live* volume rather than a stale copy of it. If that proof is
unavailable: HOLD, do not enable the service.

### Live IR/KH field-trial migration boundary (2026-10-31; source-only)

Read-only operator audits (not a deploy or client-data E2E test) confirmed:

- IR `smite-panel` image `sha256:4abfd55d5c18d95119f8bae4c790cb2b687c54355836ea5529c8aff8a53dcd09` is healthy with zero restarts. Its effective three-file Compose graph contains **only** `smite-panel`, has **no** `depends_on`, and uses `network_mode: host`.
- IR `smite-node` and KH `smite-node` are both healthy at `sha256:cf0f3b12fc2c31cb0847fd5206304837661019d8f604853a8e956448c2576265`, zero restarts. IR's one FRPS process owns the control socket 7000 and child sockets 45121, 38658, 28897; its PID belongs to `smite-node` **and not** `smite-panel`.
- KH `smite-node` contains **three** FRPC processes (expected for the three active child paths), `3xui-01` is running, Signed WSS and Sanaei Inventory journals are COMMITTED. Do **not** consolidate the three FRPC processes.
- IR Stage15 active runtime / WSS / edge / XHTTP bridge journals are COMMITTED. Four IR Trusted Grants and six XHTTP route-directory entries exist; never assume an empty grant/route tree. The Bridge journal filename is `journal.json`, unlike the other Stage15 `record.json` receipts.
- Separate consistent SQLite backup API snapshots of IR Panel+Replay+Broker nonce and KH Replay+Sanaei DB, plus password-protected GPG security backups on both hosts and a separately encrypted KH tunnel registry, were operator-verified. These backups **do not** imply a replay-safe restore, an atomic cross-database snapshot, or a successful disposable-clone recovery rehearsal. The original root broker ledger and signed replay inodes must not be silently replaced or rolled back.
- Root-only IR broker is active; the web-approval marker and pending queue were not configured at audit time. Those facts must be rechecked immediately before any future approved rollout.

The narrow IR Panel process/Compose isolation is now **observed**, not merely inferred. This does **not** mean a new Panel image is approved: preview ZIP/source checks are not signed image attestation and do not prove UI/db/API compatibility or a reversible live one-service migration. The existing `smite-stage15-active-runtime.py` migration admission predates active child leases and XHTTP routes and is **not** reusable for a new Panel cutover; legacy paired menu `U` is also forbidden.

Source-only safety helper `modules/smite-stage15-live-migration-gate.py audit` checks current IR/KH host/Node/Panel image identities, IR Compose-only isolation and exact FRPS ownership, KH three FRPC and listeners. It executes read-only Docker/ss commands and always reports `UNSIGNED_PREVIEW_ACTIVATION=DENIED`, `NODE_RECREATE_WITHOUT_MAINTENANCE=BLOCKED` and `LIVE_MIGRATION_AUTHORIZED=NO` even on audit PASS. It is **not** an apply/dry-run/rollback command. It must not be installed or run as part of this PR's source-only work without independent review; a later field-trial run still requires fresh attestations.

**HOLD on Node image rollout:** current FRPS/FRPC live inside the Node containers. A Node restart/recreate can break all three tunnels. No transaction/copy-based rollback makes that change zero-downtime; do not advertise it. With an absolute no-interruption requirement, separately design/review a non-disruptive independent evidence adapter or defer Node deployment. With an approved maintenance window, separately verify signed candidate images, rehearse exact previous-image/volume rollback on disposable clones, and obtain explicit host-specific authorization before any cutover. Physical Passkey and fourth-tunnel tests remain pending.

### Safe image migration: two explicit maintenance boundaries

No changes to currently active images in this PR. Record precise current
IR and KH image IDs, `docker inspect` mounts/Env/network/PIDs,
Signed Pairing and Replay identity files, WSS/FRPS owner/child inventory,
active routes, listener PIDs and reversible image digests before any step.
Snapshot IR and KH and perform a recovery rehearsal on disposable clones.
Stage future signed images by digest; never use mutable `latest`.

1. **Root reviewer deployment (IR host, separate service):** inert
   bootstrap first, independent keys/read-only Panel volume, then
   dedicated Nginx vhost and UDS service only after TLS and hostname approval.
   Broker opt-in marker is final, not first; old root-console flow stays
   available before opt-in.
2. **Panel upgrade (IR):** replacing only `smite-panel` likely requires
   a controlled container recreate/restart (short management UI disruption).
   Do NOT recreate/restart `smite-node` as part of this step; inspect
   Compose's true dependency graph first and use a one-service migration.
   If Compose would restart the Node: HOLD and redesign plan.
3. **Node upgrade (IR and KH):** the new Signed Agent read-only attestation
   endpoint and separate key mount are inside the Node image. Deploying them
   may require restarting/recreating each `smite-node`. The live IR FRPS
   owner is tied to IR Node and the KH FRPC singleton to KH Node. Therefore
   such a recreation **may interrupt all three active client tunnels**;
   zero-downtime cannot be promised. **Never perform it automatically.**
   Obtain explicit approval for a maintenance window, actual exact
   container-impact map and per-node rollback. If the stated goal remains
   strictly no interruption, this is a deployment blocker and a separate
   non-disruptive evidence adapter design must be reviewed first.
4. After each *approved* migration, verify unchanged FRPS singleton
   `FRP-IR-KH-45121`, Signed Pairing/replay identity, 45121,
   38658, 28897 loopback listeners, XHTTP paths, WSS control, all three
   real client connections and no new FRPS process. Reapply of the FRPS
   Owner is forbidden. An unexpectedly changed PID/route, broken signed
   proof or missing recovery point requires stop and rollback.
5. Only after all security preflight and Passkey registration pass may
   the operator approve the review service/Panel opt-in. Fourth tunnel
   requires a **new** unused Child ID, Lease, port and path; create,
   Verify, XHTTP choose, independent Passkey approval and automatic
   one-time publish; confirm client data transfer. Old three remain
   connected through the same shared FRPS Owner.

### Rollback gates

Review service failure: disable only the independent service + new vhost
and the broker root-owned opt-in marker via an approved transaction,
retain audit/nonce/queue/grant evidence. Panel failure: restore pinned
previous Panel image **without** touching the Node, FRPS Owner or Replay.
Node migration failure: stop immediately; restore only the affected
pinned previous Node image and exact retained volumes/config *under the
approved maintenance/rollback plan* and reconcile any WSS/FRPC/FRPS
runtime disruption. Never restore a stale nonce/replay DB separately;
missing or old replay state is quarantine/HOLD, not automatic repair.
Avoid touching Grandoptical throughout.

### Acceptance criteria for first live fourth tunnel

Both independent Admin Passkeys (main + backup) registered/recoverable,
valid TLS/Origin and CSRF checks, signed IR/KH/lease evidence fresh,
no unmanaged/second FRPS, exact one-use broker grant and nonce, published
new route, real VLESS+XHTTP traffic succeeds, and continuous/reverified
operation of existing 45121, 38658 and 28897. Record all exact image IDs,
Node/FRPS/FRPC PIDs and before/after public checks. **Nothing in this
draft claims those live conditions have passed.**
