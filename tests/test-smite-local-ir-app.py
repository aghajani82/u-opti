#!/usr/bin/env python3
"""Exercise bootstrap script against the exact RC7 application ORM/code store."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1]
source = Path(os.environ['UOPTI_TEST_SMITE_SOURCE']).resolve()
spec = importlib.util.spec_from_file_location('pairing', root / 'modules/smite-node-pairing.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / 'panel.db'
    env = {**os.environ, 'PYTHONPATH': str(source / 'panel'), 'DB_PATH': str(db),
           'SMITE_NODE_PAIRING_PREVIEW_ENABLED': 'true',
           'SMITE_NODE_REGISTRATION_MODE': 'signed', 'SMITE_PANEL_AGENT_AUTH_MODE': 'signed',
           'SMITE_NODE_PAIRING_MASTER_KEY': Fernet.generate_key().decode(),
           'SMITE_NODE_PAIRING_INGRESS_TOKEN': 'x' * 64}
    def run(script, *args, success=True):
        result = subprocess.run([sys.executable, '-c', script, *args], env=env,
                                cwd=tmp, text=True, capture_output=True, timeout=30)
        assert (result.returncode == 0) == success, 'RC7 application check failed'
        return result.stdout.strip()
    run('''import asyncio
from app.database import engine, Base
from app import models, node_pairing_store
from app.config import settings
async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
asyncio.run(init())
node_pairing_store.initialize_schema(settings.db_path)
''')
    node_id = str(uuid.uuid4())
    code1 = run(p._LOCAL_IR_RESERVE, node_id, 'node-ir')
    assert p._CODE.fullmatch(code1)
    code2 = run(p._LOCAL_IR_RESERVE, node_id, 'node-ir')
    assert code1 != code2
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT id,status FROM nodes').fetchall() == [(node_id, 'pending')]
        assert conn.execute('SELECT DISTINCT issued_by_admin_id FROM smite_node_pairing_codes').fetchall() == [('local-root-install',)]
        assert conn.execute('SELECT count(*) FROM smite_node_pairing_codes WHERE consumed_at IS NULL').fetchone()[0] == 1
    run(p._LOCAL_IR_RESERVE, str(uuid.uuid4()), 'other-node', success=False)
    run(p._LOCAL_IR_RESERVE, node_id, 'different-name', success=False)
    # Redeem the actual issued code with RC7's app store. It is supplied via
    # private stdin, never command arguments or output.
    script = '''import sys
from app import node_pairing_store as p
from app.config import settings
credential=p.redeem_code(settings.db_path, master_key=settings.smite_node_pairing_master_key,
    code=sys.stdin.read(), node_id=sys.argv[1], role='iran')
assert credential.node_id == sys.argv[1]
'''
    result = subprocess.run([sys.executable, '-c', script, node_id], input=code2,
                            env=env, cwd=tmp, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not result.stdout, 'RC7 redemption failed'
    run(p._LOCAL_IR_RESERVE, node_id, 'node-ir', success=False)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM nodes').fetchone()[0] == 1
        assert conn.execute('SELECT node_id,node_role FROM smite_node_identities').fetchall() == [(node_id, 'iran')]
print('PINNED_RC7_LOCAL_RESERVATION_CODE_REDEMPTION_AND_NO_REKEY=PASS')
