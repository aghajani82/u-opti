#!/usr/bin/env python3
"""Exact multiline UI JSON -> bounded private Foreign terminal intake."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "foreign_packet_intake",
    ROOT / "modules/smite-unified-foreign-packet-intake.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class OperatorPacketIntake(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / "foreign-fixture"
        self.fixture.mkdir(mode=0o700)
        self.stage = self.fixture / "foreign-staging"
        self.stage.mkdir(mode=0o700)
        self.file = self.stage / "foreign-install-packet.json"
        self.now = 1850000000
        self.grant = {
            "protocol": "smi1",
            "panel_url": "https://panel.example.com",
            "node_id": "foreign-node-1234",
            "node_name": "node-kh",
            "origin": "https://kh.example.com:443",
            "control_url": "https://kh.example.com:443/smite-node/" + "a"*32,
            "installation_code": "smi1_" + "b"*43,
            "expires_at": self.now + 7200,
        }

    def operator_paste(self, data=None, **kwargs):
        packet = self.grant if data is None else data
        stream = io.StringIO(json.dumps(packet, indent=2) + "\n\n")
        params = dict(
            target=self.file, expected_panel="https://panel.example.com",
            expected_domain="https://kh.example.com:443",
            expected_node="node-kh", now=self.now,
            disposable_capability=True)
        params.update(kwargs)
        return module.capture_disposable(stream, **params)

    def test_multiline_panel_information_staged_without_secrets_in_result(self):
        out = self.operator_paste()
        self.assertEqual(out, {
            "status":"STAGED_PRIVATE",
            "node_name":"node-kh",
            "expires_at":self.now+7200,
            "connected":False,
        })
        saved=json.loads(self.file.read_text())
        self.assertEqual(saved, self.grant)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.stage.stat().st_mode & 0o777,0o700)
        self.assertNotIn(self.grant["installation_code"], repr(out))
        self.assertFalse((self.fixture/"node-identity.json").exists())

    def test_second_paste_never_replaces_private_packet(self):
        self.operator_paste()
        original = self.file.read_bytes()
        data={**self.grant,"installation_code":"smi1_"+"c"*43}
        with self.assertRaises(module.Hold):self.operator_paste(data)
        self.assertEqual(self.file.read_bytes(), original)

    def test_expired_or_not_yet_issued_code_refused_before_write(self):
        for stamp in (self.now-1, self.now, self.now+7201):
            with self.subTest(stamp=stamp),self.assertRaises(module.Hold):
                self.operator_paste({**self.grant,"expires_at":stamp})
            self.assertFalse(self.file.exists())

    def test_bad_node_domain_and_panel_metadata_never_saved(self):
        for changes in (
            {"node_name":"other-node"},
            {"origin":"https://other.example.com:443",
             "control_url":"https://other.example.com:443/smite-node/"+"a"*32},
            {"control_url":"https://kh.example.com:443/smite-node/"+"c"*32,
             "installation_code":"invalid"},
            {"panel_url":"https://other.example.com:443"},
            {"protocol":"legacy"},
        ):
            with self.subTest(changes=sorted(changes)),self.assertRaises(module.Hold):
                self.operator_paste({**self.grant, **changes})
            self.assertFalse(self.file.exists())

    def test_wrong_local_expected_domain_or_name_refused(self):
        for override in (
            {"expected_node":"different"},
            {"expected_panel":"https://wrong.example.com"},
            {"expected_domain":"https://wrong.example.com:443"},
        ):
            with self.subTest(override=override),self.assertRaises(module.Hold):
                self.operator_paste(**override)
            self.assertFalse(self.file.exists())

    def test_unfinished_multiline_and_duplicate_json_refused(self):
        json_body=json.dumps(self.grant,indent=2)
        bad = (
            json_body+"\n", # no explicit blank line terminator
            json_body.replace('"protocol": "smi1"', '"protocol": "smi1", "protocol": "smi1"')+"\n\n",
            "{"+"\n"*45+"}\n\n",
            "X"*9000+"\n\n",
            json_body + "\x00\n\n",
        )
        for source in bad:
            with self.subTest(size=len(source)),self.assertRaises(module.Hold):
                module.capture_disposable(io.StringIO(source),target=self.file,
                    expected_panel="https://panel.example.com",
                    expected_domain="https://kh.example.com:443",
                    expected_node="node-kh",now=self.now,disposable_capability=True)
            self.assertFalse(self.file.exists())

    def test_no_fixture_capability_and_no_user_controlled_host_location(self):
        with self.assertRaises(module.Hold):
            self.operator_paste(disposable_capability=False)
        with self.assertRaises(module.Hold):
            self.operator_paste(target=Path("/etc/u-opti/smite/foreign-staging/foreign-install-packet.json"))
        with self.assertRaises(module.Hold):
            self.operator_paste(target=self.fixture/"other.json")
        self.assertFalse(self.file.exists())

    def test_reject_symlink_or_insecure_parent(self):
        self.stage.chmod(0o755)
        with self.assertRaises(module.Hold):self.operator_paste()
        self.stage.chmod(0o700)
        self.fixture.chmod(0o777)
        with self.assertRaises(module.Hold):self.operator_paste()
        self.fixture.chmod(0o700)
        self.stage.rmdir()
        other=self.fixture/"elsewhere"
        other.mkdir(mode=0o700)
        self.stage.symlink_to(other, target_is_directory=True)
        with self.assertRaises(module.Hold):self.operator_paste()
        self.assertFalse(self.file.exists())

    def test_existing_hardlink_or_symlink_target_refused(self):
        bad=self.fixture/"previous"
        bad.write_text("secret")
        bad.chmod(0o600)
        os.link(bad,self.file)
        with self.assertRaises(module.Hold):self.operator_paste()
        self.file.unlink()
        self.file.symlink_to(bad)
        with self.assertRaises(module.Hold):self.operator_paste()
        self.assertEqual(bad.read_text(),"secret")

    def test_capture_failure_does_not_print_a_credential(self):
        secret=self.grant["installation_code"]
        import contextlib
        output=io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(module.Hold) as err:
                self.operator_paste({**self.grant, "node_name":"other"})
        self.assertNotIn(secret,output.getvalue()+str(err.exception))
        self.assertNotIn("node_secret",output.getvalue()+str(err.exception))

    def test_cli_status_only_and_never_activates(self):
        code=ROOT/"modules/smite-unified-foreign-packet-intake.py"
        check=subprocess.run([sys.executable,"-B",str(code),"--status"],
            capture_output=True,text=True,check=True)
        self.assertIn("REAL_HOST_CAPTURE=NOT_AUTHORIZED",check.stdout)
        self.assertIn("FOREIGN_CONNECTED=NOT_PROVEN",check.stdout)
        denied=subprocess.run([sys.executable,"-B",str(code),"--capture"],
            capture_output=True,text=True)
        self.assertNotEqual(denied.returncode,0)


if __name__=="__main__":
    unittest.main(verbosity=2)
