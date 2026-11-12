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
        self.assertEqual(p._FOREIGN_NODE_IMAGE_UNIFIED_TRIAL,
            "ghcr.io/aghajani82/smite-node@sha256:587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483")

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
                # The verified post-up state may contain exactly base +
                # original signed candidate, never base alone or unknown.
                self.assertEqual(
                    p._rc7_foreign_compose_command(verify_active_candidate=True),
                    base_cmd + ["-f", str(candidate)])
                for bad in (
                    {"verify_active_candidate": True, "rollback": True},
                    {"verify_active_candidate": True, "staged_candidate": True},
                    {"verify_active_candidate": "yes"},
                ):
                    with self.subTest(bad=bad), self.assertRaises(p.WizardHold):
                        p._rc7_foreign_compose_command(**bad)
                self.assertEqual(p._rc7_foreign_compose_command(rollback=True), base_cmd)
                active[:] = [str(base)]
                with self.assertRaisesRegex(p.WizardHold, "not actually applied"):
                    p._rc7_foreign_compose_command(verify_active_candidate=True)
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
                    return service["image"] if ".Config.Image" in args[3] else "healthy"
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
                # Exact unified trial digest AND explicit :443 are
                # permitted together for READ-ONLY review, never legacy
                # activation/default RC7. Keep the official lane unchanged.
                service["image"] = p._FOREIGN_NODE_IMAGE_UNIFIED_TRIAL
                trial_control = "https://grandoptical.ir:443" + path
                original_node_env = (node / ".env").read_text()
                (node / ".env").write_text(
                    original_node_env.replace(control, trial_control))
                service["environment"]["SMITE_CONTROL_ADDRESS"] = trial_control
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current)
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current,
                        expected_image=p._FOREIGN_NODE_IMAGE_UNIFIED_TRIAL)
                self.assertEqual(p._foreign_gateway_preflight(
                    current, review_unified_trial=True),
                    ("iran.grandoptical.ir", "grandoptical.ir", trial_control))
                # A missing :443 or drifted control address must HOLD in
                # the trial lane, even if HTTPS would reach the same host.
                (node / ".env").write_text(original_node_env)
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current,
                        review_unified_trial=True)
                (node / ".env").write_text(
                    original_node_env.replace(control, trial_control))
                service["environment"]["SMITE_CONTROL_ADDRESS"] = control
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current,
                        review_unified_trial=True)
                service["environment"]["SMITE_CONTROL_ADDRESS"] = trial_control
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current,
                        review_unified_trial=True, allow_unattached_sanaei=True)
                with self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(current,
                        review_unified_trial=True, expected_image=p._FOREIGN_NODE_IMAGE_RC7)
                service["image"] = p._FOREIGN_NODE_IMAGE_RC7
                (node / ".env").write_text(original_node_env)
                service["environment"]["SMITE_CONTROL_ADDRESS"] = control
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

    def test_rc7_paused_rollback_verifies_running_image_env_identity_replay(self):
        retained = ("node-12345678", "a" * 64)
        image_id = "sha256:" + "d" * 64
        probe = {
            "image": p._FOREIGN_NODE_IMAGE_RC7,
            "runtime_id": image_id,
            "local_id": image_id,
            "environment": (
                "SMITE_NODE_PANEL_AUTH_MODE=paused\n"
                "SMITE_AGENT_AUTH_MODE=strict\n"
                "SMITE_ENGINE_INVENTORY_MODE=managed\n"
            ),
            "identity": retained,
            "replay": True,
        }
        calls = []
        def read_only_run(args, **kwargs):
            calls.append(args)
            self.assertEqual(kwargs, {"timeout": 10, "capture": True})
            if args[:3] == ["docker", "inspect", "-f"]:
                field = args[3]
                if field == "{{.Config.Image}}": return probe["image"]
                if field == "{{.Image}}": return probe["runtime_id"]
                if field.startswith("{{range .Config.Env}}"): return probe["environment"]
            if args[:4] == ["docker", "image", "inspect", "-f"]:
                self.assertEqual(args[-1], p._FOREIGN_NODE_IMAGE_RC7)
                return probe["local_id"]
            raise AssertionError("Unexpected mutation: " + repr(args))
        with patch.object(p, "_run", side_effect=read_only_run), \
             patch.object(p, "_identity_record", side_effect=lambda: probe["identity"]), \
             patch.object(p, "_replay_artifacts_valid", side_effect=lambda: probe["replay"]):
            p._rc7_foreign_paused_rollback_verified(
                expected_identity=retained, require_replay=True,
            )
            self.assertEqual(len(calls), 4)
            for key, wrong in (
                ("image", p._FOREIGN_NODE_IMAGE_UNIFIED_TRIAL),
                ("runtime_id", "sha256:" + "e"*64),
                ("local_id", "sha256:" + "e"*64),
                ("environment", probe["environment"].replace("paused", "signed")),
                ("environment", probe["environment"] + "SMITE_AGENT_AUTH_MODE=legacy\n"),
                ("environment", probe["environment"].replace("managed", "disabled")),
                ("identity", ("node-12345678", "b"*64)),
                ("replay", False),
            ):
                saved = probe[key]
                probe[key] = wrong
                try:
                    with self.subTest(key=key, wrong=str(wrong)[:25]), \
                         self.assertRaises(p.WizardHold):
                        p._rc7_foreign_paused_rollback_verified(
                            expected_identity=retained, require_replay=True,
                        )
                finally:
                    probe[key] = saved
        self.assertTrue(all("up" not in cmd for cmd in calls))

    def test_trial_pinned_image_read_only_uses_existing_rc7_witness(self):
        image_id = "sha256:" + "d" * 64
        observed = []
        def inspect(args, **kwargs):
            observed.append(args)
            self.assertEqual(kwargs, {"timeout": 10, "capture": True})
            if args[:3] == ["docker", "inspect", "-f"]:
                if args[3] == "{{.Config.Image}}":
                    return p._FOREIGN_NODE_IMAGE_UNIFIED_TRIAL
                if args[3] == "{{.Image}}":
                    return image_id
            if args[:4] == ["docker", "image", "inspect", "-f"]:
                self.assertEqual(args[-1], p._FOREIGN_NODE_IMAGE_UNIFIED_TRIAL)
                return image_id
            raise AssertionError("unexpected mutation: " + repr(args))
        with patch.object(p, "_run", side_effect=inspect):
            p._rc7_foreign_pinned_image_verified(review_unified_trial=True)
            self.assertEqual(len(observed), 3)
            with self.assertRaisesRegex(p.WizardHold, "published signed digest"):
                p._rc7_foreign_pinned_image_verified()
            with self.assertRaisesRegex(p.WizardHold, "selector invalid"):
                p._rc7_foreign_pinned_image_verified(review_unified_trial="yes")

    def test_rc7_rollback_refuses_trial_image_before_any_recreate(self):
        state = {
            "SMITE_ROLE": "foreign",
            "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
            "SMITE_CONNECTION_MODE": "standard",
        }
        commands = []
        def inspect(args, **kwargs):
            commands.append(args)
            self.assertEqual(args, [
                "docker", "inspect", "-f", "{{.Config.Image}}", "smite-node",
            ])
            return p._FOREIGN_NODE_IMAGE_UNIFIED_TRIAL
        with patch.object(p, "_field_trial_gate"), \
             patch.object(p, "_require_no_active_engine_overlays"), \
             patch.object(p, "_regular", return_value=b""), \
             patch.object(p, "_run", side_effect=inspect), \
             patch.object(p, "_rc7_foreign_compose_command") as guarded:
            with self.assertRaisesRegex(p.WizardHold, "not the published signed digest"):
                p.rollback_node_to_paused_field_trial(state)
            guarded.assert_not_called()
        self.assertEqual(len(commands), 1)

    def test_rc7_activation_requires_actual_pinned_image_before_mutation(self):
        state = {
            "SMITE_ROLE": "foreign",
            "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
            "SMITE_CONNECTION_MODE": "standard",
        }
        image_id = "sha256:" + "d"*64
        actual = {"id": "sha256:" + "e"*64}
        commands = []
        def probe(args, **kwargs):
            commands.append(args)
            if args[:3] == ["docker", "inspect", "-f"]:
                if args[3] == "{{.Config.Image}}": return p._FOREIGN_NODE_IMAGE_RC7
                if args[3] == "{{.Image}}": return actual["id"]
            if args[:4] == ["docker", "image", "inspect", "-f"]:
                return image_id
            raise AssertionError("Unexpected mutation before pin: " + repr(args))
        with patch.object(p, "_field_trial_gate"), \
             patch.object(p, "_require_no_active_engine_overlays"), \
             patch.object(p, "_foreign_gateway_preflight",
                          return_value=("iran.example.org", "kh.example.org",
                                        "https://kh.example.org/smite-node/"+"a"*32)), \
             patch.object(p, "_rc7_foreign_compose_command", return_value=["docker","compose"]), \
             patch.object(p, "_run", side_effect=probe), \
             patch.object(p, "_prepare_security_candidate") as candidate, \
             patch.object(p, "_provision_replay_once") as replay:
            with self.assertRaisesRegex(p.WizardHold, "image ID differs"):
                p.activate_foreign_node_field_trial(state)
            candidate.assert_not_called()
            replay.assert_not_called()
        self.assertEqual(len(commands), 3)

    def test_rc7_manual_rollback_proves_no_rekey_after_recreate(self):
        import contextlib
        import io
        state = {
            "SMITE_ROLE": "foreign",
            "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
            "SMITE_CONNECTION_MODE": "standard",
        }
        original = ("node-12345678", "a"*64)
        disk_id = "sha256:" + "d"*64
        runtime = {"identity": original, "replay": True, "image_id": disk_id,
                   "rotate_on_recreate": False}
        cmds = []
        def command(args, **kwargs):
            cmds.append(args)
            if "up" in args:
                self.assertIn("--force-recreate", args)
                # A genuinely broken recreate rotates the identity AFTER
                # the caller captured it, never before that snapshot.
                if runtime["rotate_on_recreate"]:
                    runtime["identity"] = ("node-12345678", "b"*64)
                return ""
            if args[:3] == ["docker", "inspect", "-f"]:
                if args[3] == "{{.Config.Image}}": return p._FOREIGN_NODE_IMAGE_RC7
                if args[3] == "{{.Image}}": return runtime["image_id"]
                if "{{range .Config.Env}}" in args[3]:
                    return (
                        "SMITE_NODE_PANEL_AUTH_MODE=paused\n"
                        "SMITE_AGENT_AUTH_MODE=strict\n"
                        "SMITE_ENGINE_INVENTORY_MODE=managed\n"
                    )
            if args[:4] == ["docker", "image", "inspect", "-f"]:
                return disk_id
            raise AssertionError(args)
        with tempfile.TemporaryDirectory() as tmp:
            identity = Path(tmp)/"node-identity.json"
            identity.write_text("{}")
            with patch.object(p, "_field_trial_gate"), \
                 patch.object(p, "_require_no_active_engine_overlays"), \
                 patch.object(p, "_regular", return_value=b""), \
                 patch.object(p, "IDENTITY_FILE", identity), \
                 patch.object(p, "_identity_record", side_effect=lambda: runtime["identity"]), \
                 patch.object(p, "_replay_artifacts_valid", side_effect=lambda: runtime["replay"]), \
                 patch.object(p, "_rc7_foreign_compose_command",
                              return_value=["docker", "compose", "--project-name", "test"]), \
                 patch.object(p, "_wait_container"), \
                 patch.object(p, "_run", side_effect=command):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    p.rollback_node_to_paused_field_trial(state)
                self.assertIn("NODE_RUNTIME=PAUSED_STRICT", output.getvalue())
                self.assertEqual(sum("up" in cmd for cmd in cmds), 1)
                runtime["rotate_on_recreate"] = True
                with self.assertRaisesRegex(p.WizardHold, "identity changed"):
                    p.rollback_node_to_paused_field_trial(state)
                runtime["rotate_on_recreate"] = False
                runtime["identity"] = original
                runtime["image_id"] = "sha256:" + "e"*64
                with self.assertRaisesRegex(p.WizardHold, "image ID differs"):
                    p.rollback_node_to_paused_field_trial(state)

    def test_failed_signed_rc7_activation_checks_post_rollback_identity(self):
        state = {
            "SMITE_ROLE": "foreign",
            "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
            "SMITE_CONNECTION_MODE": "standard",
            "SMITE_NODE_NAME": "node-kh",
        }
        retained = ("node-12345678", "a"*64)
        commands = []
        def mock_run(args, **kwargs):
            commands.append(args)
            if args[-2:] == ["config", "--quiet"]:
                return ""
            if "up" in args:
                self.assertIn("--force-recreate", args)
                return ""
            if args[:3] == ["docker", "inspect", "-f"]:
                self.assertIn("{{range .Config.Env}}", args[3])
                env_probes = sum(
                    cmd[:3] == ["docker", "inspect", "-f"]
                    for cmd in commands
                )
                mode = "signed" if env_probes == 1 else "paused"
                return (
                    "SMITE_NODE_PANEL_AUTH_MODE=" + mode + "\n"
                    "SMITE_AGENT_AUTH_MODE=strict\n"
                    "SMITE_ENGINE_INVENTORY_MODE=managed\n"
                )
            raise AssertionError(args)
        with patch.object(p, "_field_trial_gate"), \
             patch.object(p, "_require_no_active_engine_overlays"), \
             patch.object(p, "_foreign_gateway_preflight",
                          return_value=("iran.example.org","kh.example.org",
                                        "https://kh.example.org/smite-node/"+"a"*32)), \
             patch.object(p, "_rc7_foreign_compose_command",
                          return_value=["docker","compose","--project-name","test"]), \
             patch.object(p, "_rc7_foreign_pinned_image_verified"), \
             patch.object(p, "_identity_record", return_value=retained), \
             patch.object(p, "_regular", return_value=b"checked"), \
             patch.object(p, "_prepare_security_candidate"), \
             patch.object(p, "_provision_replay_once"), \
             patch.object(p, "_run", side_effect=mock_run), \
             patch.object(p, "_wait_container"), \
             patch.object(p, "_local_signed_replay_probe",
                          side_effect=p.WizardHold("fake signed proof failure")), \
             patch.object(p, "_rc7_foreign_paused_rollback_verified") as guard:
            with self.assertRaisesRegex(p.WizardHold, "paused again"):
                p.activate_foreign_node_field_trial(state)
            guard.assert_called_once_with(
                expected_identity=retained, require_replay=True,
            )
            self.assertEqual(sum("up" in cmd for cmd in commands), 2)
            # A failed post-rollback image/identity check must escalate
            # to CRITICAL instead of advertising safe recovery.
            commands.clear()
            guard.reset_mock(side_effect=True)
            guard.side_effect = p.WizardHold("fake identity drift")
            with self.assertRaisesRegex(p.WizardHold, "CRITICAL"):
                p.activate_foreign_node_field_trial(state)
            guard.assert_called_once_with(
                expected_identity=retained, require_replay=True,
            )

    def test_manual_rc7_rollback_rechecks_effective_compose_after_recreate(self):
        state = {
            "SMITE_ROLE": "foreign",
            "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
            "SMITE_CONNECTION_MODE": "standard",
        }
        events = []
        def compose(*, rollback=False, staged_candidate=False):
            events.append(("compose", rollback, staged_candidate))
            if not rollback:
                # A successful command was sent to Docker, but the live
                # service still reports the candidate in config_files.
                raise p.WizardHold("Foreign RC7 active Compose files are not reviewed")
            return ["docker", "compose", "--project-name", "test"]
        def run(args, **kw):
            events.append(("command", args))
            if "up" in args:
                return ""
            if args[:3] == ["docker", "inspect", "-f"] and                     "{{range .Config.Env}}" in args[3]:
                return (
                    "SMITE_NODE_PANEL_AUTH_MODE=paused\n"
                    "SMITE_AGENT_AUTH_MODE=strict\n"
                    "SMITE_ENGINE_INVENTORY_MODE=managed\n"
                )
            raise AssertionError(args)
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-yet-paired-identity.json"
            with patch.object(p, "_field_trial_gate"), \
                 patch.object(p, "_require_no_active_engine_overlays"), \
                 patch.object(p, "_regular", return_value=b"owned"), \
                 patch.object(p, "IDENTITY_FILE", missing), \
                 patch.object(p, "_rc7_foreign_pinned_image_verified"), \
                 patch.object(p, "_rc7_foreign_paused_rollback_verified"), \
                 patch.object(p, "_rc7_foreign_compose_command", side_effect=compose), \
                 patch.object(p, "_wait_container"), \
                 patch.object(p, "_run", side_effect=run):
                with self.assertRaisesRegex(p.WizardHold, "active Compose files"):
                    p.rollback_node_to_paused_field_trial(state)
        self.assertEqual(events[0], ("compose", True, False))
        self.assertIn(("compose", False, False), events)
        self.assertEqual(sum("up" in e[1] for e in events if e[0]=="command"),1)

    def test_failed_foreign_activation_must_verify_compose_after_rollback(self):
        state = {
            "SMITE_ROLE": "foreign", "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
            "SMITE_CONNECTION_MODE": "standard", "SMITE_NODE_NAME": "node-kh",
        }
        retained = ("node-12345678", "a"*64)
        state_of = {"signed": False, "active_override": False}
        events = []
        def compose(*, rollback=False, staged_candidate=False):
            events.append(("compose", rollback, staged_candidate))
            if not (rollback or staged_candidate) and state_of["active_override"]:
                raise p.WizardHold("Foreign RC7 active Compose files are not reviewed")
            return ["docker", "compose", "--project-name", "test"]
        def run(args, **kw):
            events.append(("command", args))
            if args[-2:] == ["config","--quiet"]:
                return ""
            if "up" in args:
                if "-f" in args and "never" in args:
                    state_of["signed"] = True
                else:
                    state_of["signed"] = False
                    state_of["active_override"] = True
                return ""
            if args[:3] == ["docker", "inspect", "-f"] and                     "{{range .Config.Env}}" in args[3]:
                return (
                    "SMITE_NODE_PANEL_AUTH_MODE=" +
                    ("signed" if state_of["signed"] else "paused") + "\n"
                    "SMITE_AGENT_AUTH_MODE=strict\n"
                    "SMITE_ENGINE_INVENTORY_MODE=managed\n"
                )
            raise AssertionError(args)
        with patch.object(p, "_field_trial_gate"), \
             patch.object(p, "_require_no_active_engine_overlays"), \
             patch.object(p, "_foreign_gateway_preflight",
                          return_value=("iran.example.org","kh.example.org",
                                        "https://kh.example.org/smite-node/"+"a"*32)), \
             patch.object(p, "_rc7_foreign_compose_command",side_effect=compose), \
             patch.object(p, "_rc7_foreign_pinned_image_verified"), \
             patch.object(p, "_identity_record",return_value=retained), \
             patch.object(p, "_regular",return_value=b"owned"), \
             patch.object(p, "_prepare_security_candidate"), \
             patch.object(p, "_provision_replay_once"), \
             patch.object(p, "_run",side_effect=run), \
             patch.object(p, "_wait_container"), \
             patch.object(p, "_local_signed_replay_probe",
                          side_effect=p.WizardHold("synthetic lost signed proof")), \
             patch.object(p, "_rc7_foreign_paused_rollback_verified"):
            with self.assertRaisesRegex(p.WizardHold,"CRITICAL"):
                p.activate_foreign_node_field_trial(state)
        self.assertIn(("compose",False,False),events[-1:])
        self.assertEqual(sum("up" in e[1] for e in events if e[0]=="command"),2)

    def test_unified_pair_release_refuses_even_valid_signed_trial_before_mutation(self):
        import subprocess
        source="b865be93e22153c60769f6329e6e55e781494ded"
        commands=[]
        def signed_trial(command, **kwargs):
            commands.append(command)
            role=("panel" if "smite_role=panel" in command else "node")
            signed=[{
                "critical":{
                    "type":"cosign container image signature",
                    "image":{"docker-manifest-digest":command[-1].rsplit("@",1)[1]}},
                "optional":{
                    "smite_source_sha":source,
                    "smite_role":role,
                    "smite_trial":"unified-install"},
            }]
            return subprocess.CompletedProcess(command,0,json.dumps(signed),"")
        state={
            "SMITE_ROLE":"foreign", "SMITE_MANAGED_VERSION":"2.0.0-rc.7",
            "SMITE_CONNECTION_MODE":"standard", "SMITE_NODE_NAME":"node-kh",
        }
        with patch("subprocess.run", side_effect=signed_trial), \
             patch.object(p,"_field_trial_gate"), \
             patch.object(p,"_require_no_active_engine_overlays") as overlays, \
             patch.object(p,"_foreign_gateway_preflight") as gateway, \
             patch.object(p,"_rc7_foreign_compose_command") as compose, \
             patch.object(p,"_prepare_security_candidate") as candidate, \
             patch.object(p,"_run") as run:
            with self.assertRaisesRegex(p.WizardHold,"NOT released"):
                p.activate_foreign_node_field_trial(
                    state, reviewed_unified_trial=True)
            with self.assertRaisesRegex(p.WizardHold,"NOT released"):
                p.rollback_node_to_paused_field_trial(
                    state, reviewed_unified_trial=True)
            self.assertEqual(len(commands),4)
            overlays.assert_not_called()
            gateway.assert_not_called()
            compose.assert_not_called()
            candidate.assert_not_called()
            run.assert_not_called()

    def test_unified_release_selector_fails_closed_and_never_changes_default(self):
        state={
            "SMITE_ROLE":"foreign", "SMITE_MANAGED_VERSION":"2.0.0-rc.7",
            "SMITE_CONNECTION_MODE":"standard", "SMITE_NODE_NAME":"node-kh",
        }
        for selector in (None, "true", 1, 0, {}):
            with self.subTest(selector=repr(selector)):
                with self.assertRaisesRegex(p.WizardHold,"selector invalid"):
                    p.activate_foreign_node_field_trial(
                        state, reviewed_unified_trial=selector)
                with self.assertRaisesRegex(p.WizardHold,"selector invalid"):
                    p.rollback_node_to_paused_field_trial(
                        state, reviewed_unified_trial=selector)
        with self.assertRaisesRegex(p.WizardHold,"selector invalid"):
            p.activate_foreign_node_field_trial(
                state, reviewed_unified_trial=True, reviewed_rc2=True)
        # An injected positive trial-release gate reaches the *existing*
        # exact-image read-only witness. It may NOT use the old RC7 image.
        observed=[]
        def gateway(current, **kwargs):
            observed.append(("gateway",kwargs))
            return ("iran.example.org","kh.example.org",
                    "https://kh.example.org:443/smite-node/"+"a"*32)
        def pinned(**kwargs):
            observed.append(("image",kwargs))
            raise p.WizardHold("TRIAL_PIN_ONLY")
        with patch.object(p,"_field_trial_gate"), \
             patch.object(p,"_require_unified_foreign_release"), \
             patch.object(p,"_require_no_active_engine_overlays"), \
             patch.object(p,"_foreign_gateway_preflight",side_effect=gateway), \
             patch.object(p,"_rc7_foreign_compose_command",return_value=["docker","compose"]), \
             patch.object(p,"_rc7_foreign_pinned_image_verified",side_effect=pinned), \
             patch.object(p,"_prepare_security_candidate") as candidate, \
             patch.object(p,"_run") as run:
            with self.assertRaisesRegex(p.WizardHold,"TRIAL_PIN_ONLY"):
                p.activate_foreign_node_field_trial(
                    state, reviewed_unified_trial=True)
            self.assertEqual(observed,[
                ("gateway",{"review_unified_trial":True}),
                ("image",{"review_unified_trial":True}),
            ])
            candidate.assert_not_called()
            run.assert_not_called()

    def test_unified_trial_activation_failure_uses_same_pinned_rollback_contract(self):
        state={
            "SMITE_ROLE":"foreign","SMITE_MANAGED_VERSION":"2.0.0-rc.7",
            "SMITE_CONNECTION_MODE":"standard","SMITE_NODE_NAME":"node-kh",
        }
        retained=("node-12345678","a"*64)
        commands=[]
        modes={"signed":False}
        def run(args, **kwargs):
            commands.append(args)
            if args[-2:]==["config","--quiet"]:
                return ""
            if "up" in args:
                self.assertIn("--force-recreate",args)
                modes["signed"]=not modes["signed"]
                return ""
            if args[:3]==["docker","inspect","-f"]:
                self.assertIn("{{range .Config.Env}}",args[3])
                return ("SMITE_NODE_PANEL_AUTH_MODE="+
                        ("signed" if modes["signed"] else "paused")+"\n"
                        "SMITE_AGENT_AUTH_MODE=strict\n"
                        "SMITE_ENGINE_INVENTORY_MODE=managed\n")
            raise AssertionError(args)
        with patch.object(p,"_field_trial_gate"), \
             patch.object(p,"_require_unified_foreign_release"), \
             patch.object(p,"_require_no_active_engine_overlays"), \
             patch.object(p,"_foreign_gateway_preflight",
                          return_value=("iran.example.org","kh.example.org",
                                        "https://kh.example.org:443/smite-node/"+"a"*32)) as gateway, \
             patch.object(p,"_rc7_foreign_compose_command",
                          return_value=["docker","compose","--project-name","existing"]) as compose, \
             patch.object(p,"_rc7_foreign_pinned_image_verified") as image_pin, \
             patch.object(p,"_identity_record",return_value=retained), \
             patch.object(p,"_regular",return_value=b"owned"), \
             patch.object(p,"_prepare_security_candidate"), \
             patch.object(p,"_provision_replay_once"), \
             patch.object(p,"_run",side_effect=run), \
             patch.object(p,"_wait_container"), \
             patch.object(p,"_local_signed_replay_probe",
                          side_effect=p.WizardHold("synthetic signed proof failure")), \
             patch.object(p,"_rc7_foreign_paused_rollback_verified") as recovered:
            with self.assertRaisesRegex(p.WizardHold,"paused again"):
                p.activate_foreign_node_field_trial(
                    state, reviewed_unified_trial=True)
            gateway.assert_called_once_with(state,review_unified_trial=True)
            self.assertEqual(
                [x.kwargs for x in image_pin.call_args_list],
                [{"review_unified_trial":True},{"review_unified_trial":True}])
            self.assertTrue(any(x.kwargs=={"rollback":True}
                                for x in compose.call_args_list))
            self.assertTrue(any(x.kwargs=={"verify_active_candidate":True}
                                for x in compose.call_args_list))
            recovered.assert_called_once_with(
                expected_identity=retained,require_replay=True,
                review_unified_trial=True)
            self.assertFalse(modes["signed"])
            self.assertEqual(sum("up" in args for args in commands),2)

    def test_rc7_activation_post_apply_compose_drift_triggers_verified_rollback(self):
        state = {
            "SMITE_ROLE": "foreign", "SMITE_MANAGED_VERSION": "2.0.0-rc.7",
            "SMITE_CONNECTION_MODE": "standard", "SMITE_NODE_NAME": "node-kh",
        }
        retained = ("node-12345678", "a" * 64)
        observed = {"phase": "base", "drift": True, "probes": 0}
        calls = []
        def compose(*, staged_candidate=False, rollback=False,
                    verify_active_candidate=False):
            calls.append(("compose", staged_candidate, rollback,
                          verify_active_candidate))
            if verify_active_candidate and observed["drift"]:
                raise p.WizardHold("Foreign signed candidate Compose was not actually applied")
            return ["docker", "compose", "--project-name", "existing"]
        def run(args, **kwargs):
            calls.append(("run", args))
            if args[-2:] == ["config", "--quiet"]:
                return ""
            if "up" in args:
                observed["phase"] = "paused" if observed["phase"] == "signed" else "signed"
                return ""
            if args[:3] == ["docker", "inspect", "-f"] and \
                    "{{range .Config.Env}}" in args[3]:
                observed["probes"] += 1
                return ("SMITE_NODE_PANEL_AUTH_MODE=" + observed["phase"] + "\n"
                        "SMITE_AGENT_AUTH_MODE=strict\n"
                        "SMITE_ENGINE_INVENTORY_MODE=managed\n")
            raise AssertionError("unanticipated tool call: " + str(args))
        with patch.object(p, "_field_trial_gate"), \
             patch.object(p, "_require_no_active_engine_overlays"), \
             patch.object(p, "_foreign_gateway_preflight",
                          return_value=("iran.example.org", "kh.example.org",
                                        "https://kh.example.org/smite-node/"+"a"*32)), \
             patch.object(p, "_rc7_foreign_compose_command", side_effect=compose), \
             patch.object(p, "_rc7_foreign_pinned_image_verified"), \
             patch.object(p, "_identity_record", return_value=retained), \
             patch.object(p, "_regular", return_value=b"owned"), \
             patch.object(p, "_prepare_security_candidate"), \
             patch.object(p, "_provision_replay_once"), \
             patch.object(p, "_run", side_effect=run), \
             patch.object(p, "_wait_container"), \
             patch.object(p, "_local_signed_replay_probe") as replay_probe, \
             patch.object(p, "_rc7_foreign_paused_rollback_verified") as rollback_witness:
            with self.assertRaisesRegex(p.WizardHold, "paused again"):
                p.activate_foreign_node_field_trial(state)
            replay_probe.assert_not_called()
            rollback_witness.assert_called_once_with(
                expected_identity=retained, require_replay=True)
        self.assertIn(("compose", False, False, True), calls)
        self.assertEqual(observed["probes"], 1)
        self.assertEqual(observed["phase"], "paused")
        self.assertEqual(sum("up" in x[1] for x in calls if x[0] == "run"), 2)

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
