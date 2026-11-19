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
        self.a = patch.object(ui, 'admit', return_value=('container-id', 'rc7')); self.a.start()
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
        with self.assertRaisesRegex(ValueError,'unknown UI package'):ui.operate('apply',bad,self.state)
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
        with patch.object(ui,'admit',return_value=('different-id','rc7')):
            with self.assertRaisesRegex(ValueError,'matching'):self.run_action('rollback')
    def test_journal_symlink_rejected(self):
        self.state.symlink_to(Path(self.tmp.name),target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):self.run_action('apply')
    def test_path_traversal_and_bad_encoding_rejected(self):
        for files in [dict(OLD,**{'../main.py':'YQ=='}), {'index.html':'not base64'}]:
            with self.assertRaises(ValueError):ui.validate(files)
    def test_exact_rc9_docker_admission_and_unknown_image_rejection(self):
        # Compare the actual loaded Docker Image ID; never trust an image tag
        # or container name as proof of the reviewed image.
        calls=[]
        def mock_docker(*args, **kwargs):
            calls.append(args)
            if args==('inspect','smite-panel'):
                return json.dumps([{'Id':'cid-rc9','Image':'rc9-loaded-id',
                    'State':{'Running':True,'Health':{'Status':'healthy'}},'Mounts':[]}])
            if args==('image','inspect',ui.IMAGE):
                raise subprocess.CalledProcessError(1, 'docker')
            if args==('image','inspect',ui.IMAGE_RC9):
                return json.dumps([{'Id':'rc9-loaded-id'}])
            raise AssertionError('Unexpected Docker invocation '+str(args))
        # setUp stubs admit for transaction fixtures; stop that stub here
        # so this test invokes the REAL exact-image admission code.
        self.a.stop()
        try:
            with patch.object(ui,'docker',side_effect=mock_docker):
                self.assertEqual(ui.admit('smite-panel'),('cid-rc9','rc9'))
        finally:
            self.a.start()
        self.assertIn(('image','inspect',ui.IMAGE_RC9),calls)
        def mock_unknown(*args, **kwargs):
            if args==('inspect','smite-panel'):
                return json.dumps([{'Id':'cid','Image':'unknown-image',
                    'State':{'Running':True},'Mounts':[]}])
            if args[0:2]==('image','inspect'):
                return json.dumps([{'Id':'different-reviewed-image'}])
            raise AssertionError('Unexpected Docker invocation')
        self.a.stop()
        try:
            with patch.object(ui,'docker',side_effect=mock_unknown):
                with self.assertRaisesRegex(ValueError,'exact reviewed'):
                    ui.admit('smite-panel')
        finally:
            self.a.start()

    def test_rc9_uses_separate_pinned_bundle_and_is_rollback_safe(self):
        target=ROOT/'modules/smite-panel-ui-rc9.json'
        self.assertTrue(target.is_file(), 'reviewed RC9 UI payload is missing')
        with patch.object(ui, 'admit', return_value=('container-id', 'rc9')):
            self.run_action('apply')
        journal=json.loads((self.state/'current.json').read_text())
        self.assertEqual(journal['source_sha'],ui.SOURCE_RC9)
        self.assertEqual(journal['container_id'],'container-id')
        with patch.object(ui, 'admit', return_value=('container-id', 'rc9')):
            self.run_action('rollback')
        self.assertEqual(self.current['index.html'],OLD['index.html'])

    def test_rc7_rc9_wrong_bundle_refused(self):
        with patch.object(ui, 'admit', return_value=('container-id','rc7')):
            with self.assertRaisesRegex(ValueError,'RC9 UI cannot'):
                ui.operate('apply',ROOT/'modules/smite-panel-ui-rc9.json',self.state)
        self.assertEqual(self.current,OLD)

    def test_signed_rc9_iran_option1_applies_json_disabled_ui(self):
        # New Iran installs must not activate the suspended JSON-code path.
        # RC9 uses the separately pinned reviewed bundle, not RC7 assets.
        script = r"""
set -euo pipefail
source modules/smite-install.sh
SMITE_IR_RESUMABLE=1
SMITE_IR_STAGE=ADMIN_CREATED
smite_gateway_configure_panel() { :; }
smite_gateway_panel_domain() { printf '%s\\n' 04.example.org; }
smite_gateway_verify_443() { :; }
python3() {
    case "$*" in
        *'smite-node-pairing.py --complete-local-ir-install')
            echo IR_INSTALL_ENROLLMENT=VERIFIED_ACTIVE ;;
        *) echo 'Unexpected Python invocation' >&2; return 77 ;;
    esac
}
smite_install_ir_admin_present() { :; }
smite_install_ir_foreign_schema_stage() {
    echo 'FORBIDDEN_FOREIGN_JSON_TRIAL_STAGE' >&2; return 77;
}
smite_install_ui_action() {
    test "$1" = apply || return 77
    echo 'UI_UPDATE=PASS; source=c5b3558db8c89e5e7ab23854d740d6b80862bec8; restart=NO'
}
smite_install_ir_advance() {
    test "$1" = COMPLETE || return 77
    echo "ADVANCE=$1"
}
smite_install_pause() { :; }
smite_install_finish_local_ir
"""
        proc = subprocess.run(
            ['bash', '-c', script], cwd=ROOT,
            capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn('FORBIDDEN_FOREIGN_JSON_TRIAL_STAGE', proc.stdout + proc.stderr)
        self.assertIn('IR_FOREIGN_JSON_TRIAL=DISABLED', proc.stdout)
        self.assertIn('IR_PANEL_STATIC_UI=APPLIED_FOREIGN_JSON_DISABLED', proc.stdout)
        self.assertIn('ADVANCE=COMPLETE', proc.stdout)
        self.assertIn('PANEL_AND_IR_INSTALL=COMPLETE', proc.stdout)

    def test_rc9_pinned_bundle_from_merge_sha(self):
        target=ROOT/'modules/smite-panel-ui-rc9.json'
        files=ui.bundle(target)
        metadata=json.loads(target.read_text())
        self.assertEqual(metadata['source_sha'],ui.SOURCE_RC9)
        self.assertEqual(metadata['source_sha'], 'c5b3558db8c89e5e7ab23854d740d6b80862bec8')
        self.assertIsInstance(metadata['workflow_run'], int)
        self.assertGreater(metadata['workflow_run'], 0)
        script=[name for name in files if name.startswith('assets/index-') and name.endswith('.js')]
        style=[name for name in files if name.startswith('assets/index-') and name.endswith('.css')]
        self.assertEqual(len(script), 1)
        self.assertEqual(len(style), 1)
        self.assertEqual(set(files), {'index.html', script[0], style[0]})
        js=base64.b64decode(files[script[0]]).decode('utf-8')
        self.assertIn('Experimental Foreign installation JSON is disabled',js)
        self.assertIn('Existing signed Node pairing remains available',js)
        html=base64.b64decode(files['index.html']).decode('utf-8')
        self.assertIn('/'+script[0],html)
        self.assertIn('/'+style[0],html)
        self.assertEqual(ui.IMAGE_RC9,'ghcr.io/aghajani82/smite-panel@sha256:f6999effd131f6b3272f8d9116b3fbae917f699bf9a29271fc5ede24cc387a2e')

    def test_pinned_source_and_90_percent_desktop_density(self):
        files=ui.bundle(BUNDLE)
        metadata=json.loads(BUNDLE.read_text())
        self.assertEqual(metadata['source_sha'], '5e7a289071e446345ac27e4255994daf3446430a')
        self.assertEqual(ui.SOURCE, metadata['source_sha'])
        self.assertEqual(metadata['workflow_run'], 42513266989)
        self.assertEqual(set(files), {'index.html', 'assets/index-c0Ew1NGv.css', 'assets/index-B4YJt7yO.js'})
        css=''.join(base64.b64decode(v).decode() for k,v in files.items() if k.endswith('.css'))
        self.assertIn('@media (min-width: 1024px){html{font-size:90%}}', css)
        self.assertNotIn('font-size:81.25%', css)
        self.assertNotIn('smite-login-footer', css)
        # All six content routes have no old max-width cap; layout geometry is covered by Smite PR #57 browser CI.
        # This exact asset SHA comes from the audited Smite main PR #57 UI build.
        self.assertEqual(__import__('hashlib').sha256(base64.b64decode(files['assets/index-B4YJt7yO.js'])).hexdigest(),
                         '54706d8104b87737d5d0c729dcd446eb95d06adcf9867fb7126604a804045abc')
        html=base64.b64decode(files['index.html']).decode()
        self.assertIn('/assets/index-c0Ew1NGv.css', html)
        self.assertIn('/assets/index-B4YJt7yO.js', html)
        # The existing Panel image and admission rules remain unchanged.
        self.assertEqual(ui.IMAGE, 'ghcr.io/aghajani82/smite-panel@sha256:180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8')


def real_docker():
    # This explicitly creates a disposable, network-isolated container only.
    name='uopti-ui-test-'+uuid.uuid4().hex[:12]
    try:
        ui.docker('run','-d','--name',name,'--network','none','--entrypoint','python',ui.IMAGE,'-c','import time; time.sleep(300)')
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'private';cid,profile=ui.admit(name);assert profile=='rc7'
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
