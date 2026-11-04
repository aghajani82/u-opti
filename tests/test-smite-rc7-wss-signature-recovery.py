#!/usr/bin/env python3
"""No live hosts: bounded DNS normalization and atomic journal recovery."""
import copy
import importlib.util
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('runtime',ROOT/'modules/smite-rc7-wss-runtime.py')
rt=importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)

def obj():
    return {'Config':{'Image':'sha256:approved','Env':['SECRET=private'],
                      'Cmd':['uvicorn'],'Entrypoint':None},
            'HostConfig':{'NetworkMode':'host','Privileged':False,
                          'Dns':None,'DnsOptions':None,'DnsSearch':None,
                          'RestartPolicy':{'Name':'unless-stopped','MaximumRetryCount':0}},
            'Mounts':[{'Type':'bind','Source':'/safe','Destination':'/safe','RW':False}]}

class Recovery(unittest.TestCase):
    def test_all_daemon_reload_dns_combinations_original_digest_retained(self):
        for before in itertools.product((None,[]),repeat=3):
            for after in itertools.product((None,[]),repeat=3):
                a=obj(); a['HostConfig'].update(zip(rt.DNS_EMPTY_FIELDS,before))
                b=obj(); b['HostConfig'].update(zip(rt.DNS_EMPTY_FIELDS,after))
                signature=rt.runtime_signature(a)
                base={'signature':signature,'signature_policy':rt.DNS_EMPTY_POLICY}
                rt.check_runtime_signature(b,base)
                self.assertEqual(base['signature'],signature)
                self.assertEqual(rt.runtime_signature(a,canonical_dns=True),
                                 rt.runtime_signature(b,canonical_dns=True))

    def test_legacy_is_strict_until_explicit_opt_in(self):
        a=obj(); baseline={'signature':rt.runtime_signature(a)}
        a['HostConfig']['Dns']=[]
        with self.assertRaisesRegex(rt.Hold,'WSS_RUNTIME_SECURITY_DRIFT'):
            rt.check_runtime_signature(a,baseline)
        self.assertTrue(rt.legacy_dns_proof(a,baseline['signature']))

    def test_ir_committed_legacy_trial_matches_only_original_dns_empty_permutations(self):
        # This uses the original SHA. No journal or policy field is rewritten.
        for before in itertools.product((None,[]),repeat=3):
            for after in itertools.product((None,[]),repeat=3):
                original=obj(); original['HostConfig'].update(zip(rt.DNS_EMPTY_FIELDS,before))
                live=obj(); live['HostConfig'].update(zip(rt.DNS_EMPTY_FIELDS,after))
                signature=rt.runtime_signature(original)
                baseline={'signature':signature}
                rt.check_runtime_signature(live,baseline,allow_legacy_ir_dns_proof=True)
                self.assertEqual(baseline,{'signature':signature})

    def test_ir_legacy_dns_trial_rejects_every_other_drift(self):
        original=obj()
        original_sig=rt.runtime_signature(original)
        baseline={'signature':original_sig}
        for key,value in (('Privileged',True),('CapAdd',['SYS_ADMIN']),
                          ('SecurityOpt',['seccomp=unconfined']),('NetworkMode','bridge'),
                          ('UnknownDockerField',None),('ReadonlyRootfs',True),
                          ('RestartPolicy',{'Name':'always','MaximumRetryCount':0}),
                          ('Dns',['1.1.1.1']),('DnsSearch',['evil']),
                          ('DnsOptions',['ndots:5']),('Binds',['/etc:/etc:rw'])):
            live=copy.deepcopy(original)
            live['HostConfig']['Dns']=[]
            live['HostConfig'][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(rt.Hold,'WSS_RUNTIME_SECURITY_DRIFT'):
                rt.check_runtime_signature(live,baseline,allow_legacy_ir_dns_proof=True)
        for mutate in (lambda o:o['Config'].update(Image='other'),
                       lambda o:o['Config'].update(Env=['SECRET=changed']),
                       lambda o:o['Config'].update(Cmd=['sh']),
                       lambda o:o['Mounts'][0].update(RW=True),
                       lambda o:o['HostConfig'].pop('Dns')):
            live=copy.deepcopy(original)
            live['HostConfig']['Dns']=[]
            mutate(live)
            with self.assertRaises(rt.Hold):
                rt.check_runtime_signature(live,baseline,allow_legacy_ir_dns_proof=True)
        with self.assertRaisesRegex(rt.Hold,'UNKNOWN_RUNTIME_SIGNATURE_POLICY'):
            rt.check_runtime_signature(original,dict(baseline,signature_policy='unexpected'),
                                       allow_legacy_ir_dns_proof=True)

    def test_ir_only_committed_scope_is_passed_from_service_gate(self):
        # Ensure the bypass is NOT routed into foreign or incomplete WSS journals.
        source=obj()
        source['Config']['Env'].append('SMITE_FRP_STANDARD_WSS=1')
        source['Config']['Labels']={
            'com.docker.compose.project.config_files':'/config,'+str(rt.overlay_path('smite-panel'))
        }
        digest=rt.runtime_signature(source)
        live=copy.deepcopy(source);live['HostConfig']['Dns']=[]
        common={'domain':'ir.example.test','project':'trial','baseline':{'smite-panel':{'files':['/config'],
                                                        'signature':digest}}}
        with patch.object(rt,'inspect_container',return_value=live), \\
             patch.object(rt.p,'runtime_env',return_value={'SMITE_FRP_STANDARD_WSS':'1','SECRET':'private'}), \\
             patch.object(rt.p,'service_gate'), \\
             patch.object(rt.p,'compose_files',return_value=('trial',['/config'])):
            for role,state,should_pass in [('ir','COMMITTED',True),
                                           ('ir','PREPARED',False),
                                           ('foreign','COMMITTED',False)]:
                doc=dict(common,role=role,state=state)
                if should_pass:
                    rt.ensure_service('smite-panel',doc,enabled=True)
                else:
                    with self.assertRaisesRegex(rt.Hold,'WSS_RUNTIME_SECURITY_DRIFT'):
                        rt.ensure_service('smite-panel',doc,enabled=True)

    def test_negative_security_unknown_and_nonempty_dns_changes(self):
        a=obj(); base={'signature':rt.runtime_signature(a),'signature_policy':rt.DNS_EMPTY_POLICY}
        for key,value in [('Privileged',True),('CapAdd',['SYS_ADMIN']),
                          ('SecurityOpt',['seccomp=unconfined']),('NetworkMode','bridge'),
                          ('UnknownDockerField',None),('ReadonlyRootfs',True),
                          ('RestartPolicy',{'Name':'always','MaximumRetryCount':0}),
                          ('Dns',['1.1.1.1']),('DnsSearch',['evil']),('DnsOptions',['ndots:5']),
                          ('Binds',['/etc:/etc:rw']),('Devices',[{'PathOnHost':'/dev/mem'}])]:
            b=copy.deepcopy(a); b['HostConfig']['Dns']=[]; b['HostConfig'][key]=value
            with self.subTest(key=key),self.assertRaises(rt.Hold):
                rt.check_runtime_signature(b,base)
        for mutate in (lambda x:x['Config'].update(Image='other'),
                       lambda x:x['Config'].update(Env=['SECRET=changed']),
                       lambda x:x['Config'].update(Cmd=['sh']),
                       lambda x:x['Mounts'][0].update(RW=True),
                       lambda x:x['HostConfig'].pop('Dns')):
            b=copy.deepcopy(a); mutate(b)
            with self.assertRaises(rt.Hold):rt.check_runtime_signature(b,base)
        with self.assertRaisesRegex(rt.Hold,'UNKNOWN_RUNTIME_SIGNATURE_POLICY'):
            rt.check_runtime_signature(a,dict(base,signature_policy='future'))

    def test_restart_state_does_not_affect_signature(self):
        a=obj(); signature=rt.runtime_signature(a)
        a.update(State={'Pid':999,'StartedAt':'after-reboot'},RestartCount=10)
        self.assertEqual(signature,rt.runtime_signature(a))

    def test_recovery_check_commit_repeat_rollback_and_interrupted_write(self):
        a=obj(); sig=rt.runtime_signature(a); a['HostConfig']['Dns']=[]
        doc={'schema':1,'role':'ir','state':'COMMITTED','services':['smite-panel','smite-node'],
             'baseline':{name:{'signature':sig} for name in ('smite-panel','smite-node')}}
        def gate(name,document,**kwargs): rt.check_runtime_signature(a,document['baseline'][name])
        with tempfile.TemporaryDirectory() as tmp,patch.object(rt,'STATE',Path(tmp)), \
             patch.object(rt,'check_protected'),patch.object(rt,'ensure_service',side_effect=gate), \
             patch.object(rt,'run') as run,patch.object(rt,'signed_probe') as probe:
            rt.atomic_record(doc); before=(Path(tmp)/'record.json').read_bytes()
            rt.signature_recovery(doc)
            self.assertEqual(before,(Path(tmp)/'record.json').read_bytes())
            rt.signature_recovery(doc,commit=True)
            recovered=rt.record()
            self.assertEqual(recovered['baseline']['smite-node']['signature'],sig)
            rt.signature_recovery(recovered,commit=True)
            rt.signature_recovery(recovered,commit=True,rollback=True)
            self.assertEqual(rt.record(),doc)
            (Path(tmp)/'record.next').write_text('interrupted')
            with self.assertRaisesRegex(rt.Hold,'PARTIAL_RECORD_NEEDS_REVIEW'):
                rt.signature_recovery(doc,commit=True)
            self.assertEqual(rt.record(),doc)
            run.assert_not_called(); probe.assert_not_called()

    def test_one_failed_service_prevents_all_journal_writes(self):
        doc={'state':'COMMITTED','services':['smite-panel','smite-node'],
             'baseline':{name:{'signature':'a'*64} for name in ('smite-panel','smite-node')}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(rt,'STATE',Path(tmp)), \
             patch.object(rt,'check_protected'),patch.object(rt,'atomic_record') as write, \
             patch.object(rt,'ensure_service',side_effect=[None,rt.Hold('WSS_RUNTIME_SECURITY_DRIFT')]):
            with self.assertRaises(rt.Hold):rt.signature_recovery(doc,commit=True)
            write.assert_not_called()

    def test_cli_mutations_require_tty(self):
        for action in ('signature-recover','signature-rollback'):
            with patch('sys.argv',['runtime',action,'--role','ir']), \
                 patch.object(rt.sys.stdin,'isatty',return_value=False), \
                 patch.object(rt,'signature_recovery') as recover:
                self.assertEqual(rt.main(),2); recover.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)
