#!/usr/bin/env python3
"""Non-root, offline, no-Docker regression tests of the disposable executor."""
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tests/lab/smite_host_executor.py"
spec = importlib.util.spec_from_file_location("smite_host_txn_lab_ci", MODULE)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class HostTransactionLab(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="uopti-engine-txn-lab-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root))
        self.root.chmod(0o700)
        (self.root / ".LAB_ONLY").write_bytes(lab.MARKER)
        node = self.root / "node"
        (node / "config/engine-state").mkdir(parents=True, mode=0o700)
        for name, data in {
            "docker-compose.yml": b"services:\n  smite-node:\n    image: test-pinned\n",
            ".env": b"SMITE_AGENT_AUTH_MODE=strict\n",
            "config/node-id": b"node-identity-persistent",
            "config/replay.db": b"replay-db-immutable",
            "config/tunnels.json": b"[]\n",
        }.items():
            path = node / name
            path.write_bytes(data)
            path.chmod(0o600)
        self.node = node
        self.calls = []

    def probe(self, kind, engine):
        self.calls.append((kind, engine))
        return {"signed": True, "replay": True}

    def candidate(self, engine):
        binaries = {name: ("SYNTHETIC-ELF-NO-EXEC-" + name).encode()
                    for name in lab.BINARIES[engine]}
        overlay = ("services:\n  smite-node:\n    volumes:\n"
                   "      - ./disposable-" + engine + ":/tmp/disposable:ro\n").encode()
        file = self.node / "config/engine-state/engines.json"
        prior = json.loads(file.read_bytes()) if file.exists() else {"schema": 1, "engines": {}}
        new = dict(prior["engines"])
        new[engine] = {"sha256": lab.sha(binaries[lab.BINARIES[engine][0]])}
        if engine == "frp":
            new[engine]["server_sha256"] = lab.sha(binaries["frps"])
        preview = {
            "STAGE_ADMISSION": "VERIFIED_PREVIEW_ONLY",
            "OTHER_ENGINE": ("SIGNED_READY_ATTESTED_SIMULATED" if
                             any(k != engine for k in prior["engines"]) else "NOT_INSTALLED"),
            "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
            "BINARIES_SHA256": [lab.sha(binaries[k]) for k in lab.BINARIES[engine]],
            "SOURCE_COMPOSE_SHA256": lab.sha((self.node / "docker-compose.yml").read_bytes()),
            "CANDIDATE_COMPOSE_OVERLAY_SHA256": lab.sha(overlay),
            "CANDIDATE_MANIFEST_SHA256":
                lab.sha(lab.canonical({"schema": 1, "engines": new})),
        }
        return binaries, overlay, preview

    def apply(self, engine, crash_at=None, probe=None):
        binaries, overlay, preview = self.candidate(engine)
        return lab.execute(self.root, engine, binaries, overlay, preview,
                           probe or self.probe, crash_at=crash_at)

    def check_prior(self):
        node = self.root / "node"
        self.assertFalse((node / "config/engine-state/engines.json").exists())
        for engine in lab.BINARIES:
            for name in lab.BINARIES[engine]:
                self.assertFalse((node / "managed-bin" / engine / name).exists())
            self.assertFalse((node / ("docker-compose.managed-" + engine + ".yml")).exists())
        self.assertEqual((node / "config/node-id").read_bytes(), b"node-identity-persistent")
        self.assertEqual((node / "config/replay.db").read_bytes(), b"replay-db-immutable")

    def test_backhaul_and_frp_standalone_never_enable_real_host(self):
        engine = "backhaul"
        result = self.apply(engine)
        self.assertEqual(result["LAB_RESULT"], "COMMITTED_SIMULATION_ONLY")
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
        self.assertEqual(lab.recover(self.root, self.probe), "COMMITTED")
        self.assertEqual(self.calls[-1], ("new", engine))
        manifest = json.loads((self.node / "config/engine-state/engines.json").read_bytes())
        self.assertIn(engine, manifest["engines"])

    def test_frp_first_independent_of_backhaul(self):
        self.apply("frp")
        manifest = json.loads((self.node / "config/engine-state/engines.json").read_bytes())
        self.assertEqual(set(manifest["engines"]), {"frp"})
        self.assertEqual(len(list((self.node / "managed-bin/frp").iterdir())), 2)

    def test_coexistence_second_engine_never_overwrites_first(self):
        self.apply("backhaul")
        saved = {}
        for filename in ("managed-bin/backhaul/backhaul",
                         "docker-compose.managed-backhaul.yml", "config/node-id", "config/replay.db"):
            saved[filename] = (self.node / filename).read_bytes()
        self.apply("frp")
        manifest = json.loads((self.node / "config/engine-state/engines.json").read_bytes())
        self.assertEqual(set(manifest["engines"]), {"backhaul", "frp"})
        for filename, original in saved.items():
            self.assertEqual((self.node / filename).read_bytes(), original)
        self.assertTrue(list(self.root.glob("audit-*.json")))
        self.assertIn(("other", "backhaul"), self.calls)

    def test_crash_every_checkpoint_recovers_exact_preimages(self):
        for engine in ("frp", "backhaul"):
            checkpoints = ("before_copy", "after_frpc", "after_frps", "after_compose",
                           "after_manifest", "during_restart", "after_restart", "after_signed") \
                if engine == "frp" else ("before_copy", "after_backhaul", "after_compose",
                                        "after_manifest", "during_restart", "after_restart", "after_signed")
            for checkpoint in checkpoints:
                with self.subTest(engine=engine, checkpoint=checkpoint):
                    with tempfile.TemporaryDirectory(prefix="uopti-engine-txn-lab-") as place:
                        # Use a distinct sandbox per case while preserving private lab policy.
                        original_root = self.root
                        self.root = Path(place)
                        (self.root / ".LAB_ONLY").write_bytes(lab.MARKER)
                        __import__("shutil").copytree(self.node, self.root / "node")
                        try:
                            with self.assertRaises(lab.SimulatedCrash):
                                self.apply(engine, crash_at=checkpoint)
                            self.assertEqual(lab.recover(self.root, self.probe), "ROLLED_BACK")
                            self.check_prior()
                            self.assertEqual(lab.recover(self.root, self.probe), "ROLLED_BACK")
                            self.assertIn(("prior", engine), self.calls)
                        finally:
                            self.root = original_root

    def test_process_death_after_restart_recovers_from_disk_journal(self):
        # The entire process exits abruptly instead of raising an exception.
        # Recovery is done by a DIFFERENT process using fsynced disk state.
        binaries, overlay, preview = self.candidate("frp")
        payload = {"engine": "frp", "binaries":
                   {name: data.hex() for name, data in binaries.items()},
                   "overlay": overlay.hex(), "preview": preview}
        child = """
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("host_lab_child", sys.argv[1])
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)
data = json.loads(os.environ["UOPTI_LAB_PAYLOAD"])
def power_cut(kind, engine):
    os._exit(73)
lab.execute(sys.argv[2], data["engine"],
            {name: bytes.fromhex(value) for name, value in data["binaries"].items()},
            bytes.fromhex(data["overlay"]), data["preview"], power_cut)
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", child, str(MODULE), str(self.root)],
            env={**os.environ, "UOPTI_LAB_PAYLOAD": json.dumps(payload)},
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 73)
        self.assertTrue((self.root / ".engine-journal.json").exists())
        self.assertEqual(lab.recover(self.root, self.probe), "ROLLED_BACK")
        self.check_prior()

    def test_external_manifest_edit_blocks_recovery_without_overwrite(self):
        with self.assertRaises(lab.SimulatedCrash):
            self.apply("frp", crash_at="after_manifest")
        manifest = self.node / "config/engine-state/engines.json"
        manifest.write_bytes(b"EXTERNAL_MANIFEST_CHANGE")
        with self.assertRaisesRegex(lab.Hold, "EXTERNAL_MUTATION_CONFLICT"):
            lab.recover(self.root, self.probe)
        self.assertEqual(manifest.read_bytes(), b"EXTERNAL_MANIFEST_CHANGE")

    def test_protected_identity_and_other_engine_edit_block_rollback(self):
        self.apply("backhaul")
        with self.assertRaises(lab.SimulatedCrash):
            self.apply("frp", crash_at="after_frpc")
        first = self.node / "managed-bin/backhaul/backhaul"
        first.write_bytes(b"UNEXPECTED_OUTSIDE_CHANGE")
        with self.assertRaisesRegex(lab.Hold, "PROTECTED_OR_OTHER_ENGINE_DRIFT"):
            lab.recover(self.root, self.probe)
        self.assertEqual(first.read_bytes(), b"UNEXPECTED_OUTSIDE_CHANGE")

    def test_failed_signed_restart_triggers_prior_runtime_compensation(self):
        def reject_new(kind, engine):
            return {"signed": kind == "prior", "replay": True}
        with self.assertRaisesRegex(lab.Hold, "SIGNED_RUNTIME_SIMULATION_FAILED"):
            self.apply("backhaul", probe=reject_new)
        self.check_prior()
        self.assertEqual(lab.recover(self.root, reject_new), "ROLLED_BACK")

    def test_recovery_retries_when_prior_signed_proof_missing(self):
        with self.assertRaises(lab.SimulatedCrash):
            self.apply("backhaul", crash_at="after_compose")
        with self.assertRaisesRegex(lab.Hold, "SIGNED_RUNTIME_SIMULATION_FAILED"):
            lab.recover(self.root, lambda *_: {"signed": False, "replay": True})
        self.assertEqual(lab.recover(self.root, self.probe), "ROLLED_BACK")
        self.check_prior()

    def test_other_engine_incomplete_or_unsigned_blocks_second_install(self):
        self.apply("backhaul")
        binaries, overlay, preview = self.candidate("frp")
        preview["OTHER_ENGINE"] = "NOT_INSTALLED"
        with self.assertRaisesRegex(lab.Hold, "OTHER_ENGINE_SIGNED_PROOF_REQUIRED"):
            lab.execute(self.root, "frp", binaries, overlay, preview, self.probe)
        preview["OTHER_ENGINE"] = "SIGNED_READY_ATTESTED_SIMULATED"

        def deny_existing(kind, engine):
            return {"signed": kind != "other", "replay": True}
        with self.assertRaisesRegex(lab.Hold, "SIGNED_RUNTIME_SIMULATION_FAILED"):
            lab.execute(self.root, "frp", binaries, overlay, preview, deny_existing)
        self.assertFalse((self.node / "managed-bin/frp").exists())
        self.assertEqual(set(json.loads(
            (self.node / "config/engine-state/engines.json").read_bytes())["engines"]),
            {"backhaul"})

    def test_changed_modes_also_block_rollback(self):
        with self.assertRaises(lab.SimulatedCrash):
            self.apply("frp", crash_at="after_frpc")
        binary = self.node / "managed-bin/frp/frpc"
        binary.chmod(0o777)
        with self.assertRaisesRegex(lab.Hold, "EXTERNAL_MUTATION_CONFLICT"):
            lab.recover(self.root, self.probe)
        self.assertEqual(stat.S_IMODE(binary.stat().st_mode), 0o777)

    def test_shared_lock_rejects_second_transaction(self):
        lock = os.open(self.root / ".shared-engine.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(lab.Hold, "SHARED_ENGINE_TRANSACTION_LOCKED"):
                self.apply("frp")
            self.assertFalse((self.root / ".engine-journal.json").exists())
        finally:
            os.close(lock)

    def test_unsafe_root_symlinks_and_preview_do_not_write(self):
        with self.assertRaisesRegex(lab.Hold, "DISPOSABLE_LAB_ROOT_REQUIRED"):
            lab.execute(self.root / "node", "backhaul", {}, b"", {}, self.probe)
        binaries, overlay, preview = self.candidate("backhaul")
        preview["INSTALL_ALLOWED"] = "YES"
        with self.assertRaisesRegex(lab.Hold, "PLAN_PREVIEW_INVALID"):
            lab.execute(self.root, "backhaul", binaries, overlay, preview, self.probe)
        manifest = self.node / "config/engine-state/engines.json"
        manifest.symlink_to(self.node / "config/node-id")
        with self.assertRaises(lab.Hold):
            lab.execute(self.root, "backhaul", binaries, overlay,
                        {**preview, "INSTALL_ALLOWED": "NO"}, self.probe)
        self.assertEqual((self.node / "config/node-id").read_bytes(), b"node-identity-persistent")

    def test_no_host_executor_cli_or_network_capabilities(self):
        text = MODULE.read_text()
        for forbidden in ("subprocess.run(", "os.system(", "socket.socket(",
                          "requests.get(", "urllib.request", "docker compose up",
                          "systemctl restart", "paramiko", "nginx -s"):
            self.assertNotIn(forbidden, text)
        self.assertNotIn("if __name__ == ", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
