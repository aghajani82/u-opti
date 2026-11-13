"""Cross-repository offline ASGI contract; SMITE_SOURCE must name pinned checkout."""
import importlib.util
import json
import os
import pty
import select
import termios
from pathlib import Path
import sys
import tempfile
import time
import unittest

source=Path(os.environ['SMITE_SOURCE'])
sys.path.insert(0,str(source/'tests'));sys.path.insert(0,str(source/'panel'))
import test_foreign_install_http as http_fixture
from app.config import settings
from app.routers import signed_nodes
from app.signed_node_registration import initialize_replay_schema
spec=importlib.util.spec_from_file_location('trial_client',Path(__file__).resolve().parents[1]/'modules/smite-foreign-install-client.py')
c=importlib.util.module_from_spec(spec);sys.modules[spec.name]=c;spec.loader.exec_module(c)

class Integration(unittest.TestCase):
    def test_real_panel_grant_to_promoted_foreign_identity_with_recovery(self):
        """Actual Smite ASGI grant/replay + original U-OPTI client/promotion.

        The only transport is FastAPI's in-process TestClient; no live host
        or external HTTPS request. All persistent state is a disposable DB.
        """
        spec_phase=importlib.util.spec_from_file_location(
            'trial_identity_integration',
            Path(__file__).resolve().parents[1]/
            'modules/smite-unified-foreign-identity-phase.py')
        phase=importlib.util.module_from_spec(spec_phase)
        sys.modules[spec_phase.name]=phase
        spec_phase.loader.exec_module(phase)

        fixture=http_fixture.ForeignInstallHTTP()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        settings.smite_foreign_install_origin_trust_enabled=True
        trust=Path(fixture.tmp.name)/'trust'
        trust.mkdir(mode=0o700)
        previous=settings.smite_signed_node_origins_path
        settings.smite_signed_node_origins_path=str(trust/'origins.json')
        self.addCleanup(setattr,settings,'smite_signed_node_origins_path',previous)
        initialize_replay_schema(fixture.db)
        fixture.client.app.include_router(
            signed_nodes.router,prefix='/api/node-control')
        response=fixture.issue()
        self.assertEqual(response.status_code,200)
        packet=dict(protocol='smi1',panel_url='https://panel.example.com:443',
                    **response.json())
        base=Path(fixture.tmp.name)/'foreign-fixture'
        base.mkdir(mode=0o700)
        stage=base/'foreign-staging'
        stage.mkdir(mode=0o700)
        # Copy exactly what the Panel's ForeignInstallDialog exposes as
        # multiline JSON. The Foreign terminal intake must accept this
        # without printing the one-use code or retyping domains/Node name.
        intake_spec=importlib.util.spec_from_file_location(
            'trial_foreign_packet_intake',
            Path(__file__).resolve().parents[1]/
            'modules/smite-unified-foreign-packet-intake.py')
        intake=importlib.util.module_from_spec(intake_spec)
        sys.modules[intake_spec.name]=intake
        intake_spec.loader.exec_module(intake)
        target=stage/'foreign-install-packet.json'
        master, slave = pty.openpty()
        flags_before = termios.tcgetattr(slave)
        try:
            with os.fdopen(os.dup(slave), 'r', encoding='utf-8',
                           newline='') as tty:
                def after_echo_disabled():
                    self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
                    os.write(master, (json.dumps(packet, indent=2)+'\n\n').encode())
                def confirm(scope):
                    # The operator sees only the nonsecret destinations,
                    # not the bearer code or freshly generated Node key.
                    self.assertNotIn('installation_code', scope)
                    self.assertEqual(scope['node_name'], packet['node_name'])
                    self.assertEqual(scope['control_url'],packet['control_url'])
                    return True
                # Use EXACTLY the selected installer intake, not a
                # separate test-only capture routine.
                received=intake.capture_selected_hidden_tty(
                    tty, ready=after_echo_disabled, confirm_scope=confirm,
                    target=target, now=int(time.time()))
            self.assertEqual(termios.tcgetattr(slave), flags_before)
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                self.assertNotIn(packet['installation_code'].encode(),
                                 os.read(master, 8192))
        finally:
            os.close(master)
            os.close(slave)
        self.assertEqual(received['status'],'STAGED_PRIVATE')
        self.assertIs(received['connected'],False)
        self.assertEqual(target.stat().st_mode & 0o777,0o600)
        # The SAME file now drives the existing pre-core fields and later
        # Gateway/redeem/identity checks. Neither domains nor a Node ID is
        # retyped by the installer, and no bearer credential is emitted.
        gateway_spec=importlib.util.spec_from_file_location(
            'uopti_foreign_gateway_exact_packet',
            Path(__file__).resolve().parents[1]/
            'modules/smite-unified-foreign-gateway-plan.py')
        gateway_plan=importlib.util.module_from_spec(gateway_spec)
        sys.modules[gateway_spec.name]=gateway_plan
        gateway_spec.loader.exec_module(gateway_plan)
        from urllib.parse import urlsplit
        origin=urlsplit(packet['origin']).hostname
        panel=urlsplit(packet['panel_url']).hostname
        self.assertEqual(
            gateway_plan.precore_fields(target,now=int(time.time())),
            (panel,origin,packet['node_name'],packet['control_url']))
        state=base/'state.env'
        gateway=base/'foreign-gateway.env'
        env=base/'node.env'
        live=base/'node-identity.json'
        path=urlsplit(packet['control_url']).path
        def safe_write(path,content):
            path.write_text(content)
            path.chmod(0o600)
        safe_write(state,
            'SMITE_ROLE=foreign\n'
            'SMITE_MANAGED_VERSION=2.0.0-rc.7\n'
            'SMITE_CONNECTION_MODE=standard\n'
            'SMITE_NODE_NAME='+packet['node_name']+'\n'
            'SMITE_PANEL_DOMAIN='+panel+'\n'
            'SMITE_FOREIGN_DOMAIN='+origin+'\n')
        safe_write(gateway,
            'SMITE_FOREIGN_GATEWAY_DOMAIN='+origin+'\n'
            'SMITE_FOREIGN_PANEL_DOMAIN='+panel+'\n'
            'SMITE_FOREIGN_CONTROL_PATH='+path+'\n'
            'SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443\n'
            'SMITE_FOREIGN_GATEWAY_MODE=https-control-path\n')
        safe_write(env,
            'PANEL_ADDRESS='+panel+':443\n'
            'SMITE_CONTROL_ADDRESS=https://'+origin+':443'+path+'\n'
            'SMITE_NODE_PANEL_AUTH_MODE=paused\n'
            'SMITE_AGENT_AUTH_MODE=strict\n'
            'SMITE_ENGINE_INVENTORY_MODE=managed\n')
        calls=[]
        lose_reply=True
        def transport(panel_address,target,body,headers):
            nonlocal lose_reply
            calls.append(target)
            if target==c.REDEEM:
                headers={**headers,'X-Smite-Pairing-Ingress':fixture.ingress}
            resp=fixture.client.post(
                target,content=body,
                headers={**headers,'Content-Type':'application/json'})
            if resp.status_code!=200:
                raise c.Hold('Panel rejected request')
            if target==c.REDEEM and lose_reply:
                # The real DB has committed, but the client sees a lost ACK.
                lose_reply=False
                raise TimeoutError('lost reply')
            return resp.json()
        kwargs=dict(
            packet_path=target,state_path=state,gateway_path=gateway,
            node_env_path=env,directory=stage,live_identity=live,
            transport=transport,now=int(time.time()),
            disposable_capability=True)
        # The old no-:443 alias must HOLD *before* writing a journal or
        # consuming the actual Panel grant. Restore the same source packet.
        exact_env=env.read_text()
        env.write_text(exact_env.replace(
            'SMITE_CONTROL_ADDRESS=https://'+origin+':443',
            'SMITE_CONTROL_ADDRESS=https://'+origin))
        with self.assertRaises(phase.Hold):
            phase.rehearse_transaction(**kwargs)
        self.assertEqual(calls,[])
        self.assertFalse(live.exists())
        self.assertFalse((stage/'unified-foreign-transaction.json').exists())
        env.write_text(exact_env)
        self.assertEqual(phase.rehearse_transaction(**kwargs)['phase'],
                         'IDENTITY_PROMOTED_OFFLINE')
        self.assertEqual(calls,[c.REDEEM,c.STATUS,c.STATUS])
        original=live.read_bytes()
        self.assertEqual(json.loads(original)['node_id'],packet['node_id'])
        self.assertEqual(live.stat().st_mode & 0o777,0o600)
        calls.clear()
        # Once committed, the exact packet/operation journal stays sealed;
        # a retry proves identity without issuing or re-consuming a code.
        settings.smite_foreign_install_enabled=False
        self.assertEqual(phase.rehearse_transaction(**kwargs)['connected'],False)
        self.assertEqual(json.loads((stage/'unified-foreign-transaction.json').read_text())['phase'],
                         'IDENTITY_PROMOTED_OFFLINE')
        self.assertEqual(calls,[c.STATUS])
        self.assertEqual(original,live.read_bytes())
        from app.node_pairing_store import revoke_node
        revoke_node(fixture.db,node_id=fixture.node)
        with self.assertRaises(phase.Hold):
            phase.rehearse_transaction(**kwargs)
        self.assertEqual(original,live.read_bytes())

    def test_unified_panel_rehearsal_grant_schema_matches_actual_smite(self):
        """One DB contract for Panel schema rehearsal and real Smite grant store.

        Prevent separate U-OPTI CREATE TABLE statements drifting from the
        pinned real Smite migration (columns/PK/unique indexes).
        """
        import sqlite3
        from app import foreign_install_grants
        tx_spec=importlib.util.spec_from_file_location(
            'uopti_existing_panel_transaction_contract',
            Path(__file__).resolve().parents[1]/
            'modules/smite-unified-panel-transaction.py')
        transaction=importlib.util.module_from_spec(tx_spec)
        sys.modules[tx_spec.name]=transaction
        tx_spec.loader.exec_module(transaction)
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)
            real=base/'smite-schema.db'
            rehearsed=base/'uopti-schema.db'
            # Use actual Smite pairing migration on the real side.
            from app import node_pairing_store
            node_pairing_store.initialize_schema(real)
            foreign_install_grants.initialize_schema(real)
            with sqlite3.connect(rehearsed) as conn:
                for ddl in transaction.GRANT_DDL:
                    conn.execute(ddl)
            tables=('smite_foreign_install_grants',
                    'smite_foreign_install_origins')
            with sqlite3.connect(real) as a, sqlite3.connect(rehearsed) as b:
                for table in tables:
                    # Compare columns + constraints, not formatting of DDL.
                    self.assertEqual(
                        a.execute('PRAGMA table_info('+table+')').fetchall(),
                        b.execute('PRAGMA table_info('+table+')').fetchall(),
                        table)
                    real_indexes=a.execute(
                        'PRAGMA index_list('+table+')').fetchall()
                    trial_indexes=b.execute(
                        'PRAGMA index_list('+table+')').fetchall()
                    self.assertEqual(
                        [(i[2],i[3],i[4]) for i in real_indexes],
                        [(i[2],i[3],i[4]) for i in trial_indexes],
                        table)
                    for ci,cj in zip(real_indexes,trial_indexes):
                        self.assertEqual(
                            a.execute('PRAGMA index_info('+ci[1]+')').fetchall(),
                            b.execute('PRAGMA index_info('+cj[1]+')').fetchall(),
                            table)

    def test_real_redemption_lost_reply_expired_recovery_and_revocation(self):
        fixture=http_fixture.ForeignInstallHTTP();fixture.setUp();self.addCleanup(fixture.doCleanups)
        settings.smite_foreign_install_origin_trust_enabled=True
        parent=Path(fixture.tmp.name)/'trust';parent.mkdir(mode=0o700)
        old=settings.smite_signed_node_origins_path
        settings.smite_signed_node_origins_path=str(parent/'origins.json')
        self.addCleanup(setattr,settings,'smite_signed_node_origins_path',old)
        initialize_replay_schema(fixture.db)
        fixture.client.app.include_router(signed_nodes.router,prefix='/api/node-control')
        response=fixture.issue();self.assertEqual(response.status_code,200)
        packet=dict(protocol='smi1',panel_url='https://panel.example.com',**response.json())
        stage=Path(fixture.tmp.name)/'stage';stage.mkdir(mode=0o700)
        targets=[]
        def wire(panel,target,body,headers):
            targets.append(target)
            if target==c.REDEEM:headers={**headers,'X-Smite-Pairing-Ingress':fixture.ingress}
            result=fixture.client.post(target,content=body,headers={**headers,'Content-Type':'application/json'})
            if result.status_code!=200:raise c.Hold('Rejected')
            if target==c.REDEEM:raise TimeoutError('simulate lost acknowledgement after real commit')
            return result.json()
        args=dict(directory=stage,live_identity=stage/'live.json',transport=wire)
        self.assertEqual(c.enroll(json.dumps(packet),**args)['status'],'enrolled')
        before=(stage/'foreign-install-identity.json').read_bytes()
        packet['expires_at']=int(time.time())-1
        settings.smite_foreign_install_enabled=False
        targets.clear()
        self.assertEqual(c.enroll(json.dumps(packet),**args)['status'],'enrolled')
        self.assertEqual(targets,[c.STATUS])
        self.assertEqual(before,(stage/'foreign-install-identity.json').read_bytes())
        from app.node_pairing_store import revoke_node
        revoke_node(fixture.db,node_id=fixture.node)
        with self.assertRaises(c.Hold):c.enroll(json.dumps(packet),**args)
        self.assertEqual(before,(stage/'foreign-install-identity.json').read_bytes())

if __name__=='__main__':unittest.main()
