#!/usr/bin/env python3
"""Offline state-machine tests: RC.2 Panel-only cutover and guarded RC.1 recovery."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules/smite-rc2-ir-panel-rollout.py"
spec = importlib.util.spec_from_file_location("uopti_rc2_ir_panel_rollout", MODULE)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class RuntimeFixture:
    """Mutable virtual host; no Docker, GHCR or /opt files are touched."""

    def __init__(self, root: Path):
        self.compose_before = b"services:\n  smite-panel:\n    image: rc1\n"
        self.compose_after = b"services:\n  smite-panel:\n    image: rc2\n"
        self.actual = self.compose_before
        self.before = {
            "services": {
                "smite-panel": {
                    "image": "rc1",
                    "environment": {
                        "SMITE_NODE_REGISTRATION_MODE": "signed",
                        "SMITE_PANEL_AGENT_AUTH_MODE": "signed",
                    },
                },
            },
        }
        self.patch_history: list[bytes] = []
        self.operations: list[str] = []
        self.health_fails_once = False
        self.fail_after_rename = False
        self.extra_drift = False
        self.panel = SimpleNamespace(
            RC1_PANEL="rc1", RC2_PANEL="rc2",
            KNOWN_HASHES={
                "panel": hashlib.sha256(self.compose_before).hexdigest(),
            },
            validate_combined_compose=self.validate_config,
        )
        self.lock = root / "ir-panel-trial.lock"

    def validate_config(self, doc, *, expected_image="rc1"):
        if doc["services"]["smite-panel"]["image"] != expected_image:
            raise tool.Hold("Panel unexpected image")

    def preflight(self, planner):
        return (self.compose_before, self.compose_after, self.before, "fixture-node-id")

    def config(self):
        import copy
        result = copy.deepcopy(self.before)
        if self.actual == self.compose_after:
            result["services"]["smite-panel"]["image"] = "rc2"
            if self.extra_drift:
                result["services"]["smite-panel"]["environment"]["AUTH"] = "legacy"
        return result

    def change(self, _path, data):
        self.patch_history.append(data)
        self.actual = data
        if self.fail_after_rename and data == self.compose_after:
            raise tool.Hold("fsync failed after atomic rename")

    def runtime_probe(self, *, node_id, target_image, check_foreign_prefix):
        self.operations.append("probe:" + target_image)
        if target_image == "rc1":
            assert not check_foreign_prefix
        else:
            assert check_foreign_prefix

    def pull_or_inspect(self, cmd, *, timeout=60):
        self.operations.append("docker:" + cmd[1])
        if cmd[:2] == ["docker", "pull"]:
            return "complete"
        if cmd[:3] == ["docker", "image", "inspect"]:
            return "found"
        raise AssertionError(f"Unexpected Docker operation {cmd!r}")

    def wait_health(self, *, target_image, timeout=110):
        self.operations.append("healthy:" + target_image)
        if target_image == "rc2" and self.health_fails_once:
            self.health_fails_once = False
            raise tool.Hold("Trial Panel is unhealthy")

    def install_mocks(self):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(tool, "LOCK", self.lock))
        stack.enter_context(patch.object(tool, "preflight", side_effect=self.preflight))
        stack.enter_context(patch.object(tool, "runtime_probe", side_effect=self.runtime_probe))
        stack.enter_context(patch.object(tool, "checked_cosign", lambda _: self.operations.append("signed-pair-verified")))
        stack.enter_context(patch.object(tool, "run", side_effect=self.pull_or_inspect))
        stack.enter_context(patch.object(tool, "safe_file", lambda path, size=262144: self.actual))
        stack.enter_context(patch.object(tool, "save_rollback_copy",
                                         lambda b: self.operations.append("backup-saved")))
        stack.enter_context(patch.object(tool, "change_atomically", side_effect=self.change))
        stack.enter_context(patch.object(tool, "read_only_config", side_effect=self.config))
        stack.enter_context(patch.object(tool, "recreate_panel_only",
                                         lambda: self.operations.append("recreate-panel-only")))
        stack.enter_context(patch.object(tool, "wait_panel_health", side_effect=self.wait_health))
        stack.enter_context(patch.object(tool, "verify_node_unchanged",
                                         lambda _: self.operations.append("ir-node-unchanged")))
        stack.enter_context(patch.object(tool.os, "geteuid", lambda: 0))
        return stack


class IRRC2PanelRolloutTests(unittest.TestCase):
    def run_fixture(self, check, *, approved=True):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = RuntimeFixture(Path(tmp))
            with fixture.install_mocks():
                with patch.dict(
                    os.environ,
                    {"UOPTI_SMITE_IR_RC2_PANEL_FIELD_TRIAL": "YES" if approved else "NO"},
                ):
                    check(fixture)

    def test_explicit_approval_required_before_any_mutation(self):
        def check(fixture):
            with self.assertRaisesRegex(tool.Hold, "authorization missing"):
                tool.apply(fixture.panel, object())
            self.assertEqual(fixture.operations, [])
            self.assertEqual(fixture.patch_history, [])
        self.run_fixture(check, approved=False)

    def test_good_panel_only_upgrade_never_recreates_node(self):
        def check(fixture):
            tool.apply(fixture.panel, object())
            self.assertEqual(fixture.actual, fixture.compose_after)
            self.assertEqual(fixture.patch_history, [fixture.compose_after])
            self.assertEqual(fixture.operations.count("recreate-panel-only"), 1)
            self.assertIn("probe:rc2", fixture.operations)
            self.assertIn("signed-pair-verified", fixture.operations)
            self.assertIn("ir-node-unchanged", fixture.operations)
            self.assertEqual(fixture.operations.count("backup-saved"), 1)
        self.run_fixture(check)

    def test_unhealthy_rc2_rolls_back_rc1_image_and_live_hmac(self):
        def check(fixture):
            fixture.health_fails_once = True
            with self.assertRaisesRegex(tool.Hold, "rollback verified"):
                tool.apply(fixture.panel, object())
            self.assertEqual(fixture.actual, fixture.compose_before)
            self.assertEqual(fixture.patch_history,
                             [fixture.compose_after, fixture.compose_before])
            self.assertEqual(fixture.operations.count("recreate-panel-only"), 2)
            self.assertIn("healthy:rc1", fixture.operations)
            self.assertIn("probe:rc1", fixture.operations)
            self.assertNotIn("docker:rm", fixture.operations)
        self.run_fixture(check)

    def test_effective_signed_env_drift_blocks_before_recreate(self):
        def check(fixture):
            fixture.extra_drift = True
            with self.assertRaisesRegex(tool.Hold, "rollback verified"):
                tool.apply(fixture.panel, object())
            self.assertEqual(fixture.actual, fixture.compose_before)
            self.assertEqual(fixture.operations.count("recreate-panel-only"), 0)
            self.assertIn("probe:rc1", fixture.operations)
        self.run_fixture(check)

    def test_error_after_atomic_rename_triggers_rollback(self):
        def check(fixture):
            fixture.fail_after_rename = True
            with self.assertRaisesRegex(tool.Hold, "rollback verified"):
                tool.apply(fixture.panel, object())
            self.assertEqual(fixture.actual, fixture.compose_before)
            self.assertEqual(fixture.operations.count("recreate-panel-only"), 0)
        self.run_fixture(check)

    def test_unsafe_missing_host_confirmation_blocks_in_main(self):
        with patch.object(tool.os, "geteuid", lambda: 0):
            with patch.dict(os.environ, {"UOPTI_SMITE_IR_RC2_PANEL_FIELD_TRIAL": "YES"}):
                self.assertEqual(tool.main(["--apply", "--confirm-ir-host", "kh.kolbe1.ir"]), 2)

    def test_default_plan_has_no_apply_or_compose_mutation(self):
        with patch.object(tool.os, "geteuid", lambda: 0), \
             patch.object(tool, "load_helper") as helper, \
             patch.object(tool, "preflight") as preflight, \
             patch.object(tool, "apply") as apply:
            p = SimpleNamespace()
            helper.return_value = p
            preflight.return_value = (b"old", b"new", {}, "node-id")
            self.assertEqual(tool.main([]), 0)
            apply.assert_not_called()
            helper.assert_called_once_with(
                "smite-rc2-panel-compose-review.py", "uopti_rc2_panel_review"
            )


if __name__ == "__main__":
    unittest.main()
