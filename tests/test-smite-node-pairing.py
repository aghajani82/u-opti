#!/usr/bin/env python3
"""Offline secure Smite Node pairing preview tests (no network/VPS)."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
import hashlib
import hmac
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

    def test_field_trial_env_update_and_exact_pairing_location(self):
        raw = (
            b"SMITE_NODE_REGISTRATION_MODE=signed\n"
            b"SMITE_PANEL_AGENT_AUTH_MODE=signed\n"
            b"SMITE_NODE_PAIRING_PREVIEW_ENABLED=false\n"
        )
        updated = pairing._env_update(raw, {
            "SMITE_NODE_PAIRING_PREVIEW_ENABLED": "true",
            "SMITE_NODE_PAIRING_MASTER_KEY": "A" * 43 + "=",
            "SMITE_NODE_PAIRING_INGRESS_TOKEN": "b" * 64,
        })
        self.assertEqual(updated.count(b"SMITE_NODE_PAIRING_PREVIEW_ENABLED="), 1)
        self.assertIn(b"SMITE_NODE_PAIRING_PREVIEW_ENABLED=true", updated)
        self.assertIn(b"SMITE_NODE_PAIRING_MASTER_KEY=", updated)
        self.assertIn(b"SMITE_NODE_PAIRING_INGRESS_TOKEN=", updated)

        location = pairing._render_pairing_location()
        self.assertIn("location = /api/node-pairing/redeem", location)
        self.assertIn("include /etc/nginx/u-opti-smite-pairing-secret.conf;", location)
        self.assertIn("proxy_pass http://127.0.0.1:8000;", location)
        self.assertIn("access_log off;", location)
        self.assertNotIn("node_secret", location)
        self.assertNotIn("pairing_code", location)

    def test_private_pairing_secret_store_never_prints_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            parent = root / "smite"
            parent.mkdir(mode=0o700)
            private = parent / "pairing"
            secret_file = private / "panel-pairing-secrets.json"
            with (
                patch.object(pairing, "PAIRING_PRIVATE_DIR", private),
                patch.object(pairing, "PAIRING_SECRETS", secret_file),
                patch("sys.stdout", io.StringIO()) as display,
            ):
                first = pairing._pairing_secrets()
                second = pairing._pairing_secrets()
            self.assertEqual(first, second)
            self.assertEqual(display.getvalue(), "")
            self.assertEqual(stat.S_IMODE(secret_file.stat().st_mode), 0o600)
            self.assertRegex(first[0], r"^[A-Za-z0-9_-]{43}=$")
            self.assertRegex(first[1], r"^[a-f0-9]{64}$")

    def test_replay_marker_db_and_key_binding_must_match_pairing_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            identity_dir = root / "identity"
            replay_dir = root / "replay"
            identity_dir.mkdir(mode=0o700)
            replay_dir.mkdir(mode=0o700)
            identity = identity_dir / "node-identity.json"
            marker = identity_dir / "replay-enrollment.json"
            database = replay_dir / "agent-replay.sqlite3"
            node_id = "node-ir-fieldtrial-0001"
            secret = "d" * 64

            identity.write_text(json.dumps({
                "version": 1, "node_id": node_id, "node_secret": secret,
            }))
            identity.chmod(0o600)
            binding = hmac.new(
                secret.encode("ascii"),
                b"smite-replay-key-binding-v1:" + node_id.encode("ascii"),
                hashlib.sha256,
            ).hexdigest()
            marker.write_text(json.dumps({
                "schema": 1, "node_id": node_id,
                "replay_database": pairing.CONTAINER_REPLAY,
                "status": "ENROLLMENT_STARTED",
                "key_binding": binding,
            }))
            marker.chmod(0o600)
            with sqlite3.connect(database) as db:
                db.execute(
                    "CREATE TABLE agent_nonces("
                    "node_id TEXT NOT NULL, nonce TEXT NOT NULL, "
                    "expires_at INTEGER NOT NULL, PRIMARY KEY(node_id,nonce))"
                )
                db.execute(
                    "CREATE TABLE replay_store_identity(node_id TEXT NOT NULL PRIMARY KEY)"
                )
                db.execute("INSERT INTO replay_store_identity(node_id) VALUES (?)", (node_id,))
                db.execute("PRAGMA user_version=1")
            database.chmod(0o600)

            with (
                patch.object(pairing, "IDENTITY_DIR", identity_dir),
                patch.object(pairing, "IDENTITY_FILE", identity),
                patch.object(pairing, "REPLAY_DIR", replay_dir),
                patch.object(pairing, "REPLAY_DB", database),
            ):
                self.assertTrue(pairing._replay_artifacts_valid())
                changed = json.loads(marker.read_text())
                changed["key_binding"] = "0" * 64
                marker.write_text(json.dumps(changed))
                marker.chmod(0o600)
                with self.assertRaises(pairing.WizardHold):
                    pairing._replay_artifacts_valid()

    def test_live_field_trial_actions_remain_explicitly_gated(self):
        with patch.object(pairing.os, "geteuid", return_value=0):
            with patch.dict(os.environ, {"UOPTI_SMITE_PAIRING_FIELD_TRIAL": ""}):
                with self.assertRaises(pairing.WizardHold):
                    pairing._field_trial_gate()
            with patch.dict(os.environ, {"UOPTI_SMITE_PAIRING_FIELD_TRIAL": "YES"}):
                pairing._field_trial_gate()

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
        self.assertIn("Enable secure Panel pairing on HTTPS/443 (IR)", wrapper)
        self.assertIn("Activate signed IR Node runtime", wrapper)
        self.assertIn("UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES", wrapper)
        self.assertNotIn("node_secret", wrapper)
        self.assertNotIn("pairing_code", wrapper)


if __name__ == "__main__":
    unittest.main()
