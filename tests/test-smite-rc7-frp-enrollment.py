#!/usr/bin/env python3
"""RC7 explicit bundled-FRP engine enrollment isolated safety regression."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'modules/smite-rc7-frp-enrollment.py'
spec=importlib.util.spec_from_file_location('rc7_frp_enrollment_tests',PATH)
ctl=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)

class EnrollmentTests(unittest.TestCase):
    def test_pinned_binary_pair_proposal_keeps_unrelated_engines(self):
        with tempfile.TemporaryDirectory() as temporary:
            state=Path(temporary)/'journal'
            with patch.object(ctl,'JOURNAL',state), \
                 patch.object(ctl,'node_details',return_value={'role':'foreign'}), \
                 patch.object(ctl.rt,'no_tunnels'), \
                 patch.object(ctl,'manifest_before',return_value=(
                     b'{"schema":1,"engines":{"backhaul":{"sha256":"'+b'a'*64+b'"}}}',
                     {'backhaul':{'sha256':'a'*64}})), \
                 patch.object(ctl,'binaries',return_value={'frpc':'b'*64,'frps':'c'*64}):
                doc,prior,candidate,digests=ctl.proposal()
            result=json.loads(candidate)
            self.assertEqual(doc['role'],'foreign')
            self.assertEqual(result['engines']['backhaul'],{'sha256':'a'*64})
            self.assertEqual(result['engines']['frp'],
                             {'sha256':'b'*64,'server_sha256':'c'*64})
            self.assertFalse(state.exists())

    def test_existing_enrollment_journal_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'journal'
            folder.mkdir()
            with patch.object(ctl,'JOURNAL',folder):
                with self.assertRaises(ctl.Hold):
                    ctl.proposal()

    def test_retained_backhaul_journal_blocks_standalone_frp_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=Path(tmp)/"retained-rc7.json"
            journal.write_bytes(b"{}")
            journal.chmod(0o600)
            with patch.object(ctl,"RETAINED_BACKHAUL",journal), \
                 patch.object(ctl,"safe_dir"), \
                 patch.object(ctl,"read_private",return_value=b"{}"), \
                 patch.object(ctl,"node_details") as probe:
                with self.assertRaises(ctl.Hold):
                    ctl.restore({"state":"COMMITTED","role":"ir"})
                probe.assert_not_called()

    def test_retained_cleanup_seal_blocks_frp_rollback_even_without_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            # A crash can leave only this durable terminal seal after the
            # retained Backhaul journal has been removed. Never race recovery.
            seal = Path(tmp)/"retained-rc7-cleanup.json"
            seal.write_bytes(b"pending terminal cleanup")
            with patch.object(ctl, "RETAINED_BACKHAUL_CLEANUP", seal), \
                 patch.object(ctl, "RETAINED_BACKHAUL", Path(tmp)/"missing"), \
                 patch.object(ctl, "node_details") as probe:
                with self.assertRaisesRegex(
                    ctl.Hold, "BACKHAUL_CLEANUP_REQUIRES_OWN_RECOVERY"
                ):
                    ctl.restore({"state": "COMMITTED", "role": "ir"})
                probe.assert_not_called()

    def test_unreviewed_image_blocks_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(ctl,'JOURNAL',Path(temporary)/'absent'), \
                 patch.object(ctl,'node_details',side_effect=ctl.Hold('WSS_RUNTIME_SECURITY_DRIFT')):
                with self.assertRaises(ctl.Hold):
                    ctl.proposal()

    def test_unsigned_apply_rejected_before_mutations(self):
        with patch('sys.argv',['enroll','apply','--role','foreign']), \
             patch.object(ctl.os,'geteuid',return_value=0), \
             patch.object(ctl.sys.stdin,'isatty',return_value=False), \
             patch.object(ctl,'apply') as action:
            self.assertEqual(ctl.main(),2)
            action.assert_not_called()

    def test_engine_not_ready_without_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'engine-state').mkdir()
            fake=root/'engine-state/engines.json'
            with patch.object(ctl,'JOURNAL',root), \
                 patch.object(ctl,'MANIFEST',fake), \
                 patch.object(ctl,'safe_dir'), \
                 patch.object(ctl,'json_private',return_value={
                     'schema':1,'role':'foreign','state':'COMMITTED',
                     'old':None,'new':'a'*64,
                     'binaries':{'frpc':'b'*64,'frps':'c'*64}}):
                with self.assertRaises(ctl.Hold):
                    ctl.verify_file(ctl.state())

    def test_signed_owner_valid_runtime_contract_is_sanitized(self):
        raw=json.dumps({
            'status':'success',
            'owners':[{'tunnel_id':'FRP-IR-Grandoptical-20182',
                       'control_port':7000,
                       'proxy_ports':[20182,45121,45122]}],
        })
        result=ctl.signed_owner_payload(raw)
        self.assertEqual(len(result),64)
        self.assertRegex(result,r'^[0-9a-f]{64}$')
        self.assertNotIn('Grandoptical',result)

    def test_signed_owner_rejects_missing_duplicate_spoofed_or_invalid_data(self):
        good={'status':'success','owners':[{
            'tunnel_id':'FRP-IR-Grandoptical-20182',
            'control_port':7000,'proxy_ports':[20182,45121,45122]}]}
        bad_cases=[
            {},
            {'status':'success','owners':[]},
            {'status':'success','owners':[good['owners'][0],good['owners'][0]]},
            {'status':'ok','owners':good['owners']},
            {'status':'success','owners':'SECRET'},
            {'status':'success','owners':[{
                **good['owners'][0],'tunnel_id':'../../etc/passwd'}]},
            {'status':'success','owners':[{
                **good['owners'][0],'control_port':True}]},
            {'status':'success','owners':[{
                **good['owners'][0],'control_port':7001}]},
            {'status':'success','owners':[{
                **good['owners'][0],'proxy_ports':[20182,20182]}]},
            {'status':'success','owners':[{
                **good['owners'][0],'proxy_ports':[45121,20182]}]},
            {'status':'success','owners':[{
                **good['owners'][0],'proxy_ports':[0]}]},
            {'status':'success','owners':[{
                **good['owners'][0],'proxy_ports':[7000]}]},
            {'status':'success','owners':[{
                **good['owners'][0],'proxy_ports':[True]}]},
            {'status':'success','owners':[{
                **good['owners'][0],'proxy_ports':list(range(1,131))}]},
            {'status':'success','owners':[{
                **good['owners'][0],'token':'DO_NOT_PRINT_ME'}]},
            {**good,'debug':'SECRET'},
        ]
        for case in bad_cases:
            with self.subTest(case=str(case)[:45]):
                with self.assertRaises(ctl.Hold):
                    ctl.signed_owner_payload(json.dumps(case))
        for raw in (
            '{"status":"success","status":"success","owners":[]}',
            '{"status":"success","owners":[{"tunnel_id":"id",'
            '"control_port":7000,"proxy_ports":[],"control_port":7000}]}',
            '{garbled', 'A'*8193, '', 'null',
        ):
            with self.subTest(raw=raw[:35]):
                with self.assertRaises(ctl.Hold):
                    ctl.signed_owner_payload(raw)

    def test_signed_owner_request_uses_fixed_signed_agent_endpoint(self):
        script=ctl.SIGNED_OWNER_REQUEST
        self.assertIn("target='/api/agent/frp/owners'",script)
        self.assertIn('method=\'GET\'',script)
        self.assertIn('nonce=secrets.token_hex(16)',script)
        self.assertIn('ProxyHandler({})',script)
        self.assertIn('class NoRedirect',script)
        self.assertIn('raw=response.read(8193)',script)
        self.assertNotIn('/tunnels/apply',script)
        self.assertNotIn('/tunnels/remove',script)
        compile(script,'<signed-owner-check>','exec')

    def test_verify_owner_on_ir_calls_signed_api_after_existing_rc7_guards(self):
        record={'role':'ir','state':'COMMITTED'}
        invocations=[]
        def guarded_verify(entry):
            invocations.append('file')
        def guarded_hmac():
            invocations.append('hmac')
        def guarded_inventory():
            invocations.append('engine')
        def guarded_owner():
            invocations.append('owner')
            return 'a'*64
        output=io.StringIO()
        with patch('sys.argv',['enroll','verify-owner','--role','ir']), \
             patch.object(ctl.os,'geteuid',return_value=0), \
             patch.object(ctl.rt,'locked',return_value=contextlib.nullcontext()), \
             patch.object(ctl,'state',return_value=record), \
             patch.object(ctl,'verify_file',side_effect=guarded_verify), \
             patch.object(ctl.rt,'signed_probe',side_effect=guarded_hmac), \
             patch.object(ctl,'enrolled_status',side_effect=guarded_inventory), \
             patch.object(ctl,'signed_owner_inventory',side_effect=guarded_owner), \
             contextlib.redirect_stdout(output):
            self.assertEqual(ctl.main(),0)
        self.assertEqual(invocations,['file','hmac','engine','owner'])
        self.assertIn('RC7_SIGNED_FRPS_OWNER_VERIFY=PASS_SIGNED_LISTENER',output.getvalue())
        self.assertIn('FRPS_CHILD_FORWARDING=NOT_PROVEN',output.getvalue())
        self.assertIn('LIVE_CONFIG_CHANGES=NONE',output.getvalue())
        self.assertNotIn('Grandoptical',output.getvalue())

    def test_verify_owner_blocks_wrong_role_journal_and_refused_owner(self):
        for record,role,expected in [
            ({'role':'foreign','state':'COMMITTED'},'foreign','IR_FRPS_OWNER_ONLY'),
            ({'role':'ir','state':'HOLD'},'ir','ENROLLMENT_NOT_COMMITTED'),
            ({'role':'foreign','state':'COMMITTED'},'ir','ROLE_MISMATCH'),
        ]:
            with self.subTest(role=role,state=record['state']):
                stderr=io.StringIO()
                with patch('sys.argv',['enroll','verify-owner','--role',role]), \
                     patch.object(ctl.os,'geteuid',return_value=0), \
                     patch.object(ctl.rt,'locked',return_value=contextlib.nullcontext()), \
                     patch.object(ctl,'state',return_value=record), \
                     patch.object(ctl,'verify_file') as verify_file, \
                     patch.object(ctl,'signed_owner_inventory') as owner, \
                     contextlib.redirect_stderr(stderr):
                    self.assertEqual(ctl.main(),2)
                self.assertIn('HOLD: '+expected,stderr.getvalue())
                verify_file.assert_not_called()
                owner.assert_not_called()
        stderr=io.StringIO()
        with patch('sys.argv',['enroll','verify-owner','--role','ir']), \
             patch.object(ctl.os,'geteuid',return_value=0), \
             patch.object(ctl.rt,'locked',return_value=contextlib.nullcontext()), \
             patch.object(ctl,'state',return_value={'role':'ir','state':'COMMITTED'}), \
             patch.object(ctl,'verify_file'), \
             patch.object(ctl.rt,'signed_probe'), \
             patch.object(ctl,'enrolled_status'), \
             patch.object(ctl,'signed_owner_inventory',
                          side_effect=ctl.Hold('SIGNED_FRPS_OWNER_RESPONSE_INVALID')), \
             contextlib.redirect_stderr(stderr):
            self.assertEqual(ctl.main(),2)
        self.assertIn('HOLD: SIGNED_FRPS_OWNER_RESPONSE_INVALID',stderr.getvalue())

    def test_foreign_verify_propagated_wss_runtime_hold_is_sanitized(self):
        # WSS-runtime imports an independently instantiated admission module,
        # so its Hold class is not the FRP module's Hold class. The same
        # security rejection must return 2, never leak a traceback or token.
        for error,expected in (
            (ctl.rt.Hold('WSS_RUNTIME_SECURITY_DRIFT'),
             'WSS_RUNTIME_SECURITY_DRIFT'),
            (ctl.rt.Hold('SECRET_PRIVATE_WSS_TOKEN: unexpected bytes'),
             'UNTRUSTED_FRP_ENROLLMENT_STATE'),
        ):
            with self.subTest(expected=expected):
                stderr=io.StringIO()
                with patch('sys.argv',['enroll','verify','--role','foreign']), \
                     patch.object(ctl.os,'geteuid',return_value=0), \
                     patch.object(ctl.rt,'locked',return_value=contextlib.nullcontext()), \
                     patch.object(ctl,'state',return_value={'role':'foreign','state':'COMMITTED'}), \
                     patch.object(ctl,'verify_file',side_effect=error), \
                     patch.object(ctl.rt,'signed_probe') as replay, \
                     patch.object(ctl,'enrolled_status') as inventory, \
                     contextlib.redirect_stderr(stderr):
                    self.assertEqual(ctl.main(),2)
                self.assertEqual(stderr.getvalue().strip(),'HOLD: '+expected)
                self.assertNotIn('Traceback',stderr.getvalue())
                replay.assert_not_called()
                inventory.assert_not_called()

    def test_no_host_binaries_or_network_listener_side_effects(self):
        src=PATH.read_text()
        self.assertIn("choices=('plan','apply','verify','verify-owner','rollback','recover')",src)
        self.assertIn("SNAPSHOTS-CONSOLES-VERIFIED",src)
        self.assertIn("SIGNED_INVENTORY",src)
        self.assertIn("FRP_BINARY_EXTERNAL_MOUNT",src)
        self.assertIn("rt.no_tunnels()",src)
        self.assertIn("verify_file(entry)",src)
        for prohibited in ('--force-recreate','docker restart','docker stop',
                           'systemctl reload','apt install','pip install'):
            self.assertNotIn(prohibited,src)
        self.assertIn("NODE_RESTARTED=NO",src)
        self.assertIn("SANAEI_CHANGED=NO",src)

if __name__=='__main__':
    unittest.main(verbosity=2)
