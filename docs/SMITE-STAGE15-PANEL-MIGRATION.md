# Stage15 active-owner Panel migration candidate

This supersedes the missing-implementation status in
`SMITE-STAGE15-ACTIVE-RUNTIME-HOLD.md`. Implementation exists; real IR/KH
migration and VLESS/XHTTP client E2E remain **NOT_TESTED**. No live actions,
main merge or production release are authorized by source/CI success.

## Exact scope and trust

`modules/smite-stage15-active-runtime.py` supports `plan`, `apply`, `verify`,
`recover`, and `rollback`, under the shared engine lock and an explicit IR root
console challenge for every mutating action. Only the IR Panel is recreated,
using `--no-deps --no-build --pull never`. No Node recreate, tunnel apply,
owner delete, Nginx reload/edit, FRPS/FRPC restart or live DB restore is called.

The first-owner port is discovered from the existing active DB row, checked
against real loopback sockets and signed `/api/agent/frp/owners` proof. It is
not hardcoded. Signed probe verifies unsigned rejection and nonce replay
rejection. One owner, one proxy port, zero child leases, empty routes/grants,
committed IR WSS and WSS Edge are required. Node container ID/PID/runtime,
FRP process identities/start times/socket set, owner spec, DB schema, identity,
Replay inode, broker nonce inode, trusted node files, Compose/env, both WSS
journals and effective Nginx configuration must remain unchanged.

Current test route `/45121/www` is supported by both old KH Node inventory and
new Panel. Select it from signed inventory in the existing Owner's XHTTP GUI.
Never create another owner/child or Reapply the existing owner. Arbitrary custom
paths requiring a newer KH Node are explicitly deferred to independent reviewed
maintenance, not slipped into this transaction.

Image source stays `aghajani82/Smite@8edbd4032ae657fe2bb38cd9b3290de5f1e07a54`.
Panel archive SHA256:
`7b3d3172788d62f7d60f7103965e04db0df01606c4bc8d03760f904006ecf7c3`.
Manifest SHA256:
`67672e362686b886a6e5653055ad808d1d878c514ee2e6c2f75f310eb77ef4cb`.
Only the reviewed OCI index
`sha256:4abfd55d5c18d95119f8bae4c790cb2b687c54355836ea5529c8aff8a53dcd09`
or its verified Docker config identity
`sha256:9e88d664bd42e5c1ccb09bfe36d22cce9c0ee84d3a0e44146ffacd2542307f06`
is accepted after load. Both identities are hard-pinned to the same verified
OCI/Docker content graph, not interchangeable arbitrary hashes.

The original old Panel ID must remain available:
`sha256:e2345c7a4bf17cd9507ecf065cc736f4c2abfbe276a8c334805f4e52bb3808b5`.
No unknown image, changed manifest, re-signed replacement, or newly rebuilt
archive is substituted. Signed registry attestation is not claimed.

## Journal and recovery

Separate root-only schema-1 receipt:
`/var/lib/u-opti/smite-stage15-active-runtime/record.json`.
Original WSS/edge journal bytes are never edited. WSS health accepts the new
Panel only through a committed receipt bound to the exact original journal and
full runtime signature; only the reviewed image identity can differ. Node
admission remains pinned to its original image.

Phases: PREPARING → BACKED_UP → CUTOVER → READY → COMMITTED.
Recovery: RECOVERING → RESTORED → ROLLED_BACK. Recovery always restores old
Panel/pins; it does not retry uncertain forward Apply. The initial receipt is
published by durable directory rename, so a killed preparation cannot publish
an active transaction with missing before-images. Private staging remnants from
before that rename are inert; retain them for audit.

Before cutover: consistent SQLite backup, saved old Panel image and verified
copy of the candidate archive are fsynced and hashed. No backup DB is ever
restored to a live path. Replay continues to grow normally; content is not
required to remain byte-identical. The same Replay inode is mandatory.

Broker's worker, planner, config and unit use atomic per-file replacement with
exact before/after values. Broker admission is closed throughout incomplete
phases; mixed pins are never served. A stopped broker and the engine lock make
the multi-file transaction atomic to route callers. Unknown bytes/modes,
missing backups, owner/process changes or runtime drift stop Recovery before
its target writes. Partial pin replacements are recognized and recoverable.

**Socket directory preservation:** systemd normally removes RuntimeDirectory
on stop. An unchanged Node bind mount would then point to a detached directory.
Before stopping Broker, the transaction installs the precisely reviewed unit
with `RuntimeDirectoryPreserve=yes`, daemon-reloads it and verifies that property.
It checks the directory inode throughout. Existing Node socket/key mounts,
primary UID/GID and absence of unreviewed unit drop-ins are preflight conditions.
Rollback deliberately retains this one reviewed unit setting; reverting it
would break the unchanged Node mount. The original unit is retained in the
receipt. Worker/planner/config and Panel roll back to their recorded before state.

If failure occurs after COMMITTED but before Broker restart, the files/runtime
have already passed checks; retry `recover` for rollback, not Apply. Failed
backup preparation leaves PREPARING and can be closed with `recover` without
recreating any container. Never delete the receipt to force a retry.

