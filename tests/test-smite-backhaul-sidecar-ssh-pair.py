#!/usr/bin/env python3
"""Hermetic strict-SSH IR→KH pairing tests; no network or real host changes."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "pair_under_test", ROOT / "modules/smite-backhaul-sidecar-ssh-pair.py")
pair = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(pair)

VALUE = b"V" * 43 + b"\n"


class SecurePairingTests(unittest.TestCase):
    def test_ssh_refuses_unsafe_hostname_and_uses_pinned_host_keys(self):
        args = pair._ssh_args("kh.kolbe1.ir", 5055)
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("BatchMode=yes", args)
        self.assertIn("PasswordAuthentication=no", args)
        self.assertIn("PreferredAuthentications=publickey", args)
        self.assertIn("ForwardAgent=no", args)
        self.assertIn("ClearAllForwardings=yes", args)
        self.assertIn("UserKnownHostsFile=/root/.ssh/known_hosts", args)
        self.assertEqual("5055", args[args.index("-p") + 1])
        self.assertIn("root@kh.kolbe1.ir", args)
        self.assertNotIn(VALUE.decode().strip(), " ".join(args))
        for name in ("-oProxyCommand=evil", "kh.kolbe1.ir;touch /tmp/a", "not_a_host"):
            with self.assertRaises(ValueError):
                pair._ssh_args(name, 22)
        for n in (0, 65536):
            with self.assertRaises(pair.PairingHold):
                pair._ssh_args("kh.kolbe1.ir", n)

    def test_ir_send_transmits_only_on_ssh_stdin_and_exact_ack(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "shared.token"
            f.write_bytes(VALUE)
            with patch.object(pair, "TOKEN", f), \
                 patch.object(pair, "_trusted_role"), \
                 patch.object(pair, "_safe_parents"), \
                 patch.object(pair, "_fresh") as fresh, \
                 patch.object(pair.token_tool, "inspect", return_value=True), \
                 patch.object(pair.subprocess, "run", return_value=types.SimpleNamespace(
                     returncode=0, stdout=b"KH_PAIRING_RECEIVED_PRIVATE_AND_VALID\n",
                     stderr=b"")) as ssh:
                self.assertEqual("IR_TO_KH_PRIVATE_SSH_PAIRING_PASSED",
                                 pair.send_ir("kh.kolbe1.ir", 22))
                fresh.assert_called_once_with("ir")
                args, kwargs = ssh.call_args
                self.assertEqual(VALUE, kwargs["input"])
                self.assertTrue(kwargs["capture_output"])
                self.assertNotIn(VALUE.decode().strip(), str(args))

    def test_ssh_error_and_unknown_remote_ack_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "shared.token"
            path.write_bytes(VALUE)
            with patch.object(pair, "TOKEN", path), \
                 patch.object(pair, "_trusted_role"), \
                 patch.object(pair, "_safe_parents"), \
                 patch.object(pair, "_fresh"), \
                 patch.object(pair.token_tool, "inspect", return_value=True), \
                 patch.object(pair.subprocess, "run", return_value=types.SimpleNamespace(
                     returncode=0, stdout=b"ANYTHING_ELSE\n", stderr=b"token:TOPSECRET\n")):
                with self.assertRaises(pair.PairingHold):
                    pair.send_ir("kh.kolbe1.ir", 22)

    def test_receiver_create_exact_0600_then_allow_idempotent_match(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d) / "private"
            path = directory / "shared.token"
            with patch.object(pair, "PRIVATE_DIR", directory), \
                 patch.object(pair, "TOKEN", path), \
                 patch.object(pair, "_trusted_role"), \
                 patch.object(pair, "_safe_parents"), \
                 patch.object(pair, "_fresh") as fresh, \
                 patch.object(pair.token_tool, "secure_dir", return_value=True), \
                 patch.object(pair.token_tool, "inspect",
                              side_effect=lambda p: p.is_file()
                              and stat.S_IMODE(p.stat().st_mode) == 0o600):
                self.assertEqual("KH_PAIRING_RECEIVED_PRIVATE_AND_VALID",
                                 pair.receive_kh(io.BytesIO(VALUE)))
                fresh.assert_called_once_with("kh")
                self.assertEqual(VALUE, path.read_bytes())
                self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
                self.assertEqual(0o700, stat.S_IMODE(directory.stat().st_mode))
                self.assertEqual("KH_PAIRING_ALREADY_MATCHED_NO_CHANGE",
                                 pair.receive_kh(io.BytesIO(VALUE)))
                with self.assertRaises(pair.PairingHold):
                    pair.receive_kh(io.BytesIO(b"X" * 43 + b"\n"))
                self.assertEqual(VALUE, path.read_bytes())

    def test_receiver_rejects_invalid_stream_and_active_host_without_write(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d) / "private"
            path = directory / "shared.token"
            with patch.object(pair, "PRIVATE_DIR", directory), \
                 patch.object(pair, "TOKEN", path), \
                 patch.object(pair, "_trusted_role"), \
                 patch.object(pair, "_safe_parents"), \
                 patch.object(pair, "_fresh", side_effect=pair.PairingHold("active")):
                with self.assertRaises(pair.PairingHold):
                    pair.receive_kh(io.BytesIO(VALUE))
                self.assertFalse(path.exists())
                with self.assertRaises(pair.PairingHold):
                    pair.receive_kh(io.BytesIO(b"top-secret\n"))
                self.assertFalse(directory.exists())

    def test_role_file_mismatch_and_duplicate_role_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state"
            class State:
                def lstat(self):
                    return types.SimpleNamespace(
                        st_mode=stat.S_IFREG | 0o600,
                        st_uid=0, st_gid=0, st_size=100)
                def read_text(self, encoding):
                    return path.read_text()
            with patch.object(pair, "STATE", State()), \
                 patch.object(pair.os, "geteuid", return_value=0):
                path.write_text("SMITE_ROLE=panel-iran\nSMITE_CONNECTION_MODE=standard\n")
                with self.assertRaises(pair.PairingHold):
                    pair._trusted_role("kh")
                pair._trusted_role("ir")
                path.write_text("SMITE_ROLE=foreign\nSMITE_ROLE=panel-iran\nSMITE_CONNECTION_MODE=standard\n")
                with self.assertRaises(pair.PairingHold):
                    pair._trusted_role("kh")

    def test_no_secret_or_ssh_error_text_printed_by_cli(self):
        with patch.object(sys, "argv", ["pair", "--send-ir", "--kh-host",
                                        "kh.kolbe1.ir", "--confirm", "PAIR-KH-TEST-HOST"]), \
             patch.object(pair, "send_ir", side_effect=RuntimeError(
                 "Sensitive private token text")), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(2, pair.main())
            self.assertNotIn("Sensitive", output.getvalue())
            self.assertIn("HOLD:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
