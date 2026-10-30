# Stage15 KH: signed Sanaei Inventory migration (DRAFT)

Scope: disposable KH only. Grandoptical and IR FRPS Owner are excluded.
The current KH Node image must remain:
sha256:cf0f3b12fc2c31cb0847fd5206304837661019d8f604853a8e956448c2576265.

## Why controlled recreation is mandatory

The running Node currently has SMITE_SANAEI_INVENTORY_ENABLED=false and maps
/opt/smite-node/.sanaei-empty to /run/smite-sanaei-ro.
Docker cannot change a running container's bind-mount source and environment
persistently without recreating that container. The older RC5 helper edits
.env, which is immutable in the committed Stage15 WSS journal. Do not run it.

The KH inventory transaction changes neither original Compose nor .env.
Its dedicated read-only Compose overlay only enables the inventory flag and
adds a read-only bind to /opt/3x-ui/instances/01/db if the old
mount was absent, or replaces the existing approved dummy mount source.
Both baseline layouts are admitted only after strict Compose and runtime
delta checks; all other volume mounts remain byte-identical.
A full effective Compose comparison must show exactly these two differences;
Docker may not create missing host paths. The directory mount includes x-ui.db,
x-ui.db-wal and x-ui.db-shm. SQLite reads use mode=ro/query_only with no
checkpoint or changes to Sanaei's users/inbounds.

Only smite-node is recreated, with exactly the old Stage15 image, its
security/FRP/WSS overlays, identity and durable Replay bind. FRPC stops and
restarts briefly. FRPS Owner is neither recreated nor applied. One FRPC in the
Node's PID/mount namespace, unchanged FRPC command and unchanged signed storage
are required. The old WSS receipt remains byte-identical; a separate
root-only KH receipt explicitly binds the sole allowed Node signature delta.
Incomplete migration states fail closed. Docker Compose up -d does not
wait for Node Health; the updated Apply waits a bounded interval for Healthy
before the first Runtime admission. If an older Apply already recreated the
correct Node but stopped with SERVICE_NOT_HEALTHY, never retry Apply or edit the
journal. Review the intact RECREATING state and use the separately approved
forward-finalization gate described below.

Journal: /var/lib/u-opti/smite-stage15-kh-inventory/record.json
Phases: PREPARED -> RECREATING -> COMMITTED
Recovery: RECOVERING -> ROLLED_BACK (rollback only; never resume Apply)
After external filesystem, identity, replay, Compose, Owner or image drift:
HOLD; do not remove the journal. The overlay remains for forensic review.

## Operator gates — commands do NOT authorize execution

Before a live test, require both PR CI sets green; independently review commits,
capture recent IR/KH snapshots and console access, record the IR Owner
FRP-IR-KH-45121, FRPS/FRPC state and KH Sanaei WAL. Updating KH's U-OPTI
modules is itself a separate, explicitly approved live change.

KH — Plan (signed probes write fresh nonces to the durable Replay ledger):

    python3 -B /usr/local/lib/u-opti/modules/smite-stage15-kh-inventory.py plan

KH — Apply (separate Root TTY typed challenge; one FRPC outage):

    python3 -B /usr/local/lib/u-opti/modules/smite-stage15-kh-inventory.py apply

KH — Verify (the signed loopback endpoint and replay rejection are tested):

    python3 -B /usr/local/lib/u-opti/modules/smite-stage15-kh-inventory.py verify
    python3 -B /usr/local/lib/u-opti/modules/smite-stage15-wss.py verify

KH — Forward-finalize an already recreated, fully verified Node, only
after a genuine post-cutover SERVICE_NOT_HEALTHY race and a separate Root TTY
approval (no Docker recreation, FRPC restart or Owner apply):

    python3 -B /usr/local/lib/u-opti/modules/smite-stage15-kh-inventory.py finalize

The exact root challenge is:
FINALIZE-KH-INVENTORY-VERIFIED-NO-RECREATE.
This action is permitted ONLY for RECREATING with no recorded after-signature
and no pending writes; it independently validates the immutable WSS journal,
read-only Sanaei DB/inodes/WAL, effective Compose, reviewed image, all Node
environment/mount/runtime differences, singleton FRPC command/namespace,
protected identity/replay, signed inbound 45121:/45121/www, unsigned rejection
and duplicate-nonce rejection, then signed FRP inventory readiness. Only
after every check succeeds may it atomically commit the new Node signature
to the KH inventory receipt. A second committed invocation performs verify
only; it is not another cutover. Verify WSS and the signed GUI from IR after
finalization. Any HOLD requires operator review; do not delete/edit the receipt
or blindly retry.

KH — Recover interrupted migration, only with fresh Root TTY approval
(rollback to prior Node; never retry Apply):

    python3 -B /usr/local/lib/u-opti/modules/smite-stage15-kh-inventory.py recover

KH — Rollback committed migration, only with fresh Root TTY approval and
after separately retiring dependent published routes if any:

    python3 -B /usr/local/lib/u-opti/modules/smite-stage15-kh-inventory.py rollback

IR — independently request Signed KH Inventory from the existing Smite GUI
Owner; require 45121 — /45121/www with the same original FRPS Owner ID.
No duplicate Owner/Child or new lease; no FRP reapply. If absent, HOLD.
Only after reviewing the exact signed proposed facts and hashes, approve a
TrustedGrant from the authenticated IR Root console via the existing
smite-stage15-root-review.py; submit a fresh GUI registration request.
Then verify WSS/Edge/Bridge, FRPS/FRPC, and finally an independently
authorized *real* VLESS/XHTTP client test.

## Limits

Offline/CI checks cannot prove a real live Docker migration, outage duration,
successful GUI inventory from IR, approval of a live TrustedGrant, or real
VLESS/XHTTP client traffic. Those gates remain NOT_TESTED and operator-owned.
