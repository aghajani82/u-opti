"""Exact Panel-issued Gateway scope; no credential logging or host writes."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "uopti_unified_gateway_scope_test",
    ROOT / "modules" / "smite-unified-foreign-gateway-plan.py")
gateway = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gateway
spec.loader.exec_module(gateway)

NODE = "foreign-node-A01"
PANEL = "iran.example.org"
FOREIGN = "kh.example.org"
PATH = "/smite-node/" + "a"*32
CODE = "smi1_" + "B"*43


class GatewayScope(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "etc/u-opti/smite/state.env"
        self.packet = self.root / "etc/u-opti/smite/foreign-install-staging/foreign-install-packet.json"
        self.status = self.root / "etc/u-opti/smite/foreign-gateway.env"
        self.site = self.root / "etc/nginx/sites-available/3xui-kh.example.org"
        self.state.parent.mkdir(parents=True)
        self.packet.parent.mkdir(mode=0o700)
        self.site.parent.mkdir(parents=True)
        self.write(self.state, (
            "SMITE_ROLE=foreign\n"
            "SMITE_MANAGED_VERSION=2.0.0-rc.7\n"
            "SMITE_CONNECTION_MODE=standard\n"
            "SMITE_PANEL_DOMAIN=" + PANEL + "\n"
            "SMITE_FOREIGN_DOMAIN=" + FOREIGN + "\n"
            "SMITE_NODE_NAME=" + NODE + "\n").encode())
        self.scope = {
            "protocol":"smi1",
            "panel_url":"https://"+PANEL+":443",
            "node_id":"f" * 8 + "0001",
            "node_name":NODE,
            "origin":"https://"+FOREIGN+":443",
            "control_url":"https://"+FOREIGN+":443"+PATH,
            "installation_code":CODE,
            "expires_at":1799999999,
        }
        self.save_packet()

    def write(self,p,data,mode=0o600):
        p.write_bytes(data)
        p.chmod(mode)

    def save_packet(self):
        self.write(self.packet,json.dumps(self.scope).encode())

    def admit(self):
        return gateway.admit(
            packet_path=self.packet, state_path=self.state,
            gateway_state_path=self.status, site_path=self.site)

    def test_exact_panel_issued_path_no_random_replacement(self):
        self.assertEqual(self.admit(),PATH)
        self.assertFalse(self.status.exists())
        self.assertFalse(self.site.exists())

    def test_valid_shared_sanaei_site_existing_managed_location(self):
        self.write(self.site,(
            "# U-OPTI-MANAGED-3XUI-NGINX\n"
            "server {\n listen 443 ssl;\n server_name "+FOREIGN+";\n"
            "location = /frp { proxy_pass http://127.0.0.1:7000; }\n"
            "location ^~ "+PATH+"/ { proxy_pass http://127.0.0.1:8888/; }\n"
            "# BEGIN U-OPTI SMITE FOREIGN CONTROL\n"
            "# END U-OPTI SMITE FOREIGN CONTROL\n}\n").encode(),mode=0o644)
        original=self.site.read_bytes()
        self.assertEqual(self.admit(),PATH)
        self.assertEqual(self.site.read_bytes(),original)

    def test_old_random_or_mismatched_gateway_path_refused(self):
        self.write(self.site,("location ^~ /smite-node/"+"b"*16+
                              "/ { proxy_pass http://127.0.0.1:8888/; }\n").encode(),mode=0o644)
        with self.assertRaises(gateway.Hold):self.admit()

    def test_gateway_state_must_preserve_exact_one_use_path(self):
        lines=[
            "SMITE_FOREIGN_GATEWAY_DOMAIN="+FOREIGN,
            "SMITE_FOREIGN_PANEL_DOMAIN="+PANEL,
            "SMITE_FOREIGN_CONTROL_PATH="+PATH,
            "SMITE_FOREIGN_GATEWAY_MODE=https-control-path",
            "SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443",
        ]
        self.write(self.status,("\n".join(lines)+"\n").encode())
        self.assertEqual(self.admit(),PATH)
        self.write(self.status,("\n".join(lines).replace(PATH,"/smite-node/"+"e"*32)+"\n").encode())
        with self.assertRaises(gateway.Hold):self.admit()

    def test_wrong_node_domain_role_transport_version_refused(self):
        for key, value in (
                ("node_name","wrong-node"),
                ("panel_url","https://other.example.org:443"),
                ("origin","https://other.example.org:443"),
                ("control_url","https://other.example.org:443"+PATH),
                ("control_url","https://"+FOREIGN+":443/smite-node/"+"d"*16),
                ("protocol","smn1")):
            original=self.scope[key]
            self.scope[key]=value
            self.save_packet()
            with self.subTest(key=key,value=value),self.assertRaises(gateway.Hold):
                self.admit()
            self.scope[key]=original
        self.save_packet()
        before=self.state.read_bytes()
        for old,new in (
                (b"SMITE_ROLE=foreign",b"SMITE_ROLE=panel-iran"),
                (b"SMITE_CONNECTION_MODE=standard",b"SMITE_CONNECTION_MODE=private"),
                (b"SMITE_MANAGED_VERSION=2.0.0-rc.7",b"SMITE_MANAGED_VERSION=2.0.0-rc.6"),
                (NODE.encode(),b"other-node")):
            self.write(self.state,before.replace(old,new))
            with self.subTest(old=old),self.assertRaises(gateway.Hold):self.admit()
        self.write(self.state,before)

    def test_secret_file_requirements_and_symlink_rejected(self):
        self.packet.chmod(0o644)
        with self.assertRaises(gateway.Hold):self.admit()
        self.packet.chmod(0o600)
        self.packet.parent.chmod(0o755)
        with self.assertRaises(gateway.Hold):self.admit()
        self.packet.parent.chmod(0o700)
        raw=self.packet.read_bytes()
        self.packet.unlink()
        self.packet.symlink_to(self.state)
        with self.assertRaises(gateway.Hold):self.admit()
        self.packet.unlink()
        self.write(self.packet,raw)
        os.link(self.packet,self.root/"hardlink-packet")
        with self.assertRaises(gateway.Hold):self.admit()

    def test_duplicate_json_and_drifted_site_markers_refused(self):
        self.write(self.packet,
                   json.dumps(self.scope)[:-1].encode() +
                   b', "installation_code":"smi1_DUPLICATE"}')
        with self.assertRaises(gateway.Hold):self.admit()
        self.save_packet()
        self.write(self.site,b"# BEGIN U-OPTI SMITE FOREIGN CONTROL\n",mode=0o644)
        with self.assertRaises(gateway.Hold):self.admit()

    def test_no_code_or_secret_exposed_on_failure(self):
        self.scope["control_url"]="http://"+FOREIGN+PATH
        self.save_packet()
        with patch("sys.stderr") as sink:
            self.assertEqual(gateway.main([
                "--packet-file",str(self.packet),"--state-file",str(self.state),
                "--gateway-state-file",str(self.status),"--site-file",str(self.site)]),2)
            emitted=''.join(str(c) for call in sink.write.call_args_list for c in call.args)
        self.assertNotIn(CODE,emitted)
        self.assertNotIn("installation_code",emitted)

    def test_absent_packet_or_wrong_basename_refused(self):
        with self.assertRaises(gateway.Hold):
            gateway.admit(packet_path=self.state,state_path=self.state)
        self.packet.unlink()
        with self.assertRaises(gateway.Hold):self.admit()


if __name__=="__main__":
    unittest.main(verbosity=2)
