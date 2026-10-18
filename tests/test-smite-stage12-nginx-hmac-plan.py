"""Stage12 offline Nginx HMAC gateway plan tests: no live Nginx touched."""
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "modules/smite-stage12-nginx-hmac-plan.py"
spec = importlib.util.spec_from_file_location("stage12_gateway", FILE)
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class GatewayPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "private"
        self.dir.mkdir(mode=0o700)
        self.path = self.dir / "candidate.nginx"

    def test_exact_agent_path_preservation_and_acl(self):
        snippet = plan.render(panel_ip="198.51.100.24")
        self.assertIn("location ^~ /api/agent/", snippet)
        self.assertIn("allow 198.51.100.24;", snippet)
        self.assertIn("deny all;", snippet)
        self.assertIn("limit_except GET POST", snippet)
        self.assertIn("proxy_pass http://127.0.0.1:8888;", snippet)
        self.assertNotIn("proxy_pass http://127.0.0.1:8888/;", snippet)
        self.assertNotIn("proxy_pass https://", snippet)
        self.assertNotIn("nginx -s reload", snippet)
        self.assertNotIn("proxy_set_header X-Smite-", snippet)
        self.assertNotIn("proxy_pass http://0.0.0.0", snippet)

    def test_prepare_is_private_no_overwrite_and_no_active_config(self):
        self.assertEqual(plan.prepare(panel_ip="203.0.113.14", output=self.path),
                         "INERT_NGINX_SNIPPET_PREPARED")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertIn("allow 203.0.113.14;", self.path.read_text())
        with self.assertRaises(plan.NginxPlanHold):
            plan.prepare(panel_ip="203.0.113.15", output=self.path)

    def test_unsafe_source_ips_rejected(self):
        for value in ("x;$dollar", "127.0.0.1", "0.0.0.0", "localhost",
                      "192.168.10.10/24", "fe80::1", "::"):
            with self.subTest(value=value):
                with self.assertRaises(plan.NginxPlanHold):
                    plan.render(panel_ip=value)

    def test_private_directory_permission_required(self):
        self.dir.chmod(0o755)
        with self.assertRaises(plan.NginxPlanHold):
            plan.prepare(panel_ip="198.51.100.24", output=self.path)

    def test_no_live_service_actions_and_packaging(self):
        code = FILE.read_text()
        for forbidden in ("subprocess.run(", "docker compose up",
                          "systemctl reload", "nginx -t", "os.system(",
                          "/etc/nginx/sites-enabled/"):
            self.assertNotIn(forbidden, code)
        for installer in ("install.sh", "u-opti"):
            self.assertIn("smite-stage12-nginx-hmac-plan.py",
                          (ROOT / installer).read_text())


if __name__ == "__main__":
    unittest.main()
