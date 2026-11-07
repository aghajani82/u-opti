#!/usr/bin/env python3
"""Managed Backhaul disposable-host executor: real filesystem, fake Docker only."""
from __future__ import annotations
from contextlib import contextmanager
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

    def test_exclusive_engine_lock_stable_inode_and_nested_writer_hold(self):
        # This lock is used only inside the independently gated executor.
        # A stable, private inode serializes both writers; no write occurs.
        with exe._lock(self.lock):
            with self.assertRaisesRegex(
                    exe.Hold, "ANOTHER_ENGINE_TRANSACTION_ACTIVE"):
                with exe._lock(self.lock):
                    self.fail("competing writer admitted")
        self.assertTrue(self.lock.is_file())
        self.assertEqual(self.lock.stat().st_mode & 0o777, 0o600)

    def test_exclusive_engine_lock_refuses_replaced_or_unlinked_inode(self):
        # Simulate adversarial replacement in the narrow window immediately
        # AFTER flock succeeds and BEFORE any engine transaction may begin.
        # The read-only lock already verifies this and writers must too.
        real_flock = exe.fcntl.flock
        for replacement in ("new-inode", "unlinked"):
            with self.subTest(replacement=replacement):
                if self.lock.exists():
                    self.lock.unlink()
                entered = []
                def race(fd, flags):
                    real_flock(fd, flags)
                    self.lock.unlink()
                    if replacement == "new-inode":
                        self.lock.write_bytes(b"")
                        self.lock.chmod(0o600)
                with patch.object(exe.fcntl, "flock", side_effect=race):
                    with self.assertRaisesRegex(
                            exe.Hold, "ENGINE_LOCK_CHANGED"):
                        with exe._lock(self.lock):
                            entered.append("TRANSACTION_BEGIN")
                self.assertEqual(entered, [])

    def test_exclusive_engine_lock_rejects_relative_symlinked_parent(self):
        relative = Path("unsafe-relative-engine.lock")
        parent_alias = self.root / "alias-parent"
        parent_alias.symlink_to(self.root, target_is_directory=True)
        for unsafe in (relative, parent_alias / "engine.lock"):
            with self.subTest(unsafe=str(unsafe)), self.assertRaisesRegex(
                    exe.Hold, "UNSAFE_LOCK_PATH"):
                with exe._lock(unsafe):
                    self.fail("unsafe lock admitted")

    def test_legacy_trial_recreator_refuses_all_live_paths_before_any_action(self):
        from dataclasses import replace
        live = exe.Paths()
        original = ((self.node / "docker-compose.yml").read_bytes(),
                    (self.node / ".env").read_bytes())
        names = ("node", "staging", "state", "lock", "binary")
        for action in ("install", "rollback", "recover"):
            for name in names:
                with self.subTest(action=action, resource=name):
                    blocked = replace(self.paths, **{name: getattr(live, name)})
                    with patch.object(exe, "_lock",
                                      side_effect=AssertionError("LIVE_ENGINE_LOCK_CALLED")):
                        with self.assertRaisesRegex(
                                exe.Hold, "LIVE_NODE_RECREATING_TRIAL_FORBIDDEN"):
                            if action == "install":
                                self.install(paths=blocked)
                            elif action == "rollback":
                                exe.rollback(expected_node_image=IMAGE,
                                    role_confirm="ROLLBACK-BACKHAUL-KH-TRIAL",
                                    paths=blocked, runner=self.runner)
                            else:
                                exe.recover(expected_node_image=IMAGE,
                                    role_confirm="RECOVER-BACKHAUL-KH-TRIAL",
                                    paths=blocked, runner=self.runner)
                    self.assertEqual(self.runner.calls, [])
                    self.assertFalse(exe._journal(self.paths).exists())
        # A manually supplied alias, a symlink and even an ancestor of the
        # canonical live Node must not bypass the same production refusal.
        for candidate in (live.node / "config", live.node.parent):
            with self.subTest(alias=str(candidate)):
                with self.assertRaisesRegex(
                        exe.Hold, "LIVE_NODE_RECREATING_TRIAL_FORBIDDEN"):
                    exe._deny_live_recreating_trial_paths(
                        replace(self.paths, node=candidate))
        alias = self.root / "aliased-live-node"
        alias.symlink_to(live.node)
        with self.assertRaisesRegex(
                exe.Hold, "LIVE_NODE_RECREATING_TRIAL_FORBIDDEN"):
            exe._deny_live_recreating_trial_paths(
                replace(self.paths, node=alias))
        with self.assertRaisesRegex(
                exe.Hold, "LEGACY_TRIAL_PATHS_UNTRUSTED"):
            exe._deny_live_recreating_trial_paths(
                replace(self.paths, lock=Path("relative-lock")))
        self.assertEqual(original,
                         ((self.node / "docker-compose.yml").read_bytes(),
                          (self.node / ".env").read_bytes()))

    def test_legacy_trial_cli_default_paths_refuses_even_valid_acknowledgements(self):
        import io
        for action in ("install", "rollback", "recover"):
            with self.subTest(action=action):
                argv = ["host-executor", action,
                        "--expected-node-image", IMAGE,
                        "--confirm-role", {
                            "install": "APPLY-BACKHAUL-KH-TRIAL",
                            "rollback": "ROLLBACK-BACKHAUL-KH-TRIAL",
                            "recover": "RECOVER-BACKHAUL-KH-TRIAL",
                        }[action]]
                if action == "install":
                    argv += ["--stage", str(self.stage),
                             "--expected-plan-sha256", self.plan,
                             "--confirm-snapshot-and-console", exe.SNAPSHOT_CONFIRM]
                stderr = io.StringIO()
                with (
                    patch.object(exe.sys, "argv", argv),
                    patch.object(exe.os, "geteuid", return_value=0),
                    patch.object(exe.sys, "stderr", stderr),
                    patch.object(exe, "_lock",
                                 side_effect=AssertionError("LOCK_CALLED")),
                ):
                    self.assertEqual(exe.main(), 2)
                self.assertIn("LIVE_NODE_RECREATING_TRIAL_FORBIDDEN",
                              stderr.getvalue())
                self.assertEqual(self.runner.calls, [])

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
        self.lock.touch(mode=0o600)
        self.lock.chmod(0o600)
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

    def test_retained_real_signed_witness_hold_has_sanitized_phase(self):
        # The previously generic RETAINED_NODE_PREVIEW_UNVERIFIED concealed
        # whether Cosign, Node identity, official binary or the existing
        # FRP tunnel-registry read failed. Fixed stage names only: never
        # expose the actual exception, Docker logs, paths or tunnel bytes.
        runner, audit = self._retained_review_fixture()
        approved = dict(audit, SIGNED_REGISTRY_PAIR_PROOF="COSIGN_VERIFIED",
                        NODE_ROLE="IR")
        original = (self.config / "engine-state/engines.json").read_bytes()
        with patch.object(exe, "Paths", return_value=self.paths), \
             patch.object(exe.admission, "report", return_value=approved), \
             patch.object(exe, "_retained_live_signed_witness",
                          side_effect=exe.Hold("SECRET_PATH_OR_TOKEN")) as witness:
            report = exe.review_in_place_binary(
                expected_node_image=IMAGE, arch="amd64",
                paths=self.paths, runner=runner)
        self.assertEqual(witness.call_count, 1)
        self.assertEqual(
            report["REASON"], "RETAINED_PREVIEW_LOCAL_SIGNED_WITNESS_UNVERIFIED")
        self.assertEqual(report["SIGNED_REGISTRY_PAIR_PROOF"], "COSIGN_VERIFIED")
        self.assertEqual(report["RETAINED_NODE_BACKHAUL_BINARY"], "UNVERIFIED")
        self.assertEqual(report["INSTALL_ALLOWED"], "NO")
        self.assertEqual(report["ACTIVATION_GATE"], "HOLD")
        self.assertNotIn("SECRET_PATH_OR_TOKEN", str(report))
        self.assertEqual((self.config / "engine-state/engines.json").read_bytes(),
                         original)
        self.assertFalse(self.state.exists())
        # The only commands were read-only Docker inspect; not a writer.
        self.assertTrue(all(call[:2] == ("docker", "inspect")
                            for call in runner.calls))

    def test_retained_read_only_review_holds_existing_engine_lock(self):
        # Read-only admission must neither create a lock nor race with FRP
        # enrollment or a retained Backhaul paired-receipt transaction.
        import fcntl
        runner, audit = self._retained_review_fixture()
        for kind in ("missing", "symlink", "loose-mode", "busy"):
            with self.subTest(kind=kind):
                self.lock.unlink(missing_ok=True)
                fd = None
                if kind == "symlink":
                    self.lock.symlink_to(self.root / "missing-external-lock")
                elif kind in ("loose-mode", "busy"):
                    self.lock.touch(mode=0o600)
                    self.lock.chmod(0o644 if kind == "loose-mode" else 0o600)
                    if kind == "busy":
                        fd = os.open(self.lock, os.O_RDONLY)
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    with patch.object(exe.admission, "report", return_value=audit):
                        result = exe.review_in_place_binary(
                            expected_node_image=IMAGE, arch="amd64",
                            paths=self.paths, runner=runner)
                    self.assertEqual(result["INSTALL_ALLOWED"], "NO")
                    self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
                    self.assertEqual(result["IN_PLACE_MANIFEST_TRANSACTION"],
                                     "NOT_IMPLEMENTED")
                    self.assertNotIn("REASON", audit)
                    self.assertEqual(runner.calls, [])
                    self.assertFalse(self.state.exists())
                    if kind == "missing":
                        self.assertFalse(self.lock.exists(),
                                         "read-only review created a lock file")
                finally:
                    if fd is not None:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        os.close(fd)
        self.lock.unlink(missing_ok=True)
        self.lock.touch(mode=0o600)
        self.lock.chmod(0o600)
        before = self.lock.stat()
        with patch.object(exe.admission, "report", return_value=audit):
            clean = exe.review_in_place_binary(
                expected_node_image=IMAGE, arch="amd64",
                paths=self.paths, runner=runner)
        self.assertEqual(clean["RETAINED_NODE_BACKHAUL_BINARY"],
                         "OFFICIAL_EXECUTABLE_SHA256_MATCH")
        self.assertEqual(clean["INSTALL_ALLOWED"], "NO")
        self.assertEqual((self.lock.stat().st_ino, self.lock.stat().st_mtime_ns),
                         (before.st_ino, before.st_mtime_ns))
        self.assertEqual(len(runner.calls), 3)

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
        # Direct retained-writer calls must carry the SAME disposable CI
        # admission marker and GitHub PR environment as the two-host lab.
        # Never weaken the writer boundary to make fixtures pass.
        marker = self.root / "EXPERIMENTAL-LAB"
        marker.write_text(exe.pair.MARKER)
        marker.chmod(0o600)
        ci = patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": "aghajani82/u-opti",
            "RUNNER_TEMP": str(self.root.parent),
        })
        ci.start()
        self.addCleanup(ci.stop)
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

    def test_retained_writer_cannot_bypass_ci_lab_admission_directly(self):
        # The coordinator used to enforce pair.admission, but an imported
        # direct writer call did not. Reject BEFORE acquiring any engine
        # lock or writing a PREPARED journal on an alternate path.
        from dataclasses import replace
        step, manifest, receipt = self.retained_fixture()
        paths = replace(self.paths, frp_state=self.root / "frp")
        original = (manifest.read_bytes(), receipt.read_bytes())
        journal = self.state / "retained-rc7.json"
        seal = self.state / "retained-rc7-cleanup.json"
        marker = self.root / "EXPERIMENTAL-LAB"
        valid_marker = marker.read_bytes()

        for variable, value in (
                ("GITHUB_ACTIONS", "false"),
                ("GITHUB_EVENT_NAME", "push"),
                ("GITHUB_REPOSITORY", "someone-else/other"),
                ("RUNNER_TEMP", str(self.root / "wrong-runner"))):
            with self.subTest(env=variable), \
                 patch.dict(os.environ, {variable: value}), \
                 patch.object(exe, "_lock",
                              side_effect=AssertionError("LOCK_MUST_NOT_OPEN")), \
                 self.assertRaisesRegex(exe.Hold, "RETAINED_CI_LAB_ONLY"):
                exe._retained_step(paths, action="install", role="ir",
                                   arch="amd64", witness=lambda: "1" * 64)
            self.assertFalse(journal.exists())
            self.assertFalse(seal.exists())

        for kind in ("missing", "tampered", "symlink"):
            with self.subTest(marker=kind):
                marker.unlink()
                if kind == "tampered":
                    marker.write_text("UNTRUSTED-LAB-MARKER\n")
                elif kind == "symlink":
                    reference = self.root / "fake-marker-reference"
                    reference.write_bytes(valid_marker)
                    marker.symlink_to(reference)
                with patch.object(
                        exe, "_lock",
                        side_effect=AssertionError("LOCK_MUST_NOT_OPEN")), \
                     self.assertRaisesRegex(exe.Hold, "RETAINED_CI_LAB_ONLY"):
                    exe._retained_step(paths, action="install", role="ir",
                                       arch="amd64", witness=lambda: "1" * 64)
                if marker.is_symlink() or marker.exists():
                    marker.unlink()
                if kind == "symlink":
                    reference.unlink()
                marker.write_bytes(valid_marker)
                marker.chmod(0o600)
            self.assertEqual((manifest.read_bytes(), receipt.read_bytes()),
                             original)
            self.assertFalse(journal.exists())

        # Reject every alternate field outside the admitted disposable
        # root (not merely the canonical live path aliases).
        outsider = self.root.parent / "not-under-the-disposable-root"
        for field in ("node", "staging", "state", "lock",
                      "binary", "frp_state"):
            with self.subTest(resource=field), \
                 patch.object(exe, "_lock",
                              side_effect=AssertionError("LOCK_MUST_NOT_OPEN")), \
                 self.assertRaisesRegex(exe.Hold, "RETAINED_CI_LAB_ONLY"):
                exe._retained_step(
                    replace(paths, **{field: outsider / field}),
                    action="install", role="ir", arch="amd64",
                    witness=lambda: "1" * 64)
            self.assertEqual((manifest.read_bytes(), receipt.read_bytes()),
                             original)
            self.assertFalse(journal.exists())
            self.assertFalse(seal.exists())

        # Admission is required for recovery/cleanup as well; lost CI
        # context must leave an already valid COMMITTED journal intact.
        self.assertEqual(step("install"), "COMMITTED")
        committed = (manifest.read_bytes(), receipt.read_bytes())
        committed_journal = journal.read_bytes()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}), \
             patch.object(exe, "_lock",
                          side_effect=AssertionError("LOCK_MUST_NOT_OPEN")), \
             self.assertRaisesRegex(exe.Hold, "RETAINED_CI_LAB_ONLY"):
            step("rollback")
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()),
                         committed)
        self.assertEqual(journal.read_bytes(), committed_journal)
        self.assertFalse(seal.exists())
        self.assertEqual(step("rollback"), "RESTORED")
        self.assertEqual(step("cleanup"), "CLEANED")
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()),
                         original)

    def _live_witness_test_fixture(self, role):
        from types import SimpleNamespace
        registry = self.data / "tunnels.json"
        registry.write_text('{"schema":1,"tunnels":[]}\n')
        registry.chmod(0o600)
        image_id = "sha256:" + "3" * 64
        container = {
            "Name": "/smite-node",
            "Id": "4" * 64,
            "Image": image_id,
            "Config": {"Image": IMAGE},
            "State": {"Running": True, "StartedAt": "2026-11-07T09:00:00Z"},
            "Mounts": [{
                "Type": "volume", "Driver": "local",
                "Destination": "/var/lib/smite-node",
                "Source": str(self.data), "Name": "smite-node-data",
            }],
        }
        calls = []
        def inspect(_name):
            calls.append("inspect")
            return container
        def signed_probe():
            calls.append("signed-HMAC-replay")
        def owner():
            calls.append("signed-IR-owner")
            return "5" * 64
        frp = SimpleNamespace(
            node_details=lambda: {"role": role, "state": "COMMITTED"},
            rt=SimpleNamespace(inspect_container=inspect,
                               signed_probe=signed_probe),
            signed_owner_inventory=owner,
        )
        def children(_frp):
            calls.append("persisted-foreign-children")
            return ("optical", "nahavi", "20182")
        def signed_children(_frp, ids):
            calls.append("signed-foreign-children")
            self.assertEqual(ids, ("optical", "nahavi", "20182"))
            return ("6" * 64, "7" * 64, "8" * 64)
        control = SimpleNamespace(
            _rc7_foreign_saved_child_ids=children,
            _rc7_foreign_signed_instances=signed_children,
        )
        proc = {
            "FRPS_PROCESS_LOCAL": "OBSERVED_UNATTESTED",
            "FRPS_INSTANCE_SHA256": "9" * 64,
            "FRPC_PROCESS_LOCAL": "OBSERVED_UNATTESTED",
            "FRPC_INSTANCE_SHA256": "a" * 64,
        }
        broker = {"BROKER_SOCKET_LOCAL": "PRESENT_UNATTESTED",
                  "BROKER_SOCKET_ID_SHA256": "b" * 64}
        def load(_alias, name):
            self.assertIn(name, ("smite-rc7-frp-enrollment.py",
                                 "smite-managed-backhaul-control.py"))
            return frp if name == "smite-rc7-frp-enrollment.py" else control
        return registry, container, calls, proc, broker, load

    def test_retained_legacy_tunnel_registry_snapshot_safe_existing_modes(self):
        registry = self.data / "tunnels.json"
        saved = b'{"existing":{"core":"frp","spec":{"kind":"protected"}}}\n'
        registry.write_bytes(saved)
        # Historical root-owned Smite files are allowed to be readable
        # by others but NEVER writable by others. Never chmod live host.
        for mode in (0o600, 0o640, 0o644, 0o400):
            with self.subTest(mode=oct(mode)), \
                 patch.object(exe, "_retained_registry_root_owned",
                              return_value=True):
                registry.chmod(mode)
                self.assertEqual(
                    exe._retained_saved_tunnel_registry_snapshot(registry),
                    saved)
        for mode in (0o666, 0o620, 0o606):
            with self.subTest(bad_mode=oct(mode)), \
                 patch.object(exe, "_retained_registry_root_owned",
                              return_value=True), \
                 self.assertRaisesRegex(
                     exe.Hold, "RETAINED_REGISTRY_SNAPSHOT_UNTRUSTED"):
                registry.chmod(mode)
                exe._retained_saved_tunnel_registry_snapshot(registry)
        registry.chmod(0o600)
        link = self.data / "registry-link"
        link.symlink_to(registry)
        with patch.object(exe, "_retained_registry_root_owned",
                          return_value=True), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_REGISTRY_SNAPSHOT_UNTRUSTED"):
            exe._retained_saved_tunnel_registry_snapshot(link)
        with patch.object(exe, "_retained_registry_root_owned",
                          return_value=False), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_REGISTRY_SNAPSHOT_UNTRUSTED"):
            exe._retained_saved_tunnel_registry_snapshot(registry)
        self.assertEqual(registry.read_bytes(), saved)

    def test_retained_legacy_registry_snapshot_rejects_mutation_during_read(self):
        registry = self.data / "tunnels.json"
        registry.write_bytes(b'{"existing":{"core":"frp","spec":{}}}\n')
        registry.chmod(0o644)
        original = registry.read_bytes()
        read_real = exe.os.read
        switched = False
        def raced(fd, n):
            nonlocal switched
            result = read_real(fd, n)
            if not switched:
                switched = True
                registry.write_bytes(original + b" ")
            return result
        with patch.object(exe, "_retained_registry_root_owned",
                          return_value=True), \
             patch.object(exe.os, "read", side_effect=raced), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_REGISTRY_CHANGED_DURING_READ"):
            exe._retained_saved_tunnel_registry_snapshot(registry)
        self.assertTrue(switched)

    def test_retained_production_witness_requires_real_scoped_host_before_io(self):
        with patch.object(exe, "_load",
                          side_effect=AssertionError("DOCKER_OR_AGENT_IO")), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_LIVE_WITNESS_SCOPE_UNTRUSTED"):
            exe._retained_live_signed_witness(
                role="ir", expected_node_image=IMAGE, paths=self.paths)
        for role, image in (("KH", IMAGE), ("ir", "tag:mutable"),
                            ("foreign", "sha256:" + "a" * 64)):
            with self.subTest(role=role, image=image), \
                 patch.object(exe, "Paths", return_value=self.paths), \
                 patch.object(exe, "_retained_live_root_required", return_value=True), \
                 patch.object(exe, "_load",
                              side_effect=AssertionError("DOCKER_OR_AGENT_IO")), \
                 self.assertRaisesRegex(
                     exe.Hold, "RETAINED_LIVE_WITNESS_SCOPE_UNTRUSTED"):
                exe._retained_live_signed_witness(
                    role=role, expected_node_image=image, paths=self.paths)

    def test_retained_signed_local_witness_both_roles_and_drift(self):
        for role in ("ir", "foreign"):
            with self.subTest(role=role):
                registry, container, calls, proc, broker, loader = (
                    self._live_witness_test_fixture(role))
                saved = registry.read_bytes()
                with patch.object(exe, "Paths", return_value=self.paths), \
                     patch.object(exe, "_retained_live_root_required", return_value=True), \
                     patch.object(exe, "_retained_registry_root_owned", return_value=True), \
                     patch.object(exe, "_load", side_effect=loader), \
                     patch.object(exe.admission.host, "frp_process_footprint",
                                  return_value=proc), \
                     patch.object(exe.admission.host, "broker_socket_footprint",
                                  return_value=broker):
                    first = exe._retained_live_signed_witness(
                        role=role, expected_node_image=IMAGE, paths=self.paths)
                    second = exe._retained_live_signed_witness(
                        role=role, expected_node_image=IMAGE, paths=self.paths)
                    self.assertEqual(first, second)
                    self.assertRegex(first, r"^[a-f0-9]{64}$")
                    self.assertIn("signed-HMAC-replay", calls)
                    self.assertEqual(calls.count("inspect"), 4)
                    self.assertIn("signed-IR-owner" if role == "ir"
                                  else "signed-foreign-children", calls)
                    # Restart or image drift while the signed HMAC GET is
                    # running must be rejected by the second Docker review.
                    original_started = container["State"]["StartedAt"]
                    def restart():
                        container["State"]["StartedAt"] = "2026-11-07T09:10:00Z"
                    frp_inspect_calls = calls.count("inspect")
                    real_load = loader
                    # Replace the Container ID on the *second* inspect only.
                    def drifting_load(alias, name):
                        module = real_load(alias, name)
                        if name == "smite-rc7-frp-enrollment.py":
                            base_inspect = module.rt.inspect_container
                            def drift_inspect(value):
                                doc = base_inspect(value)
                                if calls.count("inspect") == frp_inspect_calls + 2:
                                    restart()
                                return doc
                            module.rt.inspect_container = drift_inspect
                        return module
                    with patch.object(exe, "_load", side_effect=drifting_load), \
                         self.assertRaisesRegex(
                             exe.Hold, "RETAINED_LIVE_NODE_OR_FRP_DRIFT"):
                        exe._retained_live_signed_witness(
                            role=role, expected_node_image=IMAGE,
                            paths=self.paths)
                    container["State"]["StartedAt"] = original_started
                self.assertEqual(registry.read_bytes(), saved)
                self.assertNotIn(saved.decode(), str(first))

    def test_retained_live_witness_fails_closed_on_missing_signed_proof(self):
        for role in ("ir", "foreign"):
            with self.subTest(role=role):
                registry, container, calls, proc, broker, loader = (
                    self._live_witness_test_fixture(role))
                original = registry.read_bytes()
                with patch.object(exe, "Paths", return_value=self.paths), \
                     patch.object(exe, "_retained_live_root_required", return_value=True), \
                     patch.object(exe, "_retained_registry_root_owned", return_value=True), \
                     patch.object(exe, "_load", side_effect=loader), \
                     patch.object(exe.admission.host, "frp_process_footprint",
                                  return_value=proc), \
                     patch.object(exe.admission.host, "broker_socket_footprint",
                                  return_value=broker):
                    container["Config"]["Image"] = "tag:untrusted"
                    with self.assertRaisesRegex(
                            exe.Hold, "RETAINED_LIVE_IMAGE_PIN_CHANGED"):
                        exe._retained_live_signed_witness(
                            role=role, expected_node_image=IMAGE,
                            paths=self.paths)
                    container["Config"]["Image"] = IMAGE
                    proc["FRPS_PROCESS_LOCAL" if role == "ir"
                         else "FRPC_PROCESS_LOCAL"] = "NOT_OBSERVED"
                    with self.assertRaisesRegex(
                            exe.Hold, "RETAINED_LIVE_FRPS_PROCESS_UNVERIFIED"
                            if role == "ir" else "RETAINED_LIVE_FRPC_PROCESS_UNVERIFIED"):
                        exe._retained_live_signed_witness(
                            role=role, expected_node_image=IMAGE,
                            paths=self.paths)
                self.assertEqual(registry.read_bytes(), original)

    def _live_prepare_test_context(self, role):
        from dataclasses import replace
        # The IR and Foreign role cases share one temporary fixture in
        # this test. Only create the immutable original Manifest once.
        if not (self.config / "engine-state/engines.json").is_file():
            self._retained_review_fixture()
        paths = replace(self.paths, frp_state=self.root / "frp")
        paths.frp_state.mkdir(mode=0o700, exist_ok=True)
        manifest = self.config / "engine-state/engines.json"
        record = {
            "schema": 1, "state": "COMMITTED", "role": role,
            "old": None, "new": exe._sha(manifest.read_bytes()),
            "binaries": {"frpc": "b" * 64, "frps": "c" * 64},
        }
        receipt = paths.frp_state / "record.json"
        receipt.write_text(json.dumps(record, sort_keys=True) + "\n")
        receipt.chmod(0o600)
        report = {
            "RETAINED_NODE_BACKHAUL_BINARY": "OFFICIAL_EXECUTABLE_SHA256_MATCH",
            "IN_PLACE_MANIFEST_TRANSACTION": "PAIR_PLAN_VERIFIED_READ_ONLY",
            "SIGNED_REGISTRY_PAIR_PROOF": "COSIGN_VERIFIED",
            "RETAINED_LOCAL_SIGNED_RUNTIME_WITNESS": "PASS_STABLE_LOCAL_ONLY",
            "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
        }
        inputs = {
            "role": role, "arch": "amd64", "expected_node_image": IMAGE,
            "signed_pair_manifest": self.root / "signed-pair.json",
            "signed_pair_manifest_sha256": "a" * 64,
            "signed_pair_source_sha": "b" * 40,
            "signed_pair_publish_ref": "refs/tags/v2.0.0-rc.7",
            "signed_pair_trusted_root": self.root / "sigstore.json",
            "paths": paths,
        }
        return inputs, manifest, receipt, report

    def test_live_production_prepare_is_private_readonly_and_exact_both_roles(self):
        from contextlib import nullcontext
        for role in ("ir", "foreign"):
            with self.subTest(role=role):
                inputs, manifest, receipt, report = (
                    self._live_prepare_test_context(role))
                originals = (manifest.read_bytes(), receipt.read_bytes())
                self.assertFalse(inputs["paths"].state.exists())
                with patch.object(exe, "Paths", return_value=inputs["paths"]), \
                     patch.object(exe, "_retained_live_root_required",
                                  return_value=True), \
                     patch.object(exe, "review_in_place_binary",
                                  return_value=report) as reviewed, \
                     patch.object(exe, "_retained_live_signed_witness",
                                  return_value="f" * 64) as signed, \
                     patch.object(exe, "_read_only_engine_lock",
                                  side_effect=lambda _: nullcontext()), \
                     patch.object(exe, "_lock",
                                  side_effect=AssertionError("WRITER_OPENED")):
                    evidence = exe._retained_live_prepare(**inputs)
                self.assertEqual(evidence.old_pair, originals)
                self.assertEqual(evidence.role, role)
                self.assertEqual(evidence.runtime_witness, "f" * 64)
                self.assertEqual(evidence.node_image, IMAGE)
                self.assertEqual(reviewed.call_count, 1)
                self.assertEqual(signed.call_count, 2)
                self.assertEqual((manifest.read_bytes(), receipt.read_bytes()),
                                 originals)
                self.assertFalse(inputs["paths"].state.exists())
                self.assertFalse((inputs["paths"].state / "retained-rc7.json").exists())

    def test_live_prepare_rejects_unsigned_missing_and_drifting_evidence(self):
        from contextlib import nullcontext
        inputs, manifest, receipt, report = self._live_prepare_test_context("ir")
        original_pair = (manifest.read_bytes(), receipt.read_bytes())
        negative_reports = (
            {**report, "SIGNED_REGISTRY_PAIR_PROOF": "NOT_SUPPLIED"},
            {**report, "ACTIVATION_GATE": "PASS"},
            {**report, "RETAINED_LOCAL_SIGNED_RUNTIME_WITNESS": "UNVERIFIED"},
            {**report, "REASON": "RECOVERY_REQUIRED"},
        )
        for untrusted in negative_reports:
            with self.subTest(report=untrusted), \
                 patch.object(exe, "Paths", return_value=inputs["paths"]), \
                 patch.object(exe, "_retained_live_root_required",
                              return_value=True), \
                 patch.object(exe, "review_in_place_binary",
                              return_value=untrusted), \
                 patch.object(exe, "_retained_live_signed_witness",
                              side_effect=AssertionError("SIGNED_PROBE_EARLY")), \
                 patch.object(exe, "_read_only_engine_lock",
                              side_effect=AssertionError("LOCK_EARLY")), \
                 self.assertRaisesRegex(
                     exe.Hold, "RETAINED_LIVE_SIGNED_PREFLIGHT_INCOMPLETE"):
                exe._retained_live_prepare(**inputs)
        with patch.object(exe, "Paths", return_value=inputs["paths"]), \
             patch.object(exe, "_retained_live_root_required", return_value=True), \
             patch.object(exe, "review_in_place_binary", return_value=report), \
             patch.object(exe, "_retained_live_signed_witness",
                          side_effect=["f" * 64, "e" * 64]), \
             patch.object(exe, "_read_only_engine_lock",
                          side_effect=lambda _: nullcontext()), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_LIVE_PREPARE_CONCURRENT_DRIFT"):
            exe._retained_live_prepare(**inputs)
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()),
                         original_pair)
        self.assertFalse(inputs["paths"].state.exists())

    def test_common_retained_writer_core_requires_prior_admission_before_lock(self):
        with patch.object(exe, "_lock",
                          side_effect=AssertionError("WRITER_OPENED")), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_PRODUCTION_WRITER_NOT_ADMITTED"):
            exe._retained_step_core(
                exe.Paths(), action="install", role="ir",
                arch="amd64", witness=lambda: "f" * 64)
        # Even a Python caller importing the internal object cannot
        # use it to write on canonical live paths, a misleading unmarked
        # temporary directory or an alternate host alias.
        with patch.object(exe, "_lock",
                          side_effect=AssertionError("WRITER_OPENED")), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_CORE_DISPOSABLE_ADMISSION_REQUIRED"):
            exe._retained_step_core(
                exe.Paths(), action="install", role="ir", arch="amd64",
                witness=lambda: "f" * 64,
                _admission=exe._RETAINED_CI_WRITER_ADMISSION)
        with patch.object(exe, "_lock",
                          side_effect=AssertionError("WRITER_OPENED")), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_CORE_DISPOSABLE_ADMISSION_REQUIRED"):
            exe._retained_step_core(
                self.paths, action="install", role="ir", arch="amd64",
                witness=lambda: "f" * 64,
                _admission=exe._RETAINED_CI_WRITER_ADMISSION)
        # A forged string cannot satisfy the internal CI entry capability.
        with patch.object(exe, "_lock",
                          side_effect=AssertionError("WRITER_OPENED")), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_PRODUCTION_WRITER_NOT_ADMITTED"):
            exe._retained_step_core(
                self.paths, action="install", role="ir", arch="amd64",
                witness=lambda: "f" * 64,
                _admission="RETAINED_CI_WRITER_ADMISSION")

    def test_live_ir_signed_metadata_canary_only_commits_after_both_proofs(self):
        from types import SimpleNamespace
        import unittest.mock as mock
        paths = exe.Paths()
        prepared = exe.RetainedLivePrepared(
            paths=paths, role="ir", arch="amd64", node_image=IMAGE,
            old_pair=(b"old-manifest", b"old-receipt"),
            runtime_witness="f" * 64)
        initial = {
            "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
            "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
            "RC7_IR_SIGNED_FRPS_OWNER": "PASS_SIGNED_AGENT_LISTENER_STABLE",
            "NODE_RECREATED": "NO",
            "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
        }
        after = {
            **initial, "RC7_BACKHAUL_ENGINE": "READY_SIGNED_INVENTORY",
            "RC7_BACKHAUL_MANIFEST_PLAN":
                "COMMITTED_PAIR_VERIFIED_READ_ONLY",
        }
        control = SimpleNamespace(
            verify_rc7_bundled_backhaul=mock.Mock(
                side_effect=[initial, after]))
        with patch.object(exe, "_retained_live_prepare",
                          return_value=prepared) as prepare, \
             patch.object(exe, "_load", return_value=control), \
             patch.object(exe, "_mkdir_chain") as directories, \
             patch.object(exe, "_retained_step_core",
                          return_value="COMMITTED") as core, \
             patch.object(exe, "_retained_live_signed_witness",
                          return_value="f" * 64):
            report = exe._retained_live_ir_canary(
                arch="amd64", expected_node_image=IMAGE,
                signed_pair_manifest=Path("/signed-pair.json"),
                signed_pair_manifest_sha256="1" * 64,
                signed_pair_source_sha="2" * 40,
                signed_pair_publish_ref="refs/tags/v2.0.0-rc.7",
                signed_pair_trusted_root=Path("/sigstore.json"))
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(core.call_count, 1)
        self.assertEqual(core.call_args.kwargs["action"], "install")
        self.assertEqual(core.call_args.kwargs["role"], "ir")
        self.assertEqual(core.call_args.kwargs["expected_before"],
                         prepared.old_pair)
        self.assertEqual(core.call_args.kwargs["expected_witness"],
                         prepared.runtime_witness)
        self.assertIs(core.call_args.kwargs["_admission"], prepared)
        self.assertEqual(directories.call_count, 1)
        self.assertEqual(
            report["RETAINED_IR_BACKHAUL_ENROLLMENT"],
            "PASS_SIGNED_METADATA_ONLY")
        self.assertEqual(report["BACKHAUL_TUNNEL_ACTIVATED"], "NO")
        self.assertEqual(report["FOREIGN_NODE_CHANGED"], "NO")

    def test_live_ir_canary_rejects_unverified_signed_before_writer(self):
        from types import SimpleNamespace
        import unittest.mock as mock
        prepared = exe.RetainedLivePrepared(
            paths=exe.Paths(), role="ir", arch="amd64", node_image=IMAGE,
            old_pair=(b"old-manifest", b"old-receipt"),
            runtime_witness="f" * 64)
        false_initial = {
            "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
            "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
            "RC7_IR_SIGNED_FRPS_OWNER": "PASS_SIGNED_AGENT_LISTENER_STABLE",
            "NODE_RECREATED": "YES", "INSTALL_ALLOWED": "NO",
            "ACTIVATION_GATE": "HOLD",
        }
        control = SimpleNamespace(
            verify_rc7_bundled_backhaul=mock.Mock(
                return_value=false_initial))
        with patch.object(exe, "_retained_live_prepare",
                          return_value=prepared), \
             patch.object(exe, "_load", return_value=control), \
             patch.object(exe, "_mkdir_chain",
                          side_effect=AssertionError("DIRECTORY_WRITTEN")), \
             patch.object(exe, "_retained_step_core",
                          side_effect=AssertionError("WRITER_OPENED")), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_LIVE_IR_SIGNED_INITIAL_HOLD"):
            exe._retained_live_ir_canary(
                arch="amd64", expected_node_image=IMAGE,
                signed_pair_manifest=Path("/signed-pair.json"),
                signed_pair_manifest_sha256="1" * 64,
                signed_pair_source_sha="2" * 40,
                signed_pair_publish_ref="refs/tags/v2.0.0-rc.7",
                signed_pair_trusted_root=Path("/sigstore.json"))

    def test_live_ir_failed_postcommit_must_rollback_without_foreign_mutation(self):
        from types import SimpleNamespace
        import unittest.mock as mock
        prepared = exe.RetainedLivePrepared(
            paths=exe.Paths(), role="ir", arch="amd64", node_image=IMAGE,
            old_pair=(b"old-manifest", b"old-receipt"),
            runtime_witness="f" * 64)
        initial = {
            "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
            "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
            "RC7_IR_SIGNED_FRPS_OWNER": "PASS_SIGNED_AGENT_LISTENER_STABLE",
            "NODE_RECREATED": "NO",
            "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
        }
        bad_post = {**initial, "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY"}
        control = SimpleNamespace(verify_rc7_bundled_backhaul=mock.Mock(
            side_effect=[initial, bad_post]))
        with patch.object(exe, "_retained_live_prepare",
                          return_value=prepared), \
             patch.object(exe, "_load", return_value=control), \
             patch.object(exe, "_mkdir_chain"), \
             patch.object(exe, "_retained_step_core",
                          return_value="COMMITTED"), \
             patch.object(exe, "_retained_live_ir_rollback",
                          return_value={"RETAINED_IR_BACKHAUL_ROLLBACK": "PASS"}
                          ) as rollback, \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_LIVE_IR_POSTCOMMIT_ROLLED_BACK"):
            exe._retained_live_ir_canary(
                arch="amd64", expected_node_image=IMAGE,
                signed_pair_manifest=Path("/signed-pair.json"),
                signed_pair_manifest_sha256="1" * 64,
                signed_pair_source_sha="2" * 40,
                signed_pair_publish_ref="refs/tags/v2.0.0-rc.7",
                signed_pair_trusted_root=Path("/sigstore.json"))
        rollback.assert_called_once_with(
            arch="amd64", expected_node_image=IMAGE)

    def test_live_ir_recovery_corrupt_or_wrong_role_fails_before_lock(self):
        from dataclasses import replace
        paths = replace(self.paths, state=self.root / "retained-live-state")
        paths.state.mkdir(mode=0o700)
        receipt = self.root / "private-original"
        originals = (b'{"schema": 1}', b'{"role": "ir"}')
        record = {
            "schema": 1, "role": "ir",
            "binary": exe.package.OFFICIAL_BINARY_SHA256["amd64"],
            "witness": "f" * 64, "phase": "PREPARED",
            "manifest": originals[0].hex(), "receipt": originals[1].hex(),
        }
        for scenario in ("bad-checksum", "wrong-role", "wrong-witness"):
            candidate = dict(record)
            if scenario == "wrong-role":
                candidate["role"] = "foreign"
            if scenario == "wrong-witness":
                candidate["witness"] = "e" * 64
            envelope = {
                "record": candidate,
                "sha256": exe._sha(
                    json.dumps(candidate, sort_keys=True).encode()),
            }
            if scenario == "bad-checksum":
                envelope["sha256"] = "0" * 64
            data = (json.dumps(envelope, sort_keys=True) + "\n").encode()
            with self.subTest(scenario=scenario), \
                 patch.object(exe, "Paths", return_value=paths), \
                 patch.object(exe, "_retained_live_root_required",
                              return_value=True), \
                 patch.object(exe, "_retained_live_signed_witness",
                              return_value="f" * 64), \
                 patch.object(exe.pair, "_pair_read_private",
                              return_value=data), \
                 patch.object(exe, "_retained_step_core",
                              side_effect=AssertionError("WRITER_OPENED")), \
                 self.assertRaisesRegex(
                     exe.Hold, "RETAINED_LIVE_IR_RECOVERY_JOURNAL_UNTRUSTED"):
                exe._retained_live_ir_rollback(
                    arch="amd64", expected_node_image=IMAGE)

    def test_ir_live_core_detects_config_drift_before_own_journal(self):
        from contextlib import nullcontext
        approved = exe.RetainedLivePrepared(
            paths=exe.Paths(), role="ir", arch="amd64",
            node_image=IMAGE, old_pair=(b"before1", b"before2"),
            runtime_witness="f" * 64,
            node_env_sha256="a" * 64,
            node_compose_sha256="b" * 64)
        with patch.object(exe, "_retained_live_root_required",
                          return_value=True), \
             patch.object(exe, "_lock",
                          side_effect=lambda _: nullcontext()) as lock, \
             patch.object(exe, "_read", return_value=b"unexpected-env"), \
             patch.object(exe, "_retained_files",
                          side_effect=AssertionError("JOURNAL_OPENED")), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_LIVE_NODE_CONFIG_CHANGED_BEFORE_WRITE"):
            exe._retained_step_core(
                exe.Paths(), action="install", role="ir", arch="amd64",
                witness=lambda: "f" * 64, expected_before=approved.old_pair,
                expected_witness=approved.runtime_witness,
                _admission=approved)
        self.assertEqual(lock.call_count, 1)

    def test_ir_canary_compensates_interrupted_prepared_write(self):
        from types import SimpleNamespace
        import unittest.mock as mock
        prepared = exe.RetainedLivePrepared(
            paths=exe.Paths(), role="ir", arch="amd64", node_image=IMAGE,
            old_pair=(b"old-manifest", b"old-receipt"),
            runtime_witness="f" * 64)
        initial = {
            "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
            "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
            "RC7_IR_SIGNED_FRPS_OWNER": "PASS_SIGNED_AGENT_LISTENER_STABLE",
            "NODE_RECREATED": "NO",
            "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
        }
        control = SimpleNamespace(
            verify_rc7_bundled_backhaul=mock.Mock(return_value=initial))
        with patch.object(exe, "_retained_live_prepare",
                          return_value=prepared), \
             patch.object(exe, "_load", return_value=control), \
             patch.object(exe, "_mkdir_chain"), \
             patch.object(exe, "_retained_step_core",
                          side_effect=exe.Hold("PREPARED_WRITE_FAILED")), \
             patch.object(exe.os.path, "lexists", return_value=True), \
             patch.object(exe, "_retained_live_ir_rollback",
                          return_value={"RETAINED_IR_BACKHAUL_ROLLBACK": "PASS"}
                          ) as rollback, \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_LIVE_IR_PARTIAL_WRITE_ROLLED_BACK"):
            exe._retained_live_ir_canary(
                arch="amd64", expected_node_image=IMAGE,
                signed_pair_manifest=Path("/signed-pair.json"),
                signed_pair_manifest_sha256="1" * 64,
                signed_pair_source_sha="2" * 40,
                signed_pair_publish_ref="refs/tags/v2.0.0-rc.7",
                signed_pair_trusted_root=Path("/sigstore.json"))
        rollback.assert_called_once_with(
            arch="amd64", expected_node_image=IMAGE)

    def test_ir_recovery_resumes_terminal_seal_without_recreating_journal(self):
        from dataclasses import replace
        from types import SimpleNamespace
        import unittest.mock as mock
        paths = replace(self.paths, state=self.root / "ir-retained-sealed")
        paths.state.mkdir(mode=0o700)
        seal = paths.state / "retained-rc7-cleanup.json"
        seal.write_text("private sealed cleanup fixture\n")
        seal.chmod(0o600)
        self.assertFalse((paths.state / "retained-rc7.json").exists())
        prior = {
            "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
            "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
            "NODE_RECREATED": "NO",
        }
        control = SimpleNamespace(
            verify_rc7_bundled_backhaul=mock.Mock(return_value=prior))
        def read_pair(path, **kwargs):
            if path.name == "engines.json":
                return b'{"schema":1,"engines":{"frp":{}}}'
            if path.name == "record.json":
                return b'{"state":"COMMITTED","role":"ir"}'
            raise AssertionError("UNEXPECTED_READ")
        with patch.object(exe, "Paths", return_value=paths), \
             patch.object(exe, "_retained_live_root_required",
                          return_value=True), \
             patch.object(exe, "_retained_live_signed_witness",
                          return_value="f" * 64), \
             patch.object(exe.pair, "_pair_read_private",
                          side_effect=read_pair), \
             patch.object(exe.pair, "_pair_expected_transition",
                          return_value=(b"next-manifest", b"next-receipt")), \
             patch.object(exe, "_load", return_value=control), \
             patch.object(exe, "_retained_step_core",
                          return_value="CLEANED") as core:
            result = exe._retained_live_ir_rollback(
                arch="amd64", expected_node_image=IMAGE)
        self.assertEqual(
            result["RETAINED_IR_BACKHAUL_ROLLBACK"],
            "PASS_SIGNED_SEALED_CLEANUP_RECOVERED")
        self.assertEqual(core.call_count, 1)
        self.assertEqual(core.call_args.kwargs["action"], "cleanup")
        self.assertEqual(core.call_args.kwargs["role"], "ir")
        self.assertFalse((paths.state / "retained-rc7.json").exists())

    def test_live_cross_role_prepared_record_cannot_authorize_writer(self):
        for approved_role, requested_role in (("ir", "foreign"),
                                              ("foreign", "ir")):
            with self.subTest(approved=approved_role, requested=requested_role):
                prepared = exe.RetainedLivePrepared(
                    paths=exe.Paths(), role=approved_role, arch="amd64",
                    node_image=IMAGE, old_pair=(b"before1", b"before2"),
                    runtime_witness="f" * 64,
                    node_env_sha256="1" * 64, node_compose_sha256="2" * 64)
                with patch.object(exe, "_retained_live_root_required",
                                  return_value=True), \
                     patch.object(exe, "_lock",
                                  side_effect=AssertionError("LOCK_ACQUIRED")), \
                     self.assertRaisesRegex(
                         exe.Hold, "RETAINED_LIVE_IR_WRITER_NOT_ADMITTED"):
                    exe._retained_step_core(
                        exe.Paths(), action="install", role=requested_role,
                        arch="amd64", witness=lambda: "f" * 64,
                        expected_before=prepared.old_pair,
                        expected_witness=prepared.runtime_witness,
                        _admission=prepared)

    def test_live_foreign_signed_metadata_canary_only_commits_after_both_proofs(self):
        from types import SimpleNamespace
        import unittest.mock as mock
        paths = exe.Paths()
        prepared = exe.RetainedLivePrepared(
            paths=paths, role="foreign", arch="amd64", node_image=IMAGE,
            old_pair=(b"old-manifest", b"old-receipt"),
            runtime_witness="f" * 64)
        initial = {
            "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
            "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
            "RC7_FOREIGN_LOCAL_SIGNED_FRPC_CHILDREN": "PASS_STABLE_LOCAL_ONLY",
            "NODE_RECREATED": "NO",
            "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
        }
        after = {
            **initial, "RC7_BACKHAUL_ENGINE": "READY_SIGNED_INVENTORY",
            "RC7_BACKHAUL_MANIFEST_PLAN":
                "COMMITTED_PAIR_VERIFIED_READ_ONLY",
        }
        control = SimpleNamespace(
            verify_rc7_bundled_backhaul=mock.Mock(
                side_effect=[initial, after]))
        with patch.object(exe, "_retained_live_prepare",
                          return_value=prepared) as prepare, \
             patch.object(exe, "_load", return_value=control), \
             patch.object(exe, "_mkdir_chain") as directories, \
             patch.object(exe, "_retained_step_core",
                          return_value="COMMITTED") as core, \
             patch.object(exe, "_retained_live_signed_witness",
                          return_value="f" * 64):
            report = exe._retained_live_foreign_canary(
                arch="amd64", expected_node_image=IMAGE,
                signed_pair_manifest=Path("/signed-pair.json"),
                signed_pair_manifest_sha256="1" * 64,
                signed_pair_source_sha="2" * 40,
                signed_pair_publish_ref="refs/tags/v2.0.0-rc.7",
                signed_pair_trusted_root=Path("/sigstore.json"))
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(core.call_count, 1)
        self.assertEqual(core.call_args.kwargs["action"], "install")
        self.assertEqual(core.call_args.kwargs["role"], "foreign")
        self.assertEqual(core.call_args.kwargs["expected_before"],
                         prepared.old_pair)
        self.assertEqual(core.call_args.kwargs["expected_witness"],
                         prepared.runtime_witness)
        self.assertIs(core.call_args.kwargs["_admission"], prepared)
        self.assertEqual(directories.call_count, 1)
        self.assertEqual(
            report["RETAINED_FOREIGN_BACKHAUL_ENROLLMENT"],
            "PASS_SIGNED_METADATA_ONLY")
        self.assertEqual(report["BACKHAUL_TUNNEL_ACTIVATED"], "NO")
        self.assertEqual(report["IR_NODE_CHANGED"], "NO")

    def test_live_foreign_canary_rejects_unverified_signed_before_writer(self):
        from types import SimpleNamespace
        import unittest.mock as mock
        prepared = exe.RetainedLivePrepared(
            paths=exe.Paths(), role="foreign", arch="amd64", node_image=IMAGE,
            old_pair=(b"old-manifest", b"old-receipt"),
            runtime_witness="f" * 64)
        false_initial = {
            "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
            "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
            "RC7_FOREIGN_LOCAL_SIGNED_FRPC_CHILDREN": "PASS_STABLE_LOCAL_ONLY",
            "NODE_RECREATED": "YES", "INSTALL_ALLOWED": "NO",
            "ACTIVATION_GATE": "HOLD",
        }
        control = SimpleNamespace(
            verify_rc7_bundled_backhaul=mock.Mock(
                return_value=false_initial))
        with patch.object(exe, "_retained_live_prepare",
                          return_value=prepared), \
             patch.object(exe, "_load", return_value=control), \
             patch.object(exe, "_mkdir_chain",
                          side_effect=AssertionError("DFOREIGNECTORY_WRITTEN")), \
             patch.object(exe, "_retained_step_core",
                          side_effect=AssertionError("WRITER_OPENED")), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_LIVE_FOREIGN_SIGNED_INITIAL_HOLD"):
            exe._retained_live_foreign_canary(
                arch="amd64", expected_node_image=IMAGE,
                signed_pair_manifest=Path("/signed-pair.json"),
                signed_pair_manifest_sha256="1" * 64,
                signed_pair_source_sha="2" * 40,
                signed_pair_publish_ref="refs/tags/v2.0.0-rc.7",
                signed_pair_trusted_root=Path("/sigstore.json"))

    def test_live_foreign_failed_postcommit_must_rollback_without_foreign_mutation(self):
        from types import SimpleNamespace
        import unittest.mock as mock
        prepared = exe.RetainedLivePrepared(
            paths=exe.Paths(), role="foreign", arch="amd64", node_image=IMAGE,
            old_pair=(b"old-manifest", b"old-receipt"),
            runtime_witness="f" * 64)
        initial = {
            "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
            "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
            "RC7_FOREIGN_LOCAL_SIGNED_FRPC_CHILDREN": "PASS_STABLE_LOCAL_ONLY",
            "NODE_RECREATED": "NO",
            "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
        }
        bad_post = {**initial, "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY"}
        control = SimpleNamespace(verify_rc7_bundled_backhaul=mock.Mock(
            side_effect=[initial, bad_post]))
        with patch.object(exe, "_retained_live_prepare",
                          return_value=prepared), \
             patch.object(exe, "_load", return_value=control), \
             patch.object(exe, "_mkdir_chain"), \
             patch.object(exe, "_retained_step_core",
                          return_value="COMMITTED"), \
             patch.object(exe, "_retained_live_foreign_rollback",
                          return_value={"RETAINED_FOREIGN_BACKHAUL_ROLLBACK": "PASS"}
                          ) as rollback, \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_LIVE_FOREIGN_POSTCOMMIT_ROLLED_BACK"):
            exe._retained_live_foreign_canary(
                arch="amd64", expected_node_image=IMAGE,
                signed_pair_manifest=Path("/signed-pair.json"),
                signed_pair_manifest_sha256="1" * 64,
                signed_pair_source_sha="2" * 40,
                signed_pair_publish_ref="refs/tags/v2.0.0-rc.7",
                signed_pair_trusted_root=Path("/sigstore.json"))
        rollback.assert_called_once_with(
            arch="amd64", expected_node_image=IMAGE)

    def test_live_foreign_recovery_corrupt_or_wrong_role_fails_before_lock(self):
        from dataclasses import replace
        paths = replace(self.paths, state=self.root / "retained-live-state")
        paths.state.mkdir(mode=0o700)
        receipt = self.root / "private-original"
        originals = (b'{"schema": 1}', b'{"role": "foreign"}')
        record = {
            "schema": 1, "role": "foreign",
            "binary": exe.package.OFFICIAL_BINARY_SHA256["amd64"],
            "witness": "f" * 64, "phase": "PREPARED",
            "manifest": originals[0].hex(), "receipt": originals[1].hex(),
        }
        for scenario in ("bad-checksum", "wrong-role", "wrong-witness"):
            candidate = dict(record)
            if scenario == "wrong-role":
                candidate["role"] = "ir"
            if scenario == "wrong-witness":
                candidate["witness"] = "e" * 64
            envelope = {
                "record": candidate,
                "sha256": exe._sha(
                    json.dumps(candidate, sort_keys=True).encode()),
            }
            if scenario == "bad-checksum":
                envelope["sha256"] = "0" * 64
            data = (json.dumps(envelope, sort_keys=True) + "\n").encode()
            with self.subTest(scenario=scenario), \
                 patch.object(exe, "Paths", return_value=paths), \
                 patch.object(exe, "_retained_live_root_required",
                              return_value=True), \
                 patch.object(exe, "_retained_live_signed_witness",
                              return_value="f" * 64), \
                 patch.object(exe.pair, "_pair_read_private",
                              return_value=data), \
                 patch.object(exe, "_retained_step_core",
                              side_effect=AssertionError("WRITER_OPENED")), \
                 self.assertRaisesRegex(
                     exe.Hold, "RETAINED_LIVE_FOREIGN_RECOVERY_JOURNAL_UNTRUSTED"):
                exe._retained_live_foreign_rollback(
                    arch="amd64", expected_node_image=IMAGE)

    def test_foreign_live_core_detects_config_drift_before_own_journal(self):
        from contextlib import nullcontext
        approved = exe.RetainedLivePrepared(
            paths=exe.Paths(), role="foreign", arch="amd64",
            node_image=IMAGE, old_pair=(b"before1", b"before2"),
            runtime_witness="f" * 64,
            node_env_sha256="a" * 64,
            node_compose_sha256="b" * 64)
        with patch.object(exe, "_retained_live_root_required",
                          return_value=True), \
             patch.object(exe, "_lock",
                          side_effect=lambda _: nullcontext()) as lock, \
             patch.object(exe, "_read", return_value=b"unexpected-env"), \
             patch.object(exe, "_retained_files",
                          side_effect=AssertionError("JOURNAL_OPENED")), \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_LIVE_NODE_CONFIG_CHANGED_BEFORE_WRITE"):
            exe._retained_step_core(
                exe.Paths(), action="install", role="foreign", arch="amd64",
                witness=lambda: "f" * 64, expected_before=approved.old_pair,
                expected_witness=approved.runtime_witness,
                _admission=approved)
        self.assertEqual(lock.call_count, 1)

    def test_foreign_canary_compensates_interrupted_prepared_write(self):
        from types import SimpleNamespace
        import unittest.mock as mock
        prepared = exe.RetainedLivePrepared(
            paths=exe.Paths(), role="foreign", arch="amd64", node_image=IMAGE,
            old_pair=(b"old-manifest", b"old-receipt"),
            runtime_witness="f" * 64)
        initial = {
            "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
            "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
            "RC7_FOREIGN_LOCAL_SIGNED_FRPC_CHILDREN": "PASS_STABLE_LOCAL_ONLY",
            "NODE_RECREATED": "NO",
            "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
        }
        control = SimpleNamespace(
            verify_rc7_bundled_backhaul=mock.Mock(return_value=initial))
        with patch.object(exe, "_retained_live_prepare",
                          return_value=prepared), \
             patch.object(exe, "_load", return_value=control), \
             patch.object(exe, "_mkdir_chain"), \
             patch.object(exe, "_retained_step_core",
                          side_effect=exe.Hold("PREPARED_WRITE_FAILED")), \
             patch.object(exe.os.path, "lexists", return_value=True), \
             patch.object(exe, "_retained_live_foreign_rollback",
                          return_value={"RETAINED_FOREIGN_BACKHAUL_ROLLBACK": "PASS"}
                          ) as rollback, \
             self.assertRaisesRegex(
                 exe.Hold, "RETAINED_LIVE_FOREIGN_PARTIAL_WRITE_ROLLED_BACK"):
            exe._retained_live_foreign_canary(
                arch="amd64", expected_node_image=IMAGE,
                signed_pair_manifest=Path("/signed-pair.json"),
                signed_pair_manifest_sha256="1" * 64,
                signed_pair_source_sha="2" * 40,
                signed_pair_publish_ref="refs/tags/v2.0.0-rc.7",
                signed_pair_trusted_root=Path("/sigstore.json"))
        rollback.assert_called_once_with(
            arch="amd64", expected_node_image=IMAGE)

    def test_foreign_recovery_resumes_terminal_seal_without_recreating_journal(self):
        from dataclasses import replace
        from types import SimpleNamespace
        import unittest.mock as mock
        paths = replace(self.paths, state=self.root / "ir-retained-sealed")
        paths.state.mkdir(mode=0o700)
        seal = paths.state / "retained-rc7-cleanup.json"
        seal.write_text("private sealed cleanup fixture\n")
        seal.chmod(0o600)
        self.assertFalse((paths.state / "retained-rc7.json").exists())
        prior = {
            "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
            "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
            "NODE_RECREATED": "NO",
        }
        control = SimpleNamespace(
            verify_rc7_bundled_backhaul=mock.Mock(return_value=prior))
        def read_pair(path, **kwargs):
            if path.name == "engines.json":
                return b'{"schema":1,"engines":{"frp":{}}}'
            if path.name == "record.json":
                return b'{"state":"COMMITTED","role":"foreign"}'
            raise AssertionError("UNEXPECTED_READ")
        with patch.object(exe, "Paths", return_value=paths), \
             patch.object(exe, "_retained_live_root_required",
                          return_value=True), \
             patch.object(exe, "_retained_live_signed_witness",
                          return_value="f" * 64), \
             patch.object(exe.pair, "_pair_read_private",
                          side_effect=read_pair), \
             patch.object(exe.pair, "_pair_expected_transition",
                          return_value=(b"next-manifest", b"next-receipt")), \
             patch.object(exe, "_load", return_value=control), \
             patch.object(exe, "_retained_step_core",
                          return_value="CLEANED") as core:
            result = exe._retained_live_foreign_rollback(
                arch="amd64", expected_node_image=IMAGE)
        self.assertEqual(
            result["RETAINED_FOREIGN_BACKHAUL_ROLLBACK"],
            "PASS_SIGNED_SEALED_CLEANUP_RECOVERED")
        self.assertEqual(core.call_count, 1)
        self.assertEqual(core.call_args.kwargs["action"], "cleanup")
        self.assertEqual(core.call_args.kwargs["role"], "foreign")
        self.assertFalse((paths.state / "retained-rc7.json").exists())

    def test_foreign_cli_denies_snapshot_only_without_writer_or_agent(self):
        import io
        from unittest import mock
        argv = [
            "retained-host-executor", "install-retained-foreign",
            "--arch", "amd64", "--expected-node-image", IMAGE,
            "--confirm-role", "INSTALL-RETAINED-BACKHAUL-FOREIGN",
            "--signed-pair-manifest", "/proof.json",
            "--signed-pair-manifest-sha256", "a" * 64,
            "--signed-pair-source-sha", "b" * 40,
            "--signed-pair-publish-ref", "refs/tags/v2.0.0-rc.7",
            "--signed-pair-trusted-root", "/trusted.json",
        ]
        with patch.object(exe.sys, "argv", argv), \
             patch.object(exe.os, "geteuid", return_value=0), \
             patch.object(exe, "_retained_live_foreign_canary",
                          side_effect=AssertionError("FOREIGN_WRITER_STARTED")), \
             mock.patch("builtins.input",
                        side_effect=AssertionError("PROMPT_WITHOUT_SNAPSHOT")), \
             mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(exe.main(), 2)
        self.assertIn("RETAINED_LIVE_FOREIGN_RECOVERY_APPROVAL_REQUIRED",
                      stderr.getvalue())
        self.assertFalse(self.state.exists())

    def test_foreign_cli_requires_interactive_exact_recovery_challenge(self):
        import io
        from unittest import mock
        argv = [
            "retained-host-executor", "install-retained-foreign",
            "--arch", "amd64", "--expected-node-image", IMAGE,
            "--confirm-role", "INSTALL-RETAINED-BACKHAUL-FOREIGN",
            "--confirm-snapshot-and-console", exe.SNAPSHOT_CONFIRM,
        ]
        for interactive, response in (
                (False, "INSTALL-RETAINED-BACKHAUL-FOREIGN"),
                (True, "INSTALL-RETAINED-BACKHAUL-IR"),
                (True, "")):
            with self.subTest(interactive=interactive, response=response), \
                 patch.object(exe.sys, "argv", argv), \
                 patch.object(exe.os, "geteuid", return_value=0), \
                 patch.object(exe.sys.stdin, "isatty",
                              return_value=interactive), \
                 mock.patch("builtins.input", return_value=response), \
                 patch.object(exe, "_retained_live_foreign_canary",
                              side_effect=AssertionError("FOREIGN_WRITER_STARTED")), \
                 mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(exe.main(), 2)
                self.assertIn(
                    "RETAINED_LIVE_FOREIGN_RECOVERY_APPROVAL_REQUIRED",
                    stderr.getvalue())

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

    def test_retained_read_only_preflight_holds_each_competing_recovery_marker(self):
        from dataclasses import replace
        runner, audit = self._retained_review_fixture()
        paths = replace(self.paths, frp_state=self.root / "frp")
        manifest = self.config / "engine-state/engines.json"
        for path in (
            self.state / "journal",
            paths.frp_state / "record.next",
            manifest.with_name("engines.json.rc7-next"),
            manifest.with_name("engines.json.rc7-rollback-next"),
        ):
            for kind in ("regular", "dangling-symlink"):
                with self.subTest(path=path.name, kind=kind):
                    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    if kind == "regular":
                        path.write_bytes(b"pending recovery")
                    else:
                        path.symlink_to(self.root / "never-present")
                    with patch.object(exe.admission, "report", return_value=audit):
                        result = exe.review_in_place_binary(
                            expected_node_image=IMAGE, arch="amd64",
                            paths=paths, runner=runner)
                    self.assertEqual(result["REASON"], "COMPETING_RECOVERY_REQUIRED")
                    self.assertEqual(result["INSTALL_ALLOWED"], "NO")
                    self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
                    self.assertEqual(result["IN_PLACE_MANIFEST_TRANSACTION"], "NOT_IMPLEMENTED")
                    self.assertEqual(runner.calls, [], "preflight called Docker")
                    path.unlink()

    def test_retained_read_only_blocks_late_frp_and_manifest_recovery(self):
        from dataclasses import replace
        runner, audit = self._retained_review_fixture()
        frp = self.root / "frp"
        frp.mkdir(mode=0o700)
        manifest = self.config / "engine-state/engines.json"
        receipt = frp / "record.json"
        receipt.write_text(json.dumps({"schema": 1, "state": "COMMITTED",
            "role": "ir", "old": None, "new": exe._sha(manifest.read_bytes()),
            "binaries": {"frpc": "b"*64, "frps": "c"*64}}))
        receipt.chmod(0o600)
        paths = replace(self.paths, frp_state=frp)
        signed = {**audit, "NODE_ROLE": "IR",
                  "SIGNED_REGISTRY_PAIR_PROOF": "COSIGN_VERIFIED"}
        protected = (manifest.read_bytes(), receipt.read_bytes(),
                     (self.data / "tunnels.json").read_bytes())
        targets = (
            paths.frp_state / "record.next",
            manifest.with_name("engines.json.rc7-next"),
            manifest.with_name("engines.json.rc7-rollback-next"),
            paths.state / "journal",
        )
        for target in targets:
            with self.subTest(target=target.name):
                runner.calls.clear()
                target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                def raced(args, **kwargs):
                    output = runner(args, **kwargs)
                    if args[:3] == ["docker", "exec", "-i"]:
                        target.write_bytes(b"unresolved")
                    return output
                with patch.object(exe.admission, "report", return_value=signed):
                    result = exe.review_in_place_binary(
                        expected_node_image=IMAGE, arch="amd64",
                        paths=paths, runner=raced)
                self.assertEqual(result["REASON"], "COMPETING_RECOVERY_REQUIRED")
                self.assertEqual(result["INSTALL_ALLOWED"], "NO")
                self.assertEqual(result["IN_PLACE_MANIFEST_TRANSACTION"], "NOT_IMPLEMENTED")
                self.assertEqual(protected, (
                    manifest.read_bytes(), receipt.read_bytes(),
                    (self.data / "tunnels.json").read_bytes()))
                target.unlink()
        # A competing writer may appear after the paired planner rather than
        # during binary verification; this must also HOLD.
        original_plan = exe.pair._pair_expected_transition
        def during_plan(*args, **kwargs):
            candidate = original_plan(*args, **kwargs)
            targets[0].write_bytes(b"unfinished journal")
            return candidate
        with patch.object(exe.admission, "report", return_value=signed), \
                patch.object(exe.pair, "_pair_expected_transition",
                             side_effect=during_plan):
            result = exe.review_in_place_binary(
                expected_node_image=IMAGE, arch="amd64",
                paths=paths, runner=runner)
        self.assertEqual(result["REASON"], "COMPETING_RECOVERY_REQUIRED")
        targets[0].unlink()
        with patch.object(exe.admission, "report", return_value=signed):
            clean = exe.review_in_place_binary(
                expected_node_image=IMAGE, arch="amd64",
                paths=paths, runner=runner)
        self.assertEqual(clean["IN_PLACE_MANIFEST_TRANSACTION"],
                         "PAIR_PLAN_VERIFIED_READ_ONLY")
        self.assertEqual(clean["INSTALL_ALLOWED"], "NO")
        self.assertEqual(protected, (manifest.read_bytes(),
                         receipt.read_bytes(), (self.data / "tunnels.json").read_bytes()))

    def test_retained_signed_review_rejects_unlocked_receipt_and_recovery_races(self):
        from dataclasses import replace
        runner, audit = self._retained_review_fixture()
        manifest = self.config / "engine-state/engines.json"
        frp = self.root / "frp"
        frp.mkdir(mode=0o700)
        receipt = frp / "record.json"
        record = {"schema": 1, "state": "COMMITTED", "role": "ir",
                  "old": None, "new": exe._sha(manifest.read_bytes()),
                  "binaries": {"frpc": "b"*64, "frps": "c"*64}}
        receipt.write_text(json.dumps(record))
        receipt.chmod(0o600)
        original = receipt.read_bytes()
        paths = replace(self.paths, frp_state=frp)
        evidence = {**audit, "NODE_ROLE": "IR",
                    "SIGNED_REGISTRY_PAIR_PROOF": "COSIGN_VERIFIED"}
        saved_manifest = manifest.read_bytes()
        saved_tunnels = (self.data / "tunnels.json").read_bytes()
        for race, expected in (
            ("receipt", "RETAINED_FRP_RECEIPT_CHANGED_DURING_REVIEW"),
            ("journal", "RETAINED_JOURNAL_REQUIRES_LOCKED_REVIEW"),
            ("cleanup-seal", "RETAINED_CLEANUP_RECOVERY_REQUIRED"),
        ):
            with self.subTest(race=race):
                runner.calls.clear()
                receipt.write_bytes(original)
                pending = self.state / (
                    "retained-rc7.json" if race == "journal"
                    else "retained-rc7-cleanup.json")
                if pending.exists():
                    pending.unlink()

                def raced(args, **kwargs):
                    result = runner(args, **kwargs)
                    if args[:3] == ["docker", "exec", "-i"]:
                        if race == "receipt":
                            # Valid JSON with identical semantic manifest
                            # binding still represents changed exact bytes.
                            receipt.write_bytes(original + b" ")
                        else:
                            self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
                            pending.write_text("unresolved competing recovery")
                    return result

                with patch.object(exe.admission, "report", return_value=evidence):
                    result = exe.review_in_place_binary(
                        expected_node_image=IMAGE, arch="amd64",
                        paths=paths, runner=raced)
                self.assertEqual(result["REASON"], expected)
                self.assertEqual(result["INSTALL_ALLOWED"], "NO")
                self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
                self.assertEqual(result["IN_PLACE_MANIFEST_TRANSACTION"],
                                 "NOT_IMPLEMENTED")
                self.assertEqual(manifest.read_bytes(), saved_manifest)
                self.assertEqual((self.data / "tunnels.json").read_bytes(), saved_tunnels)
                if pending.exists():
                    pending.unlink()
        receipt.write_bytes(original)
        # A non-cooperating writer may also race the paired planner itself.
        expected_transition = exe.pair._pair_expected_transition

        def tamper_at_plan(*args, **kwargs):
            result = expected_transition(*args, **kwargs)
            receipt.write_bytes(original + b" ")
            return result

        with patch.object(exe.admission, "report", return_value=evidence), \
                patch.object(exe.pair, "_pair_expected_transition",
                             side_effect=tamper_at_plan):
            result = exe.review_in_place_binary(
                expected_node_image=IMAGE, arch="amd64",
                paths=paths, runner=runner)
        self.assertEqual(result["REASON"], "RETAINED_PAIR_CHANGED_DURING_REVIEW")
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        receipt.write_bytes(original)
        with patch.object(exe.admission, "report", return_value=evidence):
            clean = exe.review_in_place_binary(
                expected_node_image=IMAGE, arch="amd64",
                paths=paths, runner=runner)
        self.assertEqual(clean["IN_PLACE_MANIFEST_TRANSACTION"],
                         "PAIR_PLAN_VERIFIED_READ_ONLY")
        self.assertEqual(clean["INSTALL_ALLOWED"], "NO")
        self.assertEqual(manifest.read_bytes(), saved_manifest)
        self.assertEqual((self.data / "tunnels.json").read_bytes(), saved_tunnels)

    def test_retained_readonly_review_detects_cleanup_seal_without_docker(self):
        runner, audit = self._retained_review_fixture()
        self.state.mkdir(mode=0o700, parents=True)
        seal = self.state/"retained-rc7-cleanup.json"
        for kind in ("file", "dangling-symlink"):
            with self.subTest(kind=kind):
                if kind == "file":
                    seal.write_text("unresolved recovery seal")
                else:
                    seal.symlink_to(self.root/"nonexistent-target")
                result = exe.review_in_place_binary(
                    expected_node_image=IMAGE, arch="amd64",
                    paths=self.paths, runner=runner)
                self.assertEqual(result["REASON"],
                                 "RETAINED_CLEANUP_RECOVERY_REQUIRED")
                self.assertEqual(result["INSTALL_ALLOWED"], "NO")
                self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
                self.assertEqual(result["IN_PLACE_MANIFEST_TRANSACTION"],
                                 "NOT_IMPLEMENTED")
                self.assertEqual(runner.calls, [])
                seal.unlink()
        self.assertFalse(seal.exists())

    def _retained_two_host_real_executor_fixture(self):
        """Two marked temporary CI lab nodes, not live signed hosts."""
        from dataclasses import replace
        if not (self.config / "engine-state/engines.json").exists():
            self._retained_review_fixture()
        foreign_tmp = tempfile.TemporaryDirectory(
            prefix="backhaul-retained-foreign-", dir=self.root.parent)
        self.addCleanup(foreign_tmp.cleanup)
        foreign_root = Path(foreign_tmp.name)
        foreign_root.chmod(0o700)
        nodes = {}
        for role, root in (("ir", self.root), ("foreign", foreign_root)):
            (root / "EXPERIMENTAL-LAB").write_text(exe.pair.MARKER)
            node = root / "node"
            if role == "foreign":
                node.mkdir(mode=0o700)
                (node / "config").mkdir(mode=0o700)
                (root / "stages").mkdir(mode=0o700)
                (node / ".env").write_bytes((self.node / ".env").read_bytes())
                (node / "docker-compose.yml").write_bytes(
                    (self.node / "docker-compose.yml").read_bytes())
            state = node / "config/engine-state"
            state.mkdir(mode=0o700, parents=True, exist_ok=True)
            manifest = state / "engines.json"
            if role == "foreign":
                manifest.write_bytes(
                    (self.node / "config/engine-state/engines.json").read_bytes())
                manifest.chmod(0o600)
            frp = root / exe.pair.PAIR_RECEIPT_DIR
            frp.mkdir(mode=0o700, exist_ok=True)
            receipt = frp / "record.json"
            receipt.write_text(json.dumps({
                "schema": 1, "state": "COMMITTED", "role": role,
                "old": None, "new": exe._sha(manifest.read_bytes()),
                "binaries": {"frpc": "b" * 64, "frps": "c" * 64},
            }, sort_keys=True) + "\n")
            receipt.chmod(0o600)
            store = root / "node-data"
            store.mkdir(mode=0o700, exist_ok=True)
            for name, record in (
                ("frp-owner-child.fixture.json", {
                    "role": role, "frp": "0.71.0",
                    "tunnels": ["20182", "optical", "nahavi"],
                }),
                ("broker-replay.fixture.json", {
                    "role": role, "identity": role + "-ci",
                    "broker": "up", "replay": "durable",
                }),
            ):
                artifact = store / name
                artifact.write_text(json.dumps(record, sort_keys=True) + "\n")
                artifact.chmod(0o600)
            host_state = root / "state/engine/backhaul"
            host_state.mkdir(mode=0o700, parents=True, exist_ok=True)
            host_state.chmod(0o700)
            (root / "state").chmod(0o700)
            (root / "state/engine").chmod(0o700)
            paths = replace(self.paths, node=node, staging=root / "stages",
                            frp_state=frp, state=host_state,
                            lock=root / "engine.lock",
                            binary=root / "installed/backhaul")
            nodes[role] = {
                "root": root, "paths": paths, "manifest": manifest,
                "receipt": receipt, "before": (manifest.read_bytes(),
                                               receipt.read_bytes()),
            }
        return nodes

    def test_two_host_real_retained_executor_exact_rollback_and_no_node_recreate(self):
        hosts = self._retained_two_host_real_executor_fixture()
        phases = []
        def observe(phase, ir, foreign):
            self.assertEqual(ir, hosts["ir"]["root"])
            self.assertEqual(foreign, hosts["foreign"]["root"])
            phases.append(phase)
            return True
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_REPOSITORY": "aghajani82/u-opti",
               "RUNNER_TEMP": str(self.root.parent)}
        with patch.dict(os.environ, env), \
             patch.object(exe.subprocess, "run",
                          side_effect=AssertionError("DOCKER_OR_NETWORK_CALLED")):
            result = exe._retained_two_host_rehearsal_lab(
                hosts["ir"]["paths"], hosts["foreign"]["paths"],
                arch="amd64", observe=observe)
        self.assertEqual(phases,
                         ["before", "after-ir", "after-both", "after-rollback"])
        self.assertEqual(result["RETAINED_TWO_HOST"],
                         "DISPOSABLE_HOST_EXECUTOR_EXACT_ROLLBACK")
        self.assertEqual(result["SIGNED_OWNER_CHILD_CONTINUITY"], "NOT_PROVEN")
        self.assertEqual(result["NODE_RECREATED"], "NO_DOCKER_EXECUTED_IN_LAB")
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
        for role in ("ir", "foreign"):
            info = hosts[role]
            self.assertEqual((info["manifest"].read_bytes(),
                              info["receipt"].read_bytes()), info["before"])
            self.assertFalse((info["paths"].state / "retained-rc7.json").exists())
            self.assertFalse((info["paths"].state /
                              "retained-rc7-cleanup.json").exists())

    def test_two_host_rejects_both_role_preflight_receipt_drift_without_writes(self):
        # The first observer runs AFTER the original paired preflights.
        # Even a semantically valid whitespace edit to a COMMITTED receipt
        # must not become the new baseline for the exact rollback.
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_REPOSITORY": "aghajani82/u-opti",
               "RUNNER_TEMP": str(self.root.parent)}
        for drift_role in ("ir", "foreign"):
            with self.subTest(role=drift_role):
                hosts = self._retained_two_host_real_executor_fixture()
                before = {role: hosts[role]["before"] for role in hosts}
                changed = []
                def observe(phase, *_):
                    if phase == "before":
                        receipt = hosts[drift_role]["receipt"]
                        receipt.write_bytes(receipt.read_bytes() + b"\n")
                        changed.append(drift_role)
                    return True
                with patch.dict(os.environ, env), \
                     patch.object(exe.subprocess, "run",
                                  side_effect=AssertionError("DOCKER_CALLED")), \
                     self.assertRaisesRegex(
                         exe.Hold, "RETAINED_TWO_HOST_PREFLIGHT_PAIR_CHANGED"):
                    exe._retained_two_host_rehearsal_lab(
                        hosts["ir"]["paths"], hosts["foreign"]["paths"],
                        arch="amd64", observe=observe)
                self.assertEqual(changed, [drift_role])
                for role, info in hosts.items():
                    self.assertEqual(info["manifest"].read_bytes(), before[role][0])
                    self.assertEqual(info["receipt"].read_bytes(),
                                     before[role][1] + (b"\n" if role == drift_role else b""))
                    self.assertFalse((info["paths"].state / "retained-rc7.json").exists())
                    self.assertFalse((info["paths"].state /
                                      "retained-rc7-cleanup.json").exists())

    def test_two_host_final_prewrite_rejects_peer_identity_drift_without_ir_write(self):
        # The initial observer has already accepted BOTH roles. A process/
        # replay identity rotation on either role immediately before its
        # final locked prewrite check must block the first IR PREPARED journal.
        # In particular, Foreign cannot silently drift while IR is enrolled.
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_REPOSITORY": "aghajani82/u-opti",
               "RUNNER_TEMP": str(self.root.parent)}
        for drift_role in ("foreign", "ir"):
            with self.subTest(drift_role=drift_role):
                hosts = self._retained_two_host_real_executor_fixture()
                target_lock = hosts[drift_role]["paths"].lock
                fixture = (hosts[drift_role]["root"] / "node-data" /
                           "broker-replay.fixture.json")
                original = fixture.read_bytes()
                lock_calls = []
                real_lock = exe._lock

                @contextmanager
                def rotate_at_final_prewrite(path):
                    if path == target_lock:
                        lock_calls.append(path)
                        if len(lock_calls) == 2:
                            doc = json.loads(fixture.read_bytes())
                            doc["identity"] += "-rotated"
                            fixture.write_text(json.dumps(doc, sort_keys=True) + "\n")
                            fixture.chmod(0o600)
                    with real_lock(path):
                        yield

                with patch.dict(os.environ, env), \
                     patch.object(exe, "_lock", rotate_at_final_prewrite), \
                     patch.object(exe.subprocess, "run",
                                  side_effect=AssertionError("DOCKER_OR_NETWORK_CALLED")), \
                     self.assertRaisesRegex(
                         exe.Hold, "RETAINED_TWO_HOST_PREFLIGHT_WITNESS_CHANGED"):
                    exe._retained_two_host_rehearsal_lab(
                        hosts["ir"]["paths"], hosts["foreign"]["paths"],
                        arch="amd64", observe=lambda *_: True)
                self.assertEqual(len(lock_calls), 2)
                self.assertNotEqual(fixture.read_bytes(), original)
                for info in hosts.values():
                    self.assertEqual(
                        (info["manifest"].read_bytes(),
                         info["receipt"].read_bytes()), info["before"])
                    self.assertFalse(
                        (info["paths"].state / "retained-rc7.json").exists())
                    self.assertFalse(
                        (info["paths"].state / "retained-rc7-cleanup.json").exists())

    def test_retained_step_requires_exact_preflight_bytes_under_writer_lock(self):
        # A writer racing after the coordinator's second preflight check
        # is rejected before creating the PREPARED journal on this host.
        from dataclasses import replace
        step, manifest, receipt = self.retained_fixture()
        paths = replace(self.paths, frp_state=self.root / "frp")
        expected = (manifest.read_bytes(), receipt.read_bytes())
        receipt.write_bytes(expected[1] + b"\n")
        changed = (manifest.read_bytes(), receipt.read_bytes())
        with self.assertRaisesRegex(exe.Hold, "RETAINED_PREFLIGHT_PAIR_CHANGED"):
            exe._retained_step(paths, action="install", role="ir",
                               arch="amd64", witness=lambda: "1"*64,
                               expected_before=expected,
                               expected_witness="1"*64)
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), changed)
        self.assertFalse((paths.state / "retained-rc7.json").exists())
        self.assertFalse((paths.state / "retained-rc7-cleanup.json").exists())
        for invalid in (("bad", b"ok"), (b"", b"ok"), (b"ok", None), b"bad"):
            with self.subTest(invalid=str(invalid)[:15]), self.assertRaisesRegex(
                    exe.Hold, "RETAINED_EXPECTED_BASELINE_INVALID"):
                exe._retained_step(paths, action="install", role="ir",
                                   arch="amd64", witness=lambda: "1"*64,
                                   expected_before=invalid,
                                   expected_witness="1"*64)
        receipt.write_bytes(expected[1])
        self.assertEqual(
            exe._retained_step(paths, action="install", role="ir",
                               arch="amd64", witness=lambda: "1"*64,
                               expected_before=expected,
                               expected_witness="1"*64),
            "COMMITTED")

    def test_retained_writer_binds_exact_preflight_witness_before_journal(self):
        # A cooperating IR/Foreign coordinator has already pinned BOTH
        # manifest+receipt bytes AND its independently collected running
        # Node/FRP witness. A new PID/image/FRP process in the handoff gap
        # must not become the writer's accepted baseline.
        from dataclasses import replace
        step, manifest, receipt = self.retained_fixture()
        paths = replace(self.paths, frp_state=self.root / "frp")
        baseline = (manifest.read_bytes(), receipt.read_bytes())
        journal = paths.state / "retained-rc7.json"
        seal = paths.state / "retained-rc7-cleanup.json"
        for bad in (None, "", "bad", "g"*64, True, 123, "1"*65):
            with self.subTest(invalid_witness=str(bad)[:20]), \
                 self.assertRaisesRegex(
                     exe.Hold, "RETAINED_EXPECTED_WITNESS_REQUIRED"):
                exe._retained_step(
                    paths, action="install", role="ir", arch="amd64",
                    witness=lambda: "1"*64, expected_before=baseline,
                    expected_witness=bad)
            self.assertEqual((manifest.read_bytes(), receipt.read_bytes()),
                             baseline)
            self.assertFalse(journal.exists())
            self.assertFalse(seal.exists())
        with self.assertRaisesRegex(
                exe.Hold, "RETAINED_EXPECTED_WITNESS_UNEXPECTED"):
            exe._retained_step(paths, action="install", role="ir",
                               arch="amd64", witness=lambda: "1"*64,
                               expected_witness="1"*64)
        with self.assertRaisesRegex(
                exe.Hold, "RETAINED_PREFLIGHT_WITNESS_CHANGED"):
            exe._retained_step(
                paths, action="install", role="ir", arch="amd64",
                witness=lambda: "2"*64, expected_before=baseline,
                expected_witness="1"*64)
        self.assertFalse(journal.exists())
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), baseline)

        # Second race: fingerprint was good on entering the lock, changed
        # between the file+receipt plan and first fsynced PREPARED phase.
        calls = []
        def drift_after_first_witness():
            calls.append(1)
            return ("1" if len(calls) == 1 else "2")*64
        with self.assertRaisesRegex(
                exe.Hold, "RETAINED_PREFLIGHT_WITNESS_CHANGED"):
            exe._retained_step(
                paths, action="install", role="ir", arch="amd64",
                witness=drift_after_first_witness, expected_before=baseline,
                expected_witness="1"*64)
        self.assertEqual(len(calls),2)
        self.assertFalse(journal.exists())
        self.assertFalse(seal.exists())
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), baseline)

        # The legitimate stable coordinator path is unchanged and still
        # requires exact compensation and terminal cleanup.
        self.assertEqual(exe._retained_step(
            paths, action="install", role="ir", arch="amd64",
            witness=lambda: "1"*64, expected_before=baseline,
            expected_witness="1"*64), "COMMITTED")
        self.assertEqual(step("rollback"), "RESTORED")
        self.assertEqual(step("cleanup"), "CLEANED")
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), baseline)

    def test_retained_two_host_writer_rejects_new_journal_after_preflight(self):
        # A previous COMMITTED transaction must never be adopted as a fresh
        # coordinator install success, even with identical FRP baseline.
        from dataclasses import replace
        step, manifest, receipt = self.retained_fixture()
        paths = replace(self.paths, frp_state=self.root / "frp")
        original = (manifest.read_bytes(), receipt.read_bytes())
        self.assertEqual(step("install"), "COMMITTED")
        committed = (manifest.read_bytes(), receipt.read_bytes())
        journal = paths.state / "retained-rc7.json"
        durable = journal.read_bytes()
        with self.assertRaisesRegex(exe.Hold, "RETAINED_PREFLIGHT_JOURNAL_APPEARED"):
            exe._retained_step(paths, action="install", role="ir",
                               arch="amd64", witness=lambda: "1"*64,
                               expected_before=original,
                               expected_witness="1"*64)
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), committed)
        self.assertEqual(journal.read_bytes(), durable)
        self.assertEqual(step("rollback"), "RESTORED")
        self.assertEqual(step("cleanup"), "CLEANED")
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), original)

    def test_two_host_real_retained_executor_compensates_after_ir_and_foreign_crash(self):
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_REPOSITORY": "aghajani82/u-opti",
               "RUNNER_TEMP": str(self.root.parent)}
        for interrupted in ("after-ir", "after-both", "foreign-after-manifest"):
            with self.subTest(interrupted=interrupted):
                hosts = self._retained_two_host_real_executor_fixture()
                actual_atomic = exe.pair._pair_atomic
                foreign_manifest = hosts["foreign"]["manifest"]
                crashed = [False]
                def interrupted_atomic(path, content):
                    actual_atomic(path, content)
                    if (interrupted == "foreign-after-manifest"
                            and path == foreign_manifest and not crashed[0]):
                        crashed[0] = True
                        raise exe.SimulatedCrash("foreign-transaction-interrupted")
                with patch.dict(os.environ, env), \
                     patch.object(exe.pair, "_pair_atomic",
                                  side_effect=interrupted_atomic), \
                     self.assertRaisesRegex(
                         exe.Hold, "RETAINED_TWO_HOST_ABORTED_EXACT_ROLLBACK_PROVED"):
                    exe._retained_two_host_rehearsal_lab(
                        hosts["ir"]["paths"], hosts["foreign"]["paths"],
                        arch="amd64", observe=lambda *_: True,
                        inject=interrupted if interrupted != "foreign-after-manifest" else "")
                for role in ("ir", "foreign"):
                    info = hosts[role]
                    self.assertEqual((info["manifest"].read_bytes(),
                                      info["receipt"].read_bytes()), info["before"])
                    self.assertFalse((info["paths"].state / "retained-rc7.json").exists())

    def _retained_fixture_witness(self, info, role):
        digests = exe.pair._rc7_two_host_guards(info["root"], role=role)
        return exe._sha(json.dumps(digests, separators=(",", ":")).encode())

    def test_two_host_final_observer_failure_keeps_both_restored_journals(self):
        hosts = self._retained_two_host_real_executor_fixture()
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_REPOSITORY": "aghajani82/u-opti",
               "RUNNER_TEMP": str(self.root.parent)}
        phases = []
        def observer(phase, *_):
            phases.append(phase)
            return phase != "after-rollback"
        with patch.dict(os.environ, env), \
             patch.object(exe.subprocess, "run",
                          side_effect=AssertionError("DOCKER_NOT_ALLOWED")):
            with self.assertRaisesRegex(
                    exe.Hold, "RETAINED_TWO_HOST_MANUAL_RECOVERY_REQUIRED"):
                exe._retained_two_host_rehearsal_lab(
                    hosts["ir"]["paths"], hosts["foreign"]["paths"],
                    arch="amd64", observe=observer)
            self.assertEqual(phases, [
                "before", "after-ir", "after-both", "after-rollback"])
            for role in ("ir", "foreign"):
                info = hosts[role]
                journal = info["paths"].state / "retained-rc7.json"
                self.assertTrue(journal.is_file())
                self.assertEqual(
                    json.loads(journal.read_bytes())["record"]["phase"],
                    "RESTORED")
                self.assertEqual(
                    (info["manifest"].read_bytes(), info["receipt"].read_bytes()),
                    info["before"])
                self.assertEqual(
                    exe._retained_step(
                        info["paths"], action="cleanup", role=role,
                        arch="amd64",
                        witness=lambda role=role, info=info:
                            self._retained_fixture_witness(info, role)),
                    "CLEANED")
                self.assertFalse(journal.exists())
                self.assertFalse(
                    (info["paths"].state / "retained-rc7-cleanup.json").exists())

    def test_two_host_process_death_preserves_independent_recovery_evidence(self):
        # os._exit bypasses exception handlers and any in-process compensation.
        # The per-host PREPARED/COMMITTED records must remain usable after a
        # genuine process termination, with NO Docker or Node recreation.
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_REPOSITORY": "aghajani82/u-opti",
               "RUNNER_TEMP": str(self.root.parent)}
        for boundary in ("after-ir", "foreign-after-manifest", "after-both"):
            with self.subTest(boundary=boundary):
                hosts = self._retained_two_host_real_executor_fixture()
                original_atomic = exe.pair._pair_atomic
                foreign_manifest = hosts["foreign"]["manifest"]
                pid = os.fork()
                if pid == 0:
                    def crash_atomic(path, content):
                        original_atomic(path, content)
                        if boundary == "foreign-after-manifest" and path == foreign_manifest:
                            os._exit(91)
                    def crash_observer(phase, *_):
                        if phase == boundary:
                            os._exit(91)
                        return True
                    with patch.dict(os.environ, env), \
                         patch.object(exe.pair, "_pair_atomic", crash_atomic), \
                         patch.object(exe.subprocess, "run",
                                      side_effect=AssertionError("DOCKER_NOT_ALLOWED")):
                        try:
                            exe._retained_two_host_rehearsal_lab(
                                hosts["ir"]["paths"], hosts["foreign"]["paths"],
                                arch="amd64", observe=crash_observer)
                        finally:
                            os._exit(1)
                self.assertEqual(os.waitpid(pid, 0)[1], 91 << 8)
                self.assertTrue(
                    (hosts["ir"]["paths"].state / "retained-rc7.json").exists())
                if boundary != "after-ir":
                    self.assertTrue(
                        (hosts["foreign"]["paths"].state /
                         "retained-rc7.json").exists())
                with patch.dict(os.environ, env), \
                     patch.object(exe.subprocess, "run",
                                  side_effect=AssertionError("DOCKER_NOT_ALLOWED")):
                    for role in ("foreign", "ir"):
                        info = hosts[role]
                        journal = info["paths"].state / "retained-rc7.json"
                        if journal.exists():
                            self.assertEqual(
                                exe._retained_step(
                                    info["paths"], action="rollback",
                                    role=role, arch="amd64",
                                    witness=lambda role=role, info=info:
                                        self._retained_fixture_witness(info, role)),
                                "RESTORED")
                    for role in ("ir", "foreign"):
                        info = hosts[role]
                        self.assertEqual(
                            (info["manifest"].read_bytes(),
                             info["receipt"].read_bytes()), info["before"])
                        journal = info["paths"].state / "retained-rc7.json"
                        if journal.exists():
                            self.assertEqual(
                                exe._retained_step(
                                    info["paths"], action="cleanup",
                                    role=role, arch="amd64",
                                    witness=lambda role=role, info=info:
                                        self._retained_fixture_witness(info, role)),
                                "CLEANED")
                        self.assertFalse(journal.exists())
                        self.assertFalse(
                            (info["paths"].state /
                             "retained-rc7-cleanup.json").exists())

    def test_two_host_real_retained_executor_requires_ci_labs_and_both_preflights(self):
        from dataclasses import replace
        hosts = self._retained_two_host_real_executor_fixture()
        ir = hosts["ir"]["paths"]
        foreign = hosts["foreign"]["paths"]
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_REPOSITORY": "aghajani82/u-opti",
               "RUNNER_TEMP": str(self.root.parent)}
        with self.assertRaises(exe.Hold):
            exe._retained_two_host_rehearsal_lab(
                ir, foreign, arch="amd64", observe=lambda *_: True)
        with patch.dict(os.environ, env):
            for bad_paths in (ir, replace(foreign, node=ir.node),
                              replace(foreign, lock=exe.Paths().lock)):
                with self.subTest(paths=bad_paths):
                    with self.assertRaises(exe.Hold):
                        exe._retained_two_host_rehearsal_lab(
                            ir, bad_paths, arch="amd64", observe=lambda *_: True)
            foreign_receipt = hosts["foreign"]["receipt"]
            original = foreign_receipt.read_bytes()
            foreign_receipt.write_bytes(b"bad external journal")
            with self.assertRaises(exe.Hold):
                exe._retained_two_host_rehearsal_lab(
                    ir, foreign, arch="amd64", observe=lambda *_: True)
            self.assertEqual(hosts["ir"]["manifest"].read_bytes(),
                             hosts["ir"]["before"][0])
            self.assertFalse((ir.state / "retained-rc7.json").exists())
            foreign_receipt.write_bytes(original)
            with self.assertRaises(exe.Hold):
                exe._retained_two_host_rehearsal_lab(
                    ir, foreign, arch="amd64", observe=lambda *_: False)
            self.assertFalse((ir.state / "retained-rc7.json").exists())

    def test_retained_mutation_refuses_all_live_resource_paths_before_lock(self):
        from dataclasses import replace
        step, manifest, receipt = self.retained_fixture()
        paths = replace(self.paths, frp_state=self.root / "frp")
        live = exe.Paths()
        before = (manifest.read_bytes(), receipt.read_bytes())
        for name in ("node", "staging", "state", "lock", "binary", "frp_state"):
            with self.subTest(protected=name):
                unsafe = replace(paths, **{name: getattr(live, name)})
                with patch.object(
                        exe, "_lock",
                        side_effect=AssertionError("LIVE_ENGINE_LOCK_TOUCHED")):
                    with self.assertRaisesRegex(
                            exe.Hold, "INDEPENDENT_DEPLOYMENT_APPROVAL_REQUIRED"):
                        exe._retained_step(
                            unsafe, action="install", role="ir",
                            arch="amd64", witness=lambda: "1" * 64)
        # The production lock must not be touched through symlinks, a child
        # alias or a parent path either. The guard runs without creating it.
        alias = self.root / "alias-to-real-frp-lock"
        alias.symlink_to(live.lock)
        for candidate in (alias, live.lock.parent, live.lock / "subpath"):
            with self.subTest(candidate=str(candidate)):
                with patch.object(
                        exe, "_lock",
                        side_effect=AssertionError("LOCK_TOUCHED")):
                    with self.assertRaisesRegex(
                            exe.Hold, "INDEPENDENT_DEPLOYMENT_APPROVAL_REQUIRED"):
                        exe._retained_step(
                            replace(paths, lock=candidate),
                            action="recover", role="ir", arch="amd64",
                            witness=lambda: "1" * 64)
        for name in ("node", "staging", "state", "lock", "binary", "frp_state"):
            with self.subTest(relative=name):
                with self.assertRaisesRegex(
                        exe.Hold, "RETAINED_OPERATION_PATH_UNTRUSTED"):
                    exe._retained_step(
                        replace(paths, **{name: Path("relative")}),
                        action="install", role="ir", arch="amd64",
                        witness=lambda: "1" * 64)
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), before)
        self.assertFalse((paths.state / "retained-rc7.json").exists())
        self.assertFalse((paths.state / "retained-rc7-cleanup.json").exists())
        self.assertEqual(step("install"), "COMMITTED")
        self.assertEqual(step("rollback"), "RESTORED")
        self.assertEqual(step("cleanup"), "CLEANED")

    def test_retained_checksumming_does_not_trust_malformed_recovery_hex(self):
        step, manifest, receipt = self.retained_fixture()
        original = (manifest.read_bytes(), receipt.read_bytes())
        self.assertEqual(step("install"), "COMMITTED")
        committed = (manifest.read_bytes(), receipt.read_bytes())
        journal = self.state / "retained-rc7.json"
        envelope = json.loads(journal.read_bytes())
        original_journal = journal.read_bytes()
        malformed = (
            ("non-string-list", ["0f"]),
            ("non-string-null", None),
            ("invalid-alphabet", "zz"),
            ("uppercase", "AA"),
            ("embedded-whitespace", "aa bb"),
            ("odd-length", "a"),
            ("empty", ""),
            ("over-limit", "aa" * 8193),
        )
        for field in ("manifest", "receipt"):
            for case, value in malformed:
                with self.subTest(field=field, case=case):
                    mutated = json.loads(original_journal)
                    mutated["record"][field] = value
                    mutated["sha256"] = exe._sha(
                        json.dumps(mutated["record"], sort_keys=True).encode())
                    journal.write_text(json.dumps(mutated, sort_keys=True) + "\n")
                    journal.chmod(0o600)
                    with self.assertRaisesRegex(
                            exe.Hold, "RETAINED_JOURNAL_UNTRUSTED"):
                        step("recover")
                    self.assertEqual(
                        (manifest.read_bytes(), receipt.read_bytes()), committed)
                    self.assertEqual(
                        json.loads(journal.read_bytes())["record"][field], value)
        journal.write_bytes(original_journal)
        journal.chmod(0o600)
        self.assertEqual(step("rollback"), "RESTORED")
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), original)
        self.assertEqual(step("cleanup"), "CLEANED")
        self.assertFalse(journal.exists())

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

    def test_retained_recovery_and_cleanup_recheck_witness_before_durable_write(self):
        # A valid originally COMMITTED journal must not be prematurely
        # overwritten with RESTORING when Node/FRP identity rotates after
        # reading the protected runtime but before the first recovery write.
        step, manifest, receipt = self.retained_fixture()
        before = (manifest.read_bytes(), receipt.read_bytes())
        self.assertEqual(step("install"), "COMMITTED")
        committed = (manifest.read_bytes(), receipt.read_bytes())
        journal = self.state / "retained-rc7.json"
        seal = self.state / "retained-rc7-cleanup.json"
        committed_journal = journal.read_bytes()

        def rotate_after_first():
            rotate_after_first.calls += 1
            return ("1" if rotate_after_first.calls == 1 else "2") * 64
        rotate_after_first.calls = 0

        with self.assertRaisesRegex(
                exe.Hold, "RETAINED_RUNTIME_OR_PAIR_DRIFT"):
            step("rollback", rotate_after_first)
        self.assertEqual(rotate_after_first.calls, 2)
        self.assertEqual(journal.read_bytes(), committed_journal)
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()),
                         committed)
        self.assertFalse(seal.exists())

        # After the legitimate rollback, a new witness drift before sealing
        # terminal cleanup must likewise preserve the RESTORED journal
        # without creating a cleanup seal or unlinking recovery evidence.
        self.assertEqual(step("rollback"), "RESTORED")
        restored_journal = journal.read_bytes()
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), before)
        rotate_after_first.calls = 0
        with self.assertRaisesRegex(
                exe.Hold, "RETAINED_RUNTIME_OR_PAIR_DRIFT"):
            step("cleanup", rotate_after_first)
        self.assertEqual(rotate_after_first.calls, 2)
        self.assertEqual(journal.read_bytes(), restored_journal)
        self.assertFalse(seal.exists())
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), before)

        # Stable identity still permits byte-exact terminal cleanup and a
        # fresh transaction with the existing no-Node-recreation path.
        self.assertEqual(step("cleanup"), "CLEANED")
        self.assertFalse(journal.exists())
        self.assertFalse(seal.exists())
        self.assertEqual(step("install"), "COMMITTED")
        self.assertEqual(step("rollback"), "RESTORED")
        self.assertEqual(step("cleanup"), "CLEANED")
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
                # Every crash round is a separate transaction. Finish its
                # durable terminal journal cleanup before the next round.
                self.assertEqual(step("cleanup"), "CLEANED")
                self.assertFalse((self.state/"retained-rc7.json").exists())
                self.assertFalse((self.state/"retained-rc7-cleanup.json").exists())

    def test_retained_terminal_cleanup_requires_exact_rollback(self):
        step, manifest, receipt = self.retained_fixture()
        before = manifest.read_bytes(), receipt.read_bytes()
        self.assertEqual(step("install"), "COMMITTED")
        with self.assertRaises(exe.Hold):
            step("cleanup")
        self.assertTrue((self.state/"retained-rc7.json").exists())
        self.assertEqual(step("rollback"), "RESTORED")
        # RESTORED is terminal until cleanup: no silent re-enrollment may
        # overwrite the proof journal or skip its crash-resumable seal.
        journal = self.state/"retained-rc7.json"
        restored_journal = journal.read_bytes()
        with self.assertRaisesRegex(exe.Hold, "RETAINED_TERMINAL_CLEANUP_REQUIRED"):
            step("install")
        self.assertEqual(journal.read_bytes(), restored_journal)
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), before)
        self.assertFalse((self.state/"retained-rc7-cleanup.json").exists())
        self.assertEqual(step("recover"), "RESTORED")
        self.assertEqual(step("cleanup"), "CLEANED")
        self.assertFalse((self.state/"retained-rc7.json").exists())
        self.assertFalse((self.state/"retained-rc7-cleanup.json").exists())
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), before)
        with self.assertRaises(exe.Hold):
            step("cleanup")  # No invented cleanup proof after both records vanish.
        self.assertEqual(step("install"), "COMMITTED")

    def test_retained_terminal_cleanup_recovers_after_journal_unlink(self):
        step, manifest, receipt = self.retained_fixture()
        prior = manifest.read_bytes(), receipt.read_bytes()
        step("install")
        step("rollback")
        journal = self.state/"retained-rc7.json"
        seal = self.state/"retained-rc7-cleanup.json"
        fsync = exe.pair._pair_fsync_dir
        calls = []
        def interrupt_once(folder):
            calls.append(folder)
            raise exe.SimulatedCrash("after cleanup unlink, before fsync")
        with patch.object(exe.pair, "_pair_fsync_dir", side_effect=interrupt_once):
            with self.assertRaises(exe.SimulatedCrash):
                step("cleanup")
        self.assertEqual(len(calls), 1)
        self.assertFalse(journal.exists())
        self.assertTrue(seal.exists())
        for action in ("install", "recover", "rollback"):
            with self.subTest(action=action), self.assertRaises(exe.Hold):
                step(action)
        self.assertEqual(step("cleanup"), "CLEANED")
        self.assertFalse(seal.exists())
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), prior)

    def test_retained_terminal_cleanup_blocks_drift_and_tampered_seal(self):
        step, manifest, receipt = self.retained_fixture()
        prior = manifest.read_bytes(), receipt.read_bytes()
        step("install")
        step("rollback")
        journal = self.state/"retained-rc7.json"
        seal = self.state/"retained-rc7-cleanup.json"
        manifest.write_bytes(b"untrusted drift")
        with self.assertRaises(exe.Hold):
            step("cleanup")
        self.assertFalse(seal.exists())
        manifest.write_bytes(prior[0])
        with self.assertRaises(exe.SimulatedCrash):
            with patch.object(exe, "_retained_finish_cleanup",
                              side_effect=exe.SimulatedCrash("after seal fsync")):
                step("cleanup")
        saved_seal = seal.read_bytes()
        self.assertTrue(journal.exists())
        seal.write_bytes(b"corrupted")
        with self.assertRaises(exe.Hold):
            step("cleanup")
        self.assertTrue(journal.exists())
        seal.write_bytes(saved_seal)
        with self.assertRaises(exe.Hold):
            step("cleanup", lambda: "2"*64)
        self.assertEqual(step("cleanup"), "CLEANED")
        self.assertEqual((manifest.read_bytes(), receipt.read_bytes()), prior)

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
