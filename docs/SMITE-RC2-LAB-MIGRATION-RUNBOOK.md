# NEXT-5.AG — Smite RC.1 to RC.2 disposable two-host rollout gate

**Current status (2026-10-24, NEXT-5.AY): IR Panel RC.2 and its
co-located signed IR Node RC.1 passed independent post-cutover checks.
KH Node RC.2 independently passed all 11 post-cutover health, image,
security, Sanaei, XHTTP, Nginx, loopback and KH-to-IR HTTPS checks.
KH foreign signed pairing is still PAUSED and not yet activated; no
managed-state RC.2 transition has occurred. Neither production rollout,
stable merge nor release is approved. This remains a review runbook in
[U-OPTI draft PR #48](https://github.com/aghajani82/u-opti/pull/48).**

This runbook is intentionally **not** an executable installation script. Passing
checks or collecting snapshots is **not** authorization to alter the hosts or
to release U-OPTI stable. Always label interactive commands with their target
server role (IR / KH / BOTH).

## NEXT-5.BJ — Origin approval HOLD after operator confirmation

On 2026-10-24 the IR operator used the pinned three-file stage and
`UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES`
`UOPTI_SMITE_IR_RC2_ORIGIN_APPROVAL=YES`
with `smite-rc2-ir-foreign-origin-approval.py --apply` and typed the
exact interactive confirmation `APPROVE-KH-ORIGIN`. All prep checks
passed (`IR_RC2_PANEL_ADMISSION`, `NODE_KH_RESERVATION`,
`KH_PRIVATE_TLS443_READINESS`). The wrapper then emitted
`IR_FOREIGN_ORIGIN_APPROVAL=HOLD` and
`DO_NOT_REPEAT_AFTER_PARTIAL_FAILURE=YES` without an underlying cause.
**Do not assume success, nor blindly retry --apply.**
No Pairing code, credential redemption, Replay or KH activation is
known to have occurred.

**Source-rooted likely regression:** reviewed Smite Panel RC.2
`approved_node` normalizes the HTTPS gateway `origin` to
`https://kh.kolbe1.ir:443` and the `control_url` to
`https://kh.kolbe1.ir:443/smite-node/<private-prefix>`. The
existing U-OPTI approval helper saved the operator-validated control
URL without explicit default port and then compared raw string
`p["control_url"] == sys.argv[3]`; this rejects an otherwise
authorized, equivalent normalized Panel read-back and triggers its
restoration path.

The draft controller has been corrected to compare BOTH exact
canonical `p["origin"]` and `p["control_url"]` against reviewed
normalized origin/path. Its IR wrapper pinned source Git blob SHA1
has been advanced to the corrected controller, and the old
foreign approval unit test now reproduces the explicit :443
read-back regression. This is **source-only** pending CI and
separate operator approval; no command may be rerun on IR until
a **read-only after-HOLD trust-state forensic audit** checks
the preserved Iranian trusted record, number/status of foreign
origin records, private file ownership/permissions, pending DB
reservation, and unchanged Panel image. In particular, do not
generate a second pairing code or perform destructive rollback.

## NEXT-5.BG/BH — verified reservation, foreign Origin read-only readiness

Operator 2026-10-24 independently verified the first admin-reserved
`node-kh` database row: `FOREIGN_NODE_COUNT=1`,
`NODE_NAME=node-kh`, `NODE_STATUS=PENDING`,
`RESERVATION_MODE=SIGNED`, `IR_FOREIGN_RESERVATION=PASS`,
`LIVE_CHANGES=NONE`. The pairing code has not been issued.

Operator's IR pre-approval review confirmed:
`PANEL_DATABASE=PASS`, `PAIRING_SCHEMA=PASS`,
`SINGLE_FOREIGN_RESERVATION=PASS`, `NODE_KH_PENDING=PASS`,
`TRUST_FILE_SECURITY=PASS`, `TRUST_SCHEMA=PASS`,
`TRUST_BASELINE=PASS`, `PANEL_RC2_RUNTIME=PASS`,
`TRUST_STORE_MOUNT=PASS`, `IR_TO_KH_PUBLIC_TLS443=PASS`,
`IR_FOREIGN_ORIGIN_PREFLIGHT=PASS`,
`ORIGIN_APPROVAL=NOT_APPLIED`, `PAIRING_CODE=NOT_CREATED`,
`LIVE_CHANGES=NONE`.
The public TLS check confirms reachability, not the exact private
KH control path. **Foreign trust remains unmodified.**

A new draft-only
`modules/smite-rc2-ir-foreign-origin-approval.py` provides separate
`--plan` and `--apply`. Both require root on IR, interactive
terminal, pinned-source SHA1 verification for the controller and
read-only admission, exact pending `node-kh` and existing signed
IR local-node trusted record, exact reviewed RC.2 Panel transport,
and the operator-entered KH HTTPS/443 control prefix. The private
prefix is obtained on KH from its locally root-owned gateway metadata
and must be copied **only between operator-controlled terminals**,
not posted to this PR or support chat. IR receives it by hidden
`getpass` prompt, validates exact host/path, performs CA-validated
no-proxy/no-redirect readiness GET against the exact prefix and
does not display the prefix or foreign Node ID.

`--plan` makes zero live changes. A future **separate** `--apply`
also requires both `UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES` and
`UOPTI_SMITE_IR_RC2_ORIGIN_APPROVAL=YES`, plus interactive
`APPROVE-KH-ORIGIN` confirmation; only then it delegates the
additive origin write and read-back/rollback to the previously
reviewed pairing controller. It must not issue a code, redeem an
identity, provision Replay or activate the KH Node. Stop on any
HOLD/CRITICAL. No production approval.

## NEXT-5.BE — foreign Node reserve database gate PASS, next name-only UI step

Operator IR read-only query reports `PANEL_SIGNED_SCHEMA=PASS`,
`FOREIGN_NODE_RECORD_COUNT=0`, `FOREIGN_PENDING_RESERVATIONS=0`,
`FOREIGN_SIGNED_ACTIVE=0`, `IR_RESERVATION_REVIEW=PASS`,
`LIVE_CHANGES=NONE`. No existing Foreign Node reservation exists; this
is the first controlled enrollment, not an existing identity recovery.

Verified upstream Smite RC.2 Panel frontend and backend source at
`e6c3ecce81010130ae28e7d1e37ea99b31d70c28`:
`frontend/src/pages/Servers.tsx` secure-preview *Add Server* route
displays **Prepare secure Foreign Node**, requires only Node name, and
POSTs `/node-pairing/reserve` with JSON `{name}`, not legacy
`/nodes` registration with IP/port.
`panel/app/routers/node_pairing.py` requires authenticated admin and
enabled pairing preview, checks unique name, and creates precisely
`status=pending`, `metadata.role=foreign`,
`metadata.node_name=the supplied name` and
`metadata.provisioning=reserved_for_pairing`. It performs no call to
KH and does not issue a pairing code or create a credential.

**Next controlled action**: inspect only `SMITE_NODE_NAME` and role
from root-managed KH state, then in IR Panel's **Servers** view use
**Add Server** ONLY if the secure-preview modal displays
**Prepare secure Foreign Node** with name-only entry. Submit exact
KH managed Node name. **HOLD** if old modal requires IP/port or secure
preview is not available. Independently check the IR Panel SQLite
reservation count and metadata after operator action. Never paste
short-lived pairing code or key in PR/chat, and do not issue a code,
redeem identity, write Replay or activate signed Node yet.

## NEXT-5.BD — operator identity and Replay inventory

On 2026-10-24 the operator ran read-only artifact checks on **both**
test hosts after RC.2 pre-admission:

- **IR:** `IR_TRUST_STORE=READY`,
  `IR_FOREIGN_ORIGIN_COUNT=0`, `IR_PANEL_DB=PRESENT`.
- **KH:** `KH_SIGNED_IDENTITY=NOT_STAGED`,
  `KH_REPLAY_DB=NOT_PROVISIONED`,
  `KH_REPLAY_MARKER=NOT_PROVISIONED`.
- **Both:** `FOREIGN_PAIRING=NOT_ACTIVATED`,
  `LIVE_CHANGES=NONE`.

The missing KH identity and Replay store are an expected unpaired
initial state, not damaged state and not grounds for replay reset or
unsigned legacy fallback. Zero IR approved Foreign origins does **not**
establish whether the Panel already contains an admin-reserved pending
foreign Node record. The exact next gate is a **read-only Panel DB check**
for schema and foreign pending-reservation counts. No Node UUID,
secret or pairing code should be echoed into logs or support chats.

Intended stage order after all gates: (1) confirm Panel signed schema and
reserve an exact foreign Node UUID/name through approved Panel workflow,
(2) separately approve the specific KH TLS/443 control origin on IR
without changing the local Node, (3) issue a short-lived one-time
pairing code, (4) redeem on KH over verified HTTPS to write root-owned
0600 identity once, (5) provision identity-bound Replay marker/DB once,
(6) opt in to KH RC.2-only signed activation with a separately verified
paused/strict/managed rollback and a true dual-direction HMAC check.
Individual stages require independent authorization; the old RC.1
wizard option 7 must not be used against KH RC.2. Production release
and stable merge remain disallowed.

## NEXT-5.BC — dual-host RC.2 foreign admission PASS and isolated code lane

Operator independently ran `smite-rc2-foreign-pairing-admission.py`
from pinned, Git-blob-verified source commit
`9e69d08c2972627ac3e996bd73a52bdeb74e1cf8`:

- **IR**: `IR_PANEL_RC2_SIGNED=PASS`,
  `IR_LOCAL_NODE_RC1=UNCHANGED`,
  `IR_TRUST_MOUNT=READ_ONLY`,
  `IR_FOREIGN_PATH_HMAC_POLICY=PASS`, `IR_HTTPS_STATUS=PASS`.
- **KH**: `KH_NODE_RC2_PAUSED=PASS`,
  `KH_GATEWAY_TLS443=PASS`, `KH_SANAEI_XHTTP=UNCHANGED`,
  `KH_TO_IR_HTTPS=PASS`,
  `KH_FOREIGN_SIGNED_RUNTIME=NOT_ACTIVATED`.
- Both: `RC2_FOREIGN_PAIRING_ADMISSION=PASS_READ_ONLY`,
  `FOREIGN_PAIRING=NOT_ACTIVATED`, `LIVE_CHANGES=NONE`.
  These are two independently executed local read-only audits, not a
  successfully enrolled cross-host HMAC pair.

**Draft-only source correction:** legacy pairing's
`--activate-foreign-node-field-trial` continues to use original
immutable RC.1 gate. A separately named
`--activate-foreign-node-rc2-field-trial` option has been added to
`modules/smite-node-pairing.py`; it is NOT part of the deployed server
wizard, and MUST NOT be executed at this stage. It requires the
pre-existing root-only Field Trial gate plus distinct explicit
`UOPTI_SMITE_RC2_FOREIGN_PAIRING_FIELD_TRIAL=YES` opt-in. Before any
runtime mutation it reruns the exact immutable RC.2 dual-host
read-only admission **on KH**, checks that the KH Node digest equals
the approved RC.2 digest, KH Node base Compose SHA256 exactly equals
`8339ee07dcc3fe68da65dd8cb993b11d8da20b69b0470c032f8d504b0ea9de4e`,
effective Compose still has `paused + strict + managed` auth, the
running Node is healthy, and HTTPS/443 Gateway returns the required
readiness document. The IR approval guard now explicitly requires
the reviewed immutable RC.2 Panel image rather than any other
well-formed image digest.

The activation algorithm retains its signed HMAC + Replay checks,
foreign Gateway signature validation, and paused-mode rollback.
Recreate command was limited to `smite-node` with `--no-deps` and
`--pull never`. Offline tests cover distinct RC.1/RC.2 gates,
missing consent and missing independent admission, immutable image/
Compose drift, rejection of unreviewed IR Panel images and no
Sanaei/Panel changes from KH. A green CI is **not** real Pairing proof;
identity reservation, exact foreign trust approval, one-time pairing
credential, replay history and failure-recovery procedure still need
operator-driven staged checks and a separate explicit live decision.

## NEXT-5.BA/BB — independent Panel transport and version-aware admission

**Operator result (IR, 2026-10-24):**
`IR_RC2_FOREIGN_HMAC_REVIEW=PASS`, covering reviewed IR RC.2 Panel
digest and healthy state, unchanged healthy signed local IR RC.1 Node,
exact base/signed-overlay Compose SHA256, positive approved Foreign
gateway prefix, HMAC signed-agent target preservation, root-approved
origin pinning, TLS no downgrade, and rejection of five unapproved
gateway URLs. `FOREIGN_PAIRING=NOT_ACTIVATED` and
`LIVE_CHANGES=NONE`. These assertions inspect running application
code and example URL behavior; they are **not** a live cross-host HMAC.

**Operator result (KH, NEXT-5.AZ):** exact reviewed KH RC.2 Node image
and `paused + strict + managed`; private gateway metadata and
localhost TLS/443 prefixed readiness JSON all PASS. No foreign
enrollment, Pairing or Gateway configuration change occurred.

A new `modules/smite-rc2-foreign-pairing-admission.py` is a
strictly **read-only** command with `--role IR` or `--role KH`.
It checks the mixed-version topology and managed RC.1 state,
signed Panel trust mount and reviewed RC.2 transport (IR), paused
RC.2 Node, exact private Gateway prefix, immutable Sanaei,
single XHTTP route and TLS/443 (KH). The companion offline negative
tests reject unsigned Panel mode, writable Panel trust mount,
unpaused Node, malformed Gateway prefix, changed managed version,
changed Sanaei image, and duplicate environment keys. This tool
offers **no apply mode**; a PASS only admits further source review,
not pairing or activation. The old RC.1-hard-pinned foreign activation
helper remains blocked and unchanged.

**Next:** run the new admission read-only on IR and KH from one pinned
reviewed source commit. Then design, test, and separately authorize
a safe RC.2-aware foreign approval/pairing/activation transaction
that keeps HMAC keys and replay stores intact and can restore KH
to paused mode. Do not use the legacy RC.1 image gate for RC.2.

## NEXT-5.AY — independent KH RC.2 post-cutover PASS; foreign pairing gate

The operator's read-only KH audit after `--apply` confirmed:
`COMPOSE_SHA256=PASS`, `COMPOSE_RC2_IMAGE=PASS`,
`COMPOSE_SECURITY=PASS`, `NODE_RC2_HEALTH=PASS`,
`RUNTIME_SECURITY=PASS`, `SANAEI_UNCHANGED=PASS`,
`NODE_LOOPBACK=PASS`, `NGINX=PASS`,
`XHTTP_GUARD=PASS`, `KH_NODE_HEALTH_HTTP=PASS`,
`KH_TO_IR_HTTPS=PASS`, `KH_RC2_INDEPENDENT_AUDIT=PASS`,
`LIVE_CHANGES=NONE`. Running KH Node pinned digest:
`sha256:2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78`.

**Remaining source compatibility HOLD:** current
`modules/smite-node-pairing.py` still pins
`_FOREIGN_NODE_IMAGE` to immutable **RC.1** while KH runs RC.2.
Its foreign activation path calls `_foreign_gateway_preflight` which
must therefore refuse the present KH RC.2 runtime. The IR approval
function currently requires `SMITE_MANAGED_VERSION=2.0.0-rc.1` and
the RC.2 Panel's foreign path-pinned HMAC support check is broad rather
than tied to the exact reviewed RC.2 image. Do not simply replace a
constant or bypass that check. A separate version-aware rollout admission,
positive/negative signed Gateway tests, exact identity/replay preservation,
explicit origin pinning and safe paused rollback are necessary before
foreign signed pairing is attempted.

**Next operator step:** read-only KH gateway metadata / localhost TLS
readiness inspection. This does not reserve identities, approve origins,
generate pairing tokens or enable signed traffic.

## NEXT-5.AX — KH RC.2 Node-only field trial reported PASS

On 2026-10-24, operator ran the pinned root-private KH-only
`smite-rc2-kh-node-rollout.py --apply --confirm-kh-host kh.kolbe1.ir`
with explicit environment opt-in and interactive `APPLY` consent.
Its completion reported:

- `KH_NODE_RC2_TRIAL=PASS`
- `KH_NODE_SECURITY=PAUSED_STRICT_MANAGED`
- `KH_NODE_8888=LOOPBACK_ONLY`
- `KH_SANAEI_XHTTP=UNCHANGED`
- `KH_TO_IR_PANEL_HTTPS=PASS`
- `KH_NODE_COMPOSE_SHA256=8339ee07dcc3fe68da65dd8cb993b11d8da20b69b0470c032f8d504b0ea9de4e`
- `KH_FOREIGN_PAIRING=NOT_ACTIVATED`
- `MANAGED_VERSION=RC1_RETAINED_DURING_MIXED_TRIAL`
- `NO_SQLITE_OR_REPLAY_RESTORE=YES`
- `PRODUCTION_RELEASE_APPROVED=NO`

This is **runtime executor-reported evidence**, not independent verification.
The previously documented KH RC.1 Node health and paused checks below are
**historical pre-cutover baselines only**. The rollout did not trigger a
rollback, so real-host rollback success is still unproven. Before
enrollment, independently check immutable KH Node RC.2 digest
`sha256:2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78`,
healthy, paused/strict/managed, Compose, Sanaei unchanged original
image, XHTTP guard, Node loopback and HTTPS→IR; then separately review
foreign HMAC pairing code (still RC.1-hard-pinned).

## NEXT-5.AT — actual staged runtime checkpoints

The original frozen RC.1 baseline below is historical and is retained for
rollback reference. **The active runtime is now mixed**:

- **IR**: `smite-panel` runs reviewed RC.2 immutable Panel digest
  `sha256:9101898e19631d334b754ba8e956b63ab7dfaee304a8f9b954cf30a185125e8e`
  and the local `smite-node` remains reviewed RC.1 immutable Node digest
  `sha256:9099262bb0d5fc8b737269f3e6dc16831a1d3e8b536b7b95ba131129ed06a7ec`.
  Both healthy. Combined signed Compose validation PASS and image-only
  Panel Compose SHA256
  `adc4dfb3031d5f2b5c007241589ed96fe9679ac2df29da62853192c7d716ca5a`,
  signed overlay unchanged. Local `/api/status` HTTP 200 and public Panel
  HTTPS `/api/status` 200. Initial rollout reported Panel→local IR signed HMAC
  PASS. No live rollback occurred in this successful trial.
- **KH**: independent NEXT-5.AT audit confirmed Smite Node RC.1 unchanged,
  healthy and `paused + strict + managed`, exactly original Sanaei image ID
  `sha256:6c7e73c5bc4b6d7d70866616f78d6c9866b4904defad3077c1e2b5c1c89c2ec1`
  running, Nginx syntax PASS, XHTTP `ROUTES=1 LEGACY_ROUTE=NO`, Node port
  8888 bound only to localhost, and `KH→IR HTTPS /api/status=200`.
- **NEXT-5.AU** planned: **read-only** KH Node immutable image-line
  transformation and security/backup checks. The foreign node's existing
  pairing helper is hard-pinned to RC.1 and uses RC.1 managed-state admission:
  never change only its constants or blindly toggle signed pairing. Do not
  recreate the KH Node, change 3x-UI/Sanaei, Nginx, XHTTP, FRP/Backhaul, or
  expose Node 8888 publicly until separately reviewed, tested and authorized.
  Upgrading a paused Node image is distinct from foreign pairing or
  activation.

## NEXT-5.AV — guarded KH Node RC.2 rollback executor staged in DRAFT only

Operator ran immutable-source KH read-only plan from
`/root/uopti-rc2-kh-gac0j2w4`. The exact original Compose SHA256
`ab0f360f288c4659a52ec5e4f5b67afd22ec21dcc29a328d72cd8829b91eae6f`
and in-memory proposed RC.2 Compose SHA256
`8339ee07dcc3fe68da65dd8cb993b11d8da20b69b0470c032f8d504b0ea9de4e`
matched operator evidence. The operator's report confirmed paused/strict/managed
KH Node RC.1 healthy, Sanaei and XHTTP unchanged, both KH backup SHA256s
verified, `KH_RC2_NODE_PLAN=PASS` and `LIVE_CHANGES=NONE`.
No KH container has yet been recreated.

The separate experimental source file
`modules/smite-rc2-kh-node-rollout.py` has an inert default `--plan`
and guarded `--apply` (not used or installed). Apply requires exact
`kh.kolbe1.ir` confirmation and
`UOPTI_SMITE_KH_RC2_NODE_FIELD_TRIAL=YES`, root ownership and exclusive
lock, frozen old/new Compose hashes, preserved KH backup checksums and
positive Cosign image-signature validation using the independently pinned
`/usr/local/bin/cosign` (no PATH shadowing). Its only contemplated live
change is the exact KH Smite Node image line and recreating the **single**
`smite-node` service with `--no-deps --no-build --pull never`, never
Sanaei, Nginx, XHTTP, FRP/Backhaul, or the IR Panel.

It insists effective Compose JSON differs **only** in Node image, retains
`paused + strict + managed`, and after recreation verifies the new
immutable Node digest, Node health and loopback `/healthz`, local-only
8888 listener, unchanged Sanaei image/status and XHTTP guard, plus KH→IR
HTTPS Panel status. KH foreign signed Pairing remains **NOT ACTIVATED**.
Managed version intentionally remains RC.1 during partial trial.

On any failed cutover it restores original Compose bytes atomically and,
if the Node was recreated, re-creates the original immutable RC.1 Node and
re-verifies all guards. It never restores stale Replay history, deletes
WAL/SHM, rotates Node identity, or changes external routing. A failed
rollback raises **CRITICAL HOLD** instead of claiming recovery. The
original Compose is saved `O_EXCL` in the root-private pre-RC2 KH backup
directory. Offline mocked failure tests cover failed RC.2 health, signed
environment drift, post-rename failure, critical failed rollback, consent
gates and unapproved Cosign PATH shadowing; this is **not** a live
rollback rehearsal or release approval.

**Status:** KH stays on RC.1 pending source CI completion, pinned
on-host `--plan`, and an explicit, separate operator decision to execute
`--apply`. Production/stable and foreign Signed Pairing remain HOLD.

## NEXT-5.AU — KH Node image-only admission is plan-only

The draft-only read-only tool `modules/smite-rc2-kh-node-plan.py`
checks the original KH Node Compose SHA256
`ab0f360f288c4659a52ec5e4f5b67afd22ec21dcc29a328d72cd8829b91eae6f`,
computes the exact one-line image replacement from immutable RC.1 Node
`sha256:9099262bb0d5fc8b737269f3e6dc16831a1d3e8b536b7b95ba131129ed06a7ec`
to already independently signed RC.2 Node
`sha256:2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78`,
then verifies a byte-for-byte inverse in memory. It checks exact RC.1
foreign/Standard managed state, paused/strict/managed effective Compose,
healthy running RC.1 Node, unchanged immutable Sanaei image ID and running
status, root-private X-UI backup SHA256 + private KH config archive SHA256,
Nginx syntax, Node 8888 loopback-only, and single valid XHTTP route.

**Never run this tool with `--apply`**: it exposes **no apply mode**.
The tool cannot write Compose, pull images, restart any container, modify
Sanaei/XHTTP, change managed version, enroll HMAC keys, or enable foreign
pairing. It does not independently re-run Cosign (that was previously
confirmed by both host operators). Offline tests cover one-line
reversibility, unsafe YAML drift, unsigned/unpaused Node, changed Sanaei
image, unhealthy Node, public Node listener, and legacy XHTTP route.

After operator KH plan PASS, create and independently test a separate
guarded KH Node-only migration and rollback plan if warranted, then
explicitly authorize it as a separate operation. The existing KH signed
pairing helper still pins RC.1 and **must not** be reused for activation
of an RC.2 image without a separately reviewed compatibility change.

## Ground truth: the frozen baseline

| Host | Running | Tested controls |
|---|---|---|
| IR | `smite-panel` and local `smite-node`: **RC.1** immutable signed images, both healthy | Panel signed enrollment enabled; replay enrollment READY; Nginx/443 healthy; Node 8888 bound to loopback |
| KH | `smite-node`: **RC.1** immutable signed image, healthy, `paused + strict + managed` | Existing 3x-UI runs; KH 443 managed gateway metadata checks PASS; XHTTP guard PASS; Node 8888 bound to loopback |

The operator has separately completed three SQLite Online Backups with
`PRAGMA integrity_check=ok`:

| Role and dataset | Location | SHA256 |
|---|---|---|
| IR Panel | `/root/ir-smite-pre-rc2-20261023T151016Z/smite.db` | `8b7fb3a5681811f850df0f61b5477928b1940eb19d0ffb94632402c9f2489420` |
| IR Replay | `/root/ir-smite-pre-rc2-20261023T151016Z/agent-replay.sqlite3` | `17a5845061e31144115cc171230643a7a249edd9b87435a1f39d6e70c579a8fc` |
| KH Sanaei X-UI | `/root/kh-sanaei-pre-rc2-20261023T150429Z/x-ui.db` | `4b58350aa982389daf0953ef7e447577c8a9fcee40e27f1bfd66c1243a96e740` |

Private configuration archives are **not** shareable and must stay on encrypted,
access-controlled backup storage. Only paths and digests belong in review notes.

| Host | Archive | SHA256 |
|---|---|---|
| IR | `/root/ir-smite-pre-rc2-20261023T151016Z/ir-private-config.tar.gz` | `90849b1be778b5ae12f3347ecc87e51c415e83d02ffabb61b30102f324851e67` |
| KH | `/root/kh-sanaei-pre-rc2-20261023T150429Z/kh-private-config.tar.gz` | `3fe92f5f1bbb7804e7d34d25110d290aa24c4771e6b3d0b827fb0cea0857f719` |

KH original 3x-UI image ID:
`sha256:6c7e73c5bc4b6d7d70866616f78d6c9866b4904defad3077c1e2b5c1c89c2ec1`;
the configured tag `latest` is **mutable** and must not be pulled during
rollback. KH Nginx vhost checksum
`e3f763c792b5f07c387aec70debe67e00fac28a03dd8140169fef1ae19353a39`
and KH Node Compose
`ab0f360f288c4659a52ec5e4f5b67afd22ec21dcc29a328d72cd8829b91eae6f`
are reviewed baseline evidence.

**Remaining evidence gaps**: Snapshot IDs, labels, timestamps and restored
contents have not been independently observed; both backups presently
reside on their origin servers; volume contents beyond the listed files and
cross-database atomicity have not been established. The owner reports
snapshots ready, but the review gate is still **HOLD**.

## Immutable target and explicit anti-fallbacks

Smite source: `e6c3ecce81010130ae28e7d1e37ea99b31d70c28`;
tag `v2.0.0-rc.2`.

- Panel target:
  `ghcr.io/aghajani82/smite-panel@sha256:9101898e19631d334b754ba8e956b63ab7dfaee304a8f9b954cf30a185125e8e`
- Node target:
  `ghcr.io/aghajani82/smite-node@sha256:2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78`

Independent Cosign admission CI in U-OPTI previously passed. This is
**not** equivalent to on-host admission. Do not change the historical
`modules/smite-field-trial-candidate.json` (RC.1), stable installer defaults
or the pinned RC.1 KH activation helper until the new migration operation has
its own independently reviewed and tested state transition.

**Never use existing installer menu `Upgrade signed Field Trial candidate`
for RC.1 -> RC.2**. `smite_install_upgrade_signed_field_trial()` is strictly
RC.0 -> RC.1 and its rollback attempts a destructive live DB file restore,
removing WAL/SHM files. It is not a safe RC.2 rollback.

## Source-level RC.1 -> RC.2 compatibility review (2026-10-23)

GitHub source comparison of Smite `289f99cae8c53ba7d5b8e427bca19e5c04ebba8a`
(RC.1 candidate source) to `e6c3ecce81010130ae28e7d1e37ea99b31d70c28`
(RC.2 tag) lists **five changed paths**: two runtime **Panel** modules
(`panel/app/node_client.py` and `panel/app/signed_agent_transport.py`),
two Panel tests, and one offline image-verification GitHub workflow.
**No Node runtime code changes appear in that GitHub comparison.**

Merged Smite PR #18 extends `signed_agent_call` by an *optional*
`gateway_control_url`, only passed for approved `foreign` origins;
it preserves canonical signed `/api/agent/*` HMAC targets while sending the
HTTPS request through the exact independently approved KH prefix. Approved
`iran` origin dispatch continues without this optional parameter.

**Implication, not live proof:** a *Panel-only* RC.2 candidate change on IR
may be the lowest-risk first cutover while retaining the already-signed
RC.1 local Node until same-version Node compatibility and signature
admission are confirmed. This is plausible from the source diff, **not**
a guarantee of live binary/configuration compatibility. Keep an explicit
hold if local check-in, Panel↔IR signed HMAC, signed override or dual
health is degraded. Do not overwrite the existing mixed RC.1-managed state
or assert full RC.2 completion after only a Panel image change.

Node RC.2 must still be independently verified and migrated through its
own *separate, reviewed* operation on IR/KH if chosen. In particular, the
existing U-OPTI KH pairing helper pins the exact RC.1 Node digest and
requires `SMITE_MANAGED_VERSION=2.0.0-rc.1`. Updating only the host version
or only that pin would bypass transition invariants; dedicated reviewed
RC.2 signed activation integration and tests are mandatory.

Reference: [Smite PR #18](https://github.com/aghajani82/Smite/pull/18),
[Smite RC.1→RC.2 source comparison](https://github.com/aghajani82/Smite/compare/289f99cae8c53ba7d5b8e427bca19e5c04ebba8a...e6c3ecce81010130ae28e7d1e37ea99b31d70c28).

## Stop / go before *any* live image recreation

1. **BOTH**: record provider snapshot IDs/time/labels and verify both IR/KH
   snapshots are present in provider UI; restore rehearsal on isolated
   disposable clones is preferred. Keep both current servers unchanged.
2. **BOTH**: independently re-hash archives/backup files, validate archived
   members, protect owner-only backup directory permissions; run SQLite
   integrity checks on *backups*, without opening live databases in write
   mode. Do not print file contents.
3. **BOTH**: record exact `docker inspect` image IDs, current immutable
   image pin, health, Docker Compose config/overlays/mounts, 443/8888
   listeners, Nginx configuration, and all persistent Docker volumes.
   Preserve private identities and approved-origin configuration securely.
4. **IR**: verify Panel signed overlay actually applied in runtime and local
   signed replay/identity persistent mounts. Review RC.2 Panel↔RC.1 Node
   compatibility before selecting an order for the IR pair. If incompatible,
   prepare a bounded, rollback-capable *joint* IR change, not a blind
   Panel-only restart.
5. **KH**: retain `paused + strict + managed` and exact controlled
   gateway prefix. Verify 3x-UI image ID, Nginx vhost digest and XHTTP
   baseline before/after trial; do not pull/migrate 3x-UI.
6. **BOTH**: on-host verify both RC.2 immutable digests via pinned Cosign,
   source identity and role claims. Do not substitute mutable tags.
7. **BOTH**: only after separately reviewed executable migration + rollback
   rehearsal and fresh explicit operator authorization may the rollout
   recreate reviewed Smite containers.

## NEXT-5.AO — exact IR Panel-only reversible Compose edit (in-memory review)

The operator's NEXT-5.AN live IR Compose admission passed all six checks:
the original Panel RC.1 immutable image, signed registration and Agent auth,
original `/app/data` bind mount, root-owned approved-origins `ro` mount,
and readonly Panel `.env` all appear in the *combined* effective Compose
(`Panel Compose + signed-control override`). No changes were made.

Source-only code in `modules/smite-rc2-panel-compose-review.py` now
computes a candidate IR Panel Compose **in memory** after checking its
original SHA256. It permits *only* replacing exactly one complete
`    image: ghcr.io/aghajani82/smite-panel@sha256:...` line from the frozen
RC.1 Panel digest to the immutable Cosign-verified RC.2 Panel digest.
It verifies an exact byte-for-byte inverse and outputs the old/new
file SHA256. The code never writes either Compose file or changes
running images. `tests/test-smite-rc2-panel-compose-review.py` includes
round-trip and negative drift/duplicate mount/security downgrade tests,
run in CI.

The **target** is Panel-only. On first cutover, continue running the
signed RC.1 local IR Node and leave KH and Sanaei untouched. Preserve
both the existing base Compose and signed overlay; **do not switch
SMITE_MANAGED_VERSION to RC.2** during a mixed-version Panel-only trial.
Only a later separately reviewed, tested transaction can apply this
candidate, with the original RC.1 image and Compose as rollback and
live Panel→IR HMAC verification before declaring success. Never restore
the live SQLite DB from the earlier backup merely to undo an image-only
trial; avoid stale Replay state or WAL destruction. If a future
migration requires a DB schema change, it needs its own recovery gate.

Expected dry-run result:
`IR_PANEL_PROPOSED_DIFF=EXACT_PANEL_IMAGE_LINE_ONLY`,
`RC2_DEPLOYMENT_AUTHORIZED=NO`, `LIVE_CHANGES=NONE`.

## NEXT-5.AP — guarded experimental IR-only Panel transaction staged in code

The operator's 2026-10-23 IR dry-run returned
`ORIGINAL_COMPOSE=VERIFIED`,
`PANEL_ONLY_IMAGE_CHANGE=VERIFIED`,
`ROLLBACK_COMPOSE=REVERSIBLE`,
`PROPOSED_SHA256=adc4dfb3031d5f2b5c007241589ed96fe9679ac2df29da62853192c7d716ca5a`,
`FILES_MODIFIED=0`, and `RC2_ACTIVATION=NOT_PERFORMED`.

In the **draft-only** module `modules/smite-rc2-ir-panel-rollout.py`:
the default plan path verifies the exact RC.1 state, backup SHA256,
original Panel/overlay bytes, effective signed-only Compose and local signed
Node/Panel image health and computes only the exact reviewed SHA256. **It does
not write files, pull Docker images, run HMAC probes or restart services.**
It is not installed on IR or KH.

The separate `--apply` code path is **not approved or run**. It is isolated
behind a literal hostname confirmation AND
`UOPTI_SMITE_IR_RC2_PANEL_FIELD_TRIAL=YES`, root privileges and a
single exclusive cutover lock. It demands the already reviewed backup
checksums and a fresh exact both-role Cosign signature admission from the
pinned binary **before pulling** the immutable RC.2 Panel digest. It saves
a root-only, non-overwritable RC.1 Compose copy before any live mutation.

If a later explicitly authorized operator trial runs, its transaction may
replace ONLY the Panel image line, then revalidate that the combined effective
Compose has changed **only** the Panel image (retaining mounts, signatures,
network, env and healthcheck). It must use both the base and signed Compose
override, `--no-deps` and `--pull never` when recreating ONLY `smite-panel`.
It verifies new Panel health, the KH prefix helper and actual Panel → co-located
IR signed HMAC, and proves the IR local Node stays on the exact RC.1 image.
It does not touch any KH service, Sanaei, XHTTP, Nginx or live SQLite files.

On failure it restores the saved original Compose bytes atomically and, if
recreation was attempted, re-creates ONLY the prior RC.1 Panel. It requires
RC.1 health and Panel→IR signed HMAC again. If rollback cannot be proved,
it stops with an explicit **CRITICAL** status for manual snapshot recovery,
preserving all root-only backups and Replay/identity. It never deletes live
SQLite WAL/SHM or replays an older nonce ledger.

Offline CI mocks cover baseline, explicit consent gate, good Panel-only
upgrade, signed environment drift, unhealthy RC.2, post-rename crash,
rollback and inert default. This is **source-level simulation**, not a
host-based recovery rehearsal or owner approval to apply.

**Current status**: `IR_HOST_RC2_PANEL=NOT_INSTALLED`;
`KH_RC2_NODE=NOT_INSTALLED`; `UOPTI_PR48=DRAFT`;
`LIVE_RC2_ACTIVATION=NOT_AUTHORIZED`.

## Phased trial (plan only; no authorized commands yet)

**A. IR**: stage exact images with manifest and signature verification,
validate Compose effective configuration including security overlays and
mounts, back up SQLite online and private identity/replay at a coherent
cutover, transition reviewed IR Panel and local IR Node, then demonstrate
unchanged TLS/443, signed check-in, replay rejection, and Panel↔IR HMAC.
Do **not** drop a signed Compose override during `up`.

**B. KH**: confirm IR Panel contains the foreign HMAC gateway prefix fix;
only then stage KH reviewed Node digest. Maintain existing Nginx, certs,
Sanaei image/database, FRP/Backhaul and XHTTP untouched. Keep Node paused
until trusted-origin approval, one-time identity enrollment and durable replay
are validated. Resume signed traffic only on positive bidirectional tests.
Never use an unreviewed new Node digest with hard-coded RC.1 gate.

**C. Acceptance**: signed KH → IR check-in, IR → KH HMAC Agent GET
through exact HTTPS/443 prefix, negative replay/no-key/revoked-key/unsigned
tests, no anonymous fallback, endpoint health, untouched Sanaei/XHTTP and
reboot persistence. A green gateway icon alone is insufficient.

**D. Rollback**: if IR signed traffic or KH safe activation fails, stop
the rollout and keep KH paused/strict. Restore the exact saved image and
Compose+overlays/volumes or the **coordinated pair of provider snapshots**
as appropriate. Treat restored *older* Replay history as potentially stale:
do not resume old HMAC identities without verified replay reconciliation or
key rotation and re-enrollment. Never blindly copy a SQLite DB over a live
writer or manually delete WAL/SHM; verify application consistency after
recovery. Do not automatically delete any backup on failure.

## Release authorization

- `PR48=DRAFT`
- `RC2_CANDIDATE_ACTIVATION_ALLOWED=false`
- `RC2_RELEASE_APPROVED=false`
- `IR_KH_IMAGE_MIGRATION=NOT_EXECUTED`
- `ROLLBACK_REHEARSAL=NOT_VERIFIED`
- `HOST_ACTIVATION_AUTHORIZED=NO`

This runbook does not by itself grant any additional approval.
