# KH Node — private identity + replay SQLite mount admission (read-only)

**2026-10-20 | [U-OPTI consolidation Draft #48](https://github.com/aghajani82/u-opti/pull/48) | [Closeout Issue #47](https://github.com/aghajani82/u-opti/issues/47)**

**Status: OFFLINE PREFLIGHT ONLY. No Docker apply, no signed-mode activation, no live IR/KH work.**

## Why this is necessary

The existing U-OPTI Stage9 `smite-node-auth-candidate.py` already produces
an **inert** Smite Node Compose security override. It binds the U-OPTI paired
identity directory into the Node at `/run/smite-node-identity:ro` and a
separate private replay directory to `/var/lib/smite-node/auth:rw`.
This preserves the current Node's validated localhost:8888 and legacy base
Compose while allowing future signed-mode admission.

However, merely preparing those Compose lines cannot demonstrate that a
real paired identity, **durable first enrollment marker**, and the **real
SQLite replay database** correspond to the same Node and replay location.
Blindly applying an old candidate after DB loss could lead to a misleading
or unavailable strict Node; replacing the DB would be a replay vulnerability.

## New real U-OPTI implementation

`modules/smite-node-replay-mount-admission.py` is a **read-only** KH
preflight, packaged in both the first installer and interactive updater.
It can be run only by an explicit operator review; it is **not** invoked
by U-OPTI startup, Docker Compose or Smite's Agent API.

It validates all of these before reporting the **limited local pass**:

1. `/etc/u-opti/smite/state.env`: Standard mode and exactly KH
   (`SMITE_ROLE=foreign`); the existing Node Compose must have one
   `smite-node`, `network_mode: host`, the approved localhost:8888
   Uvicorn command and known volume layout.
2. `/etc/u-opti/smite/identities/node-identity.json`: existing paired
   Node ID/secret JSON (secret NEVER printed), within a current-UID-owned,
   private 0700 directory, the file regular/0600 with a single link.
3. `/etc/u-opti/smite/identities/replay-enrollment.json`: separate
   one-time Smite provisioning marker, private regular/0600 and bound
   to the same Node ID and **exact container replay path**
   `/var/lib/smite-node/auth/agent-replay.sqlite3`, NOT the bind-mounted
   host source. Smite's first-enrollment marker now also includes the
   `key_binding` HMAC commitment to its paired Node ID and secret.
   The U-OPTI checker verifies that commitment using the same
   domain-separated `smite-replay-key-binding-v1:` formula as Smite's
   Strict runtime. Old 4-field markers, secret changes using the same
   Node ID and path drift HOLD instead of silently migrating.
   The marker must come from reviewed Smite
   `replay_enrollment.provision_once`, never be fabricated.
4. `/var/lib/u-opti/smite-node-security/replay/agent-replay.sqlite3`:
   exists under separate private 0700 host directories, file owner and
   mode 0600, single hardlink, valid SQLite v1 schema, `PRAGMA quick_check`
   passing and `replay_store_identity` exactly matching the paired ID.
   This is **offline only**: any `-wal`, `-shm` or `-journal` sidecar,
   or a WAL-mode database, is HOLD until a separately approved quiescent
   checkpoint. SQLite opens as `mode=ro&immutable=1` to prevent creating
   shared-memory files. It does NOT inspect a hot/running Node store.
   A missing, corrupt or different-identity SQLite file is **HOLD**;
   NO automatic initialize/reset/restore.
5. `/opt/smite-node/docker-compose.security-candidate.yml`: an existing
   **exact byte match** to the reviewed Stage9 candidate, private 0600,
   with `identity:/run/smite-node-identity:ro`,
   `replay:/var/lib/smite-node/auth:rw`, and precisely corresponding
   `SMITE_AGENT_IDENTITY_PATH` and `SMITE_AGENT_REPLAY_DB`.
   Drift, symlinks, wrong modes or an unknown additional service HOLD.
   This **does not apply** the YAML or merge it with active Docker state.

Example for a **separately approved, disposable KH sandbox** that has
already completed pairing and reviewed first enrollment; NOT for live KH:

```bash
# KH — READ-ONLY REVIEW; only on a separately approved disposable snapshot-backed test host
python3 -B /usr/local/lib/u-opti/modules/smite-node-replay-mount-admission.py --review-only
```

Even when it prints `KH_PRIVATE_BIND_MOUNTS_OFFLINE_PREFLIGHT_PASS`, it also
prints `DOCKER_COMPOSE_APPLY=NO`, `REPLAY_DB_BOOTSTRAP=NO`,
`INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`,
`PERSISTENCE_REBOOT_TEST=NOT_DONE`, and
`SAME_IDENTITY_SNAPSHOT_ROLLBACK=NOT_PROVEN_SAFE`.

## Tests

`tests/test-smite-node-replay-mount-admission.py` exercises the **real
read-only checker** using disposable filesystem paths, actual SQLite
tables/nonce schema, and the exact Stage9 Compose generator:

- Positive review leaves identity, marker, SQLite and both Compose files
  unmodified; permits only the expected RO/RW bind endpoints.
- Missing DB after first enrollment holds; missing/mismatched/foreign
  marker, missing/wrong key_binding, host DB path in a container marker,
  silent same-ID key replacement, mismatched Node identity, invalid
  SQLite schema, 0644
  permissions, active WAL/journal sidecars and WAL database mode hold.
- Writable identity mount, read-only replay mount, wrong runtime path,
  modified Compose content, wrong KH role or symlink marker hold.
- Source review denies Docker/host write and any replay DB bootstrap
  in this checker. It is packaged in first install and update.

## Cross-repository Strict compatibility fix — 2026-10-20

Before this change, U-OPTI expected Smite's old four-field
first-enrollment marker and an absolute **host** SQLite path; Smite
Draft #16's actual runtime records the path visible **inside the
container** and verifies a domain-separated HMAC commitment binding
the marker to the same Node secret. Consequently valid newly
enrolled Strict Nodes were incompatible with the old U-OPTI preflight.
This exact source/protocol mismatch is now covered by real filesystem
and SQLite tests.

This check is KH-only. It does **not** verify the *IR Panel*
SQLite old-key revocation witness created by Smite's
`panel/app/recovery_snapshot_admission.py`; that recovery witness
needs a separate independently pinned SHA256 and an operator-approved
offline restore on IR. A successful KH pass never means Panel
rollback was detected or signed traffic may resume. The CLI explicitly
reports `PANEL_BACKUP_REVOCATION_WITNESS=NOT_VERIFIED`.

## Still **NOT** established

- **Important evidence update (2026-10-20):** The separate, existing
  disposable Docker Compose test now checks actual merged mounts from
  `docker inspect` (RO identity, RW nested replay and named parent volume),
  creates the replay DB explicitly before startup, tests signed→paused→signed
  container force-recreation and old-nonce denial, and confirms signed 503
  after DB loss with refusal to re-enroll. [Full proof](SMITE-NODE-DOCKER-RECREATE-REPLAY-CI-EVIDENCE.md)
  and [CI 39404517558](https://github.com/aghajani82/u-opti/actions/runs/39404517558)
  (16/16 PASS). **The local static `PASS` still does not mean production
  Compose may be applied.** CI proves one ephemeral runner's container
  recreation, not physical storage durability across provider reboot or
  recovery of stale snapshots.
- The new Smite offline provisioning tool writes the marker beside the
  identity. If the identity bind is read-only at runtime, it must be
  provisioned through a **separate approved offline process before
  starting the strict container**. The checker never tries to write
  via a read-only identity mount.
- Private directory checks cannot certify independent storage failure
  domains, real reboot, external snapshots, unexpected same-UID/root
  adversarial modification, or image signature/digest authenticity.
- **Rollback of a previous same-Node SQLite replay snapshot can restore
  previously accepted nonces without being detected by schema or ID
  verification.** Continue to quarantine signed traffic until a
  coordinated key rotation or reviewed timestamp window and snapshot
  provenance are independently approved and tested.
- This helper does not migrate v0.1.7 nodes, start/restart containers,
  change firewall, Nginx/443, 3x-UI, Panel, FRP or Backhaul.

## Next real release work

Isolated Docker Compose nested-mount precedence, recreated-container
nonce persistence and lost-replay fail-closed behavior now have positive
CI evidence. **Next:** design and negative-test authorized, trusted-time
snapshot/replay-store quarantine or coordinated signed key rotation and
verify the complete pairing/mount lifecycle without automatically enabling
strict mode. Finish independently installable Backhaul, novice IR→KH
workflow, signed image release provenance and separately approved
snapshot-backed VPS reboot tests.

**`MAIN_MERGE=NO` · `RELEASE_PUBLISH=NO` · `INSTALL_ALLOWED=NO`
· `ACTIVATION_GATE=HOLD` · `IR_KH_UNCHANGED=YES`.**
