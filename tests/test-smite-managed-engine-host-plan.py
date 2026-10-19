#!/usr/bin/env python3
"""Host transaction contract is byte-bound, reproducible and NEVER deployable.

Fully disposable synthetic ELF archive and minimal strict Core; no network,
Docker, SSH, cloud, Node restart, real tunnels or system path mutations.
"""
import hashlib
import importlib.util
import io
import json
import shutil
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules/smite-managed-engine-host-plan.py"
spec = importlib.util.spec_from_file_location("uopti_host_transaction_plan_ci", SCRIPT)
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)

lab_spec = importlib.util.spec_from_file_location(
    "uopti_host_plan_bound_recovery_lab", ROOT / "tests/lab/smite_host_executor.py")
lab = importlib.util.module_from_spec(lab_spec)
lab_spec.loader.exec_module(lab)

ENV = ("NODE_ROLE=foreign\nSMITE_ENGINE_INVENTORY_MODE=managed\n"
       "SMITE_AGENT_AUTH_MODE=strict\nSMITE_NODE_PANEL_AUTH_MODE=paused\n")
COMPOSE = ("services:\n  smite-node:\n    image: ghcr.io/zzedix/smite-node@sha256:"
           "967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e\n"
           "    network_mode: host\n    volumes:\n"
           "      - ./config:/etc/smite-node\n"
           "      - node-data:/var/lib/smite-node\n"
           "volumes:\n  node-data:\n    name: smite-node-data\n")


def synthetic_frp_exe(name):
    blob = bytearray(128)
    blob[:4] = b"\x7fELF"
    blob[4:6] = bytes([2, 1])
    struct.pack_into("<H", blob, 18, 62)
    return bytes(blob) + name.encode()


class HostPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="uopti-host-plan-test-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.node = self.home / "node"
        self.node.mkdir()
        (self.node / "config").mkdir()
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)
        self.root = self.home / "stages"
        self.root.mkdir(mode=0o700)
        self.archive = self.home / "frp.tar.gz"
        folder = "frp_0.71.0_linux_amd64"
        with tarfile.open(self.archive, "w:gz") as tf:
            for binary in ("frpc", "frps"):
                blob = synthetic_frp_exe(binary)
                info = tarfile.TarInfo(folder + "/" + binary)
                info.size = len(blob)
                tf.addfile(info, io.BytesIO(blob))
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        patcher = patch.dict(plan.frp.OFFICIAL_TAR_SHA256, {"amd64": digest})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.stage = plan.frp.prepare(self.node, self.archive, self.root, arch="amd64",
                                      allowed_sha=digest)
        self.status = {
            "ENGINE": "FRP", "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD",
            "LOCAL_PREFLIGHT": "PASS_LOCAL_ONLY_INCOMPLETE",
            "TARGET_ENGINE": "NOT_INSTALLED", "OTHER_ENGINE": "NOT_INSTALLED",
            "SAVED_TUNNELS": "ZERO", "CORE_PROFILE": "MANAGED_STRICT",
            "NODE_CONTAINER": "RUNNING_REVIEWED_IMAGE",
        }
        underlying = plan.admission.host._local_file

        def read_fixture(path, *, max_bytes, require_root=False):
            # Production keeps require_root; fixture is not root-owned.
            return underlying(path, max_bytes=max_bytes, require_root=False)

        patch_owner = patch.object(plan.admission.host, "_local_file", side_effect=read_fixture)
        patch_owner.start()
        self.addCleanup(patch_owner.stop)

    def preview(self):
        return plan.review("frp", self.node, self.stage, staging_root=self.root,
                           host_status=self.status)

    def test_official_pinned_frp_plan_matches_files_but_host_install_never_allowed(self):
        first = self.preview()
        self.assertEqual(first["STAGE_ADMISSION"], "VERIFIED_PREVIEW_ONLY")
        self.assertEqual(first["ARTIFACT_PROVENANCE"], "OFFICIAL_FRP_ARCHIVE_VERIFIED")
        self.assertEqual(first["INSTALL_ALLOWED"], "NO")
        self.assertEqual(first["ACTIVATION_GATE"], "HOLD")
        self.assertEqual(first["ROLLBACK_EXECUTOR"], "NOT_ENABLED")
        self.assertEqual(first["CLOUD_SNAPSHOT_RESTORE"], "UNVERIFIED")
        self.assertEqual(first["SIGNED_NODE_RESTART_AND_REPLAY"], "UNVERIFIED")
        self.assertEqual(first["SOURCE_COMPOSE_SHA256"],
                         hashlib.sha256(COMPOSE.encode()).hexdigest())
        self.assertEqual(len(first["BINARIES_SHA256"]), 2)
        self.assertEqual(len(first["PLAN_SHA256_NOT_AUTHORIZATION"]), 64)
        self.assertEqual(first["PLAN_SHA256_NOT_AUTHORIZATION"], self.preview()["PLAN_SHA256_NOT_AUTHORIZATION"])
        self.assertEqual(first["CHECKPOINTS"][3], "PERSIST_PRIVATE_CRASH_RECOVERY_JOURNAL_FIRST")
        self.assertNotIn("SECRET", str(first))
        self.assertNotIn(str(self.home), str(first))

    def test_tampered_compose_or_manifest_requires_no_host_mutation(self):
        (self.node / "docker-compose.yml").write_text(COMPOSE + "# external change\n")
        self.assertEqual(self.preview()["REASON"], "SOURCE_COMPOSE_OR_ARCHIVE_DRIFT")
        self.assertEqual(self.preview()["INSTALL_ALLOWED"], "NO")
        (self.node / "docker-compose.yml").write_text(COMPOSE)
        p = self.stage / "engines.candidate.json"
        data = json.loads(p.read_text())
        data["engines"]["backhaul"] = {"sha256": "b" * 64}
        p.write_text(json.dumps(data))
        self.assertNotEqual(self.preview()["STAGE_ADMISSION"], "VERIFIED_PREVIEW_ONLY")

    def test_legacy_and_incomplete_host_are_always_hold(self):
        self.status["TARGET_ENGINE"] = "ENROLLED_UNVERIFIED"
        self.assertEqual(self.preview()["REASON"], "HOST_ADMISSION_INCOMPLETE")
        self.status["TARGET_ENGINE"] = "NOT_INSTALLED"
        self.status["OTHER_ENGINE"] = "ENROLLED_UNVERIFIED"
        self.assertEqual(self.preview()["REASON"], "HOST_ADMISSION_INCOMPLETE")
        self.status["OTHER_ENGINE"] = "NOT_INSTALLED"
        self.status["SAVED_TUNNELS"] = "EXISTING_DO_NOT_RESTART"
        self.assertEqual(self.preview()["REASON"], "HOST_ADMISSION_INCOMPLETE")
        self.status["SAVED_TUNNELS"] = "ZERO"
        self.status["CORE_PROFILE"] = "LEGACY"
        self.assertEqual(self.preview()["REASON"], "HOST_ADMISSION_INCOMPLETE")

    def test_symlink_wrong_root_and_exposed_stage_permissions_fail_closed(self):
        elsewhere = self.home / "other"
        elsewhere.mkdir(mode=0o700)
        self.assertEqual(plan.review("frp", self.node, self.stage,
                                     staging_root=elsewhere,
                                     host_status=self.status)["REASON"],
                         "STAGE_OUTSIDE_PRIVATE_STAGING_ROOT")
        self.stage.chmod(0o755)
        self.assertEqual(self.preview()["REASON"], "STAGING_OWNER_OR_PERMISSIONS_UNTRUSTED")
        self.stage.chmod(0o700)
        link = self.root / "linked"
        link.symlink_to(self.stage, target_is_directory=True)
        self.assertEqual(plan.review("frp", self.node, link,
                                     staging_root=self.root,
                                     host_status=self.status)["REASON"],
                         "STAGE_OUTSIDE_PRIVATE_STAGING_ROOT")

    def test_backhaul_official_archive_binding_and_legacy_hold(self):
        archive = self.home / "official-backhaul-test.tar.gz"
        blob = synthetic_frp_exe("backhaul")
        with tarfile.open(archive, "w:gz") as tf:
            entry = tarfile.TarInfo("release/backhaul")
            entry.size = len(blob)
            tf.addfile(entry, io.BytesIO(blob))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        backhaul_status = dict(self.status, ENGINE="BACKHAUL")
        with patch.dict(plan.backhaul.OFFICIAL_TAR_SHA256, {"amd64": digest}):
            stage = plan.backhaul.prepare(
                self.node, archive, self.root, arch="amd64", allowed_sha=digest)
            verified = plan.review("backhaul", self.node, stage,
                                   staging_root=self.root,
                                   host_status=backhaul_status)
            self.assertEqual(verified["STAGE_ADMISSION"], "VERIFIED_PREVIEW_ONLY")
            self.assertEqual(verified["ARTIFACT_PROVENANCE"],
                             "OFFICIAL_BACKHAUL_ARCHIVE_VERIFIED")
            self.assertEqual(verified["INSTALL_ALLOWED"], "NO")
            # A candidate from the old packager lacking archive bytes must
            # never pass the official package and host plan checks.
            (stage / "backhaul.official.tar.gz").unlink()
            self.assertEqual(plan.review("backhaul", self.node, stage,
                                         staging_root=self.root,
                                         host_status=backhaul_status)["REASON"],
                             "BACKHAUL_OFFICIAL_ARCHIVE_NOT_VERIFIED")

    def test_plan_binds_exact_stage_overlay_and_manifest_into_recovery_lab(self):
        reviewed = self.preview()
        self.assertEqual(reviewed["STAGE_ADMISSION"], "VERIFIED_PREVIEW_ONLY")
        self.assertEqual(reviewed["CANDIDATE_COMPOSE_OVERLAY_SHA256"],
                         hashlib.sha256(
                             (self.stage / "compose.override.candidate.yml").read_bytes()
                         ).hexdigest())
        sandbox = Path(tempfile.mkdtemp(prefix="uopti-engine-txn-lab-"))
        sandbox.chmod(0o700)
        self.addCleanup(shutil.rmtree, sandbox)
        (sandbox / ".LAB_ONLY").write_bytes(lab.MARKER)
        shutil.copytree(self.node, sandbox / "node")
        isolated = sandbox / "node"
        (isolated / "config/tunnels.json").write_bytes(b"[]\n")
        (isolated / "config/node-id").write_bytes(b"UNCHANGED-IDENTITY")
        (isolated / "config/replay.db").write_bytes(b"UNCHANGED-REPLAY")
        binaries = {"frpc": (self.stage / "frpc.bin").read_bytes(),
                    "frps": (self.stage / "frps.bin").read_bytes()}
        overlay = (self.stage / "compose.override.candidate.yml").read_bytes()
        candidate_manifest = (self.stage / "engines.candidate.json").read_bytes()
        trusted = dict(reviewed, OTHER_ENGINE="NOT_INSTALLED")
        fake_signed = lambda *_: {"signed": True, "replay": True}
        with self.assertRaises(lab.SimulatedCrash):
            lab.execute(sandbox, "frp", binaries, overlay, trusted, fake_signed,
                        crash_at="after_frpc", candidate_manifest=candidate_manifest)
        self.assertEqual(lab.recover(sandbox, fake_signed), "ROLLED_BACK")
        self.assertFalse((isolated / "config/engine-state/engines.json").exists())
        self.assertEqual((isolated / "config/node-id").read_bytes(), b"UNCHANGED-IDENTITY")
        self.assertEqual((isolated / "config/replay.db").read_bytes(), b"UNCHANGED-REPLAY")
        result = lab.execute(sandbox, "frp", binaries, overlay, trusted,
                             fake_signed, candidate_manifest=candidate_manifest)
        self.assertEqual(result["INSTALL_ALLOWED"], "NO")
        self.assertEqual(result["ACTIVATION_GATE"], "HOLD")
        self.assertEqual((isolated / "config/engine-state/engines.json").read_bytes(),
                         candidate_manifest)

    def test_plan_bound_lab_rejects_modified_stage_after_review(self):
        reviewed = self.preview()
        sandbox = Path(tempfile.mkdtemp(prefix="uopti-engine-txn-lab-"))
        sandbox.chmod(0o700)
        self.addCleanup(shutil.rmtree, sandbox)
        (sandbox / ".LAB_ONLY").write_bytes(lab.MARKER)
        shutil.copytree(self.node, sandbox / "node")
        (sandbox / "node/config/tunnels.json").write_bytes(b"[]\n")
        binaries = {"frpc": (self.stage / "frpc.bin").read_bytes(),
                    "frps": (self.stage / "frps.bin").read_bytes()}
        overlay = (self.stage / "compose.override.candidate.yml").read_bytes()
        manifest = (self.stage / "engines.candidate.json").read_bytes()
        fake_signed = lambda *_: {"signed": True, "replay": True}
        # No mutable file, no journal and no Node restart if preview and stage drift.
        with self.assertRaisesRegex(lab.Hold, "CANDIDATE_COMPOSE_OVERLAY_DRIFT"):
            lab.execute(sandbox, "frp", binaries, overlay + b"# drift\n",
                        dict(reviewed, OTHER_ENGINE="NOT_INSTALLED"),
                        fake_signed, candidate_manifest=manifest)
        with self.assertRaisesRegex(lab.Hold, "CANDIDATE_MANIFEST_DRIFT"):
            lab.execute(sandbox, "frp", binaries, overlay,
                        dict(reviewed, OTHER_ENGINE="NOT_INSTALLED"),
                        fake_signed, candidate_manifest=manifest + b" ")
        self.assertFalse((sandbox / ".engine-journal.json").exists())

    def test_backhaul_archive_bound_plan_reaches_only_disposable_executor(self):
        archive = self.home / "backhaul-stage-lab.tar.gz"
        payload = synthetic_frp_exe("backhaul")
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo("release/backhaul")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with patch.dict(plan.backhaul.OFFICIAL_TAR_SHA256, {"amd64": digest}):
            stage = plan.backhaul.prepare(self.node, archive, self.root,
                                          arch="amd64", allowed_sha=digest)
            reviewed = plan.review("backhaul", self.node, stage,
                staging_root=self.root, host_status=dict(self.status, ENGINE="BACKHAUL"))
            self.assertEqual(reviewed["STAGE_ADMISSION"], "VERIFIED_PREVIEW_ONLY")
            sandbox = Path(tempfile.mkdtemp(prefix="uopti-engine-txn-lab-"))
            sandbox.chmod(0o700)
            self.addCleanup(shutil.rmtree, sandbox)
            (sandbox / ".LAB_ONLY").write_bytes(lab.MARKER)
            shutil.copytree(self.node, sandbox / "node")
            node = sandbox / "node"
            (node / "config/tunnels.json").write_bytes(b"[]\n")
            (node / "config/node-id").write_bytes(b"identity-must-stay")
            (node / "config/replay.db").write_bytes(b"replay-must-stay")
            state = lab.execute(
                sandbox, "backhaul", {"backhaul": (stage / "backhaul.bin").read_bytes()},
                (stage / "compose.override.candidate.yml").read_bytes(),
                dict(reviewed, OTHER_ENGINE="NOT_INSTALLED"),
                lambda *_: {"signed": True, "replay": True},
                candidate_manifest=(stage / "engines.candidate.json").read_bytes())
            self.assertEqual(state["INSTALL_ALLOWED"], "NO")
            self.assertEqual(state["ACTIVATION_GATE"], "HOLD")
            self.assertEqual((node / "config/node-id").read_bytes(), b"identity-must-stay")
            self.assertEqual((node / "config/replay.db").read_bytes(), b"replay-must-stay")

    def test_backhaul_override_tampering_with_recomputed_local_checksums_fails(self):
        archive = self.home / "verified-bh-overlay-test.tar.gz"
        binary = synthetic_frp_exe("backhaul")
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo("release/backhaul")
            info.size = len(binary)
            tf.addfile(info, io.BytesIO(binary))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with patch.dict(plan.backhaul.OFFICIAL_TAR_SHA256, {"amd64": digest}):
            stage = plan.backhaul.prepare(self.node, archive, self.root,
                                          arch="amd64", allowed_sha=digest)
            evidence = plan.review("backhaul", self.node, stage,
                staging_root=self.root, host_status=dict(self.status, ENGINE="BACKHAUL"))
            self.assertEqual(evidence["STAGE_ADMISSION"], "VERIFIED_PREVIEW_ONLY")
            overlay = stage / "compose.override.candidate.yml"
            overlay.write_bytes(overlay.read_bytes().replace(
                b"read_only: true", b"read_only: false"))
            # Attacker also rewrites SHA256SUMS; official archive stays genuine.
            sums = (stage / "SHA256SUMS").read_text().splitlines()
            (stage / "SHA256SUMS").write_text("\n".join(
                (f"{hashlib.sha256(overlay.read_bytes()).hexdigest()}  compose.override.candidate.yml"
                 if line.endswith("  compose.override.candidate.yml") else line)
                for line in sums) + "\n")
            self.assertFalse(plan.backhaul.verify(stage, official_only=True))
            rejected = plan.review("backhaul", self.node, stage,
                staging_root=self.root, host_status=dict(self.status, ENGINE="BACKHAUL"))
            self.assertEqual(rejected["REASON"], "BACKHAUL_OFFICIAL_ARCHIVE_NOT_VERIFIED")

    def test_no_live_executor_even_when_action_is_install(self):
        out = subprocess.run([
            sys.executable, "-B", str(SCRIPT), "install", "--engine", "frp",
            "--node-dir", str(self.node), "--stage", str(self.stage),
        ], capture_output=True, text=True, timeout=12)
        self.assertEqual(out.returncode, 2)
        self.assertIn("HOST_INSTALL_AND_ROLLBACK_DISABLED", out.stderr)
        self.assertFalse((self.node / "config/engine-state").exists())
        source = SCRIPT.read_text()
        for forbidden in ("docker compose up", "systemctl ", "subprocess.run(",
                          "os.system(", "iptables ", "nginx -s", "socket.",
                          "requests.", "urlopen(", "ssh "):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
