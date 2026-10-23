#!/usr/bin/env python3
"""No-network tests for safe, inert KH RC.2 Node image-only plan."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "modules/smite-rc2-kh-node-plan.py"
spec = importlib.util.spec_from_file_location("smite_rc2_kh_node_plan", PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def baseline():
    return {
        "services": {
            "smite-node": {
                "container_name": "smite-node",
                "image": mod.RC1_NODE,
                "network_mode": "host",
                "healthcheck": {"test": ["CMD", "true"]},
                "environment": dict(mod.SECURITY),
            }
        }
    }


class KHPlanTests(unittest.TestCase):
    def test_exact_one_line_round_trip_only(self):
        content = (
            "services:\n  smite-node:\n    image: " + mod.RC1_NODE
            + "\n    restart: unless-stopped\n"
        ).encode()
        old_sha = mod.COMPOSE_SHA
        try:
            mod.COMPOSE_SHA = hashlib.sha256(content).hexdigest()
            result = mod.exact_node_image_plan(content)
            self.assertIn(mod.RC2_NODE.encode(), result)
            self.assertEqual(
                result.replace(mod.RC2_NODE.encode(), mod.RC1_NODE.encode()),
                content,
            )
        finally:
            mod.COMPOSE_SHA = old_sha

    def test_changed_input_sha_or_yaml_line_is_rejected(self):
        content = ("    image: " + mod.RC1_NODE + "\n").encode()
        old_sha = mod.COMPOSE_SHA
        try:
            mod.COMPOSE_SHA = hashlib.sha256(content).hexdigest()
            for wrong in (content + b"# drift\n", content.replace(b"    image:", b"      image:")):
                with self.assertRaises(mod.Hold):
                    mod.exact_node_image_plan(wrong)
            malformed = content.replace(b"    image:", b"      image:")
            mod.COMPOSE_SHA = hashlib.sha256(malformed).hexdigest()
            with self.assertRaisesRegex(mod.Hold, "whole Node image line"):
                mod.exact_node_image_plan(malformed)
            double = content * 2
            mod.COMPOSE_SHA = hashlib.sha256(double).hexdigest()
            with self.assertRaisesRegex(mod.Hold, "whole Node image line"):
                mod.exact_node_image_plan(double)
        finally:
            mod.COMPOSE_SHA = old_sha

    def test_duplicate_or_invalid_state_rejected(self):
        for payload in (
            b"SMITE_ROLE=foreign\nSMITE_ROLE=foreign\n",
            b"SMITE ROLE=foreign\n",
            b"SMITE_ROLE\n",
        ):
            with self.subTest(payload=payload), self.assertRaises(mod.Hold):
                mod.read_state(payload)

    def simulated_audit(self, *, env_override=None, inspect_override=None,
                        ss_override=None, guard_override=None):
        content = ("    image: " + mod.RC1_NODE + "\n").encode()
        original = mod.COMPOSE_SHA
        mod.COMPOSE_SHA = hashlib.sha256(content).hexdigest()
        calls: list[list[str]] = []
        try:
            def read_file(path, *, limit=256000):
                if path == mod.NODE_COMPOSE:
                    return content
                if path == mod.STATE:
                    return (b"SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n"
                            b"SMITE_MANAGED_VERSION=2.0.0-rc.1\n")
                self.fail("Unexpected file inspection")
            def execute(cmd):
                calls.append(cmd)
                if cmd[:2] == ["docker", "compose"]:
                    conf = baseline()
                    conf["services"]["smite-node"]["environment"].update(env_override or {})
                    return json.dumps(conf)
                if cmd[:2] == ["docker", "inspect"]:
                    target = cmd[-1]
                    field = cmd[-2]
                    known = {
                        ("smite-node", "{{.Config.Image}}"): mod.RC1_NODE,
                        ("smite-node", "{{.State.Health.Status}}"): "healthy",
                        ("3xui-01", "{{.Image}}"): mod.SANAEI_IMAGE,
                        ("3xui-01", "{{.State.Status}}"): "running",
                    }
                    value = known[(target,field)]
                    return (inspect_override or {}).get((target,field),value)
                if cmd[0] == "ss":
                    return ss_override if ss_override is not None else "LISTEN 0 4096 127.0.0.1:8888 0.0.0.0:*"
                if cmd[0] == "nginx":
                    return ""
                if cmd[0] == "python3":
                    return (guard_override if guard_override is not None
                            else "XHTTP_REVIEW=PASS ROUTES=1 LEGACY_ROUTE=NO")
                self.fail("Unexpected action " + repr(cmd))
            backed_up = []
            def check_backup(path, digest):
                backed_up.append((path, digest))
            result = mod.audit(read_file=read_file, execute=execute,
                               check_backup=check_backup)
            self.assertEqual(len(backed_up), len(mod.BACKUPS))
            self.assertTrue(all(cmd[0] in ("docker", "ss", "nginx", "python3")
                                for cmd in calls))
            self.assertFalse(any("pull" in cmd or "up" in cmd or "restart" in cmd
                                 or "exec" in cmd for cmd in calls))
            self.assertEqual(result["KH_RC2_UPGRADE_AUTHORIZED"], "NO")
            self.assertEqual(result["LIVE_CHANGES"], "NONE")
            self.assertEqual(result["KH_NODE_IMAGE_DIFF"], "EXACT_ONE_LINE_REVERSIBLE")
            return result
        finally:
            mod.COMPOSE_SHA = original

    def test_current_paused_baseline_passes_without_mutation(self):
        self.simulated_audit()

    def test_unsigned_or_unpaused_auth_holds(self):
        for change in (
            {"SMITE_NODE_PANEL_AUTH_MODE": "signed"},
            {"SMITE_AGENT_AUTH_MODE": "off"},
            {"SMITE_ENGINE_INVENTORY_MODE": "legacy"},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(mod.Hold, "security drift"):
                self.simulated_audit(env_override=change)

    def test_sanaei_image_or_node_health_drift_holds(self):
        for change in (
            {("3xui-01", "{{.Image}}"): "sha256:unknown"},
            {("smite-node", "{{.State.Health.Status}}"): "unhealthy"},
        ):
            with self.subTest(change=change), self.assertRaises(mod.Hold):
                self.simulated_audit(inspect_override=change)

    def test_open_node_port_or_legacy_xhttp_holds(self):
        with self.assertRaisesRegex(mod.Hold, "exclusively loopback"):
            self.simulated_audit(ss_override="LISTEN 0 4096 0.0.0.0:8888 0.0.0.0:*")
        with self.assertRaisesRegex(mod.Hold, "XHTTP guard changed"):
            self.simulated_audit(guard_override="XHTTP_REVIEW=PASS ROUTES=2 LEGACY_ROUTE=YES")


if __name__ == "__main__":
    unittest.main()
