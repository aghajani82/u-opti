#!/usr/bin/env python3
"""Offline RC.2 KH Replay-only tests; no VPS, network or Docker."""
from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest.mock import Mock, call, patch

SOURCE = Path(__file__).resolve().parents[1] / "modules/smite-rc2-kh-replay-only.py"
spec = importlib.util.spec_from_file_location("kh_replay_only", SOURCE)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def info(kind="file"):
    return types.SimpleNamespace(
        st_mode=(stat.S_IFDIR if kind == "dir" else stat.S_IFREG)
        | (0o700 if kind == "dir" else 0o600),
        st_uid=0, st_nlink=1,
    )


class ReplayOnlyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        identity_dir = root / "identities"
        identity_dir.mkdir()
        replay_dir = root / "replay"
        replay_dir.mkdir()
        self.pairing = types.SimpleNamespace(
            IDENTITY_DIR=identity_dir,
            IDENTITY_FILE=identity_dir / "node-identity.json",
            REPLAY_DB=replay_dir / "agent-replay.sqlite3",
            REPLAY_DIR=replay_dir,
            CONTAINER_IDENTITY="/run/smite-node-identity/node-identity.json",
            CONTAINER_REPLAY="/var/lib/smite-node/auth/agent-replay.sqlite3",
            _FOREIGN_NODE_IMAGE_RC2="ghcr.io/aghajani82/smite-node@sha256:"+"a"*64,
            _identity_record=Mock(return_value=("test-node-abcdefgh","b"*64)),
            _replay_artifacts_valid=Mock(return_value=True),
            _run=Mock(),
            state_values=Mock(return_value={
                "SMITE_ROLE": "foreign", "SMITE_NODE_NAME": "node-kh",
                "SMITE_PANEL_DOMAIN": "ir.kolbe1.ir",
                "SMITE_MANAGED_VERSION": "2.0.0-rc.1",
            }),
        )
        self.gate = types.SimpleNamespace(admit_kh=Mock(return_value=p.EXPECTED_ADMISSION))

    def fake_entries(self, marker=False, db=False, quarantine=False):
        directory = self.pairing.IDENTITY_DIR
        values = {
            directory: info("dir"),
            self.pairing.IDENTITY_FILE: info(),
            directory / "replay-enrollment.json": info() if marker else None,
            self.pairing.REPLAY_DB: info() if db else None,
            directory / "replay-restore-hold.json": info() if quarantine else None,
        }
        return patch.object(p, "entry", side_effect=lambda path: values.get(path))

    def test_enrollment_is_offline_immutable_no_activation(self):
        cmd = p.enrollment_command(self.pairing)
        joined = " ".join(cmd)
        for flag in ("--rm", "--pull never", "--network none", "--read-only",
                     "--cap-drop ALL", "no-new-privileges",
                     "--confirm-first-provision"):
            self.assertIn(flag, joined)
        self.assertNotIn("docker compose", joined)
        for forbidden in ("--publish", "--privileged", "--force-recreate",
                          "--pull always", "node-identity.json="):
            self.assertNotIn(forbidden, joined)
        self.assertEqual(cmd[cmd.index("--entrypoint")+2],
                         self.pairing._FOREIGN_NODE_IMAGE_RC2)

    def test_absent_replay_is_plan_only(self):
        with self.fake_entries(), patch.object(p, "private_tree", return_value=False):
            self.assertEqual(p.replay_state(self.pairing), "ABSENT")
        self.pairing._replay_artifacts_valid.assert_not_called()

    def test_partial_state_marker_only_is_hold(self):
        with self.fake_entries(marker=True), patch.object(p, "private_tree", return_value=True):
            with self.assertRaisesRegex(p.Hold, "REPLAY_PARTIAL_STATE"):
                p.replay_state(self.pairing)

    def test_partial_state_database_only_is_hold(self):
        with self.fake_entries(db=True), patch.object(p, "private_tree", return_value=True):
            with self.assertRaisesRegex(p.Hold, "REPLAY_PARTIAL_STATE"):
                p.replay_state(self.pairing)

    def test_valid_replay_is_read_only(self):
        with self.fake_entries(marker=True, db=True), \
             patch.object(p, "private_tree", return_value=True):
            self.assertEqual(p.replay_state(self.pairing), "READY")
        self.pairing._replay_artifacts_valid.assert_called_once()

    def test_replay_restore_quarantine_blocks_even_valid_ledger(self):
        with self.fake_entries(marker=True, db=True, quarantine=True), \
             patch.object(p, "private_tree", return_value=True):
            with self.assertRaisesRegex(p.Hold, "REPLAY_RESTORE_QUARANTINED"):
                p.replay_state(self.pairing)

    def test_nonempty_directory_without_marker_is_hold(self):
        (self.pairing.REPLAY_DIR / "leftover-journal").write_text("x")
        with self.fake_entries(), patch.object(p, "private_tree", return_value=True):
            with self.assertRaisesRegex(p.Hold, "REPLAY_DIRECTORY_NONEMPTY"):
                p.replay_state(self.pairing)

    def test_missing_dual_consent_performs_no_mutation(self):
        with patch.dict(os.environ, {
            "UOPTI_SMITE_PAIRING_FIELD_TRIAL": "NO",
            "UOPTI_SMITE_RC2_REPLAY_ONLY": "NO",
        }), patch.object(p, "lock_identity") as lock:
            with self.assertRaisesRegex(p.Hold, "REPLAY_DUAL_CONSENT_REQUIRED"):
                p.apply_once(self.pairing, self.gate)
            lock.assert_not_called()
            self.pairing._run.assert_not_called()

    def test_operator_cancel_performs_no_mutation(self):
        with patch.dict(os.environ, {
            "UOPTI_SMITE_PAIRING_FIELD_TRIAL": "YES",
            "UOPTI_SMITE_RC2_REPLAY_ONLY": "YES",
        }), patch.object(p.sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", return_value="CANCEL"), \
             patch.object(p, "lock_identity") as lock:
            with self.assertRaisesRegex(p.Hold, "OPERATOR_CANCELLED"):
                p.apply_once(self.pairing, self.gate)
            lock.assert_not_called()
            self.pairing._run.assert_not_called()

    def approved(self):
        return (
            patch.dict(os.environ, {
                "UOPTI_SMITE_PAIRING_FIELD_TRIAL": "YES",
                "UOPTI_SMITE_RC2_REPLAY_ONLY": "YES",
            }),
            patch.object(p.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="ENROLL-REPLAY-ONCE"),
        )

    def test_exactly_one_replay_provision_no_node_restart(self):
        self.pairing._run.return_value = (
            "REPLAY_DB_FIRST_ENROLLMENT=PROVISIONED\n"
            "ENROLLMENT_MARKER=PERSISTENT_IN_IDENTITY_DIRECTORY\n"
            "SIGNED_TRAFFIC_ACTIVATION=NOT_AUTHORIZED"
        )
        fd = os.open(os.devnull, os.O_RDONLY)
        with self.approved()[0], self.approved()[1], self.approved()[2], \
             patch.object(p, "lock_identity", return_value=fd), \
             patch.object(p, "replay_state", side_effect=["ABSENT", "ABSENT", "READY"]), \
             patch.object(p, "admission") as check, \
             patch.object(p, "private_tree") as make, \
             patch.object(p, "fingerprint", return_value=b"same-key"), \
             patch.object(p, "runtime_snapshot", return_value=("image","started","ss")), \
             patch("sys.stdout", io.StringIO()) as output:
            p.apply_once(self.pairing, self.gate)
            self.assertIn("KH_REPLAY_FIRST_ENROLLMENT=PASS", output.getvalue())
            self.assertIn("KH_SIGNED_RUNTIME=PAUSED", output.getvalue())
            self.assertNotIn("b"*64, output.getvalue())
            self.assertEqual(check.call_count, 2)
            make.assert_called_once_with(self.pairing.REPLAY_DIR, create=True)
            self.pairing._run.assert_called_once_with(
                p.enrollment_command(self.pairing), timeout=90, capture=True)
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_already_valid_does_not_write_or_restart(self):
        fd = os.open(os.devnull, os.O_RDONLY)
        with self.approved()[0], self.approved()[1], self.approved()[2], \
             patch.object(p, "lock_identity", return_value=fd), \
             patch.object(p, "replay_state", return_value="READY"), \
             patch.object(p, "admission"), \
             patch.object(p, "private_tree") as make, \
             patch("sys.stdout", io.StringIO()) as output:
            p.apply_once(self.pairing, self.gate)
            self.assertIn("KH_REPLAY_ALREADY_VALID=YES", output.getvalue())
            make.assert_not_called()
            self.pairing._run.assert_not_called()

    def test_failed_enrollment_never_auto_retries(self):
        self.pairing._run.side_effect = RuntimeError("No")
        fd = os.open(os.devnull, os.O_RDONLY)
        with self.approved()[0], self.approved()[1], self.approved()[2], \
             patch.object(p, "lock_identity", return_value=fd), \
             patch.object(p, "replay_state", side_effect=["ABSENT", "ABSENT"]), \
             patch.object(p, "admission"), \
             patch.object(p, "private_tree"), \
             patch.object(p, "fingerprint", return_value=b"same-key"), \
             patch.object(p, "runtime_snapshot", return_value=("same",)), \
             self.assertRaises(RuntimeError):
            p.apply_once(self.pairing, self.gate)
        self.assertEqual(self.pairing._run.call_count, 1)

    def test_cli_plan_has_no_apply(self):
        with patch.object(p.os, "geteuid", return_value=0), \
             patch.object(p.socket, "gethostname", return_value="kh"), \
             patch.object(p, "load_checked", side_effect=[self.pairing, self.gate]), \
             patch.object(p, "admission"), \
             patch.object(p, "replay_state", return_value="ABSENT"), \
             patch.object(p, "apply_once") as apply, \
             patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(p.main(["--plan"]), 0)
            self.assertIn("KH_REPLAY_PLAN=PASS_READ_ONLY", out.getvalue())
            self.assertIn("LIVE_CHANGES=NONE", out.getvalue())
            apply.assert_not_called()

    def test_verify_refuses_absent_replay(self):
        with patch.object(p.os, "geteuid", return_value=0), \
             patch.object(p.socket, "gethostname", return_value="kh"), \
             patch.object(p, "load_checked", side_effect=[self.pairing, self.gate]), \
             patch.object(p, "admission"), \
             patch.object(p, "replay_state", return_value="ABSENT"), \
             patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(p.main(["--verify"]), 2)
            self.assertIn("REPLAY_NOT_PROVISIONED", out.getvalue())

    def test_wrong_host_refuses_to_load_sources(self):
        with patch.object(p.os, "geteuid", return_value=0), \
             patch.object(p.socket, "gethostname", return_value="ir"), \
             patch.object(p, "load_checked") as load, \
             patch("sys.stdout", io.StringIO()):
            self.assertEqual(p.main(["--plan"]), 2)
            load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
