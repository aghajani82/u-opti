#!/usr/bin/env python3
"""Independent read-only host gate, synthetic Docker and confidential state."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules/smite-managed-engine-host-admission.py"
IMAGE = "ghcr.io/aghajani82/smite-node@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
spec = importlib.util.spec_from_file_location("joint_host_admission_test", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

COMPOSE = """services:
  smite-node:
    image: ghcr.io/aghajani82/smite-node@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
      - node-data:/var/lib/smite-node
volumes:
  node-data:
    name: smite-node-data
"""
ENV = """NODE_ROLE=foreign
SMITE_NODE_PANEL_AUTH_MODE=signed
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
PANEL_SECRET=DO_NOT_PRINT_ME
"""


class SharedHostAdmission(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="two-engine-host-gate-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base / "node"
        self.node.mkdir()
        self.config = self.node / "config"
        self.config.mkdir()
        self.data = self.base / "node-data"
        self.data.mkdir()
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)
        self.runtime = {
            "Name": "/smite-node",
            "State": {"Running": True},
            "Config": {"Image": IMAGE,
                       "Env": ["SECRET=DO_NOT_PRINT_ME"]},
            "HostConfig": {"NetworkMode": "host", "PortBindings": {}},
            "Mounts": [
                {"Type": "bind", "Destination": "/etc/smite-node",
                 "Source": str(self.config)},
                {"Type": "volume", "Destination": "/var/lib/smite-node",
                 "Name": "smite-node-data", "Driver": "local",
                 "Source": str(self.data)},
            ],
        }
        genuine = gate.host._local_file

        def fixture_read(path, *, max_bytes, require_root=False):
            # Simulated test user is not root, never bypass in production.
            return genuine(path, max_bytes=max_bytes, require_root=False)

        patcher = patch.object(gate.host, "_local_file", side_effect=fixture_read)
        patcher.start()
        self.addCleanup(patcher.stop)

    def report(self, engine, *, expected_node_image=IMAGE):
        return gate.report(
            engine, self.node, runtime=self.runtime, min_bytes=4096,
            expected_node_image=expected_node_image,
        )

    def test_backhaul_and_frp_clean_core_never_grant_install(self):
        for engine in ("backhaul", "frp"):
            with self.subTest(engine=engine):
                result = self.report(engine)
                self.assertEqual(result["ENGINE"], engine.upper())
                self.assertEqual(result["NODE_ROLE"], "KH")
                self.assertEqual(result["CORE_PROFILE"], "MANAGED_STRICT")
                self.assertEqual(result["NODE_CONTAINER"], "RUNNING_REVIEWED_IMAGE")
                self.assertEqual(result["PERSISTENT_STORAGE"], "LOCAL_NAMED_VOLUME_CONFIRMED")
                self.assertEqual(result["SAVED_TUNNELS"], "ZERO")
                self.assertEqual(result["TARGET_ENGINE"], "NOT_INSTALLED")
                self.assertEqual(result["OTHER_ENGINE"], "NOT_INSTALLED")
                self.assertEqual(result["LOCAL_PREFLIGHT"], "PASS_LOCAL_ONLY_INCOMPLETE")
                self.assertEqual(result["INSTALL_ALLOWED"], "NO")
                self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
                self.assertEqual(result["SNAPSHOT_RESTORE"], "UNVERIFIED")
                self.assertEqual(result["HOST_TRANSACTION_AND_ROLLBACK"], "NOT_IMPLEMENTED")
                self.assertNotIn("DO_NOT_PRINT_ME", str(result))
        self.assertFalse((self.config / "engine-state").exists())

    def test_existing_other_engine_requires_signed_verification_not_uninstall(self):
        with patch.object(gate, "local_state", side_effect=lambda engine, node:
                          {"state": "ENROLLED_UNVERIFIED", "reason": "SIGNED_NODE_RECHECK_REQUIRED"}
                          if engine == "backhaul" else
                          {"state": "NOT_INSTALLED", "reason": "NO_ENROLLMENT"}):
            r = self.report("frp")
            self.assertEqual(r["TARGET_ENGINE"], "NOT_INSTALLED")
            self.assertEqual(r["OTHER_ENGINE"], "ENROLLED_UNVERIFIED")
            self.assertEqual(r["OTHER_ENGINE_ACTION"], "NEVER_MODIFY")
            self.assertEqual(r["REASON"], "OTHER_ENGINE_SIGNED_STATUS_REQUIRED")
            self.assertEqual(r["LOCAL_PREFLIGHT"], "PASS_LOCAL_ONLY_INCOMPLETE")
            self.assertEqual(r["OTHER_ENGINE_ACTION"], "NEVER_MODIFY")
            self.assertEqual(r["SIGNED_NODE_HEALTH_AND_REPLAY"], "UNVERIFIED")
            self.assertEqual(r["INSTALL_ALLOWED"], "NO")
            self.assertEqual(r["ACTIVATION_GATE"], "HOLD")
        with patch.object(gate, "local_state", side_effect=lambda engine, node:
                          {"state": "UNAVAILABLE", "reason": "MISSING_READONLY_MOUNT"}
                          if engine == "frp" else
                          {"state": "NOT_INSTALLED", "reason": "NO_ENROLLMENT"}):
            r = self.report("backhaul")
            self.assertEqual(r["REASON"], "OTHER_ENGINE_INCOMPLETE")

    def test_existing_target_never_suggested_for_reinstallation(self):
        with patch.object(gate, "local_state", side_effect=lambda engine, node:
                          {"state": "ENROLLED_UNVERIFIED", "reason": "SIGNED_NODE_RECHECK_REQUIRED"}
                          if engine == "frp" else
                          {"state": "NOT_INSTALLED", "reason": "NO_ENROLLMENT"}):
            out = self.report("frp")
        self.assertEqual(out["REASON"], "TARGET_ENGINE_ALREADY_PRESENT")

    def test_persisted_tunnel_prevents_engine_install_preflight(self):
        (self.data / "tunnels.json").write_text(json.dumps({
            "saved": {"core": "frp", "spec": {"secret": "DO_NOT_PRINT_ME"}}
        }))
        result = self.report("backhaul")
        self.assertEqual(result["SAVED_TUNNELS"], "EXISTING_DO_NOT_RESTART")
        self.assertEqual(result["REASON"], "SAVED_TUNNELS_PRESENT")
        self.assertNotIn("DO_NOT_PRINT_ME", str(result))

    def test_saved_tunnel_hold_carries_hashed_baselines_but_not_authorization(self):
        self.runtime["Id"] = "c" * 64
        raw = json.dumps({
            "active": {"core": "frp", "spec": {"token": "TOP_SECRET", "port": 20182}}
        }).encode()
        (self.data / "tunnels.json").write_bytes(raw)
        snapshot = self.report("backhaul")
        self.assertEqual(snapshot["SAVED_TUNNELS"], "EXISTING_DO_NOT_RESTART")
        self.assertEqual(snapshot["REASON"], "SAVED_TUNNELS_PRESENT")
        self.assertEqual(snapshot["SAVED_TUNNEL_REGISTRY_SHA256"],
                         hashlib.sha256(raw).hexdigest())
        self.assertEqual(snapshot["NODE_CONTAINER_ID_SHA256"],
                         hashlib.sha256(("c" * 64).encode()).hexdigest())
        self.assertNotIn("TOP_SECRET", str(snapshot))
        self.assertNotIn("20182", str(snapshot))
        self.assertEqual(snapshot["OTHER_ENGINE_ACTION"], "NEVER_MODIFY")
        self.assertEqual(snapshot["HOST_TRANSACTION_AND_ROLLBACK"], "NOT_IMPLEMENTED")
        self.assertEqual(snapshot["INSTALL_ALLOWED"], "NO")
        self.assertEqual(snapshot["ACTIVATION_GATE"], "HOLD")

    def test_local_frp_process_receipt_remains_unattested_with_saved_tunnels(self):
        (self.data / "tunnels.json").write_text(json.dumps({
            "active": {"core": "frp", "spec": {"secret": "DO_NOT_PRINT_ME"}}
        }))
        fake = {"FRPC_PROCESS_LOCAL": "OBSERVED_UNATTESTED",
                "FRPS_PROCESS_LOCAL": "OBSERVED_UNATTESTED",
                "FRPC_INSTANCE_SHA256": "a"*64,
                "FRPS_INSTANCE_SHA256": "b"*64}
        with patch.object(gate.host, "frp_process_footprint", return_value=fake):
            result = self.report("backhaul")
        self.assertEqual(result["FRPC_PROCESS_LOCAL"], "OBSERVED_UNATTESTED")
        self.assertEqual(result["FRPS_INSTANCE_SHA256"], "b"*64)
        self.assertEqual(result["BROKER_SOCKET_LOCAL"], "UNVERIFIED")
        self.assertEqual(result["WSS_EDGE_JOURNAL_LOCAL"], "UNVERIFIED")
        self.assertEqual(result["SAVED_TUNNELS"], "EXISTING_DO_NOT_RESTART")
        self.assertEqual(result["REASON"], "SAVED_TUNNELS_PRESENT")
        self.assertEqual(result["SIGNED_NODE_HEALTH_AND_REPLAY"], "UNVERIFIED")
        self.assertEqual(result["HOST_TRANSACTION_AND_ROLLBACK"], "NOT_IMPLEMENTED")
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
        self.assertNotIn("DO_NOT_PRINT_ME", str(result))

    def test_invalid_registry_blocks_baseline_and_can_never_open_install(self):
        self.runtime["Id"] = "invalid-id"
        (self.data / "tunnels.json").write_text('{"live": {"core": "frp"}}')
        state = self.report("backhaul")
        self.assertEqual(state["SAVED_TUNNEL_REGISTRY_SHA256"], "UNVERIFIED")
        self.assertEqual(state["NODE_CONTAINER_ID_SHA256"], "UNVERIFIED")
        self.assertEqual(state["INSTALL_ALLOWED"], "NO")
        self.assertEqual(state["ACTIVATION_GATE"], "HOLD")

    def test_missing_or_mismatched_digest_pin_holds_before_engine_review(self):
        missing = self.report("backhaul", expected_node_image=None)
        self.assertEqual(missing["REASON"], "EXPECTED_NODE_DIGEST_REQUIRED")
        wrong = self.report(
            "frp",
            expected_node_image="ghcr.io/aghajani82/smite-node@sha256:" + "b" * 64,
        )
        self.assertEqual(wrong["REASON"], "NODE_IMAGE_DIGEST_MISMATCH")
        self.assertEqual(wrong["INSTALL_ALLOWED"], "NO")

    def test_unreviewed_image_or_published_docker_ports_are_hold(self):
        self.runtime["Config"]["Image"] = "smite-node:stage15-local"
        out = self.report("frp")
        self.assertEqual(out["REASON"], "LOCAL_TEST_IMAGE_CANNOT_SATISFY_PIN")
        self.runtime["Config"]["Image"] = IMAGE
        self.runtime["HostConfig"]["PortBindings"] = {"8888/tcp": [
            {"HostPort": "8888", "HostIp": "0.0.0.0"}]}
        out = self.report("backhaul")
        self.assertEqual(out["REASON"], "PUBLISHED_DOCKER_PORTS")
        self.assertEqual(out["INSTALL_ALLOWED"], "NO")

    def test_unmanaged_legacy_profile_fails_closed(self):
        (self.node / ".env").write_text(ENV.replace(
            "SMITE_AGENT_AUTH_MODE=strict", "SMITE_AGENT_AUTH_MODE=legacy"))
        out = self.report("frp")
        self.assertEqual(out["REASON"], "NOT_MANAGED_STRICT_CORE")

    def test_compose_change_during_review_halts_without_mutation(self):
        base_reader = gate.host._local_file
        calls = [0]

        def drifting(path, *, max_bytes, require_root=False):
            if path == self.node / "docker-compose.yml":
                calls[0] += 1
                if calls[0] >= 3:
                    return b"changed-other-compose"
            return base_reader(path, max_bytes=max_bytes, require_root=require_root)

        with patch.object(gate.host, "_local_file", side_effect=drifting):
            result = self.report("frp")
        self.assertEqual(result["REASON"], "COMPOSE_CHANGED_DURING_REVIEW")
        self.assertEqual((self.node / "docker-compose.yml").read_text(), COMPOSE)

    def signed_inputs(self):
        import hashlib
        candidate = self.base / "externally-reviewed-pair.json"
        source = "e" * 40
        publish_ref = "refs/tags/v2.0.0-rc.7"
        candidate.write_text(json.dumps({
            "schema": 1,
            "kind": "smite_signed_registry_pair_candidate",
            "source_repo": "aghajani82/Smite",
            "source_commit": source,
            "publish_ref": publish_ref,
            "version": "2.0.0-rc.7",
            "images": {
                "panel": "ghcr.io/aghajani82/smite-panel@sha256:" + "b" * 64,
                "node": IMAGE,
            },
            "activation_allowed": False,
            "release_approved": False,
        }), encoding="utf-8")
        return dict(
            signed_pair_manifest=candidate,
            signed_pair_manifest_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
            signed_pair_source_sha=source,
            signed_pair_publish_ref=publish_ref,
        )

    def signed_cosign(self, args, **kwargs):
        role = "panel" if "smite-panel@" in args[-1] else "node"
        image_digest = args[-1].split("@", 1)[1]
        source = next(x.split("=", 1)[1] for x in args
                      if x.startswith("smite_source_sha="))
        signed = [{"critical": {
            "type": "cosign container image signature",
            "image": {"docker-manifest-digest": image_digest}},
            "optional": {"smite_source_sha": source, "smite_role": role}}]
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(signed), stderr="")

    def test_signed_pair_cosign_verification_reaches_deeper_read_only_host_gate(self):
        inputs = self.signed_inputs()
        with patch.object(gate.signed_pair.subprocess, "run",
                          side_effect=self.signed_cosign) as run:
            result = gate.report("backhaul", self.node, runtime=self.runtime,
                                 min_bytes=4096, **inputs)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result["SIGNED_REGISTRY_PAIR_PROOF"], "COSIGN_VERIFIED")
        self.assertEqual(result["NODE_CONTAINER"], "RUNNING_REVIEWED_IMAGE")
        self.assertEqual(result["SAVED_TUNNELS"], "ZERO")
        self.assertEqual(result["REASON"], "SNAPSHOT_SIGNED_NODE_AND_HOST_EXECUTOR_UNVERIFIED")
        self.assertEqual(result["HOST_TRANSACTION_AND_ROLLBACK"], "NOT_IMPLEMENTED")
        self.assertEqual(result["NODE_RUNTIME_BYTES_AND_REPLAY"], "UNVERIFIED")
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
        self.assertNotIn("DO_NOT_PRINT_ME", str(result))

    def test_signed_pair_never_bypasses_existing_saved_tunnel_hold(self):
        inputs = self.signed_inputs()
        (self.data / "tunnels.json").write_text(json.dumps({
            "saved": {"core": "frp", "spec": {"secret": "DO_NOT_PRINT_ME"}}
        }))
        with patch.object(gate.signed_pair.subprocess, "run",
                          side_effect=self.signed_cosign):
            result = gate.report("backhaul", self.node, runtime=self.runtime,
                                 min_bytes=4096, **inputs)
        self.assertEqual(result["SIGNED_REGISTRY_PAIR_PROOF"], "COSIGN_VERIFIED")
        self.assertEqual(result["SAVED_TUNNELS"], "EXISTING_DO_NOT_RESTART")
        self.assertEqual(result["REASON"], "SAVED_TUNNELS_PRESENT")
        self.assertEqual(result["OTHER_ENGINE_ACTION"], "NEVER_MODIFY")
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        self.assertNotIn("DO_NOT_PRINT_ME", str(result))

    def test_signed_production_frp_inventory_still_holds_saved_tunnels(self):
        inputs = self.signed_inputs()
        (self.data / "tunnels.json").write_text(json.dumps({
            "saved": {"core": "frp", "spec": {"secret": "DO_NOT_PRINT_ME"}}
        }))
        def local_fixture(engine, node):
            return {"state": "ENROLLED_UNVERIFIED" if engine == "frp" else "NOT_INSTALLED",
                    "reason": "LOCAL_ONLY"}
        with patch.object(gate.signed_pair.subprocess, "run",
                          side_effect=self.signed_cosign), \
             patch.object(gate, "local_state", side_effect=local_fixture):
            out = gate.report("backhaul", self.node, runtime=self.runtime,
                              min_bytes=4096, **inputs)
        self.assertEqual(out["TARGET_ENGINE"], "NOT_INSTALLED")
        self.assertEqual(out["OTHER_ENGINE"], "ENROLLED_UNVERIFIED")
        self.assertEqual(out["OTHER_ENGINE_LOCAL_REASON"], "LOCAL_ONLY")
        self.assertEqual(out["OTHER_ENGINE_ACTION"], "NEVER_MODIFY")
        self.assertEqual(out["REASON"], "SAVED_TUNNELS_PRESENT")
        self.assertEqual(out["SAVED_TUNNELS"], "EXISTING_DO_NOT_RESTART")
        self.assertEqual(out["SIGNED_NODE_HEALTH_AND_REPLAY"], "UNVERIFIED")
        self.assertEqual(out["INSTALL_ALLOWED"], "NO")
        self.assertEqual(out["ACTIVATION_GATE"], "HOLD")
        self.assertNotIn("DO_NOT_PRINT_ME", str(out))

    def test_incomplete_or_invalid_signed_pair_never_queries_docker(self):
        inputs = self.signed_inputs()
        examples = [
            {"signed_pair_manifest": inputs["signed_pair_manifest"]},
            {**inputs, "signed_pair_manifest_sha256": "0" * 64},
            {**inputs, "signed_pair_publish_ref": "refs/tags/v2.0.0-rc.5"},
        ]
        for values in examples:
            with self.subTest(values=str(values)[:70]):
                with patch.object(gate.signed_pair.subprocess, "run",
                                  side_effect=self.signed_cosign) as run:
                    out = gate.report("backhaul", self.node, runtime=self.runtime,
                                      min_bytes=4096, **values)
                self.assertEqual(out["INSTALL_ALLOWED"], "NO")
                self.assertEqual(out["ACTIVATION_GATE"], "HOLD")
                self.assertEqual(out["NODE_CONTAINER"], "UNVERIFIED")
                self.assertIn(out["REASON"], ("INCOMPLETE_SIGNED_PAIR_PROOF",
                                               "SIGNED_PAIR_PROOF_INVALID"))
                self.assertEqual(run.call_count, 0)

    def test_failed_cosign_and_mismatched_runtime_image_hold(self):
        inputs = self.signed_inputs()
        with patch.object(gate.signed_pair.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="secret")):
            out = gate.report("backhaul", self.node, runtime=self.runtime,
                              min_bytes=4096, **inputs)
        self.assertEqual(out["REASON"], "SIGNED_PAIR_PROOF_INVALID")
        self.assertNotIn("secret", str(out))
        with patch.object(gate.signed_pair.subprocess, "run",
                          side_effect=self.signed_cosign):
            out = gate.report(
                "backhaul", self.node, runtime=self.runtime, min_bytes=4096,
                expected_node_image="ghcr.io/aghajani82/smite-node@sha256:" + "f" * 64,
                **inputs)
        self.assertEqual(out["REASON"], "SIGNED_PAIR_IMAGE_PIN_CONFLICT")
        self.runtime["Config"]["Image"] = (
            "ghcr.io/aghajani82/smite-node@sha256:" + "a" * 63 + "b"
        )
        with patch.object(gate.signed_pair.subprocess, "run",
                          side_effect=self.signed_cosign):
            out = gate.report("backhaul", self.node, runtime=self.runtime,
                              min_bytes=4096, **inputs)
        self.assertEqual(out["SIGNED_REGISTRY_PAIR_PROOF"], "COSIGN_VERIFIED")
        self.assertEqual(out["REASON"], "NODE_IMAGE_DIGEST_MISMATCH")
        self.assertEqual(out["INSTALL_ALLOWED"], "NO")

    def test_backhaul_menu_forwards_only_external_proof_and_keeps_install_disabled(self):
        menu = (ROOT / "modules/smite-managed-backhaul-menu.sh").read_text()
        for name in ("SMITE_BH_PAIR_MANIFEST", "SMITE_BH_PAIR_SHA256",
                     "SMITE_BH_PAIR_SOURCE_SHA", "SMITE_BH_PAIR_PUBLISH_REF",
                     "--signed-pair-manifest", "--signed-pair-manifest-sha256",
                     "--signed-pair-source-sha", "--signed-pair-publish-ref"):
            self.assertIn(name, menu)
        # The only newly admitted live action is an IR-only metadata
        # transaction via the existing option 3. Foreign and two-host
        # Backhaul traffic activation stay disabled.
        self.assertIn("smite_managed_bh_ir_retained_canary", menu)
        self.assertIn("install-retained-ir", menu)
        self.assertIn("rollback-retained-ir", menu)
        self.assertNotIn("install-retained-foreign", menu)
        self.assertIn("HOLD: Host installation disabled. No changes made.", menu)
        self.assertNotIn("docker compose up", menu)

    def test_backhaul_existing_option2_invokes_only_pinned_read_only_review(self):
        # End-to-end actual Bash menu dispatch; intercept every Python call
        # before it can reach Docker, Cosign or host filesystem operations.
        selected = json.loads((ROOT / "modules/smite-selected-candidate.json").read_text())
        with tempfile.TemporaryDirectory(prefix="bh-menu-readonly-") as temp:
            out = Path(temp) / "commands"
            script = r"""
