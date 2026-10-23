#!/usr/bin/env python3
"""Offline, no-network tests for guarded KH-only RC.2 Node rollback transaction."""
from __future__ import annotations

from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "modules/smite-rc2-kh-node-rollout.py"
spec = importlib.util.spec_from_file_location("uopti_kh_rc2_node_trial", PATH)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class KHFixture:
    def __init__(self, root: Path):
        self.original = b"node-image=rc1"
        self.candidate = b"node-image=rc2"
        self.disk = self.original
        self.log: list[str] = []
        self.health_fail_once = False
        self.after_rename_fail = False
        self.signed_env_drift = False
        self.rollback_fail = False
        self.planner = SimpleNamespace(
            RC1_NODE="rc1", RC2_NODE="rc2", SANAEI_IMAGE="sanaei-id",
        )
        self.old_effective = {
            "services": {
                "smite-node": {
                    "image": "rc1",
                    "network_mode": "host",
                    "environment": {
                        "SMITE_AGENT_AUTH_MODE": "strict",
                        "SMITE_NODE_PANEL_AUTH_MODE": "paused",
                        "SMITE_ENGINE_INVENTORY_MODE": "managed",
                        "SOME_SECRET": "NEVER_PRINT",
                    },
                    "volumes": [{"source": "/etc/u-opti/smite", "target": "/config"}],
                }
            }
        }
        self.lock = root / "lock"

    def preflight(self, planner):
        self.log.append("admission")
        return self.original, self.candidate, self.old_effective

    def signatures(self, registry, planner):
        self.log.append("cosign-both-roles")

    def run(self, cmd, *, timeout=40):
        if cmd[:2] == ["docker", "pull"]:
            self.log.append("pull-rc2")
            return "pulled"
        if cmd[:3] == ["docker", "image", "inspect"]:
            self.log.append("image-locally-present")
            return "yes"
        raise AssertionError("unexpected host mutation in test: " + repr(cmd))

    def read_regular(self, path, *, limit=262144):
        return self.disk

    def save_original(self, content):
        self.log.append("backup:rc1")
        assert content == self.original

    def atomic_write(self, path, content):
        if content == self.original and self.rollback_fail:
            raise tool.Hold("simulated rollback write failure")
        self.disk = content
        self.log.append("atomic:rc2" if content == self.candidate else "atomic:rc1")
        if content == self.candidate and self.after_rename_fail:
            raise tool.Hold("simulated fsync failure after rename")

    def compose_effective(self):
        new = json.loads(json.dumps(self.old_effective))
        if self.disk == self.candidate:
            new["services"]["smite-node"]["image"] = "rc2"
            if self.signed_env_drift:
                new["services"]["smite-node"]["environment"]["SMITE_AGENT_AUTH_MODE"] = "off"
        return new

    def recreate_node(self):
        self.log.append("recreate-only-smite-node")

    def wait_node(self, image, *, timeout=110):
        self.log.append("wait-" + image)
        if image == "rc2" and self.health_fail_once:
            self.health_fail_once = False
            raise tool.Hold("new Node health failure")

    def runtime_node(self, expected_image, planner):
        self.log.append("runtime-health:" + expected_image)
        assert (self.disk == self.candidate) == (expected_image == "rc2")

    def patch_all(self):
        stack = ExitStack()
        for name, func in (
            ("preflight", self.preflight),
            ("signatures", self.signatures),
            ("run", self.run),
            ("read_regular", self.read_regular),
            ("save_original", self.save_original),
            ("atomic_write", self.atomic_write),
            ("compose_effective", self.compose_effective),
            ("recreate_node", self.recreate_node),
            ("wait_node", self.wait_node),
            ("runtime_node", self.runtime_node),
        ):
            stack.enter_context(patch.object(tool, name, side_effect=func))
        stack.enter_context(patch.object(tool, "LOCK", self.lock))
        stack.enter_context(patch.object(tool.os, "geteuid", return_value=0))
        # Only exact blob fixture bytes, not a local host.
        stack.enter_context(patch.object(tool, "ORIGINAL_SHA",
                                         __import__("hashlib").sha256(self.original).hexdigest()))
        return stack


