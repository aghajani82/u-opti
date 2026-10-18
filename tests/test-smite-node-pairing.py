#!/usr/bin/env python3
"""Offline secure Smite Node pairing preview tests (no network/VPS)."""
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "modules/smite-node-pairing.py"
spec = importlib.util.spec_from_file_location("uopti_pairing_preview", HELPER)
pairing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pairing)


class PreviewTests(unittest.TestCase):
    def test_exact_https_origin(self):
        self.assertEqual(
            pairing.secure_endpoint("https://iran01.kolbe1.ir:443/"),
            "https://iran01.kolbe1.ir/api/node-pairing/redeem",
        )
        bad = (
            "http://iran01.kolbe1.ir", "https://iran01.kolbe1.ir:8888",
            "https://iran01.kolbe1.ir:8000", "https://127.0.0.1",
            "https://user:pass@iran01.kolbe1.ir",
            "https://iran01.kolbe1.ir?token=leak",
            "https://iran01.kolbe1.ir/api/nodes",
            "https://iran01.kolbe1.ir/#fragment", "https://localhost",
            "https://iran01.kolbe1.ir:bad",
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(pairing.WizardHold):
                pairing.secure_endpoint(value)

    def test_standard_only_and_role(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state"
            path.write_text(
                "SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n"
                "SMITE_PANEL_DOMAIN=iran01.kolbe1.ir\n"
            )
            self.assertEqual(pairing._determine_role(pairing.state_values(path)), "foreign")
            path.write_text("SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=private\n")
            with self.assertRaises(pairing.WizardHold):
                pairing.state_values(path)

    def test_private_exclusive_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder) / "identity"
            parent.mkdir(mode=0o700)
            path = parent / "node-identity.json"
            node_id = "bbbbbbbb-1111-2222-3333-444444444444"
            pairing.store_identity(path, node_id, "a" * 64)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text())["node_secret"], "a" * 64)
            with self.assertRaises(pairing.WizardHold):
                pairing.store_identity(path, node_id, "b" * 64)
            self.assertEqual(json.loads(path.read_text())["node_secret"], "a" * 64)

    def test_reject_world_readable_identity_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "open"
            path.mkdir(mode=0o755)
            with self.assertRaises(pairing.WizardHold):
                pairing.store_identity(path / "node-identity.json", "node-abcdefgh", "f" * 64)
            link = Path(folder) / "symlink"
            link.symlink_to(path, target_is_directory=True)
            with self.assertRaises(pairing.WizardHold):
                pairing.prepare_store(link)

    def test_tls_validated_post_and_no_redirect_or_proxy(self):
        with tempfile.TemporaryDirectory() as folder:
            private = Path(folder) / "identities"
            private.mkdir(mode=0o700)
            target = private / "node-identity.json"
            node_id = "node-uniquekey"
            code = "smn1_" + "X" * 43
            secret = "c" * 64
            invoked = []

            class Response:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self, maximum):
                    self_test.assertEqual(maximum, 8193)
                    return json.dumps({"node_id": node_id, "node_secret": secret}).encode()
            self_test = self

            class Opener:
                def open(self, req, timeout):
                    self_test.assertEqual(req.full_url, "https://iran01.kolbe1.ir/api/node-pairing/redeem")
                    self_test.assertNotIn(code, req.full_url)
                    self_test.assertEqual(json.loads(req.data)["pairing_code"], code)
                    invoked.append(timeout)
                    return Response()

            with patch.object(pairing.request, "build_opener", return_value=Opener()) as build:
                with patch.object(pairing.ssl, "create_default_context", return_value=Mock()) as tls:
                    with patch("sys.stdout", io.StringIO()) as display:
                        result = pairing.redeem(
                            panel_url="https://iran01.kolbe1.ir",
                            pairing_code=code, node_id=node_id,
                            role="foreign", destination=target,
                        )
                    self.assertEqual(display.getvalue(), "")
                    self.assertEqual(result, node_id)
                    self.assertTrue(invoked)
                    tls.assert_called_once_with()
                    args = build.call_args.args
                    self.assertEqual(args[0].proxies, {})
                    self.assertIsInstance(args[2], pairing.NoRedirect)
                    self.assertIsInstance(args[1], pairing.request.HTTPSHandler)
            self.assertEqual(json.loads(target.read_text())["node_secret"], secret)
            with self.assertRaises(pairing.WizardHold):
                pairing.redeem(
                    panel_url="https://iran01.kolbe1.ir",
                    pairing_code=code, node_id=node_id,
                    role="foreign", destination=target,
                )

    def test_preview_network_off_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state"
            path.write_text(
                "SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n"
                "SMITE_PANEL_DOMAIN=iran01.kolbe1.ir\n"
            )
            with patch.dict(os.environ, {"UOPTI_SMITE_PAIRING_PREVIEW": ""}):
                with patch.object(pairing, "redeem") as network:
                    with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
                        rc = pairing.run(["--redeem-preview", "--state-path", str(path)])
                    self.assertEqual(rc, 2)
                    network.assert_not_called()

    def test_packaging_and_cli_no_existing_wizard_edits(self):
        wrapper = (ROOT / "modules/smite-node-pairing-wizard.sh").read_text()
        install = (ROOT / "install.sh").read_text()
        launcher = (ROOT / "u-opti").read_text()
        for name in ("smite-node-pairing.py", "smite-node-pairing-wizard.sh"):
            self.assertIn('    "' + name + '"', install)
            self.assertEqual(launcher.count('                "' + name + '"'), 2)
            self.assertEqual(launcher.count('["' + name + '"]="$BASE_URL/modules/' + name + '"'), 1)
            self.assertEqual(launcher.count('["' + name + '"]="$TEMP_DIR/' + name + '"'), 1)
        self.assertIn('if [ "${1:-}" = "--smite-pairing" ]', launcher)
        self.assertIn("smite_node_pairing_menu()", wrapper)
        self.assertNotIn("docker compose up", wrapper)
        self.assertNotIn("systemctl restart", wrapper)


if __name__ == "__main__":
    unittest.main()
