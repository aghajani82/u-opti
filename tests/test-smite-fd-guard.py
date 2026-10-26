#!/usr/bin/env python3
"""Negative path-boundary tests; NO VPS or external services."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/lab/smite_fd_guard.py"
spec = importlib.util.spec_from_file_location("smite_fd_guard_ci", SOURCE)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class DirfdGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="uopti-fdguard-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        (self.root / "node/config").mkdir(parents=True, mode=0o700)
        (self.root / "node/config/identity").write_bytes(b"private-id")

    def test_exact_bytes_and_fsync_mode(self):
        guard.replace(self.root, "node/config/data", b"alpha", 0o600)
        self.assertEqual(guard.read(self.root, "node/config/data", 100), (b"alpha", 0o600))
        guard.replace(self.root, "node/config/data", b"beta", 0o600)
        self.assertEqual(guard.read(self.root, "node/config/data", 100), (b"beta", 0o600))
        guard.remove(self.root, "node/config/data")
        self.assertEqual(guard.read(self.root, "node/config/data", 100), (None, None))

    def test_traversal_escape_and_absolute_paths_fail(self):
        for bad in ("../elsewhere", "/tmp/elsewhere", "node//config/x",
                    "./node/config/x", "node/config/../identity", "node/config/"):
            with self.subTest(path=bad):
                with self.assertRaises(guard.UnsafePath):
                    guard.read(self.root, bad, 100)

    def test_symlink_parent_and_final_never_followed(self):
        with tempfile.TemporaryDirectory(prefix="uopti-guard-outside-") as outside:
            external = Path(outside) / "canary"
            external.write_bytes(b"DO_NOT_TOUCH")
            (self.root / "node/config/evil").symlink_to(external)
            for fn in (lambda: guard.read(self.root, "node/config/evil", 100),
                       lambda: guard.replace(self.root, "node/config/evil", b"bad", 0o600),
                       lambda: guard.remove(self.root, "node/config/evil")):
                with self.assertRaises((guard.UnsafePath, OSError)):
                    fn()
            (self.root / "node/redirect").symlink_to(outside, target_is_directory=True)
            with self.assertRaises((guard.UnsafePath, OSError)):
                guard.replace(self.root, "node/redirect/canary", b"bad", 0o600)
            self.assertEqual(external.read_bytes(), b"DO_NOT_TOUCH")

    def test_hardlink_fails_even_for_same_user(self):
        external = self.root / "node/config/identity"
        link = self.root / "node/config/alias"
        os.link(external, link)
        with self.assertRaises(guard.UnsafePath):
            guard.read(self.root, "node/config/alias", 100)
        with self.assertRaises(guard.UnsafePath):
            guard.replace(self.root, "node/config/alias", b"new", 0o600)
        self.assertEqual(external.read_bytes(), b"private-id")

    def test_untrusted_directory_permissions_and_root(self):
        node = self.root / "node"
        node.chmod(0o777)
        with self.assertRaises(guard.UnsafePath):
            guard.read(self.root, "node/config/identity", 100)
        node.chmod(0o755)
        self.root.chmod(0o755)
        with self.assertRaises(guard.UnsafePath):
            guard.read(self.root, "node/config/identity", 100)
        self.root.chmod(0o700)

    def test_journal_audit_rename_never_overwrites(self):
        guard.replace(self.root, "audit-old", b"KEEP", 0o600)
        guard.replace(self.root, ".engine-journal.json", b"JOURNAL", 0o600)
        with self.assertRaises(guard.UnsafePath):
            guard.move(self.root, ".engine-journal.json", "audit-old")
        self.assertEqual(guard.read(self.root, "audit-old", 100)[0], b"KEEP")
        guard.move(self.root, ".engine-journal.json", "audit-new")
        self.assertEqual(guard.read(self.root, "audit-new", 100)[0], b"JOURNAL")
        self.assertEqual(guard.read(self.root, ".engine-journal.json", 100), (None, None))

    def test_concurrent_lock_is_not_ignored(self):
        with guard.lock(self.root):
            with self.assertRaisesRegex(guard.UnsafePath, "SHARED_ENGINE_TRANSACTION_LOCKED"):
                with guard.lock(self.root):
                    self.fail("second guard lock unexpectedly succeeded")

    def test_read_size_limit_and_nonregular_file_fail_closed(self):
        guard.replace(self.root, "node/config/file", b"1234567890", 0o600)
        with self.assertRaises(guard.UnsafePath):
            guard.read(self.root, "node/config/file", 5)
        with self.assertRaises(guard.UnsafePath):
            guard.read(self.root, "node/config", 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
