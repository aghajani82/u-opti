#!/usr/bin/env python3
"""No-server offline regression tests for IR RC2 XHTTP module-only parity repair."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"modules/smite-frp-rc2-xhttp-module-upgrade.py"
spec=importlib.util.spec_from_file_location("uopti_rc2_module_repair",SCRIPT)
tx=importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)


class RC2ModuleRepairTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="uopti-rc2-module-")
        self.addCleanup(t.cleanup)
        root=Path(t.name)
        modules=root/"modules"
        modules.mkdir()
        stage=root/"stage"
        stage.mkdir()
        txbase=root/"var"/"repair"
        txbase.parent.mkdir()
        self.shell=modules/"smite-frp-xhttp.sh"
        self.helper=modules/"smite-frp-xhttp-paths.py"
        self.gate=modules/"smite-frp-rc2-gateway-ready.py"
        self.staged=stage/"smite-frp-rc2-gateway-ready.py"
        self.snippet=root/"xhttp.conf"
        self.old=b"#!/usr/bin/env bash\necho legacy\n"
        self.new=b"#!/usr/bin/env bash\necho reviewed\n"
        self.helper_bytes=b"#!/usr/bin/env python3\npass\n"
        self.gate_bytes=b"#!/usr/bin/env python3\nprint('reviewed')\n"
        self.shell.write_bytes(self.old)
        self.shell.chmod(0o644)
        self.helper.write_bytes(self.helper_bytes)
        self.staged.write_bytes(self.gate_bytes)
        self.staged.chmod(0o600)
        self.snippet.write_bytes(tx.HEADER)
        fixes=[
            ("MOD_DIR",modules),("SHELL",self.shell),("HELPER",self.helper),
            ("GATE",self.gate),("STAGED_GATE",self.staged),
            ("SNIPPET",self.snippet),("TX_BASE",txbase),
            ("TX",txbase/"ir"),("BACKUP",txbase/"ir"/"before"),
            ("RECORD",txbase/"ir"/"record.json"),
            ("OLD_SHELL",tx.blob(self.old)),
            ("NEW_SHELL",tx.blob(self.new)),
            ("PATH_HELPER",tx.blob(self.helper_bytes)),
            ("GATE_BLOB",tx.blob(self.gate_bytes)),
        ]
        for key,value in fixes:
            p=patch.object(tx,key,value)
            p.start();self.addCleanup(p.stop)
        patches=[
            patch.object(tx,"read_root",
                         side_effect=lambda path,limit,mode=None:Path(path).read_bytes()),
            patch.object(tx,"secure_dir",return_value=None),
            patch.object(tx,"timer_idle",return_value=None),
            patch.object(tx,"gate_check",return_value=None),
            patch.object(tx,"reviewed_shell",return_value=self.new),
            patch.object(tx,"engine_lock",
                         side_effect=lambda:os.open(os.devnull,os.O_RDONLY)),
            patch.object(tx.os,"geteuid",return_value=0),
            patch.object(tx.os,"uname",return_value=type("U",(),{"nodename":"ir"})()),
        ]
        for p in patches:
            p.start();self.addCleanup(p.stop)

    def test_plan_does_not_write_or_replace_any_module(self):
        before=tx.prepare()
        self.assertEqual(before[:3],(self.old,self.new,self.gate_bytes))
        self.assertEqual(self.shell.read_bytes(),self.old)
        self.assertFalse(self.gate.exists())
        self.assertFalse(tx.TX_BASE.exists())

    def test_apply_only_changes_exact_shell_and_adds_gate(self):
        tx.apply()
        self.assertEqual(self.shell.read_bytes(),self.new)
        self.assertEqual(self.gate.read_bytes(),self.gate_bytes)
        self.assertEqual(self.helper.read_bytes(),self.helper_bytes)
        self.assertEqual(self.snippet.read_bytes(),tx.HEADER)
        self.assertEqual(stat.S_IMODE(self.shell.stat().st_mode),0o644)
        self.assertEqual(stat.S_IMODE(self.gate.stat().st_mode),0o644)
        self.assertEqual(stat.S_IMODE(tx.BACKUP.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(tx.RECORD.stat().st_mode),0o600)
        self.assertEqual(json.loads(tx.RECORD.read_text())["state"],"COMMITTED")
        tx.verify()

    def test_explicit_rollback_requires_no_published_routes(self):
        tx.apply()
        tx.rollback()
        self.assertEqual(self.shell.read_bytes(),self.old)
        self.assertFalse(self.gate.exists())
        self.assertEqual(tx.record()["state"],"ROLLED_BACK")

    def test_external_shell_drift_blocks_rollback(self):
        tx.apply()
        self.shell.write_bytes(b"unsafe third party change")
        with self.assertRaisesRegex(tx.Hold,"CRITICAL_EXTERNAL_SHELL_CHANGE"):
            tx.rollback()
        self.assertTrue(self.gate.exists())

    def test_published_route_blocks_rollback(self):
        tx.apply()
        self.snippet.write_bytes(tx.HEADER+b"    location = /45121/www {}\n")
        with self.assertRaisesRegex(tx.Hold,"CRITICAL_ACTIVE_ROUTE_PREVENTS_ROLLBACK"):
            tx.rollback()
        self.assertEqual(self.shell.read_bytes(),self.new)

    def test_wrong_old_module_hash_blocks_all_changes(self):
        self.shell.write_bytes(b"unknown old version")
        with self.assertRaisesRegex(tx.Hold,"UNKNOWN_INSTALLED_XHTTP_SHELL"):
            tx.apply()
        self.assertFalse(self.gate.exists())
        self.assertFalse(tx.TX_BASE.exists())

    def test_helper_version_drift_blocks_all_changes(self):
        self.helper.write_bytes(b"unknown helper")
        with self.assertRaisesRegex(tx.Hold,"PATH_HELPER_VERSION_DRIFT"):
            tx.apply()
        self.assertFalse(self.gate.exists())

    def test_existing_unreviewed_gate_blocks_upgrade(self):
        self.gate.write_bytes(b"unreviewed")
        with self.assertRaisesRegex(tx.Hold,"EXISTING_GATE_DO_NOT_REPLACE"):
            tx.apply()
        self.assertEqual(self.gate.read_bytes(),b"unreviewed")

    def test_failed_gate_after_install_auto_restores(self):
        with patch.object(tx,"gate_check",side_effect=[
            None,tx.Hold("SIGNED_RC2_GATE_HOLD")]):
            with self.assertRaisesRegex(tx.Hold,"MODULE_UPGRADE_FAILED_ROLLED_BACK"):
                tx.apply()
        self.assertEqual(self.shell.read_bytes(),self.old)
        self.assertFalse(self.gate.exists())
        self.assertEqual(tx.record()["state"],"ROLLED_BACK")

    def test_no_runtime_activation_or_unreviewed_provider_change(self):
        code=SCRIPT.read_text()
        self.assertNotIn("systemctl reload nginx",code)
        self.assertNotIn("docker compose up",code)
        self.assertNotIn("systemctl enable",code)
        self.assertNotIn("location = /45121/www",code)
        self.assertIn("UOPTI_RC2_IR_XHTTP_MODULE_TRIAL",code)
        self.assertIn("AUTHORIZE-IR-RC2-XHTTP-MODULE-UPGRADE",code)


if __name__=="__main__":
    unittest.main(verbosity=2)
