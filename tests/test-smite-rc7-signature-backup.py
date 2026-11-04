#!/usr/bin/env python3
"""Original-journal backup alternative; no external host or service access."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import stat
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('backup_rt',ROOT/'modules/smite-rc7-wss-runtime.py')
rt=importlib.util.module_from_spec(spec);spec.loader.exec_module(rt)

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.doc={'schema':1,'role':'ir','state':'COMMITTED','services':['smite-panel','smite-node'],
                  'domain':'ir.example.test','project':'retained','protected':{'/config':{'sha256':'a'*64}},
                  'baseline':{n:{'signature':'b'*64,'files':['/config']} for n in ('smite-panel','smite-node')}}
        self.raw=json.dumps(self.doc).encode()
        self.backup=self.root/'original.json';self.backup.write_bytes(self.raw);self.backup.chmod(0o600)
        self.digest=hashlib.sha256(self.raw).hexdigest()
        self.state=self.root/'state';self.state.mkdir(mode=0o700)
        self.record=self.state/'record.json';self.record.write_bytes(self.raw);self.record.chmod(0o600)
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(rt,'STATE',self.state))
        self.stack.enter_context(patch.object(rt,'LOCK',self.root/'engine.lock'))
    def proof(self,**kw):
        rt.backup_recovery_proof(kw.get('path',str(self.backup)),kw.get('digest',self.digest),kw.get('doc',self.doc))
    def test_valid_original_and_policy_rollback_proof(self):
        self.proof()
        recovered=copy.deepcopy(self.doc)
        for value in recovered['baseline'].values():value['signature_policy']=rt.DNS_EMPTY_POLICY
        self.proof(doc=recovered)
        self.assertEqual(self.record.read_bytes(),self.raw)
    def test_hash_missing_or_wrong_and_corrupt_json(self):
        for digest in ('','x'*64,'0'*64):
            with self.subTest(digest=digest),self.assertRaises(rt.Hold):self.proof(digest=digest)
        raw=b'not JSON';self.backup.write_bytes(raw)
        with self.assertRaises(ValueError):self.proof(digest=hashlib.sha256(raw).hexdigest())
    def test_missing_incomplete_stale_wrong_identity_or_replaced_fingerprint(self):
        for mutate in (lambda d:d.pop('protected'),lambda d:d.update(role='foreign'),
                       lambda d:d.update(schema=True),lambda d:d.update(project='other'),
                       lambda d:d.update(state='PREPARED'),
                       lambda d:d['baseline']['smite-node'].update(signature='c'*64),
                       lambda d:d['baseline']['smite-node'].update(signature_policy=rt.DNS_EMPTY_POLICY)):
            altered=copy.deepcopy(self.doc);mutate(altered)
            raw=json.dumps(altered).encode();self.backup.write_bytes(raw)
            with self.assertRaisesRegex(rt.Hold,'BACKUP_NOT_ORIGINAL_WSS_JOURNAL'):
                self.proof(digest=hashlib.sha256(raw).hexdigest())
        self.backup.unlink()
        with self.assertRaises(OSError):self.proof()
    def test_duplicate_keys_rejected_even_with_matching_digest(self):
        raw=b'{"schema":1,"schema":1}'
        self.backup.write_bytes(raw)
        with self.assertRaisesRegex(rt.Hold,'DUPLICATE_BACKUP_JSON_KEY'):
            self.proof(digest=hashlib.sha256(raw).hexdigest())
    def test_live_journal_symlinks_hardlinks_permissions_and_oversize_fail(self):
        with self.assertRaisesRegex(rt.Hold,'BACKUP_IS_LIVE_JOURNAL'):self.proof(path=str(self.record))
        link=self.root/'link';link.symlink_to(self.backup)
        with self.assertRaises(OSError):self.proof(path=str(link))
        parent=self.root/'parent';parent.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(OSError):self.proof(path=str(parent/'original.json'))
        os.link(self.backup,self.root/'hardlink')
        with self.assertRaises(rt.Hold):self.proof()
        (self.root/'hardlink').unlink()
        self.backup.chmod(0o644)
        with self.assertRaises(rt.Hold):self.proof()
        self.backup.chmod(0o600);self.backup.write_bytes(b'x'*1048577)
        with self.assertRaises(rt.Hold):self.proof()
    def test_failed_restore_drill_prevents_proof(self):
        with patch.object(rt,'atomic_new',side_effect=OSError('no space')):
            with self.assertRaises(OSError):self.proof()
        self.assertEqual(self.record.read_bytes(),self.raw)
    def cli(self,action,answers=None,extra=None,gate_error=None):
        argv=['runtime',action,'--role','ir','--recovery-backup',str(self.backup),'--backup-sha256',self.digest]
        if extra:argv+=extra
        with patch('sys.argv',argv),patch.object(rt,'recovery_console'), \
             patch.object(rt,'check_protected'),patch.object(rt,'ensure_service',side_effect=gate_error), \
             patch('builtins.input',side_effect=answers or []),patch.object(rt,'run') as run, \
             patch.object(rt,'signed_probe') as probe:
            result=rt.main();run.assert_not_called();probe.assert_not_called();return result
    def answers(self,action):
        return ['OFF-HOST-RESTORE-VERIFIED '+self.digest,action.upper()+'-RC7-WSS-IR']
    def test_cli_recovery_repeat_and_rollback_preserve_fingerprints(self):
        for action in ('signature-recover','signature-recover','signature-rollback'):
            self.assertEqual(self.cli(action,self.answers(action)),0)
            for name in self.doc['services']:
                self.assertEqual(rt.record()['baseline'][name]['signature'],self.doc['baseline'][name]['signature'])
        self.assertEqual(rt.record(),self.doc)
        self.assertEqual(self.backup.read_bytes(),self.raw)
    def test_cancel_and_fake_snapshot_flags_do_not_mutate(self):
        for answers in (['no'],['OFF-HOST-RESTORE-VERIFIED '+self.digest,'no']):
            self.assertEqual(self.cli('signature-recover',answers),2)
            self.assertEqual(self.record.read_bytes(),self.raw)
        self.assertEqual(self.cli('signature-recover',extra=['--snapshot-confirm','SNAPSHOTS-CONSOLES-VERIFIED']),2)
        self.assertEqual(self.record.read_bytes(),self.raw)
    def test_invalid_backup_restore_failure_and_runtime_drift_never_commit(self):
        self.backup.write_bytes(b'corrupt')
        self.assertEqual(self.cli('signature-recover'),2)
        self.backup.write_bytes(self.raw)
        with patch.object(rt,'atomic_new',side_effect=OSError('restore failed')):
            self.assertEqual(self.cli('signature-recover'),2)
        self.assertEqual(self.cli('signature-recover',gate_error=rt.Hold('WSS_RUNTIME_SECURITY_DRIFT')),2)
        self.assertEqual(self.record.read_bytes(),self.raw)
    def test_eof_cancellation_preserves_journal(self):
        self.assertEqual(self.cli('signature-recover',answers=[EOFError()]),2)
        self.assertEqual(self.record.read_bytes(),self.raw)
    def test_untrusted_owner_and_writable_directory_are_rejected(self):
        original_fstat=os.fstat
        def untrusted(fd):
            result=original_fstat(fd)
            if stat.S_ISREG(result.st_mode):
                values=list(result);values[4]=65534
                return os.stat_result(values)
            return result
        with patch.object(rt.os,'fstat',side_effect=untrusted),self.assertRaises(rt.Hold):self.proof()
        self.root.chmod(0o777)
        with self.assertRaises(rt.Hold):self.proof()
        self.root.chmod(0o700)

    def test_backup_changed_during_confirmation_blocks_commit(self):
        answers=iter(self.answers('signature-recover'))
        def confirm(prompt):
            self.backup.write_bytes(b'changed during consent')
            return next(answers)
        with patch('sys.argv',['runtime','signature-recover','--role','ir','--recovery-backup',str(self.backup),'--backup-sha256',self.digest]), \
             patch.object(rt,'recovery_console'),patch.object(rt,'check_protected'), \
             patch.object(rt,'ensure_service'),patch('builtins.input',side_effect=confirm):
            self.assertEqual(rt.main(),2)
        self.assertEqual(self.record.read_bytes(),self.raw)

    def test_alternative_cannot_authorize_other_actions(self):
        for action in ('apply','rollback','recover','plan','verify','signature-check'):
            self.assertEqual(self.cli(action),2)
        self.assertEqual(self.record.read_bytes(),self.raw)
    def test_incomplete_arguments_block(self):
        for option,value in (('--recovery-backup',str(self.backup)),('--backup-sha256',self.digest)):
            with patch('sys.argv',['runtime','signature-recover','--role','ir',option,value]),patch.object(rt,'atomic_record') as write:
                self.assertEqual(rt.main(),2);write.assert_not_called()
    def test_interrupted_record_and_runtime_drift_block_commit(self):
        (self.state/'record.next').write_text('interrupted')
        self.assertEqual(self.cli('signature-recover'),2)
        (self.state/'record.next').unlink()
        with patch('sys.argv',['runtime','signature-recover','--role','ir','--recovery-backup',str(self.backup),'--backup-sha256',self.digest]), \
             patch.object(rt,'recovery_console'),patch.object(rt,'check_protected',side_effect=rt.Hold('PROTECTED_CONFIG_OR_IDENTITY_DRIFT')), \
             patch.object(rt,'atomic_record') as write:
            self.assertEqual(rt.main(),2);write.assert_not_called()
        self.assertEqual(self.record.read_bytes(),self.raw)

class ConsoleTests(unittest.TestCase):
    def test_only_direct_foreground_console_passes(self):
        with patch.dict(os.environ,{},clear=True),patch.object(rt.sys.stdin,'isatty',return_value=True), \
             patch.object(rt.sys.stdout,'isatty',return_value=True),patch.object(rt.os,'tcgetpgrp',return_value=12), \
             patch.object(rt.os,'getpgrp',return_value=12),patch.object(rt.os,'fstat',return_value=SimpleNamespace(st_rdev=5)):
            for name in ('/dev/tty1','/dev/ttyS0','/dev/hvc0','/dev/ttyAMA0'):
                with patch.object(rt.os,'ttyname',return_value=name):rt.recovery_console()
            for name in ('/dev/pts/0','/dev/tty','/tmp/tty1'):
                with patch.object(rt.os,'ttyname',return_value=name),self.assertRaises(rt.Hold):rt.recovery_console()
            with patch.dict(os.environ,{'SSH_CONNECTION':'remote'}),self.assertRaises(rt.Hold):rt.recovery_console()
            with patch.object(rt.os,'ttyname',return_value='/dev/tty1'),patch.object(rt.os,'tcgetpgrp',return_value=99),self.assertRaises(rt.Hold):rt.recovery_console()
    def test_noninteractive_denied(self):
        with patch.object(rt.sys.stdin,'isatty',return_value=False),self.assertRaises(rt.Hold):rt.recovery_console()

if __name__=='__main__':unittest.main(verbosity=2)
