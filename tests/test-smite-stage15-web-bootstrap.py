"""Bootstrap and independent Ed25519 key enrollment: crash-safe inert setup."""
import importlib.util
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]/"modules"
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/file)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m
    spec.loader.exec_module(m);return m
boot=load("web_bootstrap_test","smite-stage15-web-bootstrap.py")
keys=load("approval_key_bootstrap_test","smite-stage15-approval-key-enrollment.py")

class SetupTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.root.chmod(0o700)

    def test_inert_bootstrap_does_not_enable_live_mode(self):
        r=boot.prepare(state_dir=self.root/"state",
                       queue_dir=self.root/"pending",root_check=False)
        self.assertEqual(r["service"],"NOT_ENABLED")
        self.assertEqual(r["broker_replay_db"],"UNCHANGED")
        self.assertFalse((self.root/"web-approval-mode.json").exists())
        self.assertTrue((self.root/"state"/"credentials.db").exists())
        self.assertTrue((self.root/"state"/"approval.db").exists())
        with self.assertRaises(boot.BootstrapHold):
            boot.prepare(state_dir=self.root/"state",
                         queue_dir=self.root/"pending",root_check=False)

    def test_distinct_public_private_root_only_key_pair(self):
        private=self.root/"node-approval.key"
        public=self.root/"node-approval.pub"
        digest=keys.generate(private,public,enforce_root=False)
        self.assertEqual(len(digest),64)
        self.assertEqual(len(private.read_bytes()),32)
        self.assertEqual(len(public.read_bytes()),32)
        self.assertNotEqual(private.read_bytes(),public.read_bytes())
        self.assertEqual(stat.S_IMODE(private.stat().st_mode),0o400)
        self.assertEqual(stat.S_IMODE(public.stat().st_mode),0o600)
        with self.assertRaises(keys.KeyEnrollmentHold):
            keys.generate(private,public,enforce_root=False)

    def test_insecure_key_dir_rejected(self):
        self.root.chmod(0o755)
        with self.assertRaises(keys.KeyEnrollmentHold):
            keys.generate(self.root/"a",self.root/"b",enforce_root=False)

if __name__=="__main__":
    unittest.main()
