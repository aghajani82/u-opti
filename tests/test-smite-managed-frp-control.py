#!/usr/bin/env python3
"""Managed FRP operator status / menu, no actual Docker operations."""
from __future__ import annotations
import hashlib
import types
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-managed-frp-control.py"
MENU = ROOT / "modules/smite-managed-frp-menu.sh"
BH_MENU = ROOT / "modules/smite-managed-backhaul-menu.sh"
spec = importlib.util.spec_from_file_location("managed_frp_operator_tests", SOURCE)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
COMPOSE = (
    "services:\n  smite-node:\n    image: smite-node:reviewed\n"
    "    network_mode: host\n    volumes:\n"
    "      - ./config:/etc/smite-node\n"
)
ENV = (
    "NODE_ROLE=foreign\nSMITE_AGENT_AUTH_MODE=strict\n"
    "SMITE_NODE_PANEL_AUTH_MODE=paused\nSMITE_ENGINE_INVENTORY_MODE=managed\n"
)


class FrpOperator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="frp-review-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.node = self.root / "node"
        self.node.mkdir()
        (self.node / "config").mkdir()
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)

    def cli(self, action):
        return subprocess.run(
            [sys.executable, "-B", str(SOURCE), action, "--node-dir", str(self.node)],
            capture_output=True, text=True, timeout=15,
        )

    def test_clean_managed_frp_status_and_review(self):
        out = self.cli("status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("STATE=NOT_INSTALLED", out.stdout)
        self.assertIn("ROLE=KH", out.stdout)
        self.assertIn("SIGNED_NODE_STATUS=NOT_QUERIED", out.stdout)
        out = self.cli("review")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("BACKHAUL_DEPENDENCY=NONE", out.stdout)
        self.assertIn("PORT_OR_TUNNEL_INPUT=NOT_REQUIRED", out.stdout)
        self.assertIn("INSTALL_ALLOWED=NO", out.stdout)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_host_install_and_rollback_always_denied(self):
        for action in ("install", "rollback"):
            with self.subTest(action=action):
                out = self.cli(action)
                self.assertEqual(out.returncode, 2)
                self.assertIn("NOT enabled", out.stderr)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_frp_status_preserves_preexisting_backhaul(self):
        directory = self.node / "config/engine-state"
        directory.mkdir(mode=0o700)
        manifest = directory / "engines.json"
        original = {"schema": 1, "engines": {"backhaul": {"sha256": "b" * 64}}}
        manifest.write_text(json.dumps(original))
        manifest.chmod(0o600)
        status = self.cli("review")
        self.assertEqual(status.returncode, 0)
        self.assertIn("STATE=NOT_INSTALLED", status.stdout)
        self.assertIn("BACKHAUL_DEPENDENCY=NONE", status.stdout)
        self.assertEqual(json.loads(manifest.read_text()), original)

    def test_partial_frp_mount_and_missing_server_denied(self):
        manifest_dir = self.node / "config/engine-state"
        manifest_dir.mkdir(mode=0o700)
        manifest = manifest_dir / "engines.json"
        manifest.write_text(json.dumps({"schema": 1, "engines": {
            "frp": {"sha256": "a" * 64, "server_sha256": "b" * 64}
        }}))
        manifest.chmod(0o600)
        status = self.cli("status")
        self.assertEqual(status.returncode, 0)
        self.assertIn("STATE=UNAVAILABLE", status.stdout)
        self.assertIn("MISSING_READONLY_MOUNT", status.stdout)
        manifest.write_text(json.dumps({"schema": 1, "engines": {
            "frp": {"sha256": "a" * 64}
        }}))
        self.assertIn("DUAL_FRP_DIGEST_REQUIRED", self.cli("status").stdout)

    def rc7_bundled_fixture(self, *, state="COMMITTED", journal_role="foreign",
                             altered_manifest=False, altered_binary=False):
        directory = self.node / "config" / "engine-state"
        directory.mkdir(mode=0o700, exist_ok=True)
        content = json.dumps({"schema": 1, "engines": {
            "frp": {"sha256": "a" * 64, "server_sha256": "b" * 64}
        }}, sort_keys=True).encode()
        (directory / "engines.json").write_bytes(content)
        (directory / "engines.json").chmod(0o600)
        raw = b"untrusted-inventory" if altered_manifest else content
        digest = hashlib.sha256(raw).hexdigest()
        binaries = {"frpc": "a" * 64, "frps": "c" * 64 if altered_binary else "b" * 64}
        journal_doc = {
            "schema": 1, "role": journal_role, "state": state,
            "new": digest, "old": None, "binaries": binaries,
        }
        journal_dir = self.root / "rc7-enrollment"
        journal_dir.mkdir(mode=0o700, exist_ok=True)
        (journal_dir / "record.json").write_text(json.dumps(journal_doc))
        return content, journal_doc, journal_dir

    def inspect_with_rc7_fixture(self, content, journal_doc, journal_dir):
        class FakeLoader:
            def exec_module(self, module):
                return None

        fake = types.SimpleNamespace(
            state=lambda: journal_doc,
            read_private=lambda path: content,
            sha=lambda raw: hashlib.sha256(raw).hexdigest(),
        )
        with patch.object(control, "RC7_ENROLLMENT_RECORD",
                          journal_dir / "record.json"), \
             patch.object(control.importlib.util, "spec_from_file_location",
                          return_value=types.SimpleNamespace(loader=FakeLoader())), \
             patch.object(control.importlib.util, "module_from_spec",
                          return_value=fake):
            return control.inspect(self.node)

    def test_rc7_image_bundled_frp_enrollment_is_local_only_not_unavailable(self):
        content, journal, journal_dir = self.rc7_bundled_fixture()
        r = self.inspect_with_rc7_fixture(content, journal, journal_dir)
        self.assertEqual(r["role"], "KH")
        self.assertEqual(r["state"], "ENROLLED_UNVERIFIED")
        self.assertEqual(r["reason"], "RC7_BUNDLED_FRP_SIGNED_STATUS_REQUIRED")
        self.assertFalse("SIGNED_NODE_VERIFIED" in str(r))
        self.assertEqual(self.cli("install").returncode, 2)
        self.assertEqual(self.cli("rollback").returncode, 2)

    def test_rc7_bundled_journal_rejects_incomplete_drift_and_wrong_role(self):
        for variation in ("PREPARED", "HOLD", "ROLLED_BACK",
                          "wrong-role", "manifest-drift", "binary-drift"):
            with self.subTest(variation=variation):
                if variation in ("PREPARED", "HOLD", "ROLLED_BACK"):
                    values = dict(state=variation)
                    expected = "RC7_ENROLLMENT_NOT_COMMITTED"
                elif variation == "wrong-role":
                    values = dict(journal_role="ir")
                    expected = "RC7_ENROLLMENT_ROLE_MISMATCH"
                elif variation == "manifest-drift":
                    values = dict(altered_manifest=True)
                    expected = "RC7_ENROLLMENT_MANIFEST_DRIFT"
                else:
                    values = dict(altered_binary=True)
                    expected = "RC7_ENROLLMENT_MANIFEST_DRIFT"
                content, journal, journal_dir = self.rc7_bundled_fixture(**values)
                actual = self.inspect_with_rc7_fixture(content, journal, journal_dir)
                self.assertEqual(actual["state"], "UNAVAILABLE")
                self.assertEqual(actual["reason"], expected)
                self.assertNotIn("READY", str(actual))

    def test_rc7_invalid_private_journal_fails_closed_without_other_engine_actions(self):
        content, journal, journal_dir = self.rc7_bundled_fixture()
        class FakeLoader:
            def exec_module(self, module):
                return None
        fake = types.SimpleNamespace(
            state=lambda: (_ for _ in ()).throw(ValueError("SECRET_DATA")),
            read_private=lambda path: content,
            sha=lambda raw: hashlib.sha256(raw).hexdigest(),
        )
        with patch.object(control, "RC7_ENROLLMENT_RECORD",
                          journal_dir / "record.json"), \
             patch.object(control.importlib.util, "spec_from_file_location",
                          return_value=types.SimpleNamespace(loader=FakeLoader())), \
             patch.object(control.importlib.util, "module_from_spec",
                          return_value=fake):
            result = control.inspect(self.node)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(result["reason"], "RC7_ENROLLMENT_LOCAL_PROOF_INVALID")
        self.assertNotIn("SECRET_DATA", str(result))

    def test_partial_external_frp_mount_never_uses_rc7_bundled_fallback(self):
        content, journal, journal_dir = self.rc7_bundled_fixture()
        compose = (self.node / "docker-compose.yml").read_text()
        compose += "      - /any/path:/usr/local/bin/frpc:ro\n"
        (self.node / "docker-compose.yml").write_text(compose)
        result = self.inspect_with_rc7_fixture(content, journal, journal_dir)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual(result["reason"], "MISSING_READONLY_MOUNT")

    def test_duplicate_env_and_untrusted_ports_rejected(self):
        (self.node / ".env").write_text(ENV + "SMITE_AGENT_AUTH_MODE=legacy\n")
        self.assertEqual(self.cli("status").returncode, 2)
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE + "    ports:\n      - 8888:8888\n")
        self.assertEqual(self.cli("status").returncode, 2)

    def test_frp_menu_beginner_walkthrough_and_host_install_hold(self):
        env = {**os.environ, "SMITE_NODE_DIR": str(self.node), "TERM": "dumb"}
        process = subprocess.run(["bash", str(MENU), "--menu"], input="1\n2\n3\n4\n0\n",
                                 capture_output=True, text=True, timeout=15, env=env)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("STATE=NOT_INSTALLED", process.stdout)
        self.assertIn("BACKHAUL_DEPENDENCY=NONE", process.stdout)
        self.assertIn("HOLD: Disposable IR/KH root only", process.stdout)
        install = subprocess.run(["bash", str(MENU), "--install"], capture_output=True,
                                 text=True, timeout=15, env=env)
        self.assertEqual(install.returncode, 2)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_rc9_signed_bundled_frp_review_is_read_only_and_never_installs(self):
        # Exact live RC9 release reference + image, but no signature/replay
        # assertion or permission to call an RC7/Stage15 mutating installer.
        state = self.root / "state.env"
        state.write_text(
            "SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.9\n"
            "SMITE_UPSTREAM_REF=" + control.RC9_UPSTREAM + "\n"
            "SMITE_CONNECTION_MODE=standard\n")
        state.chmod(0o600)
        # The original RC9 installer keeps .env paused+strict; the signed
        # Compose security candidate promotes only the effective runtime.
        (self.node / ".env").write_text(
            ENV + "PANEL_ADDRESS=04.grandoptical.ir:443\n")
        signed = self.node / "docker-compose.security-candidate.yml"
        signed.write_text("services:\n  smite-node:\n    environment: {}\n")
        signed.chmod(0o600)
        node_env = {
            "SMITE_NODE_PANEL_AUTH_MODE": "signed",
            "SMITE_AGENT_AUTH_MODE": "strict",
            "SMITE_ENGINE_INVENTORY_MODE": "managed",
            "NODE_ROLE": "foreign",
            "PANEL_ADDRESS": "04.grandoptical.ir:443",
        }
        runtime = {
            "Config": {
                "Image": control.RC9_NODE_IMAGE,
                "Env": [f"{k}={v}" for k, v in node_env.items()],
                "Cmd": list(control.SAFE_NODE_COMMANDS[0]),
                "Labels": {
                    "com.docker.compose.project": "uopti_rc6_" + "a"*32,
                    "com.docker.compose.service": "smite-node",
                    "com.docker.compose.project.config_files":
                        str(self.node / "docker-compose.yml") + "," + str(signed),
                },
            },
            "Image": "sha256:" + "a"*64,
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "HostConfig": {"NetworkMode": "host", "PortBindings": None,
                           "Privileged": False},
            "Mounts": [
                {"Destination": "/etc/smite-node", "Type": "bind",
                 "Source": str(self.node / "config"), "RW": True},
                {"Destination": "/run/smite-node-identity", "Type": "bind",
                 "RW": False},
                {"Destination": "/var/lib/smite-node/auth", "Type": "bind",
                 "RW": True},
                {"Destination": "/run/smite-sanaei-ro", "Type": "bind",
                 "Source": "/opt/3x-ui/instances/01/db", "RW": False},
            ],
        }
        calls = []
        def fake_read(argv):
            calls.append(list(argv))
            if argv == ["docker", "inspect", "smite-node"]:
                return json.dumps([runtime])
            if argv[:3] == ["docker", "image", "inspect"]:
                self.assertEqual(argv[-1], control.RC9_NODE_IMAGE)
                return "sha256:" + "a"*64
            if argv[:3] == ["docker", "exec", "smite-node"]:
                return "0.71.0"
            raise AssertionError(argv)

        result = control.rc9_readiness(
            self.node, state_path=state, run=fake_read)
        self.assertEqual(result["FRP_BINARIES"], "BUNDLED_0_71_0")
        self.assertEqual(result["RC9_SIGNED_SOURCE"], "EXACT_LOCAL_STATE")
        self.assertEqual(result["HOST_FRP_INSTALL"],
                         "HOLD_PENDING_RC9_SIGNED_WSS_AND_ROLLBACK_REVIEW")
        self.assertEqual(result["SIGNED_HMAC_REPLAY"], "NOT_QUERIED")
        self.assertFalse(any("compose" in cmd or "--force-recreate" in cmd
                             or "restart" in cmd for cmd in calls))
        self.assertFalse((self.node / "config/engine-state").exists())

        # A base that is already signed is not the reviewed installer owner.
        baseline_env = (self.node / ".env").read_text()
        (self.node / ".env").write_text(
            baseline_env.replace("SMITE_NODE_PANEL_AUTH_MODE=paused",
                                 "SMITE_NODE_PANEL_AUTH_MODE=signed"))
        calls.clear()
        with self.assertRaisesRegex(
                control.Hold, "RC9_NODE_SIGNED_POLICY_MISMATCH"):
            control.rc9_readiness(
                self.node, state_path=state, run=fake_read)
        self.assertEqual(calls, [])
        (self.node / ".env").write_text(baseline_env)

        # A correctly paused base with paused/missing runtime must be denied.
        original_runtime_env = list(runtime["Config"]["Env"])
        runtime["Config"]["Env"] = [
            x.replace("SMITE_NODE_PANEL_AUTH_MODE=signed",
                      "SMITE_NODE_PANEL_AUTH_MODE=paused")
            for x in original_runtime_env]
        with self.assertRaisesRegex(
                control.Hold, "RC9_EFFECTIVE_SIGNED_POLICY_DRIFT"):
            control.rc9_readiness(
                self.node, state_path=state, run=fake_read)
        runtime["Config"]["Env"] = [
            x for x in original_runtime_env
            if not x.startswith("SMITE_NODE_PANEL_AUTH_MODE=")]
        with self.assertRaisesRegex(
                control.Hold, "RC9_EFFECTIVE_SIGNED_POLICY_DRIFT"):
            control.rc9_readiness(
                self.node, state_path=state, run=fake_read)
        runtime["Config"]["Env"] = original_runtime_env

        # Fail-closed: version/source mismatch is rejected BEFORE Docker.
        original = state.read_text()
        for bad in ("SMITE_MANAGED_VERSION=2.0.0-rc.7",
                    "SMITE_UPSTREAM_REF=" + "0"*40,
                    "SMITE_ROLE=panel-iran"):
            with self.subTest(bad=bad):
                state.write_text(original.replace(
                    bad.split("=")[0]+"="+(
                        "2.0.0-rc.9" if bad.startswith("SMITE_MANAGED")
                        else control.RC9_UPSTREAM if bad.startswith("SMITE_UPSTREAM")
                        else "foreign"), bad))
                calls.clear()
                with self.assertRaisesRegex(
                        control.Hold, "RC9_SIGNED_SOURCE_OR_ROLE_MISMATCH"):
                    control.rc9_readiness(
                        self.node, state_path=state, run=fake_read)
                self.assertEqual(calls, [])
        state.write_text(original)
        for key, value, expected in (
            ("Image", "ghcr.io/aghajani82/smite-node@sha256:"+"b"*64,
             "RC9_NODE_IMAGE_ID_MISMATCH"),
            ("Image", control.RC9_NODE_IMAGE, None)):
            runtime["Config"][key] = value
            if expected:
                with self.assertRaisesRegex(control.Hold, expected):
                    control.rc9_readiness(
                        self.node, state_path=state, run=fake_read)
        runtime["Config"]["Image"] = control.RC9_NODE_IMAGE
        runtime["Config"]["Cmd"] = [
            "uvicorn","main:app","--host","0.0.0.0","--port","8888"]
        with self.assertRaisesRegex(
                control.Hold, "RC9_NODE_NETWORK_OR_LOOPBACK_DRIFT"):
            control.rc9_readiness(self.node, state_path=state, run=fake_read)
        runtime["Config"]["Cmd"] = list(control.SAFE_NODE_COMMANDS[0])
        runtime["Config"]["Env"].append("SMITE_FRP_STANDARD_WSS=1")
        with self.assertRaisesRegex(control.Hold,
                                    "RC9_WSS_ALREADY_CONFIGURED"):
            control.rc9_readiness(self.node, state_path=state, run=fake_read)
        runtime["Config"]["Env"].pop()
        runtime["Mounts"][-1]["RW"] = True
        with self.assertRaisesRegex(control.Hold,
                                    "RC9_SANAEI_READONLY_MOUNT_DRIFT"):
            control.rc9_readiness(self.node, state_path=state, run=fake_read)
        runtime["Mounts"][-1]["RW"] = False
        runtime["Config"]["Labels"][
            "com.docker.compose.project.config_files"] = str(
                self.node / "docker-compose.yml")
        with self.assertRaisesRegex(control.Hold,
                                    "RC9_NODE_COMPOSE_OWNER_DRIFT"):
            control.rc9_readiness(self.node, state_path=state, run=fake_read)
        # A bad runtime preflight cannot mutate installed FRP state.
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_rc9_readiness_stays_opt_in_review_only(self):
        source = SOURCE.read_text()
        self.assertIn('"--rc9-baseline"', source)
        self.assertIn(
            '(args.rc9_baseline or args.rc9_wss_plan) and args.action != "review"',
            source)
        self.assertIn('print("INSTALL_ALLOWED=NO")', source)
        self.assertIn('rc9_readiness(', source)
        self.assertIn('smite-rc7-frp-enrollment.py', (
            ROOT / "modules/smite-managed-backhaul-control.py").read_text())
        self.assertIn('if args.action in ("install", "rollback"):', source)
        for blocked in ("docker compose up", "docker restart",
                        "systemctl start", "nginx -s", "iptables "):
            self.assertNotIn(blocked, source)

    def test_rc9_wss_candidate_reuses_original_single_key_diff_without_host_change(self):
        state = self.root / "state.env"
        state.write_text(
            "SMITE_ROLE=foreign\nSMITE_MANAGED_VERSION=2.0.0-rc.9\n"
            "SMITE_UPSTREAM_REF=" + control.RC9_UPSTREAM + "\n"
            "SMITE_CONNECTION_MODE=standard\n"
            "SMITE_PANEL_DOMAIN=04.grandoptical.ir\n")
        state.chmod(0o600)
        (self.node / ".env").write_text(
            ENV + "PANEL_ADDRESS=04.grandoptical.ir:443\n")
        signed = self.node / "docker-compose.security-candidate.yml"
        signed.write_text(
            "services:\n  smite-node:\n    environment:\n"
            "      - SMITE_NODE_PANEL_AUTH_MODE=signed\n")
        signed.chmod(0o600)
        expected_image = control.RC9_NODE_IMAGE
        labels = {
            "com.docker.compose.project": "uopti_rc6_" + "a"*32,
            "com.docker.compose.service": "smite-node",
            "com.docker.compose.project.config_files":
                str(self.node / "docker-compose.yml") + "," + str(signed),
        }
        runtime = {
            "Config": {"Labels": labels, "Image": expected_image},
            "State": {"Running": True, "Health": {"Status": "healthy"}},
        }
        original = {
            "name": "reviewed-compose",
            "services": {"smite-node": {
                "environment": {
                    "SMITE_AGENT_AUTH_MODE": "strict",
                    "SMITE_NODE_PANEL_AUTH_MODE": "signed"
                },
                "image": expected_image,
                "network_mode": "host",
            }},
        }
        seen = []
        tamper = {}
        def fake_run(argv, *, input=None):
            seen.append((tuple(argv), input))
            if argv == ["docker", "inspect", "smite-node"]:
                return json.dumps([runtime])
            if argv[-4:] == ["-", "config", "--format", "json"]:
                self.assertIn("SMITE_FRP_STANDARD_WSS: \"1\"", input)
                result = json.loads(json.dumps(original))
                result["services"]["smite-node"]["environment"][
                    "SMITE_FRP_STANDARD_WSS"] = "1"
                if tamper.get("extra"):
                    result["services"]["smite-node"]["network_mode"] = "bridge"
                return json.dumps(result)
            if argv[-3:] == ["config", "--format", "json"]:
                return json.dumps(original)
            raise AssertionError(argv)
        result = control._rc9_wss_compose_plan(
            self.node, "KH", state_path=state, run=fake_run)
        self.assertEqual(result["RC9_WSS_COMPOSE_CANDIDATE"],
                         "EXACT_ONE_ENV_ONLY")
        self.assertEqual(result["RC9_WSS_RUNTIME_APPLY"],
                         "HOLD_RECREATE_AND_ROLLBACK_NOT_APPROVED")
        self.assertFalse(any("up" in cmd or "restart" in cmd
                             for cmd, _ in seen))
        self.assertFalse((self.node / "config/engine-state").exists())
        self.assertEqual(sum(arg is not None for _, arg in seen), 1)
        tamper["extra"] = True
        with self.assertRaisesRegex(
                control.Hold, "EFFECTIVE_COMPOSE_DRIFT"):
            control._rc9_wss_compose_plan(
                self.node, "KH", state_path=state, run=fake_run)
        tamper.clear()
        labels["com.docker.compose.project.config_files"] = str(
            self.node / "docker-compose.yml")
        with self.assertRaisesRegex(
                control.Hold, "RC9_WSS_COMPOSE_RUNTIME_DRIFT"):
            control._rc9_wss_compose_plan(
                self.node, "KH", state_path=state, run=fake_run)
        labels["com.docker.compose.project.config_files"] = (
            str(self.node / "docker-compose.yml") + "," + str(signed))
        state.write_text(state.read_text().replace(
            "04.grandoptical.ir", "wrong.grandoptical.ir"))
        with self.assertRaisesRegex(
                control.Hold, "RC9_WSS_PANEL_SCOPE_MISMATCH"):
            control._rc9_wss_compose_plan(
                self.node, "KH", state_path=state, run=fake_run)

    def test_rc9_wss_plan_requires_review_and_never_enables_host_install(self):
        self.assertIn('args.rc9_baseline or args.rc9_wss_plan',
                      SOURCE.read_text())
        self.assertIn('if args.action in ("install", "rollback"):',
                      SOURCE.read_text())
        self.assertIn('HOLD_RECREATE_AND_ROLLBACK_NOT_APPROVED',
                      SOURCE.read_text())
        for action in ("install", "rollback"):
            with self.subTest(action=action):
                p = subprocess.run(
                    [sys.executable, "-B", str(SOURCE), action,
                     "--rc9-wss-plan", "--node-dir", str(self.node)],
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(p.returncode, 2)
                self.assertIn("NOT enabled", p.stderr)

    def test_stage15_readiness_is_read_only_and_never_authorizes_install(self):
        signed = self.node / "docker-compose.security-candidate.yml"
        signed.write_text("services:\\n  smite-node:\\n    environment:\\n")
        signed.chmod(0o600)
        values = {
            "SMITE_NODE_PANEL_AUTH_MODE": "signed",
            "SMITE_AGENT_AUTH_MODE": "strict",
            "SMITE_ENGINE_INVENTORY_MODE": "managed",
            "PANEL_ADDRESS": "02ir.kolbe1.ir:443",
        }
        runtime = {
            "Config": {
                "Image": "smite-node:stage15-local",
                "Env": [f"{k}={v}" for k, v in values.items()],
                "Cmd": ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"],
                "Labels": {
                    "com.docker.compose.project.config_files":
                        str(self.node / "docker-compose.yml") + "," + str(signed),
                },
            },
            "Image": control.STAGE15_NODE_ID,
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "HostConfig": {"NetworkMode": "host", "PortBindings": None, "Privileged": False},
            "Mounts": [
                {"Destination": "/etc/smite-node", "RW": True},
                {"Destination": "/run/smite-node-identity", "RW": False},
                {"Destination": "/var/lib/smite-node/auth", "RW": True},
            ],
        }
        calls = []
        def fake_run(argv):
            calls.append(argv)
            if argv[:3] == ["docker", "inspect", "smite-node"]:
                return json.dumps([runtime])
            if argv[:3] == ["docker", "image", "inspect"]:
                return control.STAGE15_NODE_ID
            if argv[:3] == ["docker", "exec", "smite-node"]:
                return "0.65.0"
            raise AssertionError(argv)

        result = control.stage15_readiness(self.node, run=fake_run)
        self.assertEqual(result["STAGE15_IMAGE"], "PINNED_TEST_ID_MATCH")
        self.assertEqual(result["HOST_FRP_INSTALL"], "HOLD_VERSION_AND_SIGNED_WSS_ADMISSION")
        self.assertEqual(result["FRP_BINARIES"], "STAGE15_BUNDLED_0_65_0")
        self.assertEqual(result["FRP_0_71_MANAGED_MATCH"], "NO")
        self.assertEqual(result["BUNDLED_FRP_PROVENANCE"], "NOT_ATTESTED")
        self.assertEqual(result["LIVE_CHANGES"], "NONE")
        self.assertEqual(result["FRP_ENGINE_ENROLLED"], "NO")
        self.assertFalse(any("restart" in argv or "up" in argv for argv in calls))

        # The current Standard installer uses the reviewed 9-token command.
        runtime["Image"] = control.STAGE15_FRP071_NODE_ID
        runtime["Config"]["Cmd"] = list(control.SAFE_NODE_COMMANDS[1])
        def new_image_run(argv):
            result = fake_run(argv)
            if argv[:3] == ["docker", "image", "inspect"]:
                return control.STAGE15_FRP071_NODE_ID
            if argv[:3] == ["docker", "exec", "smite-node"]:
                return "0.71.0"
            return result
        modern = control.stage15_readiness(self.node, run=new_image_run)
        self.assertEqual(modern["FRP_BINARIES"], "STAGE15_BUNDLED_0_71_0")
        for invalid in (
            list(control.SAFE_NODE_COMMANDS[1]) + ["--proxy-headers"],
            ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8888"],
            ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8899",
             "--log-level", "info", "--access-log"],
        ):
            runtime["Config"]["Cmd"] = invalid
            with self.assertRaisesRegex(control.Hold, "STAGE15_NODE_LOOPBACK_DRIFT"):
                control.stage15_readiness(self.node, run=new_image_run)
        runtime["Config"]["Cmd"] = list(control.SAFE_NODE_COMMANDS[0])
        runtime["Image"] = control.STAGE15_NODE_ID

        original = runtime["Image"]
        runtime["Image"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(control.Hold, "STAGE15_IMAGE_ID_MISMATCH"):
            control.stage15_readiness(self.node, run=fake_run)
        runtime["Image"] = original

        runtime["Config"]["Env"].append("SMITE_FRP_STANDARD_WSS=1")
        with self.assertRaisesRegex(control.Hold, "STAGE15_WSS_FLAG_UNREVIEWED"):
            control.stage15_readiness(self.node, run=fake_run)
        runtime["Config"]["Env"].pop()

        runtime["HostConfig"]["PortBindings"] = {"8888/tcp": [{"HostPort": "8888"}]}
        with self.assertRaisesRegex(control.Hold, "STAGE15_NODE_NETWORK_DRIFT"):
            control.stage15_readiness(self.node, run=fake_run)
        runtime["HostConfig"]["PortBindings"] = None

        runtime["Config"]["Labels"]["com.docker.compose.project.config_files"] = str(self.node / "docker-compose.yml")
        with self.assertRaisesRegex(control.Hold, "STAGE15_SIGNED_COMPOSE_NOT_ACTIVE"):
            control.stage15_readiness(self.node, run=fake_run)

    def test_stage15_readiness_rejects_incomplete_unsigned_core(self):
        (self.node / ".env").write_text(ENV.replace(
            "SMITE_AGENT_AUTH_MODE=strict",
            "SMITE_AGENT_AUTH_MODE=legacy"))
        calls = []
        def run(argv):
            calls.append(argv)
            raise AssertionError("Docker should not be queried for invalid Core")
        with self.assertRaisesRegex(control.Hold, "MANAGED_STRICT_CORE_REQUIRED"):
            control.stage15_readiness(self.node, run=run)
        self.assertEqual(calls, [])

    def test_parent_has_separate_frp_and_existing_backhaul(self):
        source = BH_MENU.read_text()
        self.assertIn('5) FRP — Independent install/review', source)
        self.assertIn('smite_managed_frp_menu', source)
        self.assertIn('smite_managed_bh_menu', source)
        # Existing option 3 is now a scoped IR-only metadata canary;
        # the independent FRP menu is unchanged and foreign writes remain
        # explicitly forbidden by the production executor.
        self.assertIn(
            '3) Backhaul retained install / rollback (IR / Foreign, no Node recreate)',
            source)
        self.assertIn('smite_managed_bh_ir_retained_canary', source)
        self.assertIn('--confirm-role INSTALL-RETAINED-BACKHAUL-IR', source)
        self.assertIn('--confirm-role ROLLBACK-RETAINED-BACKHAUL-IR', source)
        self.assertIn('INSTALL-RETAINED-BACKHAUL-FOREIGN', source)
        self.assertIn('ROLLBACK-RETAINED-BACKHAUL-FOREIGN', source)
        self.assertIn('SNAPSHOT-RESTORE-AND-CONSOLE-VERIFIED', source)
        for body in (SOURCE.read_text(), MENU.read_text()):
            for forbidden in ("docker compose up", "docker restart", "systemctl start",
                              "iptables ", "ufw ", "nginx -s", "ssh ", "curl "):
                self.assertNotIn(forbidden, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
