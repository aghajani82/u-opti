#!/usr/bin/env python3
"""CI-only Backhaul install → signed probe → restart → rollback contracts.

Unit tests use inert ELF bytes; they never start Docker, network or services.
Real official Backhaul + HMAC API integration runs in a separate PR workflow.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / "modules"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, HERE / path)
    val = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(val)
    return val


pkg = module("bh_pkg_lifecycle_test", "smite-managed-backhaul.py")
life = module("bh_lifecycle_test", "smite-managed-backhaul-lifecycle.py")
tx = life.tx
ctl = life.ctl

ENV = """NODE_ROLE=foreign
SMITE_AGENT_AUTH_MODE=strict
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_ENGINE_INVENTORY_MODE=managed
"""
COMPOSE = """services:
  smite-node:
    image: smite-node:stage15-local
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
"""


class Trial(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="backhaul-lifecycle-ci-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        (self.root / "EXPERIMENTAL-LAB").write_text(tx.MARKER)
        node = self.root / "node"
        node.mkdir(mode=0o700)
        (node / "config").mkdir(mode=0o700)
        (node / ".env").write_text(ENV)
        (node / "docker-compose.yml").write_text(COMPOSE)
        (self.root / "stages").mkdir(mode=0o700)
        (self.root / "node-data").mkdir(mode=0o700)
        self.node = node
        self.identity = node / "config/identity/node-identity.json"
        self.identity.parent.mkdir(mode=0o700)
        self.identity.write_text('{"secret": "NEVER_PRINT_THIS_SYNTHETIC_SECRET"}')
        self.identity.chmod(0o600)
        blob = b"\x7fELF" + b"BACKHAUL_TEST_NOT_EXECUTABLE"
        archive = self.root / "demo.tar.gz"
        with tarfile.open(archive, mode="w:gz") as tf:
            member = tarfile.TarInfo("backhaul")
            member.size = len(blob)
            tf.addfile(member, io.BytesIO(blob))
        self.stage = pkg.prepare(node, archive, self.root / "stages",
                                 arch="amd64", allowed_sha=hashlib.sha256(archive.read_bytes()).hexdigest())
        self.env = patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": "aghajani82/u-opti",
            "RUNNER_TEMP": str(self.root.parent),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        real_activate = tx.activate
        self.test_activate = patch.object(
            tx, "activate",
            side_effect=lambda root, stage, **kw: real_activate(root, stage, fixture=True, **kw),
        )
        self.test_activate.start()
        self.addCleanup(self.test_activate.stop)
        self.proof = patch.object(ctl, "verified_candidate", return_value={"state": "VERIFIED_CANDIDATE_ONLY"})
        self.proof.start()
        self.addCleanup(self.proof.stop)
        original = tx.candidate
        self.test_candidate = patch.object(
            tx, "candidate",
            side_effect=lambda root, stage, **kwargs: original(root, stage, fixture=True),
        )
        self.test_candidate.start()
        self.addCleanup(self.test_candidate.stop)
        # Unit-test runner file is not root-owned. Real Docker CI uses root.
        self.actual_inspect = ctl.inspect
        def mocked_inspect(node, *, lab_binary=None):
            manifest = node / "config/engine-state/engines.json"
            binary = self.root / "installed/backhaul"
            if not manifest.exists():
                return {"state": "NOT_INSTALLED"}
            if not binary.is_file():
                return {"state": "UNAVAILABLE"}
            record = json.loads(manifest.read_text())["engines"]
            if "backhaul" not in record:
                return {"state": "NOT_INSTALLED" if not binary.exists() else "UNAVAILABLE"}
            data = record["backhaul"]["sha256"]
            return {"state": "ENROLLED_UNVERIFIED" if hashlib.sha256(binary.read_bytes()).hexdigest() == data else "UNAVAILABLE"}
        self.inspect_patch = patch.object(ctl, "inspect", side_effect=mocked_inspect)
        self.inspect_patch.start()
        self.addCleanup(self.inspect_patch.stop)

    def verify_clean(self):
        self.assertEqual((self.node / "docker-compose.yml").read_text(), COMPOSE)
        self.assertFalse((self.node / "config/engine-state/engines.json").exists())
        self.assertFalse((self.root / "installed/backhaul").exists())
        self.assertFalse((self.root / "recovery-journal").exists())
        self.assertIn("NEVER_PRINT_THIS_SYNTHETIC_SECRET", self.identity.read_text())

    def test_success_rehearsal_is_always_rolled_back(self):
        calls = []
        def ready(root):
            calls.append("ready")
            self.assertTrue((root / "installed/backhaul").is_file())
            return True
        def absent(root):
            calls.append("absent")
            self.assertFalse((root / "installed/backhaul").exists())
            return True
        report = life.run_lab_rehearsal(self.root, self.stage,
                                       check_ready=ready, check_absent=absent)
        self.assertEqual(calls, ["ready", "absent"])
        self.assertEqual(report["PRODUCTION_ACTIVATION"], "HOLD")
        self.assertEqual(report["TRIAL_ROLLBACK"], "BYTES_AND_MODES_RESTORED")
        self.verify_clean()

    def _existing_frp_fixture(self):
        # A genuine FRP-pinned local inventory already occupying the shared
        # engine directory. Its bytes and hashes must NEVER change.
        installed = self.root / "installed"
        installed.mkdir(mode=0o700)
        frp_dir = installed / "frp"
        frp_dir.mkdir(mode=0o700)
        existing = {}
        for name in ("frpc", "frps"):
            value = b"\x7fELF" + name.encode() + b"-already-installed"
            path = frp_dir / name
            path.write_bytes(value)
            path.chmod(0o755)
            existing[name] = value
        before = COMPOSE.replace(
            "      - ./config:/etc/smite-node\n",
            "      - ./config:/etc/smite-node\n" +
            "".join(f"      - {frp_dir / name}:/usr/local/bin/{name}:ro\n"
                    for name in ("frpc", "frps")))
        self.node.joinpath("docker-compose.yml").write_text(before)
        state = self.node / "config" / "engine-state"
        state.mkdir(mode=0o700)
        manifest = state / "engines.json"
        record = {"schema": 1, "engines": {"frp": {
            "sha256": hashlib.sha256(existing["frpc"]).hexdigest(),
            "server_sha256": hashlib.sha256(existing["frps"]).hexdigest()}}}
        manifest.write_text(json.dumps(record))
        manifest.chmod(0o600)
        stage = pkg.prepare(
            self.node, self.archive, self.root / "stages",
            arch="amd64", allowed_sha=hashlib.sha256(self.archive.read_bytes()).hexdigest())
        return stage, before.encode(), manifest.read_bytes(), existing

    def test_existing_frp_needs_three_signed_checks_and_exact_rollback(self):
        stage, prior_compose, prior_manifest, prior_binary = self._existing_frp_fixture()
        with self.assertRaisesRegex(life.Hold, "EXISTING_FRP_SIGNED_PROOF_REQUIRED"):
            life.run_lab_rehearsal(
                self.root, stage, check_ready=lambda _: True,
                check_absent=lambda _: True)
        self.assertEqual(self.node.joinpath("docker-compose.yml").read_bytes(), prior_compose)
        self.assertFalse((self.root / "recovery-journal").exists())
        calls = []
        def other(root, phase):
            calls.append(phase)
            state = json.loads((self.node / "config/engine-state/engines.json").read_text())
            self.assertEqual(state["engines"]["frp"]["sha256"],
                             hashlib.sha256(prior_binary["frpc"]).hexdigest())
            for name, payload in prior_binary.items():
                self.assertEqual((root / "installed/frp" / name).read_bytes(), payload)
            return phase in ("before", "with-backhaul", "after-rollback")
        status = life.run_lab_rehearsal(
            self.root, stage, check_ready=lambda _: True,
            check_absent=lambda _: True, check_other=other)
        self.assertEqual(calls, ["before", "with-backhaul", "after-rollback"])
        self.assertEqual(status["EXISTING_FRP_SIGNED_RUNTIME"],
                         "BEFORE_WITH_BACKHAUL_AND_AFTER_ROLLBACK_VERIFIED")
        self.assertEqual(status["PRODUCTION_ACTIVATION"], "HOLD")
        self.assertEqual(self.node.joinpath("docker-compose.yml").read_bytes(), prior_compose)
        self.assertEqual((self.node / "config/engine-state/engines.json").read_bytes(),
                         prior_manifest)
        self.assertFalse((self.root / "installed/backhaul").exists())
        self.assertFalse((self.root / "recovery-journal").exists())

    def test_existing_frp_failed_signed_pre_and_post_checks_never_claim_success(self):
        stage, prior_compose, prior_manifest, prior_binary = self._existing_frp_fixture()
        with self.assertRaisesRegex(life.Hold, "EXISTING_FRP_PRIOR_SIGNED_RUNTIME_NOT_VERIFIED"):
            life.run_lab_rehearsal(
                self.root, stage, check_ready=lambda _: self.fail("no install"),
                check_absent=lambda _: self.fail("no rollback"),
                check_other=lambda root, phase: False)
        self.assertFalse((self.root / "recovery-journal").exists())
        calls = []
        def other(root, phase):
            calls.append(phase)
            return phase != "with-backhaul"
        with self.assertRaisesRegex(life.Hold, "ACTIVATION_FAILED_EXACT_ROLLBACK_PROVED"):
            life.run_lab_rehearsal(
                self.root, stage, check_ready=lambda _: True,
                check_absent=lambda _: True, check_other=other)
        self.assertEqual(calls, ["before", "with-backhaul", "after-rollback"])
        self.assertFalse((self.root / "recovery-journal").exists())
        with self.assertRaisesRegex(life.Hold, "EXISTING_FRP_AFTER_ROLLBACK_NOT_VERIFIED"):
            life.run_lab_rehearsal(
                self.root, stage, check_ready=lambda _: True,
                check_absent=lambda _: True,
                check_other=lambda _, phase: phase != "after-rollback")
        self.assertFalse((self.root / "installed/backhaul").exists())
        self.assertEqual(self.node.joinpath("docker-compose.yml").read_bytes(), prior_compose)
        self.assertEqual((self.node / "config/engine-state/engines.json").read_bytes(),
                         prior_manifest)
        for name, payload in prior_binary.items():
            self.assertEqual((self.root / "installed/frp" / name).read_bytes(), payload)

    def test_signed_ready_failure_forces_rollback_and_absent_proof(self):
        calls = []
        def failure(_):
            calls.append("ready")
            raise RuntimeError("SYNTHETIC_SECRET_MUST_NOT_APPEAR")
        def absent(_):
            calls.append("absent")
            return True
        with self.assertRaisesRegex(life.Hold, "ACTIVATION_FAILED_EXACT_ROLLBACK_PROVED") as exc:
            life.run_lab_rehearsal(self.root, self.stage,
                                   check_ready=failure, check_absent=absent)
        self.assertNotIn("SYNTHETIC_SECRET", str(exc.exception))
        self.assertEqual(calls, ["ready", "absent"])
        self.verify_clean()

    def test_failed_probe_return_false_also_rolls_back(self):
        with self.assertRaisesRegex(life.Hold, "ACTIVATION_FAILED_EXACT_ROLLBACK_PROVED"):
            life.run_lab_rehearsal(
                self.root, self.stage,
                check_ready=lambda root: False, check_absent=lambda root: True)
        self.verify_clean()

    def test_crash_after_binary_or_compose_is_recovered(self):
        for step in ("after-binary", "after-compose", "after-manifest"):
            with self.subTest(stage=step):
                with self.assertRaisesRegex(life.Hold, "ACTIVATION_FAILED_EXACT_ROLLBACK_PROVED"):
                    life.run_lab_rehearsal(
                        self.root, self.stage,
                        check_ready=lambda root: self.fail("unexpected ready"),
                        check_absent=lambda root: True, inject=step)
                self.verify_clean()

    def test_restored_bytes_without_healthy_old_node_are_hard_hold(self):
        with self.assertRaisesRegex(life.Hold, "PREVIOUS_SIGNED_NODE_RUNTIME_NOT_RESTORED"):
            life.run_lab_rehearsal(
                self.root, self.stage,
                check_ready=lambda root: True, check_absent=lambda root: False)
        self.verify_clean()

    def test_active_saved_tunnels_stop_trial_before_mutation(self):
        (self.root / "node-data/tunnels.json").write_text(
            '{"active":{"core":"frp","spec":{"token":"NEVER_PRINT_THIS_SECRET"}}}')
        with self.assertRaisesRegex(life.Hold, "EXISTING_TUNNELS_DO_NOT_RECREATE"):
            life.run_lab_rehearsal(
                self.root, self.stage,
                check_ready=lambda root: self.fail("must not start"),
                check_absent=lambda root: self.fail("must not run"))
        self.verify_clean()

    def test_identity_modified_after_install_causes_hold_and_keeps_evidence(self):
        before = self.identity.read_bytes()
        def tamper(_):
            self.identity.write_text('{"secret":"TAMPERED"}')
            return True
        with self.assertRaisesRegex(life.Hold, "ROLLBACK_BYTES_OR_PROTECTED_STATE_MISMATCH"):
            life.run_lab_rehearsal(
                self.root, self.stage, check_ready=tamper,
                check_absent=lambda root: self.fail("must not certify"))
        self.assertEqual((self.node / "docker-compose.yml").read_text(), COMPOSE)
        self.assertNotEqual(self.identity.read_bytes(), before)

    def test_out_of_band_compose_edit_refuses_destructive_rollback(self):
        def drift(root):
            with (root / "node/docker-compose.yml").open("a") as file:
                file.write("# out-of-band-edit\n")
            return True
        with self.assertRaisesRegex(life.Hold, "ROLLBACK_FAILED_MANUAL_REVIEW_REQUIRED"):
            life.run_lab_rehearsal(
                self.root, self.stage, check_ready=drift,
                check_absent=lambda root: self.fail("must hold"))
        self.assertTrue((self.root / "recovery-journal").exists())
        self.assertIn("# out-of-band-edit", (self.node / "docker-compose.yml").read_text())

    def test_only_pr_runner_can_trigger_mutations(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            with self.assertRaises(tx.Hold):
                life.run_lab_rehearsal(
                    self.root, self.stage,
                    check_ready=lambda root: True, check_absent=lambda root: True)
        self.verify_clean()

    def test_module_has_no_docker_shell_network_executor(self):
        source = (HERE / "smite-managed-backhaul-lifecycle.py").read_text()
        for forbidden in ("subprocess", "docker run", "docker compose up", "systemctl",
                          "requests.", "urllib.", "socket.", "os.system(", "ssh "):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
