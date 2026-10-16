#!/usr/bin/env python3
"""Run the non-distributed activation engine on private fake filesystem only.

All Docker/Nginx commands use a MOCK driver. No host services are changed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import os
import stat
import tempfile
import unittest
from unittest.mock import patch


BASE = Path(__file__).resolve().parents[1]
source = BASE / "modules/smite-backhaul-sidecar-live-engine.py"
spec = importlib.util.spec_from_file_location("sidecar_live_engine_test", source)
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class FakeDriver:
    def __init__(self, role):
        self.role = role
        self.calls = []
        self.running_id = None
        self.fail_next = None
        self.fail_ps = False

    def call(self, argv, timeout=45):
        cmd = " ".join(argv[:2])
        self.calls.append(argv[:])
        if self.fail_next == cmd:
            self.fail_next = None
            raise live.ActivationRefused("mock failure")
        if argv[:2] == ["docker", "ps"]:
            if self.fail_ps:
                raise live.ActivationRefused("mock daemon unreachable")
            return live.CONTAINER[self.role] if self.running_id is not None else ""
        if argv[:2] == ["docker", "inspect"]:
            if self.running_id is None:
                raise live.ActivationRefused("not found")
            if "-f" in argv:
                return self.running_id + "|" + live.IMAGE
            return "yes"
        if argv[:2] == ["docker", "run"]:
            tx = next(x[9:] for x in argv if x.startswith("uopti.tx="))
            self.running_id = tx
        if argv[:3] == ["docker", "rm", "-f"]:
            self.running_id = None
        return "ok"


class LiveEngineTests(unittest.TestCase):
    def fixture(self, role):
        td = tempfile.TemporaryDirectory(prefix="uopti-bh-live-fixture-", dir="/tmp")
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        root.chmod(0o700)
        marker = root / ".uopti-live-engine-fixture"
        marker.write_text("unit-test-only")
        marker.chmod(0o600)
        for location in ("etc/u-opti", "etc/nginx", "etc/nginx/conf.d",
                         "etc/nginx/sites-available",
                         "var/lib/u-opti/backhaul-sidecar"):
            path = root / location
            path.mkdir(parents=True, exist_ok=True)
            if location.endswith("backhaul-sidecar"):
                path.chmod(0o700)
        original = b"server { listen 443; }\n"
        patched = b"server { listen 443; # patched }\n"
        rows = []
        for path, (op, _, _) in live.pair.LAYOUT[role].items():
            if op == "edit":
                target = root / path.lstrip("/")
                target.write_bytes(original)
                target.chmod(0o640)
            rows.append({
                "path": path, "operation": op,
                "before": original if op == "edit" else None,
                "after": patched if op == "edit" else b"private-fixture-value",
            })
        driver = FakeDriver(role)
        engine = live.LiveEngine(root=root, driver=driver)
        return root, rows, driver, engine, original

    def approve(self, engine, rows, role):
        with patch.object(live.admission, "admission", return_value=[]),              patch.object(live.pair, "reconcile", return_value=rows):
            result = engine.prepare(role, Path("/tmp/mock-stage"),
                                    Path("/tmp/mock-nginx"))
            self.assertEqual(rows, result)

    def mock_health(self):
        return patch.object(live.admission.local, "inspect_local", return_value=[])

    def test_apply_and_restore_exact_files_and_owner_metadata(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                root, rows, driver, engine, old = self.fixture(role)
                self.approve(engine, rows, role)
                with self.mock_health():
                    txid = engine.apply(role, rows, txn_id="a" * 32)
                self.assertEqual(txid, "a" * 32)
                self.assertIsNotNone(driver.running_id)
                changed = next(x for x in rows if x["operation"] == "edit")
                target = root / changed["path"].lstrip("/")
                self.assertEqual(target.read_bytes(), changed["after"])
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
                txn = root / "var/lib/u-opti/backhaul-sidecar" / txid
                self.assertTrue((txn / "vhost-original").is_file())
                self.assertEqual(stat.S_IMODE((txn / "vhost-original").stat().st_mode), 0o600)
                self.assertEqual(live.shasum((txn / "vhost-original").read_bytes()),
                                 live.shasum(old))
                engine.rollback(role, txid)
                self.assertIsNone(driver.running_id)
                self.assertEqual(target.read_bytes(), old)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
                for row in rows:
                    if row["operation"] == "create":
                        self.assertFalse((root / row["path"].lstrip("/")).exists())

    def test_nginx_or_docker_error_rolls_back_with_journal(self):
        for role in ("ir", "kh"):
            for stage in ("nginx -t", "docker run", "docker update"):
                with self.subTest(role=role, failure=stage):
                    root, rows, driver, engine, original = self.fixture(role)
                    driver.fail_next = stage
                    self.approve(engine, rows, role)
                    with self.mock_health(), self.assertRaises(live.ActivationRefused):
                        engine.apply(role, rows, txn_id="b" * 32)
                    self.assertIsNone(driver.running_id)
                    edit = next(x for x in rows if x["operation"] == "edit")
                    self.assertEqual((root / edit["path"].lstrip("/")).read_bytes(),
                                     original)
                    self.assertTrue((root / "var/lib/u-opti/backhaul-sidecar" /
                                    ("b" * 32) / "journal.json").exists())

    def test_unknown_file_drift_refuses_destructive_rollback(self):
        root, rows, driver, engine, _ = self.fixture("kh")
        self.approve(engine, rows, "kh")
        with self.mock_health():
            engine.apply("kh", rows, txn_id="c" * 32)
        edited = next(x for x in rows if x["operation"] == "edit")
        target = root / edited["path"].lstrip("/")
        target.write_bytes(target.read_bytes() + b"external-change")
        before = len(driver.calls)
        with self.assertRaises(live.ActivationRefused):
            engine.rollback("kh", "c" * 32)
        self.assertEqual(before, len(driver.calls))
        self.assertIsNotNone(driver.running_id)

    def test_no_approval_and_unmarked_host_refused(self):
        root, rows, driver, engine, _ = self.fixture("ir")
        with self.assertRaises(live.ActivationRefused):
            engine.apply("ir", rows, txn_id="d" * 32)
        self.approve(engine, rows, "ir")
        rows[0]["after"] = b"unexpected-upstream"
        with self.assertRaises(live.ActivationRefused):
            engine.apply("ir", rows, txn_id="d" * 32)
        self.assertEqual([], driver.calls)
        (root / ".uopti-live-engine-fixture").unlink()
        with self.assertRaises(live.ActivationRefused):
            engine.rollback("ir", "d" * 32)

    def test_host_command_allowlist_rejects_argument_injection(self):
        strict = live.SubprocessDriver
        label = "uopti.tx=" + "a" * 32
        image = live.IMAGE
        name = live.CONTAINER["ir"]
        allowed_run = [
            "docker", "run", "-d", "--name", name,
            "--label", label, "--network", "host", "--restart", "no",
            "--read-only", "--cap-drop", "ALL", "--security-opt",
            "no-new-privileges", "--mount",
            "type=bind,src=/etc/u-opti/backhaul-sidecar/ir.toml,dst=/run/backhaul/config.toml,readonly",
            "--entrypoint", "/usr/local/bin/backhaul", image, "-c",
            "/run/backhaul/config.toml",
        ]
        self.assertTrue(strict.allowed(allowed_run))
        self.assertTrue(strict.allowed(["docker", "ps", "-a", "--filter",
                                       "name=^/" + name + "$", "--format",
                                       "{{.Names}}"]))
        self.assertTrue(strict.allowed(["docker", "inspect", "-f",
                                       strict.LABEL_FMT, name]))
        self.assertTrue(strict.allowed(["docker", "rm", "-f", name]))
        self.assertTrue(strict.allowed(["docker", "update", "--restart",
                                       "unless-stopped", name]))
        self.assertTrue(strict.allowed(["nginx", "-t"]))
        self.assertTrue(strict.allowed(["systemctl", "reload", "nginx"]))
        dangerous = [
            ["docker", "rm", "-f", "smite-node"],
            ["docker", "system", "prune", "-af"],
            ["systemctl", "stop", "nginx"],
            ["nginx", "-s", "stop"],
            ["docker", "inspect", name],
            ["docker", "ps", "-a"],
            allowed_run + ["--privileged"],
            [x.replace("host", "bridge") for x in allowed_run],
            [x.replace(image, "ubuntu:latest") for x in allowed_run],
            [x.replace("/etc/u-opti/backhaul-sidecar/ir.toml",
                       "/etc/shadow") for x in allowed_run],
            [x.replace(label, "uopti.tx=nothex") for x in allowed_run],
        ]
        from unittest.mock import patch as local_patch
        driver = strict()
        with local_patch.object(live.subprocess, "run") as exec_mock:
            for command in dangerous:
                with self.subTest(command=command), self.assertRaises(live.ActivationRefused):
                    driver.call(command)
            exec_mock.assert_not_called()

    def test_docker_daemon_failure_during_rollback_holds_everything(self):
        root, rows, driver, engine, original = self.fixture("kh")
        self.approve(engine, rows, "kh")
        with self.mock_health():
            engine.apply("kh", rows, txn_id="e" * 32)
        before = {
            row["path"]: (root / row["path"].lstrip("/")).read_bytes()
            for row in rows
        }
        driver.running_id = "f" * 32  # foreign container label
        driver.fail_ps = True
        with self.assertRaises(live.ActivationRefused):
            engine.rollback("kh", "e" * 32)
        for row in rows:
            self.assertEqual((root / row["path"].lstrip("/")).read_bytes(),
                             before[row["path"]])
        self.assertTrue((root / "var/lib/u-opti/backhaul-sidecar"
                         / ("e" * 32) / "journal.json").exists())

    def test_foreign_container_name_blocks_rollback_without_file_changes(self):
        root, rows, driver, engine, _ = self.fixture("ir")
        self.approve(engine, rows, "ir")
        with self.mock_health():
            engine.apply("ir", rows, txn_id="f" * 32)
        driver.running_id = "e" * 32
        before_calls = len(driver.calls)
        with self.assertRaises(live.ActivationRefused):
            engine.rollback("ir", "f" * 32)
        self.assertEqual(
            [(x[:2]) for x in driver.calls[before_calls:]],
            [["docker", "inspect"], ["docker", "ps"]]
        )
        self.assertTrue((root / "var/lib/u-opti/backhaul-sidecar"
                         / ("f" * 32) / "journal.json").exists())

    def test_synthetic_root_refuses_nonmocked_real_host_driver(self):
        root, rows, driver, _, _ = self.fixture("ir")
        with self.assertRaises(live.ActivationRefused):
            live.LiveEngine(root=root, driver=live.SubprocessDriver())

    def test_cli_is_off_and_code_not_packaged(self):
        import subprocess
        import sys
        completed = subprocess.run([sys.executable, "-B", str(source)],
                                   capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("NOT enabled", completed.stdout)
        install = (BASE / "install.sh").read_text()
        updater = (BASE / "u-opti").read_text()
        self.assertNotIn('"smite-backhaul-sidecar-live-engine.py"', install)
        self.assertNotIn('"smite-backhaul-sidecar-live-engine.py"', updater)


if __name__ == "__main__":
    unittest.main()
