#!/usr/bin/env python3
"""Unit safety cases for the GitHub-only Nginx transaction controller.

All Docker calls are mocked. Real Docker traffic is tested in the separate
private GitHub-hosted integration job. No host daemon required for this file.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[1] / "modules/smite-backhaul-sidecar-docker-lab.py"
spec = importlib.util.spec_from_file_location("bh_docker_lab", FILE)
lab = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(lab)


class LabControllerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="uopti-bh-executor-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in (
            (".uopti-lab-marker", lab.MARKER.encode()),
            ("baseline.conf", b"server { old; }\n"),
            ("nginx.conf", b"server { old; }\n"),
            ("active.conf", b"server { new; }\n"),
        ):
            path = self.root / name
            path.write_bytes(value)
            path.chmod(0o600)

    def test_workspace_marker_and_symlink_refuse(self):
        self.assertEqual(lab.workspace(self.root), self.root)
        (self.root / ".uopti-lab-marker").write_text("bad marker")
        with self.assertRaises(lab.LabRefused):
            lab.workspace(self.root)
        (self.root / ".uopti-lab-marker").write_text(lab.MARKER)
        (self.root / "active.conf").unlink()
        (self.root / "active.conf").symlink_to(self.root / "baseline.conf")
        with self.assertRaises(lab.LabRefused):
            lab.workspace(self.root)

    def test_non_github_environment_refused(self):
        with patch.dict(os.environ, {
            "GITHUB_ACTIONS": "false",
            "RUNNER_ENVIRONMENT": "github-hosted",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": "aghajani82/u-opti",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
        }):
            with self.assertRaises(lab.LabRefused):
                lab.safe_environment()

    def test_container_exact_run_label_network_and_mount(self):
        run_id, attempt = "123456", "1"
        name = f"uopti-ng-executor-{run_id}-{attempt}"
        net = f"uopti-net-executor-{run_id}-{attempt}"
        container = [{
            "Name": "/" + name, "State": {"Running": True},
            "Config": {"Labels": {"uopti.lab": "backhaul-executor-v1"}},
            "HostConfig": {"NetworkMode": net, "PortBindings": {},
                           "Privileged": False, "PidMode": ""},
            "Mounts": [{"Type": "bind", "Source": str(self.root),
                        "Destination": "/run/uopti-lab", "RW": True}],
        }]
        network = [{"Name": net, "Internal": True}]
        def fake_docker(args):
            if args[:2] == ["docker", "inspect"]:
                return json.dumps(container)
            if args[:3] == ["docker", "network", "inspect"]:
                return json.dumps(network)
            raise AssertionError("Unexpected Docker action")
        with patch.object(lab, "command", side_effect=fake_docker):
            self.assertEqual(lab.validate_container(name, self.root, run_id, attempt), name)
            container[0]["HostConfig"]["NetworkMode"] = "host"
            with self.assertRaises(lab.LabRefused):
                lab.validate_container(name, self.root, run_id, attempt)
            container[0]["HostConfig"]["NetworkMode"] = net
            container[0]["HostConfig"]["PortBindings"] = {"443/tcp": [{"HostPort": "443"}]}
            with self.assertRaises(lab.LabRefused):
                lab.validate_container(name, self.root, run_id, attempt)
            container[0]["HostConfig"]["PortBindings"] = {}
            container[0]["Config"]["Labels"].clear()
            with self.assertRaises(lab.LabRefused):
                lab.validate_container(name, self.root, run_id, attempt)

    def test_apply_and_rollback_preserves_exact_original(self):
        with patch.object(lab, "nginx") as nginx:
            self.assertEqual(lab.apply(self.root, "lab-container"),
                             "APPLIED_WITH_RECOVERY_JOURNAL")
            self.assertEqual((self.root / "nginx.conf").read_bytes(),
                             (self.root / "active.conf").read_bytes())
            self.assertTrue((self.root / lab.JOURNAL).exists())
            self.assertEqual(lab.rollback(self.root, "lab-container"),
                             "ROLLED_BACK_TO_EXACT_BASELINE")
            self.assertEqual((self.root / "nginx.conf").read_bytes(),
                             (self.root / "baseline.conf").read_bytes())
            self.assertFalse((self.root / lab.JOURNAL).exists())
            self.assertFalse((self.root / lab.BACKUP).exists())
            self.assertEqual(nginx.call_count, 5)

    def test_invalid_nginx_syntax_automatically_rolls_back(self):
        calls = []
        def synthetic_nginx(_container, flag):
            calls.append(flag)
            if len(calls) == 2:
                raise lab.LabRefused("Injected invalid Nginx syntax")
        with patch.object(lab, "nginx", side_effect=synthetic_nginx):
            with self.assertRaises(lab.LabRefused):
                lab.apply(self.root, "lab-container")
        self.assertEqual((self.root / "nginx.conf").read_bytes(),
                         (self.root / "baseline.conf").read_bytes())
        self.assertFalse((self.root / lab.JOURNAL).exists())

    def test_foreign_drift_retains_journal(self):
        with patch.object(lab, "nginx"):
            lab.apply(self.root, "lab-container")
            (self.root / "nginx.conf").write_bytes(b"outsider change")
            with self.assertRaises(lab.LabRefused):
                lab.rollback(self.root, "lab-container")
            self.assertTrue((self.root / lab.JOURNAL).exists())
            self.assertEqual((self.root / "nginx.conf").read_bytes(),
                             b"outsider change")

    def test_journal_only_crash_has_safe_idempotent_recovery(self):
        # A power loss after journal durability but before touching Nginx.
        old = (self.root / "nginx.conf").read_bytes()
        data = {
            "version": 1, "container": "lab-container",
            "original_sha": lab.digest(old),
            "active_sha": lab.digest((self.root / "active.conf").read_bytes()),
        }
        lab.atomic_bytes(self.root / lab.JOURNAL,
                         json.dumps(data, sort_keys=True).encode())
        with patch.object(lab, "nginx") as fake:
            self.assertEqual(lab.rollback(self.root, "lab-container"),
                             "ROLLED_BACK_UNCHANGED_BASELINE")
            self.assertEqual(fake.call_count, 2)
        self.assertFalse((self.root / lab.JOURNAL).exists())
        self.assertEqual((self.root / "nginx.conf").read_bytes(), old)

    def test_missing_backup_blocks_applied_rollback(self):
        with patch.object(lab, "nginx"):
            lab.apply(self.root, "lab-container")
            (self.root / lab.BACKUP).unlink()
            with self.assertRaises(lab.LabRefused):
                lab.rollback(self.root, "lab-container")

    def test_no_live_service_or_host_paths_in_interface(self):
        code = FILE.read_text()
        self.assertNotIn("docker run", code)
        self.assertNotIn("docker rm", code)
        self.assertNotIn("systemctl", code)
        self.assertNotIn("sshd", code)
        self.assertNotIn("nginx -s reload", code)


if __name__ == "__main__":
    unittest.main()
