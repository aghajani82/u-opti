#!/usr/bin/env python3
"""Non-root, hermetic private token tests; never print or upload a secret."""
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "modules/smite-backhaul-sidecar-token.py"
spec = importlib.util.spec_from_file_location("bh_private_pairing_test", MODULE)
token = importlib.util.module_from_spec(spec)
spec.loader.exec_module(token)


class PairingTests(unittest.TestCase):
    def test_requires_root_and_explicit_private_mode(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(token.os, "geteuid", return_value=1001):
                with self.assertRaisesRegex(token.TokenRefused, "Root required"):
                    token.generate(Path(d))
            self.assertFalse((Path(d) / "shared.token").exists())

    def test_one_time_secure_creation_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            # Mock only the root identity gate; destination remains a fixture.
            with patch.object(token.os, "geteuid", return_value=0), \
                 patch.object(token, "secure_dir", return_value=True):
                token.generate(directory)
                path = directory / "shared.token"
                before = path.read_bytes()
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertGreaterEqual(len(before.strip()), 24)
                with self.assertRaisesRegex(token.TokenRefused, "NO OVERWRITE"):
                    token.generate(directory)
                self.assertEqual(before, path.read_bytes())

    def test_symlink_directory_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "real"
            source.mkdir()
            link = Path(d) / "linked"
            link.symlink_to(source, target_is_directory=True)
            with patch.object(token.os, "geteuid", return_value=0):
                with self.assertRaisesRegex(token.TokenRefused, "Unsafe token directory"):
                    token.generate(link)
            self.assertFalse((source / "shared.token").exists())

    def test_verify_never_leaks_invalid_token(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "shared.token"
            path.write_bytes(b"secret-not-meant-for-output\n")
            path.chmod(0o644)
            self.assertFalse(token.inspect(path))
            path.chmod(0o600)
            with patch.object(token, "secure_dir", return_value=True), \
                 patch.object(token.Path, "lstat", wraps=Path.lstat):
                # The file is owned by the runner, so verification must refuse.
                self.assertFalse(token.inspect(path))


if __name__ == "__main__":
    unittest.main()
