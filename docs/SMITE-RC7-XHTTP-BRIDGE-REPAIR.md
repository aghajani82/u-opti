# RC7 XHTTP Bridge compatibility repair

Scope: the existing Bridge transaction and broker, not a new installer or UI.
Keep `FRP-IR-Grandoptical-20182` / `1fe35d8d-9f22-43dc-b90a-be42224c363b`.
Do not recreate FRPS, the tunnel, nodes, Sanaei or `3xui-01`.
No deployment, merge or release is authorized by this runbook alone.

## Binding and rollback contract

The existing `smite-stage15-xhttp-bridge.py` also accepts a committed RC7
edge journal plus the RC7 panel-iran installation receipt. The existing Bridge
directory remains in use; schema 1 binds Stage15 and schema 2 binds RC7.
Both edge generations present, partial state, symlinks, unsafe permissions,
incorrect role/domain and uncommitted state fail closed. No legacy fallback
is allowed on an RC7 host without a Bridge.

RC7 WSS validation reconstructs only the exact Bridge include insertion from
its durable before-image. The original TLS hash must still match the unchanged
RC7 edge receipt. The stream config, map before-image, derived peer map and
8444 alternate retain their original hash/content checks. No journal is patched
to bless arbitrary Nginx contents. The Bridge adds no route or grant.

The broker's wire response remains compatible; a sanitized `BROKER_HOLD=...`
reason is written to its local journal without wire data, secrets or nonces.
The shared host lock, signed owner/child/inventory/lease binding, G/1 human
approval and durable replay gate remain mandatory.

## IR — reconcile the previous unconfirmed request first (read only)

After CI passes, review this PR and separately authorize deployment. Verify a
provider snapshot and working recovery console before updating IR through the
existing U-OPTI update flow after merge. Do not update Grandoptical for this fix.
Stop repeated Final Register attempts during reconciliation.

The following deliberately admits only the reported never-published baseline.
It does not inspect or print client UUIDs, tokens, wire bodies or nonce values.
Any nonempty ledger, existing grant/queue/route/transaction or invalid database
means HOLD, not permission to clear state or issue a fresh nonce.

```bash
# IR — read-only baseline reconciliation; no new Panel request yet
sudo python3 - <<'PY'
import importlib.util, sqlite3, subprocess
from pathlib import Path
root = Path('/usr/local/lib/u-opti/modules')
spec = importlib.util.spec_from_file_location('review_broker', root/'smite-rc5-xhttp-root-broker.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
try:
    with b._lock():
        config = b._configuration(); b._verify_helper(config)
        ledger = b._ledger_module(); ledger._trusted_db(b.LEDGER)
        with sqlite3.connect(b.LEDGER.as_uri()+'?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF')
            assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
            assert db.execute('PRAGMA user_version').fetchone() == (ledger.SCHEMA_VERSION,)
            assert db.execute('PRAGMA application_id').fetchone() == (ledger.APPLICATION_ID,)
            assert db.execute('SELECT instance_id FROM broker_identity').fetchall() == [(config['instance_id'],)]
            assert db.execute('SELECT COUNT(*) FROM consumed_nonces').fetchone() == (0,)
        for p in (b.GRANTS/'1fe35d8d-9f22-43dc-b90a-be42224c363b.json', b.LEDGER.parent/'approval-request.json'):
            assert not p.exists() and not p.is_symlink()
        routes = Path('/etc/nginx/smite-xhttp-routes')
        b._dir(routes, mode=0o755)
        assert not any(routes.iterdir())
        result = subprocess.run(['nginx','-T'], capture_output=True, timeout=25)
        assert result.returncode == 0
        assert b'/20182/category-software-99' not in result.stdout+result.stderr
    print('PREVIOUS_REQUEST=NOT_CONSUMED_NO_ROUTE_NO_GRANT_NO_QUEUE')
except Exception:
    raise SystemExit('HOLD_RECONCILE_ORIGINAL_REQUEST_NO_RETRY')
PY
```

If HOLD: privately match the original signed request hash/nonce to its consumed
ledger row, the exact route transaction, effective Nginx location, grant and
approval queue. A matching committed route is not a reason to republish. An
incomplete route transaction must use the existing pinned helper's explicit
recovery for that port/path after evidence review; external drift must not be
overwritten. A missing original request with a nonempty ledger is unresolved:
keep HOLD. Never delete/reset the nonce database, fabricate a journal/grant,
or treat a new nonce as recovery. Do not run Bridge rollback under a published
or unresolved route.

## IR — controlled Bridge repair, after baseline PASS and approval

```bash
cd /usr/local/lib/u-opti
sudo python3 modules/smite-rc7-wss-edge.py verify
sudo python3 modules/smite-stage15-xhttp-bridge.py plan
# Only after snapshot/console verification and operator approval:
sudo python3 modules/smite-stage15-xhttp-bridge.py apply
sudo python3 modules/smite-stage15-xhttp-bridge.py verify
sudo python3 modules/smite-rc7-wss-edge.py verify
```

The existing apply challenge remains `APPLY-IR-STAGE15-BRIDGE-SNAPSHOT`;
the filename/challenge are retained, while validated journal schema selects RC7.
Successful apply must leave 8444, the peer-only `/~!frp` map and FRPS unchanged.
Restart only `u-opti-smite-xhttp-broker.service` after the reviewed U-OPTI
module update so its already-loaded Python modules do not retain the old
verifier. Do not restart Nginx manually, FRPS, Smite containers or Sanaei.

```bash
# IR — only after the authorized update and Bridge verification
sudo systemctl restart u-opti-smite-xhttp-broker.service
sudo systemctl is-active u-opti-smite-xhttp-broker.service
```

Run the existing broker read-only checks (`_configuration`, `_verify_helper`,
`_verify_bridge`) before submitting a request. Refresh signed owner/child,
foreign inventory and lease evidence through the existing flow. Then:

1. In Panel, request approval for the same tunnel, port `20182`, path
   `/20182/category-software-99`; confirm the real approval queue was staged.
2. IR Option **G → 1**, after comparing the exact signed binding.
3. Panel Final Register with a fresh request, only after `ROOT_GRANT_APPROVED`.
   Any unconfirmed result returns to reconciliation; never retry automatically.

Check `nginx -t` and privately inspect `nginx -T`: one exact location and one
slash-suffix location for the path, loopback upstream `127.0.0.1:20182`, no
public 7000/20182 listener, unchanged 8443/8444 and peer-only control route.
Verify Bridge and WSS again. The user's v2rayN traffic test and an unchanged
direct connection to `grandoptical.ir` are required before claiming field PASS.

## IR — existing rollback/recovery

```bash
# Before any route is published; published routes require their own reviewed rollback first
sudo python3 /usr/local/lib/u-opti/modules/smite-stage15-xhttp-bridge.py rollback
# Instead, after interruption or failed rollback:
sudo python3 /usr/local/lib/u-opti/modules/smite-stage15-xhttp-bridge.py recover
sudo python3 /usr/local/lib/u-opti/modules/smite-rc7-wss-edge.py verify
```

Use one action appropriate to the recorded state. Retain all journals, grants,
backups and replay data. Recovery is explicit and refuses external drift.
Repeated apply is refused instead of duplicating includes. An uncertain reload
leaves a recoverable transaction; it never grants or retries route publication.

## Grandoptical

No installation or mutation commands. Keep the current owner, inbound,
`3xui-01` and direct clients. Only the user performs the final direct-client
connectivity check. CI and offline tests do not establish live traffic success.
