#!/usr/bin/env python3
"""Offline IR/KH pairing report review. No network, Docker or host changes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"modules/smite-managed-backhaul-pair-review.py"
spec=importlib.util.spec_from_file_location("bh_pair_review_test",SOURCE)
pair=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pair)


def report(role, *, status="PASS_LOCAL_ONLY_INCOMPLETE",
           tunnels="ZERO", image="REVIEWED_DIGEST_UNATTESTED"):
    return {
        "NODE_ROLE":role,
        "LOCAL_CORE":"MANAGED_STRICT",
        "DOCKER_NODE":"RUNNING_REVIEWED_IMAGE",
        "PERSISTENT_DATA":"LOCAL_NAMED_VOLUME_CONFIRMED",
        "PERSISTED_TUNNELS":tunnels,
        "DISK_SPACE":"MINIMUM_AVAILABLE",
        "ENGINE":"BACKHAUL_ONLY",
        "FRP_INSTALL_REQUIRED":"NO",
        "NEW_PUBLIC_PORTS":"NONE_PLANNED",
        "SNAPSHOT_AND_CONSOLE":pair.NO_PROOF,
        "SIGNED_NODE_POST_RESTART":pair.NO_PROOF,
        "PAIRING_AND_REPLAY_PRESERVATION":pair.NO_PROOF,
        "NGINX_443_AND_FIREWALL_EXPOSURE":pair.NO_PROOF,
        "TUNNEL_RECOVERY_AFTER_RESTART":pair.NO_PROOF,
        "HOST_INSTALL_AUTHORIZED":"NO",
        "HOST_PREFLIGHT":status,
        "BACKHAUL_ACTIVATION_GATE":"HOLD",
        "COMPOSE_SHA256":"a"*64,
        "IMAGE_REFERENCE_CLASS":image,
    }


class PairReview(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.ir=report("IR")
        self.kh=report("KH")
        self.irpath=self.root/"ir.json"
        self.khpath=self.root/"kh.json"

    def save(self):
        self.irpath.write_text(json.dumps(self.ir))
        self.khpath.write_text(json.dumps(self.kh))

    def test_matching_trusted_shape_never_unblocks_host(self):
        self.save()
        a=pair.compare(pair.read_report(self.irpath),pair.read_report(self.khpath))
        self.assertEqual(a["IR_LOCAL_PREFLIGHT"],"PASS_LOCAL_ONLY")
        self.assertEqual(a["KH_LOCAL_PREFLIGHT"],"PASS_LOCAL_ONLY")
        self.assertEqual(a["HOST_INSTALL_AUTHORIZED"],"NO")
        self.assertEqual(a["BACKHAUL_ACTIVATION_GATE"],"HOLD")
        self.assertEqual(a["REPORT_TRUST"],"USER_SUPPLIED_UNAUTHENTICATED")
        self.assertEqual(a["NEXT"],"SNAPSHOT_CONSOLE_AND_SIGNED_443_UNVERIFIED")
        self.assertNotIn("READY_TO_INSTALL",str(a))

    def test_cli_is_nonzero_even_with_clean_pair(self):
        self.save()
        proc=subprocess.run([
            sys.executable,"-B",str(SOURCE),
            "--ir-report",str(self.irpath),"--kh-report",str(self.khpath),
        ],capture_output=True,text=True,timeout=10)
        self.assertEqual(proc.returncode,2)
        self.assertIn("IR_LOCAL_PREFLIGHT=PASS_LOCAL_ONLY",proc.stdout)
        self.assertIn("HOST_INSTALL_AUTHORIZED=NO",proc.stdout)

    def test_saved_tunnel_on_either_side_means_no_restart(self):
        self.kh["PERSISTED_TUNNELS"]="EXISTING_DO_NOT_RESTART"
        self.kh["HOST_PREFLIGHT"]="HOLD_EXISTING_TUNNELS"
        self.save()
        r=pair.compare(pair.read_report(self.irpath),pair.read_report(self.khpath))
        self.assertEqual(r["IR_LOCAL_PREFLIGHT"],"PASS_LOCAL_ONLY")
        self.assertEqual(r["KH_LOCAL_PREFLIGHT"],"HOLD")
        self.assertEqual(r["NEXT"],"EXISTING_TUNNELS_NO_RESTART")
        self.assertEqual(r["HOST_INSTALL_AUTHORIZED"],"NO")

    def test_role_mismatch_is_denied(self):
        self.kh["NODE_ROLE"]="IR"
        self.save()
        with self.assertRaisesRegex(pair.Hold,"WRONG_NODE_PAIR_ROLES"):
            pair.compare(pair.read_report(self.irpath),pair.read_report(self.khpath))

    def test_snapshot_and_443_claims_cannot_be_forged(self):
        for key in ["SNAPSHOT_AND_CONSOLE","NGINX_443_AND_FIREWALL_EXPOSURE",
                    "SIGNED_NODE_POST_RESTART"]:
            with self.subTest(key=key):
                self.ir[key]="VERIFIED"
                self.save()
                with self.assertRaisesRegex(pair.Hold,"UNTRUSTED_APPROVAL_CLAIM"):
                    pair.read_report(self.irpath)
                self.ir[key]=pair.NO_PROOF

    def test_unexpected_secret_fields_do_not_appear_in_error(self):
        self.ir["NODE_SECRET"]="SYNTHETIC_NOT_FOR_LOGS"
        self.save()
        with self.assertRaisesRegex(pair.Hold,"UNEXPECTED_REPORT_FIELDS"):
            pair.read_report(self.irpath)
        proc=subprocess.run([
            sys.executable,str(SOURCE),"--ir-report",str(self.irpath),
            "--kh-report",str(self.khpath)
        ],capture_output=True,text=True,timeout=10)
        self.assertEqual(proc.returncode,2)
        self.assertNotIn("SYNTHETIC_NOT_FOR_LOGS",proc.stderr+proc.stdout)
        self.assertIn("HOST_INSTALL_AUTHORIZED=NO",proc.stdout)

    def test_corruption_symlink_and_oversized_report_hold(self):
        self.save()
        self.irpath.write_text("{invalid")
        with self.assertRaises(pair.Hold):pair.read_report(self.irpath)
        self.irpath.unlink()
        self.irpath.symlink_to(self.khpath)
        with self.assertRaisesRegex(pair.Hold,"REPORT_SYMLINK"):
            pair.read_report(self.irpath)
        self.irpath.unlink()
        self.irpath.write_text("x"*9000)
        with self.assertRaisesRegex(pair.Hold,"INVALID_REPORT_FILE"):
            pair.read_report(self.irpath)

    def test_dynamic_image_tag_not_considered_reviewed_attestation(self):
        self.ir["IMAGE_REFERENCE_CLASS"]="LOCAL_TAG_UNATTESTED"
        self.save()
        r=pair.compare(pair.read_report(self.irpath),pair.read_report(self.khpath))
        self.assertEqual(r["IR_LOCAL_PREFLIGHT"],"HOLD")
        self.assertEqual(r["KH_LOCAL_PREFLIGHT"],"PASS_LOCAL_ONLY")
        self.assertEqual(r["NEXT"],"LOCAL_EVIDENCE_INCOMPLETE")

    def test_no_executor_ssh_or_network(self):
        script=SOURCE.read_text()
        for banned in ("subprocess", "docker inspect", "docker compose",
                       "os.system(", "requests.", "socket.", "urlopen("):
            self.assertNotIn(banned,script)


if __name__=="__main__":
    unittest.main(verbosity=2)
