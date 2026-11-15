"""End-to-end Foreign option-2 offline integration of EXISTING stage journals.

The only exercised actions are disposable test callbacks and the original
signed grant/identity promotion against an injected fake Panel. Never
starts a Node, touches a server, or claims Connected.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


host = load("option2_host_recovery",
            ROOT / "modules" / "smite-unified-foreign-host-recovery.py")
fixtures = load("option2_identity_fixture",
                ROOT / "tests" / "test-smite-unified-foreign-identity-phase.py")


class UnifiedForeignOption2(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IdentityPhase(
            methodName="test_real_client_promotion_and_no_duplicate_redemption")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tmp.cleanup)
        self.states = {"core": True, "sanaei": "ABSENT", "gateway": "ABSENT"}
        self.events = []
        self.fail_after = None
        self.fail_before = None

    def verify_core(self, scope):
        self.events.append("verify_core")
        self.assertEqual(scope["node_id"], self.fixture.doc["node_id"])
        return self.states["core"]

    def verify_sanaei(self, scope):
        self.events.append("verify_sanaei")
        return self.states["sanaei"]

    def verify_gateway(self, scope):
        self.events.append("verify_gateway")
        return self.states["gateway"]

    def install_sanaei(self, scope):
        self.events.append("install_sanaei")
        if self.fail_before == "sanaei":
            self.fail_before = None
            raise OSError("failure before Sanaei could be committed")
        self.states["sanaei"] = "READY"
        if self.fail_after == "sanaei":
            self.fail_after = None
            raise KeyboardInterrupt("power loss after Sanaei mount")

    def install_gateway(self, scope):
        self.events.append("install_gateway")
        if self.fail_before == "gateway":
            self.fail_before = None
            raise OSError("failure before Gateway could be committed")
        self.states["gateway"] = "READY"
        if self.fail_after == "gateway":
            self.fail_after = None
            raise KeyboardInterrupt("power loss after Gateway TLS/443")

    def rollback_sanaei(self, scope):
        self.events.append("rollback_sanaei")
        self.assertEqual(self.states["gateway"], "ABSENT")
        self.states["sanaei"] = "ABSENT"
        return "ROLLED_BACK_VERIFIED"

    def rollback_gateway(self, scope):
        self.events.append("rollback_gateway")
        self.assertEqual(self.states["sanaei"], "READY")
        self.states["gateway"] = "ABSENT"
        return "ROLLED_BACK_VERIFIED"

    def run_option2(self, **kwargs):
        p = self.fixture
        data = dict(
            directory=p.stage, packet_path=p.packet,
            state_path=p.state, gateway_path=p.gateway,
            node_env_path=p.env, live_identity=p.live,
            now=p.now, expected_panel=p.doc["panel_url"],
            expected_foreign=p.doc["origin"],
            expected_node=p.doc["node_name"],
            verify_core=self.verify_core, verify_sanaei=self.verify_sanaei,
            verify_gateway=self.verify_gateway,
            install_sanaei=self.install_sanaei,
            install_gateway=self.install_gateway,
            rollback_sanaei=self.rollback_sanaei,
            rollback_gateway=self.rollback_gateway,
            transport=p.mock_panel, disposable_capability=True,
        )
        data.update(kwargs)
        return host.rehearse_option2(**data)

    def assert_no_identity(self):
        self.assertFalse(self.fixture.live.exists())
        self.assertEqual(self.fixture.calls, [])
        self.assertFalse(
            (self.fixture.stage / "foreign-install-identity.json").exists())

    def test_full_sequence_sanaei_gateway_then_signed_redeem_no_activation(self):
        result = self.run_option2()
        self.assertEqual(result, {
            "phase": "FOREIGN_OPTION2_OFFLINE_READY",
            "host_journal": "GATEWAY_443_VERIFIED",
            "identity_journal": "IDENTITY_PROMOTED_OFFLINE",
            "node_id": "foreign-node-1234",
            "sanaei": "READ_ONLY_VERIFIED",
            "gateway": "EXACT_HTTPS_443_VERIFIED",
            "signed_panel_proof": "PASS",
            "runtime_activation": "NOT_PERFORMED",
            "activation_allowed": False,
            "connected": False,
        })
        self.assertEqual(self.events.count("install_sanaei"), 1)
        self.assertEqual(self.events.count("install_gateway"), 1)
        self.assertLess(self.events.index("install_sanaei"),
                        self.events.index("install_gateway"))
        self.assertEqual(self.fixture.calls, [
            "/api/foreign-install/redeem",
            "/api/node-control/installation-status",
            "/api/node-control/installation-status",
        ])
        before = self.fixture.live.read_bytes()
        self.fixture.calls.clear()
        self.events.clear()
        self.assertEqual(self.run_option2(), result)
        self.assertEqual(self.fixture.calls,
                         ["/api/node-control/installation-status"])
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)
        self.assertEqual(before, self.fixture.live.read_bytes())
        for receipt in (
            self.fixture.stage / host.JOURNAL,
            self.fixture.stage / "unified-foreign-transaction.json",
        ):
            raw = receipt.read_text()
            self.assertNotIn(self.fixture.doc["installation_code"], raw)
            self.assertNotIn("node_secret", raw)
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)

    def test_original_rc9_core_owner_handoff_to_existing_host_and_identity_journals(self):
        # Core is committed by the ORIGINAL fresh U-OPTI journal; this
        # test exercises real source/image/scope checks before the existing
        # Sanaei, 443 and signed-identity phase sequence, with NO host I/O.
        import subprocess
        import os
        import stat
        from unittest.mock import patch
        core_mod = load("option2_original_rc9_core_owner",
                        ROOT / "modules" / "smite-rc6-install-journal.py")
        # The production Journal explicitly requires root-owned files.
        # This suite runs without root: enforce the IDENTICAL path/mode
        # predicates against the owner of this private disposable fixture.
        # Never relax the actual module or run Docker under elevated rights.
        original_trusted = core_mod.trusted
        def fixture_trusted(path, directory=False):
            st = Path(path).lstat()
            if (stat.S_ISLNK(st.st_mode) or st.st_uid != os.geteuid()
                    or st.st_mode & 0o022
                    or (directory and not stat.S_ISDIR(st.st_mode))):
                raise core_mod.Hold("UNTRUSTED_PATH")
            return st
        core_mod.trusted = fixture_trusted
        self.addCleanup(setattr, core_mod, "trusted", original_trusted)
        p = self.fixture
        source = core_mod.RC9_SOURCE
        p.write(p.state, p.state.read_text().replace(
            "SMITE_MANAGED_VERSION=2.0.0-rc.7",
            "SMITE_MANAGED_VERSION=2.0.0-rc.9\nSMITE_UPSTREAM_REF="+source))
        root = p.base / "core-owner"
        root.mkdir(mode=0o700)
        current = {}
        def runner(args, **kwargs):
            if args[:3] == ["docker", "--host", "unix:///var/run/docker.sock"]:
                action = args[3]
                if action == "ps":
                    output = "smite-node\n" if current else ""
                elif action == "inspect":
                    self.assertEqual(args[4], "smite-node")
                    output = json.dumps([current["smite-node"]])
                else:
                    raise AssertionError("No Docker mutation allowed")
                return subprocess.CompletedProcess(args, 0, output, "")
            raise AssertionError("No system/service access allowed")
        owner = core_mod.Journal(root, runner)
        owner.folder.mkdir(parents=True, mode=0o700)
        scope = ("panel.example.com", "kh.example.com",
                 p.doc["node_name"], p.doc["node_id"],
                 "/smite-node/" + "a"*32)
        # The original private 0600 grant is the ONLY authority for Core
        # owner fields; no free-form foreign-inputs or second operator prompts.
        with patch("time.time", return_value=p.doc["expires_at"]+1):
            with self.assertRaises(core_mod.Hold):
                owner.begin("foreign", source=source,
                            resumable_foreign=True,
                            foreign_packet_path=p.packet)
        self.assertFalse(owner.path.exists())
        with patch("time.time", return_value=p.now):
            project = owner.begin("foreign", source=source,
                                  resumable_foreign=True,
                                  foreign_packet_path=p.packet)
        self.assertEqual(owner.load()["foreign_inputs"]["node_id"],p.doc["node_id"])
        self.assertEqual(owner.load()["state"], "INSTALLING")
        # A partially installed, or an inconsistent Core cannot start the
        # Host journal or redeem a grant.
        self.events.clear()
        with self.assertRaises(host.Hold):
            self.run_option2(core_owner=owner)
        self.assertEqual(self.events, [])
        self.assert_no_identity()
        node = root / "opt/smite-node"
        node.mkdir(parents=True)
        env = node / ".env"
        env.write_text(
            "NODE_NAME="+p.doc["node_name"]+"\n"
            "NODE_ROLE=foreign\n"
            "PANEL_ADDRESS=panel.example.com:443\n"
            "SMITE_CONTROL_ADDRESS=https://kh.example.com:443/smite-node/"+("a"*32)+"\n"
            "SMITE_NODE_PANEL_AUTH_MODE=paused\n"
            "SMITE_AGENT_AUTH_MODE=strict\n"
            "SMITE_SANAEI_INVENTORY_ENABLED=false\n")
        env.chmod(0o600)
        state = root / "etc/u-opti/smite/state.env"
        state.parent.mkdir(parents=True)
        state.write_text(p.state.read_text())
        state.chmod(0o600)
        current["smite-node"] = dict(
            Id="a"*64, Name="/smite-node",
            State={"Running":True, "Health":{"Status":"healthy"}},
            Config={"Image":core_mod.RC9_IMAGES["smite-node"],
                    "Env":["SMITE_NODE_PANEL_AUTH_MODE=paused"],
                    "Labels":{"com.docker.compose.project":project,
                              "com.docker.compose.service":"smite-node",
                              "com.docker.compose.project.config_files":
                                  "/opt/smite-node/docker-compose.yml"}},
            HostConfig={"RestartPolicy":{"Name":"unless-stopped"}})
        self.assertEqual(owner.foreign_resume(), ("CORE_READY_TO_COMMIT", project))
        self.assertEqual(owner.commit(), "RC6_INSTALL_TRANSACTION=COMMITTED")
        self.assertEqual(owner.foreign_resume(), ("CORE_COMMITTED", project))
        record = owner.load()
        record["foreign_inputs"]["foreign_domain"]="spoofed.example.com"
        owner.save(record)
        self.events.clear()
        with self.assertRaises(host.Hold):
            self.run_option2(core_owner=owner)
        self.assertEqual(self.events, [])
        self.assert_no_identity()
        record["foreign_inputs"]["foreign_domain"]=scope[1]
        owner.save(record)
        before_core = state.read_text()
        state.write_text(before_core.replace(
            "SMITE_UPSTREAM_REF="+source, "SMITE_UPSTREAM_REF="+("0"*40)))
        state.chmod(0o600)
        with self.assertRaises(host.Hold):
            self.run_option2(core_owner=owner)
        self.assertEqual(self.events, [])
        self.assert_no_identity()
        state.write_text(before_core)
        state.chmod(0o600)
        current["smite-node"]["Config"]["Image"]=core_mod.RC7_IMAGES["smite-node"]
        with self.assertRaises(host.Hold):
            self.run_option2(core_owner=owner)
        self.assertEqual(self.events, [])
        self.assert_no_identity()
        current["smite-node"]["Config"]["Image"]=core_mod.RC9_IMAGES["smite-node"]
        report = self.run_option2(core_owner=owner)
        self.assertEqual(report["phase"], "FOREIGN_OPTION2_OFFLINE_READY")
        self.assertFalse(report["connected"])
        self.assertFalse(report["activation_allowed"])
        self.assertEqual(self.events.count("install_sanaei"), 1)
        self.assertEqual(self.events.count("install_gateway"), 1)
        before = p.live.read_bytes()
        self.events.clear()
        p.calls.clear()
        self.assertEqual(self.run_option2(core_owner=owner), report)
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)
        self.assertEqual(p.live.read_bytes(), before)
        self.assertEqual(p.calls, ["/api/node-control/installation-status"])
        self.assertNotIn(p.doc["installation_code"], owner.path.read_text())
        with self.assertRaises(core_mod.Hold):
            owner.rollback()
    def test_rc9_exact_source_checked_before_any_host_stage_mutation(self):
        # Use the original gateway packet/state admission, NOT a second
        # source validator. A real RC9 Foreign state has to match the exact
        # signed RC9 Panel/Node release before Sanaei/Gateway can be touched.
        source="e7f76185e9a7da51d7069d5d0a829dc192cc1e06"
        original=self.fixture.state.read_text()
        exact=original.replace(
            "SMITE_MANAGED_VERSION=2.0.0-rc.7",
            "SMITE_MANAGED_VERSION=2.0.0-rc.9\nSMITE_UPSTREAM_REF="+source
        )
        self.fixture.write(self.fixture.state,exact)
        for invalid in (
            exact.replace(source,"0"*40),
            exact.replace("SMITE_UPSTREAM_REF="+source+"\n",""),
            exact.replace("SMITE_ROLE=foreign","SMITE_ROLE=panel-iran"),
            exact.replace("SMITE_NODE_NAME=node-kh","SMITE_NODE_NAME=other-kh"),
            exact.replace("SMITE_FOREIGN_DOMAIN=kh.example.com",
                          "SMITE_FOREIGN_DOMAIN=spoofed.example.com"),
        ):
            with self.subTest(invalid=invalid):
                self.fixture.write(self.fixture.state,invalid)
                self.events.clear()
                with self.assertRaises(host.Hold):
                    self.run_option2()
                self.assertEqual(self.events,[])
                self.assert_no_identity()
                self.assertFalse((self.fixture.stage / host.JOURNAL).exists())
        self.fixture.write(self.fixture.state,exact)
        result=self.run_option2()
        self.assertEqual(result["phase"],"FOREIGN_OPTION2_OFFLINE_READY")
        self.assertFalse(result["activation_allowed"])
        self.assertFalse(result["connected"])
        self.assertEqual(self.events.count("install_sanaei"),1)
        self.assertEqual(self.events.count("install_gateway"),1)
        key=self.fixture.live.read_bytes()
        self.events.clear()
        self.fixture.calls.clear()
        self.assertEqual(self.run_option2(),result)
        self.assertNotIn("install_sanaei",self.events)
        self.assertNotIn("install_gateway",self.events)
        self.assertEqual(self.fixture.live.read_bytes(),key)
        self.assertEqual(self.fixture.calls,
                         ["/api/node-control/installation-status"])

    def test_rc9_real_signed_readonly_witnesses_join_original_stage_and_identity_journals(self):
        # Compose the existing, SOURCE-PINNED RC9 Docker/Compose/HTTPS witness
        # (not a stub returning READY) with the original offline Host journal
        # and the real one-use Panel grant/HMAC identity promotion functions.
        # No actual Docker, network, service or server access is permitted.
        witness_fixture = load(
            "option2_existing_real_witness_fixture",
            ROOT / "tests" / "test-smite-unified-foreign-existing-witnesses.py"
        )
        trial = witness_fixture.ForeignReadOnlyWitnesses(
            methodName="test_exact_signed_runtime_is_read_only_witness_ready"
        )
        trial.setUp()
        self.addCleanup(trial.doCleanups)
        exact_source="e7f76185e9a7da51d7069d5d0a829dc192cc1e06"
        trial.current.update(
            SMITE_MANAGED_VERSION="2.0.0-rc.9",
            SMITE_UPSTREAM_REF=exact_source
        )
        self.fixture.write(self.fixture.state,
            self.fixture.state.read_text().replace(
                "SMITE_MANAGED_VERSION=2.0.0-rc.7",
                "SMITE_MANAGED_VERSION=2.0.0-rc.9\nSMITE_UPSTREAM_REF="+exact_source
            ))
        def with_existing_witness():
            return self.run_option2(
                verify_core=trial.observer.core,
                verify_sanaei=trial.observer.sanaei,
                verify_gateway=trial.observer.gateway,
                install_sanaei=lambda scope: trial.attach(),
                install_gateway=lambda scope: trial.serve_gateway(),
            )
        trial.current["SMITE_UPSTREAM_REF"]="0"*40
        with self.assertRaises(host.Hold):
            with_existing_witness()
        self.assertFalse((self.fixture.stage/host.JOURNAL).exists())
        self.assert_no_identity()
        trial.current["SMITE_UPSTREAM_REF"]=exact_source
        trial.image="ghcr.io/aghajani82/smite-node:latest"
        with self.assertRaises(host.Hold):
            with_existing_witness()
        self.assertFalse((self.fixture.stage/host.JOURNAL).exists())
        self.assert_no_identity()
        trial.image=witness_fixture.w.TRIAL_NODE
        report=with_existing_witness()
        self.assertEqual(report["phase"],"FOREIGN_OPTION2_OFFLINE_READY")
        self.assertEqual(report["signed_panel_proof"],"PASS")
        self.assertFalse(report["connected"])
        self.assertFalse(report["activation_allowed"])
        self.assertEqual(trial.observer.sanaei(trial.scope),"READY")
        self.assertEqual(trial.observer.gateway(trial.scope),"READY")
        original_identity=self.fixture.live.read_bytes()
        self.fixture.calls.clear()
        self.assertEqual(with_existing_witness(),report)
        self.assertEqual(self.fixture.live.read_bytes(),original_identity)
        self.assertEqual(self.fixture.calls,
                         ["/api/node-control/installation-status"])

    def test_gateway_must_be_verified_before_any_code_redeem(self):
        self.fail_after = "gateway"
        with self.assertRaises(KeyboardInterrupt):
            self.run_option2()
        self.assert_no_identity()
        self.assertEqual(self.states["sanaei"], "READY")
        self.assertEqual(self.states["gateway"], "READY")
        self.assertEqual(
            json.loads((self.fixture.stage / host.JOURNAL).read_text())["phase"],
            "GATEWAY_INTENT")
        # Independently witnessed READY; retry commits with NO reinstallation.
        self.events.clear()
        self.run_option2()
        self.assertNotIn("install_gateway", self.events)
        self.assertNotIn("install_sanaei", self.events)
        self.assertTrue(self.fixture.live.exists())

    def test_interrupted_sanaei_witness_ready_is_not_reinstalled(self):
        self.fail_after = "sanaei"
        with self.assertRaises(KeyboardInterrupt):
            self.run_option2()
        self.assert_no_identity()
        self.events.clear()
        self.assertEqual(self.run_option2()["phase"],
                         "FOREIGN_OPTION2_OFFLINE_READY")
        self.assertEqual(self.events.count("install_sanaei"), 0)
        self.assertEqual(self.events.count("install_gateway"), 1)

    def test_gateway_failure_compensates_only_gateway_and_no_code(self):
        self.fail_before = "gateway"
        with self.assertRaises(host.Hold):
            self.run_option2()
        self.assert_no_identity()
        self.assertEqual(self.states["sanaei"], "READY")
        self.assertEqual(self.states["gateway"], "ABSENT")
        self.assertIn("rollback_gateway", self.events)
        self.assertNotIn("rollback_sanaei", self.events)
        self.assertEqual(
            json.loads((self.fixture.stage / host.JOURNAL).read_text())["phase"],
            "SANAEI_RO_VERIFIED")
        self.events.clear()
        self.run_option2()
        self.assertEqual(self.events.count("install_gateway"), 1)
        self.assertNotIn("install_sanaei", self.events)

    def test_sanaei_failure_rolls_back_own_stage_only_before_any_redeem(self):
        self.fail_before = "sanaei"
        with self.assertRaises(host.Hold):
            self.run_option2()
        self.assert_no_identity()
        self.assertEqual(self.states["sanaei"], "ABSENT")
        self.assertEqual(self.states["gateway"], "ABSENT")
        self.assertIn("rollback_sanaei", self.events)
        self.events.clear()
        self.run_option2()
        self.assertEqual(self.events.count("install_sanaei"), 1)
        self.assertEqual(self.events.count("install_gateway"), 1)

    def test_revoked_panel_proof_retains_verified_host_and_staged_secret(self):
        self.fixture.wrong_proof = True
        with self.assertRaises(ValueError):
            self.run_option2()
        self.assertEqual(self.states["sanaei"], "READY")
        self.assertEqual(self.states["gateway"], "READY")
        self.assertFalse(self.fixture.live.exists())
        self.assertTrue(
            (self.fixture.stage / "foreign-install-identity.json").is_file())
        self.assertEqual(
            json.loads((self.fixture.stage / host.JOURNAL).read_text())["phase"],
            "GATEWAY_443_VERIFIED")
        # A retry reuses the original key and never redoes Sanaei/Gateway.
        self.fixture.wrong_proof = False
        self.fixture.calls.clear()
        self.events.clear()
        self.assertEqual(self.run_option2()["signed_panel_proof"], "PASS")
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)

    def test_expired_grant_renewal_recovers_original_host_and_identity_without_reinstall(self):
        """Real private packet intake -> original Host -> HMAC Identity journals.

        Failure AFTER the original Host Gateway commit but BEFORE proof
        must preserve the same staged key. On expiry, renew ONLY the one-use
        packet for the exact same reserved Node; retry never installs
        Sanaei/Gateway or regenerates its signed HMAC identity.
        """
        import hashlib
        import io
        intake = load("option2_original_packet_intake",
                      ROOT / "modules" / "smite-unified-foreign-packet-intake.py")
        p = self.fixture
        p.wrong_proof = True
        with self.assertRaises(host.Hold):
            self.run_option2()
        self.assertEqual((self.states["sanaei"], self.states["gateway"]),
                         ("READY", "READY"))
        identity_staged = p.stage / "foreign-install-identity.json"
        initial = identity_staged.read_bytes()
        self.assertFalse(p.live.exists())
        self.assertEqual(json.loads((p.stage / host.JOURNAL).read_text())
                         ["phase"], "GATEWAY_443_VERIFIED")
        self.assertEqual(json.loads((p.stage /
                        "unified-foreign-transaction.json").read_text())
                         ["phase"], "INTENT")
        old_end = p.doc["expires_at"]
        old_packet = p.packet.read_bytes()
        old_host = (p.stage / host.JOURNAL).read_bytes()
        old_identity_tx = (p.stage / "unified-foreign-transaction.json").read_bytes()

        # Original intake rejects a changed code before expiry without
        # modifying a completed Host checkpoint or identity secret.
        new_code = "smi1_" + "c"*43
        updated = dict(p.doc, installation_code=new_code,
                       expires_at=old_end + 3600)
        def capture(at, changed=updated):
            return intake.capture_disposable(
                io.StringIO(json.dumps(changed) + "\n\n"),
                target=p.packet, expected_panel=p.doc["panel_url"],
                expected_domain=p.doc["origin"],
                expected_node=p.doc["node_name"], now=at,
                disposable_capability=True, allow_expired_renewal=True)
        with self.assertRaises(intake.Hold):
            capture(old_end - 1)
        self.assertEqual(p.packet.read_bytes(), old_packet)
        self.assertEqual(identity_staged.read_bytes(), initial)
        self.assertEqual((p.stage / host.JOURNAL).read_bytes(), old_host)
        self.assertEqual((p.stage / "unified-foreign-transaction.json").read_bytes(),
                         old_identity_tx)

        p.now = old_end
        self.assertEqual(capture(old_end)["status"], "RENEWED_PRIVATE")
        p.doc = updated
        self.assertNotEqual(p.packet.read_bytes(), old_packet)
        self.assertEqual(identity_staged.read_bytes(), initial)
        self.assertEqual((p.stage / host.JOURNAL).read_bytes(), old_host)
        self.assertEqual((p.stage / "unified-foreign-transaction.json").read_bytes(),
                         old_identity_tx)

        p.wrong_proof = False
        self.events.clear()
        p.calls.clear()
        report = self.run_option2()
        self.assertEqual(report["phase"], "FOREIGN_OPTION2_OFFLINE_READY")
        self.assertFalse(report["connected"])
        self.assertFalse(report["activation_allowed"])
        self.assertEqual(report["signed_panel_proof"], "PASS")
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)
        self.assertEqual(identity_staged.read_bytes(), initial)
        self.assertEqual(json.loads(p.live.read_text())["node_secret"],
                         json.loads(initial)["node_secret"])
        self.assertEqual(json.loads((p.stage / host.JOURNAL).read_text())
                         ["packet_sha256"],
                         hashlib.sha256(p.packet.read_bytes()).hexdigest())
        self.assertEqual(json.loads((p.stage /
                        "unified-foreign-transaction.json").read_text())
                         ["phase"], "IDENTITY_PROMOTED_OFFLINE")
        # Retained promoted key: a final same-option retry uses only a
        # fresh signed Panel proof, never another bearer-code redemption.
        live_before = p.live.read_bytes()
        p.calls.clear()
        self.events.clear()
        self.assertEqual(self.run_option2(), report)
        self.assertEqual(p.calls, ["/api/node-control/installation-status"])
        self.assertEqual(p.live.read_bytes(), live_before)
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)
        for file in (p.stage / host.JOURNAL,
                     p.stage / "unified-foreign-transaction.json"):
            text = file.read_text()
            self.assertNotIn(new_code, text)
            self.assertNotIn("node_secret", text)

    def test_foreign_gateway_drift_after_redeem_blocks_success_without_rekey(self):
        original = self.verify_gateway
        count = [0]
        def transient(scope):
            count[0] += 1
            # Host recovery's verified receipt passes; post-identity
            # independent witness catches the later drift.
            if self.fixture.live.exists():
                return "DRIFT"
            return original(scope)
        self.verify_gateway = transient
        try:
            with self.assertRaises(host.Hold):
                self.run_option2()
        finally:
            self.verify_gateway = original
        self.assertTrue(self.fixture.live.exists())
        secret_before = self.fixture.live.read_bytes()
        self.fixture.calls.clear()
        self.run_option2()
        self.assertEqual(self.fixture.live.read_bytes(), secret_before)
        self.assertEqual(self.fixture.calls,
                         ["/api/node-control/installation-status"])

    def test_no_disposable_capability_or_unsafe_identity_path_never_runs_host(self):
        for change in (
            {"disposable_capability": False},
            {"transport": None},
            {"live_identity": Path("/etc/u-opti/smite/identities/node-identity.json")},
            {"packet_path": self.fixture.state},
            {"gateway_path": Path("/etc/nginx/conf.d/foreign.conf")},
        ):
            with self.subTest(change=change):
                with self.assertRaises((host.Hold, OSError, ValueError)):
                    self.run_option2(**change)
                self.assertEqual(self.events, [])
                self.assert_no_identity()

    def test_preinstalled_sanaei_and_gateway_are_only_reverified(self):
        self.states["sanaei"] = "READY"
        self.states["gateway"] = "READY"
        self.assertEqual(self.run_option2()["phase"],
                         "FOREIGN_OPTION2_OFFLINE_READY")
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)
        self.assertTrue(self.fixture.live.exists())

    def test_expired_code_never_starts_host_or_signed_redemption(self):
        self.fixture.now = self.fixture.doc["expires_at"]+1
        with self.assertRaises(host.Hold):
            self.run_option2()
        self.assertEqual(self.events, [])
        self.assert_no_identity()

    def test_revoked_signed_panel_after_completion_never_regenerates_node_key(self):
        self.run_option2()
        original_key = self.fixture.live.read_bytes()
        self.fixture.calls.clear()
        self.events.clear()
        self.fixture.revoke = True
        with self.assertRaises(ValueError):
            self.run_option2()
        self.assertEqual(self.fixture.live.read_bytes(), original_key)
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)
        self.assertNotIn("/api/foreign-install/redeem", self.fixture.calls)

    def test_corrupted_identity_transaction_journal_cannot_be_redeemed_again(self):
        self.run_option2()
        original_key = self.fixture.live.read_bytes()
        receipt = self.fixture.stage / "unified-foreign-transaction.json"
        doc = json.loads(receipt.read_text())
        doc["phase"] = "UNREVIEWED_RUNTIME_ACTIVATION"
        receipt.write_text(json.dumps(doc))
        receipt.chmod(0o600)
        self.events.clear()
        self.fixture.calls.clear()
        with self.assertRaises(ValueError):
            self.run_option2()
        self.assertEqual(self.fixture.live.read_bytes(), original_key)
        self.assertNotIn("install_sanaei", self.events)
        self.assertNotIn("install_gateway", self.events)
        self.assertNotIn("/api/foreign-install/redeem", self.fixture.calls)

    def test_foreign_scope_switch_after_complete_never_adopts_old_identity(self):
        self.run_option2()
        original_key = self.fixture.live.read_bytes()
        original_doc = dict(self.fixture.doc)
        self.fixture.doc["node_id"] = "foreign-node-other"
        self.fixture.write_packet()
        self.events.clear()
        self.fixture.calls.clear()
        try:
            with self.assertRaises(host.Hold):
                self.run_option2()
            self.assertEqual(self.fixture.live.read_bytes(), original_key)
            self.assertNotIn("install_sanaei", self.events)
            self.assertNotIn("install_gateway", self.events)
            self.assertFalse(self.fixture.calls)
        finally:
            self.fixture.doc = original_doc
            self.fixture.write_packet()

    def test_gateway_drift_after_success_does_not_trigger_rollback_of_completed_stage(self):
        self.run_option2()
        original_key = self.fixture.live.read_bytes()
        self.states["gateway"] = "DRIFT"
        self.events.clear()
        self.fixture.calls.clear()
        with self.assertRaises(host.Hold):
            self.run_option2()
        self.assertEqual(self.fixture.live.read_bytes(), original_key)
        self.assertNotIn("install_gateway", self.events)
        self.assertNotIn("rollback_gateway", self.events)
        self.assertNotIn("rollback_sanaei", self.events)
        self.assertFalse(self.fixture.calls)

    def test_public_cli_remains_status_only_and_never_claims_connected(self):
        source = (ROOT / "modules" /
                  "smite-unified-foreign-host-recovery.py").read_text()
        self.assertIn('parser.add_argument("--status"', source)
        self.assertNotIn('parser.add_argument("--apply"', source)
        self.assertNotIn('parser.add_argument("--activate"', source)
        self.assertNotIn("FOREIGN_CONNECTED=YES", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
