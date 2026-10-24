#!/usr/bin/env python3
"""Offline behavioral tests for inert mixed-version foreign signing admission."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "modules/smite-rc2-foreign-pairing-admission.py"
spec = importlib.util.spec_from_file_location("rc2_foreign_pairing_admission", PATH)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class Fixture:
    def __init__(self, role: str):
        self.role = role
        self.calls = []
        self.state = {
            "SMITE_ROLE": "panel-iran" if role == "IR" else "foreign",
            "SMITE_CONNECTION_MODE": "standard",
            "SMITE_PANEL_DOMAIN": p.IR_DOMAIN,
            "SMITE_MANAGED_VERSION": "2.0.0-rc.1",
        }
        self.gateway = {
            "SMITE_FOREIGN_GATEWAY_DOMAIN": p.KH_DOMAIN,
            "SMITE_FOREIGN_PANEL_DOMAIN": p.IR_DOMAIN,
            "SMITE_FOREIGN_GATEWAY_PUBLIC_PORT": "443",
            "SMITE_FOREIGN_GATEWAY_MODE": "https-control-path",
            "SMITE_FOREIGN_PANEL_SOURCE_IPV4": "198.51.100.12",
            "SMITE_FOREIGN_CONTROL_PATH": "/smite-node/0123456789abcdef",
        }
        self.node_env = dict(p.SECURITY)
        self.node_env["PANEL_ADDRESS"] = p.IR_DOMAIN + ":443"
        self.node_env["SMITE_CONTROL_ADDRESS"] = (
            "https://" + p.KH_DOMAIN + self.gateway["SMITE_FOREIGN_CONTROL_PATH"]
        )
        self.config = {
            "services": {
                "smite-panel": {
                    "image": p.PANEL_IMAGE,
                    "network_mode": "host",
                    "environment": {
                        "SMITE_NODE_REGISTRATION_MODE": "signed",
                        "SMITE_PANEL_AGENT_AUTH_MODE": "signed",
                        "SMITE_NODE_PAIRING_PREVIEW_ENABLED": "true",
                        "SMITE_SIGNED_NODE_ORIGINS_PATH":
                            "/etc/smite-panel/trusted-nodes/approved-origins.json",
                    },
                    "volumes": [{
                        "target": "/etc/smite-panel/trusted-nodes",
                        "source": "/etc/u-opti/smite/panel-trusted-nodes",
                        "read_only": True,
                    }],
                },
                "smite-node": {
                    "image": p.KH_NODE_IMAGE,
                    "network_mode": "host",
                    "environment": dict(p.SECURITY),
                },
            }
        }

    @staticmethod
    def env_bytes(values):
        return ("\n".join(k + "=" + v for k, v in values.items()) + "\n").encode()

    def read(self, path, *, private=False, limit=262144):
        if path == p.STATE:
            return self.env_bytes(self.state)
        if path == p.GATEWAY:
            if not private:
                raise AssertionError("Gateway must be read as a private file")
            return self.env_bytes(self.gateway)
        if path == p.KH_ENV:
            if not private:
                raise AssertionError("Node environment must be read as private")
            return self.env_bytes(self.node_env)
        if path in (p.IR_COMPOSE, p.IR_OVERLAY, p.KH_COMPOSE):
            return b"reviewed-compose-placeholder"
        raise AssertionError("Unplanned file read " + repr(path))

    def execute(self, args, *, timeout=30):
        self.calls.append(tuple(args))
        if args[:2] == ["docker", "compose"]:
            return json.dumps(self.config)
        if args[:2] == ["docker", "inspect"]:
            what, name = args[3], args[4]
            if what == "{{.Config.Image}}":
                return {"smite-panel": p.PANEL_IMAGE,
                        "smite-node": p.IR_NODE_IMAGE if self.role == "IR"
                        else p.KH_NODE_IMAGE}[name]
            if what == "{{.State.Health.Status}}":
                return "healthy"
            if what == "{{.Image}}":
                return p.SANAEI_IMAGE
            if what == "{{.State.Status}}":
                return "running"
            if what.startswith("{{range .Config.Env}}"):
                return "\n".join(k + "=" + v for k,v in p.SECURITY.items())
            raise AssertionError("Unexpected docker inspection " + repr(args))
        if args[:2] == ["docker", "exec"]:
            if args[2:4] != ["smite-panel", "python3"]:
                raise AssertionError("Unexpected exec")
            return "PANEL_FOREIGN_TRANSPORT=PASS"
        if args[0] == "nginx":
            return ""
        if args[0] == "ss":
            return "LISTEN 0 4096 127.0.0.1:8888 0.0.0.0:*"
        if args[0] == "python3":
            return "XHTTP_REVIEW=PASS ROUTES=1 LEGACY_ROUTE=NO"
        if args[0] == "curl":
            if "--resolve" in args:
                return json.dumps({"status": "ok", "service": "smite-node"})
            return "200"
        raise AssertionError("Unexpected command " + repr(args))

    def run(self):
        with patch.object(p.hashlib, "sha256", wraps=hashlib.sha256) as sha:
            original_sha = hashlib.sha256(b"reviewed-compose-placeholder").hexdigest()
            with patch.object(p, "IR_COMPOSE_SHA", original_sha), \
                 patch.object(p, "IR_OVERLAY_SHA", original_sha), \
                 patch.object(p, "KH_COMPOSE_SHA", original_sha):
                result = (p.admit_ir(read=self.read, execute=self.execute)
                          if self.role == "IR" else
                          p.admit_kh(read=self.read, execute=self.execute))
        if any(x in repr(self.calls) for x in ("--force-recreate", "docker pull", "docker restart")):
            raise AssertionError("Unexpected mutating command")
        return result


class AdmissionTests(unittest.TestCase):
    def test_ir_current_mixed_signed_runtime_admitted(self):
        f = Fixture("IR")
        result = f.run()
        self.assertIn("IR_FOREIGN_PATH_HMAC_POLICY=PASS", result)
        self.assertNotIn("KH_FOREIGN_SIGNED_RUNTIME=NOT_ACTIVATED", result)

    def test_kh_current_paused_signed_gateway_admitted(self):
        f = Fixture("KH")
        result = f.run()
        self.assertIn("KH_FOREIGN_SIGNED_RUNTIME=NOT_ACTIVATED", result)

    def test_ir_unsigned_panel_refused(self):
        f = Fixture("IR")
        f.config["services"]["smite-panel"]["environment"]["SMITE_PANEL_AGENT_AUTH_MODE"] = "legacy"
        with self.assertRaisesRegex(p.Hold, "IR_SIGNED_ENV_DRIFT"):
            f.run()

    def test_ir_trust_mount_must_be_readonly(self):
        f = Fixture("IR")
        f.config["services"]["smite-panel"]["volumes"][0]["read_only"] = False
        with self.assertRaisesRegex(p.Hold, "IR_APPROVED_ORIGINS_MOUNT_DRIFT"):
            f.run()

    def test_kh_unpaused_auth_refused(self):
        f = Fixture("KH")
        f.node_env["SMITE_NODE_PANEL_AUTH_MODE"] = "signed"
        with self.assertRaisesRegex(p.Hold, "KH_PAUSED_CONTROL_DRIFT"):
            f.run()

    def test_kh_suspicious_control_prefix_refused(self):
        f = Fixture("KH")
        f.gateway["SMITE_FOREIGN_CONTROL_PATH"] += "?token=never"
        with self.assertRaisesRegex(p.Hold, "KH_GATEWAY_PREFIX_UNSAFE"):
            f.run()

    def test_kh_state_version_drift_refused(self):
        f = Fixture("KH")
        f.state["SMITE_MANAGED_VERSION"] = "2.0.0-rc.2"
        with self.assertRaisesRegex(p.Hold, "KH_MIXED_VERSION_STATE_DRIFT"):
            f.run()

    def test_duplicate_env_key_refused(self):
        with self.assertRaisesRegex(p.Hold, "INVALID_OR_DUPLICATE_ENV"):
            p.env_map(b"SMITE_ROLE=foreign\nSMITE_ROLE=foreign\n")

    def test_kh_wrong_sanaei_image_refused(self):
        f = Fixture("KH")
        original = f.execute
        def tamper(args, *, timeout=30):
            if args[:2] == ["docker", "inspect"] and args[3] == "{{.Image}}":
                return "sha256:unreviewed"
            return original(args, timeout=timeout)
        f.execute = tamper
        with self.assertRaisesRegex(p.Hold, "KH_SANAEI_IMAGE_DRIFT"):
            f.run()

    def test_only_role_arg_exposed_no_apply_option(self):
        with self.assertRaises(SystemExit) as context:
            p.main(["--role", "KH", "--apply"])
        self.assertEqual(context.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
