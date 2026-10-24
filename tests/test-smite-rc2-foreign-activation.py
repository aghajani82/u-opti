#!/usr/bin/env python3
"""Offline fail-closed regression tests for separate RC.2 foreign activation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "modules/smite-node-pairing.py"
spec = importlib.util.spec_from_file_location("uopti_signed_pairing_rc2", SOURCE)
pairing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pairing)

CURRENT = {
    "SMITE_ROLE": "foreign",
    "SMITE_CONNECTION_MODE": "standard",
    "SMITE_MANAGED_VERSION": "2.0.0-rc.1",
    "SMITE_NODE_NAME": "node-kh",
    "SMITE_PANEL_DOMAIN": "ir.kolbe1.ir",
}
GATEWAY = "https://kh.kolbe1.ir/smite-node/0123456789abcdef"
ADMITTED = (
    "RC2_FOREIGN_PAIRING_ADMISSION=PASS_READ_ONLY\n"
    "FOREIGN_PAIRING=NOT_ACTIVATED\n"
    "LIVE_CHANGES=NONE"
)


class RC2ActivationTests(unittest.TestCase):
    def test_rc2_image_not_accepted_in_original_rc1_lane(self):
        with patch.object(pairing, "_field_trial_gate"), \
             patch.object(pairing, "_foreign_gateway_preflight", side_effect=pairing.WizardHold("RC1 baseline mismatch")) as preflight, \
             patch.object(pairing, "_prepare_security_candidate") as stage:
            with self.assertRaisesRegex(pairing.WizardHold, "RC1 baseline"):
                pairing.activate_foreign_node_field_trial(dict(CURRENT))
            preflight.assert_called_once_with(CURRENT)
            stage.assert_not_called()

    def test_rc2_cannot_activate_without_separate_explicit_optin(self):
        with patch.object(pairing, "_field_trial_gate"), \
             patch.dict(os.environ, {"UOPTI_SMITE_RC2_FOREIGN_PAIRING_FIELD_TRIAL": "NO"}), \
             patch.object(pairing, "_foreign_gateway_preflight") as preflight, \
             patch.object(pairing, "_prepare_security_candidate") as stage:
            with self.assertRaisesRegex(pairing.WizardHold, "consent missing"):
                pairing.activate_foreign_node_field_trial(dict(CURRENT), reviewed_rc2=True)
            preflight.assert_not_called()
            stage.assert_not_called()

    def test_rc2_rejected_when_admission_absent(self):
        with patch.object(pairing, "_field_trial_gate"), \
             patch.dict(os.environ, {"UOPTI_SMITE_RC2_FOREIGN_PAIRING_FIELD_TRIAL": "YES"}), \
             patch.object(pairing.Path, "is_file", return_value=False), \
             patch.object(pairing, "_foreign_gateway_preflight") as preflight:
            with self.assertRaisesRegex(pairing.WizardHold, "module unavailable"):
                pairing.activate_foreign_node_field_trial(dict(CURRENT), reviewed_rc2=True)
            preflight.assert_not_called()

    def test_rc2_rejected_before_runtime_mutation_if_admission_holds(self):
        with patch.object(pairing, "_field_trial_gate"), \
             patch.dict(os.environ, {"UOPTI_SMITE_RC2_FOREIGN_PAIRING_FIELD_TRIAL": "YES"}), \
             patch.object(pairing.Path, "is_file", return_value=True), \
             patch.object(pairing.Path, "is_symlink", return_value=False), \
             patch.object(pairing, "_regular", return_value=b"reviewed"), \
             patch.object(pairing, "_run", return_value="RC2_FOREIGN_PAIRING_ADMISSION=HOLD") as runner, \
             patch.object(pairing, "_prepare_security_candidate") as stage:
            with self.assertRaisesRegex(pairing.WizardHold, "admission failed"):
                pairing.activate_foreign_node_field_trial(dict(CURRENT), reviewed_rc2=True)
            self.assertEqual(len(runner.call_args_list), 1)
            stage.assert_not_called()

    def test_rc2_good_lane_does_not_mutate_other_containers(self):
        calls = []
        runtime_signed = [False]
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:2] == ["python3", "-B"]:
                if "--role" in cmd:
                    return ADMITTED
                return ""
            if cmd[:2] == ["docker", "compose"]:
                if "up" in cmd:
                    runtime_signed[0] = True
                return ""
            if cmd[:2] == ["docker", "inspect"]:
                return "\n".join([
                    "SMITE_NODE_PANEL_AUTH_MODE=signed" if runtime_signed[0]
                    else "SMITE_NODE_PANEL_AUTH_MODE=paused",
                    "SMITE_AGENT_AUTH_MODE=strict",
                    "SMITE_ENGINE_INVENTORY_MODE=managed",
                ])
            raise AssertionError(repr(cmd))
        with patch.object(pairing, "_field_trial_gate"), \
             patch.dict(os.environ, {"UOPTI_SMITE_RC2_FOREIGN_PAIRING_FIELD_TRIAL": "YES"}), \
             patch.object(pairing.Path, "is_file", return_value=True), \
             patch.object(pairing.Path, "is_symlink", return_value=False), \
             patch.object(pairing, "_foreign_gateway_preflight",
                          return_value=(CURRENT["SMITE_PANEL_DOMAIN"], "kh.kolbe1.ir", GATEWAY)) as preflight, \
             patch.object(pairing, "_identity_record", return_value=("node-abcdefgh", b"x"*64)), \
             patch.object(pairing, "_regular", return_value=b"reviewed"), \
             patch.object(pairing, "_prepare_security_candidate") as stage, \
             patch.object(pairing, "_provision_replay_once") as replay, \
             patch.object(pairing, "_wait_container"), \
             patch.object(pairing, "_local_signed_replay_probe") as signed_hmac, \
             patch.object(pairing, "_run", side_effect=fake_run):
            pairing.activate_foreign_node_field_trial(dict(CURRENT), reviewed_rc2=True)
        self.assertTrue(runtime_signed[0])
        preflight.assert_called_once_with(CURRENT, expected_image=pairing._FOREIGN_NODE_IMAGE_RC2)
        stage.assert_called_once()
        replay.assert_called_once()
        signed_hmac.assert_called_once()
        recreates = [c for c in calls if c[:2] == ["docker", "compose"] and "up" in c]
        self.assertEqual(len(recreates), 1)
        self.assertIn("--no-deps", recreates[0])
        self.assertIn("--pull", recreates[0])
        self.assertEqual(recreates[0][-1], "smite-node")
        self.assertFalse(any("smite-panel" in c or "3xui-01" in c for c in recreates))

    def test_rc2_node_preflight_exact_compose_and_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gateway = root / "foreign-gateway.env"
            gateway.write_text(
                "SMITE_FOREIGN_GATEWAY_DOMAIN=kh.kolbe1.ir\n"
                "SMITE_FOREIGN_PANEL_DOMAIN=ir.kolbe1.ir\n"
                "SMITE_FOREIGN_PANEL_SOURCE_IPV4=198.51.100.11\n"
                "SMITE_FOREIGN_CONTROL_PATH=/smite-node/0123456789abcdef\n"
                "SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443\n"
                "SMITE_FOREIGN_GATEWAY_MODE=https-control-path\n"
            )
            gateway.chmod(0o600)
            node_dir = root / "node"
            node_dir.mkdir()
            env = node_dir / ".env"
            env.write_text(
                "SMITE_NODE_PANEL_AUTH_MODE=paused\n"
                "SMITE_AGENT_AUTH_MODE=strict\n"
                "SMITE_ENGINE_INVENTORY_MODE=managed\n"
                "PANEL_ADDRESS=ir.kolbe1.ir:443\n"
                f"SMITE_CONTROL_ADDRESS={GATEWAY}\n"
            )
            env.chmod(0o600)
            compose = node_dir / "docker-compose.yml"
            compose.write_bytes(b"reviewed-original-compose")
            conf = json.dumps({
                "services": {"smite-node": {
                    "image": pairing._FOREIGN_NODE_IMAGE_RC2,
                    "network_mode": "host",
                    "environment": {
                        "SMITE_NODE_PANEL_AUTH_MODE": "paused",
                        "SMITE_AGENT_AUTH_MODE": "strict",
                        "SMITE_ENGINE_INVENTORY_MODE": "managed",
                    }
                }}
            })
            selected_image = [pairing._FOREIGN_NODE_IMAGE_RC2]
            def runtime(args, **_):
                if args[:2] == ["docker", "inspect"]:
                    return "healthy" if "{{.State.Health.Status}}" in args else selected_image[0]
                if args[:2] == ["docker", "compose"]:
                    return conf
                if args[0] == "curl":
                    return '{"status":"ok","service":"smite-node"}'
                raise AssertionError(args)
            good_sha = hashlib.sha256(compose.read_bytes()).hexdigest()
            with patch.object(pairing, "STATE", root / "state.env"), \
                 patch.object(pairing, "NODE_DIR", node_dir), \
                 patch.object(pairing, "NODE_COMPOSE", compose), \
                 patch.object(pairing, "_FOREIGN_RC2_COMPOSE_SHA", good_sha), \
                 patch.object(pairing, "_run", side_effect=runtime):
                self.assertEqual(
                    pairing._foreign_gateway_preflight(
                        dict(CURRENT), expected_image=pairing._FOREIGN_NODE_IMAGE_RC2),
                    ("ir.kolbe1.ir", "kh.kolbe1.ir", GATEWAY)
                )
                selected_image[0] = pairing._FOREIGN_NODE_IMAGE
                with self.assertRaisesRegex(pairing.WizardHold, "digest"):
                    pairing._foreign_gateway_preflight(
                        dict(CURRENT), expected_image=pairing._FOREIGN_NODE_IMAGE_RC2)
                selected_image[0] = pairing._FOREIGN_NODE_IMAGE_RC2
                compose.write_bytes(b"unreviewed-compose")
                with self.assertRaisesRegex(pairing.WizardHold, "Compose SHA256"):
                    pairing._foreign_gateway_preflight(
                        dict(CURRENT), expected_image=pairing._FOREIGN_NODE_IMAGE_RC2)

    def test_ir_approval_exact_rc2_panel_digest_required(self):
        for image in (
            "ghcr.io/aghajani82/smite-panel@sha256:" + "a"*64,
            pairing._FOREIGN_NODE_IMAGE_RC2,
        ):
            with patch.object(pairing, "_run", return_value=image) as runner:
                with self.assertRaisesRegex(pairing.WizardHold, "exact reviewed"):
                    pairing._require_panel_foreign_transport()
                runner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
