#!/usr/bin/env python3
"""Managed Backhaul disposable-host executor: real filesystem, fake Docker only."""
from __future__ import annotations
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"modules/smite-managed-backhaul-host-executor.py"
spec=importlib.util.spec_from_file_location("managed_bh_host_executor_test",SRC)
exe=importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name]=exe
spec.loader.exec_module(exe)

IMAGE="ghcr.io/aghajani82/smite-node@sha256:"+"a"*64
ENV=("NODE_ROLE=foreign\nSMITE_NODE_PANEL_AUTH_MODE=signed\n"
     "SMITE_AGENT_AUTH_MODE=strict\nSMITE_ENGINE_INVENTORY_MODE=managed\n")
COMPOSE=("services:\n  smite-node:\n    image: "+IMAGE+"\n    network_mode: host\n"
         "    volumes:\n      - ./config:/etc/smite-node\n"
         "      - node-data:/var/lib/smite-node\n"
         "volumes:\n  node-data:\n    name: smite-node-data\n")

def elf():
    blob=bytearray(128); blob[:4]=b"\x7fELF"; blob[4:6]=bytes([2,1])
    struct.pack_into("<H",blob,18,62)
    return bytes(blob)+b"BACKHAUL"

class FakeRunner:
    def __init__(self):
        self.calls=[]; self.fail_ready=False
    def __call__(self,args,**kwargs):
        self.calls.append(list(args))
        class R:
            returncode=0; stdout=""; stderr=""
        out=R()
        if args[:2]==["docker","exec"]:
            env=next(x for x in args if x.startswith("UOPTI_EXPECTED_ENGINES="))
            states=json.loads(env.split("=",1)[1])
            if self.fail_ready and states["backhaul"]=="ready":
                out.returncode=1; out.stdout=""
            else:
                out.stdout="UOPTI_SIGNED_RUNTIME=PASS\n"
        return out

