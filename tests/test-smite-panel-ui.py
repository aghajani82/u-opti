#!/usr/bin/env python3
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ui', ROOT/'modules/smite-panel-ui.py')
ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(ui)
BUNDLE = ROOT/'modules/smite-panel-ui.json'
OLD = {'index.html': base64.b64encode(b'old-index').decode(), 'assets/old.js': base64.b64encode(b'old-js').decode()}

class Updates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.state = Path(self.tmp.name)/'state'
        self.current = dict(OLD)
        self.a = patch.object(ui, 'admit', return_value='container-id'); self.a.start()
        self.s = patch.object(ui, 'snapshot', side_effect=lambda cid: dict(self.current)); self.s.start()
        def publish(cid, files, expected):
            self.assertEqual(ui.index_hash(self.current), expected); self.current.update(files)
        self.p = patch.object(ui, 'publish', side_effect=publish); self.p.start()
    def tearDown(self):
        self.a.stop(); self.s.stop(); self.p.stop(); self.tmp.cleanup()
    def run_action(self, action): ui.operate(action, BUNDLE, self.state)
    def test_apply_backup_idempotent_rollback(self):
        self.run_action('apply'); journal = json.loads((self.state/'current.json').read_text())
        self.assertEqual(journal['before'], OLD); self.assertEqual(journal['status'], 'APPLIED')
        self.run_action('apply'); self.assertEqual(json.loads((self.state/'current.json').read_text()), journal)
        self.run_action('rollback'); self.assertEqual(self.current['index.html'], OLD['index.html'])
    def test_corrupt_bundle_does_not_write(self):
        bad=Path(self.tmp.name)/'bad.json';bad.write_text('{}')
        with self.assertRaisesRegex(ValueError,'SHA256'):ui.operate('apply',bad,self.state)
        self.assertEqual(self.current,OLD)
    def test_interrupted_publish_has_backup_and_can_rollback(self):
        with patch.object(ui,'publish',side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):self.run_action('apply')
        self.assertEqual(json.loads((self.state/'current.json').read_text())['before'],OLD)
        with self.assertRaisesRegex(ValueError,'interrupted'):self.run_action('apply')
        self.run_action('rollback');self.assertEqual(self.current['index.html'],OLD['index.html'])
    def test_unknown_ui_drift_blocks_rollback(self):
        self.run_action('apply');self.current['index.html']=base64.b64encode(b'unreviewed').decode()
        with self.assertRaisesRegex(ValueError,'differs'):self.run_action('rollback')
    def test_recreated_container_cannot_use_old_backup(self):
        self.run_action('apply')
        with patch.object(ui,'admit',return_value='different-id'):
            with self.assertRaisesRegex(ValueError,'matching'):self.run_action('rollback')
    def test_journal_symlink_rejected(self):
        self.state.symlink_to(Path(self.tmp.name),target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):self.run_action('apply')
    def test_path_traversal_and_bad_encoding_rejected(self):
        for files in [dict(OLD,**{'../main.py':'YQ=='}), {'index.html':'not base64'}]:
            with self.assertRaises(ValueError):ui.validate(files)
    def test_pinned_source_and_90_percent_desktop_density(self):
        files=ui.bundle(BUNDLE)
        metadata=json.loads(BUNDLE.read_text())
        self.assertEqual(metadata['source_sha'], 'd4b318de24faff3261a93687c37c52ca6a2a0acc')
        self.assertEqual(ui.SOURCE, metadata['source_sha'])
        self.assertEqual(metadata['workflow_run'], 42504320814)
        self.assertEqual(set(files), {'index.html', 'assets/index-BEGdlx2C.css', 'assets/index-CBheFV49.js'})
        css=''.join(base64.b64decode(v).decode() for k,v in files.items() if k.endswith('.css'))
        self.assertIn('@media (min-width: 1024px){html{font-size:90%}}', css)
        self.assertNotIn('font-size:81.25%', css)
        self.assertNotIn('smite-login-footer', css)
        html=base64.b64decode(files['index.html']).decode()
        self.assertIn('/assets/index-BEGdlx2C.css', html)
        self.assertIn('/assets/index-CBheFV49.js', html)
        # The existing Panel image and admission rules remain unchanged.
        self.assertEqual(ui.IMAGE, 'ghcr.io/aghajani82/smite-panel@sha256:180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8')


def real_docker():
    # This explicitly creates a disposable, network-isolated container only.
    name='uopti-ui-test-'+uuid.uuid4().hex[:12]
    try:
        ui.docker('run','-d','--name',name,'--network','none','--entrypoint','python',ui.IMAGE,'-c','import time; time.sleep(300)')
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'private';cid=ui.admit(name)
            before=ui.snapshot(cid); started=json.loads(ui.docker('inspect',cid))[0]['State']['StartedAt']
            ui.operate('apply',BUNDLE,state,name)
            target=ui.bundle(BUNDLE);after=ui.snapshot(cid)
            assert all(after[k]==v for k,v in target.items())
            ui.operate('apply',BUNDLE,state,name)
            ui.operate('rollback',BUNDLE,state,name)
            restored=ui.snapshot(cid);assert all(restored[k]==v for k,v in before.items())
            assert json.loads(ui.docker('inspect',cid))[0]['State']['StartedAt']==started
            print('REAL_RC7_UI_APPLY_VERIFY_ROLLBACK_NO_RESTART=PASS')
    finally:
        ui.docker('rm','-f',name)

if __name__=='__main__':
    if '--docker' in sys.argv:real_docker()
    else:unittest.main()
