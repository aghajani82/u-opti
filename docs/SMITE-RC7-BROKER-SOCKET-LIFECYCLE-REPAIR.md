# RC7 Broker UNIX socket directory lifecycle — focused repair

**Scope:** existing U-OPTI Broker unit, Stage15 receipt compatibility, and
IR-only reviewed recovery. No UI, new installer, image, external endpoint,
port, Smite change, tunnel creation, or Grandoptical update.

Keep the existing `FRP-IR-Grandoptical-20182` and
`1fe35d8d-9f22-43dc-b90a-be42224c363b`; FRPS 7000, KH inbound
`127.0.0.1:20182`, path `/20182/category-software-99`, and direct
Grandoptical users remain untouched. **No live deployment is authorized
by this PR.** Requires CI success, operator review, a separately approved
maintenance window, independent provider snapshot and tested console.

## Failure and correction

The live IR broker directory `/run/u-opti/smite` had a new host
device:inode after a Broker restart while the existing read-only Docker
bind of `smite-node` was still pinned to the prior directory. A live host
Broker socket alone could not make it reachable to Node.

The clean RC7 `smite-rc5-xhttp-broker-provision.py::_service_unit` now
generates `RuntimeDirectoryPreserve=yes`, so routine Broker restarts
must retain the host runtime inode. Only known exact previous service
units (with optional historic lock-path spelling) may be atomically upgraded.
The Stage15 active-runtime validator accepts only its exact earlier and
new U-OPTI unit bytes; it does not modify an existing migration receipt.
In particular, this change does **not** reattach an already-stale Docker
bind by itself.

The existing Broker provision module has a read-only audit and a
separately authorized repair. Repair only proceeds with: trusted
root-owned Broker configuration/HMAC/helper and strict SQLite replay
schema; an unmodified known systemd unit with no drop-ins; current
signed XHTTP Bridge and RC7 WSS Edge verification; owner listener on
7000; existing healthy Panel and Node, exact read-only Node bind, UID 0
and dedicated GID; persistent Node tunnel volume (legacy `smite-node-data` or the exact
RC6 Compose-scoped `<project>_node-data`, verified against both container
project labels and read-only Docker volume metadata); independent
snapshot/console challenge; and the existing exclusive host engine lock.
Unexpected ownership, mount, service, missing ledger, symlink, missing
tunnel registry, competing operation, or active protected-file drift is
`HOLD`. No nonce or request is replayed, rebuilt, or cleared.

In an approved maintenance window, after unit replacement and
`daemon-reload` verifies preservation, recovery restarts **only**
the current Broker service to demonstrate the directory inode remains
unchanged. If the Node bind is stale, recovery performs **one**
`docker restart smite-node` (never compose up or recreate), then
revalidates the exact container ID/image/Compose configuration/mounts,
Broker directory inode and socket owner/mode, protected input fingerprints,
FRPS listening identity, Bridge, WSS, and healthy Panel/Node. No Panel,
Grandoptical, Sanaei, FRP owner or tunnel reapplication.

## Follow-up: RC6 Compose-scoped Node volume acceptance

The IR field audit originally stopped at `HOLD_BROKER_NODE_TUNNEL_VOLUME_DRIFT`
because its running Node has a Compose-created volume named
`uopti_rc6_<32-hex-project-id>_node-data` rather than the older fixed
`smite-node-data`. Read-only Docker evidence confirms both `smite-panel`
and `smite-node` share the same Compose project and the existing volume
has `com.docker.compose.project=<project>` and
`com.docker.compose.volume=node-data`. This is **not** permission to rename
the volume, move `tunnels.json`, recreate the container, or change FRP.

The repair audit now accepts the existing fixed-name layout unchanged, or
**only** the project-scoped RC6 pattern when all these proofs agree:
the exact Node mount destination `/var/lib/smite-node`, type `volume`,
read-write data mount, matching Panel and Node Compose project/service
labels, volume name `<project>_node-data`, the same canonical Docker
volume directory, and a read-only `docker volume inspect` record with
matching Name/Mountpoint, local driver/scope, default options, project,
`node-data` label, Compose config hash and version. A forged/mismatched
name, foreign project, missing labels or untrusted mount fails closed.

No change to signed Pairing, XHTTP route publication, FRPS, Bridge, WSS,
replay ledger, or root approval flow. Restart/recovery remains separately
authorized and is **not** implied by a passing audit. On any HOLD, stop
without renaming/mounting anything or retrying a Panel publish.

