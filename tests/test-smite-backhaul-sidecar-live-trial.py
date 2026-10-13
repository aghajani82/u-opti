#!/usr/bin/env python3
"""Offline mock-service trials of the explicitly gated fresh-host installer.

All mutable fixture paths live under a temporary directory. Python patches
all Docker/Nginx commands; NO live external services or /etc paths touched.
"""
from __future__ import annotations

from contextlib import nullcontext
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-backhaul-sidecar-live-trial.py"
spec = importlib.util.spec_from_file_location("bh_live_trial_under_test", SOURCE)
trial = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(trial)


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.new = self.base / "ir-sidecar.toml"
        self.vhost = self.base / "site.conf"
        self.vhost.write_bytes(b"server { old config }\n")
        self.vhost.chmod(0o644)
        self.original = self.vhost.read_bytes()
        self.resources = [
            {"path": str(self.new), "operation": "create",
             "before": None, "after": b"secret-auth-token-never-print"},
            {"path": str(self.vhost), "operation": "edit",
             "before": self.original, "after": b"server { new config }\n"},
        ]
        self.mock_layout = {"ir": {
            str(self.new): ("create", "ir.toml", "sidecar"),
            str(self.vhost): ("edit", "patched.conf", "nginx"),
        }}
        self.state_dir = self.base / "journal"
        self.fake_container = {"exists": False, "label": "",
                               "fail_reload": False, "fail_docker": False}
        self.events = []

        def fake_root(role, create=False):
            self.assertEqual(role, "ir")
            if create:
                self.state_dir.mkdir(mode=0o700)
            return self.state_dir

        def fake_safe(path, owner=0, mode=None):
            st = path.lstat()
            if not stat.S_ISREG(st.st_mode):
                raise trial.TrialRefused("Symlink or foreign file")
            permissions = stat.S_IMODE(st.st_mode)
            if mode is not None and mode != permissions:
                raise trial.TrialRefused("Permission drift")
            return path.read_bytes(), permissions

        def fake_run(argv, *, capture=False):
            self.events.append(tuple(argv))
            action = argv[:2]
            if action == ["docker", "ps"]:
                if self.fake_container["fail_docker"]:
                    raise trial.TrialRefused("Daemon unavailable")
                return "uopti-backhaul-sidecar-ir" if self.fake_container["exists"] else ""
            if action == ["docker", "inspect"]:
                return "sha256:synthetic|"+trial.IMAGE+"|"+self.fake_container["label"]+"|true"
            if action == ["docker", "run"]:
                self.fake_container["exists"] = True
                label = argv[argv.index("--label") + 1]
                self.fake_container["label"] = label.split("=", 1)[1]
                return ""
            if argv[:3] == ["docker", "rm", "-f"]:
                self.fake_container["exists"] = False
                return ""
            if argv[:3] == ["systemctl", "reload", "nginx"]:
                if self.fake_container["fail_reload"]:
                    self.fake_container["fail_reload"] = False
                    raise trial.TrialRefused("Synthetic failed Nginx reload")
            return ""

        self.patches = [
            patch.object(trial.paired, "LAYOUT", self.mock_layout),
            patch.object(trial.paired, "reconcile", return_value=self.resources),
            patch.object(trial.admission, "admission", return_value=[]),
            patch.object(trial.admission, "_existing_ancestors_safe", return_value=True),
            patch.object(trial, "_safe_file", side_effect=fake_safe),
            patch.object(trial, "_create_dirs", return_value=None),
            patch.object(trial, "_root", side_effect=fake_root),
            patch.object(trial, "mutex", return_value=nullcontext()),
            patch.object(trial, "run", side_effect=fake_run),
            patch.dict(os.environ, {"UOPTI_BH_TEST_HOST": "I_ACCEPT_REBUILD_TEST_HOST"}),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def install(self):
        return trial.install("ir", self.base / "sidecar", self.base / "nginx")

    def test_success_and_explicit_rollback_restores_exact_baseline(self):
        self.assertEqual(self.install(), "TRIAL_INSTALL_LOCAL_CHECKS_PASSED")
        self.assertTrue(self.fake_container["exists"])
        self.assertEqual(self.new.read_bytes(), b"secret-auth-token-never-print")
        self.assertEqual(self.vhost.read_bytes(), b"server { new config }\n")
        self.assertEqual(self.vhost.stat().st_mode & 0o777, 0o644)
        journal = (self.state_dir / trial.JOURNAL).read_text()
        self.assertNotIn("secret-auth-token-never-print", journal)
        self.assertEqual(trial.rollback("ir"), "TRIAL_OWNED_RESOURCES_RECOVERED")
        self.assertFalse(self.new.exists())
        self.assertEqual(self.vhost.read_bytes(), self.original)
        self.assertEqual(self.vhost.stat().st_mode & 0o777, 0o644)
        self.assertFalse(self.fake_container["exists"])
        self.assertFalse(self.state_dir.exists())

    def test_failure_reload_automatically_rolls_back(self):
        self.fake_container["fail_reload"] = True
        with self.assertRaisesRegex(trial.TrialRefused, "recovered"):
            self.install()
        self.assertEqual(self.vhost.read_bytes(), self.original)
        self.assertFalse(self.new.exists())
        self.assertFalse(self.fake_container["exists"])
        self.assertFalse(self.state_dir.exists())

    def test_crash_after_nginx_file_edit_can_resume_recovery(self):
        real_atomic = trial.write_atomic
        def crash_after_edit(path, contents, **kwargs):
            real_atomic(path, contents, **kwargs)
            if path == self.vhost and contents != self.original:
                raise KeyboardInterrupt("Synthetic power loss after atomic rename")
        with patch.object(trial, "write_atomic", side_effect=crash_after_edit):
            with self.assertRaises(KeyboardInterrupt):
                self.install()
        self.assertTrue(self.state_dir.exists())
        self.assertTrue(self.new.exists())
        self.assertEqual(self.vhost.read_bytes(), b"server { new config }\n")
        trial.rollback("ir")
        self.assertFalse(self.state_dir.exists())
        self.assertEqual(self.vhost.read_bytes(), self.original)

    def test_external_file_drift_refuses_all_rollback(self):
        self.install()
        self.vhost.write_bytes(b"server { third-party config }\n")
        event_count = len([e for e in self.events if e[:3] == ("docker", "rm", "-f")])
        with self.assertRaisesRegex(trial.TrialRefused, "drift"):
            trial.rollback("ir")
        self.assertTrue(self.fake_container["exists"])
        self.assertTrue(self.state_dir.exists())
        self.assertEqual(event_count,
                         len([e for e in self.events if e[:3] == ("docker", "rm", "-f")]))

    def test_foreign_docker_label_and_daemon_failure_refuse_rollback(self):
        for kind in ("foreign", "daemon"):
            with self.subTest(kind=kind):
                if not self.state_dir.exists():
                    self.install()
                if kind == "foreign":
                    self.fake_container["label"] = "unrelated-container"
                else:
                    self.fake_container["label"] = trial._journal_read(self.state_dir)["trial_id"]
                    self.fake_container["fail_docker"] = True
                with self.assertRaises(trial.TrialRefused):
                    trial.rollback("ir")
                self.assertTrue(self.new.exists())
                self.assertTrue(self.state_dir.exists())

    def test_repeated_install_blocked(self):
        self.install()
        with self.assertRaisesRegex(trial.TrialRefused, "Existing trial state"):
            self.install()
        self.assertTrue(self.fake_container["exists"])

    def test_without_operator_gate_no_install(self):
        os.environ.pop("UOPTI_BH_TEST_HOST", None)
        with self.assertRaisesRegex(trial.TrialRefused, "not explicitly enabled"):
            self.install()
        self.assertFalse(self.state_dir.exists())
        self.assertEqual(self.vhost.read_bytes(), self.original)

    def test_unknown_candidate_paths_refused(self):
        self.resources[0]["path"] = "/etc/smite-panel/foreign.yml"
        with self.assertRaisesRegex(trial.TrialRefused, "Unrecognized"):
            self.install()
        self.assertFalse(self.state_dir.exists())


if __name__ == "__main__":
    unittest.main()
