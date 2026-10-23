# NEXT-5.AG — Smite RC.1 to RC.2 disposable two-host rollout gate

**Current status (2026-10-23, NEXT-5.AT): IR Panel RC.2 trial is running
successfully with its original signed RC.1 local Node; this was independently
verified with healthy image pins, effective Compose SHA256, and HTTP/HTTPS 200.
KH is still RC.1 Node in paused/strict/managed mode, Sanaei and XHTTP
unchanged. Operator reports both provider snapshots ready. No KH image change,
foreign signed pairing, production rollout, stable merge or release approved.
This remains a review runbook in [U-OPTI draft PR #48](https://github.com/aghajani82/u-opti/pull/48).**

This runbook is intentionally **not** an executable installation script. Passing
checks or collecting snapshots is **not** authorization to alter the hosts or
to release U-OPTI stable. Always label interactive commands with their target
server role (IR / KH / BOTH).

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
