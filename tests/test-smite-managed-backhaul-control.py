#!/usr/bin/env python3
"""Read-only Backhaul operator review plus CI-only transaction admission."""
from __future__ import annotations
import importlib.util
import json
import contextlib
from types import SimpleNamespace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "modules/smite-managed-backhaul-control.py"
MENU = ROOT / "modules/smite-managed-backhaul-menu.sh"

spec = importlib.util.spec_from_file_location("uopti_bh_control_test", FILE)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)

COMPOSE = """services:
  smite-node:
    image: smite-node:stage15-local
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
"""
ENV = """NODE_ROLE=foreign
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
"""


class OperatorControl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="uopti-bh-operator-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.node = self.root / "node"
        self.node.mkdir(mode=0o700)
        (self.node / "config").mkdir(mode=0o700)
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)

    def run_control(self, action: str, *args):
        return subprocess.run(
            [sys.executable, "-B", str(FILE), action, *map(str, args)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )

    def test_no_engine_is_declared_even_when_binaries_are_bundled(self):
        output = self.run_control("status", "--node-dir", self.node)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertIn("ROLE=KH", output.stdout)
        self.assertIn("STATE=NOT_INSTALLED", output.stdout)
        self.assertIn("SIGNED_NODE_STATUS=NOT_QUERIED", output.stdout)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_review_refuses_real_install_and_never_requests_frp_or_ports(self):
        output = self.run_control("review", "--node-dir", self.node)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertIn("INSTALL_ALLOWED=NO", output.stdout)
        self.assertIn("FRP_DEPENDENCY=NONE", output.stdout)
        self.assertIn("PORT_OR_TUNNEL_INPUT=NOT_REQUIRED", output.stdout)
        self.assertIn("HOST_DOCKER_ACTIONS=NONE", output.stdout)
        output = self.run_control("install", "--node-dir", self.node)
        self.assertEqual(output.returncode, 2)
        self.assertIn("activation is NOT enabled", output.stderr)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_partial_install_fails_closed_without_silent_ready(self):
        compose = self.node / "docker-compose.yml"
        compose.write_text(COMPOSE + "      - /opt/u-opti/engines/backhaul/v0.7.2/backhaul:/usr/local/bin/backhaul:ro\n")
        state = control.inspect(self.node)
        self.assertEqual(state["state"], "UNAVAILABLE")
        self.assertEqual(state["reason"], "PARTIAL_INSTALL_OR_DRIFT")

    def test_manifest_without_verified_binary_is_unavailable(self):
        state = self.node / "config/engine-state"
        state.mkdir(mode=0o700)
        manifest = state / "engines.json"
        manifest.write_text(json.dumps({
            "schema": 1,
            "engines": {
                "gost": {"sha256": "c" * 64},
                "backhaul": {"sha256": "a" * 64},
            },
        }))
        manifest.chmod(0o600)
        self.assertEqual(control.inspect(self.node)["state"], "UNAVAILABLE")
        self.assertIn("gost", manifest.read_text())
        manifest.chmod(0o644)
        with self.assertRaises(control.package.Hold):
            control.inspect(self.node)

    def test_duplicate_critical_env_or_unsafe_compose_denied(self):
        (self.node / ".env").write_text(ENV + "SMITE_AGENT_AUTH_MODE=legacy\n")
        with self.assertRaises(control.Hold):
            control.inspect(self.node)
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE + "    ports:\n      - 443:443\n")
        with self.assertRaises(control.Hold):
            control.inspect(self.node)

    def test_bogus_archive_candidate_cannot_be_promoted(self):
        stage = self.root / "stage"
        stage.mkdir(mode=0o700)
        with self.assertRaises(control.Hold):
            control.verified_candidate(stage)
        self.assertEqual(self.run_control("verify-stage", "--stage", stage).returncode, 2)

    def test_install_and_rollback_fail_outside_ci(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false", "RUNNER_TEMP": self.tmp.name}):
            with self.assertRaises(control.transaction.Hold):
                control.exercise(self.root, action="install", stage=self.root / "fake-stage")
            with self.assertRaises(control.transaction.Hold):
                control.exercise(self.root, action="rollback")
        self.assertFalse((self.root / ".backhaul-control.lock").exists())
        self.assertFalse((self.node / "config/engine-state").exists())

    def _rc7_bundle_fake(self, *, role="foreign", inventory=None,
                         binary=None, mounts=None, probe_error=None):
        engines = {name: "not-installed" for name in control.ENGINES}
        engines["frp"] = "ready"
        if inventory is None:
            inventory = {"mode": "managed", "engines": engines}
        if binary is None:
            binary = {"sha256": "a" * 64}
        calls = []
        def node_details():
            calls.append("runtime")
            return {"role": role}
        def inspect(_name):
            calls.append("mounts")
            return {"Mounts": mounts if mounts is not None else [
                {"Destination": "/etc/smite-node", "Type": "bind"},
                {"Destination": "/var/lib/smite-node", "Type": "volume"},
            ]}
        def hmac():
            calls.append("replay")
            if probe_error:
                raise FakeHold(probe_error)
        def run(argv, *, timeout):
            self.assertEqual(argv[:5], ["docker","exec","smite-node","python3","-B"])
            self.assertEqual(timeout, 30)
            if "os.lstat(path)" in argv[-1]:
                calls.append("binary")
                return binary if isinstance(binary,str) else json.dumps(binary)
            self.assertIn("target='/api/agent/engines'",argv[-1])
            calls.append("signed-inventory")
            return inventory if isinstance(inventory,str) else json.dumps(inventory)
        class FakeHold(Exception):
            pass
        rt = SimpleNamespace(
            Hold=FakeHold, locked=lambda:contextlib.nullcontext(),
            inspect_container=inspect, signed_probe=hmac, run=run,
        )
        fake = SimpleNamespace(Hold=FakeHold, rt=rt, node_details=node_details)
        return fake,calls

    def test_rc7_bundled_signed_inventory_no_recreate_and_not_ready_yet(self):
        fake,calls = self._rc7_bundle_fake()
        with patch.object(control.os,"geteuid",return_value=0), \
             patch.object(control,"_load",return_value=fake):
            status=control.verify_rc7_bundled_backhaul("foreign")
        self.assertEqual(calls,["runtime","mounts","replay","binary","signed-inventory"])
        self.assertEqual(status["RC7_BACKHAUL_IMAGE_BINARY"],
                         "OBSERVED_PINNED_IMAGE_NO_MOUNT")
        self.assertEqual(status["RC7_BACKHAUL_ENGINE"],
                         "NOT_INSTALLED_SIGNED_INVENTORY")
        self.assertEqual(status["RC7_FRP_ENGINE"],"READY_SIGNED_INVENTORY")
        self.assertEqual(status["NODE_RECREATED"],"NO")
        self.assertEqual(status["INSTALL_ALLOWED"],"NO")
        self.assertEqual(status["ACTIVATION_GATE"],"HOLD")
        self.assertEqual(status["SIGNED_OWNER_CHILD_CONTINUITY"],"NOT_PROVEN")
        self.assertNotIn("a"*64,str(status))
        self.assertNotIn("Docker",str(status))

    def test_rc7_bundle_unsafe_mount_role_and_root_are_hold_before_probe(self):
        for kwargs,reason in (
            ({"role":"ir"}, "RC7_BUNDLED_RUNTIME_ROLE_MISMATCH"),
            ({"mounts":[{"Destination":"/usr/local/bin/backhaul"}]},
             "RC7_BUNDLED_BACKHAUL_EXTERNAL_MOUNT"),
            ({"mounts":[{"Destination":"/usr/local"}]},
             "RC7_BUNDLED_BACKHAUL_EXTERNAL_MOUNT"),
            ({"mounts":[{"Destination":None}]},
             "RC7_BUNDLED_MOUNT_INVENTORY_UNTRUSTED"),
        ):
            with self.subTest(kwargs=kwargs):
                fake,calls = self._rc7_bundle_fake(**kwargs)
                with patch.object(control.os,"geteuid",return_value=0), \
                     patch.object(control,"_load",return_value=fake):
                    with self.assertRaisesRegex(control.Hold,reason):
                        control.verify_rc7_bundled_backhaul("foreign")
                self.assertNotIn("replay",calls)
                self.assertNotIn("binary",calls)
        fake,calls=self._rc7_bundle_fake()
        with patch.object(control.os,"geteuid",return_value=123), \
             patch.object(control,"_load",return_value=fake):
            with self.assertRaisesRegex(control.Hold,"RC7_BUNDLED_ROOT_REQUIRED"):
                control.verify_rc7_bundled_backhaul("foreign")
        self.assertEqual(calls,[])

    def test_rc7_bundle_wrong_signed_inventory_fails_closed(self):
        ready = {name:"not-installed" for name in control.ENGINES}
        ready["frp"]="ready"
        cases = [
            {"mode":"legacy","engines":ready},
            {"mode":"managed","engines":{**ready,"frp":"unavailable"}},
            {"mode":"managed","engines":{**ready,"backhaul":"ready"}},
            {"mode":"managed","engines":{**ready,"backhaul":"unavailable"}},
            {"mode":"managed","engines":{**ready,"frp":True}},
            {"mode":"managed","engines":{**ready,"frp":"ready","unknown":"ready"}},
            {"mode":"managed","engines":{"backhaul":"not-installed"}},
            {"engines":ready},
            '{"mode":"managed","mode":"managed","engines":{}}',
            '{"mode":"managed","engines":{"backhaul":"not-installed","backhaul":"ready"}}',
            "SECRET_USERNAME_TOKEN_NOT_JSON",
        ]
        for state in cases:
            with self.subTest(state=str(state)[:40]):
                fake,calls = self._rc7_bundle_fake(inventory=state)
                with patch.object(control.os,"geteuid",return_value=0), \
                     patch.object(control,"_load",return_value=fake):
                    with self.assertRaises(control.Hold):
                        control.verify_rc7_bundled_backhaul("foreign")
                self.assertEqual(calls,["runtime","mounts","replay",
                                        "binary","signed-inventory"])
        fake,calls=self._rc7_bundle_fake(probe_error="PRIVATE_SECRET")
        with patch.object(control.os,"geteuid",return_value=0), \
             patch.object(control,"_load",return_value=fake):
            with self.assertRaisesRegex(control.Hold,
                                        "RC7_BUNDLED_RUNTIME_UNVERIFIED") as held:
                control.verify_rc7_bundled_backhaul("foreign")
        self.assertNotIn("PRIVATE_SECRET",str(held.exception))
        self.assertEqual(calls,["runtime","mounts","replay"])

    def test_rc7_bundle_binary_hash_invalid_or_unsafe_payload_refused(self):
        for blob in (
            {}, {"sha256":""}, {"sha256":"G"*64}, {"sha256":1},
            {"sha256":"a"*64, "token":"DONT_LOG_THIS"},
            '{"sha256":"'+("a"*64)+'","sha256":"'+("b"*64)+'"}',
            "{garbled", "",
        ):
            with self.subTest(blob=str(blob)[:30]):
                fake,_=self._rc7_bundle_fake(binary=blob)
                with patch.object(control.os,"geteuid",return_value=0), \
                     patch.object(control,"_load",return_value=fake):
                    with self.assertRaises(control.Hold):
                        control.verify_rc7_bundled_backhaul("foreign")
        self.assertNotIn("DONT_LOG_THIS",str(control._strict_rc7_response.__doc__))

    def test_rc7_preflight_actions_have_fixed_signed_and_no_mutation_contract(self):
        compile(control.RC7_BUNDLED_BACKHAUL_AUDIT,"<image-audit>","exec")
        compile(control.RC7_BUNDLED_SIGNED_INVENTORY,"<signed-agent-get>","exec")
        self.assertIn("nonce=secrets.token_hex(16)",
                      control.RC7_BUNDLED_SIGNED_INVENTORY)
        self.assertIn("ProxyHandler({})",control.RC7_BUNDLED_SIGNED_INVENTORY)
        self.assertIn("NoRedirect",control.RC7_BUNDLED_SIGNED_INVENTORY)
        self.assertIn("os.O_NOFOLLOW",control.RC7_BUNDLED_BACKHAUL_AUDIT)
        self.assertNotIn("docker compose",control.RC7_BUNDLED_BACKHAUL_AUDIT)
        self.assertNotIn("/api/agent/tunnels/apply",
                         control.RC7_BUNDLED_SIGNED_INVENTORY)
        out=self.run_control("verify-rc7-bundle")
        self.assertEqual(out.returncode,2)
        self.assertIn("HOLD: RC7_BUNDLED_ROLE_REQUIRED",out.stderr)
        self.assertFalse((self.node/"config/engine-state").exists())

    def test_menu_is_clear_and_inert(self):
        result = subprocess.run(
            ["bash", str(MENU), "--install"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Host installation disabled", result.stderr)
        result = subprocess.run(
            ["bash", str(MENU), "--status"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "SMITE_NODE_DIR": str(self.node)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOT_INSTALLED", result.stdout)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_menu_full_beginner_walkthrough_is_read_only(self):
        result = subprocess.run(
            ["bash", str(MENU), "--menu"],
            input="1\n2\n3\n0\n", capture_output=True, text=True, timeout=15,
            env={**os.environ, "SMITE_NODE_DIR": str(self.node), "TERM": "dumb"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATE=NOT_INSTALLED", result.stdout)
        self.assertIn("INSTALL_ALLOWED=NO", result.stdout)
        self.assertIn("installation on real IR/KH is disabled", result.stdout)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_concurrent_engine_operations_are_rejected_before_mutation(self):
        # Simulate a trusted runner admission while testing only the lock.
        with patch.object(control.transaction, "admission", return_value=None):
            with control._lab_lock(self.root):
                with self.assertRaisesRegex(control.Hold, "transaction is in progress"):
                    with control._lab_lock(self.root):
                        self.fail("A second concurrent transaction acquired the lock")

    def test_no_network_or_live_service_actions_in_menu_or_controller(self):
        script = MENU.read_text()
        controller = FILE.read_text()
        for text in ("apt-get ", "curl ", "docker compose up", "systemctl ",
                     "iptables ", "ufw ", "ssh ", "nginx -s"):
            self.assertNotIn(text, script)
            self.assertNotIn(text, controller)
        parent = (ROOT / "modules/smite-backhaul-management.sh").read_text()
        self.assertIn('7) Independent Engines (Backhaul review)', parent)
        self.assertIn('smite_managed_bh_menu', parent)
        self.assertIn('2) 443 Gateway (auto-detect Panel / Foreign)', parent)
        self.assertIn('show_smite_gateway_menu', parent)
        self.assertIn('6) docker_smite_advanced_menu', parent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
