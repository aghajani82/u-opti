# RC7 image-bundled FRP — read-only coexistence with independent Backhaul

Issue #102. **No live installer, FRP upgrade, Node restart, tunnel Apply, or bypass of saved-tunnel HOLD.**

## Root cause

The independent FRP host inspector previously recognized **only** the offline
two-binary host-bind lane: `/opt/u-opti/engines/frp/v0.71.0/{frpc,frps}`
mounted read-only into `/usr/local/bin/{frpc,frps}`.

The live RC7 path is different. The reviewed `smite-rc7-frp-enrollment.py`
uses the FRP 0.71.0 pair **bundled in the signed Node image**, with no host
binary binds. It creates a root-owned, private, committed journal at
`/var/lib/u-opti/smite-rc7-frp-enrollment/record.json`, recording two
container-binary digests and the hash of the installed engine manifest.
Consequently `MISSING_READONLY_MOUNT` in a legacy-only inspector is NOT proof
that active FRP is broken.

## Read-only classification

The existing `smite-managed-frp-control.py status` now preserves the original
external-mount checks and additionally recognizes *candidate* image-bundled
enrollment only if all of these conditions hold:

- Managed/strict Node role and reviewed Compose structure.
- Trusted local engine manifest declaring **both** FRP binary hashes.
- **No** declared external FRP binary mounts (even a partial mount blocks
  fallback).
- The existing RC7 enrollment helper's private ownership and file checks
  succeed; journal state is exactly `COMMITTED`, journal role agrees, and its
  recorded bytes/digests match the installed manifest.

On valid **local-only** evidence it reports
`STATE=ENROLLED_UNVERIFIED`,
`REASON=RC7_BUNDLED_FRP_SIGNED_STATUS_REQUIRED`.

The result explicitly does **not** establish runtime Docker image content,
FRPS Owner/Child health, active tunnels, signed API inventory, identity/replay,
TLS 443, or recovery. An untrusted, partial, wrong-role, stale or mismatching
journal returns `UNAVAILABLE` (HOLD) with a redacted reason. When no RC7
journal exists, the original `MISSING_READONLY_MOUNT` classification remains;
no migration or new enrollment is inferred.

The existing Backhaul host report now includes
`OTHER_ENGINE_LOCAL_REASON` so it does not hide the local classification
behind `OTHER_ENGINE`. **None of the safety output fields change:**
`SAVED_TUNNELS=EXISTING_DO_NOT_RESTART`,
`OTHER_ENGINE_ACTION=NEVER_MODIFY`,
`HOST_TRANSACTION_AND_ROLLBACK=NOT_IMPLEMENTED`,
`INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`.

## Operator order

1. Review `smite-managed-frp-control.py status --node-dir /opt/smite-node`
   on IR, **read only**. No FRP process mutation or restart.
2. For a valid local RC7 journal, the separate existing signed RC7
   enrollment `verify` pathway and host health/replay probes must still
   prove active FRP state, WSS owner/children, Broker sockets, and persistence.
   No verification should authorize installation by itself.
3. Finish Issue #102's live two-host Backhaul-only transaction with before
   and after signed FRP inventories, backups, recovery-console proof,
   rollback, and shared WSS/XHTTP isolation on disposable hosts first.

**Do not run** `smite-managed-backhaul-host-executor.py install` on IR or
Grandoptical: that test executor requires `SAVED_TUNNELS=ZERO` and may
force-recreate `smite-node`. All three production FRP tunnels
(`20182`, `optical`, `nahavi`) and Grandoptical users must be preserved.
