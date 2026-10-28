#!/usr/bin/env python3
"""Real module regressions; isolated files and mocked Docker transport only."""
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PINNED = 'sha256:a417e8c28426da5eaf16d59925d5c89b52dbf7849ca560dfa9a765a1266b3991'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'modules' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


storage = load('smite-node-auth-candidate')
pairing = load('smite-node-pairing')


class StorageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.anchor = Path(tmp.name)
        self.shared = self.anchor / 'u-opti'
        self.target = self.shared / 'smite-node-security' / 'replay'

    def test_shared_safe_modes_preserved_and_private_0700(self):
        for mode in (0o755, 0o750, 0o700):
            with self.subTest(mode=oct(mode)):
                self.shared.mkdir(exist_ok=True)
                self.shared.chmod(mode)
                storage._create_private_hierarchy(self.target)
                storage._create_private_hierarchy(self.target)
                self.assertEqual(stat.S_IMODE(self.shared.stat().st_mode), mode)
                for path in (self.target.parent, self.target):
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

    def test_missing_shared_parent_created_private(self):
        storage._create_private_hierarchy(self.target)
        self.assertEqual(stat.S_IMODE(self.shared.stat().st_mode), 0o700)

    def test_unsafe_modes_rejected_at_each_level(self):
        storage._create_private_hierarchy(self.target)
        for path in (self.anchor, self.shared, self.target.parent, self.target):
            original = stat.S_IMODE(path.stat().st_mode)
            modes = (0o777, 0o775, 0o702, 0o722)
            if path in (self.target.parent, self.target):
                modes += (0o755, 0o750, 0o2700)
            for mode in modes:
                with self.subTest(path=path.name, mode=oct(mode)):
                    path.chmod(mode)
                    try:
                        with self.assertRaises(storage.StageHold):
                            storage._create_private_hierarchy(self.target)
                    finally:
                        path.chmod(original)

    def test_symlinks_rejected_at_each_level_including_dangling(self):
        storage._create_private_hierarchy(self.target)
        for path in (self.anchor, self.shared, self.target.parent, self.target):
            moved = path.with_name(path.name + '-real')
            path.rename(moved)
            try:
                for destination in (moved, moved / 'missing'):
                    path.symlink_to(destination, target_is_directory=True)
                    try:
                        with self.assertRaises(storage.StageHold):
                            storage._create_private_hierarchy(self.target)
                    finally:
                        path.unlink()
            finally:
                moved.rename(path)

    def test_wrong_owner_rejected_by_real_validators(self):
        storage._create_private_hierarchy(self.target)
        real_lstat = Path.lstat
        for victim in (self.anchor, self.shared, self.target.parent, self.target):
            def wrong_owner(path, *args, **kwargs):
                value = real_lstat(path, *args, **kwargs)
                if path == victim:
                    fields = list(value)
                    fields[4] = os.geteuid() + 1
                    return os.stat_result(fields)
                return value
            with self.subTest(path=victim.name), patch.object(Path, 'lstat', wrong_owner):
                with self.assertRaises(storage.StageHold):
                    storage._create_private_hierarchy(self.target)


