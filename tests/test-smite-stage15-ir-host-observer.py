"""Offline IR observer and two-host non-deployable handoff regressions."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT=Path(__file__).resolve().parents[1]/"modules"


def get(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/file)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod


ir=get("offline_ir_host_observer","smite-stage15-ir-host-observer.py")
host=get("offline_host_pair_verifier","smite-stage15-host-evidence-offline.py")
node=get("offline_node_verifier","smite-stage15-approval-evidence.py")


class IRObserverTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.file=self.root/"tunnels.json"
        self.doc={ir.OWNER_ID: {
            "core":"frp", "spec":{"mode":"server","bind_port":7000}}}
        self.write_registry()
        proc=self.root/"proc"/"541"
        proc.mkdir(parents=True)
        (proc/"stat").write_text(
            "541 (frps) "+" ".join(["S"]+["0"]*18+["776677"]+["0"]*5))
        self.proc_root=self.root/"proc"
        self.container={
            "Id":"a"*64, "Image":ir.NODE_IMAGE,
            "State":{"Running":True,"Health":{"Status":"healthy"}},
            "RestartCount":0,
            "Mounts":[{"Type":"volume", "Name":"smite-node-data",
                       "Source":str(self.root),"Destination":"/var/lib/smite-node",
                       "RW":True}]
        }
        self.top="PID COMMAND\n541 frps\n900 python3\n"
        self.ss="\n".join(
            f'LISTEN 0 4096 127.0.0.1:{port} 0.0.0.0:* users:(("frps",pid=541,fd=3))'
            for port in ir.PORTS)

    def write_registry(self):
        self.file.write_text(json.dumps(self.doc),encoding="utf-8")

    def fake_command(self,*args):
        if args==("docker","inspect","smite-node"):
            return json.dumps([self.container])
        if args==("docker","top","smite-node","-eo","pid,comm"):
            return self.top
        if args==("ss","-Hlntp"):
            return self.ss
        self.fail("Unexpected command: "+str(args))

    def collect(self,port=38658,**kwargs):
        with patch.object(ir,"REGISTRY",self.file):
            return ir.collect_ir(node_id="node-ir-0001",port=port,
                runner=self.fake_command,proc_root=self.proc_root,
                registry_path=self.file,require_host=False,**kwargs)

    def test_observe_all_four_loopback_owner_sockets_without_secrets(self):
        fact=self.collect()
        self.assertEqual(fact["owner_pid"],541)
        self.assertEqual(fact["owner_start_ticks"],776677)
        self.assertEqual(fact["proxy_port"],38658)
        self.assertEqual(fact["listener_ports"],[7000,28897,38658,45121])
        self.assertEqual(len(fact["registry_sha256"]),64)
        self.assertNotIn("spec",fact)
        self.assertEqual(self.collect(port=45121)["proxy_port"],45121)

    def test_unknown_registry_layout_or_wrong_owner_holds(self):
        for doc in (
            {"owners": {}},
            {"tunnels": {ir.OWNER_ID: {"core":"frp", "spec":{"mode":"server","bind_port":7000}}}},
            {ir.OWNER_ID: {"core":"frp", "spec":{"mode":"client","bind_port":7000}}},
            {ir.OWNER_ID: {"core":"frp", "spec":{"mode":"server","bind_port":7010}}},
            {ir.OWNER_ID: {"core":"frp", "spec":{"mode":"server","bind_port":7000}},
             "second-owner": {"core":"frp", "spec":{"mode":"server","bind_port":7000}}},
            {ir.OWNER_ID: {"core":"frp", "spec":{"mode":"server","bind_port":7000},
                            "status":"active"}},
        ):
            self.doc=doc
            self.write_registry()
            with self.subTest(doc=doc),self.assertRaises(ir.ObserverHold):
                self.collect()

    def test_public_wrong_duplicate_or_extra_frps_listener_holds(self):
        original=self.ss
        for new in (
            original.replace("127.0.0.1:38658","0.0.0.0:38658"),
            original.replace("pid=541","pid=542",1),
            original+"\n"+original.splitlines()[0],
            original+"\nLISTEN 0 128 127.0.0.1:9999 0.0.0.0:* users:((\"frps\",pid=541,fd=3))",
            "\n".join(original.splitlines()[1:]),
        ):
            self.ss=new
            with self.subTest(new=new[-100:]),self.assertRaises(ir.ObserverHold):
                self.collect()
        self.ss=original

    def test_node_volume_image_and_process_drift_holds(self):
        original=json.loads(json.dumps(self.container))
        self.container["Image"]="sha256:"+"0"*64
        with self.assertRaisesRegex(ir.ObserverHold,"IR_NODE_RUNTIME_DRIFT"):
            self.collect()
        self.container=json.loads(json.dumps(original))
        self.container["Mounts"][0]["Name"]="unknown"
        with self.assertRaisesRegex(ir.ObserverHold,"IR_REGISTRY_LIVE_VOLUME_UNVERIFIED"):
            self.collect()
        self.container=json.loads(json.dumps(original))
        self.top="PID COMMAND\n541 xray\n900 python3\n"
        with self.assertRaisesRegex(ir.ObserverHold,"FRPS_PROCESS_NOT_SINGLETON"):
            self.collect()

    def test_pid_reuse_and_stale_result_fail_closed(self):
        counter=0
        original=ir.start_ticks
        def changed(pid, proc_root):
            nonlocal counter
            counter+=1
            return 776677 if counter==1 else 998877
        with patch.object(ir,"start_ticks",side_effect=changed):
            with self.assertRaisesRegex(ir.ObserverHold,"GENERATION_CHANGED"):
                self.collect()
        with patch.object(ir.time,"monotonic",side_effect=[1,15]):
            with self.assertRaisesRegex(ir.ObserverHold,"IR_OBSERVATION_STALE"):
                self.collect()

    def test_non_ir_field_trial_host_refused(self):
        with patch.object(ir.os,"geteuid",return_value=0),\
             patch.object(ir.socket,"gethostname",return_value="grandoptical"):
            with self.assertRaisesRegex(ir.ObserverHold,"IR_ROOT_ONLY"):
                ir.collect_ir(node_id="node-ir-0001",port=38658,
                    runner=self.fake_command,proc_root=self.proc_root)

    def test_pair_with_kh_synthetic_evidence_remains_offline_only(self):
        ir_key=Ed25519PrivateKey.generate()
        kh_key=Ed25519PrivateKey.generate()
        facts=self.collect()
        kh_facts={
            "node":"node-kh-0001","port":38658,"listen":"127.0.0.1",
            "protocol":"vless","network":"xhttp","path":"/38658/shop",
            "enabled":True,"xray_pid":777,"xray_start_ticks":8844,
            "sanaei_container_id":"d"*64,"db_view_sha256":"f"*64,"frpc_count":3,
        }
        pair={
            "ir_host":host.sign_offline_fixture(role="ir_host",facts=facts,
                     key=ir_key,nonce="1"*32,issued_at=1000),
            "kh_host":host.sign_offline_fixture(role="kh_host",facts=kh_facts,
                     key=kh_key,nonce="2"*32,issued_at=1000),
        }
        pin=lambda key:key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        binding={"ir_node":"node-ir-0001","kh_node":"node-kh-0001",
                 "owner":ir.OWNER_ID,"child":"child-frp10","lease":"child-frp10",
                 "port":38658,"path":"/38658/shop"}
        used=host.verify_offline_pair(pair=pair,binding=binding,
             ir_host_public=pin(ir_key),kh_host_public=pin(kh_key),now=1001)
        self.assertEqual(used,frozenset({"1"*32,"2"*32}))
        # Existing Node verifier must reject host-origin proofs.
        with self.assertRaises(node.EvidenceHold):
            node.verify_bundle(
                {"ir_owner":pair["ir_host"],"kh_inbound":pair["kh_host"],
                 "ir_lease":pair["ir_host"]},
                {**binding,"owner_proof_sha256":"a"*64,
                 "kh_inventory_sha256":"b"*64},
                ir_public_key=pin(ir_key),kh_public_key=pin(kh_key),
                lease_public_key=pin(ir_key),now=1001)

    def test_no_service_or_signer_coupling(self):
        raw=(ROOT/"smite-stage15-ir-host-observer.py").read_text()
        for forbidden in ("sign_offline_fixture(", "install_grant(",
                          "serve_forever(", "Popen(", "docker run",
                          '"docker","restart"', '"docker","stop"',
                          "UPDATE tunnels", "DELETE FROM", "nginx -s reload"):
            self.assertNotIn(forbidden,raw)
        self.assertIn("OFFLINE_LIBRARY_ONLY_NO_IR_HOST_ACTIVATION",raw)


if __name__=="__main__":
    unittest.main()
