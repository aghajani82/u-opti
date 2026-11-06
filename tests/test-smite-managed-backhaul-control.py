#!/usr/bin/env python3
"""Read-only Backhaul operator review plus CI-only transaction admission."""
from __future__ import annotations
import importlib.util
import json
import hashlib
import contextlib
from types import SimpleNamespace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "modules/smite-managed-backhaul-control.py"
MENU = ROOT / "modules/smite-managed-backhaul-menu.sh"

spec = importlib.util.spec_from_file_location("uopti_bh_control_test", FILE)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)

COMPOSE = """services:
  smite-node:
    image: smite-node:stage15-local
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
"""
ENV = """NODE_ROLE=foreign
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
"""


class OperatorControl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="uopti-bh-operator-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.node = self.root / "node"
        self.node.mkdir(mode=0o700)
        (self.node / "config").mkdir(mode=0o700)
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)

    def run_control(self, action: str, *args):
        return subprocess.run(
            [sys.executable, "-B", str(FILE), action, *map(str, args)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )

    def test_no_engine_is_declared_even_when_binaries_are_bundled(self):
        output = self.run_control("status", "--node-dir", self.node)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertIn("ROLE=KH", output.stdout)
        self.assertIn("STATE=NOT_INSTALLED", output.stdout)
        self.assertIn("SIGNED_NODE_STATUS=NOT_QUERIED", output.stdout)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_review_refuses_real_install_and_never_requests_frp_or_ports(self):
        output = self.run_control("review", "--node-dir", self.node)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertIn("INSTALL_ALLOWED=NO", output.stdout)
        self.assertIn("FRP_DEPENDENCY=NONE", output.stdout)
        self.assertIn("PORT_OR_TUNNEL_INPUT=NOT_REQUIRED", output.stdout)
        self.assertIn("HOST_DOCKER_ACTIONS=NONE", output.stdout)
        output = self.run_control("install", "--node-dir", self.node)
        self.assertEqual(output.returncode, 2)
        self.assertIn("activation is NOT enabled", output.stderr)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_partial_install_fails_closed_without_silent_ready(self):
        compose = self.node / "docker-compose.yml"
        compose.write_text(COMPOSE + "      - /opt/u-opti/engines/backhaul/v0.7.2/backhaul:/usr/local/bin/backhaul:ro\n")
        state = control.inspect(self.node)
        self.assertEqual(state["state"], "UNAVAILABLE")
        self.assertEqual(state["reason"], "PARTIAL_INSTALL_OR_DRIFT")

    def test_manifest_without_verified_binary_is_unavailable(self):
        state = self.node / "config/engine-state"
        state.mkdir(mode=0o700)
        manifest = state / "engines.json"
        manifest.write_text(json.dumps({
            "schema": 1,
            "engines": {
                "gost": {"sha256": "c" * 64},
                "backhaul": {"sha256": "a" * 64},
            },
        }))
        manifest.chmod(0o600)
        self.assertEqual(control.inspect(self.node)["state"], "UNAVAILABLE")
        self.assertIn("gost", manifest.read_text())
        manifest.chmod(0o644)
        with self.assertRaises(control.package.Hold):
            control.inspect(self.node)

    def test_duplicate_critical_env_or_unsafe_compose_denied(self):
        (self.node / ".env").write_text(ENV + "SMITE_AGENT_AUTH_MODE=legacy\n")
        with self.assertRaises(control.Hold):
            control.inspect(self.node)
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE + "    ports:\n      - 443:443\n")
        with self.assertRaises(control.Hold):
            control.inspect(self.node)

    def test_bogus_archive_candidate_cannot_be_promoted(self):
        stage = self.root / "stage"
        stage.mkdir(mode=0o700)
        with self.assertRaises(control.Hold):
            control.verified_candidate(stage)
        self.assertEqual(self.run_control("verify-stage", "--stage", stage).returncode, 2)

    def test_install_and_rollback_fail_outside_ci(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false", "RUNNER_TEMP": self.tmp.name}):
            with self.assertRaises(control.transaction.Hold):
                control.exercise(self.root, action="install", stage=self.root / "fake-stage")
            with self.assertRaises(control.transaction.Hold):
                control.exercise(self.root, action="rollback")
        self.assertFalse((self.root / ".backhaul-control.lock").exists())
        self.assertFalse((self.node / "config/engine-state").exists())

    def _rc7_bundle_fake(self, *, role="foreign", inventory=None,
                         binary=None, mounts=None, probe_error=None,
                         owner_hashes=None, owner_error=None):
        engines = {name: "not-installed" for name in control.ENGINES}
        engines["frp"] = "ready"
        if inventory is None:
            inventory = {"mode": "managed", "engines": engines}
        if binary is None:
            binary = {"architecture": "amd64",
                      "sha256": control.package.OFFICIAL_BINARY_SHA256["amd64"]}
        calls = []
        def node_details():
            calls.append("runtime")
            return {"role": role}
        def inspect(_name):
            calls.append("mounts")
            return {"Mounts": mounts if mounts is not None else [
                {"Destination": "/etc/smite-node", "Type": "bind"},
                {"Destination": "/var/lib/smite-node", "Type": "volume"},
            ]}
        def hmac():
            calls.append("replay")
            if probe_error:
                raise FakeHold(probe_error)
        def run(argv, *, timeout):
            self.assertEqual(argv[:5], ["docker","exec","smite-node","python3","-B"])
            self.assertEqual(timeout, 30)
            if "os.lstat(path)" in argv[-1]:
                calls.append("binary")
                return binary if isinstance(binary,str) else json.dumps(binary)
            self.assertIn("target='/api/agent/engines'",argv[-1])
            calls.append("signed-inventory")
            return inventory if isinstance(inventory,str) else json.dumps(inventory)
        class FakeHold(Exception):
            pass
        rt = SimpleNamespace(
            Hold=FakeHold, locked=lambda:contextlib.nullcontext(),
            inspect_container=inspect, signed_probe=hmac, run=run,
        )
        manifest, receipt = self.rc7_manifest_pair_fixture()
        receipt["role"] = role
        manifest_path = Path("/opt/smite-node/config/engine-state/engines.json")
        journal_dir = Path("/var/lib/u-opti/smite-rc7-frp-enrollment")
        receipt_bytes = (json.dumps(receipt, sort_keys=True) + "\n").encode()
        def private(path):
            if path == manifest_path:
                calls.append("manifest-read")
                return manifest
            if path == journal_dir / "record.json":
                calls.append("receipt-read")
                return receipt_bytes
            raise AssertionError("Unexpected private file access")
        def state():
            calls.append("receipt-state")
            return dict(receipt)
        def verify_file(parsed):
            calls.append("frp-verify")
            self.assertEqual(parsed, receipt)
        signed_owner_values = (["d" * 64, "d" * 64]
                               if owner_hashes is None else owner_hashes)
        def signed_owner_inventory():
            calls.append("signed-owner")
            if owner_error is not None:
                raise FakeHold(owner_error)
            index = calls.count("signed-owner") - 1
            return signed_owner_values[min(index, len(signed_owner_values) - 1)]
        fake = SimpleNamespace(
            Hold=FakeHold, rt=rt, node_details=node_details,
            MANIFEST=manifest_path, JOURNAL=journal_dir,
            read_private=private, state=state, verify_file=verify_file,
            signed_owner_inventory=signed_owner_inventory,
        )
        return fake,calls

    def test_rc7_bundled_signed_inventory_no_recreate_and_not_ready_yet(self):
        fake,calls = self._rc7_bundle_fake()
        with patch.object(control.os,"geteuid",return_value=0), \
             patch.object(control,"_load",return_value=fake):
            status=control.verify_rc7_bundled_backhaul("foreign")
        self.assertEqual(calls,["runtime","mounts","replay","binary",
                                "signed-inventory","manifest-read","receipt-read",
                                "receipt-state","frp-verify","manifest-read","receipt-read"])
        self.assertEqual(status["RC7_BACKHAUL_BINARY_PIN"],
                         "OFFICIAL_V0_7_2_ARCH_EXACT_MATCH")
        self.assertEqual(status["RC7_FRP_RECEIPT_BINDING"],
                         "COMMITTED_EXACT_MANIFEST_REVIEWED")
        self.assertEqual(status["RC7_BACKHAUL_MANIFEST_PLAN"],
                         "CANDIDATE_ONLY_NO_WRITE")
        self.assertEqual(status["RC7_BACKHAUL_IMAGE_BINARY"],
                         "OBSERVED_PINNED_IMAGE_NO_MOUNT")
        self.assertEqual(status["RC7_BACKHAUL_ENGINE"],
                         "NOT_INSTALLED_SIGNED_INVENTORY")
        self.assertEqual(status["RC7_FRP_ENGINE"],"READY_SIGNED_INVENTORY")
        self.assertEqual(status["NODE_RECREATED"],"NO")
        self.assertEqual(status["INSTALL_ALLOWED"],"NO")
        self.assertEqual(status["ACTIVATION_GATE"],"HOLD")
        self.assertEqual(status["SIGNED_OWNER_CHILD_CONTINUITY"],"NOT_PROVEN")
        self.assertNotIn("a"*64,str(status))
        self.assertNotIn("Docker",str(status))

    def test_rc7_ir_owner_is_checked_twice_by_existing_signed_endpoint(self):
        fake,calls = self._rc7_bundle_fake(role="ir")
        with patch.object(control.os, "geteuid", return_value=0), \
             patch.object(control, "_load", return_value=fake):
            status = control.verify_rc7_bundled_backhaul("ir")
        self.assertEqual(calls.count("signed-owner"), 2)
        self.assertLess(calls.index("frp-verify"), calls.index("signed-owner"))
        self.assertEqual(calls[-1], "signed-owner")
        self.assertEqual(status["RC7_IR_SIGNED_FRPS_OWNER"],
                         "PASS_SIGNED_AGENT_LISTENER_STABLE")
        self.assertEqual(status["RC7_FOREIGN_FRPC_CHILD_FORWARDING"], "NOT_PROVEN")
        self.assertEqual(status["SIGNED_OWNER_CHILD_CONTINUITY"], "NOT_PROVEN")
        self.assertEqual(status["INSTALL_ALLOWED"], "NO")
        self.assertEqual(status["ACTIVATION_GATE"], "HOLD")
        self.assertNotIn("d" * 64, str(status))
        fake_foreign,foreign_calls = self._rc7_bundle_fake(role="foreign")
        with patch.object(control.os, "geteuid", return_value=0), \
             patch.object(control, "_load", return_value=fake_foreign):
            foreign_status = control.verify_rc7_bundled_backhaul("foreign")
        self.assertEqual(foreign_calls.count("signed-owner"), 0)
        self.assertEqual(foreign_status["RC7_IR_SIGNED_FRPS_OWNER"],
                         "NOT_APPLICABLE_FOREIGN")
        self.assertEqual(foreign_status["RC7_FOREIGN_FRPC_CHILD_FORWARDING"],
                         "NOT_PROVEN")

    def test_rc7_ir_signed_owner_failure_and_identity_drift_fail_closed(self):
        for settings,expected in (
            ({"owner_error": "PRIVATE_FRPS_OWNER_TOKEN"}, "RC7_BUNDLED_RUNTIME_UNVERIFIED"),
            ({"owner_hashes": ["invalid"]}, "RC7_BUNDLED_OWNER_PROOF_INVALID"),
            ({"owner_hashes": ["a" * 64, "b" * 64]},
             "RC7_BUNDLED_SIGNED_OWNER_CHANGED_DURING_REVIEW"),
            ({"owner_hashes": ["a" * 64, None]},
             "RC7_BUNDLED_SIGNED_OWNER_CHANGED_DURING_REVIEW"),
        ):
            with self.subTest(settings=settings):
                fake,calls = self._rc7_bundle_fake(role="ir", **settings)
                with patch.object(control.os, "geteuid", return_value=0), \
                     patch.object(control, "_load", return_value=fake):
                    with self.assertRaisesRegex(control.Hold, expected) as held:
                        control.verify_rc7_bundled_backhaul("ir")
                self.assertNotIn("PRIVATE_FRPS_OWNER_TOKEN", str(held.exception))
                self.assertIn("signed-owner", calls)
                self.assertNotIn("INSTALL_ALLOWED=YES", str(held.exception))

    def test_rc7_bundle_unsafe_mount_role_and_root_are_hold_before_probe(self):
        for kwargs,reason in (
            ({"role":"ir"}, "RC7_BUNDLED_RUNTIME_ROLE_MISMATCH"),
            ({"mounts":[{"Destination":"/usr/local/bin/backhaul"}]},
             "RC7_BUNDLED_BACKHAUL_EXTERNAL_MOUNT"),
            ({"mounts":[{"Destination":"/usr/local"}]},
             "RC7_BUNDLED_BACKHAUL_EXTERNAL_MOUNT"),
            ({"mounts":[{"Destination":None}]},
             "RC7_BUNDLED_MOUNT_INVENTORY_UNTRUSTED"),
        ):
            with self.subTest(kwargs=kwargs):
                fake,calls = self._rc7_bundle_fake(**kwargs)
                with patch.object(control.os,"geteuid",return_value=0), \
                     patch.object(control,"_load",return_value=fake):
                    with self.assertRaisesRegex(control.Hold,reason):
                        control.verify_rc7_bundled_backhaul("foreign")
                self.assertNotIn("replay",calls)
                self.assertNotIn("binary",calls)
        fake,calls=self._rc7_bundle_fake()
        with patch.object(control.os,"geteuid",return_value=123), \
             patch.object(control,"_load",return_value=fake):
            with self.assertRaisesRegex(control.Hold,"RC7_BUNDLED_ROOT_REQUIRED"):
                control.verify_rc7_bundled_backhaul("foreign")
        self.assertEqual(calls,[])

    def test_rc7_bundle_wrong_signed_inventory_fails_closed(self):
        ready = {name:"not-installed" for name in control.ENGINES}
        ready["frp"]="ready"
        cases = [
            {"mode":"legacy","engines":ready},
            {"mode":"managed","engines":{**ready,"frp":"unavailable"}},
            {"mode":"managed","engines":{**ready,"backhaul":"ready"}},
            {"mode":"managed","engines":{**ready,"backhaul":"unavailable"}},
            {"mode":"managed","engines":{**ready,"frp":True}},
            {"mode":"managed","engines":{**ready,"frp":"ready","unknown":"ready"}},
            {"mode":"managed","engines":{"backhaul":"not-installed"}},
            {"engines":ready},
            '{"mode":"managed","mode":"managed","engines":{}}',
            '{"mode":"managed","engines":{"backhaul":"not-installed","backhaul":"ready"}}',
            "SECRET_USERNAME_TOKEN_NOT_JSON",
        ]
        for state in cases:
            with self.subTest(state=str(state)[:40]):
                fake,calls = self._rc7_bundle_fake(inventory=state)
                with patch.object(control.os,"geteuid",return_value=0), \
                     patch.object(control,"_load",return_value=fake):
                    with self.assertRaises(control.Hold):
                        control.verify_rc7_bundled_backhaul("foreign")
                self.assertEqual(calls,["runtime","mounts","replay",
                                        "binary","signed-inventory"])
        fake,calls=self._rc7_bundle_fake(probe_error="PRIVATE_SECRET")
        with patch.object(control.os,"geteuid",return_value=0), \
             patch.object(control,"_load",return_value=fake):
            with self.assertRaisesRegex(control.Hold,
                                        "RC7_BUNDLED_RUNTIME_UNVERIFIED") as held:
                control.verify_rc7_bundled_backhaul("foreign")
        self.assertNotIn("PRIVATE_SECRET",str(held.exception))
        self.assertEqual(calls,["runtime","mounts","replay"])

    def test_rc7_bundle_refuses_unbound_real_receipt_and_partial_state(self):
        # This is an opt-in, read-only *real path* preflight. A hash claim
        # alone must never bless an FRP receipt unrelated to the Manifest.
        for mutation in ("wrong-hash", "wrong-role", "not-committed",
                         "wrong-frp-pin", "duplicate-json"):
            with self.subTest(mutation=mutation):
                fake,calls = self._rc7_bundle_fake()
                original_read = fake.read_private
                original_state = fake.state
                if mutation == "duplicate-json":
                    def duplicate(path, original_read=original_read):
                        value = original_read(path)
                        if path == fake.JOURNAL / "record.json":
                            return b'{"schema":1,"schema":1}'
                        return value
                    fake.read_private = duplicate
                else:
                    original = original_state()
                    if mutation == "wrong-hash":
                        original["new"] = "e" * 64
                    elif mutation == "wrong-role":
                        original["role"] = "ir"
                    elif mutation == "not-committed":
                        original["state"] = "PREPARED"
                    else:
                        original["binaries"]["frpc"] = "e" * 64
                    raw = (json.dumps(original, sort_keys=True) + "\n").encode()
                    def altered(path, original_read=original_read, raw=raw):
                        if path == fake.JOURNAL / "record.json":
                            return raw
                        return original_read(path)
                    fake.read_private = altered
                    fake.state = lambda original=original: original
                    # The stricter pure planner is the final guard, even
                    # if existing FRP file verification is mocked positive.
                    fake.verify_file = lambda _: None
                with patch.object(control.os,"geteuid",return_value=0), \
                     patch.object(control,"_load",return_value=fake):
                    with self.assertRaises(control.Hold):
                        control.verify_rc7_bundled_backhaul("foreign")
                self.assertNotIn("RC7_BACKHAUL_MANIFEST_PLAN",str(calls))

    def test_rc7_bundle_refuses_out_of_band_receipt_drift_during_review(self):
        fake,calls = self._rc7_bundle_fake()
        original_read = fake.read_private
        count = {"receipt":0}
        def changed(path):
            value = original_read(path)
            if path == fake.JOURNAL / "record.json":
                count["receipt"] += 1
                if count["receipt"] == 2:
                    return value + b"DRIFT"
            return value
        fake.read_private = changed
        with patch.object(control.os,"geteuid",return_value=0), \
             patch.object(control,"_load",return_value=fake):
            with self.assertRaisesRegex(
                    control.Hold,"RC7_BUNDLED_REVIEW_CONCURRENT_DRIFT"):
                control.verify_rc7_bundled_backhaul("foreign")
        self.assertEqual(count["receipt"],2)
        self.assertNotIn("CANDIDATE_ONLY_NO_WRITE",str(calls))

    def test_rc7_bundle_refuses_frp_verifier_failure_without_secret_leak(self):
        fake,calls = self._rc7_bundle_fake()
        def failed(_):
            calls.append("frp-verify")
            raise fake.Hold("PRIVATE_FRP_TOKEN_NOT_FOR_LOGS")
        fake.verify_file = failed
        with patch.object(control.os,"geteuid",return_value=0), \
             patch.object(control,"_load",return_value=fake):
            with self.assertRaisesRegex(
                    control.Hold,"RC7_BUNDLED_RUNTIME_UNVERIFIED") as held:
                control.verify_rc7_bundled_backhaul("foreign")
        self.assertNotIn("PRIVATE_FRP_TOKEN_NOT_FOR_LOGS",str(held.exception))
        self.assertIn("frp-verify", calls)

    def test_rc7_bundle_accepts_only_exact_official_architecture_binary_pin(self):
        # The binary SHA must equal the separately archived official pin;
        # allowing any well-formed hex string would make this preflight weak.
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                trusted = control.package.OFFICIAL_BINARY_SHA256[arch]
                fake,calls = self._rc7_bundle_fake(
                    binary={"architecture": arch, "sha256":trusted})
                with patch.object(control.os, "geteuid", return_value=0), \
                     patch.object(control, "_load", return_value=fake):
                    report=control.verify_rc7_bundled_backhaul("foreign")
                self.assertEqual(report["RC7_BACKHAUL_BINARY_PIN"],
                                 "OFFICIAL_V0_7_2_ARCH_EXACT_MATCH")
                self.assertNotIn(trusted, str(report))
                self.assertEqual(calls.count("frp-verify"),1)

        wrong_sha = "b"*64
        amd64_pin = control.package.OFFICIAL_BINARY_SHA256["amd64"]
        arm64_pin = control.package.OFFICIAL_BINARY_SHA256["arm64"]
        bad = [
            {"architecture":"amd64","sha256":wrong_sha},
            {"architecture":"amd64","sha256":arm64_pin},
            {"architecture":"arm64","sha256":amd64_pin},
        ]
        for binary in bad:
            with self.subTest(binary=binary["architecture"]):
                fake,calls = self._rc7_bundle_fake(binary=binary)
                with patch.object(control.os,"geteuid",return_value=0), \
                     patch.object(control,"_load",return_value=fake):
                    with self.assertRaisesRegex(
                            control.Hold,"RC7_BUNDLED_BINARY_DIGEST_MISMATCH"):
                        control.verify_rc7_bundled_backhaul("foreign")
                self.assertNotIn("manifest-read", calls)
                self.assertNotIn("frp-verify", calls)

    def test_rc7_bundle_binary_architecture_schema_is_fail_closed(self):
        pin = control.package.OFFICIAL_BINARY_SHA256["amd64"]
        for bad_arch in ("x86_64","aarch64","i386","",None,23,True,["amd64"]):
            with self.subTest(arch=str(bad_arch)):
                fake,_=self._rc7_bundle_fake(
                    binary={"architecture":bad_arch,"sha256":pin})
                with patch.object(control.os,"geteuid",return_value=0), \
                     patch.object(control,"_load",return_value=fake):
                    with self.assertRaises(control.Hold):
                        control.verify_rc7_bundled_backhaul("foreign")
        compile(control.RC7_BUNDLED_BACKHAUL_AUDIT,
                "<reviewed-arch-audit>", "exec")
        self.assertIn("platform.machine()",control.RC7_BUNDLED_BACKHAUL_AUDIT)

    def test_rc7_bundle_binary_hash_invalid_or_unsafe_payload_refused(self):
        for blob in (
            {}, {"sha256":""}, {"sha256":"G"*64}, {"sha256":1},
            {"sha256":"a"*64, "token":"DONT_LOG_THIS"},
            '{"sha256":"'+("a"*64)+'","sha256":"'+("b"*64)+'"}',
            "{garbled", "",
        ):
            with self.subTest(blob=str(blob)[:30]):
                fake,_=self._rc7_bundle_fake(binary=blob)
                with patch.object(control.os,"geteuid",return_value=0), \
                     patch.object(control,"_load",return_value=fake):
                    with self.assertRaises(control.Hold):
                        control.verify_rc7_bundled_backhaul("foreign")
        self.assertNotIn("DONT_LOG_THIS",str(control._strict_rc7_response.__doc__))

    @staticmethod
    def rc7_manifest_pair_fixture(*, extra=False):
        one = "1" * 64
        two = "2" * 64
        engines = {
            "frp": {"sha256": one, "server_sha256": two},
        }
        if extra:
            engines["gost"] = {"sha256": "3" * 64}
            engines["rathole"] = {"sha256": "4" * 64}
        raw = (json.dumps({"schema": 1, "engines": engines},
                          sort_keys=True, indent=2) + "\n").encode()
        receipt = {
            "schema": 1, "role": "foreign", "state": "COMMITTED",
            "old": None, "new": hashlib.sha256(raw).hexdigest(),
            "binaries": {"frpc": one, "frps": two},
        }
        return raw, receipt

    def test_rc7_manifest_pair_plan_preserves_frp_receipt_and_other_engines(self):
        raw, receipt = self.rc7_manifest_pair_fixture(extra=True)
        manifest_path = self.node / "config/engine-state/engines.json"
        manifest_path.parent.mkdir(mode=0o700)
        manifest_path.write_bytes(raw)
        journal_before = json.dumps(receipt, sort_keys=True).encode()
        candidate, report = control.plan_rc7_backhaul_manifest_pair(
            manifest_path.read_bytes(), receipt, "a" * 64, role="foreign")
        parsed = json.loads(candidate)
        original = json.loads(raw)
        self.assertEqual(parsed["engines"]["frp"], original["engines"]["frp"])
        self.assertEqual(parsed["engines"]["gost"], original["engines"]["gost"])
        self.assertEqual(parsed["engines"]["rathole"], original["engines"]["rathole"])
        self.assertEqual(parsed["engines"]["backhaul"], {"sha256": "a" * 64})
        self.assertEqual(report["RC7_PRIOR_MANIFEST_SHA256"],
                         hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["RC7_CANDIDATE_MANIFEST_SHA256"],
                         hashlib.sha256(candidate).hexdigest())
        self.assertNotEqual(report["RC7_PRIOR_MANIFEST_SHA256"],
                            report["RC7_CANDIDATE_MANIFEST_SHA256"])
        self.assertEqual(report["RC7_FRP_RECEIPT_REBIND"],
                         "ATOMIC_TRANSACTION_REQUIRED")
        self.assertEqual(report["MANIFEST_WRITTEN"], "NO")
        self.assertEqual(report["FRP_JOURNAL_WRITTEN"], "NO")
        self.assertEqual(report["NODE_RECREATED"], "NO")
        self.assertEqual(report["INSTALL_ALLOWED"], "NO")
        self.assertEqual(report["ACTIVATION_GATE"], "HOLD")
        self.assertEqual(manifest_path.read_bytes(), raw)
        self.assertEqual(json.dumps(receipt, sort_keys=True).encode(), journal_before)
        self.assertNotIn("a" * 64, str(report))

    def test_rc7_manifest_pair_cannot_accept_unbound_or_forged_frp_receipt(self):
        raw, receipt = self.rc7_manifest_pair_fixture(extra=True)
        cases = [
            {**receipt, "new": "f" * 64},
            {**receipt, "role": "ir"},
            {**receipt, "state": "HOLD"},
            {**receipt, "state": "PREPARED"},
            {**receipt, "schema": True},
            {**receipt, "old": "NOT_SHA256"},
            {**receipt, "binaries": {"frpc": "1" * 64}},
            {**receipt, "binaries": {"frpc": "1" * 64, "frps": "f" * 64}},
            {**receipt, "binaries": {"frpc": "1" * 64, "frps": True}},
            {**receipt, "binaries": None},
            {**receipt, "debug": "DO_NOT_PRINT_ME"},
            {},
            None,
        ]
        for item in cases:
            with self.subTest(item=str(item)[:50]):
                with self.assertRaises(control.Hold):
                    control.plan_rc7_backhaul_manifest_pair(
                        raw, item, "a" * 64, role="foreign")
        self.assertNotIn("DO_NOT_PRINT_ME",
                         str(control.plan_rc7_backhaul_manifest_pair.__doc__))

    def test_rc7_manifest_pair_rejects_bad_or_ambiguous_manifest(self):
        raw, receipt = self.rc7_manifest_pair_fixture()
        cases = [
            b"",
            b"{" + b"x" * 8192 + b"}",
            b"INVALID JSON",
            b'{"schema":1,"schema":1,"engines":{}}',
            b'{"schema":true,"engines":{}}',
            b'{"schema":1,"engines":{"frp":null}}',
            b'{"schema":1,"engines":{"frp":{"sha256":"1","server_sha256":"2"}}}',
            b'{"schema":1,"engines":{"frp":{"sha256":"1"*64}}}',
            json.dumps({"schema": 1, "engines": {
                "frp": {"sha256": "1" * 64, "server_sha256": "2" * 64},
                "backhaul": {"sha256": "a" * 64},
            }}).encode(),
            json.dumps({"schema": 1, "engines": {
                "frp": {"sha256": "1" * 64, "server_sha256": "2" * 64},
                "unknown": {"sha256": "a" * 64},
            }}).encode(),
            json.dumps({"schema": 1, "engines": {
                "gost": {"sha256": "1" * 64},
            }}).encode(),
            [],
            "not bytes",
            None,
        ]
        for case in cases:
            with self.subTest(case=str(case)[:40]):
                with self.assertRaises(control.Hold):
                    control.plan_rc7_backhaul_manifest_pair(
                        case, receipt, "a" * 64, role="foreign")
        self.assertEqual(control._parse_rc7_manifest_snapshot(raw)["schema"], 1)

    def test_rc7_manifest_pair_invalid_role_and_backhaul_sha_are_hold(self):
        raw, receipt = self.rc7_manifest_pair_fixture()
        for role in ("", "KH", "panel-iran", None, "foreign\nbad"):
            with self.subTest(role=role):
                with self.assertRaisesRegex(control.Hold,
                                            "RC7_ENGINE_ROLE_UNTRUSTED"):
                    control.plan_rc7_backhaul_manifest_pair(
                        raw, receipt, "a" * 64, role=role)
        for sha in ("a" * 63, "G" * 64, "ABSENT", "", 42, None):
            with self.subTest(sha=sha):
                with self.assertRaisesRegex(control.Hold,
                                            "RC7_BACKHAUL_BINARY_DIGEST_UNTRUSTED"):
                    control.plan_rc7_backhaul_manifest_pair(
                        raw, receipt, sha, role="foreign")

    def test_rc7_manifest_pair_requires_coherent_journal_on_each_role(self):
        raw, receipt = self.rc7_manifest_pair_fixture(extra=True)
        iran = {**receipt, "role": "ir"}
        candidate, report = control.plan_rc7_backhaul_manifest_pair(
            raw, iran, "b" * 64, role="ir")
        self.assertNotEqual(candidate, raw)
        self.assertEqual(report["RC7_FRP_RECEIPT_BINDING"],
                         "EXACT_PRIOR_MANIFEST_MATCH")
        with self.assertRaises(control.Hold):
            control.plan_rc7_backhaul_manifest_pair(
                raw, iran, "b" * 64, role="foreign")
        # A manifest-only write would invalidate the exact legacy RC7
        # enrollment journal's 'new' digest. The future two-file
        # transaction must handle this, and must not silently call PASS.
        self.assertNotEqual(hashlib.sha256(candidate).hexdigest(), iran["new"])
        self.assertEqual(report["INSTALL_ALLOWED"], "NO")
        self.assertEqual(report["RC7_BACKHAUL_MANIFEST_PLAN"], "CANDIDATE_ONLY")

    def test_rc7_preflight_actions_have_fixed_signed_and_no_mutation_contract(self):
        compile(control.RC7_BUNDLED_BACKHAUL_AUDIT,"<image-audit>","exec")
        compile(control.RC7_BUNDLED_SIGNED_INVENTORY,"<signed-agent-get>","exec")
        self.assertIn("nonce=secrets.token_hex(16)",
                      control.RC7_BUNDLED_SIGNED_INVENTORY)
        self.assertIn("ProxyHandler({})",control.RC7_BUNDLED_SIGNED_INVENTORY)
        self.assertIn("NoRedirect",control.RC7_BUNDLED_SIGNED_INVENTORY)
        self.assertIn("os.O_NOFOLLOW",control.RC7_BUNDLED_BACKHAUL_AUDIT)
        self.assertNotIn("docker compose",control.RC7_BUNDLED_BACKHAUL_AUDIT)
        self.assertNotIn("/api/agent/tunnels/apply",
                         control.RC7_BUNDLED_SIGNED_INVENTORY)
        out=self.run_control("verify-rc7-bundle")
        self.assertEqual(out.returncode,2)
        self.assertIn("HOLD: RC7_BUNDLED_ROLE_REQUIRED",out.stderr)
        self.assertFalse((self.node/"config/engine-state").exists())


    def test_rc7_menu_auto_role_denies_arbitrary_node_dir_without_docker(self):
        # The review may classify only the real /opt/smite-node; a sandbox
        # with a valid-looking .env is not field-server evidence.
        result = self.run_control(
            "verify-rc7-bundle", "--auto-role",
            "--node-dir", self.node)
        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "HOLD: RC7_BUNDLED_PRODUCTION_NODE_PATH_REQUIRED", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.node/"config/engine-state").exists())
        conflict = self.run_control(
            "verify-rc7-bundle", "--auto-role", "--role", "ir")
        self.assertEqual(conflict.returncode, 2)
        self.assertIn("HOLD: RC7_BUNDLED_CONFLICTING_ROLE_SELECTION",
                      conflict.stderr)
        self.assertFalse((self.node/"config/engine-state").exists())

    def test_rc7_auto_role_uses_existing_env_parser_not_sourcing(self):
        with patch.object(control,"NODE_DEFAULT",self.node):
            self.assertEqual(control._rc7_operator_review_role(self.node),
                             "foreign")
            (self.node/".env").write_text(
                ENV.replace("NODE_ROLE=foreign","NODE_ROLE=panel-iran"))
            self.assertEqual(control._rc7_operator_review_role(self.node),
                             "ir")
            (self.node/".env").write_text(
                ENV.replace("NODE_ROLE=foreign","NODE_ROLE=iran")+
                "NODE_ROLE=foreign\n")
            with self.assertRaisesRegex(
                    control.Hold,"Duplicate protected Node"):
                control._rc7_operator_review_role(self.node)
            (self.node/".env").write_text(ENV)
            symlink = self.root/"linked"
            symlink.symlink_to(self.node,target_is_directory=True)
            with self.assertRaisesRegex(
                    control.Hold,"RC7_BUNDLED_PRODUCTION_NODE_PATH_REQUIRED"):
                control._rc7_operator_review_role(symlink)

    def test_menu_is_clear_and_inert(self):
        result = subprocess.run(
            ["bash", str(MENU), "--install"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Host installation disabled", result.stderr)
        result = subprocess.run(
            ["bash", str(MENU), "--status"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "SMITE_NODE_DIR": str(self.node)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOT_INSTALLED", result.stdout)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_menu_full_beginner_walkthrough_is_read_only(self):
        result = subprocess.run(
            ["bash", str(MENU), "--menu"],
            input="1\n2\n3\n0\n", capture_output=True, text=True, timeout=15,
            env={**os.environ, "SMITE_NODE_DIR": str(self.node), "TERM": "dumb"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATE=NOT_INSTALLED", result.stdout)
        self.assertIn("INSTALL_ALLOWED=NO", result.stdout)
        self.assertIn("RC7 BUNDLED BACKHAUL + SIGNED INVENTORY", result.stdout)
        self.assertIn("HOLD: RC7_BUNDLED_PRODUCTION_NODE_PATH_REQUIRED", result.stderr)
        self.assertIn("ACTIVATION_GATE=HOLD",result.stdout)
        self.assertIn("installation on real IR/KH is disabled", result.stdout)
        self.assertFalse((self.node / "config/engine-state").exists())

    def test_concurrent_engine_operations_are_rejected_before_mutation(self):
        # Simulate a trusted runner admission while testing only the lock.
        with patch.object(control.transaction, "admission", return_value=None):
            with control._lab_lock(self.root):
                with self.assertRaisesRegex(control.Hold, "transaction is in progress"):
                    with control._lab_lock(self.root):
                        self.fail("A second concurrent transaction acquired the lock")

    def test_rc7_backhaul_review_supplies_pinned_root_to_both_existing_verifiers(self):
        # Intercept ONLY the Python verifier calls, not the menu logic. No
        # Docker or real host connection; test actual bash argument plumbing.
        stub_dir = self.root / "fake-bin"
        stub_dir.mkdir()
        mock_python = stub_dir / "python3"
        log = self.root / "argv.txt"
        mock_python.write_text(
            '#!/bin/sh\n'
            'printf "%s\\\n" "$*" >> "$SMITE_TEST_ARGV_LOG"\n'
            'exit 0\n')
        mock_python.chmod(0o700)
        root = ROOT / "modules/smite-rc7-sigstore-trusted-root.json"
        for override in (None, str(root), str(self.root / "bad-root.json")):
            with self.subTest(override=override):
                if log.exists():
                    log.unlink()
                env = {
                    **os.environ,
                    "PATH": str(stub_dir) + os.pathsep + os.environ["PATH"],
                    "SMITE_TEST_ARGV_LOG": str(log),
                    "SMITE_NODE_DIR": "/opt/smite-node",
                    "TERM": "dumb",
                }
                for key in ("SMITE_BH_PAIR_TRUSTED_ROOT", "SMITE_BH_PAIR_MANIFEST",
                            "SMITE_BH_PAIR_SHA256", "SMITE_BH_PAIR_SOURCE_SHA",
                            "SMITE_BH_PAIR_PUBLISH_REF"):
                    env.pop(key, None)
                if override is not None:
                    env["SMITE_BH_PAIR_TRUSTED_ROOT"] = override
                out = subprocess.run(
                    ["bash", str(MENU), "--menu"],
                    input="2\n0\n", capture_output=True, text=True,
                    timeout=15, env=env)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertIn("INSTALL_ALLOWED=NO", out.stdout)
                self.assertIn("ACTIVATION_GATE=HOLD", out.stdout)
                calls = log.read_text().splitlines()
                admission = [call for call in calls
                             if "smite-managed-engine-host-admission.py" in call]
                retained = [call for call in calls
                            if "smite-managed-backhaul-host-executor.py" in call]
                self.assertEqual(len(admission), 1)
                self.assertEqual(len(retained), 1)
                expected = override if override is not None else str(root)
                for call in (*admission, *retained):
                    self.assertIn("--signed-pair-trusted-root " + expected, call)
                    self.assertIn("--signed-pair-source-sha "
                                  "9a1270b31e8d44f13d09b71ab6b9798410b09c12", call)
                self.assertFalse((self.node / "config/engine-state").exists())

    def test_no_network_or_live_service_actions_in_menu_or_controller(self):
        script = MENU.read_text()
        controller = FILE.read_text()
        self.assertIn("verify-rc7-bundle --auto-role",script)
        self.assertIn('echo "INSTALL_ALLOWED=NO"',script)
        self.assertIn('echo "ACTIVATION_GATE=HOLD"',script)
        self.assertNotIn("docker exec",script)
        self.assertNotIn("docker restart",script)
        for text in ("apt-get ", "curl ", "docker compose up", "systemctl ",
                     "iptables ", "ufw ", "ssh ", "nginx -s"):
            self.assertNotIn(text, script)
            self.assertNotIn(text, controller)
        parent = (ROOT / "modules/smite-backhaul-management.sh").read_text()
        self.assertIn('7) Independent Engines (Backhaul review)', parent)
        self.assertIn('smite_managed_bh_menu', parent)
        self.assertIn('2) 443 Gateway (auto-detect Panel / Foreign)', parent)
        self.assertIn('show_smite_gateway_menu', parent)
        self.assertIn('6) docker_smite_advanced_menu', parent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