class ReplayTests(unittest.TestCase):
    def exercise(self, image='smite-node:stage15-local', local=PINNED, running=PINNED,
                 failure=None, output=None, final_valid=True):
        calls = []
        self.calls = calls
        def run(command, **kwargs):
            calls.append(command)
            if failure is not None and failure in command:
                raise pairing.WizardHold('inspection failed')
            if '{{.Config.Image}}' in command:
                return image
            if '{{.Image}}' in command:
                return running
            if '{{.Id}}' in command:
                return local
            if command[:2] == ['docker', 'run']:
                return output if output is not None else (
                    'REPLAY_DB_FIRST_ENROLLMENT=PROVISIONED\n'
                    'ENROLLMENT_MARKER=PERSISTENT_IN_IDENTITY_DIRECTORY')
            raise AssertionError(command)
        with tempfile.TemporaryDirectory() as tmp, patch.object(pairing, 'REPLAY_DIR', Path(tmp)), \
                patch.object(pairing, '_replay_artifacts_valid', side_effect=[False, final_valid]), \
                patch.object(pairing, '_run', side_effect=run):
            pairing._provision_replay_once()
        return calls

    def test_pinned_image_only_and_isolated_no_activation(self):
        calls = self.exercise()
        self.assertEqual(len(calls), 4)
        command = calls[-1]
        self.assertEqual(command[:2], ['docker', 'run'])
        for option, value in (('--pull', 'never'), ('--network', 'none'),
                              ('--cap-drop', 'ALL'), ('--security-opt', 'no-new-privileges')):
            self.assertEqual(command[command.index(option) + 1], value)
        self.assertEqual(command[command.index('--entrypoint') + 2], PINNED)
        self.assertIn('app.replay_enrollment', command)
        self.assertFalse(any(c[:2] in (['docker', 'compose'], ['docker', 'exec']) for c in calls))

    def test_unknown_or_mutated_image_fails_before_any_run(self):
        bad = 'sha256:' + '0' * 64
        cases = [dict(local=bad), dict(running=bad), dict(local=bad, running=bad),
                 dict(local=''), dict(running=''), dict(image=PINNED),
                 dict(image='smite-node:unverified'), dict(image='smite-node:stage15-local\n'),
                 dict(image='ghcr.io/aghajani82/smite-node:latest'),
                 dict(failure='{{.Image}}'), dict(failure='{{.Id}}')]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(pairing.WizardHold):
                self.exercise(**case)
            self.assertFalse(any(c[:2] == ['docker', 'run'] for c in self.calls))

    def test_immutable_ghcr_branch_preserved(self):
        image = 'ghcr.io/aghajani82/smite-node@sha256:' + 'a' * 64
        command = self.exercise(image=image)[-1]
        self.assertEqual(command[command.index('--entrypoint') + 2], image)

    def test_enrollment_output_and_local_artifacts_both_required(self):
        for options in (dict(output=''), dict(output='REPLAY_DB_FIRST_ENROLLMENT=PROVISIONED'),
                        dict(final_valid=False)):
            with self.subTest(options=options), self.assertRaises(pairing.WizardHold):
                self.exercise(**options)

    def test_existing_valid_replay_is_not_reenrolled(self):
        with patch.object(pairing, '_replay_artifacts_valid', return_value=True), \
                patch.object(pairing, '_run') as run:
            pairing._provision_replay_once()
            run.assert_not_called()

    def test_invalid_existing_replay_does_not_fall_back_to_enrollment(self):
        with patch.object(pairing, '_replay_artifacts_valid', side_effect=pairing.WizardHold('invalid')), \
                patch.object(pairing, '_run') as run:
            with self.assertRaises(pairing.WizardHold):
                pairing._provision_replay_once()
            run.assert_not_called()


class DiagnosticsTests(unittest.TestCase):
    def test_exact_allowlisted_reason_and_stage_without_secrets(self):
        command = ['python3', '-B', str(pairing.CANDIDATE_HELPER), '--prepare']
        for stderr, reason in (
            ('HOLD: Private directory must be owned and mode 0700\n', 'private-directory-permissions'),
            ('HOLD: Replay storage anchor is unsafe\n', 'unsafe-storage-anchor'),
            ('HOLD: Private directory must be owned and mode 0700\nSECRET', 'helper-failed'),
            ('node_secret=SECRET token=SECRET', 'helper-failed'),
        ):
            result = subprocess.CompletedProcess(command, 2, 'SECRET', stderr)
            with patch.object(pairing.subprocess, 'run', return_value=result):
                with self.assertRaises(pairing.WizardHold) as caught:
                    pairing._run(command, capture=True)
            self.assertIn('security-candidate-prepare/' + reason, str(caught.exception))
            self.assertNotIn('SECRET', str(caught.exception))
            self.assertIn('exit=2', str(caught.exception))

    def test_timeout_and_oserror_do_not_echo_command_or_exception(self):
        for error, label in ((subprocess.TimeoutExpired(['SECRET'], 10, output='SECRET'), 'timed out'),
                             (OSError('SECRET'), 'unavailable')):
            with patch.object(pairing.subprocess, 'run', side_effect=error):
                with self.assertRaises(pairing.WizardHold) as caught:
                    pairing._run(['unknown-SECRET', 'SECRET'])
            self.assertIn(label, str(caught.exception))
            self.assertNotIn('SECRET', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
