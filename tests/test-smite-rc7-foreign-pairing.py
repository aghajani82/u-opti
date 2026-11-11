#!/usr/bin/env python3
"""RC7 Foreign signed-pairing admission, no live hosts or credentials."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("smite_pairing", ROOT / "modules/smite-node-pairing.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
PROJECT = "uopti_rc6_" + "a" * 32


class ForeignRC7Tests(unittest.TestCase):
    def test_publisher_signed_digest_pins(self):
        self.assertEqual(p._FOREIGN_PANEL_IMAGE_RC7,
            "ghcr.io/aghajani82/smite-panel@sha256:180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8")
        self.assertEqual(p._FOREIGN_NODE_IMAGE_RC7,
            "ghcr.io/aghajani82/smite-node@sha256:03ae4ca0f6d516374671fad4e32d44c13fbb46d0e4309bccb0265230d6fc4263")

    def test_rc7_compose_preserves_owner_before_recreate_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "docker-compose.yml"
            candidate = Path(tmp) / "docker-compose.security-candidate.yml"
            base.write_text("services:\n  smite-node: {}\n")
            candidate.write_text("services:\n  smite-node: {}\n")
            candidate.chmod(0o600)
            active = [str(base)]
            def mock_run(args, **kwargs):
                probe = args[3]
                if "com.docker.compose.project.config_files" in probe:
                    return ",".join(active)
                if "com.docker.compose.service" in probe:
                    return "smite-node"
                if "com.docker.compose.project" in probe:
                    return PROJECT
                raise AssertionError(args)
            with patch.object(p, "NODE_COMPOSE", base), \
                 patch.object(p, "NODE_SECURITY_CANDIDATE", candidate), \
                 patch.object(p, "_run", side_effect=mock_run), \
                 patch.dict(os.environ, {"COMPOSE_PROJECT_NAME": ""}):
                base_cmd = ["docker", "compose", "--project-name", PROJECT, "-f", str(base)]
                self.assertEqual(p._rc7_foreign_compose_command(), base_cmd)
                self.assertEqual(p._rc7_foreign_compose_command(staged_candidate=True),
                                 base_cmd + ["-f", str(candidate)])
                active.append(str(candidate))
                with self.assertRaises(p.WizardHold):
                    p._rc7_foreign_compose_command(staged_candidate=True)
                self.assertEqual(p._rc7_foreign_compose_command(rollback=True), base_cmd)
                active[:] = [str(base), "/tmp/untrusted.yml"]
                with self.assertRaises(p.WizardHold):
                    p._rc7_foreign_compose_command(rollback=True)
                active[:] = [str(base)]
                with patch.dict(os.environ, {"COMPOSE_PROJECT_NAME": "smite"}):
                    with self.assertRaises(p.WizardHold):
                        p._rc7_foreign_compose_command()

    def test_rc7_panel_image_requires_signed_transport(self):
        calls = []
        def mocked(args, **kwargs):
            calls.append(args)
            if args[:2] == ["docker", "inspect"]:
                return p._FOREIGN_PANEL_IMAGE_RC7
            if args[:3] == ["docker", "exec", "smite-panel"]:
                return "PANEL_FOREIGN_HMAC_GATEWAY=READY"
            raise AssertionError(args)
        with patch.object(p, "_run", side_effect=mocked):
            p._require_panel_foreign_transport()
        self.assertEqual(len(calls), 2)
        with patch.object(p, "_run", return_value="smite-panel:latest"):
            with self.assertRaises(p.WizardHold):
                p._require_panel_foreign_transport()

    def test_rc7_ir_origin_approval_reaches_strict_path_validation(self):
        state = {
            "SMITE_ROLE": "panel-iran",
            "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
            "SMITE_NODE_NAME": "node-ir",
        }
        with patch.object(p, "_field_trial_gate"), \
             patch.object(p, "_approved_foreign_control_url",
                          side_effect=p.WizardHold("RC7_PATH_VALIDATOR_REACHED")):
            with self.assertRaisesRegex(p.WizardHold, "RC7_PATH_VALIDATOR_REACHED"):
                p.approve_foreign_origin_field_trial(
                    node_id="nodeid123456", node_name="node-kh",
                    control_url="https://grandoptical.ir/smite-node/" + "a" * 16,
                    state=state,
                )
            with self.assertRaisesRegex(p.WizardHold, "reviewed signed IR Panel"):
                p.approve_foreign_origin_field_trial(
                    node_id="nodeid123456", node_name="node-kh",
                    control_url="https://grandoptical.ir/smite-node/" + "a" * 16,
                    state={**state, "SMITE_MANAGED_VERSION": "2.0.0-rc.6"},
                )

    def test_foreign_rc7_real_preflight_checks_tls_and_readonly_sanaei(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state.env"
            node = root / "node"
            node.mkdir()
            compose = node / "docker-compose.yml"
            compose.write_text("services:\n  smite-node: {}\n")
            path = "/smite-node/" + "a" * 16
            control = "https://grandoptical.ir" + path
            (root / "foreign-gateway.env").write_text(
                "SMITE_FOREIGN_GATEWAY_DOMAIN=grandoptical.ir\n"
                "SMITE_FOREIGN_PANEL_DOMAIN=iran.grandoptical.ir\n"
                "SMITE_FOREIGN_PANEL_SOURCE_IPV4=213.176.7.204\n"
                "SMITE_FOREIGN_CONTROL_PATH=" + path + "\n"
                "SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443\n"
                "SMITE_FOREIGN_GATEWAY_MODE=https-control-path\n"
            )
            (node / ".env").write_text(
                "SMITE_NODE_PANEL_AUTH_MODE=paused\n"
                "SMITE_AGENT_AUTH_MODE=strict\n"
                "SMITE_ENGINE_INVENTORY_MODE=managed\n"
                "PANEL_ADDRESS=iran.grandoptical.ir:443\n"
                "SMITE_CONTROL_ADDRESS=" + control + "\n"
            )
            for x in (root / "foreign-gateway.env", node / ".env"):
                x.chmod(0o600)
            service = {
                "image": p._FOREIGN_NODE_IMAGE_RC7,
                "network_mode": "host",
                "cap_add": ["NET_ADMIN", "SYS_MODULE"],
                "devices": [{"source": "/dev/net/tun", "target": "/dev/net/tun", "permissions": "rwm"}],
                "command": ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"],
                "environment": {
                    "SMITE_NODE_PANEL_AUTH_MODE": "paused",
                    "SMITE_AGENT_AUTH_MODE": "strict",
                    "SMITE_ENGINE_INVENTORY_MODE": "managed",
                    "PANEL_ADDRESS": "iran.grandoptical.ir:443",
                    "SMITE_CONTROL_ADDRESS": control,
                    "NODE_ROLE": "foreign",
                    "SMITE_SANAEI_INVENTORY_ENABLED": "true",
                },
                "volumes": [{"target": "/run/smite-sanaei-ro",
                             "source": "/opt/3x-ui/instances/01/db", "read_only": True}],
            }
            def mock_run(args, **kwargs):
                if args[:2] == ["docker", "inspect"]:
                    return p._FOREIGN_NODE_IMAGE_RC7 if ".Config.Image" in args[3] else "healthy"
                if args[:2] == ["docker", "compose"]:
                    return json.dumps({"services": {"smite-node": service}})
                if args[0] == "curl":
                    self.assertIn("grandoptical.ir:443:127.0.0.1", args)
                    return '{"status":"ok","service":"smite-node"}'
                raise AssertionError(args)
            current = {
                "SMITE_ROLE": "foreign", "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
                "SMITE_PANEL_DOMAIN": "iran.grandoptical.ir",
            }
            with patch.object(p, "STATE", state), patch.object(p, "NODE_DIR", node), \
                 patch.object(p, "NODE_COMPOSE", compose), \
                 patch.object(p, "_rc7_foreign_compose_command", return_value=[
                     "docker", "compose", "--project-name", PROJECT, "-f", str(compose)]), \
                 patch.object(p, "_run", side_effect=mock_run):
                self.assertEqual(p._foreign_gateway_preflight(current),
                                 ("iran.grandoptical.ir", "grandoptical.ir", control))
                # Exact pre-pairing Sanaei placeholder is accepted ONLY by
                # explicit read-only recovery admission. Ordinary activation
                # must continue refusing missing inventory.
                service["environment"]["SMITE_SANAEI_INVENTORY_ENABLED"] = "false"
                service["volumes"][0]["source"] = str(node / ".sanaei-empty")
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current)
                self.assertEqual(p._foreign_gateway_preflight(
                    current, allow_unattached_sanaei=True,
                ), ("iran.grandoptical.ir", "grandoptical.ir", control))
                service["volumes"][0]["read_only"] = False
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current, allow_unattached_sanaei=True)
                service["volumes"][0]["read_only"] = True
                service["cap_add"] = ["NET_ADMIN", "SYS_MODULE", "SYS_ADMIN"]
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current, allow_unattached_sanaei=True)
                service["cap_add"] = ["NET_ADMIN", "SYS_MODULE"]
                service["volumes"][0]["source"] = "/opt/3x-ui/instances/01/db"
                service["environment"]["SMITE_SANAEI_INVENTORY_ENABLED"] = "true"
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current, allow_unattached_sanaei=True)
                service["volumes"][0]["read_only"] = False
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current)
                service["volumes"][0]["read_only"] = True
                service["command"][3] = "0.0.0.0"
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current)
                service["command"][3] = "127.0.0.1"
                # Extra host capabilities or devices must still fail closed.
                for caps in (
                    ["NET_ADMIN", "SYS_MODULE", "SYS_ADMIN"],
                    ["NET_ADMIN"],
                    [],
                ):
                    service["cap_add"] = caps
                    with self.subTest(cap_add=caps), self.assertRaises(p.WizardHold):
                        p._foreign_gateway_preflight(current)
                service["cap_add"] = ["NET_ADMIN", "SYS_MODULE"]
                for devices in (
                    ["/dev/net/tun:/dev/net/tun", "/dev/kvm:/dev/kvm"],
                    ["/dev/kvm:/dev/kvm"],
                    [],
                ):
                    service["devices"] = devices
                    with self.subTest(devices=devices), self.assertRaises(p.WizardHold):
                        p._foreign_gateway_preflight(current)
                # Docker Compose 5 maps the exact TUN device to a dict.
                # Reject changes in any field or additional devices.
                for device in (
                    {"source": "/dev/other", "target": "/dev/net/tun", "permissions": "rwm"},
                    {"source": "/dev/net/tun", "target": "/dev/other", "permissions": "rwm"},
                    {"source": "/dev/net/tun", "target": "/dev/net/tun", "permissions": "rw"},
                    {"source": "/dev/net/tun", "target": "/dev/net/tun", "permissions": "rwm", "other": 1},
                ):
                    service["devices"] = [device]
                    with self.subTest(device=device), self.assertRaises(p.WizardHold):
                        p._foreign_gateway_preflight(current)
                service["devices"] = [{"source": "/dev/net/tun",
                                      "target": "/dev/net/tun", "permissions": "rwm"}]
                self.assertEqual(p._foreign_gateway_preflight(current),
                                 ("iran.grandoptical.ir", "grandoptical.ir", control))
                service["devices"] = ["/dev/net/tun:/dev/net/tun:rwm"]
                self.assertEqual(p._foreign_gateway_preflight(current),
                                 ("iran.grandoptical.ir", "grandoptical.ir", control))

    def test_staged_recovery_refuses_replay_and_signed_overlays(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            identity = root / "identity"
            identity.mkdir()
            candidate = root / "candidate.yml"
            replay = root / "replay.sqlite3"
            current = {
                "SMITE_ROLE": "foreign",
                "SMITE_CONNECTION_MODE": "standard",
                "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
            }
            env = (
                "SMITE_NODE_PANEL_AUTH_MODE=paused\n"
                "SMITE_AGENT_AUTH_MODE=strict\n"
                "SMITE_ENGINE_INVENTORY_MODE=managed\n"
            )
            with (patch.object(p, "_field_trial_gate"),
                  patch.object(p, "_identity_record", return_value=("node-12345678", "a"*64)),
                  patch.object(p, "_require_no_active_engine_overlays"),
                  patch.object(p, "_foreign_gateway_preflight") as gateway,
                  patch.object(p, "_run", return_value=env),
                  patch.object(p, "NODE_SECURITY_CANDIDATE", candidate),
                  patch.object(p, "REPLAY_DB", replay),
                  patch.object(p, "IDENTITY_DIR", identity)):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    p.staged_foreign_sanaei_admission(current)
                self.assertIn("ADMISSION_PASS_READ_ONLY", output.getvalue())
                gateway.assert_called_with(current, allow_unattached_sanaei=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    p.staged_foreign_sanaei_admission(current, verify_attached=True)
                gateway.assert_called_with(current, allow_unattached_sanaei=False)
                for marker in (candidate, replay, identity / "replay-enrollment.json"):
                    marker.touch()
                    with self.subTest(marker=marker), self.assertRaises(p.WizardHold):
                        p.staged_foreign_sanaei_admission(current)
                    marker.unlink()
                with patch.object(p, "_run", return_value=env.replace(
                    "SMITE_NODE_PANEL_AUTH_MODE=paused",
                    "SMITE_NODE_PANEL_AUTH_MODE=signed",
                )):
                    with self.assertRaises(p.WizardHold):
                        p.staged_foreign_sanaei_admission(current)
                with self.assertRaises(p.WizardHold):
                    p.staged_foreign_sanaei_admission({
                        **current, "SMITE_MANAGED_VERSION": "2.0.0-rc.6"
                    })

    def test_staged_recovery_wizard_requires_operator_and_preserves_identity(self):
        source = (ROOT / "modules/smite-install.sh").read_text()
        body = source.split("smite_install_sanaei_foreign() {", 1)[1].split(
            "\nsmite_install_field_trial_patch_compose_image()", 1
        )[0]
        for needle in (
            "--admit-staged-foreign-sanaei",
            "--verify-staged-foreign-sanaei",
            "ATTACH-STAGED-KH-SANAEI",
            "staged_identity_sha",
            "PAIRING_IDENTITY=PRESERVED",
            "Staged identity recovery requires an existing registered Sanaei database",
        ):
            self.assertIn(needle, body)
        self.assertNotIn('rm -f "$staged_identity_file"', body)

    def test_activation_and_rollback_use_guarded_compose(self):
        source = (ROOT / "modules/smite-node-pairing.py").read_text()
        body = source.split("def activate_foreign_node_field_trial(", 1)[1].split(
            "\ndef rollback_node_to_paused_field_trial(", 1)[0]
        self.assertIn("_rc7_foreign_compose_command(staged_candidate=True)", body)
        self.assertIn("_rc7_foreign_compose_command(rollback=True)", body)
        self.assertIn("candidate_command + [", body)
        self.assertIn("rollback_command + [", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
