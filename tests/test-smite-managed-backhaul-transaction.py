#!/usr/bin/env python3
"""Disposable Backhaul-only transaction and recovery: zero live services."""
from __future__ import annotations
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "modules"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pkg = load("bh_package_fixture", ROOT / "smite-managed-backhaul.py")
lab = load("bh_tx_fixture", ROOT / "smite-managed-backhaul-transaction.py")

COMPOSE = """services:
  smite-node:
    image: smite-node:stage15-local
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
"""
ENV = """NODE_ROLE=iran
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
"""


class TransactionLab(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bh-transaction-lab-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        (self.root / "EXPERIMENTAL-LAB").write_text(lab.MARKER)
        self.node = self.root / "node"
        self.node.mkdir(mode=0o700)
        self.config = self.node / "config"
        self.config.mkdir(mode=0o700)
        (self.node / ".env").write_text(ENV)
        self.compose = self.node / "docker-compose.yml"
        self.compose.write_text(COMPOSE)
        self.stages = self.root / "stages"
        self.stages.mkdir(mode=0o700)
        archive = self.root / "official-fixture.tar.gz"
        with tarfile.open(archive, "w:gz") as f:
            binary = b"\x7fELF" + b"BACKHAUL-CI-INERT-FIXTURE"
            m = tarfile.TarInfo("backhaul")
            m.size = len(binary)
            f.addfile(m, io.BytesIO(binary))
        self.digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.archive = archive
        self.patch_env = patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": "aghajani82/u-opti",
            "RUNNER_TEMP": str(self.root.parent),
        })
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)

    def prepare(self):
        return pkg.prepare(self.node, self.archive, self.stages,
                           arch="amd64", allowed_sha=self.digest)

    def test_rc7_pair_private_read_rejects_rename_symlink_and_inplace_races(self):
        # Both FRP receipt and retained rollback bytes use this private reader.
        path = self.root / "record.json"
        good = b'{"schema":1,"role":"ir"}'
        bad = b'{"schema":1,"role":"kh"}'
        path.write_bytes(good)
        path.chmod(0o600)
        secret = self.root / "unrelated.json"
        secret.write_bytes(b"SECRET_MUST_NOT_LEAK")
        secret.chmod(0o600)
        self.assertEqual(lab._pair_read_private(path), good)

        original_open = os.open
        def swap_to_symlink(name, flags, *args, **kwargs):
            if Path(name) == path:
                path.unlink()
                path.symlink_to(secret)
            return original_open(name, flags, *args, **kwargs)
        with patch.object(lab.os, "open", side_effect=swap_to_symlink):
            with self.assertRaises(lab.Hold):
                lab._pair_read_private(path)
        self.assertTrue(path.is_symlink())
        self.assertEqual(secret.read_bytes(), b"SECRET_MUST_NOT_LEAK")
        path.unlink()
        path.write_bytes(good)
        path.chmod(0o600)

        relocated = self.root / "original.json"
        def swap_after_open(name, flags, *args, **kwargs):
            fd = original_open(name, flags, *args, **kwargs)
            if Path(name) == path:
                path.rename(relocated)
                path.write_bytes(bad)
                path.chmod(0o600)
            return fd
        with patch.object(lab.os, "open", side_effect=swap_after_open):
            with self.assertRaises(lab.Hold):
                lab._pair_read_private(path)
        self.assertEqual(relocated.read_bytes(), good)
        self.assertEqual(path.read_bytes(), bad)
        relocated.unlink()
        path.write_bytes(good)

        original_read = os.read
        def changed_during_read(fd, length):
            value = original_read(fd, length)
            if value:
                path.write_bytes(bad)
                os.utime(path, ns=(1_700_000_000_000_000_000,
                                   1_700_000_000_000_000_000))
            return value
        with patch.object(lab.os, "read", side_effect=changed_during_read):
            with self.assertRaises(lab.Hold):
                lab._pair_read_private(path)
        self.assertEqual(path.read_bytes(), bad)
        path.write_bytes(good)
        path.chmod(0o644)
        with self.assertRaises(lab.Hold):
            lab._pair_read_private(path)
        path.unlink()
        with self.assertRaises(lab.Hold):
            lab._pair_read_private(path)
        path.write_bytes(good)
        path.chmod(0o600)
        self.assertEqual(lab._pair_read_private(path), good)

    def test_install_and_exact_rollback_do_not_change_other_engines(self):
        state = self.config / "engine-state"
        state.mkdir(mode=0o700)
        original = {"schema": 1, "engines": {"gost": {"sha256": "d" * 64}}}
        manifest = state / "engines.json"
        manifest.write_text(json.dumps(original))
        manifest.chmod(0o600)
        source_bytes = manifest.read_bytes()
        stage = self.prepare()
        self.assertEqual(lab.activate(self.root, stage, fixture=True),
                         "LAB_FILES_APPLIED_NO_DOCKER_NO_LIVE_ENGINE")
        self.assertIn(str(self.root / "installed/backhaul"), self.compose.read_text())
        self.assertIn(":/usr/local/bin/backhaul:ro", self.compose.read_text())
        actual = json.loads(manifest.read_text())["engines"]
        self.assertEqual(actual["gost"], original["engines"]["gost"])
        self.assertIn("backhaul", actual)
        self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.root / "installed/backhaul").stat().st_mode), 0o755)
        with self.assertRaises(lab.Hold):
            lab.activate(self.root, stage, fixture=True)
        self.assertEqual(lab.rollback(self.root), "LAB_EXACT_ROLLBACK_CONFIRMED")
        self.assertEqual(self.compose.read_text(), COMPOSE)
        self.assertEqual(manifest.read_bytes(), source_bytes)
        self.assertFalse((self.root / "installed/backhaul").exists())
        self.assertFalse((self.root / "recovery-journal").exists())
        self.assertEqual(set(json.loads(manifest.read_text())["engines"]), {"gost"})

    def test_independent_backhaul_preserves_healthy_existing_frp_dual_binaries(self):
        # A valid installed FRP must not be changed, removed, or reported as
        # absent when the operator chooses Backhaul as their second engine.
        state = self.config / "engine-state"
        state.mkdir(mode=0o700)
        manifest = state / "engines.json"
        frp_dir = self.root / "installed" / "frp"
        frp_dir.mkdir(parents=True, mode=0o700)
        # Shared engine parent has the 0700 permissions required by the
        # real PR-only transaction, independent of runner default umask.
        frp_dir.parent.chmod(0o700)
        frp_hashes = {}
        initial_binary = {}
        for name in ("frpc", "frps"):
            payload = b"\x7fELF" + ("FRP_EXISTING_" + name).encode()
            target = frp_dir / name
            target.write_bytes(payload)
            target.chmod(0o755)
            initial_binary[name] = payload
            frp_hashes[name] = hashlib.sha256(payload).hexdigest()
        self.compose.write_text(COMPOSE + "".join(
            f"      - {frp_dir / name}:/usr/local/bin/{name}:ro\n"
            for name in ("frpc", "frps")
        ))
        before_compose = self.compose.read_bytes()
        record = {"schema": 1, "engines": {
            "frp": {"sha256": frp_hashes["frpc"],
                    "server_sha256": frp_hashes["frps"]}
        }}
        manifest.write_text(json.dumps(record))
        manifest.chmod(0o600)
        before_manifest = manifest.read_bytes()
        stage = self.prepare()
        summary = (stage / "summary.txt").read_text()
        self.assertIn("FRP_INSTALLED=YES", summary)
        self.assertIn("CANDIDATE_ONLY=YES", summary)
        self.assertEqual(lab.activate(self.root, stage, fixture=True),
                         "LAB_FILES_APPLIED_NO_DOCKER_NO_LIVE_ENGINE")
        deployed = json.loads(manifest.read_text())["engines"]
        self.assertEqual(deployed["frp"], record["engines"]["frp"])
        self.assertIn("backhaul", deployed)
        for name in ("frpc", "frps"):
            self.assertIn(f"      - {frp_dir / name}:/usr/local/bin/{name}:ro\n",
                          self.compose.read_text())
        for name in ("frpc", "frps"):
            self.assertEqual((frp_dir / name).read_bytes(), initial_binary[name])
        self.assertEqual(lab.rollback(self.root), "LAB_EXACT_ROLLBACK_CONFIRMED")
        self.assertEqual(self.compose.read_bytes(), before_compose)
        self.assertEqual(manifest.read_bytes(), before_manifest)
        for name in ("frpc", "frps"):
            self.assertEqual((frp_dir / name).read_bytes(), initial_binary[name])
        self.assertFalse((self.root / "installed/backhaul").exists())
        self.assertFalse((self.root / "recovery-journal").exists())

    def test_refuse_partial_or_tampered_frp_before_any_backhaul_write(self):
        # Registry/Compose/binary mismatch is a bad shared baseline;
        # never mutate shared files or destroy FRP to install Backhaul.
        state = self.config / "engine-state"
        state.mkdir(mode=0o700)
        manifest = state / "engines.json"
        frp_dir = self.root / "installed/frp"
        frp_dir.mkdir(parents=True, mode=0o700)
        # Shared engine parent has the 0700 permissions required by the
        # real PR-only transaction, independent of runner default umask.
        frp_dir.parent.chmod(0o700)
        data = {}
        for name in ("frpc", "frps"):
            value = b"\x7fELF" + name.encode()
            target = frp_dir / name
            target.write_bytes(value)
            target.chmod(0o755)
            data[name] = hashlib.sha256(value).hexdigest()
        baseline = COMPOSE + "".join(
            f"      - {frp_dir / name}:/usr/local/bin/{name}:ro\n"
            for name in ("frpc", "frps")
        )
        self.compose.write_text(baseline)
        manifest.write_text(json.dumps({"schema": 1, "engines": {
            "frp": {"sha256": data["frpc"], "server_sha256": data["frps"]}
        }}))
        manifest.chmod(0o600)
        broken = [
            baseline.replace(":/usr/local/bin/frpc:ro", ":/usr/local/bin/frpc:rw"),
            baseline.replace(f"      - {frp_dir / 'frps'}:/usr/local/bin/frps:ro\n", ""),
        ]
        for text in broken:
            with self.subTest(compose=text[-55:]):
                self.compose.write_text(text)
                with self.assertRaises(pkg.Hold):
                    self.prepare()
                self.assertFalse((self.root / "recovery-journal").exists())
                self.assertFalse((self.root / "installed/backhaul").exists())
        self.compose.write_text(baseline)
        (frp_dir / "frps").write_bytes(b"\x7fELF" + b"tampered")
        with self.assertRaisesRegex(pkg.Hold, "digest mismatch"):
            self.prepare()
        self.assertFalse((self.root / "installed/backhaul").exists())
        self.assertFalse((self.root / "recovery-journal").exists())
        # No registered FRP but stale FRP mount is also a hard stop.
        manifest.unlink()
        with self.assertRaisesRegex(pkg.Hold, "Unenrolled FRP"):
            self.prepare()

    def test_fresh_registry_creation_and_removal(self):
        stage = self.prepare()
        self.compose.chmod(0o644)
        lab.activate(self.root, stage, fixture=True)
        self.assertEqual(
            set(json.loads((self.config / "engine-state/engines.json").read_text())["engines"]),
            {"backhaul"},
        )
        lab.rollback(self.root)
        self.assertFalse((self.config / "engine-state/engines.json").exists())
        self.assertEqual(self.compose.read_text(), COMPOSE)
        self.assertEqual(stat.S_IMODE(self.compose.stat().st_mode), 0o644)

    def test_recovery_from_each_partial_install_stage(self):
        for step in ("after-binary", "after-compose", "after-manifest"):
            with self.subTest(step=step):
                stage = self.prepare()
                with self.assertRaises(lab.Hold):
                    lab.activate(self.root, stage, fixture=True, inject=step)
                self.assertTrue((self.root / "recovery-journal").exists())
                self.assertEqual(lab.rollback(self.root), "LAB_EXACT_ROLLBACK_CONFIRMED")
                self.assertEqual(self.compose.read_text(), COMPOSE)
                self.assertFalse((self.root / "installed/backhaul").exists())

    def test_refuse_out_of_band_compose_and_registry_changes(self):
        stage = self.prepare()
        lab.activate(self.root, stage, fixture=True)
        self.compose.write_text(self.compose.read_text() + "# operator edit\n")
        with self.assertRaisesRegex(lab.Hold, "Compose modified"):
            lab.rollback(self.root)
        self.assertTrue((self.root / "recovery-journal").exists())
        self.compose.write_text(COMPOSE + "      - " +
                                str(self.root / "installed/backhaul") +
                                ":/usr/local/bin/backhaul:ro\n")
        manifest = self.config / "engine-state/engines.json"
        manifest.write_text('{"schema":1,"engines":{"backhaul":{"sha256":"f"}}}')
        with self.assertRaisesRegex(lab.Hold, "Registry modified"):
            lab.rollback(self.root)

    def test_refuse_unknown_stage_and_untrusted_node(self):
        stage = self.prepare()
        (self.node / ".env").write_text(ENV.replace("strict", "legacy"))
        with self.assertRaises(lab.Hold):
            lab.activate(self.root, stage, fixture=True)
        self.assertFalse((self.root / "recovery-journal").exists())
        (self.node / ".env").write_text(ENV)
        (self.root / "EXPERIMENTAL-LAB").write_text("not verified\n")
        with self.assertRaises(lab.Hold):
            lab.activate(self.root, stage, fixture=True)

    def test_refuse_non_ci_and_synthetic_fixture_via_public_api(self):
        stage = self.prepare()
        with self.assertRaises(lab.Hold):
            lab.activate(self.root, stage)  # Real launcher never accepts synthetic SHA.
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            with self.assertRaisesRegex(lab.Hold, "CI ONLY"):
                lab.activate(self.root, stage, fixture=True)
        self.assertFalse((self.root / "recovery-journal").exists())


    def _rc7_pair_lab_fixture(self):
        """Synthetic, private RC7 bytes: never a real host or signed attestation."""
        state = self.config / "engine-state"
        state.mkdir(mode=0o700, exist_ok=True)
        manifest = state / "engines.json"
        pins = {"frpc": "b" * 64, "frps": "c" * 64}
        before = (json.dumps({
            "schema": 1, "engines": {
                "frp": {"sha256": pins["frpc"],
                        "server_sha256": pins["frps"]},
                "gost": {"sha256": "d" * 64},
            },
        }, sort_keys=True, indent=2) + "\n").encode()
        manifest.write_bytes(before)
        manifest.chmod(0o600)
        frpdir = self.root / lab.PAIR_RECEIPT_DIR
        frpdir.mkdir(mode=0o700)
        receipt = frpdir / "record.json"
        frp = (json.dumps({
            "schema": 1, "role": "ir", "state": "COMMITTED",
            "old": None, "new": hashlib.sha256(before).hexdigest(),
            "binaries": pins,
        }, sort_keys=True) + "\n").encode()
        receipt.write_bytes(frp)
        receipt.chmod(0o600)
        return manifest, receipt, before, frp

    def test_rc7_pair_rehearsal_preserves_frp_pins_and_rollback_exact_bytes(self):
        manifest, receipt, old_manifest, old_receipt = self._rc7_pair_lab_fixture()
        before_compose = self.compose.read_bytes()
        result = lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir")
        self.assertEqual(result, "LAB_PAIR_BYTES_APPLIED_UNATTESTED_RECOVERY_REQUIRED")
        self.assertNotEqual(manifest.read_bytes(), old_manifest)
        self.assertNotEqual(receipt.read_bytes(), old_receipt)
        candidate = json.loads(manifest.read_bytes())
        updated = json.loads(receipt.read_bytes())
        self.assertEqual(candidate["engines"]["frp"],
                         json.loads(old_manifest)["engines"]["frp"])
        self.assertEqual(candidate["engines"]["gost"],
                         json.loads(old_manifest)["engines"]["gost"])
        self.assertEqual(candidate["engines"]["backhaul"]["sha256"], "a" * 64)
        self.assertEqual(updated["binaries"], json.loads(old_receipt)["binaries"])
        self.assertEqual(updated["new"], hashlib.sha256(manifest.read_bytes()).hexdigest())
        self.assertTrue((self.root / lab.PAIR_JOURNAL).is_dir())
        self.assertEqual(before_compose, self.compose.read_bytes())
        self.assertFalse((self.root / "installed").exists())
        self.assertEqual(lab.rc7_pair_recover_lab(self.root),
                         "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
        self.assertEqual(manifest.read_bytes(), old_manifest)
        self.assertEqual(receipt.read_bytes(), old_receipt)
        self.assertFalse((self.root / lab.PAIR_JOURNAL).exists())
        self.assertEqual(before_compose, self.compose.read_bytes())

    def test_rc7_pair_recovery_all_crash_boundaries_and_idempotent_resume(self):
        manifest, receipt, old_manifest, old_receipt = self._rc7_pair_lab_fixture()
        for cut in ("after-journal", "after-manifest", "after-receipt"):
            with self.subTest(cut=cut):
                with self.assertRaisesRegex(lab.Hold, "RECOVER_REQUIRED"):
                    lab.rc7_pair_apply_lab(self.root, "a" * 64,
                                           role="ir", inject=cut)
                with self.assertRaisesRegex(lab.Hold, "REQUIRES_RECOVERY"):
                    lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir")
                self.assertEqual(lab.rc7_pair_recover_lab(self.root),
                                 "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
                self.assertEqual(manifest.read_bytes(), old_manifest)
                self.assertEqual(receipt.read_bytes(), old_receipt)
                self.assertFalse((self.root / lab.PAIR_JOURNAL).exists())

    def test_rc7_pair_rollback_crash_at_each_restore_boundary_then_resume(self):
        # Simulate a power cut *inside recovery*, not merely during Apply.
        # Every restart revalidates the same durable four-part journal.
        for role in ("ir", "foreign"):
            for crash in ("after-restore-manifest", "after-restore-receipt",
                          "before-journal-cleanup"):
                with self.subTest(role=role, crash=crash):
                    manifest, receipt, original, original_receipt = (
                        self._rc7_pair_lab_fixture())
                    if role == "foreign":
                        data = json.loads(original_receipt)
                        data["role"] = "foreign"
                        original_receipt = (
                            json.dumps(data, sort_keys=True) + "\n").encode()
                        receipt.write_bytes(original_receipt)
                    prior_compose = self.compose.read_bytes()
                    prior_env = (self.node / ".env").read_bytes()
                    self.assertEqual(
                        lab.rc7_pair_apply_lab(self.root, "a" * 64, role=role),
                        "LAB_PAIR_BYTES_APPLIED_UNATTESTED_RECOVERY_REQUIRED")
                    self.assertNotEqual(manifest.read_bytes(), original)
                    self.assertNotEqual(receipt.read_bytes(), original_receipt)
                    with self.assertRaisesRegex(
                            lab.Hold, "ROLLBACK_CRASH_RESUME_REQUIRED"):
                        lab.rc7_pair_recover_lab(self.root, inject=crash)
                    # Manifest is restored first; receipt may remain at
                    # the candidate until the second restoration boundary.
                    self.assertEqual(manifest.read_bytes(), original)
                    if crash == "after-restore-manifest":
                        self.assertNotEqual(receipt.read_bytes(), original_receipt)
                    else:
                        self.assertEqual(receipt.read_bytes(), original_receipt)
                    journal = self.root / lab.PAIR_JOURNAL
                    self.assertEqual(set(p.name for p in journal.iterdir()), {
                        "record.json", "manifest.before", "frp.before",
                        "manifest.next", "frp.next"})
                    self.assertEqual(
                        lab.rc7_pair_recover_lab(self.root),
                        "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
                    self.assertEqual(manifest.read_bytes(), original)
                    self.assertEqual(receipt.read_bytes(), original_receipt)
                    self.assertEqual(self.compose.read_bytes(), prior_compose)
                    self.assertEqual((self.node / ".env").read_bytes(), prior_env)
                    self.assertFalse(journal.exists())
                    self.assertFalse((self.root / "installed").exists())
                    # New independent rehearsal permitted only after full
                    # proof and journal cleanup; no stale recovery remains.
                    manifest.parent.joinpath("engines.json").unlink()
                    receipt.unlink()
                    receipt.parent.rmdir()
                    manifest.parent.rmdir()

    def test_rc7_pair_recovery_repeat_crash_and_external_drift_hold(self):
        manifest, receipt, old_manifest, old_receipt = self._rc7_pair_lab_fixture()
        with self.assertRaisesRegex(lab.Hold, "RECOVER_REQUIRED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir",
                                   inject="after-receipt")
        for crash in ("after-restore-manifest", "after-restore-manifest",
                      "after-restore-receipt", "before-journal-cleanup"):
            with self.subTest(crash=crash):
                with self.assertRaisesRegex(
                        lab.Hold, "ROLLBACK_CRASH_RESUME_REQUIRED"):
                    lab.rc7_pair_recover_lab(self.root, inject=crash)
                self.assertEqual(manifest.read_bytes(), old_manifest)
                self.assertTrue((self.root / lab.PAIR_JOURNAL).exists())
        receipt.write_bytes(old_receipt + b"OUT_OF_BAND")
        altered = receipt.read_bytes()
        with self.assertRaisesRegex(lab.Hold, "RECOVERY_EXTERNAL_DRIFT"):
            lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(receipt.read_bytes(), altered)
        self.assertTrue((self.root / lab.PAIR_JOURNAL).exists())
        receipt.write_bytes(old_receipt)
        self.assertEqual(lab.rc7_pair_recover_lab(self.root),
                         "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
        self.assertEqual(manifest.read_bytes(), old_manifest)
        self.assertEqual(receipt.read_bytes(), old_receipt)

    def test_rc7_pair_cleanup_crashes_are_resumable_for_both_roles(self):
        # Crash at every *destructive* cleanup boundary, including after
        # rmdir; neither CI lab flow may bypass a pending terminal seal.
        for role in ("ir", "foreign"):
            for cut in ("after-completion-seal",
                        *(f"after-cleanup-{n}" for n in range(1, 6)),
                        "after-cleanup-rmdir"):
                with self.subTest(role=role, cut=cut):
                    manifest, receipt, original, old_receipt = (
                        self._rc7_pair_lab_fixture())
                    if role == "foreign":
                        doc = json.loads(old_receipt)
                        doc["role"] = "foreign"
                        old_receipt = (
                            json.dumps(doc, sort_keys=True) + "\n").encode()
                        receipt.write_bytes(old_receipt)
                    compose_before = self.compose.read_bytes()
                    env_before = (self.node / ".env").read_bytes()
                    self.assertEqual(
                        lab.rc7_pair_apply_lab(self.root, "a" * 64, role=role),
                        "LAB_PAIR_BYTES_APPLIED_UNATTESTED_RECOVERY_REQUIRED")
                    with self.assertRaisesRegex(
                            lab.Hold, "CLEANUP_CRASH_RESUME_REQUIRED"):
                        lab.rc7_pair_recover_lab(self.root, inject=cut)
                    seal = self.root / lab.PAIR_CLEANUP_SEAL
                    self.assertTrue(seal.is_file())
                    self.assertEqual(seal.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(manifest.read_bytes(), original)
                    self.assertEqual(receipt.read_bytes(), old_receipt)
                    with self.assertRaisesRegex(
                            lab.Hold, "REQUIRES_RECOVERY"):
                        lab.rc7_pair_apply_lab(self.root, "a" * 64, role=role)
                    with self.assertRaisesRegex(
                            lab.Hold, "OTHER_ENGINE_RECOVERY_JOURNAL_PENDING"):
                        lab.rollback(self.root)
                    journal = self.root / lab.PAIR_JOURNAL
                    if cut == "after-cleanup-rmdir":
                        self.assertFalse(journal.exists())
                    else:
                        self.assertTrue(journal.is_dir())
                    self.assertEqual(
                        lab.rc7_pair_recover_lab(self.root),
                        "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
                    self.assertFalse(journal.exists())
                    self.assertFalse(seal.exists())
                    self.assertEqual(manifest.read_bytes(), original)
                    self.assertEqual(receipt.read_bytes(), old_receipt)
                    self.assertEqual(self.compose.read_bytes(), compose_before)
                    self.assertEqual((self.node / ".env").read_bytes(), env_before)
                    self.assertFalse((self.root / "installed").exists())
                    manifest.unlink()
                    manifest.parent.rmdir()
                    receipt.unlink()
                    receipt.parent.rmdir()

    def test_rc7_pair_cleanup_hold_on_changed_source_or_remaining_piece(self):
        manifest, receipt, original, old_receipt = self._rc7_pair_lab_fixture()
        self.assertEqual(
            lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir"),
            "LAB_PAIR_BYTES_APPLIED_UNATTESTED_RECOVERY_REQUIRED")
        with self.assertRaisesRegex(lab.Hold, "CLEANUP_CRASH_RESUME_REQUIRED"):
            lab.rc7_pair_recover_lab(self.root, inject="after-cleanup-1")
        journal = self.root / lab.PAIR_JOURNAL
        seal = self.root / lab.PAIR_CLEANUP_SEAL
        remain_before = set(p.name for p in journal.iterdir())
        receipt.write_bytes(old_receipt + b"OUT_OF_BAND")
        with self.assertRaisesRegex(lab.Hold, "CLEANUP_BASELINE_DRIFT"):
            lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(set(p.name for p in journal.iterdir()), remain_before)
        receipt.write_bytes(old_receipt)
        (journal / "frp.before").write_bytes(b"CORRUPTED")
        with self.assertRaisesRegex(lab.Hold, "CLEANUP_JOURNAL_DRIFT"):
            lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(set(p.name for p in journal.iterdir()), remain_before)
        (journal / "frp.before").write_bytes(old_receipt)
        (journal / "unexpected").write_bytes(b"UNREVIEWED")
        with self.assertRaisesRegex(lab.Hold, "CLEANUP_JOURNAL_UNTRUSTED"):
            lab.rc7_pair_recover_lab(self.root)
        (journal / "unexpected").unlink()
        self.assertEqual(lab.rc7_pair_recover_lab(self.root),
                         "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
        self.assertFalse(seal.exists())
        self.assertFalse(journal.exists())
        self.assertEqual(manifest.read_bytes(), original)
        self.assertEqual(receipt.read_bytes(), old_receipt)

    def test_rc7_pair_cleanup_seal_must_be_private_semantically_valid(self):
        for change in ("symlink", "world-readable", "wrong-role",
                       "wrong-candidate-sha"):
            with self.subTest(change=change):
                manifest, receipt, old_manifest, old_receipt = (
                    self._rc7_pair_lab_fixture())
                self.assertEqual(
                    lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir"),
                    "LAB_PAIR_BYTES_APPLIED_UNATTESTED_RECOVERY_REQUIRED")
                with self.assertRaisesRegex(
                        lab.Hold, "CLEANUP_CRASH_RESUME_REQUIRED"):
                    lab.rc7_pair_recover_lab(
                        self.root, inject="after-completion-seal")
                seal = self.root / lab.PAIR_CLEANUP_SEAL
                original_seal = seal.read_bytes()
                if change == "symlink":
                    seal.unlink()
                    seal.symlink_to(self.root / "EXPERIMENTAL-LAB")
                elif change == "world-readable":
                    seal.chmod(0o644)
                else:
                    data = json.loads(original_seal)
                    if change == "wrong-role":
                        data["role"] = "foreign"
                    else:
                        data["manifest_next"] = "f" * 64
                    seal.write_text(json.dumps(data, sort_keys=True) + "\n")
                with self.assertRaises(lab.Hold):
                    lab.rc7_pair_recover_lab(self.root)
                self.assertTrue((self.root / lab.PAIR_JOURNAL).is_dir())
                self.assertEqual(manifest.read_bytes(), old_manifest)
                self.assertEqual(receipt.read_bytes(), old_receipt)
                if seal.is_symlink():
                    seal.unlink()
                seal.write_bytes(original_seal)
                # A newly-created test file inherits umask and is not
                # implicitly 0600; restore the exact private mode as well.
                seal.chmod(0o600)
                self.assertEqual(lab.rc7_pair_recover_lab(self.root),
                                 "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
                self.assertFalse(seal.exists())
                manifest.unlink()
                manifest.parent.rmdir()
                receipt.unlink()
                receipt.parent.rmdir()

    def test_rc7_pair_recovery_detects_external_edits_before_any_restore(self):
        manifest, receipt, _, _ = self._rc7_pair_lab_fixture()
        with self.assertRaises(lab.Hold):
            lab.rc7_pair_apply_lab(self.root, "a" * 64,
                                   role="ir", inject="after-manifest")
        changed_manifest = manifest.read_bytes()
        receipt.write_bytes(receipt.read_bytes() + b"EXTERNAL_TAMPER")
        changed_receipt = receipt.read_bytes()
        with self.assertRaisesRegex(lab.Hold, "EXTERNAL_DRIFT"):
            lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(manifest.read_bytes(), changed_manifest)
        self.assertEqual(receipt.read_bytes(), changed_receipt)
        self.assertTrue((self.root / lab.PAIR_JOURNAL).exists())

    def test_rc7_pair_recovery_requires_all_exact_secure_backups(self):
        manifest, receipt, _, _ = self._rc7_pair_lab_fixture()
        with self.assertRaises(lab.Hold):
            lab.rc7_pair_apply_lab(self.root, "a" * 64,
                                   role="ir", inject="after-receipt")
        altered_manifest = manifest.read_bytes()
        altered_receipt = receipt.read_bytes()
        backup = self.root / lab.PAIR_JOURNAL / "frp.before"
        backup.write_bytes(backup.read_bytes() + b"altered")
        with self.assertRaisesRegex(lab.Hold, "BACKUP_DRIFT"):
            lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(manifest.read_bytes(), altered_manifest)
        self.assertEqual(receipt.read_bytes(), altered_receipt)
        self.assertTrue((self.root / lab.PAIR_JOURNAL).exists())

    def test_rc7_pair_missing_or_wrong_role_receipt_never_creates_journal(self):
        manifest, receipt, old_manifest, old_receipt = self._rc7_pair_lab_fixture()
        for role, sha in (("foreign", "a" * 64), ("ir", "INVALID_SHA"),
                          ("other", "a" * 64)):
            with self.subTest(role=role, sha=sha[:8]):
                with self.assertRaises(lab.Hold):
                    lab.rc7_pair_apply_lab(self.root, sha, role=role)
                self.assertEqual(manifest.read_bytes(), old_manifest)
                self.assertEqual(receipt.read_bytes(), old_receipt)
                self.assertFalse((self.root / lab.PAIR_JOURNAL).exists())
        receipt.write_bytes(b'{"schema":1,"schema":1}')
        with self.assertRaises(lab.Hold):
            lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir")
        self.assertFalse((self.root / lab.PAIR_JOURNAL).exists())

    def test_rc7_pair_untrusted_file_modes_and_non_ci_always_hold(self):
        manifest, receipt, before, receipt_before = self._rc7_pair_lab_fixture()
        receipt.chmod(0o644)
        with self.assertRaisesRegex(lab.Hold, "PRIVATE_FILE_UNTRUSTED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir")
        receipt.chmod(0o600)
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            with self.assertRaisesRegex(lab.Hold, "CI ONLY"):
                lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir")
        self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual(receipt.read_bytes(), receipt_before)
        self.assertFalse((self.root / lab.PAIR_JOURNAL).exists())

    def test_rc7_pair_uses_legacy_engine_shared_lock_for_apply_and_recovery(self):
        manifest, receipt, old_manifest, old_receipt = self._rc7_pair_lab_fixture()
        control = load("bh_control_pair_lock_test",
                       ROOT / "smite-managed-backhaul-control.py")
        with control._lab_lock(self.root):
            with self.assertRaisesRegex(lab.Hold, "ANOTHER_ENGINE_TRANSACTION_ACTIVE"):
                lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir")
        self.assertEqual(manifest.read_bytes(), old_manifest)
        self.assertEqual(receipt.read_bytes(), old_receipt)
        self.assertFalse((self.root / lab.PAIR_JOURNAL).exists())

        with self.assertRaisesRegex(lab.Hold, "RECOVER_REQUIRED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64,
                                   role="ir", inject="after-manifest")
        intermediate_manifest = manifest.read_bytes()
        intermediate_receipt = receipt.read_bytes()
        with control._lab_lock(self.root):
            with self.assertRaisesRegex(lab.Hold, "ANOTHER_ENGINE_TRANSACTION_ACTIVE"):
                lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(manifest.read_bytes(), intermediate_manifest)
        self.assertEqual(receipt.read_bytes(), intermediate_receipt)
        self.assertEqual(lab.rc7_pair_recover_lab(self.root),
                         "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
        self.assertEqual(manifest.read_bytes(), old_manifest)
        self.assertEqual(receipt.read_bytes(), old_receipt)

    def test_rc7_pair_shared_lock_fail_closed_on_symlink_and_bad_mode(self):
        manifest, receipt, old_manifest, old_receipt = self._rc7_pair_lab_fixture()
        lock = self.root / ".smite-engine-transaction.lock"
        lock.symlink_to(self.root / "EXPERIMENTAL-LAB")
        with self.assertRaisesRegex(lab.Hold, "SHARED_LOCK_UNTRUSTED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir")
        lock.unlink()
        lock.write_bytes(b"")
        lock.chmod(0o644)
        with self.assertRaisesRegex(lab.Hold, "SHARED_LOCK_UNTRUSTED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir")
        self.assertEqual(manifest.read_bytes(), old_manifest)
        self.assertEqual(receipt.read_bytes(), old_receipt)
        self.assertFalse((self.root / lab.PAIR_JOURNAL).exists())

    def _rewrite_pair_journal_piece_with_matching_checksum(self, name, raw):
        journal = self.root / lab.PAIR_JOURNAL
        (journal / name).write_bytes(raw)
        keys = {
            "manifest.before": "manifest_before",
            "frp.before": "frp_before",
            "manifest.next": "manifest_next",
            "frp.next": "frp_next",
        }
        record_file = journal / "record.json"
        record = json.loads(record_file.read_bytes())
        record[keys[name]] = hashlib.sha256(raw).hexdigest()
        record_file.write_text(json.dumps(record, sort_keys=True) + "\n")

    def test_rc7_pair_recovery_rejects_hash_consistent_wrong_prior_binding(self):
        manifest, receipt, _, _ = self._rc7_pair_lab_fixture()
        with self.assertRaisesRegex(lab.Hold, "RECOVER_REQUIRED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64,
                                   role="ir", inject="after-manifest")
        actual_manifest, actual_receipt = manifest.read_bytes(), receipt.read_bytes()
        journal = self.root / lab.PAIR_JOURNAL
        original = json.loads((journal / "manifest.before").read_bytes())
        original["engines"]["gost"]["sha256"] = "e" * 64
        altered = (json.dumps(original, sort_keys=True, indent=2) + "\n").encode()
        self._rewrite_pair_journal_piece_with_matching_checksum(
            "manifest.before", altered)
        with self.assertRaisesRegex(lab.Hold, "RECOVERY_SEMANTIC_DRIFT"):
            lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(manifest.read_bytes(), actual_manifest)
        self.assertEqual(receipt.read_bytes(), actual_receipt)
        self.assertTrue(journal.exists())

    def test_rc7_pair_recovery_rejects_hash_consistent_wrong_next_receipt(self):
        manifest, receipt, _, _ = self._rc7_pair_lab_fixture()
        with self.assertRaisesRegex(lab.Hold, "RECOVER_REQUIRED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64,
                                   role="ir", inject="after-receipt")
        actual_manifest, actual_receipt = manifest.read_bytes(), receipt.read_bytes()
        journal = self.root / lab.PAIR_JOURNAL
        changed = json.loads((journal / "frp.next").read_bytes())
        changed["new"] = "f" * 64
        self._rewrite_pair_journal_piece_with_matching_checksum(
            "frp.next", (json.dumps(changed, sort_keys=True) + "\n").encode())
        with self.assertRaisesRegex(lab.Hold, "RECOVERY_SEMANTIC_DRIFT"):
            lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(manifest.read_bytes(), actual_manifest)
        self.assertEqual(receipt.read_bytes(), actual_receipt)
        self.assertTrue(journal.exists())

    def test_rc7_pair_recovery_rejects_hash_consistent_wrong_next_manifest(self):
        manifest, receipt, _, _ = self._rc7_pair_lab_fixture()
        with self.assertRaisesRegex(lab.Hold, "RECOVER_REQUIRED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64,
                                   role="ir", inject="after-receipt")
        actual_manifest, actual_receipt = manifest.read_bytes(), receipt.read_bytes()
        journal = self.root / lab.PAIR_JOURNAL
        changed = json.loads((journal / "manifest.next").read_bytes())
        changed["engines"]["backhaul"]["sha256"] = "e" * 64
        self._rewrite_pair_journal_piece_with_matching_checksum(
            "manifest.next",
            (json.dumps(changed, sort_keys=True, indent=2) + "\n").encode())
        with self.assertRaisesRegex(lab.Hold, "RECOVERY_SEMANTIC_DRIFT"):
            lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(manifest.read_bytes(), actual_manifest)
        self.assertEqual(receipt.read_bytes(), actual_receipt)
        self.assertTrue(journal.exists())

    def test_rc7_pair_recovery_rejects_wrong_role_in_intact_journal(self):
        manifest, receipt, _, _ = self._rc7_pair_lab_fixture()
        with self.assertRaisesRegex(lab.Hold, "RECOVER_REQUIRED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64,
                                   role="ir", inject="after-manifest")
        actual_manifest, actual_receipt = manifest.read_bytes(), receipt.read_bytes()
        journal = self.root / lab.PAIR_JOURNAL
        record_file = journal / "record.json"
        record = json.loads(record_file.read_bytes())
        record["role"] = "foreign"
        record_file.write_text(json.dumps(record, sort_keys=True) + "\n")
        with self.assertRaisesRegex(lab.Hold, "RECOVERY_SEMANTIC_DRIFT"):
            lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(manifest.read_bytes(), actual_manifest)
        self.assertEqual(receipt.read_bytes(), actual_receipt)
        self.assertTrue(journal.exists())

    def test_pending_legacy_recovery_blocks_rc7_pair_apply_and_recovery(self):
        manifest, receipt, old_manifest, old_receipt = self._rc7_pair_lab_fixture()
        pending = self.root / "recovery-journal"
        pending.mkdir(mode=0o700)
        (pending / "record.json").write_text('{"state":"INCOMPLETE"}')
        with self.assertRaisesRegex(lab.Hold, "OTHER_ENGINE_RECOVERY_JOURNAL_PENDING"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64, role="ir")
        with self.assertRaisesRegex(lab.Hold, "OTHER_ENGINE_RECOVERY_JOURNAL_PENDING"):
            lab.rc7_pair_recover_lab(self.root)
        self.assertEqual(manifest.read_bytes(), old_manifest)
        self.assertEqual(receipt.read_bytes(), old_receipt)
        self.assertFalse((self.root / lab.PAIR_JOURNAL).exists())
        self.assertTrue(pending.is_dir())
        (pending / "record.json").unlink()
        pending.rmdir()
        # Removing the independent interrupted-state marker is sufficient
        # ONLY in this disposable test, never a production recovery policy.
        with self.assertRaisesRegex(lab.Hold, "RECOVER_REQUIRED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64,
                                   role="ir", inject="after-journal")
        self.assertEqual(lab.rc7_pair_recover_lab(self.root),
                         "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
        self.assertEqual(manifest.read_bytes(), old_manifest)
        self.assertEqual(receipt.read_bytes(), old_receipt)

    def test_pending_rc7_pair_blocks_direct_legacy_apply_and_rollback(self):
        manifest, receipt, old_manifest, old_receipt = self._rc7_pair_lab_fixture()
        with self.assertRaisesRegex(lab.Hold, "RECOVER_REQUIRED"):
            lab.rc7_pair_apply_lab(self.root, "a" * 64,
                                   role="ir", inject="after-manifest")
        pending = self.root / lab.PAIR_JOURNAL
        manifest_after = manifest.read_bytes()
        receipt_after = receipt.read_bytes()
        stage = self.stages / "intentionally-absent-stage"
        with self.assertRaisesRegex(lab.Hold, "OTHER_ENGINE_RECOVERY_JOURNAL_PENDING"):
            lab.activate(self.root, stage, fixture=True)
        with self.assertRaisesRegex(lab.Hold, "OTHER_ENGINE_RECOVERY_JOURNAL_PENDING"):
            lab.rollback(self.root)
        self.assertEqual(manifest.read_bytes(), manifest_after)
        self.assertEqual(receipt.read_bytes(), receipt_after)
        self.assertTrue(pending.is_dir())
        self.assertFalse((self.root / "recovery-journal").exists())
        self.assertEqual(lab.rc7_pair_recover_lab(self.root),
                         "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
        self.assertEqual(manifest.read_bytes(), old_manifest)
        self.assertEqual(receipt.read_bytes(), old_receipt)

    def test_direct_legacy_entrypoints_respect_existing_shared_control_lock(self):
        control = load("bh_control_existing_lock_for_legacy_entrypoints",
                       ROOT / "smite-managed-backhaul-control.py")
        stage = self.prepare()
        before_compose = self.compose.read_bytes()
        with control._lab_lock(self.root):
            with self.assertRaisesRegex(lab.Hold, "ANOTHER_ENGINE_TRANSACTION_ACTIVE"):
                lab.activate(self.root, stage, fixture=True)
            with self.assertRaisesRegex(lab.Hold, "ANOTHER_ENGINE_TRANSACTION_ACTIVE"):
                lab.rollback(self.root)
        self.assertEqual(self.compose.read_bytes(), before_compose)
        self.assertFalse((self.root / "recovery-journal").exists())
        self.assertFalse((self.root / "installed/backhaul").exists())
        # Both direct and managed-control paths share the lock inode.
        self.assertEqual(lab.activate(self.root, stage, fixture=True),
                         "LAB_FILES_APPLIED_NO_DOCKER_NO_LIVE_ENGINE")
        self.assertEqual(lab.rollback(self.root), "LAB_EXACT_ROLLBACK_CONFIRMED")

    def _two_host_rc7_fixture(self):
        """Two distinct private PR-runner roots; all runtime evidence synthetic."""
        ir_manifest, ir_receipt, ir_before, ir_journal = (
            self._rc7_pair_lab_fixture())
        foreign_tmp = tempfile.TemporaryDirectory(
            prefix="bh-foreign-rc7-pair-", dir=self.root.parent)
        self.addCleanup(foreign_tmp.cleanup)
        foreign = Path(foreign_tmp.name)
        foreign.chmod(0o700)
        (foreign / "EXPERIMENTAL-LAB").write_text(lab.MARKER)
        foreign_node = foreign / "node"
        foreign_node.mkdir(mode=0o700)
        foreign_config = foreign_node / "config"
        foreign_config.mkdir(mode=0o700)
        (foreign / "stages").mkdir(mode=0o700)
        (foreign_node / ".env").write_text(ENV.replace(
            "NODE_ROLE=iran", "NODE_ROLE=foreign"))
        (foreign_node / "docker-compose.yml").write_text(COMPOSE)
        state = foreign_config / "engine-state"
        state.mkdir(mode=0o700)
        manifest = state / "engines.json"
        # Prior FRP binary pins are exact and identical across both fixtures,
        # but role-specific enrollment receipts may never be exchanged.
        foreign_before = ir_before
        manifest.write_bytes(foreign_before)
        manifest.chmod(0o600)
        frp_dir = foreign / lab.PAIR_RECEIPT_DIR
        frp_dir.mkdir(mode=0o700)
        receipt = frp_dir / "record.json"
        record = json.loads(ir_journal)
        record["role"] = "foreign"
        foreign_receipt = (json.dumps(record, sort_keys=True) + "\n").encode()
        receipt.write_bytes(foreign_receipt)
        receipt.chmod(0o600)
        protected = {}
        for role, root in (("ir", self.root), ("foreign", foreign)):
            node_data = root / "node-data"
            node_data.mkdir(mode=0o700)
            files = {
                "frp-owner-child.fixture.json": {
                    "role": role, "frp": "0.71.0",
                    "tunnels": ["20182", "optical", "nahavi"]},
                "broker-replay.fixture.json": {
                    "role": role, "identity": role + "-synthetic-identity",
                    "broker": "up", "replay": "durable"},
            }
            for name, body in files.items():
                file = node_data / name
                file.write_text(json.dumps(body, sort_keys=True) + "\n")
                file.chmod(0o600)
            protected[role] = tuple(
                (root / name).read_bytes() for name in (
                    "node/docker-compose.yml", "node/.env",
                    "node-data/frp-owner-child.fixture.json",
                    "node-data/broker-replay.fixture.json"))
        return foreign, {
            "ir": (ir_manifest, ir_receipt, ir_before, ir_journal),
            "foreign": (manifest, receipt, foreign_before, foreign_receipt),
        }, protected

    def _assert_two_host_originals(self, fixtures, protected, foreign):
        for role, root in (("ir", self.root), ("foreign", foreign)):
            manifest, receipt, original_manifest, original_receipt = fixtures[role]
            self.assertEqual(manifest.read_bytes(), original_manifest)
            self.assertEqual(receipt.read_bytes(), original_receipt)
            self.assertFalse((root / lab.PAIR_JOURNAL).exists())
            self.assertFalse((root / lab.PAIR_CLEANUP_SEAL).exists())
            actual = tuple((root / name).read_bytes() for name in (
                "node/docker-compose.yml", "node/.env",
                "node-data/frp-owner-child.fixture.json",
                "node-data/broker-replay.fixture.json"))
            self.assertEqual(actual, protected[role])

    def test_rc7_two_host_coordinator_preserves_existing_frp_without_recreate(self):
        foreign, fixtures, protected = self._two_host_rc7_fixture()
        calls = []
        def observe(phase, ir, kh):
            self.assertEqual(ir, self.root)
            self.assertEqual(kh, foreign)
            calls.append(phase)
            return True
        report = lab.rc7_two_host_rehearsal_lab(
            self.root, foreign, "a" * 64, observe=observe)
        self.assertEqual(calls,
                         ["before", "after-ir", "after-both", "after-rollback"])
        self.assertEqual(report["RC7_TWO_HOST_PAIR"],
                         "DISPOSABLE_ROLE_PAIRED_EXACT_ROLLBACK")
        self.assertEqual(report["SIGNED_OWNER_CHILD_CONTINUITY"], "NOT_PROVEN")
        self.assertEqual(report["NODE_RECREATED"], "NO_DOCKER_EXECUTED_IN_LAB")
        self.assertEqual(report["INSTALL_ALLOWED"], "NO")
        self.assertEqual(report["ACTIVATION_GATE"], "HOLD")
        self._assert_two_host_originals(fixtures, protected, foreign)

    def test_rc7_two_host_abort_at_each_boundary_compensates_both(self):
        for injected in ("after-ir", "foreign-after-manifest", "after-both"):
            with self.subTest(injected=injected):
                foreign, fixtures, protected = self._two_host_rc7_fixture()
                phases = []
                def observe(phase, *_):
                    phases.append(phase)
                    return True
                with self.assertRaisesRegex(
                        lab.Hold, "TWO_HOST_ABORTED_EXACT_ROLLBACK_PROVED"):
                    lab.rc7_two_host_rehearsal_lab(
                        self.root, foreign, "a" * 64, observe=observe,
                        inject=injected)
                self.assertEqual(phases[-1], "after-rollback")
                self._assert_two_host_originals(fixtures, protected, foreign)
                self._remove_two_host_originals(fixtures, foreign)

    def _remove_two_host_originals(self, fixtures, foreign):
        # Dispose only these synthetic enrollment fixtures; preserve
        # other CI temporary directories for the remaining test methods.
        for role in ("ir", "foreign"):
            manifest, receipt, _, _ = fixtures[role]
            receipt.unlink()
            receipt.parent.rmdir()
            manifest.unlink()
            manifest.parent.rmdir()
        for root in (self.root, foreign):
            for name in ("frp-owner-child.fixture.json",
                         "broker-replay.fixture.json"):
                (root / "node-data" / name).unlink()
            (root / "node-data").rmdir()

    def test_rc7_two_host_preflight_checks_foreign_before_ir_mutation(self):
        foreign, fixtures, protected = self._two_host_rc7_fixture()
        foreign_receipt = fixtures["foreign"][1]
        altered = json.loads(foreign_receipt.read_bytes())
        altered["role"] = "ir"
        foreign_receipt.write_text(json.dumps(altered, sort_keys=True) + "\n")
        called = []
        with self.assertRaises(lab.Hold):
            lab.rc7_two_host_rehearsal_lab(
                self.root, foreign, "a" * 64,
                observe=lambda phase, *_: called.append(phase) or True)
        self.assertEqual(called, [])
        self.assertEqual(fixtures["ir"][0].read_bytes(), fixtures["ir"][2])
        self.assertEqual(fixtures["ir"][1].read_bytes(), fixtures["ir"][3])
        self.assertFalse((self.root / lab.PAIR_JOURNAL).exists())
        self.assertFalse((foreign / lab.PAIR_JOURNAL).exists())
        with self.assertRaisesRegex(lab.Hold, "DISTINCT_OBSERVER_REQUIRED"):
            lab.rc7_two_host_rehearsal_lab(
                self.root, self.root, "a" * 64, observe=lambda *_: True)
        foreign_receipt.write_bytes(fixtures["foreign"][3])
        self._assert_two_host_originals(fixtures, protected, foreign)

    def test_rc7_two_host_probe_failure_exact_rollback_or_manual_hold(self):
        foreign, fixtures, protected = self._two_host_rc7_fixture()
        with self.assertRaisesRegex(
                lab.Hold, "TWO_HOST_ABORTED_EXACT_ROLLBACK_PROVED"):
            lab.rc7_two_host_rehearsal_lab(
                self.root, foreign, "a" * 64,
                observe=lambda phase, *_: phase != "after-both")
        self._assert_two_host_originals(fixtures, protected, foreign)
        # Drifting the simulated protected child receipt at after-ir must
        # preserve the IR recovery journal for manual inspection.
        foreign_guard = foreign / "node-data/frp-owner-child.fixture.json"
        def mutate(phase, *_):
            if phase == "after-ir":
                foreign_guard.write_bytes(b"UNTRUSTED OUT OF BAND CHANGE")
            return True
        with self.assertRaisesRegex(
                lab.Hold, "TWO_HOST_ROLLBACK_MANUAL_REVIEW_REQUIRED"):
            lab.rc7_two_host_rehearsal_lab(
                self.root, foreign, "a" * 64, observe=mutate)
        self.assertTrue((self.root / lab.PAIR_JOURNAL).is_dir())
        self.assertFalse((foreign / lab.PAIR_JOURNAL).exists())
        foreign_guard.write_bytes(protected["foreign"][2])
        self.assertEqual(lab.rc7_pair_recover_lab(self.root),
                         "LAB_PAIR_EXACT_BYTES_RESTORED_NO_LIVE_ATTESTATION")
        self._assert_two_host_originals(fixtures, protected, foreign)

    def test_rc7_two_host_lock_or_pending_journal_blocks_both(self):
        foreign, fixtures, protected = self._two_host_rc7_fixture()
        with lab._rc7_pair_shared_lock(foreign):
            with self.assertRaisesRegex(
                    lab.Hold, "ANOTHER_ENGINE_TRANSACTION_ACTIVE"):
                lab.rc7_two_host_rehearsal_lab(
                    self.root, foreign, "a" * 64, observe=lambda *_: True)
        self._assert_two_host_originals(fixtures, protected, foreign)
        (foreign / lab.PAIR_JOURNAL).mkdir(mode=0o700)
        with self.assertRaisesRegex(lab.Hold, "TWO_HOST_PENDING_RECOVERY"):
            lab.rc7_two_host_rehearsal_lab(
                self.root, foreign, "a" * 64, observe=lambda *_: True)
        self.assertFalse((self.root / lab.PAIR_JOURNAL).exists())
        (foreign / lab.PAIR_JOURNAL).rmdir()
        self._assert_two_host_originals(fixtures, protected, foreign)

    def test_no_shell_docker_or_network_execution_available(self):
        src = (ROOT / "smite-managed-backhaul-transaction.py").read_text()
        for dangerous in ("subprocess", "os.system(", "socket.", "requests.", "httpx.",
                          "docker compose up", "systemctl restart"):
            self.assertNotIn(dangerous, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