source "$MENU"
uname() { printf '%s\n' "${TEST_ARCH:-x86_64}"; }
python3() {
    printf '%q ' "$@" >> "$CAPTURE"
    printf '\n' >> "$CAPTURE"
    return 2
}
smite_managed_bh_menu <<'CHOICES'
2
0
CHOICES
"""
            base_env = {**os.environ, "MENU": str(ROOT / "modules/smite-managed-backhaul-menu.sh"),
                        "CAPTURE": str(out), "SMITE_NODE_DIR": "/opt/smite-node"}
            # Don't let a developer's existing external pins or trust path
            # accidentally change this deterministic CI exercise.
            for key in ("SMITE_BH_PAIR_MANIFEST", "SMITE_BH_PAIR_SHA256",
                        "SMITE_BH_PAIR_SOURCE_SHA", "SMITE_BH_PAIR_PUBLISH_REF",
                        "SMITE_BH_PAIR_TRUSTED_ROOT"):
                base_env.pop(key, None)
            for label, overrides, expected_call in (
                ("selected-default", {}, True),
                ("partial-override", {"SMITE_BH_PAIR_MANIFEST": "/tmp/custom.json"}, False),
                ("unexpected-node-dir", {"SMITE_NODE_DIR": "/tmp/not-live"}, False),
                ("unknown-architecture", {"TEST_ARCH": "mips64"}, False),
            ):
                with self.subTest(label=label):
                    out.unlink(missing_ok=True)
                    result = subprocess.run(["bash", "-c", script],
                                            env={**base_env, **overrides},
                                            capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    calls = out.read_text() if out.exists() else ""
                    self.assertIn("smite-managed-engine-host-admission.py", calls)
                    self.assertIn("verify-rc7-bundle", calls)
                    if expected_call:
                        self.assertEqual(calls.count("review-in-place"), 1)
                        self.assertIn("--confirm-role REVIEW-BACKHAUL-IN-PLACE", calls)
                        self.assertIn("--arch amd64", calls)
                        self.assertIn("--expected-node-image " + selected["images"]["node"], calls)
                        self.assertIn("--signed-pair-manifest-sha256 " +
                                      "58bebfc605a5c1a64cf02ce38e6397dbcdae5f1c3289a01952f361b6a8aa660e", calls)
                        self.assertIn("--signed-pair-source-sha " + selected["source_commit"], calls)
                        self.assertIn("--signed-pair-publish-ref " + selected["publish_ref"], calls)
                    else:
                        self.assertNotIn("review-in-place", calls)
                        self.assertIn("HOLD:", result.stdout)
                    self.assertNotIn(" --install", calls)
                    self.assertNotIn(" --force-recreate", calls)
                    self.assertIn("INSTALL_ALLOWED=NO", result.stdout)
                    self.assertIn("ACTIVATION_GATE=HOLD", result.stdout)

    def test_backhaul_option3_remains_hard_hold(self):
        menu = ROOT / "modules/smite-managed-backhaul-menu.sh"
        result = subprocess.run(["bash", str(menu), "--install"], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("HOLD: Host installation disabled", result.stderr)

    def test_no_external_executor_or_snapshot_proof(self):
        body = SCRIPT.read_text()
        for dangerous in ("docker compose up", "docker restart", "systemctl",
                          "subprocess.run", "subprocess.Popen", "os.system(",
                          "ssh ", "curl ", "iptables ", "nginx -s"):
            self.assertNotIn(dangerous, body)
        for engine in ("backhaul", "frp"):
            out = self.report(engine)
            self.assertEqual(out["INSTALL_ALLOWED"], "NO")
            self.assertEqual(out["ACTIVATION_GATE"], "HOLD")

    def test_cli_real_host_probe_always_hold_even_on_missing_node(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--engine", "frp",
                            "--node-dir", str(self.node),
                            "--expected-node-image", IMAGE, "--format", "json"],
                           text=True, capture_output=True, timeout=15)
        self.assertEqual(p.returncode, 2)
        parsed = json.loads(p.stdout)
        self.assertEqual(parsed["INSTALL_ALLOWED"], "NO")
        self.assertNotIn("DO_NOT_PRINT_ME", p.stdout + p.stderr)


    @staticmethod
    def ir_local_preservation_fixture():
        """Synthetic sanitized gate outputs, NOT authenticated server data."""
        fake_hashes = {
            "SAVED_TUNNEL_REGISTRY_SHA256": "a" * 64,
            "NODE_CONTAINER_ID_SHA256": "b" * 64,
            "FRPC_INSTANCE_SHA256": "c" * 64,
            "FRPS_INSTANCE_SHA256": "d" * 64,
            "BROKER_SOCKET_ID_SHA256": "e" * 64,
            "WSS_EDGE_JOURNAL_SHA256": "f" * 64,
        }
        return {
            **gate.LOCAL_PRESERVATION_STATIC,
            **gate.LOCAL_PRESERVATION_STATUS,
            "FRPC_PROCESS_LOCAL": "OBSERVED_UNATTESTED",
            **fake_hashes,
            "SECRET_MUST_NOT_LEAK": "DONT_PRINT_ME",
            "LOCAL_PEER": "DONT_PRINT_ME",
        }

    def test_ir_local_preservation_equal_hashes_are_never_install_permission(self):
        before = self.ir_local_preservation_fixture()
        after = dict(before)
        result = gate.compare_ir_local_preservation(before, after)
        self.assertEqual(result["PRESERVATION_LOCAL"], "MATCH_UNATTESTED")
        self.assertEqual(result["PRESERVATION_REASON"], "LOCAL_HASHES_MATCH_NOT_SIGNED_HEALTH")
        self.assertEqual(result["SIGNED_RUNTIME_CONTINUITY"], "NOT_PROVEN")
        self.assertEqual(result["BACKHAUL_HOST_TRANSACTION"], "NOT_AUTHORIZED")
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
        self.assertNotIn("DONT_PRINT_ME", str(result))
        self.assertNotIn("c" * 64, str(result))

    def test_ir_local_preservation_any_modified_digest_fails_closed(self):
        baseline = self.ir_local_preservation_fixture()
        for key, expected in gate.LOCAL_PRESERVATION_DIGEST_REASON.items():
            with self.subTest(key=key):
                changed = dict(baseline)
                changed[key] = "0" * 64
                result = gate.compare_ir_local_preservation(baseline, changed)
                self.assertEqual(result["PRESERVATION_LOCAL"], "HOLD")
                self.assertEqual(result["PRESERVATION_REASON"], expected)
                self.assertEqual(result["INSTALL_ALLOWED"], "NO")
                self.assertNotIn("DONT_PRINT_ME", str(result))

    def test_ir_local_preservation_missing_corrupt_or_forged_receipt_is_hold(self):
        baseline = self.ir_local_preservation_fixture()
        for key in list(gate.LOCAL_PRESERVATION_DIGEST_REASON) + list(
            gate.LOCAL_PRESERVATION_STATIC) + list(gate.LOCAL_PRESERVATION_STATUS):
            with self.subTest(key=key):
                changed = dict(baseline)
                changed.pop(key)
                result = gate.compare_ir_local_preservation(baseline, changed)
                self.assertEqual(result["PRESERVATION_LOCAL"], "HOLD")
                self.assertEqual(result["PRESERVATION_REASON"], "INCOMPLETE_LOCAL_EVIDENCE")
        for wrong in ("UNVERIFIED", "ABSENT", "", "a" * 63, "G" * 64, 42, None, [], {}):
            with self.subTest(wrong=repr(wrong)):
                changed = dict(baseline)
                changed["NODE_CONTAINER_ID_SHA256"] = wrong
                result = gate.compare_ir_local_preservation(baseline, changed)
                self.assertEqual(result["PRESERVATION_REASON"], "INCOMPLETE_LOCAL_EVIDENCE")
        for wrong in (None, False, "DONT_PRINT_ME", [], {}):
            self.assertEqual(gate.compare_ir_local_preservation(baseline, wrong)[
                "PRESERVATION_LOCAL"], "HOLD")

    def test_ir_local_preservation_frpc_absent_is_distinct_and_role_is_pinned(self):
        before = self.ir_local_preservation_fixture()
        after = dict(before)
        before["FRPC_PROCESS_LOCAL"] = after["FRPC_PROCESS_LOCAL"] = "NOT_OBSERVED"
        before["FRPC_INSTANCE_SHA256"] = after["FRPC_INSTANCE_SHA256"] = "ABSENT"
        result = gate.compare_ir_local_preservation(before, after)
        self.assertEqual(result["PRESERVATION_LOCAL"], "MATCH_UNATTESTED")
        changed = dict(after)
        changed["FRPC_PROCESS_LOCAL"] = "OBSERVED_UNATTESTED"
        changed["FRPC_INSTANCE_SHA256"] = "c" * 64
        self.assertEqual(gate.compare_ir_local_preservation(before, changed)[
            "PRESERVATION_REASON"], "FRPC_PROCESS_CHANGED")
        changed = dict(after)
        changed["NODE_ROLE"] = "KH"
        self.assertEqual(gate.compare_ir_local_preservation(before, changed)[
            "PRESERVATION_REASON"], "INCOMPLETE_LOCAL_EVIDENCE")
        changed = dict(after)
        changed["SAVED_TUNNELS"] = "ZERO"
        self.assertEqual(gate.compare_ir_local_preservation(before, changed)[
            "PRESERVATION_REASON"], "INCOMPLETE_LOCAL_EVIDENCE")

    def test_ir_local_preservation_cannot_substitute_signed_image_or_owner(self):
        before = self.ir_local_preservation_fixture()
        after = dict(before)
        for key, val in (
            ("SIGNED_REGISTRY_PAIR_PROOF", "NOT_SUPPLIED"),
            ("OTHER_ENGINE", "UNAVAILABLE"),
            ("FRPS_PROCESS_LOCAL", "NOT_OBSERVED"),
            ("BROKER_SOCKET_LOCAL", "ABSENT"),
            ("WSS_EDGE_JOURNAL_LOCAL", "UNVERIFIED"),
            ("INSTALL_ALLOWED", "YES"),
            ("ACTIVATION_GATE", "READY"),
            ("HOST_TRANSACTION_AND_ROLLBACK", "IMPLEMENTED"),
        ):
            with self.subTest(key=key):
                changed = dict(after)
                changed[key] = val
                result = gate.compare_ir_local_preservation(before, changed)
                self.assertEqual(result["PRESERVATION_LOCAL"], "HOLD")
                self.assertEqual(result["INSTALL_ALLOWED"], "NO")
                self.assertEqual(result["ACTIVATION_GATE"], "HOLD")


    @staticmethod
    def foreign_local_preservation_fixture():
        """Synthetic local Foreign Child hints, NOT signed or live proof."""
        return {
            **gate.FOREIGN_LOCAL_PRESERVATION_STATIC,
            "SAVED_TUNNEL_REGISTRY_SHA256": "a" * 64,
            "NODE_CONTAINER_ID_SHA256": "b" * 64,
            "FRPC_INSTANCE_SHA256": "c" * 64,
            "SECRET_MUST_NOT_LEAK": "DONT_PRINT_ME",
        }

    def test_foreign_child_local_preservation_is_never_signed_or_install(self):
        foreign = self.foreign_local_preservation_fixture()
        result = gate.compare_foreign_local_preservation(foreign, dict(foreign))
        self.assertEqual(result["PRESERVATION_LOCAL"], "MATCH_UNATTESTED")
        self.assertEqual(result["SIGNED_RUNTIME_CONTINUITY"], "NOT_PROVEN")
        self.assertEqual(result["BACKHAUL_HOST_TRANSACTION"], "NOT_AUTHORIZED")
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
        self.assertNotIn("DONT_PRINT_ME", str(result))
        self.assertNotIn("c" * 64, str(result))

    def test_foreign_child_local_drift_and_corruption_fail_closed(self):
        before = self.foreign_local_preservation_fixture()
        for key, reason in gate.FOREIGN_LOCAL_PRESERVATION_DIGEST_REASON.items():
            with self.subTest(drift=key):
                modified = dict(before)
                modified[key] = "0" * 64
                result = gate.compare_foreign_local_preservation(before, modified)
                self.assertEqual(result["PRESERVATION_LOCAL"], "HOLD")
                self.assertEqual(result["PRESERVATION_REASON"], reason)
                self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        for key in gate.FOREIGN_LOCAL_PRESERVATION_STATIC:
            with self.subTest(missing=key):
                modified = dict(before)
                modified.pop(key)
                result = gate.compare_foreign_local_preservation(before, modified)
                self.assertEqual(result["PRESERVATION_LOCAL"], "HOLD")
                self.assertEqual(result["PRESERVATION_REASON"],
                                 "INCOMPLETE_LOCAL_EVIDENCE")
        for value in ("ABSENT", "UNVERIFIED", "d" * 63, "X" * 64,
                      None, [], {}, 0):
            with self.subTest(digest=repr(value)):
                modified = dict(before)
                modified["FRPC_INSTANCE_SHA256"] = value
                self.assertEqual(
                    gate.compare_foreign_local_preservation(before, modified)[
                        "PRESERVATION_LOCAL"], "HOLD")

    def test_foreign_child_never_accepts_ir_owner_or_fabricated_broker(self):
        before = self.foreign_local_preservation_fixture()
        for key, wrong in (
            ("NODE_ROLE", "IR"),
            ("FRPC_PROCESS_LOCAL", "NOT_OBSERVED"),
            ("FRPC_INSTANCE_SHA256", "ABSENT"),
            ("FRPS_PROCESS_LOCAL", "OBSERVED_UNATTESTED"),
            ("FRPS_INSTANCE_SHA256", "d" * 64),
            ("BROKER_SOCKET_LOCAL", "PRESENT_UNATTESTED"),
            ("BROKER_SOCKET_ID_SHA256", "e" * 64),
            ("WSS_EDGE_JOURNAL_LOCAL", "COMMITTED_LOCAL_UNATTESTED"),
            ("WSS_EDGE_JOURNAL_SHA256", "f" * 64),
            ("SIGNED_REGISTRY_PAIR_PROOF", "NOT_SUPPLIED"),
            ("SAVED_TUNNELS", "ZERO"),
            ("INSTALL_ALLOWED", "YES"),
            ("ACTIVATION_GATE", "READY"),
            ("HOST_TRANSACTION_AND_ROLLBACK", "IMPLEMENTED"),
        ):
            with self.subTest(key=key):
                modified = dict(before)
                modified[key] = wrong
                result = gate.compare_foreign_local_preservation(before, modified)
                self.assertEqual(result["PRESERVATION_LOCAL"], "HOLD")
                self.assertEqual(result["INSTALL_ALLOWED"], "NO")
                self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
        for wrong in (None, False, [], {}, "DONT_PRINT_ME"):
            self.assertEqual(
                gate.compare_foreign_local_preservation(before, wrong)[
                    "PRESERVATION_LOCAL"], "HOLD")

    def test_two_host_local_preservation_requires_both_and_never_authorizes(self):
        ir = self.ir_local_preservation_fixture()
        foreign = self.foreign_local_preservation_fixture()
        result = gate.compare_two_host_local_preservation(
            ir, dict(ir), foreign, dict(foreign))
        self.assertEqual(result["TWO_HOST_PRESERVATION_LOCAL"], "MATCH_UNATTESTED")
        self.assertEqual(result["IR_LOCAL"], "MATCH_UNATTESTED")
        self.assertEqual(result["FOREIGN_LOCAL"], "MATCH_UNATTESTED")
        self.assertEqual(result["SIGNED_OWNER_CHILD_CONTINUITY"], "NOT_PROVEN")
        self.assertEqual(result["BACKHAUL_HOST_TRANSACTION"], "NOT_AUTHORIZED")
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
        self.assertNotIn("DONT_PRINT_ME", str(result))
        for role in ("ir", "foreign", "swapped", "missing"):
            with self.subTest(role=role):
                changed_ir, changed_foreign = dict(ir), dict(foreign)
                if role == "ir":
                    changed_ir["FRPS_INSTANCE_SHA256"] = "0" * 64
                elif role == "foreign":
                    changed_foreign["FRPC_INSTANCE_SHA256"] = "0" * 64
                elif role == "swapped":
                    changed_ir, changed_foreign = dict(foreign), dict(ir)
                else:
                    changed_foreign.pop("SAVED_TUNNEL_REGISTRY_SHA256")
                rejected = gate.compare_two_host_local_preservation(
                    ir, changed_ir, foreign, changed_foreign)
                self.assertEqual(rejected["TWO_HOST_PRESERVATION_LOCAL"], "HOLD")
                self.assertEqual(rejected["INSTALL_ALLOWED"], "NO")
                self.assertEqual(rejected["ACTIVATION_GATE"], "HOLD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
