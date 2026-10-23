#!/usr/bin/env python3
"""Offline safety matrix for RC.2 IR Panel-only effective Compose review."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / "modules/smite-rc2-panel-compose-review.py"
spec = importlib.util.spec_from_file_location("panel_rc2_compose_review", PATH)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def valid_effective():
    return {
        "services": {
            "smite-panel": {
                "image": tool.RC1_PANEL,
                "container_name": "smite-panel",
                "network_mode": "host",
                "restart": "unless-stopped",
                "healthcheck": {"test": ["CMD", "true"]},
                "environment": dict(tool.ENV_REQUIRED, SECRET_KEY="SHOULD_NOT_BE_PRINTED"),
                "volumes": [
                    {"type": "bind", "source": source, "target": dest,
                     "read_only": ro}
                    for dest, (source, ro) in tool.REQUIRED_MOUNTS.items()
                ],
            },
            "other-service": {"image": "nginx:alpine"},
        }
    }


class PanelRC2ComposeReviewTest(unittest.TestCase):
    def test_approved_rc1_effective_config(self):
        tool.validate_combined_compose(valid_effective())

    def test_missing_overlay_mount_fail_closed(self):
        cfg = valid_effective()
        cfg["services"]["smite-panel"]["volumes"] = [
            v for v in cfg["services"]["smite-panel"]["volumes"]
            if v["target"] != "/etc/smite-panel/trusted-nodes"
        ]
        with self.assertRaisesRegex(tool.ReviewHold, "mount"):
            tool.validate_combined_compose(cfg)

    def test_signed_mount_must_be_read_only(self):
        cfg = valid_effective()
        for item in cfg["services"]["smite-panel"]["volumes"]:
            if item["target"] == "/etc/smite-panel/trusted-nodes":
                item["read_only"] = False
        with self.assertRaisesRegex(tool.ReviewHold, "mount"):
            tool.validate_combined_compose(cfg)

    def test_signed_auth_never_reverts_to_legacy(self):
        for key, incorrect in (
            ("SMITE_PANEL_AGENT_AUTH_MODE", "legacy"),
            ("SMITE_NODE_REGISTRATION_MODE", "open"),
            ("SMITE_NODE_PAIRING_PREVIEW_ENABLED", "false"),
            ("SMITE_SIGNED_NODE_ORIGINS_PATH", "/tmp/untrusted.json"),
        ):
            cfg = valid_effective()
            cfg["services"]["smite-panel"]["environment"][key] = incorrect
            with self.subTest(key=key), self.assertRaises(tool.ReviewHold):
                tool.validate_combined_compose(cfg)

    def test_rc2_requires_explicit_expected_image_and_preserves_security(self):
        cfg = valid_effective()
        cfg["services"]["smite-panel"]["image"] = tool.RC2_PANEL
        with self.assertRaises(tool.ReviewHold):
            tool.validate_combined_compose(cfg)
        tool.validate_combined_compose(cfg, expected_image=tool.RC2_PANEL)
        cfg["services"]["smite-panel"]["environment"]["SMITE_PANEL_AGENT_AUTH_MODE"] = "legacy"
        with self.assertRaisesRegex(tool.ReviewHold, "Signed"):
            tool.validate_combined_compose(cfg, expected_image=tool.RC2_PANEL)

    def test_unknown_running_panel_digest_is_rejected(self):
        for image in (tool.RC2_PANEL, "ghcr.io/aghajani82/smite-panel:latest"):
            cfg = valid_effective()
            cfg["services"]["smite-panel"]["image"] = image
            with self.assertRaisesRegex(tool.ReviewHold, "reviewed target"):
                tool.validate_combined_compose(cfg)

    def test_duplicate_data_mount_is_rejected(self):
        cfg = valid_effective()
        cfg["services"]["smite-panel"]["volumes"].append(
            copy.deepcopy(cfg["services"]["smite-panel"]["volumes"][0])
        )
        with self.assertRaisesRegex(tool.ReviewHold, "Duplicate"):
            tool.validate_combined_compose(cfg)

    def test_panel_network_or_restart_policy_drift_is_rejected(self):
        for key, bad in (("network_mode", "bridge"), ("restart", "no")):
            cfg = valid_effective()
            cfg["services"]["smite-panel"][key] = bad
            with self.subTest(key=key), self.assertRaises(tool.ReviewHold):
                tool.validate_combined_compose(cfg)

    def test_dry_run_never_changes_files_or_runs_docker_up(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            panel = Path(tmp) / "docker-compose.yml"
            overlay = Path(tmp) / "docker-compose.signed-control.yml"
            panel.write_text("services:\n  smite-panel:\n    image: " + tool.RC1_PANEL + "\n")
            overlay.write_text("known signed overlay fixture")
            original = tool.KNOWN_HASHES.copy()
            tool.KNOWN_HASHES["panel"] = __import__("hashlib").sha256(panel.read_bytes()).hexdigest()
            tool.KNOWN_HASHES["overlay"] = __import__("hashlib").sha256(overlay.read_bytes()).hexdigest()
            captured = []
            def execute(command):
                captured.append(command)
                if command[-3:] == ["config", "--format", "json"]:
                    return json.dumps(valid_effective())
                if command[-2:] == ["{{.Config.Image}}", "smite-panel"]:
                    return tool.RC1_PANEL
                if command[-2:] == ["{{.Config.Image}}", "smite-node"]:
                    return tool.RC1_NODE
                if command[-2:] == ["{{.State.Health.Status}}", "smite-panel"]:
                    return "healthy"
                if command[-2:] == ["{{.State.Health.Status}}", "smite-node"]:
                    return "healthy"
                raise AssertionError("Unexpected non-read-only command")
            try:
                before = [panel.read_bytes(), overlay.read_bytes()]
                output = tool.review(compose=panel, overlay=overlay, execute=execute)
                self.assertEqual(before, [panel.read_bytes(), overlay.read_bytes()])
                self.assertIn("RC2_DEPLOYMENT_AUTHORIZED=NO", output)
                self.assertIn("LIVE_CHANGES=NONE", output)
                self.assertNotIn("SHOULD_NOT_BE_PRINTED", " ".join(output))
                for command in captured:
                    self.assertEqual(command[0], "docker")
                    self.assertIn(command[1], ("compose", "inspect"))
                    self.assertFalse(any(op in command for op in (
                        "pull", "run", "up", "stop", "down", "restart", "build"
                    )))
            finally:
                tool.KNOWN_HASHES.clear()
                tool.KNOWN_HASHES.update(original)

    def test_exact_panel_image_patch_is_in_memory_and_reversible(self):
        import hashlib
        original = (
            "services:\n  smite-panel:\n    image: " + tool.RC1_PANEL
            + "\n    restart: unless-stopped\n"
        ).encode()
        stored = tool.KNOWN_HASHES["panel"]
        try:
            tool.KNOWN_HASHES["panel"] = hashlib.sha256(original).hexdigest()
            proposed = tool.plan_exact_panel_image_replacement(original)
            self.assertIn(tool.RC2_PANEL.encode(), proposed)
            self.assertNotIn(tool.RC1_PANEL.encode(), proposed)
            self.assertEqual(
                proposed.replace(tool.RC2_PANEL.encode(), tool.RC1_PANEL.encode()),
                original,
            )
            self.assertEqual(
                hashlib.sha256(original).hexdigest(),
                tool.KNOWN_HASHES["panel"],
            )
        finally:
            tool.KNOWN_HASHES["panel"] = stored

    def test_exact_panel_patch_fails_closed_on_drift_or_missing_image(self):
        import hashlib
        original = ("services:\n    image: " + tool.RC1_PANEL + "\n").encode()
        stored = tool.KNOWN_HASHES["panel"]
        try:
            tool.KNOWN_HASHES["panel"] = hashlib.sha256(original).hexdigest()
            missing_line = original.replace(b"    image:", b"      image:")
            tool.KNOWN_HASHES["panel"] = hashlib.sha256(missing_line).hexdigest()
            with self.assertRaisesRegex(tool.ReviewHold, "not unique"):
                tool.plan_exact_panel_image_replacement(missing_line)
            tool.KNOWN_HASHES["panel"] = hashlib.sha256(original).hexdigest()
            with self.assertRaisesRegex(tool.ReviewHold, "baseline"):
                tool.plan_exact_panel_image_replacement(original + b"# drift\n")
        finally:
            tool.KNOWN_HASHES["panel"] = stored

    def test_changed_compose_hash_holds_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            panel = Path(tmp) / "compose.yml"
            overlay = Path(tmp) / "override.yml"
            panel.write_text("tampered")
            overlay.write_text("untested")
            with self.assertRaisesRegex(tool.ReviewHold, "SHA256"):
                tool.review(compose=panel, overlay=overlay,
                            execute=lambda cmd: self.fail("Docker should not run"))

    def test_unreviewed_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "compose.yml"
            o = Path(tmp) / "override.yml"
            p.symlink_to("/etc/passwd")
            o.write_text("test")
            with self.assertRaisesRegex(tool.ReviewHold, "not regular"):
                tool.review(compose=p, overlay=o,
                            execute=lambda cmd: self.fail("Docker should not run"))


if __name__ == "__main__":
    unittest.main()
