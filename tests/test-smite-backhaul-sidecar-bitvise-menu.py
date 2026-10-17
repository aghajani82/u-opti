#!/usr/bin/env python3
"""Safe non-network regression checks for two-terminal wizard selection."""
import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import sys
import unittest

file = Path(__file__).resolve().parents[1] / "modules/smite-backhaul-sidecar-paste-pair.py"
spec = importlib.util.spec_from_file_location("pair_under_test", file)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PairingMenuTests(unittest.TestCase):
    def test_noninteractive_session_refused(self):
        with patch.object(sys.stdin, "isatty", return_value=False):
            with self.assertRaises(module.PasteHold):
                module._interactive()

    def test_ir_requires_explicit_confirmation(self):
        with patch.object(sys, "argv", ["helper", "--show-ir"]), \
             patch.object(module, "show_ir") as action, \
             redirect_stdout(io.StringIO()) as screen:
            self.assertEqual(module.main(), 2)
            action.assert_not_called()
            self.assertIn("HOLD", screen.getvalue())

    def test_kh_requires_explicit_confirmation(self):
        with patch.object(sys, "argv", ["helper", "--paste-kh"]), \
             patch.object(module, "paste_kh") as action, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(), 2)
            action.assert_not_called()

    def test_installed_ir_requires_explicit_confirmation(self):
        with patch.object(sys, "argv", ["helper", "--show-installed-ir"]), \
             patch.object(module, "show_installed_ir") as action, \
             redirect_stdout(io.StringIO()) as screen:
            self.assertEqual(module.main(), 2)
            action.assert_not_called()
            self.assertNotIn("PAIRING CODE:", screen.getvalue())

    def test_installed_ir_refuses_partial_journal_and_never_regenerates(self):
        from types import SimpleNamespace
        trial = SimpleNamespace(
            _root=lambda role: Path("/synthetic/ir"),
            _journal_read=lambda root: {"role": "ir", "phase": "files_installed"},
        )
        with patch.object(module, "_interactive"), \
             patch.object(module.pair, "_trusted_role"), \
             patch.object(module.pair, "_safe_parents"), \
             patch.object(module, "_load", return_value=trial), \
             patch.object(module.pair.token_tool, "generate") as generate:
            with self.assertRaises(module.PasteHold):
                module.show_installed_ir()
            generate.assert_not_called()

    def test_installed_ir_only_reads_verified_existing_token(self):
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as home:
            secret = Path(home) / "shared.token"
            secret.write_text("A" * 43 + "\\n")
            trial = SimpleNamespace(
                _root=lambda role: Path("/synthetic/ir"),
                _journal_read=lambda root: {"role": "ir", "phase": "trial_active"},
            )
            with patch.object(module, "TOKEN", secret), \
                 patch.object(module, "_interactive"), \
                 patch.object(module.pair, "_trusted_role"), \
                 patch.object(module.pair, "_safe_parents"), \
                 patch.object(module, "_load", return_value=trial), \
                 patch.object(module.pair.token_tool, "inspect", return_value=True), \
                 patch.object(module.pair.token_tool, "generate") as generate:
                self.assertEqual(module.show_installed_ir(), "A" * 43)
                self.assertEqual(secret.read_text(), "A" * 43 + "\\n")
                generate.assert_not_called()

    def test_preflight_blocks_ir_before_read(self):
        with patch.object(module, "_interactive"), \
             patch.object(module.pair, "_trusted_role"), \
             patch.object(module.pair, "_safe_parents"), \
             patch.object(module.pair, "_fresh", side_effect=module.PasteHold("busy")), \
             patch.object(module.pair.token_tool, "generate") as write:
            with self.assertRaises(module.PasteHold):
                module.show_ir()
            write.assert_not_called()

    def test_preflight_blocks_kh_before_prompt(self):
        with patch.object(module, "_interactive"), \
             patch.object(module.pair, "_trusted_role"), \
             patch.object(module.pair, "_safe_parents"), \
             patch.object(module.pair, "_fresh", side_effect=module.PasteHold("busy")), \
             patch.object(module.getpass, "getpass") as prompt:
            with self.assertRaises(module.PasteHold):
                module.paste_kh()
            prompt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
