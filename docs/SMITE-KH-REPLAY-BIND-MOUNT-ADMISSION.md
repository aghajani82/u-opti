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
   to the same Node ID and the **exact host DB path**. It must come from
   the reviewed Smite offline `replay_enrollment.provision_once` process,
   not be manually fabricated.
4. `/var/lib/u-opti/smite-node-security/replay/agent-replay.sqlite3`:
   exists under separate private 0700 host directories, file owner and
   mode 0600, single hardlink, valid SQLite v1 schema, `PRAGMA quick_check`
   passing and `replay_store_identity` exactly matching the paired ID.
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
  marker, mismatched Node identity, invalid SQLite schema and 0644
  permissions hold.
- Writable identity mount, read-only replay mount, wrong runtime path,
  modified Compose content, wrong KH role or symlink marker hold.
- Source review denies Docker/host write and any replay DB bootstrap
  in this checker. It is packaged in first install and update.

## Still **NOT** established

- **Real persistent Docker bind mounts** are not verified by parsing a
  candidate YAML file. The base Node Compose also uses a parent
  `node-data:/var/lib/smite-node` mount; only a disposable live Docker
  inspection/recreation test can prove the nested bind and its durability.
  A `PASS` above is not an admission for `docker compose up`.
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

Reconcile a final reviewed paired Node image with **offline first pairing
and enrollment**, then test isolated Docker Compose mount precedence and
identity/replay persistence across container deletion/recreation, while
ensuring a lost replay volume stays HOLD. Separately implement and test
authorized replay-snapshot quarantine/key rotation; complete independent
Backhaul and novice IR→KH wizard without more nested steps.

**`MAIN_MERGE=NO` · `RELEASE_PUBLISH=NO` · `INSTALL_ALLOWED=NO`
· `ACTIVATION_GATE=HOLD` · `IR_KH_UNCHANGED=YES`.**
