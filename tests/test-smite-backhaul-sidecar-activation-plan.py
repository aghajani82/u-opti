#!/usr/bin/env python3
"""Offline-only regression tests: deployment blueprint does not install anything."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/"modules"/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

plan=load("uopti_test_activation","smite-backhaul-sidecar-activation-plan.py")
preflight=load("uopti_test_evidence","smite-backhaul-sidecar-preflight.py")
builder=load("uopti_test_stage_builder","smite-backhaul-sidecar.py")


def synthetic_snapshot(role, now):
    listeners=(
        [{"address":"0.0.0.0","port":443,"owner":"nginx"},
         {"address":"127.0.0.1","port":8443,"owner":"nginx"},
         {"address":"127.0.0.1","port":7000,"owner":"frps"}]
        if role=="ir" else
        [{"address":"127.0.0.1","port":56053,"owner":"xray"}]
    )
    return {
        "role":role,"observed_at":now.isoformat(),
        "ports":{"role":role,"network_mode":"host","listeners":listeners},
        "checks":{k:True for k in preflight.EXPECTED[role]},
        "versions":{"backhaul":"v0.7.2","smite":"v0.1.7"},
        "baseline":{"legacy_clients":0 if role=="ir" else 4},
    }

def synthetic_backups(role):
    return {
        "role":role,"copies":[
            {"label":name,"path":path,"observed_sha256":c*64,
             "backup_sha256":c*64,"verified_independently":True}
            for c,(name,path) in zip("abcde",plan.BACKUPS[role].items())
        ],
    }

class DeploymentBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,13,9,0,tzinfo=timezone.utc)
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token=Path(self.tmp.name)/"private_token"
        self.secret="ABCD"*12
        token.write_text(self.secret+"\n")
        token.chmod(0o600)
        self.ir_path=builder.prepare("ir",token,"ir.kolbe1.ir","kh.kolbe1.ir")
        self.kh_path=builder.prepare("kh",token,"ir.kolbe1.ir","kh.kolbe1.ir")
        self.addCleanup(lambda:shutil.rmtree(self.ir_path))
        self.addCleanup(lambda:shutil.rmtree(self.kh_path))
        self.ir=plan.private_stage(self.ir_path,"ir")
        self.kh=plan.private_stage(self.kh_path,"kh")
        self.ir_e=synthetic_snapshot("ir",self.now)
        self.kh_e=synthetic_snapshot("kh",self.now)
        self.ir_b=synthetic_backups("ir")
        self.kh_b=synthetic_backups("kh")

    def compile(self,**kw):
        options={
            "ir_evidence":self.ir_e,"kh_evidence":self.kh_e,
            "ir":self.ir,"kh":self.kh,
            "ir_backups":self.ir_b,"kh_backups":self.kh_b,"now":self.now,
        }
        options.update(kw)
        return plan.plan(**options)

    def test_complete_synthetic_evidence_is_review_only_not_approval(self):
        result=self.compile()
        self.assertEqual(result["state"],"REVIEW_ONLY_NO_DEPLOYMENT_AUTHORIZATION")
        self.assertIs(result["has_execution_actions"],False)
        self.assertIs(result["authorized_for_production"],False)
        self.assertIn("No production installer",result["unresolved_blockers"][0])
        self.assertEqual(set(result["file_hashes"]["ir"]),set(plan.ASSIGN["ir"]))
        self.assertEqual(set(result["file_hashes"]["kh"]),set(plan.ASSIGN["kh"]))
        data=json.dumps(result)
        self.assertNotIn(self.secret,data)
        self.assertNotIn("token =",data)
        self.assertEqual(len(result["manual_sequence"]),10)

    def test_actual_collector_style_unknown_evidence_blocks(self):
        source=synthetic_snapshot("ir",self.now)
        source["checks"]["tls_certificate_valid"]=None
        with self.assertRaisesRegex(plan.PlanBlocked,"Preflight"):
            self.compile(ir_evidence=source)
        source=synthetic_snapshot("kh",self.now)
        source["versions"]["backhaul"]=None
        with self.assertRaisesRegex(plan.PlanBlocked,"Preflight"):
            self.compile(kh_evidence=source)

    def test_conflict_stale_and_legacy_change_block(self):
        e=synthetic_snapshot("kh",self.now)
        e["ports"]["listeners"].append(
            {"address":"::","port":13080,"owner":"other"}
        )
        with self.assertRaises(plan.PlanBlocked):
            self.compile(kh_evidence=e)
        e=synthetic_snapshot("kh",self.now)
        e["baseline"]["legacy_clients"]=3
        with self.assertRaises(plan.PlanBlocked):
            self.compile(kh_evidence=e)

    def test_backup_mismatch_incomplete_unknown_and_unverified_fail(self):
        for role in ("ir","kh"):
            cases=("mismatch","unknown","missing","unverified","duplicate")
            for scenario in cases:
                with self.subTest(role=role,scenario=scenario):
                    backup=json.loads(json.dumps(synthetic_backups(role)))
                    if scenario=="mismatch":
                        backup["copies"][0]["backup_sha256"]="f"*64
                    elif scenario=="unknown":
                        backup["copies"][0]["path"]="/etc/smite-node/config.toml"
                    elif scenario=="missing":
                        backup["copies"].pop()
                    elif scenario=="unverified":
                        backup["copies"][0]["verified_independently"]=False
                    elif scenario=="duplicate":
                        backup["copies"].append(backup["copies"][0])
                    arg="ir_backups" if role=="ir" else "kh_backups"
                    with self.assertRaises(plan.PlanBlocked):
                        self.compile(**{arg:backup})

    def test_token_mismatch_loopback_hardening_and_nginx_regressions(self):
        changes=[
            ("ir","ir.toml",b'skip_optz = true',b'skip_optz = false'),
            ("ir","ir.toml",b'127.0.0.1:3080',b'0.0.0.0:3080'),
            ("kh","kh.toml",self.secret.encode(),b"DIFFERENT"*6),
            ("ir","ir-control.inc",b'location ^~ /tunnel/ {',
             b'location = /tunnel {'),
            ("kh","kh-bridge.conf",b'proxy_ssl_verify on;',
             b'proxy_ssl_verify off;'),
            ("kh","compose.candidate.yaml",b'cap_drop: [ALL]',
             b'cap_drop: []'),
        ]
        for role,filename,old,new in changes:
            with self.subTest(role=role,file=filename):
                blob=dict(self.ir if role=="ir" else self.kh)
                self.assertIn(old,blob[filename])
                blob[filename]=blob[filename].replace(old,new)
                with self.assertRaises(plan.PlanBlocked):
                    self.compile(**{role:blob})

    def test_private_stage_rejects_world_readable_and_symlinked_files(self):
        file=self.ir_path/"ir.toml"
        file.chmod(0o644)
        with self.assertRaises(plan.PlanBlocked):
            plan.private_stage(self.ir_path,"ir")
        file.chmod(0o600)
        copy=self.ir_path/"ir.toml.backup"
        copy.symlink_to(file)
        with self.assertRaises(plan.PlanBlocked):
            plan.private_stage(self.ir_path,"ir")

    def test_cli_only_prints_hashes_and_review_state(self):
        records={
            "ir-evidence":self.ir_e,"kh-evidence":self.kh_e,
            "ir-backups":self.ir_b,"kh-backups":self.kh_b,
        }
        argv=[sys.executable,str(ROOT/"modules"/"smite-backhaul-sidecar-activation-plan.py"),
              "--ir-stage",str(self.ir_path),"--kh-stage",str(self.kh_path)]
        for name,obj in records.items():
            path=Path(self.tmp.name)/(name+".json")
            path.write_text(json.dumps(obj))
            path.chmod(0o600)
            argv.extend(("--"+name,str(path)))
        # Test fresh timestamp for the real CLI clock.
        now=datetime.now(timezone.utc)
        for name in ("ir-evidence","kh-evidence"):
            path=Path(self.tmp.name)/(name+".json")
            obj=json.loads(path.read_text())
            obj["observed_at"]=now.isoformat()
            path.write_text(json.dumps(obj))
        result=subprocess.run(argv,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("REVIEW_ONLY_NO_DEPLOYMENT_AUTHORIZATION",result.stdout)
        self.assertIn("NO HOST ACTION PERFORMED",result.stderr)
        self.assertNotIn(self.secret,result.stdout+result.stderr)

if __name__=="__main__":
    unittest.main()
