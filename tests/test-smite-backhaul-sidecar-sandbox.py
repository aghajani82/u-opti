#!/usr/bin/env python3
"""End-to-end file transaction/rollback inside synthetic /tmp sandbox only."""
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "modules" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sidecar = load("standalone_sidecar", "smite-backhaul-sidecar.py")
sandbox = load("standalone_sidecar_sandbox", "smite-backhaul-sidecar-sandbox.py")


class OfflineTransactionalSandbox(unittest.TestCase):
    def setUp(self):
        self.tokens = tempfile.TemporaryDirectory()
        self.addCleanup(self.tokens.cleanup)
        token = Path(self.tokens.name) / "secret"
        token.write_text("A"*48+"\n")
        token.chmod(0o600)
        self.token = token

    def fixture(self, role):
        temp = tempfile.TemporaryDirectory(prefix="uopti-bh-sandbox-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        sandbox.bootstrap_mock(root, role)
        stage = sidecar.prepare(role, self.token, "ir.kolbe1.ir", "kh.kolbe1.ir")
        self.addCleanup(lambda p=stage: __import__("shutil").rmtree(p))
        return root, stage

    def resource(self, root, file):
        return root / file.lstrip("/")

    def test_successful_apply_and_exact_rollback(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                root, stage = self.fixture(role)
                edited = None
                if role == "ir":
                    edited = self.resource(
                        root, "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf"
                    )
                    baseline = edited.read_bytes()
                manifest = sandbox.simulate_apply(root, stage, role)
                self.assertEqual(len(manifest["resources"]),
                                 len(sandbox.rollback.ALLOW[role]))
                self.assertEqual(
                    stat.S_IMODE((root / sandbox.MANIFEST).stat().st_mode), 0o600
                )
                for row in manifest["resources"]:
                    target = self.resource(root, row["path"])
                    self.assertTrue(target.is_file())
                    self.assertEqual(sandbox.digest(target.read_bytes()),
                                     row["applied_sha256"])
                if edited is not None:
                    self.assertIn(sandbox.INCLUDE, edited.read_text())
                plan = sandbox.simulate_rollback(root)
                self.assertTrue(any("PLAN ONLY" in item for item in plan))
                self.assertFalse((root / sandbox.MANIFEST).exists())
                self.assertFalse((root / sandbox.BACKUP).exists())
                for dest, operation in sandbox.rollback.ALLOW[role].items():
                    if operation == "create":
                        self.assertFalse(self.resource(root, dest).exists())
                if edited is not None:
                    self.assertEqual(edited.read_bytes(), baseline)

    def test_failure_injection_is_restored(self):
        for role in ("ir", "kh"):
            for step in range(1, len(sandbox.rollback.ALLOW[role])+1):
                with self.subTest(role=role, failure_after=step):
                    root, stage = self.fixture(role)
                    backend = self.resource(
                        root, "/etc/nginx/conf.d/u-opti-smite-panel-backend.conf"
                    )
                    baseline = backend.read_bytes() if role == "ir" else None
                    with self.assertRaisesRegex(RuntimeError, "Injected"):
                        sandbox.simulate_apply(root, stage, role, fail_after=step)
                    self.assertFalse((root / sandbox.MANIFEST).exists())
                    self.assertFalse((root / sandbox.BACKUP).exists())
                    for dest, operation in sandbox.rollback.ALLOW[role].items():
                        if operation == "create":
                            self.assertFalse(self.resource(root, dest).exists())
                    if role == "ir":
                        self.assertEqual(baseline, backend.read_bytes())

    def test_drift_blocks_rollback_and_never_overwrites(self):
        root, stage = self.fixture("kh")
        sandbox.simulate_apply(root, stage, "kh")
        path = self.resource(root, "/etc/u-opti/backhaul-sidecar/kh.toml")
        before = path.read_bytes()
        path.write_bytes(before+b"\n# external change\n")
        with self.assertRaises(sandbox.rollback.RollbackUnsafe):
            sandbox.simulate_rollback(root)
        self.assertEqual(path.read_bytes(), before+b"\n# external change\n")
        self.assertTrue((root / sandbox.MANIFEST).is_file())
        self.assertTrue(self.resource(root, "/etc/nginx/conf.d/u-opti-backhaul-kh-bridge.conf").exists())

    def test_guard_rejects_non_sandbox_missing_marker(self):
        other = tempfile.TemporaryDirectory(prefix="not-sidecar-sandbox-")
        self.addCleanup(other.cleanup)
        with self.assertRaises(sandbox.SandboxRefused):
            sandbox.check_sandbox(Path(other.name))
        private = tempfile.TemporaryDirectory(prefix="uopti-bh-sandbox-")
        self.addCleanup(private.cleanup)
        with self.assertRaises(sandbox.SandboxRefused):
            sandbox.check_sandbox(Path(private.name))

    def test_symlink_ancestor_rejected(self):
        root, stage = self.fixture("kh")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (root / "etc").symlink_to(outside.name)
        with self.assertRaises(sandbox.SandboxRefused):
            sandbox.simulate_apply(root, stage, "kh")
        self.assertEqual(list(Path(outside.name).iterdir()), [])

    def test_second_apply_requires_explicit_rollback(self):
        root, stage = self.fixture("ir")
        sandbox.simulate_apply(root, stage, "ir")
        with self.assertRaises(sandbox.SandboxRefused):
            sandbox.simulate_apply(root, stage, "ir")
        sandbox.simulate_rollback(root)


if __name__ == "__main__":
    unittest.main()
