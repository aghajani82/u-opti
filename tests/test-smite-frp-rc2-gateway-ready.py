#!/usr/bin/env python3
"""Offline fail-closed contract tests for Standard Smite FRP/XHTTP RC2 gate."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"modules/smite-frp-rc2-gateway-ready.py"
ROUTES=ROOT/"modules/smite-frp-xhttp.sh"
spec=importlib.util.spec_from_file_location("rc2_gateway",PATH)
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class RC2GatewayContract(unittest.TestCase):
    def setUp(self):
        self.p={name:Path("/test")/name for name in (
            "state","backend","snippet","journal","overlay",
            "state_root","journal_dir"
        )}
        self.backend=("# Managed by U-OPTI - Smite Panel TLS backend\n"
                      "    server_name ir.kolbe1.ir;\n"
                      "    location = /~!frp {\n        proxy_pass http://127.0.0.1:7000;\n    }\n"
                      "    include /etc/nginx/u-opti-smite-frp-xhttp.conf;\n").encode()
        self.snippet=b"# Managed by U-OPTI - Standard FRP XHTTP\n"
        self.node={
            "Config":{
                "Image":gate.NODE_IMAGE,
                "Env":[
                    "SMITE_FRP_STANDARD_WSS=1",
                    "SMITE_NODE_PANEL_AUTH_MODE=signed",
                    "SMITE_AGENT_AUTH_MODE=strict",
                    "SMITE_ENGINE_INVENTORY_MODE=managed",
                    "PANEL_ADDRESS=ir.kolbe1.ir:443",
                ],
                "Labels":{
                    "com.docker.compose.project.config_files":",".join(sorted(gate.NODE_FILES)),
                    "com.docker.compose.service":"smite-node",
                },
            },
            "State":{"Running":True,"Health":{"Status":"healthy"}},
            "Mounts":[
                {"Destination":"/etc/smite-node","Source":"/opt/smite-node/config","RW":True},
                {"Destination":"/run/smite-node-identity","Source":"/run/identity","RW":False},
                {"Destination":"/var/lib/smite-node/auth","Source":"/var/lib/auth","RW":True},
            ],
        }
        self.journal={
            "schema":1,"host":"ir","state":"COMMITTED",
            "image":gate.NODE_IMAGE,
            "overlay_sha":hashlib.sha256(gate.WSS_OVERLAY).hexdigest(),
        }
        self.files={
            self.p["state"]:b"SMITE_CONNECTION_MODE=standard\n",
            self.p["backend"]:self.backend,
            self.p["snippet"]:self.snippet,
            self.p["journal"]:json.dumps(self.journal).encode(),
            self.p["overlay"]:gate.WSS_OVERLAY,
        }

    def check(self):
        with patch.object(gate,"read_root_file",side_effect=lambda path,**kw:self.files[path]), \
             patch.object(gate,"read_root_dir",return_value=None):
            gate.audit(self.p,self.node,enforce_host=False)

    def test_committed_signed_node_and_ir_gateway_pass(self):
        self.check()

    def test_legacy_gateway_file_not_fabricated(self):
        shell=ROUTES.read_text()
        self.assertIn('if [ -f "${SMITE_OVERLAY_DIR:-/opt/u-opti-smite}/node/frp_gateway_config.py" ]; then',shell)
        self.assertIn('python3 -B "$SMITE_FRP_RC2_READY_SCRIPT" >/dev/null',shell)
        self.assertIn('smite_frp_xhttp_stage_path()',shell)
        self.assertNotIn('touch "$SMITE_FRP_XHTTP_HELPER"',shell)

    def test_missing_standard_mode_holds(self):
        self.files[self.p["state"]]=b"SMITE_CONNECTION_MODE=private\n"
        with self.assertRaisesRegex(gate.GateHold,"STANDARD_FRP_STATE_MISSING"):
            self.check()

    def test_missing_commit_holds(self):
        self.journal["state"]="PREPARED"
        self.files[self.p["journal"]]=json.dumps(self.journal).encode()
        with self.assertRaisesRegex(gate.GateHold,"RC2_WSS_NOT_COMMITTED"):
            self.check()

    def test_wrong_wss_overlay_holds(self):
        self.files[self.p["overlay"]]=b"services: {}\n"
        with self.assertRaisesRegex(gate.GateHold,"RC2_WSS_OVERLAY_MISMATCH"):
            self.check()

    def test_wrong_signed_mode_holds(self):
        for expected,bad in [
            ("SMITE_FRP_STANDARD_WSS=1","SMITE_FRP_STANDARD_WSS=0"),
            ("SMITE_AGENT_AUTH_MODE=strict","SMITE_AGENT_AUTH_MODE=legacy"),
            ("SMITE_NODE_PANEL_AUTH_MODE=signed","SMITE_NODE_PANEL_AUTH_MODE=legacy"),
            ("PANEL_ADDRESS=ir.kolbe1.ir:443","PANEL_ADDRESS=bad.example:443"),
        ]:
            with self.subTest(expected=expected):
                self.node["Config"]["Env"]=[
                    bad if item==expected else item for item in self.node["Config"]["Env"]
                ]
                with self.assertRaisesRegex(gate.GateHold,"SIGNED_WSS_NODE_DRIFT"):
                    self.check()
                self.node["Config"]["Env"]=[
                    expected if item==bad else item for item in self.node["Config"]["Env"]
                ]

    def test_wrong_image_compose_mount_health_holds(self):
        for key,bad,code in [
            ("image","old-tag","NODE_IMAGE_DRIFT"),
            ("running",False,"NODE_NOT_HEALTHY"),
            ("composes","/opt/smite-node/docker-compose.yml","NODE_SIGNED_COMPOSE_DRIFT"),
            ("identity_rw",True,"NODE_SIGNED_MOUNTS_DRIFT"),
        ]:
            with self.subTest(case=key):
                before=copy.deepcopy(self.node)
                if key=="image":self.node["Config"]["Image"]=bad
                elif key=="running":self.node["State"]["Running"]=bad
                elif key=="composes":self.node["Config"]["Labels"]["com.docker.compose.project.config_files"]=bad
                else:self.node["Mounts"][1]["RW"]=bad
                with self.assertRaisesRegex(gate.GateHold,code):
                    self.check()
                self.node=before

    def test_wrong_backend_or_nginx_include_holds(self):
        for modified in (
            self.backend.replace(b"location = /~!frp {",b"location = /missing {"),
            self.backend.replace(b"    include /etc/nginx/u-opti-smite-frp-xhttp.conf;\n",b""),
            self.backend.replace(b"server_name ir.kolbe1.ir;",b"server_name other.example;"),
        ):
            self.files[self.p["backend"]]=modified
            with self.assertRaisesRegex(gate.GateHold,"IR_WSS_NGINX_BACKEND_DRIFT"):
                self.check()
        self.files[self.p["backend"]]=self.backend

    def test_snippet_header_holds(self):
        self.files[self.p["snippet"]]=b"# other managed\n"
        with self.assertRaisesRegex(gate.GateHold,"IR_XHTTP_SNIPPET_UNTRUSTED"):
            self.check()

    def test_strict_gate_requires_snippet_but_bootstrap_preflight_accepts_exact_absence(self):
        del self.files[self.p["snippet"]]
        with self.assertRaises(KeyError):
            self.check()
        # This tests the read-only preparation lane only, never published
        # routing; the production gate without the flag still refuses.
        with patch.object(gate, "read_root_file",
                          side_effect=lambda path, **kw: self.files[path]), \
             patch.object(gate, "read_root_dir", return_value=None):
            gate.audit(self.p, self.node, enforce_host=False,
                       allow_missing_snippet=True)

    def test_bootstrap_preflight_does_not_allow_bad_nginx_backend(self):
        del self.files[self.p["snippet"]]
        self.files[self.p["backend"]] = self.backend.replace(
            b"    include /etc/nginx/u-opti-smite-frp-xhttp.conf;\n", b"")
        with patch.object(gate, "read_root_file",
                          side_effect=lambda path, **kw: self.files[path]), \
             patch.object(gate, "read_root_dir", return_value=None):
            with self.assertRaisesRegex(gate.GateHold,"IR_WSS_NGINX_BACKEND_DRIFT"):
                gate.audit(self.p, self.node, enforce_host=False,
                           allow_missing_snippet=True)

    def test_missing_file_refuses_without_fallback(self):
        del self.files[self.p["journal"]]
        with self.assertRaises(KeyError):
            self.check()

    def test_no_restarts_or_token_logging(self):
        source=PATH.read_text()
        self.assertNotIn('"docker", "compose", "up"',source)
        self.assertNotIn("systemctl reload",source)
        self.assertNotIn("settings.get('token')",source)
        self.assertNotIn('PANEL_ADDRESS: "example.com"',source)


if __name__=="__main__":
    unittest.main(verbosity=2)
