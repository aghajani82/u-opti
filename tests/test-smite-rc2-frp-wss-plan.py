#!/usr/bin/env python3
"""Offline tests for RC2 signed FRP WSS preservation planner."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import json

SRC = Path(__file__).resolve().parents[1] / "modules/smite-rc2-frp-wss-plan.py"
spec = importlib.util.spec_from_file_location("rc2_frp_wss_plan", SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

IMAGE = "ghcr.io/aghajani82/smite-node@sha256:" + "a"*64
BACKEND = (
    "# Managed by U-OPTI - Smite Panel TLS backend\n"
    "server {\n"
    "    listen 127.0.0.1:8443 ssl;\n"
    "    server_name ir.kolbe1.ir;\n"
    "    location = /some/previous/route {\n"
    "        proxy_pass http://127.0.0.1:32555;\n"
    "    }\n"
    "    location / {\n"
    "        proxy_pass http://127.0.0.1:8000;\n"
    "    }\n"
    "}\n"
)
SIGNED = {
    "SMITE_AGENT_AUTH_MODE": "strict",
    "SMITE_NODE_PANEL_AUTH_MODE": "signed",
    "SMITE_ENGINE_INVENTORY_MODE": "managed",
    "PANEL_ADDRESS": "ir.kolbe1.ir:443",
}

def current():
    env = [f"{k}={v}" for k,v in SIGNED.items()]
    return {
        "Config": {"Image": IMAGE, "Env": env},
        "State": {"Running": True},
        "Mounts": [
            {"Destination": "/etc/smite-node"},
            {"Destination": "/run/smite-node-identity"},
            {"Destination": "/var/lib/smite-node/auth"},
        ],
    }

def effective():
    env = dict(SIGNED, SMITE_FRP_STANDARD_WSS="1")
    return {"services": {"smite-node": {
        "image": IMAGE, "network_mode": "host",
        "command": ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"],
        "environment": env,
        "volumes": [
            {"target": "/etc/smite-node"},
            {"target": "/run/smite-node-identity"},
            {"target": "/var/lib/smite-node/auth"},
        ]
    }}}


class CandidateSecurity(unittest.TestCase):
    def test_preserves_existing_panel_and_custom_locations(self):
        updated = mod.render_backend(BACKEND)
        self.assertIn("location = /some/previous/route", updated)
        self.assertEqual(updated.count("location / {"), 1)
        self.assertEqual(updated.count("location = /~!frp {"), 1)
        self.assertEqual(updated.count("proxy_pass http://127.0.0.1:7000;"), 1)
        self.assertIn("proxy_set_header Upgrade $http_upgrade", updated)
        self.assertEqual(updated.replace(
            updated[updated.index("    # BEGIN U-OPTI RC2 FRP WSS CANDIDATE"):
                    updated.index("    # END U-OPTI RC2 FRP WSS CANDIDATE") +
                    len("    # END U-OPTI RC2 FRP WSS CANDIDATE\n\n")],
            ""), BACKEND)

    def test_rejects_unmanaged_or_different_panel_domain(self):
        for source in (BACKEND.replace("# Managed by U-OPTI", "# Unmanaged"),
                       BACKEND.replace("ir.kolbe1.ir", "other.example.com")):
            with self.subTest(source=source[:50]):
                with self.assertRaises(mod.Hold):
                    mod.render_backend(source)

    def test_rejects_duplicate_wss_location(self):
        with self.assertRaisesRegex(mod.Hold, "EXISTING_FRP_LOCATION"):
            mod.render_backend(BACKEND.replace("    location / {",
                "    location = /~!frp {\n        return 200;\n    }\n    location / {"))

    def test_explicit_signed_mounts_and_env_preserved(self):
        mod.validate_preview(current(), effective(), IMAGE)

    def test_missing_identity_or_replay_mount_is_denied(self):
        for path in ("/run/smite-node-identity", "/var/lib/smite-node/auth"):
            e=effective()
            e["services"]["smite-node"]["volumes"]=[
                v for v in e["services"]["smite-node"]["volumes"]
                if v["target"]!=path]
            with self.subTest(path=path):
                with self.assertRaisesRegex(mod.Hold, "SIGNED_MOUNTS_NOT_PRESERVED"):
                    mod.validate_preview(current(),e,IMAGE)

    def test_unsigned_or_legacy_policy_fails_closed(self):
        for key in mod.MANDATORY:
            e=effective()
            e["services"]["smite-node"]["environment"][key]="legacy"
            with self.subTest(key=key):
                with self.assertRaisesRegex(mod.Hold, "SIGNED_AUTH_NOT_PRESERVED"):
                    mod.validate_preview(current(),e,IMAGE)

    def test_non_443_panel_address_blocks(self):
        e=effective()
        e["services"]["smite-node"]["environment"]["PANEL_ADDRESS"]="ir.kolbe1.ir:7000"
        with self.assertRaisesRegex(mod.Hold, "443_PANEL_ADDRESS_REQUIRED"):
            mod.validate_preview(current(),e,IMAGE)

    def test_node_network_or_bind_port_cannot_expand(self):
        e=effective()
        e["services"]["smite-node"]["network_mode"]="bridge"
        with self.assertRaisesRegex(mod.Hold, "NETWORK_MODE_CHANGED"):
            mod.validate_preview(current(),e,IMAGE)
        e=effective()
        e["services"]["smite-node"]["command"]=["uvicorn","main:app","--host","0.0.0.0","--port","8888"]
        with self.assertRaisesRegex(mod.Hold, "SIGNED_AGENT_LOCAL_BIND_LOST"):
            mod.validate_preview(current(),e,IMAGE)

    def test_wss_must_be_off_in_current_and_on_in_preview(self):
        c=current()
        c["Config"]["Env"].append("SMITE_FRP_STANDARD_WSS=1")
        with self.assertRaises(mod.Hold):
            mod.validate_preview(c,effective(),IMAGE)
        e=effective()
        del e["services"]["smite-node"]["environment"]["SMITE_FRP_STANDARD_WSS"]
        with self.assertRaises(mod.Hold):
            mod.validate_preview(current(),e,IMAGE)

    def test_no_live_writes_nor_nginx_reload(self):
        source=SRC.read_text()
        for bad in ("--force-recreate", "systemctl reload", "nginx -s reload",
                    "mkdir(", "write_text(", "os.replace(", "unlink(", "iptables ",
                    "ufw ", "/api/agent/tunnels/apply"):
            self.assertNotIn(bad,source)
        self.assertIn('"REAL_KH_SOURCE_ACL=NOT_ESTABLISHED"', source)
        self.assertEqual(mod.OVERLAY.count("SMITE_FRP_STANDARD_WSS=1"),1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