Runtime rollback requires routes/grants removed and Stage15 bridge rolled back
first, under separately approved operations. Their presence or Nginx drift
causes HOLD. `active-runtime verify` is the **pre-route** verification gate;
after route publication use normal WSS/edge/bridge verification, whose receipt
admission remains compatible with the committed Panel migration.

## Preserved artifact delivery

Successful preservation run:
https://github.com/aghajani82/Smite/actions/runs/41020816370

Artifact `12960674420`, `stage15-reviewed-8edbd403-preserved`, expires
2027-01-28. It contains the exact original ZIP plus preservation metadata.
Outer download ZIP SHA256:
`55a4f55ebe6f14929c65fb05da96b60ea49f58480b3db9a46bf23c1395273575`.
Inner `stage15-reviewed-8edbd403.zip` SHA256 remains:
`d250b0fd27ae362bc4008b9e62208f94ae92fb71273d66bee83c9bcdcd1f75d9`.
The workflow checked original successful run 40921424209, artifact 12919495217,
source SHA, exact ZIP/member hashes and unchanged activation-disabled manifest.
It did not rebuild images. Other new-source image workflow outputs are NOT
substitutes for this migration's pinned artifact.

Download authenticated from that run, verify outer and inner hashes, then
extract the three original files into a private root-owned folder. Run the
existing bundle verifier with `--inspect-archives`; its deployment-denied
exit 2 is intentional. Preserve a verified offline copy before retention ends.
Rebuild from source can yield different hashes and requires a new independent
review/transaction version; this migration will reject it.

## Controlled test sequence — separate approval required

**Snapshot — IR and KH:** have console access and verified snapshots/backups.
Capture owner/Node/FRPS/FRPC identities and port listeners. Do not plan to revert
an old Replay DB over a live system. No Grandoptical access.

**Preflight — IR:** stage the reviewed U-OPTI modules through its normal
immutable-source update mechanism (this itself is a live change requiring
approval). No old image upgrader. With the verified extracted images:

```sh
python3 -B /usr/local/lib/u-opti/modules/smite-stage15-active-runtime.py plan --images /root/stage15-reviewed-images
```

`plan` performs signed GET probes, recording fresh nonces in the existing replay
ledger; it does not apply a tunnel or mutate service/configuration files.
Treat this as an explicitly approved diagnostic, not a byte-for-byte read-only
operation. **KH:** independently confirm signed inbound inventory contains the
actual loopback port/path and that Node/FRPC remain unchanged; no upgrade.

**Apply — IR, only after successful preflight and separate approval:**

```sh
python3 -B /usr/local/lib/u-opti/modules/smite-stage15-active-runtime.py apply --images /root/stage15-reviewed-images
python3 -B /usr/local/lib/u-opti/modules/smite-stage15-active-runtime.py verify
python3 -B /usr/local/lib/u-opti/modules/smite-stage15-wss.py verify
python3 -B /usr/local/lib/u-opti/modules/smite-stage15-wss-edge.py verify
```

Panel management temporarily restarts; Node-owned FRP is required to remain live.
Verify the same Owner ID and process/socket evidence before proceeding.

**Route publication — IR:** separately approve Stage15 bridge `plan`/`apply`/
`verify` using `smite-stage15-xhttp-bridge.py`. In Smite select the existing
Owner and signed inbound `/45121/www`; request registration. Missing grant must
HOLD and stage a signed proposal. Independently verify IR owner/KH inventory,
then run `smite-stage15-root-review.py` on the authenticated root console and
approve the exact digest displayed. A fresh GUI registration request follows;
nonce replay is never retried. No manual port/path transcription, automatic
grant minting, duplicate child or owner reapply.

**Verify — IR/KH:** normal WSS/edge/bridge verification, Signed/Replay negative
checks, one FRPS/no child, unchanged process identities and actual VLESS/XHTTP
client traffic. UI Active alone is not PASS.

**Recovery / Rollback — IR, only after separate approval:** before any route or
bridge publication, use `recover` after an interrupted transaction, or `rollback`
after a completed transaction. Both require console confirmation. For example:

```sh
python3 -B /usr/local/lib/u-opti/modules/smite-stage15-active-runtime.py recover
```

After publication, remove the route/grant and roll back bridge first using their
reviewed flows; do not bypass dependency HOLD. **KH:** no runtime changes in this
stage and no rollback command. Never restore old live SQLite/Replay databases.

STOP for any failed backup/hash, changed Owner/PID/socket/inode, unknown image,
missing mount, unsupported source/DB schema, active auto-reset/legacy FRP,
invalid signed proof, Nginx/TLS failure or unexpected journal state.

## Evidence limits

Private-filesystem tests exercise actual receipt and pin replacement, SQLite
nonce uniqueness/preservation, injected failure at every coordinator boundary,
interrupted Recovery, real SIGKILL mid-pin-write, drift, invalid images, duplicate
owner/lease, unsafe startup settings and the restricted Panel-only Compose call.
A disposable systemd/bind-mount test checks broker socket inode survival.
Existing pinned cross-repository tests cover Bridge/RootGrant/Replay and the
actual Panel startup/timer functions' no-Reapply behavior.

These are not an end-to-end migration of the real enrolled IR host. Target
Docker image load, complete live upgrade/rollback, KH FRPC continuity, and
actual VLESS/XHTTP traffic remain **NOT_TESTED** until separately approved.