## IR-only: after CI PASS, PR merge/review, and independent deployment approval

Update U-OPTI **through its existing update mechanism** only after the
PR is accepted. No manual replacement of the running service or container.
The new helper must be present locally before running these commands.

Read-only audit, before maintenance:

```bash
# IR — read-only. The existing service may still show NO and STALE_HOLD.
sudo python3 /usr/local/lib/u-opti/modules/smite-rc5-xhttp-broker-provision.py \
  --audit-node-socket --confirm-local-root
sudo systemctl show u-opti-smite-xhttp-broker.service \
  -p FragmentPath -p DropInPaths -p RuntimeDirectoryPreserve
```

For the repair below, independently verify a Hetzner/provider snapshot,
working recovery console, original signed owner/lease/inbound, and an
announced IR traffic interruption. Take a safe durable data snapshot,
**without** removing nonce, grant, queue, or route files. Do not issue a
new Panel publish while the earlier 409/503 request is uncertain.

```bash
# IR — ONLY with explicit human approval, console, snapshot and outage window
sudo python3 /usr/local/lib/u-opti/modules/smite-rc5-xhttp-broker-provision.py \
  --recover-node-socket --confirm-local-root
# Type the exact maintenance challenge only if its conditions are satisfied.
```

Read-only postproof:

```bash
# IR — no route publication
sudo python3 /usr/local/lib/u-opti/modules/smite-rc5-xhttp-broker-provision.py \
  --audit-node-socket --confirm-local-root
sudo python3 /usr/local/lib/u-opti/modules/smite-rc7-wss-edge.py verify
sudo python3 /usr/local/lib/u-opti/modules/smite-stage15-xhttp-bridge.py verify
sudo systemctl show u-opti-smite-xhttp-broker.service -p RuntimeDirectoryPreserve
sudo stat -Lc '%d:%i %U:%G %a' /run/u-opti/smite
sudo docker exec smite-node stat -Lc '%d:%i %U:%G %a' /run/u-opti/smite
```

Expected: preservation `yes`, exactly matching host/Node device:inode,
Broker socket root:dedicated GID 0660, Node health `healthy`, and
unchanged active owner/tunnel and all durable evidence. The host directory
mode is 0750. A subsequent controlled Broker restart must leave directory
inode unchanged (the reviewed recovery already tests this). No further
restart is justified merely to collect an extra proof.

## Rollback, interruption and fail-closed recovery

- On `HOLD`, do not repeatedly click Final Register, restart containers,
  create a new Node, rotate keys, reset replay ledger or recreate FRPS.
  The unit edit uses an atomic replace; `daemon-reload` is checked before
  any service restart. No old unit is blindly restored after the new
  directory is attached, because that would recreate the orphaning flaw.
- After interrupted Broker restart or Node restart, capture read-only
  audit and service/health evidence. If prior bytes, owner, mounts, key,
  ledger, protected route/queue state or container ID drift, stop and use
  the **verified provider snapshot / recovery console** under separate
  approval. Do not automatically repeat the Docker restart.
- When the only remaining issue is a provably stale inode and all
  independent checks still match, the same reviewed recovery may be
  explicitly re-authorized after maintenance investigation. If already
  bound, it exits without restarting anything. Existing U-OPTI signed
  journals and their own recovery/rollback remain authoritative.
- If a signed XHTTP publication previously returned 409/503/UNCONFIRMED,
  reconcile the exact prior request using the read-only procedure in
  `docs/SMITE-RC7-XHTTP-BRIDGE-REPAIR.md`; do not infer a safe retry
  merely from socket repair. Only when reconciliation proves no grant,
  no route, no pending approval, and no consumed nonce may an operator
  separately request that route **once** through the existing UI,
  IR console G → 1, and Panel Final Register.

## Disposable CI acceptance

`tests/test-stage15-broker-directory-systemd.sh` demonstrates the old
orphaned bind with real systemd and a disposable, network-disabled,
read-only Docker container, then the preserved inode and a one-time
in-place container restart. Root-broker and Stage15 tests exercise
legacy receipts, tampered units, missing snapshot approval, engine lock,
partial restart, immutable replay/tunnel evidence and no route/reapply.
No test accesses IR, KH, Grandoptical, or production credentials.
