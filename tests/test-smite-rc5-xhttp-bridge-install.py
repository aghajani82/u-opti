#!/usr/bin/env python3
"""Offline-only RC5 U-OPTI bridge transaction tests; no real host service calls."""
from __future__ import annotations

import dataclasses
import importlib.util
import json
from pathlib import Path
import os
import stat
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules" / "smite-rc5-xhttp-bridge-install.py"
spec = importlib.util.spec_from_file_location("uopti_rc5_xhttp_install_test", SOURCE)
tx = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tx
spec.loader.exec_module(tx)
REAL_EFFECTIVE_BRIDGE_GATE = tx.verify_effective_bridge

PREVIOUS_SOURCE = ROOT / "tests" / "test-smite-rc5-xhttp-bridge-admission.py"
spec2 = importlib.util.spec_from_file_location("rc5_fixture", PREVIOUS_SOURCE)
fixture = importlib.util.module_from_spec(spec2)
sys.modules[spec2.name] = fixture
spec2.loader.exec_module(fixture)


class HostDirectorySecurityTests(unittest.TestCase):
    """Offline regression for Ubuntu root:root /run/lock 01777."""

    def fake_stat(self, mode, uid=0, gid=0, kind=stat.S_IFDIR):
        return SimpleNamespace(st_mode=kind | mode, st_uid=uid, st_gid=gid)

    def test_exact_sticky_system_lock_directory_only(self):
        self.assertEqual(tx.LOCK.parent, Path("/run/lock"))
        with patch.object(Path, "lstat", return_value=self.fake_stat(0o1777)):
            tx.trusted_lock_directory(Path("/run/lock"))
            # A mode-01777 nginx directory is still untrusted.
            with self.assertRaisesRegex(tx.Hold, "UNTRUSTED_DIRECTORY"):
                tx.trusted_dir(Path("/etc/nginx"))
            with self.assertRaisesRegex(tx.Hold, "UNEXPECTED_LOCK_DIRECTORY"):
                tx.trusted_lock_directory(Path("/tmp"))
            with self.assertRaisesRegex(tx.Hold, "UNEXPECTED_LOCK_DIRECTORY"):
                tx.trusted_lock_directory(Path("/run/lock/../tmp"))

    def test_lock_directory_rejects_noncanonical_modes_owners_and_symlinks(self):
        candidates = [
            self.fake_stat(0o0777),  # writable, but no sticky bit
            self.fake_stat(0o2777),  # unexpected setgid
            self.fake_stat(0o1775),
            self.fake_stat(0o1755),
            self.fake_stat(0o1777, uid=1),
            self.fake_stat(0o1777, gid=1),
            self.fake_stat(0o0777, kind=stat.S_IFLNK),
            self.fake_stat(0o1777, kind=stat.S_IFREG),
        ]
        for state in candidates:
            with self.subTest(mode=oct(state.st_mode), uid=state.st_uid, gid=state.st_gid):
                with patch.object(Path, "lstat", return_value=state):
                    with self.assertRaisesRegex(tx.Hold, "UNTRUSTED_LOCK_DIRECTORY"):
                        tx.trusted_lock_directory(Path("/run/lock"))


class BridgeInstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="uopti-rc5-install-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.etc = self.root / "nginx"
        self.etc.mkdir()
        self.data = self.root / "varlibuopti"
        self.data.mkdir()
        self.backend = self.etc / "backend.conf"
        self.backend.write_bytes(fixture.BACKEND)
        self.backend.chmod(0o644)
        self.legacy = self.etc / "legacy.conf"
        self.legacy.write_bytes(fixture.LEGACY)
        self.legacy.chmod(0o644)
        self.bridge = self.etc / "bridge.conf"
        self.route_dir = self.etc / "managed"
        self.lock = self.root / "engine.lock"
        self.tx_root = self.data / "transaction"
        self.tx_dir = self.tx_root / "ir"
        self.backup = self.tx_dir / "backend.before"
        self.journal = self.tx_dir / "journal.json"
        self.plan_obj = tx.admission.propose_bridge(
            backend=fixture.BACKEND,
            stream=fixture.STREAM,
            sni_map=fixture.SNI_MAP,
            legacy=fixture.LEGACY,
            domain=fixture.DOMAIN,
            timer_enabled=False,
            bridge_exists=False,
            directory_exists=False,
        )
        self.log = []
        self.break_first_reload = False

        def mock_reload():
            self.log.append("RELOAD")
            if self.break_first_reload:
                self.break_first_reload = False
                raise tx.Hold("SIMULATED_RELOAD_FAILED")

        overrides = {
            "BACKEND": self.backend,
            "BRIDGE": self.bridge,
            "ROUTE_DIR": self.route_dir,
            "LOCK": self.lock,
            "TX_ROOT": self.tx_root,
            "TX_DIR": self.tx_dir,
            "BACKUP": self.backup,
            "JOURNAL": self.journal,
        }
        for name, value in overrides.items():
            p = patch.object(tx, name, value)
            p.start()
            self.addCleanup(p.stop)
        mocks = [
            patch.object(tx, "host_gate", return_value=None),
            patch.object(tx.admission, "audit_read_only", return_value=self.plan_obj),
            patch.object(tx, "nginx_test", side_effect=lambda: self.log.append("TEST")),
            patch.object(tx, "nginx_reload", side_effect=mock_reload),
            patch.object(tx, "verify_effective_bridge", side_effect=lambda: self.log.append("EFFECTIVE")),
            patch.object(tx, "probe_panel", side_effect=lambda domain:
                         self.log.append("TLS_" + domain)),
        ]
        for p in mocks:
            p.start()
            self.addCleanup(p.stop)

    def use_bootstrap_directory(self):
        self.route_dir.mkdir(mode=0o755)
        self.plan_obj = dataclasses.replace(self.plan_obj, route_dir_preexisting=True)
        tx.admission.audit_read_only.return_value = self.plan_obj

    def test_clean_rc_empty_directory_preserved_after_apply_verify_and_rollback(self):
        self.use_bootstrap_directory()
        before = self.route_dir.stat()
        tx.plan()
        self.assertFalse(self.journal.exists())
        tx.apply()
        tx.verify()
        self.assertTrue(json.loads(self.journal.read_text())["route_dir_preexisting"])
        tx.rollback()
        after = self.route_dir.stat()
        self.assertEqual((before.st_ino, before.st_mode), (after.st_ino, after.st_mode))
        self.assertFalse(self.bridge.exists())
        self.assertEqual(self.backend.read_bytes(), fixture.BACKEND)

    def test_clean_rc_reload_failure_preserves_bootstrap_directory(self):
        self.use_bootstrap_directory()
        self.break_first_reload = True
        with self.assertRaisesRegex(tx.Hold, "APPLY_FAILED_ROLLED_BACK"):
            tx.apply()
        self.assertTrue(self.route_dir.is_dir())
        self.assertEqual(self.route_dir.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.backend.read_bytes(), fixture.BACKEND)

    def test_preexisting_directory_rejects_unsafe_modes_owners_symlink_and_contents(self):
        self.use_bootstrap_directory()
        for mode in (0o777, 0o775, 0o700, 0o2755):
            self.route_dir.chmod(mode)
            with self.assertRaises(tx.admission.BridgeHold): tx.plan()
        self.route_dir.chmod(0o755)
        real_lstat = Path.lstat
        for uid, gid in ((1, 0), (0, 1)):
            def wrong_owner(path, *args, **kwargs):
                value = real_lstat(path, *args, **kwargs)
                if path == self.route_dir:
                    fields = list(value)
                    fields[4:6] = [uid, gid]
                    return os.stat_result(fields)
                return value
            with patch.object(Path, 'lstat', wrong_owner):
                with self.assertRaises(tx.admission.BridgeHold): tx.plan()
        (self.route_dir / 'existing.conf').write_text('unreviewed route')
        with self.assertRaises(tx.admission.BridgeHold): tx.plan()
        (self.route_dir / 'existing.conf').unlink()
        self.route_dir.rmdir()
        self.route_dir.symlink_to(self.etc, target_is_directory=True)
        with self.assertRaises(tx.admission.BridgeHold): tx.plan()
        self.assertFalse(self.journal.exists())

    def test_preexisting_directory_with_later_route_still_blocks_rollback(self):
        self.use_bootstrap_directory()
        tx.apply()
        (self.route_dir / 'route.conf').write_text('later route')
        with self.assertRaisesRegex(tx.Hold, "MANAGED_ROUTES_REQUIRE_REVIEW"):
            tx.rollback()
        self.assertTrue(self.bridge.exists())

    def test_old_schema_one_transaction_remains_recoverable(self):
        tx.prepare(self.plan_obj)
        record = json.loads(self.journal.read_text())
        record['schema'] = 1
        del record['route_dir_preexisting']
        self.journal.write_text(json.dumps(record))
        tx.rollback()
        self.assertEqual(json.loads(self.journal.read_text())['state'], 'ROLLED_BACK')

    def test_plan_creates_no_files_or_service_changes(self):
        tx.plan()
        self.assertEqual(self.backend.read_bytes(), fixture.BACKEND)
        self.assertFalse(self.tx_root.exists())
        self.assertFalse(self.bridge.exists())
        self.assertFalse(self.route_dir.exists())
        self.assertFalse(self.lock.exists())
        self.assertEqual(self.log, [])

    def test_apply_creates_bridge_only_and_tracks_commit(self):
        tx.apply()
        self.assertEqual(self.backend.read_bytes(), self.plan_obj.candidate)
        self.assertEqual(self.bridge.read_bytes(), tx.BRIDGE_BYTES)
        self.assertEqual(self.backend.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.bridge.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.route_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.route_dir.iterdir()), [])
        self.assertEqual(self.legacy.read_bytes(), fixture.LEGACY)
        self.assertEqual(json.loads(self.journal.read_text())["state"], "COMMITTED")
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.journal.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.log.count("RELOAD"), 1)
        tx.verify()
        with self.assertRaises(tx.Hold):
            tx.apply()

    def test_failed_nginx_reload_restores_only_our_bridge(self):
        self.break_first_reload = True
        with self.assertRaises(tx.Hold) as caught:
            tx.apply()
        self.assertEqual(str(caught.exception), "APPLY_FAILED_ROLLED_BACK")
        self.assertEqual(self.backend.read_bytes(), fixture.BACKEND)
        self.assertEqual(self.legacy.read_bytes(), fixture.LEGACY)
        self.assertFalse(self.bridge.exists())
        self.assertFalse(self.route_dir.exists())
        self.assertEqual(json.loads(self.journal.read_text())["state"], "ROLLED_BACK")
        self.assertEqual(self.log.count("RELOAD"), 2)

    def test_operator_rollback_preserves_legacy_and_rejects_new_routes(self):
        tx.apply()
        (self.route_dir / "52000.conf").write_text("manual foreign contents")
        with self.assertRaisesRegex(tx.Hold, "MANAGED_ROUTES_REQUIRE_REVIEW"):
            tx.rollback()
        self.assertEqual(self.backend.read_bytes(), self.plan_obj.candidate)
        self.assertTrue(self.bridge.exists())
        (self.route_dir / "52000.conf").unlink()
        tx.rollback()
        self.assertEqual(self.backend.read_bytes(), fixture.BACKEND)
        self.assertFalse(self.bridge.exists())
        self.assertFalse(self.route_dir.exists())
        self.assertEqual(json.loads(self.journal.read_text())["state"], "ROLLED_BACK")

    def test_prepared_crash_is_explicitly_recoverable(self):
        tx.prepare(self.plan_obj)
        tx.rollback()
        self.assertEqual(self.backend.read_bytes(), fixture.BACKEND)
        self.assertEqual(json.loads(self.journal.read_text())["state"], "ROLLED_BACK")

    def test_unknown_backend_drift_and_symlink_hold_without_cleanup(self):
        tx.apply()
        self.backend.write_bytes(fixture.BACKEND.replace(b"8443", b"9443"))
        with self.assertRaisesRegex(tx.Hold, "BACKEND_EXTERNAL_DRIFT"):
            tx.rollback()
        self.assertTrue(self.bridge.exists())
        self.assertEqual(json.loads(self.journal.read_text())["state"], "COMMITTED")

    def test_tampered_journal_refuses_rollback(self):
        tx.apply()
        data = json.loads(self.journal.read_text())
        data["after_sha"] = "0" * 64
        self.journal.write_text(json.dumps(data))
        with self.assertRaises(tx.Hold):
            tx.rollback()
        self.assertTrue(self.bridge.exists())

    def test_effective_nginx_requires_real_bridge_include_and_all_sources(self):
        config = "".join(
            f"# configuration file {p}:\n"
            for p in (self.backend, self.bridge, tx.admission.LEGACY,
                      tx.admission.STREAM, tx.admission.SNI_MAP)
        )
        config += tx.admission.INCLUDE.decode()
        config += tx.BRIDGE_BYTES.decode()

        with patch.object(tx.admission, "_run", return_value=(0, config)):
            REAL_EFFECTIVE_BRIDGE_GATE()
        for bad in (
            config.replace(tx.admission.INCLUDE.decode(), ""),
            config.replace(f"# configuration file {self.bridge}:\n", ""),
            config.replace(tx.BRIDGE_BYTES.decode(), ""),
        ):
            with self.subTest(bad=bad), patch.object(tx.admission, "_run", return_value=(0, bad)):
                with self.assertRaises(tx.Hold):
                    REAL_EFFECTIVE_BRIDGE_GATE()

    def test_manual_only_cli_never_calls_apply_or_rollback_without_approval(self):
        with patch.object(sys, "argv", ["program", "apply"]), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(tx.main(), 2)
        with patch.object(sys, "argv", ["program", "rollback"]), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(tx.main(), 2)
        self.assertFalse(self.tx_root.exists())

    def test_plan_fails_closed_on_stale_backup_directory_or_symlinks(self):
        self.tx_dir.mkdir(parents=True)
        with self.assertRaises(tx.Hold):
            tx.plan()
        self.tx_dir.rmdir()
        self.bridge.symlink_to(self.legacy)
        with self.assertRaises(tx.Hold):
            tx.apply()
        self.assertEqual(self.legacy.read_bytes(), fixture.LEGACY)


if __name__ == "__main__":
    unittest.main()
