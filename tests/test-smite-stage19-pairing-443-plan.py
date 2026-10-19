"""Stage19 private Nginx pairing review: offline unit tests only."""
import importlib.util
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-stage19-pairing-443-plan.py"
spec = importlib.util.spec_from_file_location("stage19", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Pairing443PlanTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.parent = Path(temp.name) / "secrets"
        self.parent.mkdir(mode=0o700)
        self.dest = self.parent / "candidate"

    def test_generates_private_secrets_without_log_and_exact_path(self):
        with patch("sys.stdout", new_callable=io.StringIO) as visible:
            self.assertEqual(mod.main([
                "--panel-domain", "ir.kolbe1.ir", "--output-dir", str(self.dest)
            ]), 0)
        self.assertNotIn("SMITE_NODE_PAIRING_INGRESS_TOKEN=", visible.getvalue())
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o700)
        for item in mod._FILE_NAMES:
            self.assertEqual(stat.S_IMODE((self.dest/item).stat().st_mode), 0o600)
        env = (self.dest / "panel-pairing.env").read_text()
        secret = (self.dest / "nginx-ingress-secret.conf").read_text()
        nginx = (self.dest / "nginx-pairing-location.conf").read_text()
        self.assertIn("SMITE_NODE_PAIRING_PREVIEW_ENABLED=false", env)
        token = next(row.partition("=")[2] for row in env.splitlines()
                     if row.startswith("SMITE_NODE_PAIRING_INGRESS_TOKEN="))
        self.assertEqual(len(token), 64)
        self.assertIn(token, secret)
        self.assertNotIn(token, nginx)
        self.assertIn("location = /api/node-pairing/redeem", nginx)
        self.assertIn("limit_except POST { deny all; }", nginx)
        self.assertIn("proxy_request_buffering on;", nginx)
        self.assertIn("proxy_pass http://127.0.0.1:8000;", nginx)
        self.assertNotIn("proxy_pass http://127.0.0.1:8000/;", nginx)
        self.assertIn("include " + str(self.dest) + "/nginx-ingress-secret.conf;", nginx)
        self.assertNotIn("listen 443", nginx)
        self.assertNotIn("listen 8443", nginx)
        self.assertIn("access_log off;", nginx)
        self.assertIn("ACTIVATION=HOLD", visible.getvalue())

    def test_refuses_existing_candidate_insecure_directory_or_symlink(self):
        mod.prepare(domain="ir.kolbe1.ir", output=self.dest)
        initial = (self.dest / "panel-pairing.env").read_bytes()
        with self.assertRaises(mod.Stage19Hold):
            mod.prepare(domain="ir.kolbe1.ir", output=self.dest)
        self.assertEqual((self.dest / "panel-pairing.env").read_bytes(), initial)
        self.parent.chmod(0o755)
        with self.assertRaises(mod.Stage19Hold):
            mod.prepare(domain="ir.kolbe1.ir", output=self.parent/"new")
        self.parent.chmod(0o700)
        (self.parent/"shortcut").symlink_to(self.dest, target_is_directory=True)
        with self.assertRaises(mod.Stage19Hold):
            mod.prepare(domain="ir.kolbe1.ir", output=self.parent/"shortcut")

    def test_rejects_unsafe_domain_and_paths(self):
        for host in ("", "http://ir.kolbe1.ir", "ir.kolbe1.ir:443", "127.0.0.1",
                     "-ir.kolbe1.ir", "ir..kolbe1.ir", "ir.kolbe1.ir/path"):
            with self.subTest(host=host), self.assertRaises(mod.Stage19Hold):
                mod.validate(domain=host, output=self.dest)
        for name in ("../oops", "a b", "unsafe;path"):
            with self.subTest(name=name), self.assertRaises(mod.Stage19Hold):
                mod.validate(domain="ir.kolbe1.ir", output=self.parent/name)

    def test_no_live_execution_and_well_packaged(self):
        source = SOURCE.read_text()
        for banned in ("subprocess.run(", "os.system(", "docker compose up",
                       "systemctl reload", "nginx -t", "/etc/nginx/sites-enabled/"):
            self.assertNotIn(banned, source)
        for script in ("install.sh", "u-opti"):
            self.assertIn("smite-stage19-pairing-443-plan.py", (ROOT/script).read_text())
        installer = (ROOT/"modules/smite-install.sh").read_text()
        self.assertIn('local panel_host="127.0.0.1"', installer)


if __name__ == "__main__":
    unittest.main()
