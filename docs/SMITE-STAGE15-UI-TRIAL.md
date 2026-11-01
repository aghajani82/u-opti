# Static UI trial — IR only, four active FRP paths preserved

Candidate frontend: Smite `aec8a5f7e7a91a9e59fd968ef0f7570fdd995d57`.
This is an opt-in test bundle, not a stable release or authorization to deploy.
The supplied helper is standalone and is not installed/enabled by default.

## Admission and implementation

Only a root SSH TTY on host `ir` can back up/apply/rollback. Docker is fixed to
`unix:///var/run/docker.sock`. Preflight verifies exact packaged Python backend
file hashes, running healthy Panel/Node identities, a single FRPS process and
absence of mounts over the UI/backend. An incompatible/custom/mounted layout
is HOLD; do not loosen checks or substitute the old Stage15 image upgrader.
The deployed Panel and Node image IDs, container IDs, start times, restart counts,
mounts, PIDs and FRP process IDs are retained and rechecked.

The helper writes only static assets and an atomic `index.html` replacement in
`smite-panel`; host receipt/backup is root-private under
`/var/lib/u-opti/smite-ui-trial`. It never updates Python, images, Compose,
Node, leases, grants, Signed Pairing, replay, Nginx or firewall. Backend bytes
from `8edbd403` and this UI source are identical in Git; actual deployed bytes
must still pass the live preflight. No claim is made that live preflight passed.

Old assets remain available for existing tabs. New assets are durable before
index replacement. Rollback atomically restores the old index; inert new assets
remain to support tabs that already loaded them. Interrupted temp files remain
inert and are not automatically deleted. Unknown asset/index drift is HOLD.
An interrupted APPLYING transaction must be verified or rolled back, never
blindly reapplied. A container restart/recreate or image change is HOLD.
This trial lives in the container writable layer: a future container recreation
will discard it. Do not treat it as a permanent image update.

## Commands prepared for separately approved live execution

Transfer the bundle into a root-owned private directory on **IR**. Verify the
published SHA-256 before extracting the fixed `ui-trial.py` and `README.md`
entries. Replace `BUNDLE.zip` and `EXPECTED_SHA256` with the delivered filename
and checksum; use the same values for every command. No commands target KH.

```bash
# IR — verify download before extracting the reviewed helper
printf '%s  %s\n' 'EXPECTED_SHA256' 'BUNDLE.zip' | sha256sum -c -
unzip -p BUNDLE.zip ui-trial.py > ui-trial.py
chmod 600 ui-trial.py
# IR — Preflight (read-only)
python3 -B ui-trial.py preflight --bundle BUNDLE.zip --sha256 EXPECTED_SHA256
# IR — Backup (host receipt only, no container writes)
python3 -B ui-trial.py backup --bundle BUNDLE.zip --sha256 EXPECTED_SHA256
# IR — Apply (requires typing APPLY-UI-ONLY)
python3 -B ui-trial.py apply --bundle BUNDLE.zip --sha256 EXPECTED_SHA256
# IR — Verify exact static bytes + backend + unchanged container/FRP identities
python3 -B ui-trial.py verify --bundle BUNDLE.zip --sha256 EXPECTED_SHA256
# IR — Rollback when needed (requires typing ROLLBACK-UI-ONLY)
python3 -B ui-trial.py rollback --bundle BUNDLE.zip --sha256 EXPECTED_SHA256
```

Before Apply, independently record four active routes/leases/grants and successful
real client traffic. Keep provider snapshots and console access. These commands
back up **public static files only**, not database/replay restore points. Never
restore a stale security DB to roll back a UI change. Do not run commands after
any failed step. Unknown outcome: inspect using Verify, then reviewed Rollback.

After Apply, hard-refresh the Panel, confirm Persian XHTTP guidance and visible
Verify success. Verify means signed FRPS listener verification, not end-to-end
VLESS traffic. Confirm all four old clients still work; create a distinct fifth
child/inbound, use G, submit a fresh publication request, and test v2rayN. Do not
reapply the existing Owner or the four children. Record the fifth port/path and
result for the final release decision.

## Test limits

Offline tests exercise real temporary files: collision/tamper/symlink
static checks, atomic index commit, failure before/after commit, rollback, and
backend preservation. No Docker daemon or live IR/KH was available in the test
workspace. A disposable Docker HTTP-serving test is included in the dedicated CI workflow.
Host transaction commands are tested with a mocked Docker boundary. Actual
IR serving/cache behavior and runtime identity therefore still require the separately approved preflight and operator browser test. If this
layout is refused, stop and review a Panel-only migration separately.
