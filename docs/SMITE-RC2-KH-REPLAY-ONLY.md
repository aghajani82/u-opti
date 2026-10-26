# Smite RC.2 — KH Replay-only gate (NEXT-5.BV)

**Scope:** disposable KH host only. This is a *Draft PR* feature and is NOT
authorization to run live enrollment or enable signed Node traffic.

## Why this separate gate exists

The previously reviewed `smite-node-pairing.py` directly invokes
`_provision_replay_once()` inside `activate_foreign_node_field_trial()` before
a Compose `up --force-recreate`. Never invoke that activation function merely
to create Replay. The RC.1 foreign wizard is also out of scope.

New standalone tool: `modules/smite-rc2-kh-replay-only.py`.

| Action | Permitted effect | Required disposition |
|---|---|---|
| `--plan` | Read-only verified KH admission and Replay state | HOLD on drift |
| `--verify` | Read-only check of existing Marker, DB and identity binding | HOLD if incomplete |
| `--apply` | Exactly one *offline* initial Replay enrollment | Separate operator authorization |

There is deliberately **no** Replay erase, reset, recovery, rotate-key, signed
activation, Node restart, Compose change, Nginx reload or gateway update option.

## Source integrity and host gates

- KH hostname and root required.
- The two previously reviewed U-OPTI helper modules MUST be present as
  root-owned, non-linked, private mode `0600` files, verified against their
  exact Git blob SHA1 **before importing source**.
- The new standalone tool itself must be staged from one reviewed Git commit
  and independently Git-blob-verified before any execution.
- The existing RC.2 KH admission checks exact Node image and effective Compose,
  paused/strict/managed, TLS/443 controlled gateway, Nginx, Sanaei XHTTP guard
  and healthy Panel HTTPS. Do not weaken or skip that prerequisite.
- Existing paired identity must remain root-owned `0600` under `0700`;
  no secret, UUID or private gateway prefix appears in command output.
- Replay tree must be root-owned `0700`. In `--plan`, missing Replay
  parents are reported without creating them.
- Any Marker/DB mismatch, symlink, unsafe link count, unexpected leftover
  file, or restore HOLD sentinel blocks enrollment. NEVER delete and retry.
- Both `--plan` and `--verify` must be invoked with `python3 -B`
  to prevent Python bytecode cache writes.

## Offline first enrollment (not authorized by this document)

Separate consent requires BOTH environment flags
`UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES` and
`UOPTI_SMITE_RC2_REPLAY_ONLY=YES`, a real TTY, and the literal operator
confirmation `ENROLL-REPLAY-ONCE`.

After acquiring an exclusive non-writing lock on the *existing* identity file
and repeating KH admission, the tool may create ONLY the private Replay
directory hierarchy and execute the EXACT locally pinned Node RC.2 image in an
ephemeral Docker container:

- `--rm --pull never --network none --read-only`
- `--cap-drop ALL --security-opt no-new-privileges`
- private identity and Replay directory bind mounts (no socket mount)
- `python3 -B -m app.replay_enrollment --confirm-first-provision`

The Smite enrollment routine creates a permanent HMAC-bound Marker **before**
initializing its fresh SQLite DB. It refuses repeat enrollment. A crash after
Marker creation is quarantined and must receive independent forensic review;
do not clear the directory or blindly retry.

After a positive result, verify:
1. Marker and DB mode `0600`, root owner, one hard link and valid Schema.
2. Binding to the unchanged existing Node ID/HMAC key.
3. Unchanged running Node image, container start timestamp and listening
   endpoints; unchanged KH gate admission; no Compose or service mutation.
4. Runtime remains `paused + strict + managed`.

An existing valid enrollment is accepted without overwriting either file.
Replay readiness NEVER implies permission to activate the Node.

## Operator progression

1. CI: all new offline tests and full draft PR checks pass.
2. Independent reviewer checks source, pin, Docker flags, failure behavior,
   storage snapshot availability and storage recovery limitations.
3. KH: stage reviewed standalone tool securely, compare exact Git blob and
   run **only** `--plan`; capture sanitized PASS/HOLD statuses.
4. IR/KH: read-only re-check Panel signed identity, exact KH HMAC identity
   correspondence, gateway and preserved unrelated services.
5. Request NEW explicit user authorization for the Replay-only one-time
   `--apply`; never treat chat discussion or this document as consent.
6. On independent KH `--verify` PASS, request another separate approval for
   RC.2 signed Node activation and follow the dedicated activation runbook.
7. Only after dual-direction HMAC and negative replay verification, stability
   drill, recovery test, operator UI/docs and Issue #47 closeout may the
   owner consider a separately approved merge/release.

**Grandoptical is excluded absolutely.** IR, Sanaei, XHTTP, FRP, Backhaul,
main/stable and PR ready-for-review status remain unchanged in this gate.
