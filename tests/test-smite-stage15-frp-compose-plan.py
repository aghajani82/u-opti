#!/usr/bin/env python3
"""Offline negative tests for Stage15 signed FRP Compose-only admission.

No real Docker, network, secrets, host writes, or live FRP activation.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "stage15_frp_signed_compose_plan", HERE / "modules/smite-stage15-frp-compose-plan.py"
)
assert spec and spec.loader
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class Stage15FrpComposePlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.node = Path(self.tmp.name) / "node"
        self.stage = Path(self.tmp.name) / "official-stage"
        self.node.mkdir()
        self.stage.mkdir()
        (self.stage / "compose.override.candidate.yml").write_bytes(plan.STAGED_OVERLAY.encode())
        self.base = {
            "name": "smite-node",
            "services": {
                "smite-node": {
                    "image": "smite-node:stage15-local",
                    "network_mode": "host",
                    "command": ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"],
                    "environment": {
                        "SMITE_NODE_PANEL_AUTH_MODE": "signed",
                        "SMITE_AGENT_AUTH_MODE": "strict",
                        "SMITE_ENGINE_INVENTORY_MODE": "managed",
                        "PANEL_ADDRESS": "02ir.kolbe1.ir:443",
                    },
                    "volumes": [
                        {"type": "bind", "source": "/opt/smite-node/config",
                         "target": "/etc/smite-node", "read_only": False},
                        {"type": "bind", "source": "/etc/u-opti/smite/identities",
                         "target": "/run/smite-node-identity", "read_only": True},
                        {"type": "bind", "source": "/var/lib/u-opti/smite-node-security/replay",
                         "target": "/var/lib/smite-node/auth", "read_only": False},
                    ],
                }
            },
        }
        self.future = copy.deepcopy(self.base)
        for target, source in plan.EXPECTED_MOUNTS.items():
            self.future["services"]["smite-node"]["volumes"].append(
                {"type": "bind", "source": source, "target": target,
                 "read_only": True, "bind": {"create_host_path": False}}
            )
        self.calls = []
        self.readiness = {
            "ROLE": "KH",
            "STAGE15_IMAGE": "PINNED_TEST_ID_MATCH",
            "SIGNED_NODE": "HEALTHY_LOCAL_RUNTIME_ONLY",
            "FRP_0_71_MANAGED_MATCH": "NO",
            "HOST_FRP_INSTALL": "HOLD_VERSION_AND_SIGNED_WSS_ADMISSION",
        }

    def runner(self, args, *, stdin=None):
        self.calls.append((args, stdin))
        self.assertEqual(args[:2], ["docker", "compose"])
        self.assertIn("config", args)
        self.assertNotIn("up", args)
        self.assertNotIn("restart", args)
        self.assertNotIn("pull", args)
        if stdin is None:
            self.assertNotIn("-", args)
            return json.dumps(self.base)
        self.assertEqual(stdin, plan.OVERLAY)
        self.assertEqual(args[-5:], ["-f", "-", "config", "--format", "json"])
        return json.dumps(self.future)

    def check(self):
        return plan.review(
            self.node, self.stage, official_verify=lambda _: True,
            signed_readiness=lambda _: self.readiness, run=self.runner,
        )

    def test_accepts_only_verified_dual_readonly_bind_overlay(self):
        result = self.check()
        self.assertEqual(result["STAGE15_FRP_COMPOSE_PLAN"], "PASS_READ_ONLY")
        self.assertEqual(result["LEGACY_IMAGE_FRP"], "v0.65.0_NOT_SELECTED")
        self.assertEqual(result["OFFICIAL_FRP_VERSION"], "v0.71.0")
        self.assertEqual(result["FRP_MOUNTS"], "TWO_READ_ONLY_BINDS_ONLY")
        self.assertEqual(result["SIGNED_COMPOSE"], "UNCHANGED_EXCEPT_FRP_BINARIES")
        self.assertEqual(result["APPLY_ALLOWED"], "NO")
        self.assertEqual(result["FRP_HOST_TRANSACTION"], "NOT_IMPLEMENTED")
        self.assertEqual(result["LIVE_CHANGES"], "NONE")
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("7000", json.dumps(result))

    def test_unverified_official_archive_blocks_before_any_docker(self):
        with self.assertRaisesRegex(plan.Hold, "OFFICIAL_FRP_071_PAIR_NOT_VERIFIED"):
            plan.review(self.node, self.stage, official_verify=lambda _: False,
                        signed_readiness=lambda _: self.readiness, run=self.runner)
        self.assertEqual(self.calls, [])

    def test_bad_runtime_admission_blocks(self):
        for key, value in [
            ("SIGNED_NODE", "UNKNOWN"), ("STAGE15_IMAGE", "UNVERIFIED"),
            ("FRP_0_71_MANAGED_MATCH", "YES"),
            ("HOST_FRP_INSTALL", "READY"),
        ]:
            original = self.readiness[key]
            self.readiness[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(
                plan.Hold, "STAGE15_SIGNED_RUNTIME_NOT_ADMITTED"
            ):
                self.check()
            self.readiness[key] = original
        self.assertEqual(self.calls, [])

    def test_forged_official_compose_override_rejected(self):
        (self.stage / "compose.override.candidate.yml").write_text(
            plan.STAGED_OVERLAY.replace("read_only: true", "read_only: false", 1)
        )
        with self.assertRaisesRegex(plan.Hold, "OFFICIAL_FRP_COMPOSE_CANDIDATE_DRIFT"):
            self.check()
        self.assertEqual(self.calls, [])

    def test_unsafe_overlay_and_base_changes_hold(self):
        service = self.future["services"]["smite-node"]
        for name, mutate in [
            ("writable_frpc", lambda: service["volumes"][-2].update(read_only=False)),
            ("wrong_frps_src", lambda: service["volumes"][-1].update(source="/tmp/frps")),
            ("extra_port", lambda: service.update(ports=[{"published": 8888}])),
            ("legacy_auth", lambda: service["environment"].update(SMITE_AGENT_AUTH_MODE="legacy")),
            ("missing_frpc", lambda: service["volumes"].pop(-2)),
            ("missing_frps", lambda: service["volumes"].pop()),
            ("new_container", lambda: self.future["services"].update({"unsafe": {"image": "example"}})),
            ("identity_mount_drift", lambda: service["volumes"][1].update(read_only=False)),
        ]:
            saved = copy.deepcopy(self.future)
            mutate()
            with self.subTest(name=name), self.assertRaises(plan.Hold):
                self.check()
            self.future = saved
            service = self.future["services"]["smite-node"]

    def test_existing_frp_mount_or_unsigned_base_rejected(self):
        self.base["services"]["smite-node"]["volumes"].append({
            "type": "bind", "source": "/some/frp", "target": "/usr/local/bin/frpc",
            "read_only": False,
        })
        with self.assertRaisesRegex(plan.Hold, "FRP_BINARY_MOUNT_ALREADY_PRESENT"):
            self.check()
        self.base["services"]["smite-node"]["volumes"].pop()
        self.base["services"]["smite-node"]["environment"]["SMITE_NODE_PANEL_AUTH_MODE"] = "paused"
        with self.assertRaisesRegex(plan.Hold, "STAGE15_SIGNED_BASE_COMPOSE_DRIFT"):
            self.check()

    def test_cli_does_not_have_apply_or_install_action(self):
        result = subprocess.run(
            ["python3", "-B", str(HERE / "modules/smite-stage15-frp-compose-plan.py"),
             "apply", "--stage", str(self.stage)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)
        self.assertEqual(list(self.node.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