class KHNodeRolloutTests(unittest.TestCase):
    def exercise(self, callback, *, approved=True):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = KHFixture(Path(tmp))
            with fixture.patch_all(), patch.dict(
                os.environ,
                {"UOPTI_SMITE_KH_RC2_NODE_FIELD_TRIAL": "YES" if approved else "NO"},
            ):
                callback(fixture)

    def test_requires_explicit_env_optin_before_mutation(self):
        def test(f):
            with self.assertRaisesRegex(tool.Hold, "opt-in missing"):
                tool.apply(f.planner, object())
            self.assertEqual(f.log, [])
        self.exercise(test, approved=False)

    def test_approved_trial_recreates_only_smite_node(self):
        def test(f):
            tool.apply(f.planner, object())
            self.assertEqual(f.disk, f.candidate)
            self.assertEqual(f.log.count("recreate-only-smite-node"), 1)
            self.assertIn("cosign-both-roles", f.log)
            self.assertIn("runtime-health:rc2", f.log)
            self.assertIn("backup:rc1", f.log)
            self.assertNotIn("atomic:rc1", f.log)
        self.exercise(test)

    def test_unhealthy_rc2_rolls_back_rc1_and_health(self):
        def test(f):
            f.health_fail_once = True
            with self.assertRaisesRegex(tool.Hold, "restored and independently verified"):
                tool.apply(f.planner, object())
            self.assertEqual(f.disk, f.original)
            self.assertEqual(f.log.count("recreate-only-smite-node"), 2)
            self.assertIn("runtime-health:rc1", f.log)
        self.exercise(test)

    def test_signed_environment_drift_blocks_before_recreate(self):
        def test(f):
            f.signed_env_drift = True
            with self.assertRaisesRegex(tool.Hold, "restored and independently verified"):
                tool.apply(f.planner, object())
            self.assertEqual(f.disk, f.original)
            self.assertNotIn("recreate-only-smite-node", f.log)
            self.assertIn("runtime-health:rc1", f.log)
        self.exercise(test)

    def test_failure_after_atomic_rename_still_restores_rc1(self):
        def test(f):
            f.after_rename_fail = True
            with self.assertRaisesRegex(tool.Hold, "restored and independently verified"):
                tool.apply(f.planner, object())
            self.assertEqual(f.disk, f.original)
            self.assertNotIn("recreate-only-smite-node", f.log)
        self.exercise(test)

    def test_unrecoverable_rollback_reports_critical_not_success(self):
        def test(f):
            f.health_fail_once = True
            f.rollback_fail = True
            with self.assertRaisesRegex(tool.Hold, "CRITICAL"):
                tool.apply(f.planner, object())
            # The normal preflight RC.1 probe runs once; failed rollback must\n            # not create a second, falsely successful recovery probe.\n            self.assertEqual(f.log.count("runtime-health:rc1"), 1)
        self.exercise(test)

    def test_default_plan_never_triggers_apply(self):
        with patch.object(tool.os, "geteuid", return_value=0), \
             patch.object(tool, "helper") as helper, \
             patch.object(tool, "preflight") as preflight, \
             patch.object(tool, "apply") as apply:
            helper.return_value = object()
            preflight.return_value = (b"original", b"candidate", {})
            self.assertEqual(tool.main([]), 0)
            apply.assert_not_called()
            helper.assert_called_once_with("smite-rc2-kh-node-plan.py", "kh_rc2_plan")

    def test_other_host_not_authorized(self):
        with patch.object(tool.os, "geteuid", return_value=0), \
             patch.object(tool, "helper", return_value=object()), \
             patch.object(tool, "apply") as apply, \
             patch.dict(os.environ, {"UOPTI_SMITE_KH_RC2_NODE_FIELD_TRIAL": "YES"}):
            self.assertEqual(
                tool.main(["--apply", "--confirm-kh-host", "ir.kolbe1.ir"]), 2,
            )
            apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
