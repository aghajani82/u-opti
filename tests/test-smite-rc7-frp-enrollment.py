#!/usr/bin/env python3
"""RC7 explicit bundled-FRP engine enrollment isolated safety regression."""
import importlib.util
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

    def test_no_host_binaries_or_network_listener_side_effects(self):
        src=PATH.read_text()
        self.assertIn("choices=('plan','apply','verify','rollback','recover')",src)
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
