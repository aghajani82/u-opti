#!/usr/bin/env python3
"""Exercise the retained Panel policy without Docker or a live RC9 host."""
import copy
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(file):
    spec = importlib.util.spec_from_file_location(file, ROOT / "modules" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


panel = load("smite-rc9-retained-panel.py")
runtime = load("smite-rc7-wss-runtime.py")


class RetainedPanel(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.old = "old-image"
        self.new_id = "sha256:" + "a" * 64
        self.wss = root / "wss.yml"
        self.new = root / panel.OVERLAY_NAME
        self.files = [str(root / "compose.yml"), str(root / "signed.yml")]
        self.old_label = ",".join([*self.files, str(self.wss)])
        self.new_label = ",".join([*self.files, str(self.new), str(self.wss)])
        self.doc = {"state": "COMMITTED", "role": "ir", "baseline": {
            "smite-panel": {"files": self.files, "image_id": "old-id"}}}
        self.record = {"phase": "COMMITTED", "image_id": self.new_id, "wss_sha": "wss"}
        self.rt = SimpleNamespace(p=SimpleNamespace(PANEL=root), need=runtime.need,
                                  run=Mock(return_value=self.new_id),
                                  overlay_path=lambda _: self.wss)
        self.obj = {
            "Config": {"Image": panel.IMAGE, "Env": ["SMITE_VERSION=2.0.0-rc.9"],
                       "Cmd": ["/bin/sh", "/app/start.sh"], "Entrypoint": None,
                       "Labels": {"com.docker.compose.project.config_files": self.new_label}},
            "HostConfig": {"NetworkMode": "host"}, "Mounts": [], "Image": self.new_id,
        }

    def normalize(self, obj):
        with patch.object(panel, "read_record", return_value=self.record), \
                patch.object(panel, "wss_sha", return_value="wss"), \
                patch.object(panel, "check_overlay"):
            panel.original_identity(self.rt, obj, self.doc, self.old)

    def test_only_image_and_compose_source_are_normalized(self):
        expected = copy.deepcopy(self.obj)
        expected["Config"]["Image"] = self.old
        expected["Config"]["Labels"]["com.docker.compose.project.config_files"] = self.old_label
        expected["Image"] = "old-id"
        self.normalize(self.obj)
        self.assertEqual(self.obj, expected)
        # An environment or host drift reaches the unchanged WSS digest check.
        baseline = {"signature": runtime.runtime_signature(expected)}
        self.obj["Config"]["Env"].append("SMITE_ENGINE_MANAGEMENT_MODE=legacy")
        with self.assertRaisesRegex(runtime.Hold, "WSS_RUNTIME_SECURITY_DRIFT"):
            runtime.check_runtime_signature(self.obj, baseline)

    def test_unapproved_or_wrong_local_image_remains_held(self):
        self.rt.run.return_value = "unexpected-image-id"
        with self.assertRaisesRegex(runtime.Hold, "RETAINED_PANEL_IMAGE_DRIFT"):
            self.normalize(self.obj)

    def test_wrong_compose_file_order_remains_held(self):
        self.obj["Config"]["Labels"]["com.docker.compose.project.config_files"] = self.old_label
        with self.assertRaisesRegex(runtime.Hold, "RETAINED_PANEL_COMPOSE_OWNER_DRIFT"):
            self.normalize(self.obj)

    def test_no_approval_does_not_invoke_cosign(self):
        with patch.object(panel, "APPROVAL_COMMIT", ""):
            with self.assertRaisesRegex(runtime.Hold, "RETAINED_PANEL_SIGNED_APPROVAL_REQUIRED"):
                panel.signed_release(self.rt)
        self.rt.run.assert_not_called()

    def test_missing_cosign_uses_verified_bootstrap_and_cleans_up(self):
        self.rt.trusted_path = Mock()

        def bootstrap(command, **_):
            self.assertIn("smite_install_rc7_verified_cosign", command[4])
            self.assertEqual(command[-1], "test-digest")
            Path(command[-2]).write_bytes(b"fixture")
            return SimpleNamespace(returncode=0)

        with patch.object(panel, "STATE", self.new.parent / "state"), \
                patch.object(panel.os, "uname", return_value=SimpleNamespace(machine="x86_64")), \
                patch.object(panel.shutil, "which", return_value=None), \
                patch.object(panel.subprocess, "run", side_effect=bootstrap):
            with panel.cosign_binary(self.rt, "test-digest") as binary:
                temporary = Path(binary)
                self.assertTrue(temporary.is_file())
                self.assertEqual(temporary.stat().st_mode & 0o777, 0o700)
            self.assertFalse(temporary.parent.exists())

    def test_compose_only_accepts_exact_image_change(self):
        self.rt.trusted_path = Mock()
        self.rt.check_rc9_compose = Mock()
        self.rt.compose = Mock(return_value=["docker", "compose", "-f", str(self.wss)])
        old = '{"services":{"smite-panel":{"image":"old","network_mode":"host"}}}'
        new = old.replace('"old"', '"' + panel.IMAGE + '"')
        self.rt.run.side_effect = [old, new]
        panel.compose_commands(self.rt, self.doc, installed=False)
        self.rt.run.side_effect = [old, new.replace('"host"', '"bridge"')]
        with self.assertRaisesRegex(runtime.Hold, "RETAINED_PANEL_COMPOSE_CHANGE_EXCEEDS_IMAGE"):
            panel.compose_commands(self.rt, self.doc, installed=False)

    def test_recreate_scoped_to_panel_and_never_pulls(self):
        panel.recreate(self.rt, ["docker", "compose"])
        self.rt.run.assert_called_once_with(
            ["docker", "compose", "up", "-d", "--no-deps", "--no-build", "--pull", "never",
             "--force-recreate", "smite-panel"], timeout=180)


if __name__ == "__main__":
    unittest.main()
