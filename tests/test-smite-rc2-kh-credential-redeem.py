#!/usr/bin/env python3
"""Offline tests for inert /plan and individually gated KH one-time redemption."""
from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-rc2-kh-credential-redeem.py"
spec = importlib.util.spec_from_file_location("rc2_kh_credential_redeem", SOURCE)
redeemer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redeemer)


class KHRedemptionTests(unittest.TestCase):
    def setUp(self):
        self.helper = Mock()
        self.helper.IDENTITY_DIR = Path("/etc/u-opti/smite/identities")
        self.helper.IDENTITY_FILE = self.helper.IDENTITY_DIR / "node-identity.json"
        self.helper.REPLAY_DB = Path("/var/lib/u-opti/smite-node-security/replay/agent-replay.sqlite3")
        self.helper.state_values.return_value = {
            "SMITE_ROLE": "foreign", "SMITE_NODE_NAME": "node-kh",
            "SMITE_PANEL_DOMAIN": "ir.kolbe1.ir",
            "SMITE_MANAGED_VERSION": "2.0.0-rc.1",
        }
        self.helper.secure_endpoint.return_value = "https://ir.kolbe1.ir/api/node-pairing/redeem"
        import re
        self.helper._NODE_ID = re.compile(r"[A-Za-z0-9_-]{8,80}")
        self.helper._CODE = re.compile(r"smn1_[A-Za-z0-9_-]{32,100}")
        self.admit = Mock()
        self.admit.admit_kh.return_value = [
            "KH_NODE_RC2_PAUSED=PASS",
            "KH_GATEWAY_TLS443=PASS",
            "KH_SANAEI_XHTTP=UNCHANGED",
            "KH_TO_IR_HTTPS=PASS",
            "KH_FOREIGN_SIGNED_RUNTIME=NOT_ACTIVATED",
        ]

    def base(self):
        return (
            patch.object(redeemer.os, "geteuid", return_value=0),
            patch.object(redeemer.socket, "gethostname", return_value="kh"),
            patch.object(redeemer.sys.stdin, "isatty", return_value=True),
            patch.object(redeemer, "load_checked", side_effect=[
                self.helper, self.admit,
            ]),
            patch.object(redeemer, "empty_secure_store"),
            patch("sys.stdout", io.StringIO()),
        )

    def test_wrong_host_fails_before_import(self):
        with patch.object(redeemer.os, "geteuid", return_value=0), \
             patch.object(redeemer.socket, "gethostname", return_value="ir"), \
             patch("sys.stdout", io.StringIO()), \
             patch.object(redeemer, "load_checked") as load:
            self.assertEqual(redeemer.main(["--plan"]), 2)
        load.assert_not_called()

    def test_plan_no_credentials_no_mutation(self):
        with self.base()[0] as _, self.base()[1] as _, self.base()[2] as _, \
             patch.object(redeemer, "load_checked",
                          side_effect=[self.helper, self.admit]), \
             patch.object(redeemer, "empty_secure_store"), \
             patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(redeemer.main(["--plan"]), 0)
            self.assertIn("KH_ONE_TIME_REDEEM_PLAN=PASS_READ_ONLY", out.getvalue())
            self.assertIn("LIVE_CHANGES=NONE", out.getvalue())
        self.helper.prepare_store.assert_not_called()
        self.helper.redeem.assert_not_called()

    def test_apply_refuses_without_two_consents(self):
        with patch.object(redeemer.os, "geteuid", return_value=0), \
             patch.object(redeemer.socket, "gethostname", return_value="kh"), \
             patch.object(redeemer.sys.stdin, "isatty", return_value=True), \
             patch.object(redeemer, "load_checked",
                          side_effect=[self.helper, self.admit]), \
             patch.object(redeemer, "empty_secure_store"), \
             patch.dict(redeemer.os.environ,
                        {"UOPTI_SMITE_PAIRING_FIELD_TRIAL": "NO",
                         "UOPTI_SMITE_RC2_KH_REDEEM": "NO"}), \
             patch("sys.stdout", io.StringIO()):
            self.assertEqual(redeemer.main(["--redeem"]), 2)
        self.helper.prepare_store.assert_not_called()
        self.helper.redeem.assert_not_called()

    def test_apply_refuses_cancel(self):
        with patch.object(redeemer.os, "geteuid", return_value=0), \
             patch.object(redeemer.socket, "gethostname", return_value="kh"), \
             patch.object(redeemer.sys.stdin, "isatty", return_value=True), \
             patch.object(redeemer, "load_checked",
                          side_effect=[self.helper, self.admit]), \
             patch.object(redeemer, "empty_secure_store"), \
             patch.dict(redeemer.os.environ,
                        {"UOPTI_SMITE_PAIRING_FIELD_TRIAL": "YES",
                         "UOPTI_SMITE_RC2_KH_REDEEM": "YES"}), \
             patch("builtins.input", return_value="CANCEL"), \
             patch("sys.stdout", io.StringIO()):
            self.assertEqual(redeemer.main(["--redeem"]), 2)
        self.helper.prepare_store.assert_not_called()
        self.helper.redeem.assert_not_called()

    def test_redemption_uses_hidden_fields_and_never_prints_them(self):
        self.helper._identity_record.return_value = ("node-abcdefgh", "a"*64)
        with patch.object(redeemer.os, "geteuid", return_value=0), \
             patch.object(redeemer.socket, "gethostname", return_value="kh"), \
             patch.object(redeemer.sys.stdin, "isatty", return_value=True), \
             patch.object(redeemer, "load_checked",
                          side_effect=[self.helper, self.admit]), \
             patch.object(redeemer, "empty_secure_store"), \
             patch.dict(redeemer.os.environ,
                        {"UOPTI_SMITE_PAIRING_FIELD_TRIAL": "YES",
                         "UOPTI_SMITE_RC2_KH_REDEEM": "YES"}), \
             patch("builtins.input", return_value="REDEEM-KH-ONCE"), \
             patch.object(redeemer.getpass, "getpass",
                          side_effect=["node-abcdefgh","smn1_"+"B"*40]), \
             patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(redeemer.main(["--redeem"]), 0)
            printed = out.getvalue()
            self.assertIn("KH_PAIRING_REDEMPTION=PASS", printed)
            self.assertNotIn("node-abcdefgh", printed)
            self.assertNotIn("smn1_"+"B"*40, printed)
            self.assertNotIn("a"*64, printed)
        self.helper.prepare_store.assert_called_once()
        self.helper.redeem.assert_called_once_with(
            panel_url="https://ir.kolbe1.ir", pairing_code="smn1_"+"B"*40,
            node_id="node-abcdefgh", role="foreign",
        )

    def test_existing_identity_blocks_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            directory=root/"identities"
            directory.mkdir(mode=0o700)
            (directory/"node-identity.json").write_text("do not overwrite")
            self.helper.IDENTITY_DIR=directory
            self.helper.IDENTITY_FILE=directory/"node-identity.json"
            self.helper.REPLAY_DB=root/"replay.db"
            with self.assertRaisesRegex(redeemer.Hold, "IDENTITY_OR_REPLAY_ALREADY_EXISTS"):
                redeemer.empty_secure_store(self.helper)


if __name__ == "__main__":
    unittest.main()
