#!/usr/bin/env python3
"""Static and pure-function regression checks for Security Monitoring."""
import ast
import importlib.util
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SecurityMonitorContractTests(unittest.TestCase):
    def test_syntax(self):
        subprocess.run(["bash", "-n", str(ROOT / "u-opti")], check=True)
        subprocess.run(["bash", "-n", str(ROOT / "install.sh")], check=True)
        subprocess.run(["bash", "-n", str(ROOT / "modules/security-monitor.sh")], check=True)
        ast.parse((ROOT / "modules/security-monitor.py").read_text(encoding="utf-8"))

    def test_menu_and_both_install_paths(self):
        main = (ROOT / "u-opti").read_text(encoding="utf-8")
        install = (ROOT / "install.sh").read_text(encoding="utf-8")
        menu = (ROOT / "modules/security-monitor.sh").read_text(encoding="utf-8")
        self.assertIn('echo "7) Security Monitoring"', main)
        self.assertIn('u_opti_security_monitor_menu', main)
        self.assertIn('read -rp "Please enter your selection [0-7]: " opt_choice', main)
        for f in ("security-monitor.sh", "security-monitor.py"):
            self.assertIn(f, install)
            self.assertGreaterEqual(main.count(f), 4)
        self.assertIn("1) Install / Enable Daily Monitoring", menu)
        self.assertIn("5) Open Report by Filename", menu)
        self.assertIn("6) Show Last 10 Days", menu)

    def test_archive_allowlist(self):
        path = ROOT / "modules/security-monitor.py"
        spec = importlib.util.spec_from_file_location("securitymonitor", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(module.ARCHIVE_RE.fullmatch("access.log.12.gz"))
        self.assertTrue(module.ARCHIVE_RE.fullmatch("access.log.1"))
        for name in ("access.log", "access.snapshot.20261023T094551Z",
                     "access.log.before-20261023T094551Z",
                     "x-ui.db", "../access.log.1.gz"):
            self.assertFalse(bool(module.ARCHIVE_RE.fullmatch(name)))
        self.assertEqual(module.RETAIN_DAYS, 10)
        self.assertEqual(module.ROTATIONS, 240)

    def test_history_reads_archives_without_exposing_client_labels(self):
        import contextlib
        import datetime as dt
        import gzip
        import io
        import tempfile
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location(
            "securitymonitor_fixture", ROOT / "modules/security-monitor.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = dt.datetime.now().astimezone()
            stamp = now.strftime("%Y/%m/%d %H:%M:%S")
            raw = (stamp + " from 127.0.0.1:1234 accepted tcp:ycxrl.com:80 "
                   "email: khodam\\n")
            (root / "access.log").write_text(raw, encoding="utf-8")
            with gzip.open(root / "access.log.1.gz", "wt") as z:
                z.write(raw)
            (root / "access.snapshot.20261023T094551Z").write_text(
                raw, encoding="utf-8")
            out = io.StringIO()
            with patch.object(module, "known_logdirs", return_value=[root]):
                with contextlib.redirect_stdout(out):
                    module.history()
            result = out.getvalue()
            self.assertIn("XRAY_FILES_SCANNED=2", result)
            self.assertIn("BADBOX_DOMAIN=2", result)
            self.assertNotIn("khodam", result)
            self.assertNotIn("127.0.0.1", result)

    def test_no_automatic_service_changes(self):
        code = (ROOT / "modules/security-monitor.py").read_text(encoding="utf-8")
        self.assertNotIn("systemctl restart", code)
        self.assertNotIn("ufw deny", code)
        self.assertNotIn("docker restart", code)
        self.assertIn("def prune(", code)
        self.assertIn("def generate_report(", code)
        self.assertIn("def install(", code)

if __name__ == "__main__":
    unittest.main()
