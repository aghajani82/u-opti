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
        # No saved-tunnel registry at all == genuine zero-tunnel fresh host.
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
        self.assertEqual(reviewed["STAGE_ADMISSION"],"VERIFIED_PREVIEW_ONLY",{"status":status,"reviewed":reviewed})
        self.plan=reviewed["PLAN_SHA256_NOT_AUTHORIZATION"]
        self.runner=FakeRunner()
        # Never depend on the GitHub runner's unrelated /proc processes.
        # Production code always performs the real read-only kernel check.
        proc_stub = patch.object(exe.admission.host, "frp_process_footprint",
                                 return_value={
                                     "FRPC_PROCESS_LOCAL": "NOT_OBSERVED",
                                     "FRPS_PROCESS_LOCAL": "NOT_OBSERVED",
                                     "FRPC_INSTANCE_SHA256": "ABSENT",
                                     "FRPS_INSTANCE_SHA256": "ABSENT",
                                 })
        proc_stub.start()
        self.addCleanup(proc_stub.stop)
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

    def test_enrolled_frp_is_never_recreated_even_when_no_tunnels_exist(self):
        # Explicit FRP enrollment is a stronger guard than an empty tunnel
        # registry; the installer cannot repurpose a running FRP Node.
        manifest = self.config / "engine-state" / "engines.json"
        manifest.parent.mkdir(mode=0o700)
        original = (json.dumps({
            "schema": 1, "engines": {
                "frp": {"sha256": "b" * 64, "server_sha256": "c" * 64},
            },
        }) + "\n").encode()
        manifest.write_bytes(original)
        manifest.chmod(0o600)
        before_env = (self.node / ".env").read_bytes()
        before_compose = (self.node / "docker-compose.yml").read_bytes()
        with self.assertRaises(exe.Hold):
            self.install()
        self.assertEqual(manifest.read_bytes(), original)
        self.assertEqual((self.node / ".env").read_bytes(), before_env)
        self.assertEqual((self.node / "docker-compose.yml").read_bytes(), before_compose)
        self.assertFalse(self.binary.exists())
        self.assertFalse(exe._journal(self.paths).exists())
        self.assertEqual(self.runner.calls, [])

    def test_frp_process_or_unknown_proc_footprint_blocks_before_mutation(self):
        for value in ("OBSERVED_UNATTESTED", "UNVERIFIED"):
            with self.subTest(value=value), patch.object(
                exe.admission.host, "frp_process_footprint",
                return_value={
                    "FRPC_PROCESS_LOCAL": "NOT_OBSERVED",
                    "FRPS_PROCESS_LOCAL": value,
                    "FRPC_INSTANCE_SHA256": "ABSENT",
                    "FRPS_INSTANCE_SHA256": "b" * 64 if value == "OBSERVED_UNATTESTED"
                                              else "UNVERIFIED",
                },
            ):
                before = (self.node / "docker-compose.yml").read_bytes()
                with self.assertRaisesRegex(
                        exe.Hold, "FRP_PROCESS_PRESENCE_OR_UNVERIFIED"):
                    self.install()
                self.assertEqual((self.node / "docker-compose.yml").read_bytes(), before)
                self.assertFalse(self.binary.exists())
                self.assertFalse(exe._journal(self.paths).exists())
                self.assertEqual(self.runner.calls, [])

    def test_frp_detected_after_trial_commit_blocks_rollback_before_journal(self):
        self.install()
        original_record = (exe._journal(self.paths) / "record.json").read_bytes()
        original_compose = (self.node / "docker-compose.yml").read_bytes()
        manifest = self.config / "engine-state" / "engines.json"
        doc = json.loads(manifest.read_bytes())
        doc["engines"]["frp"] = {"sha256": "b" * 64,
                                 "server_sha256": "c" * 64}
        manifest.write_text(json.dumps(doc))
        current = manifest.read_bytes()
        prior_calls = len(self.runner.calls)
        with self.assertRaisesRegex(
                exe.Hold, "ENROLLED_FRP_NODE_RECREATE_FORBIDDEN"):
            exe.rollback(expected_node_image=IMAGE,
                         role_confirm="ROLLBACK-BACKHAUL-KH-TRIAL",
                         paths=self.paths, runner=self.runner)
        self.assertEqual(current, manifest.read_bytes())
        self.assertEqual(original_compose,
                         (self.node / "docker-compose.yml").read_bytes())
        self.assertEqual(original_record,
                         (exe._journal(self.paths) / "record.json").read_bytes())
        self.assertTrue(self.binary.exists())
        self.assertEqual(prior_calls, len(self.runner.calls))

    def test_existing_frp_process_blocks_recovery_without_core_mutation(self):
        with self.assertRaises(exe.SimulatedCrash):
            self.install(inject="after-compose")
        original_record = (exe._journal(self.paths) / "record.json").read_bytes()
        before_compose = (self.node / "docker-compose.yml").read_bytes()
        before_binary = self.binary.read_bytes()
        runner_calls = len(self.runner.calls)
        with patch.object(exe.admission.host, "frp_process_footprint",
                          return_value={
                              "FRPC_PROCESS_LOCAL": "OBSERVED_UNATTESTED",
                              "FRPS_PROCESS_LOCAL": "NOT_OBSERVED",
                              "FRPC_INSTANCE_SHA256": "b" * 64,
                              "FRPS_INSTANCE_SHA256": "ABSENT",
                          }):
            with self.assertRaisesRegex(
                    exe.Hold, "FRP_PROCESS_PRESENCE_OR_UNVERIFIED"):
                exe.recover(expected_node_image=IMAGE,
                            role_confirm="RECOVER-BACKHAUL-KH-TRIAL",
                            paths=self.paths, runner=self.runner)
        self.assertEqual((exe._journal(self.paths) / "record.json").read_bytes(),
                         original_record)
        self.assertEqual((self.node / "docker-compose.yml").read_bytes(),
                         before_compose)
        self.assertEqual(self.binary.read_bytes(), before_binary)
        self.assertEqual(len(self.runner.calls), runner_calls)

    def test_frp_in_trusted_prior_manifest_blocks_even_if_current_is_empty(self):
        original_manifest = (json.dumps({
            "schema": 1, "engines": {"frp": {
                "sha256": "b" * 64, "server_sha256": "c" * 64,
            }},
        }) + "\n").encode()
        with self.assertRaisesRegex(
                exe.Hold, "ENROLLED_FRP_NODE_RECREATE_FORBIDDEN"):
            exe._assert_no_frp_before_recreate(
                self.paths, previous_manifest=original_manifest)
        for malformed in (
            b'{"schema":1,"engines":{},"engines":{"frp":{}}}',
            b'{"schema":true,"engines":{}}',
            b'{"schema":1,"engines":null}',
            b'{',
        ):
            with self.subTest(malformed=malformed[:30]):
                with self.assertRaisesRegex(
                        exe.Hold, "FRP_RECREATE_MANIFEST_UNTRUSTED"):
                    exe._assert_no_frp_before_recreate(
                        self.paths, previous_manifest=malformed)


    def _retained_review_fixture(self):
        """FRP enrolled with saved tunnels; no Compose or container changes."""
        manifest=self.config/"engine-state"/"engines.json"
        manifest.parent.mkdir(mode=0o700)
        manifest.write_text(json.dumps({"schema":1,"engines":{"frp":{
            "sha256":"b"*64,"server_sha256":"c"*64
        }}},sort_keys=True)+"\n")
        manifest.chmod(0o600)
        (self.data/"tunnels.json").write_text(json.dumps({
            "owner":{"core":"frp","spec":{"mode":"server"}},
            "child":{"core":"frp","spec":{"mode":"client"}},
        }))
        self.runtime["Id"]="1"*64
        self.runtime["Image"]="sha256:"+"2"*64
        self.runtime["State"]["StartedAt"]="2026-11-05T18:00:00Z"
        audit={"NODE_CONTAINER":"RUNNING_REVIEWED_IMAGE",
               "CORE_PROFILE":"MANAGED_STRICT",
               "SAVED_TUNNELS":"EXISTING_DO_NOT_RESTART",
               "TARGET_ENGINE":"NOT_INSTALLED",
               "OTHER_ENGINE":"ENROLLED_UNVERIFIED",
               "OTHER_ENGINE_ACTION":"NEVER_MODIFY",
               "SIGNED_REGISTRY_PAIR_PROOF":"NOT_SUPPLIED",
               "INSTALL_ALLOWED":"NO",
               "ACTIVATION_GATE":"HOLD",
               "SAVED_TUNNEL_REGISTRY_SHA256":"d"*64,
               "BROKER_SOCKET_ID_SHA256":"e"*64,
               "WSS_EDGE_JOURNAL_SHA256":"f"*64,
               "FRPC_INSTANCE_SHA256":"a"*64,
               "FRPS_INSTANCE_SHA256":"b"*64}
        class RetainedRunner:
            def __init__(self,doc):
                self.doc=doc
                self.calls=[]
                self.binary_ok=True
                self.replace=False
            def __call__(self,args,**kwargs):
                self.calls.append(tuple(args))
                class Result:
                    returncode=0
                    stdout=""
                    stderr=""
                result=Result()
                if args[:3]==["docker","inspect","--type=container"]:
                    doc=dict(self.doc)
                    if self.replace and len(self.calls)>2:
                        doc["Id"]="3"*64
                    result.stdout=json.dumps([doc])
                elif args[:3]==["docker","exec","-i"]:
                    result.stdout=("OFFICIAL_BUNDLED_BACKHAUL_BYTES=PASS\n"
                                   if self.binary_ok else "")
                    if not self.binary_ok: result.returncode=2
                    self.assert_probe_args=args
                else:
                    raise AssertionError("Unexpected command")
                return result
        runner=RetainedRunner(self.runtime)
        return runner,audit

    def test_retained_frp_node_official_binary_preview_is_never_install(self):
        runner,audit=self._retained_review_fixture()
        original=(self.node/".env").read_bytes(),(self.node/"docker-compose.yml").read_bytes(),\
                 (self.config/"engine-state/engines.json").read_bytes(),\
                 (self.data/"tunnels.json").read_bytes()
        with patch.object(exe.admission,"report",return_value=audit):
            result=exe.review_in_place_binary(
                expected_node_image=IMAGE,arch="amd64",
                paths=self.paths,runner=runner)
        self.assertEqual(result["RETAINED_NODE_BACKHAUL_BINARY"],
                         "OFFICIAL_EXECUTABLE_SHA256_MATCH")
        self.assertEqual(result["REASON"],
                         "SIGNED_IMAGE_AND_IN_PLACE_ROLLBACK_STILL_REQUIRED")
        self.assertEqual(result["INSTALL_ALLOWED"],"NO")
        self.assertEqual(result["ACTIVATION_GATE"],"HOLD")
        self.assertEqual(result["NODE_RECREATE"],"FORBIDDEN")
        self.assertEqual(result["IN_PLACE_MANIFEST_TRANSACTION"],"NOT_IMPLEMENTED")
        self.assertEqual(len(runner.calls),3)
        self.assertEqual([x[:2] for x in runner.calls],
                         [("docker","inspect"),("docker","exec"),("docker","inspect")])
        self.assertNotIn("compose",str(runner.calls))
        self.assertIn("UOPTI_EXPECTED_BACKHAUL_SHA256="+
                      exe.package.OFFICIAL_BINARY_SHA256["amd64"],runner.assert_probe_args)
        self.assertEqual(original,(
            (self.node/".env").read_bytes(),
            (self.node/"docker-compose.yml").read_bytes(),
            (self.config/"engine-state/engines.json").read_bytes(),
            (self.data/"tunnels.json").read_bytes()))
        self.assertFalse(exe._journal(self.paths).exists())

    def test_retained_frp_binary_missing_or_replaced_fails_closed(self):
        runner,audit=self._retained_review_fixture()
        for attr in ("binary_ok","replace"):
            with self.subTest(attr=attr):
                runner.calls.clear()
                setattr(runner,attr,False if attr=="binary_ok" else True)
                with patch.object(exe.admission,"report",return_value=audit):
                    result=exe.review_in_place_binary(
                        expected_node_image=IMAGE,arch="amd64",
                        paths=self.paths,runner=runner)
                self.assertEqual(result["INSTALL_ALLOWED"],"NO")
                self.assertNotEqual(result["RETAINED_NODE_BACKHAUL_BINARY"],
                                    "OFFICIAL_EXECUTABLE_SHA256_MATCH")
                self.assertFalse(exe._journal(self.paths).exists())
                setattr(runner,attr,True if attr=="binary_ok" else False)

    def test_retained_frp_unsigned_image_or_bad_host_never_authorizes(self):
        runner,audit=self._retained_review_fixture()
        for expected in ("latest","ghcr.io/aghajani82/smite-node:latest"):
            with self.subTest(image=expected):
                result=exe.review_in_place_binary(
                    expected_node_image=expected,arch="amd64",
                    paths=self.paths,runner=runner)
                self.assertEqual(result["REASON"],"EXTERNAL_NODE_IMAGE_PIN_REQUIRED")
                self.assertFalse(runner.calls)
        with patch.object(exe.admission,"report",return_value={
            **audit,"OTHER_ENGINE":"UNAVAILABLE",
        }):
            result=exe.review_in_place_binary(
                expected_node_image=IMAGE,arch="amd64",paths=self.paths,runner=runner)
        self.assertEqual(result["REASON"],"RETAINED_FRP_HOST_ADMISSION_HOLD")
        self.assertEqual(result["INSTALL_ALLOWED"],"NO")
        self.assertFalse(exe._journal(self.paths).exists())

    def retained_fixture(self):
        from dataclasses import replace
        self._retained_review_fixture()
        self.state.mkdir(mode=0o700, parents=True)
        frp = self.root / "frp"
        frp.mkdir(mode=0o700)
        manifest = self.config / "engine-state/engines.json"
        receipt = frp / "record.json"
        receipt.write_text(json.dumps({"schema": 1, "state": "COMMITTED", "role": "ir",
            "old": None, "new": exe._sha(manifest.read_bytes()),
            "binaries": {"frpc": "b"*64, "frps": "c"*64}}))
        receipt.chmod(0o600)
        paths = replace(self.paths, frp_state=frp)

        def step(action, witness=lambda: "1"*64):
            return exe._retained_step(paths, action=action, role="ir", arch="amd64",
                                      witness=witness)
        return step, manifest, receipt

    def test_signed_read_only_plan_for_actual_host_role_names(self):
        from dataclasses import replace
        runner, audit = self._retained_review_fixture()
        manifest = self.config / "engine-state/engines.json"
        frp = self.root / "frp"
        frp.mkdir(mode=0o700)
        paths = replace(self.paths, frp_state=frp)
        for label, role in (("IR", "ir"), ("KH", "foreign")):
            record = {"schema": 1, "state": "COMMITTED", "role": role,
                      "old": None, "new": exe._sha(manifest.read_bytes()),
                      "binaries": {"frpc": "b"*64, "frps": "c"*64}}
            receipt = frp / "record.json"
            receipt.write_text(json.dumps(record))
            receipt.chmod(0o600)
            evidence = {**audit, "NODE_ROLE": label, "SIGNED_REGISTRY_PAIR_PROOF": "COSIGN_VERIFIED"}
            with patch.object(exe.admission, "report", return_value=evidence):
                result = exe.review_in_place_binary(expected_node_image=IMAGE,
                    arch="amd64", paths=paths, runner=runner)
            self.assertEqual(result["IN_PLACE_MANIFEST_TRANSACTION"], "PAIR_PLAN_VERIFIED_READ_ONLY")
            self.assertEqual(result["INSTALL_ALLOWED"], "NO")
            self.assertFalse(self.state.exists())

    def test_retained_commit_retry_rollback_and_drift(self):
        step, manifest, receipt = self.retained_fixture()
        before = manifest.read_bytes(), receipt.read_bytes()
        with exe._lock(self.lock), self.assertRaises(exe.Hold):
            step("install")
        self.assertEqual(step("install"), "COMMITTED")
        self.assertEqual(step("install"), "COMMITTED")
        self.assertEqual(step("recover"), "COMMITTED")
        changed = manifest.read_bytes(), receipt.read_bytes()
        with self.assertRaises(exe.Hold):
            step("rollback", lambda: "2"*64)
        manifest.write_bytes(b"drift")
        with self.assertRaises(exe.Hold):
            step("recover")
        self.assertEqual(receipt.read_bytes(), changed[1])
        self.assertEqual(manifest.read_bytes(), b"drift")
        manifest.write_bytes(changed[0])
        self.assertEqual(step("rollback"), "RESTORED")
        self.assertEqual(step("recover"), "RESTORED")
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), before)

    def test_retained_process_death_during_apply_and_compensation(self):
        step, manifest, receipt = self.retained_fixture()
        before = manifest.read_bytes(), receipt.read_bytes()
        for action, target in (("install", manifest), ("install", receipt),
                               ("rollback", receipt), ("rollback", manifest)):
            with self.subTest(action=action, target=target.name):
                if action == "rollback":
                    step("install")
                pid = os.fork()
                if pid == 0:
                    atomic = exe.pair._pair_atomic
                    def crash(path, content):
                        atomic(path, content)
                        if path == target:
                            os._exit(91)
                    with patch.object(exe.pair, "_pair_atomic", crash):
                        try:
                            step(action)
                        finally:
                            os._exit(1)
                self.assertEqual(os.waitpid(pid, 0)[1], 91 << 8)
                with self.assertRaises(exe.Hold):
                    step("install")
                self.assertEqual(step("recover"), "RESTORED")
                self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), before)

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