class HostExecutor(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="managed-bh-host-exec-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.root.chmod(0o700)
        self.node=self.root/"node"; self.node.mkdir(mode=0o700)
        self.config=self.node/"config"; self.config.mkdir(mode=0o700)
        (self.node/".env").write_text(ENV); (self.node/".env").chmod(0o600)
        (self.node/"docker-compose.yml").write_text(COMPOSE)
        (self.node/"docker-compose.yml").chmod(0o600)
        self.data=self.root/"data"; self.data.mkdir(mode=0o700)
        (self.data/"tunnels.json").write_text("[]\n")
        (self.data/"tunnels.json").chmod(0o600)
        self.stages=self.root/"stages"; self.stages.mkdir(mode=0o700)
        self.state_anchor=self.root/"state"; self.state_anchor.mkdir(mode=0o700)
        self.state=self.state_anchor/"engine"/"backhaul"
        self.engine_anchor=self.root/"opt-uopti"; self.engine_anchor.mkdir(mode=0o700)
        self.binary=self.engine_anchor/"engines"/"backhaul"/"v0.7.2"/"backhaul"
        self.lock=self.root/"engine.lock"
        self.paths=exe.Paths(node=self.node,staging=self.stages,state=self.state,
                             lock=self.lock,binary=self.binary)
        # CI runner is intentionally non-root. Production code keeps the
        # root-owner checks; only these temp fixtures skip the UID==0 branch.
        for host_module in (exe.admission.host, exe.plan.admission.host):
            real_file=host_module._local_file
            patcher=patch.object(
                host_module, "_local_file",
                side_effect=lambda path, *, max_bytes, require_root=False, _real=real_file:
                    _real(path, max_bytes=max_bytes, require_root=False),
            )
            patcher.start(); self.addCleanup(patcher.stop)
        self.runtime={
            "Name":"/smite-node","State":{"Running":True},
            "Config":{"Image":IMAGE,"Env":[]},
            "HostConfig":{"NetworkMode":"host","PortBindings":{}},
            "Mounts":[
                {"Type":"bind","Destination":"/etc/smite-node","Source":str(self.config)},
                {"Type":"volume","Destination":"/var/lib/smite-node","Name":"smite-node-data",
                 "Driver":"local","Source":str(self.data)},
            ],
        }
        archive=self.root/"backhaul.tar.gz"
        payload=elf()
        with tarfile.open(archive,"w:gz") as tf:
            info=tarfile.TarInfo("release/backhaul"); info.size=len(payload)
            tf.addfile(info,io.BytesIO(payload))
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        self.patches=[
            patch.object(exe.package,"INSTALL_BINARY",self.binary),
            patch.object(exe.plan.backhaul,"INSTALL_BINARY",self.binary),
            patch.dict(exe.package.OFFICIAL_TAR_SHA256,{"amd64":digest},clear=False),
            patch.dict(exe.plan.backhaul.OFFICIAL_TAR_SHA256,{"amd64":digest},clear=False),
        ]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        self.stage=exe.package.prepare(self.node,archive,self.stages,arch="amd64",allowed_sha=digest)
        # Host plan uses its own imported package instance; prepare the stage
        # under the executor package then both verify identical official bytes.
        status=exe.admission.report("backhaul",self.node,runtime=self.runtime,
                                    min_bytes=1,expected_node_image=IMAGE)
        reviewed=exe.plan.review("backhaul",self.node,self.stage,
                                 staging_root=self.stages,host_status=status)
        self.assertEqual(reviewed["STAGE_ADMISSION"],"VERIFIED_PREVIEW_ONLY")
        self.plan=reviewed["PLAN_SHA256_NOT_AUTHORIZATION"]
        self.runner=FakeRunner()
        self.old_compose=(self.node/"docker-compose.yml").read_bytes()

    def install(self,**kwargs):
        values=dict(stage=self.stage,expected_node_image=IMAGE,
                    expected_plan_sha256=self.plan,
                    snapshot_confirm=exe.SNAPSHOT_CONFIRM,
                    role_confirm="APPLY-BACKHAUL-KH-TRIAL",
                    paths=self.paths,runtime=self.runtime,runner=self.runner)
        values.update(kwargs)
        return exe.install(**values)

    def test_commit_then_explicit_rollback_restores_exact_bytes(self):
        result=self.install()
        self.assertEqual(result["TRIAL_INSTALL"],"COMMITTED_SIGNED_RUNTIME_VERIFIED")
        self.assertEqual(result["TUNNEL_APPLY"],"NOT_PERFORMED")
        self.assertTrue(self.binary.is_file())
        self.assertIn(b"/usr/local/bin/backhaul:ro",(self.node/"docker-compose.yml").read_bytes())
        manifest=json.loads((self.config/"engine-state/engines.json").read_text())
        self.assertIn("backhaul",manifest["engines"])
        record=exe._record(self.paths)
        self.assertEqual(record["state"],"COMMITTED")
        rolled=exe.rollback(expected_node_image=IMAGE,
                            role_confirm="ROLLBACK-BACKHAUL-KH-TRIAL",
                            paths=self.paths,runner=self.runner)
        self.assertEqual(rolled["TRIAL_ROLLBACK"],
                         "EXACT_BYTES_AND_SIGNED_PRIOR_RUNTIME_VERIFIED")
        self.assertEqual((self.node/"docker-compose.yml").read_bytes(),self.old_compose)
        self.assertFalse(self.binary.exists())
        self.assertFalse((self.config/"engine-state/engines.json").exists())
        self.assertFalse(exe._journal(self.paths).exists())
        self.assertTrue(any(p.name.startswith("audit-") for p in self.state.iterdir()))

    def test_missing_snapshot_wrong_role_image_or_plan_never_mutates(self):
        cases=[
            {"snapshot_confirm":""},
            {"role_confirm":"APPLY-BACKHAUL-IR-TRIAL"},
            {"expected_node_image":"ghcr.io/aghajani82/smite-node:latest"},
            {"expected_plan_sha256":"0"*64},
        ]
        for change in cases:
            with self.subTest(change=change):
                before=(self.node/"docker-compose.yml").read_bytes()
                with self.assertRaises(exe.Hold): self.install(**change)
                self.assertEqual((self.node/"docker-compose.yml").read_bytes(),before)
                self.assertFalse(self.binary.exists())
                self.assertFalse(exe._journal(self.paths).exists())

    def test_signed_ready_failure_forces_exact_rollback(self):
        self.runner.fail_ready=True
        with self.assertRaisesRegex(exe.Hold,"INSTALL_FAILED_EXACT_ROLLBACK_PROVED"):
            self.install()
        self.assertEqual((self.node/"docker-compose.yml").read_bytes(),self.old_compose)
        self.assertFalse(self.binary.exists())
        self.assertFalse((self.config/"engine-state/engines.json").exists())
        self.assertFalse(exe._journal(self.paths).exists())

    def test_interrupted_after_compose_is_recoverable_without_reinstall(self):
        with self.assertRaises(exe.SimulatedCrash):
            self.install(inject="after-compose")
        self.assertTrue(exe._journal(self.paths).exists())
        self.assertTrue(self.binary.exists())
        recovered=exe.recover(expected_node_image=IMAGE,
                              role_confirm="RECOVER-BACKHAUL-KH-TRIAL",
                              paths=self.paths,runner=self.runner)
        self.assertIn("ROLLED_BACK",recovered["INTERRUPTED_TRIAL_RECOVERY"])
        self.assertEqual((self.node/"docker-compose.yml").read_bytes(),self.old_compose)
        self.assertFalse(self.binary.exists())
        self.assertFalse(exe._journal(self.paths).exists())

    def test_out_of_band_compose_change_blocks_destructive_rollback(self):
        self.install()
        (self.node/"docker-compose.yml").write_text("external operator edit\n")
        with self.assertRaisesRegex(exe.Hold,"COMPOSE_EXTERNAL_DRIFT"):
            exe.rollback(expected_node_image=IMAGE,
                         role_confirm="ROLLBACK-BACKHAUL-KH-TRIAL",
                         paths=self.paths,runner=self.runner)
        self.assertTrue(exe._journal(self.paths).exists())
        self.assertTrue(self.binary.exists())

    def test_executor_has_no_nginx_firewall_xray_or_tunnel_apply_actions(self):
        source=SRC.read_text()
        for forbidden in ("nginx -s","iptables ","nft ","ufw ","xray","3x-ui",
                          "/api/agent/tunnels/apply","systemctl ","ssh ","curl "):
            self.assertNotIn(forbidden,source)
        self.assertIn('"TUNNEL_APPLY": "NOT_PERFORMED"',source)
        # Only the reviewed Node itself is recreated and probed.
        self.assertIn('["docker", "compose"',source)
        self.assertIn('["docker", "exec"',source)

if __name__=="__main__":
    unittest.main(verbosity=2)
