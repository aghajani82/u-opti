#!/usr/bin/env python3
"""Real existing RC7 read-only witness composition, with isolated Docker fixtures.

Exercises actual immutable OIDC trial signature-admission code with injected
Cosign responses; uses an injected existing-pairing contract and tmpfs-like
on-disk mock, never Docker/Nginx services or host paths.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT/"modules"/file)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj

w = load("uopti_existing_witness_test", "smite-unified-foreign-existing-witnesses.py")
recovery = load("uopti_host_recovery_for_witness_test", "smite-unified-foreign-host-recovery.py")


class ForeignReadOnlyWitnesses(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.foreign = self.root/"foreign-fixture"
        self.stage = self.foreign/"foreign-staging"
        self.foreign.mkdir(mode=0o700)
        self.stage.mkdir(mode=0o700)
        self.node = self.root/"node"
        self.node.mkdir(mode=0o700)
        self.file = self.node/".env"
        self.state_root = self.root/"state"
        self.state_root.mkdir(mode=0o700)
        self.site = self.root/"sites"/"3xui-kh.example.com"
        self.site.parent.mkdir(mode=0o755)
        self.packet = self.stage/"foreign-install-packet.json"
        self.now=1850000000
        self.doc = {
            "protocol":"smi1", "panel_url":"https://panel.example.com:443",
            "node_id":"foreign-node-1234", "node_name":"node-kh",
            "origin":"https://kh.example.com:443",
            "control_url":"https://kh.example.com:443/smite-node/"+"a"*32,
            "installation_code":"smi1_"+"b"*43, "expires_at":self.now+7200,
        }
        self.packet.write_text(json.dumps(self.doc))
        self.packet.chmod(0o600)
        self.scope={k:self.doc[k] for k in (
            "panel_url","node_id","node_name","origin","control_url")}
        self.current={
            "SMITE_ROLE":"foreign", "SMITE_MANAGED_VERSION":"2.0.0-rc.7",
            "SMITE_CONNECTION_MODE":"standard",
            "SMITE_NODE_NAME":"node-kh",
            "SMITE_PANEL_DOMAIN":"panel.example.com",
            "SMITE_FOREIGN_DOMAIN":"kh.example.com",
        }
        self.env={
            "SMITE_NODE_PANEL_AUTH_MODE":"paused",
            "SMITE_AGENT_AUTH_MODE":"strict",
            "SMITE_ENGINE_INVENTORY_MODE":"managed",
            "PANEL_ADDRESS":"panel.example.com:443",
            "NODE_ROLE":"foreign", "NODE_NAME":"node-kh",
            "SMITE_SANAEI_INVENTORY_ENABLED":"false",
            "SMITE_SANAEI_DB_HOST_PATH":str(self.node/".sanaei-empty"),
        }
        self.container_env=dict(self.env)
        self.mount={
            "target":"/run/smite-sanaei-ro",
            "source":str(self.node/".sanaei-empty"),
            "read_only":True,
        }
        self.image=w.TRIAL_NODE
        self.id="sha256:"+"d"*64
        self.health="healthy"
        self.overlays=False
        self.db_ready=True
        self.local_443=True
        self.fail_signature=None
        self.calls=[]
        self.write_env()
        self.pair=SimpleNamespace(
            WizardHold=RuntimeError, NODE_DIR=self.node,
            STATE=self.state_root/"state.env",
            _FOREIGN_NODE_IMAGE_UNIFIED_TRIAL=w.TRIAL_NODE,
            state_values=lambda:self.current,
            _require_no_active_engine_overlays=self.check_overlays,
            _rc7_foreign_compose_command=lambda:["docker","compose",
                "--project-name","uopti_rc6_"+"a"*32,"-f",
                str(self.node/"docker-compose.yml")],
            _regular=self.regular,
            _env_map=self.env_map,
            _run=self.command,
            _foreign_gateway_preflight=self.gateway_preflight,
        )
        self.observer=w.bind_existing(pairing=self.pair,signature_runner=self.sign)

        # Keep all filesystem probes inside isolated fixture, while the
        # production binding selects its reviewed /etc Nginx site itself.
        self.observer.gateway_site=lambda scope:self.site
        self.observer.validate_db=self.validate_db

    def write_env(self):
        self.file.write_text("".join(f"{k}={v}\n" for k,v in self.env.items()))
        self.file.chmod(0o600)

    def regular(self, path, mode=None, limit=None):
        if path != self.file:raise RuntimeError("unexpected read")
        return path.read_bytes()

    def env_map(self, value):
        if isinstance(value,bytes):value=value.decode()
        return dict(x.split("=",1) for x in value.splitlines() if "=" in x)

    def check_overlays(self):
        self.calls.append("overlays")
        if self.overlays:raise RuntimeError("active signed override")

    def sign(self,args,**kwargs):
        self.calls.append("cosign")
        self.assertTrue(args[0].endswith("cosign"))
        role="panel" if "smite_role=panel" in args else "node"
        ref=w.TRIAL_PANEL if role=="panel" else w.TRIAL_NODE
        digest=ref.split("@",1)[1]
        if self.fail_signature=="denied":
            return subprocess.CompletedProcess(args,1,"","bad")
        if self.fail_signature=="wrong":
            digest="sha256:"+"e"*64
        result={
            "critical":{"type":"cosign container image signature",
                        "image":{"docker-manifest-digest":digest}},
            "optional":{"smite_source_sha":w.SOURCE,
                        "smite_role":role,"smite_trial":"unified-install"},
        }
        return subprocess.CompletedProcess(args,0,json.dumps([result]),"")

    def command(self,args,**kwargs):
        self.calls.append(" ".join(args[:4]))
        if args[-3:]==["config","--format","json"]:
            service={
                "image":self.image,"network_mode":"host",
                "cap_add":["NET_ADMIN","SYS_MODULE"],
                "devices":["/dev/net/tun:/dev/net/tun"],
                "command":["uvicorn","main:app","--host","127.0.0.1",
                           "--port","8888"],
                "environment":self.container_env,
                "volumes":[self.mount],
            }
            return json.dumps({"services":{"smite-node":service}})
        if args[:3]==["docker","exec","smite-node"]:
            if not self.db_ready:raise RuntimeError("RO DB schema invalid")
            self.assertIn("mode=ro",args[-1])
            self.assertIn("mountinfo",args[-1])
            return ""
        if args[:3]==["docker","image","inspect"]:
            return self.id
        if args[:2]==["docker","inspect"]:
            fmt=args[3]
            if fmt=="{{.Config.Image}}":return self.image
            if fmt=="{{.State.Health.Status}}":return self.health
            if fmt=="{{.Image}}":return self.id
            if fmt.startswith("{{range .Config.Env}}"):
                return "\n".join(k+"="+v for k,v in self.container_env.items())
        raise AssertionError("unexpected read-only command: "+repr(args))

    def validate_db(self,root,instance_id):
        self.calls.append("db")
        self.assertEqual(root,Path("/"))
        self.assertEqual(instance_id,"01")
        if not self.db_ready:raise RuntimeError("untrusted DB")
        return "/opt/3x-ui/instances/01/db"

    def gateway_preflight(self,state,**kwargs):
        self.calls.append("full_gateway")
        self.assertEqual(kwargs,{"review_unified_trial":True})
        if not self.local_443:raise RuntimeError("signed TLS 443 failed")
        return ("panel.example.com","kh.example.com",
                "https://kh.example.com"+self.scope["control_url"].split(".com:443",1)[1])

    def attach(self):
        self.env["SMITE_SANAEI_INVENTORY_ENABLED"]="true"
        self.env["SMITE_SANAEI_DB_HOST_PATH"]="/opt/3x-ui/instances/01/db"
        self.container_env.update(self.env)
        self.mount["source"]="/opt/3x-ui/instances/01/db"
        self.write_env()

    def serve_gateway(self):
        self.env["SMITE_CONTROL_ADDRESS"]="https://kh.example.com"+(
            self.scope["control_url"].split(".com:443",1)[1])
        self.container_env.update(self.env)
        self.write_env()
        path=self.state_root/"foreign-gateway.env"
        path.write_text("SMITE_FOREIGN_GATEWAY_DOMAIN=kh.example.com\n"
                        "SMITE_FOREIGN_PANEL_DOMAIN=panel.example.com\n"
                        "SMITE_FOREIGN_CONTROL_PATH="+
                        self.scope["control_url"].split(".com:443",1)[1]+"\n"
                        "SMITE_FOREIGN_GATEWAY_MODE=https-control-path\n"
                        "SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443\n")
        path.chmod(0o600)
        self.site.write_text(
            "server { listen 443 ssl; server_name kh.example.com;\n"
            "location ^~ "+self.scope["control_url"].split(".com:443",1)[1]
            +"/ { allow 127.0.0.1; deny all;\n"
            "proxy_pass http://127.0.0.1:8888/; }\n}")
        self.site.chmod(0o644)

    def test_exact_signed_runtime_is_read_only_witness_ready(self):
        self.assertIs(self.observer.core(self.scope),True)
        self.assertEqual(self.observer.sanaei(self.scope),"ABSENT")
        self.assertEqual(self.observer.gateway(self.scope),"ABSENT")
        self.assertFalse((self.state_root/"foreign-gateway.env").exists())
        self.assertTrue(any(c=="cosign" for c in self.calls))
        self.assertNotIn("full_gateway",self.calls)

    def test_core_refuses_mutated_roles_digest_health_and_compose(self):
        self.assertIs(self.observer.core(self.scope),True)
        self.overlays=True
        self.assertIs(self.observer.core(self.scope),False)
        self.overlays=False
        for key,value in (("SMITE_ROLE","iran"),
                          ("SMITE_MANAGED_VERSION","2.0.0-rc.6"),
                          ("SMITE_NODE_NAME","other")):
            original=self.current[key];self.current[key]=value
            self.assertFalse(self.observer.core(self.scope))
            self.current[key]=original
        old=self.image;self.image="ghcr.io/aghajani82/smite-node:latest"
        self.assertFalse(self.observer.core(self.scope))
        self.image=old
        old=self.health;self.health="unhealthy"
        self.assertFalse(self.observer.core(self.scope))
        self.health=old
        self.container_env["SMITE_AGENT_AUTH_MODE"]="legacy"
        self.assertFalse(self.observer.core(self.scope))
        self.container_env["SMITE_AGENT_AUTH_MODE"]="strict"

    def test_bad_signed_pair_fails_before_host_commands(self):
        self.fail_signature="wrong"
        self.observer._signed_scope=None
        self.calls.clear()
        with self.assertRaises(w.Hold):
            self.observer.core(self.scope)
        self.assertFalse(any(x.startswith("docker") for x in self.calls))

    def test_exact_ro_sanaei_after_attach_and_drift_cases(self):
        self.attach()
        self.assertEqual(self.observer.sanaei(self.scope),"READY")
        self.db_ready=False
        self.assertEqual(self.observer.sanaei(self.scope),"DRIFT")
        self.db_ready=True
        self.mount["read_only"]=False
        self.assertEqual(self.observer.sanaei(self.scope),"DRIFT")
        self.mount["read_only"]=True
        self.mount["source"]="/tmp/unsafe"
        self.assertEqual(self.observer.sanaei(self.scope),"DRIFT")

    def test_gateway_requires_actual_managed_location_and_signed_443(self):
        self.attach()
        self.assertEqual(self.observer.gateway(self.scope),"ABSENT")
        self.serve_gateway()
        self.assertEqual(self.observer.gateway(self.scope),"READY")
        self.assertIn("full_gateway",self.calls)
        self.local_443=False
        self.assertEqual(self.observer.gateway(self.scope),"DRIFT")
        self.local_443=True
        self.site.write_text("server { location ^~ /smite-node/"+("b"*32)
                             +"/ { deny all; proxy_pass http://127.0.0.1:8888/; }}")
        self.assertEqual(self.observer.gateway(self.scope),"DRIFT")
        self.serve_gateway()

    def test_missing_gateway_receipt_with_old_location_is_not_absent(self):
        self.attach()
        self.serve_gateway()
        (self.state_root/"foreign-gateway.env").unlink()
        self.assertEqual(self.observer.gateway(self.scope),"DRIFT")
        self.site.unlink()
        self.assertEqual(self.observer.gateway(self.scope),"DRIFT")

    def test_host_recovery_integration_verifies_existing_probes(self):
        actions=[]
        def install_sanaei(scope):
            actions.append("attach")
            self.attach()
        def install_gateway(scope):
            actions.append("gateway")
            self.serve_gateway()
        result=recovery.rehearse(
            directory=self.stage,packet_path=self.packet, now=self.now,
            expected_panel=self.doc["panel_url"],
            expected_foreign=self.doc["origin"],
            expected_node=self.doc["node_name"],
            verify_core=self.observer.core,
            verify_sanaei=self.observer.sanaei,
            verify_gateway=self.observer.gateway,
            install_sanaei=install_sanaei,install_gateway=install_gateway,
            disposable_capability=True)
        self.assertEqual(actions,["attach","gateway"])
        self.assertEqual(result["phase"],"GATEWAY_443_VERIFIED")
        self.assertFalse(result["connected"])
        actions.clear()
        result=recovery.rehearse(
            directory=self.stage,packet_path=self.packet, now=self.now,
            expected_panel=self.doc["panel_url"],
            expected_foreign=self.doc["origin"],
            expected_node=self.doc["node_name"],
            verify_core=self.observer.core,
            verify_sanaei=self.observer.sanaei,
            verify_gateway=self.observer.gateway,
            install_sanaei=install_sanaei,install_gateway=install_gateway,
            disposable_capability=True)
        self.assertEqual(actions,[])
        self.assertFalse(result["connected"])

    def test_cli_is_status_only(self):
        proc=subprocess.run([sys.executable,"-B",str(
            ROOT/"modules/smite-unified-foreign-existing-witnesses.py"),
            "--status"],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0)
        self.assertIn("HOST_EXECUTION=NOT_AUTHORIZED",proc.stdout)
        fail=subprocess.run([sys.executable,"-B",str(
            ROOT/"modules/smite-unified-foreign-existing-witnesses.py"),
            "--apply"],capture_output=True)
        self.assertNotEqual(fail.returncode,0)


if __name__=="__main__":
    unittest.main(verbosity=2)
