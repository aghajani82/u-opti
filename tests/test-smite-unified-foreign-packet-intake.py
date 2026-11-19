#!/usr/bin/env python3
"""Exact multiline UI JSON -> bounded private Foreign terminal intake."""
import importlib.util
import fcntl
import hashlib
import io
import json
import os
import pty
import select
import termios
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "foreign_packet_intake",
    ROOT / "modules/smite-unified-foreign-packet-intake.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class OperatorPacketIntake(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / "foreign-fixture"
        self.fixture.mkdir(mode=0o700)
        self.stage = self.fixture / "foreign-staging"
        self.stage.mkdir(mode=0o700)
        self.file = self.stage / "foreign-install-packet.json"
        self.now = 1850000000
        self.grant = {
            "protocol": "smi1",
            "panel_url": "https://panel.example.com",
            "node_id": "foreign-node-1234",
            "node_name": "node-kh",
            "origin": "https://kh.example.com:443",
            "control_url": "https://kh.example.com:443/smite-node/" + "a"*32,
            "installation_code": "smi1_" + "b"*43,
            "expires_at": self.now + 7200,
        }

    def operator_paste(self, data=None, **kwargs):
        packet = self.grant if data is None else data
        stream = io.StringIO(json.dumps(packet, indent=2) + "\n\n")
        params = dict(
            target=self.file, expected_panel="https://panel.example.com",
            expected_domain="https://kh.example.com:443",
            expected_node="node-kh", now=self.now,
            disposable_capability=True)
        params.update(kwargs)
        return module.capture_disposable(stream, **params)

    def test_multiline_panel_information_staged_without_secrets_in_result(self):
        out = self.operator_paste()
        self.assertEqual(out, {
            "status":"STAGED_PRIVATE",
            "node_name":"node-kh",
            "expires_at":self.now+7200,
            "connected":False,
        })
        saved=json.loads(self.file.read_text())
        self.assertEqual(saved, self.grant)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.stage.stat().st_mode & 0o777,0o700)
        self.assertNotIn(self.grant["installation_code"], repr(out))
        self.assertFalse((self.fixture/"node-identity.json").exists())

    def test_leading_newlines_from_terminal_paste_are_not_a_packet_terminator(self):
        # Exact field failure: one blank line before pasted JSON previously
        # stopped capture immediately and fed the remaining lines to Bash.
        for prefix in ("\n", "\r\n", "\n\n"):
            with self.subTest(prefix=repr(prefix)):
                if self.file.exists():
                    self.file.unlink()
                source = prefix + json.dumps(self.grant, indent=2) + "\n\n"
                result = module.capture_disposable(
                    io.StringIO(source), target=self.file,
                    expected_panel="https://panel.example.com",
                    expected_domain="https://kh.example.com:443",
                    expected_node="node-kh", now=self.now,
                    disposable_capability=True)
                self.assertEqual(result["status"], "STAGED_PRIVATE")
                self.assertEqual(json.loads(self.file.read_text()), self.grant)
        self.file.unlink()
        # Never allow unlimited empty input or empty-only pseudo-packets.
        for source in ("\n\n\n" + json.dumps(self.grant) + "\n\n", "\n\n"):
            with self.assertRaises(module.Hold):
                module.capture_disposable(io.StringIO(source),
                    target=self.file, expected_panel="https://panel.example.com",
                    expected_domain="https://kh.example.com:443",
                    expected_node="node-kh", now=self.now, disposable_capability=True)
            self.assertFalse(self.file.exists())

    def test_second_paste_never_replaces_private_packet(self):
        self.operator_paste()
        original = self.file.read_bytes()
        data={**self.grant,"installation_code":"smi1_"+"c"*43}
        with self.assertRaises(module.Hold):self.operator_paste(data)
        self.assertEqual(self.file.read_bytes(), original)

    def _owned_host_checkpoint(self, *, phase="GATEWAY_443_VERIFIED"):
        """Existing recovery journal from a verified, non-promoted host stage."""
        original = self.file.read_bytes()
        packet = module.client_module().parse_packet(original)
        (self.stage / "unified-foreign-host.lock").write_bytes(b"")
        (self.stage / "unified-foreign-host.lock").chmod(0o600)
        journal = {
            "schema": 2,
            "scope": packet.scope,
            "expires_at": packet.expires_at,
            "packet_sha256": hashlib.sha256(original).hexdigest(),
            "phase": phase,
        }
        receipt = self.stage / "unified-foreign-host-journal.json"
        receipt.write_text(json.dumps(journal, sort_keys=True))
        receipt.chmod(0o600)
        return receipt

    def _renewed(self, **change):
        renewed = {**self.grant,
                   "installation_code": "smi1_" + "c" * 43,
                   "expires_at": self.now + 14400, **change}
        return self.operator_paste(renewed, now=self.now + 7200,
                                   allow_expired_renewal=True)

    def test_expired_packet_renewal_preserves_owned_checkpoint_and_node_secret(self):
        self.operator_paste()
        checkpoint = self._owned_host_checkpoint()
        original_journal = checkpoint.read_bytes()
        scope = module.client_module().parse_packet(self.file.read_bytes()).scope
        identity = {"schema":1,"scope":scope,"node_secret":"d"*64}
        secret_path = self.stage / "foreign-install-identity.json"
        secret_path.write_text(json.dumps(identity))
        secret_path.chmod(0o600)
        before_identity = secret_path.read_bytes()
        result = self._renewed()
        self.assertEqual(result["status"], "RENEWED_PRIVATE")
        self.assertEqual(result["expires_at"], self.now+14400)
        self.assertFalse(result["connected"])
        self.assertNotIn(self.grant["installation_code"], repr(result))
        self.assertEqual(json.loads(self.file.read_text())["installation_code"],
                         "smi1_" + "c" * 43)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(checkpoint.read_bytes(), original_journal)
        self.assertEqual(secret_path.read_bytes(), before_identity)
        self.assertFalse(list(self.stage.glob(".packet-renew-*")))
        # The existing recovery flow reads this packet and can adopt its
        # newer expiry after independently re-verifying host witnesses.

    def original_precore_owner(self):
        def load(name, path):
            spec = importlib.util.spec_from_file_location(
                name, ROOT/"modules"/path)
            result = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = result
            spec.loader.exec_module(result)
            return result
        owner = load("uopti_exact_rc9_core_owner_pre_packet_test",
                     "smite-rc6-install-journal.py")
        promotion = load("uopti_exact_promotion_owner_pre_packet_test",
                         "smite-foreign-install-promotion.py")
        return owner, promotion, owner.Journal(root=self.root)

    def test_root_precore_reissue_verifier_is_read_only_and_never_creates_core(self):
        self.operator_paste()
        owner, promotion, journal = self.original_precore_owner()
        core_receipt = journal.path
        self.assertFalse(core_receipt.exists())
        packet_before = self.file.read_bytes()
        with promotion.private_directory(self.stage) as fd:
            result = module._original_unstarted_core_packet_witness(
                journal, owner, promotion, fd, module.client_module())
        self.assertTrue(result)
        self.assertFalse(core_receipt.exists())
        self.assertEqual(self.file.read_bytes(), packet_before)
        self.assertFalse((self.stage/"foreign-install-identity.json").exists())

    def test_root_precore_reissue_refuses_any_previous_stage_or_core_path(self):
        self.operator_paste()
        owner, promotion, journal = self.original_precore_owner()
        candidate = (
            self.stage/"unified-foreign-transaction.json",
            self.stage/"foreign-install-identity.json",
            self.stage/"unified-foreign-host-journal.json",
            self.stage/"foreign-install-promotion-prepared.json",
        )
        for path in candidate:
            path.write_text("{}")
            path.chmod(0o600)
            try:
                with promotion.private_directory(self.stage) as fd:
                    with self.subTest(receipt=path.name), self.assertRaises(module.Hold):
                        module._original_unstarted_core_packet_witness(
                            journal, owner, promotion, fd, module.client_module())
            finally:
                path.unlink()
        target = self.root/"opt/smite-node"
        target.mkdir(parents=True, mode=0o700)
        try:
            with promotion.private_directory(self.stage) as fd:
                with self.assertRaises(module.Hold):
                    module._original_unstarted_core_packet_witness(
                        journal, owner, promotion, fd, module.client_module())
        finally:
            target.rmdir()
            target.parent.rmdir()
        journal.folder.mkdir(parents=True, mode=0o700)
        journal.path.write_text("{}")
        journal.path.chmod(0o600)
        with promotion.private_directory(self.stage) as fd:
            self.assertFalse(module._original_unstarted_core_packet_witness(
                journal, owner, promotion, fd, module.client_module()))
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_no_renewal_before_expiry_or_without_owned_checkpoint(self):
        self.operator_paste()
        original = self.file.read_bytes()
        with self.assertRaises(module.Hold):
            self.operator_paste(
                {**self.grant,"installation_code":"smi1_"+"c"*43},
                allow_expired_renewal=True)
        with self.assertRaises(module.Hold):
            self._renewed()
        self.assertEqual(self.file.read_bytes(), original)

    def test_exact_repaste_of_still_valid_packet_is_idempotent(self):
        self.operator_paste()
        original = self.file.read_bytes()
        result = self.operator_paste(allow_expired_renewal=True)
        self.assertEqual(result["status"], "ALREADY_STAGED_PRIVATE")
        self.assertEqual(self.file.read_bytes(), original)
        self.assertFalse((self.stage/"unified-foreign-host-journal.json").exists())

    def test_renewal_refuses_scope_change_code_reuse_and_bad_checkpoint(self):
        self.operator_paste()
        checkpoint = self._owned_host_checkpoint()
        original = self.file.read_bytes()
        cases = (
            {"node_id": "foreign-replacement"},
            {"origin": "https://wrong.example.com:443",
             "control_url": "https://wrong.example.com:443/smite-node/"+"a"*32},
            {"panel_url":"https://different.example.com:443"},
            {"control_url":"https://kh.example.com:443/smite-node/"+"d"*32},
            {"installation_code":self.grant["installation_code"]},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(module.Hold):
                self._renewed(**changes)
            self.assertEqual(self.file.read_bytes(), original)
        prior = checkpoint.read_bytes()
        checkpoint.write_text("{}")
        with self.assertRaises(module.Hold):
            self._renewed()
        self.assertEqual(self.file.read_bytes(), original)
        checkpoint.write_bytes(prior)
        checkpoint.chmod(0o600)
        stored = json.loads(prior)
        stored["packet_sha256"] = "0"*64
        checkpoint.write_text(json.dumps(stored))
        with self.assertRaises(module.Hold):
            self._renewed()
        self.assertEqual(self.file.read_bytes(), original)

    def test_renewal_refuses_promotion_and_untrusted_secret(self):
        self.operator_paste()
        self._owned_host_checkpoint()
        original = self.file.read_bytes()
        prepared = self.stage/"foreign-install-promotion-prepared.json"
        prepared.write_text("{}")
        prepared.chmod(0o600)
        with self.assertRaises(module.Hold): self._renewed()
        prepared.unlink()
        identity = self.stage/"foreign-install-identity.json"
        identity.write_text('{"schema":1,"scope":{},"node_secret":"spoof"}')
        identity.chmod(0o600)
        with self.assertRaises(module.Hold): self._renewed()
        self.assertEqual(self.file.read_bytes(), original)

    def test_renewal_refuses_symlink_hardlink_and_locked_stage(self):
        self.operator_paste()
        self._owned_host_checkpoint()
        original = self.file.read_bytes()
        linked = self.fixture / "packet-original"
        linked.write_bytes(original)
        linked.chmod(0o600)
        self.file.unlink()
        os.link(linked, self.file)
        with self.assertRaises(module.Hold): self._renewed()
        self.file.unlink()
        self.file.symlink_to(linked)
        with self.assertRaises(module.Hold): self._renewed()
        self.file.unlink()
        self.file.write_bytes(original)
        self.file.chmod(0o600)
        lock = self.stage/"unified-foreign-host.lock"
        with open(lock, "rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(module.Hold): self._renewed()
        self.assertEqual(self.file.read_bytes(), original)

    def test_renewed_grant_is_adopted_by_existing_host_recovery_without_reinstall(self):
        self.operator_paste()
        journal = self._owned_host_checkpoint()
        self.assertEqual(self._renewed()["status"], "RENEWED_PRIVATE")
        spec = importlib.util.spec_from_file_location(
            "uopti_packet_renew_host_recovery",
            ROOT / "modules/smite-unified-foreign-host-recovery.py")
        host = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = host
        spec.loader.exec_module(host)
        calls = []
        def only_verify(label, result):
            def probe(_scope):
                calls.append(label)
                return result
            return probe
        def forbidden(_scope):
            self.fail("A renewed grant must not reinstall an existing stage")
        result = host.rehearse(
            directory=self.stage, packet_path=self.file,
            now=self.now+7200,
            expected_panel="https://panel.example.com:443",
            expected_foreign="https://kh.example.com:443",
            expected_node="node-kh",
            verify_core=only_verify("core", True),
            verify_sanaei=only_verify("sanaei", "READY"),
            verify_gateway=only_verify("gateway", "READY"),
            install_sanaei=forbidden, install_gateway=forbidden,
            disposable_capability=True)
        self.assertEqual(result["phase"], "GATEWAY_443_VERIFIED")
        self.assertFalse(result["connected"])
        self.assertGreaterEqual(calls.count("core"), 2)
        self.assertEqual(json.loads(journal.read_text())["expires_at"],
                         self.now+14400)
        self.assertEqual(json.loads(journal.read_text())["packet_sha256"],
                         hashlib.sha256(self.file.read_bytes()).hexdigest())

    def test_selected_hidden_pty_renewal_keeps_echo_off_and_checkpoint(self):
        self.operator_paste()
        checkpoint = self._owned_host_checkpoint()
        original = checkpoint.read_bytes()
        renewed = {**self.grant,
                   "installation_code":"smi1_"+"c"*43,
                   "expires_at":self.now+14400}
        master, slave = pty.openpty()
        initial = termios.tcgetattr(slave)
        try:
            with os.fdopen(os.dup(slave), "r", encoding="utf-8",
                           newline="") as tty:
                def paste():
                    self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
                    os.write(master,
                             (json.dumps(renewed)+"\n\n").encode("utf-8"))
                result = module.capture_selected_hidden_tty(
                    tty, target=self.file, now=self.now+7200,
                    confirm_scope=lambda s: s["node_id"] == self.grant["node_id"],
                    ready=paste)
            self.assertEqual(result["status"], "RENEWED_PRIVATE")
            self.assertFalse(result["connected"])
            self.assertEqual(checkpoint.read_bytes(), original)
            self.assertEqual(termios.tcgetattr(slave), initial)
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                reflected = os.read(master, 8192)
                self.assertNotIn(renewed["installation_code"].encode(), reflected)
        finally:
            self.assertEqual(termios.tcgetattr(slave), initial)
            os.close(master)
            os.close(slave)

    def test_expired_or_not_yet_issued_code_refused_before_write(self):
        for stamp in (self.now-1, self.now, self.now+7201):
            with self.subTest(stamp=stamp),self.assertRaises(module.Hold):
                self.operator_paste({**self.grant,"expires_at":stamp})
            self.assertFalse(self.file.exists())

    def test_bad_node_domain_and_panel_metadata_never_saved(self):
        for changes in (
            {"node_name":"other-node"},
            {"origin":"https://other.example.com:443",
             "control_url":"https://other.example.com:443/smite-node/"+"a"*32},
            {"control_url":"https://kh.example.com:443/smite-node/"+"c"*32,
             "installation_code":"invalid"},
            {"panel_url":"https://other.example.com:443"},
            {"protocol":"legacy"},
        ):
            with self.subTest(changes=sorted(changes)),self.assertRaises(module.Hold):
                self.operator_paste({**self.grant, **changes})
            self.assertFalse(self.file.exists())

    def test_wrong_local_expected_domain_or_name_refused(self):
        for override in (
            {"expected_node":"different"},
            {"expected_panel":"https://wrong.example.com"},
            {"expected_domain":"https://wrong.example.com:443"},
        ):
            with self.subTest(override=override),self.assertRaises(module.Hold):
                self.operator_paste(**override)
            self.assertFalse(self.file.exists())

    def test_unfinished_multiline_and_duplicate_json_refused(self):
        json_body=json.dumps(self.grant,indent=2)
        bad = (
            json_body+"\n", # no explicit blank line terminator
            json_body.replace('"protocol": "smi1"', '"protocol": "smi1", "protocol": "smi1"')+"\n\n",
            "{"+"\n"*45+"}\n\n",
            "X"*9000+"\n\n",
            json_body + "\x00\n\n",
        )
        for source in bad:
            with self.subTest(size=len(source)),self.assertRaises(module.Hold):
                module.capture_disposable(io.StringIO(source),target=self.file,
                    expected_panel="https://panel.example.com",
                    expected_domain="https://kh.example.com:443",
                    expected_node="node-kh",now=self.now,disposable_capability=True)
            self.assertFalse(self.file.exists())

    def test_no_fixture_capability_and_no_user_controlled_host_location(self):
        with self.assertRaises(module.Hold):
            self.operator_paste(disposable_capability=False)
        with self.assertRaises(module.Hold):
            self.operator_paste(target=Path("/etc/u-opti/smite/foreign-staging/foreign-install-packet.json"))
        with self.assertRaises(module.Hold):
            self.operator_paste(target=self.fixture/"other.json")
        self.assertFalse(self.file.exists())

    def test_reject_symlink_or_insecure_parent(self):
        self.stage.chmod(0o755)
        with self.assertRaises(module.Hold):self.operator_paste()
        self.stage.chmod(0o700)
        self.fixture.chmod(0o777)
        with self.assertRaises(module.Hold):self.operator_paste()
        self.fixture.chmod(0o700)
        self.stage.rmdir()
        other=self.fixture/"elsewhere"
        other.mkdir(mode=0o700)
        self.stage.symlink_to(other, target_is_directory=True)
        with self.assertRaises(module.Hold):self.operator_paste()
        self.assertFalse(self.file.exists())

    def test_existing_hardlink_or_symlink_target_refused(self):
        bad=self.fixture/"previous"
        bad.write_text("secret")
        bad.chmod(0o600)
        os.link(bad,self.file)
        with self.assertRaises(module.Hold):self.operator_paste()
        self.file.unlink()
        self.file.symlink_to(bad)
        with self.assertRaises(module.Hold):self.operator_paste()
        self.assertEqual(bad.read_text(),"secret")

    def test_capture_failure_does_not_print_a_credential(self):
        secret=self.grant["installation_code"]
        import contextlib
        output=io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(module.Hold) as err:
                self.operator_paste({**self.grant, "node_name":"other"})
        self.assertNotIn(secret,output.getvalue()+str(err.exception))
        self.assertNotIn("node_secret",output.getvalue()+str(err.exception))

    def _hidden_paste(self, packet, approve):
        """Real Linux PTY: paste secrets AFTER echo has been disabled."""
        master, slave = pty.openpty()
        original = termios.tcgetattr(slave)
        scopes = []
        def review(scope):
            scopes.append(dict(scope))
            return approve(scope)
        try:
            with os.fdopen(os.dup(slave), "r", encoding="utf-8", newline="") as stream:
                data = (json.dumps(packet, indent=2) + "\n\n").encode("utf-8")
                def send_after_echo_off():
                    assert not (termios.tcgetattr(slave)[3] & termios.ECHO)
                    os.write(master, data)
                result = module.capture_disposable_hidden_tty(
                    stream, confirm_scope=review, ready=send_after_echo_off,
                    target=self.file, expected_panel="https://panel.example.com",
                    expected_domain="https://kh.example.com:443",
                    expected_node="node-kh", now=self.now,
                    disposable_capability=True)
            self.assertEqual(termios.tcgetattr(slave), original)
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                # Nothing typed during the protected read may echo to terminal.
                reflected = os.read(master, 8192)
                self.assertNotIn(self.grant["installation_code"].encode(), reflected)
                self.assertNotIn(b'"node_secret"', reflected)
            return result, scopes
        finally:
            self.assertEqual(termios.tcgetattr(slave), original)
            os.close(master)
            os.close(slave)

    def test_real_pty_leading_blank_paste_only_after_echo_off(self):
        master, slave = pty.openpty()
        saved = termios.tcgetattr(slave)
        scopes = []
        try:
            with os.fdopen(os.dup(slave), "r", encoding="utf-8", newline="") as tty:
                def send():
                    self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
                    os.write(master, ("\n" + json.dumps(self.grant, indent=2)
                                      + "\n\n").encode("utf-8"))
                result = module.capture_disposable_hidden_tty(
                    tty, target=self.file, now=self.now,
                    expected_panel="https://panel.example.com",
                    expected_domain="https://kh.example.com:443",
                    expected_node="node-kh", disposable_capability=True,
                    confirm_scope=lambda scope: scopes.append(scope) or True,
                    ready=send)
            self.assertEqual(result["status"], "STAGED_PRIVATE")
            self.assertEqual(len(scopes), 1)
            self.assertEqual(json.loads(self.file.read_text()), self.grant)
            self.assertEqual(termios.tcgetattr(slave), saved)
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                self.assertNotIn(self.grant["installation_code"].encode(),
                                 os.read(master, 8192))
        finally:
            os.close(master)
            os.close(slave)

    def test_real_pty_single_hidden_paste_and_nonsecret_confirmation(self):
        output, scopes = self._hidden_paste(self.grant, approve=lambda _: True)
        self.assertEqual(output["status"], "STAGED_PRIVATE")
        self.assertIs(output["connected"], False)
        self.assertEqual(json.loads(self.file.read_text()), self.grant)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(scopes), 1)
        self.assertNotIn("installation_code", scopes[0])
        self.assertNotIn(self.grant["installation_code"], repr(scopes))
        self.assertEqual(scopes[0]["node_name"], "node-kh")
        self.assertEqual(scopes[0]["control_url"], self.grant["control_url"])

    def test_real_pty_operator_denial_stages_nothing(self):
        with self.assertRaises(module.Hold):
            self._hidden_paste(self.grant, approve=lambda _: False)
        self.assertFalse(self.file.exists())

    def test_real_pty_wrong_packet_stages_nothing_and_restores_echo(self):
        wrong = {**self.grant, "origin": "https://wrong.example.com:443",
                 "control_url": "https://wrong.example.com:443/smite-node/"+"a"*32}
        with self.assertRaises(module.Hold):
            self._hidden_paste(wrong, approve=lambda _: True)
        self.assertFalse(self.file.exists())

    def test_terminal_restored_after_cancelled_keyboard_input(self):
        master, slave = pty.openpty()
        original = termios.tcgetattr(slave)
        class Interrupted:
            def fileno(self): return slave
            def readline(self, *_): raise KeyboardInterrupt()
        try:
            with self.assertRaises(KeyboardInterrupt):
                module.read_hidden_tty(Interrupted())
            self.assertEqual(termios.tcgetattr(slave), original)
        finally:
            os.close(master); os.close(slave)

    def test_non_terminal_source_never_prompts_or_captures(self):
        with self.assertRaises(module.Hold):
            module.capture_disposable_hidden_tty(
                io.StringIO(json.dumps(self.grant)+"\n\n"),
                confirm_scope=lambda _: True,
                target=self.file, expected_panel="https://panel.example.com",
                expected_domain="https://kh.example.com:443",
                expected_node="node-kh", now=self.now,
                disposable_capability=True)
        self.assertFalse(self.file.exists())

    def test_selected_hidden_single_paste_reuses_same_scope_no_echo(self):
        master, slave = pty.openpty()
        original = termios.tcgetattr(slave)
        scopes = []
        try:
            with os.fdopen(os.dup(slave), "r", encoding="utf-8", newline="") as tty:
                def paste_after_echo_disabled():
                    self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
                    os.write(master, (json.dumps(self.grant, indent=2)+"\n\n").encode())
                result = module.capture_selected_hidden_tty(
                    tty, target=self.file, now=self.now,
                    confirm_scope=lambda s: scopes.append(dict(s)) or True,
                    ready=paste_after_echo_disabled)
            self.assertEqual(result["status"],"STAGED_PRIVATE")
            self.assertFalse(result["connected"])
            self.assertEqual(json.loads(self.file.read_text()),self.grant)
            self.assertEqual(len(scopes),1)
            self.assertEqual(scopes[0]["node_name"],"node-kh")
            self.assertNotIn("installation_code",repr(scopes))
            self.assertEqual(termios.tcgetattr(slave),original)
            readable,_,_=select.select([master],[],[],0.05)
            if readable:
                self.assertNotIn(self.grant["installation_code"].encode(),
                                 os.read(master,8192))
        finally:
            self.assertEqual(termios.tcgetattr(slave),original)
            os.close(master);os.close(slave)

    def test_real_clock_is_read_after_paste_and_after_confirmation(self):
        issued = self.now + 180
        packet = dict(self.grant, expires_at=issued + 7200)
        timestamps = iter((self.now, issued, issued + 1))
        master, slave = pty.openpty()
        try:
            with os.fdopen(os.dup(slave), "r", encoding="utf-8", newline="") as tty:
                def send():
                    self.assertEqual(module.time.time(), self.now)
                    os.write(master, (json.dumps(packet) + "\n\n").encode())
                with patch.object(module.time, "time", side_effect=lambda: next(timestamps)):
                    result = module.capture_selected_hidden_tty(
                        tty, target=self.file, now=None, ready=send,
                        confirm_scope=lambda _: True)
            self.assertEqual(result["status"], "STAGED_PRIVATE")
            self.assertEqual(json.loads(self.file.read_text()), packet)
        finally:
            os.close(master); os.close(slave)

    def test_expired_grant_never_offers_operator_confirmation(self):
        master,slave=pty.openpty()
        confirms=[]
        try:
            with os.fdopen(os.dup(slave),"r",encoding="utf-8",newline="") as tty:
                def send():
                    self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
                    os.write(master,(json.dumps(self.grant)+"\n\n").encode())
                with self.assertRaises(module.Hold):
                    module.capture_selected_hidden_tty(
                        tty,target=self.file,now=self.now+7201,
                        confirm_scope=lambda scope:confirms.append(scope) or True,
                        ready=send)
            self.assertEqual(confirms,[])
            self.assertFalse(self.file.exists())
        finally:
            os.close(master);os.close(slave)

    def test_wrong_fixed_disposable_scope_rejects_before_confirmation(self):
        master,slave=pty.openpty()
        confirms=[]
        try:
            with os.fdopen(os.dup(slave),"r",encoding="utf-8",newline="") as tty:
                def send():
                    self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
                    os.write(master,(json.dumps(self.grant)+"\n\n").encode())
                with self.assertRaises(module.Hold):
                    module.capture_disposable_hidden_tty(
                        tty,target=self.file,now=self.now,ready=send,
                        expected_panel="https://other.example.org:443",
                        expected_domain="https://kh.example.com:443",
                        expected_node="node-kh",disposable_capability=True,
                        confirm_scope=lambda scope:confirms.append(scope) or True)
            self.assertEqual(confirms,[])
            self.assertFalse(self.file.exists())
        finally:
            os.close(master);os.close(slave)

    def test_selected_no_tty_expired_and_cancel_never_stage(self):
        with self.assertRaises(module.Hold):
            module.capture_selected_hidden_tty(
                io.StringIO(json.dumps(self.grant)+"\n\n"),
                target=self.file, now=self.now, confirm_scope=lambda _:True)
        master,slave=pty.openpty()
        try:
            def attempt(confirmed,when):
                with os.fdopen(os.dup(slave),"r",encoding="utf-8",newline="") as tty:
                    def paste():
                        self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
                        os.write(master,(json.dumps(self.grant)+"\n\n").encode())
                    return module.capture_selected_hidden_tty(
                        tty,target=self.file,now=when,
                        confirm_scope=lambda _:confirmed,ready=paste)
            with self.assertRaises(module.Hold):attempt(False,self.now)
            self.assertFalse(self.file.exists())
            with self.assertRaises(module.Hold):attempt(True,self.now+7201)
            self.assertFalse(self.file.exists())
        finally:
            os.close(master);os.close(slave)
        # A CLI action without a real terminal may never stage credentials.
        cmd=[sys.executable,"-B",
             str(ROOT/"modules/smite-unified-foreign-packet-intake.py"),
             "--capture-selected-foreign",str(self.root)]
        check=subprocess.run(cmd,input="do not accept stdin\n",text=True,
                             capture_output=True)
        self.assertEqual(check.returncode,2)
        self.assertFalse(self.file.exists())
        self.assertNotIn(self.grant["installation_code"],
                         check.stdout+check.stderr)

    def test_reissued_iran_panel_code_uses_original_core_owner_without_new_node(self):
        # The IR Panel issues a replacement two-hour code for the SAME
        # reserved Node and retains its original control_url. The original
        # RC9 Core journal must prove the unchanged owner and actual paused/
        # strict/R-O runtime, not the expired bearer code's TTL.
        from types import SimpleNamespace

        self.operator_paste()
        packet = module.client_module().parse_packet(self.file.read_bytes())
        class CoreHold(RuntimeError):
            pass
        class OriginalOwner:
            def __init__(self):
                self.resume_calls = []
                self.record = {
                    "source": "signed-rc9", "role": "foreign",
                    "foreign_resumable_version": 1, "state": "COMMITTED",
                    "id": "uopti_rc6_" + "a" * 32,
                }
                self.scope = {
                    "panel_domain": "panel.example.com",
                    "foreign_domain": "kh.example.com",
                    "node_name": "node-kh",
                    "node_id": self_id,
                    "control_path": "/smite-node/" + "a" * 32,
                }
            def load(self):
                return dict(self.record)
            def foreign_inputs(self, doc):
                return dict(self.scope)
            def foreign_resume(self, *, attached_sanaei=False, installer_pid=None):
                self.resume_calls.append((attached_sanaei, installer_pid))
                if not attached_sanaei:
                    raise CoreHold("Sanaei already attached, do not undo it")
                return "CORE_COMMITTED", self.record["id"]

        self_id = packet.scope["node_id"]
        original = OriginalOwner()
        owner = SimpleNamespace(RC9_SOURCE="signed-rc9", Hold=CoreHold)
        self.assertEqual(
            module._original_core_reissue_witness(
                original, owner, packet, installer_pid=6123),
            "CORE_COMMITTED")
        self.assertEqual(original.resume_calls, [(False, 6123), (True, 6123)])
        # Switching the reserved Node or its HTTPS/443 path must HOLD
        # without replacing the on-disk original grant.
        saved = self.file.read_bytes()
        cases = [
            ("node_id", "another-foreign-node"),
            ("foreign_domain", "other.example.com"),
            ("control_path", "/smite-node/" + "b" * 32),
            ("source", "unsigned-source"),
            ("state", "ROLLING_BACK"),
        ]
        for key, value in cases:
            with self.subTest(key=key):
                previous_scope = dict(original.scope)
                previous_record = dict(original.record)
                if key in original.scope:
                    original.scope[key] = value
                else:
                    original.record[key] = value
                with self.assertRaises(module.Hold):
                    module._original_core_reissue_witness(
                        original, owner, packet, installer_pid=6123)
                original.scope = previous_scope
                original.record = previous_record
                self.assertEqual(self.file.read_bytes(), saved)

    def test_reissue_refuses_foreign_core_without_runtime_witness(self):
        from types import SimpleNamespace

        self.operator_paste()
        packet = module.client_module().parse_packet(self.file.read_bytes())
        class CoreHold(RuntimeError):
            pass
        class UnverifiedOwner:
            def load(self):
                return {
                    "source": "signed-rc9", "role": "foreign",
                    "foreign_resumable_version": 1, "state": "COMMITTED",
                    "id": "uopti_rc6_" + "a"*32,
                }
            def foreign_inputs(self, _doc):
                return {
                    "panel_domain": "panel.example.com",
                    "foreign_domain": "kh.example.com",
                    "node_name": "node-kh",
                    "node_id": packet.scope["node_id"],
                    "control_path": "/smite-node/" + "a"*32,
                }
            def foreign_resume(self, **_kwargs):
                raise CoreHold("Foreign Node/Compose is unverified")
        with self.assertRaises(module.Hold):
            module._original_core_reissue_witness(
                UnverifiedOwner(),
                SimpleNamespace(RC9_SOURCE="signed-rc9", Hold=CoreHold),
                packet, installer_pid=100)

    def test_owned_host_packet_cannot_be_staged_without_reviewed_release(self):
        # The exact durable owner is not interchangeable with the
        # disposable fixture. No credential, enrollment or host write is
        # permitted under the signed RC9 trial release (approval=false).
        payload = json.dumps(self.grant) + "\n\n"
        with self.assertRaises(module.Hold):
            module.capture_disposable(
                io.StringIO(payload),
                target=module._SELECTED_ROOT_PACKET,
                expected_panel=self.grant["panel_url"],
                expected_domain=self.grant["origin"],
                expected_node=self.grant["node_name"],
                now=self.now, selected_capability=True)
        with self.assertRaises(module.Hold):
            module.capture_disposable(
                io.StringIO(payload), target=self.file,
                expected_panel=self.grant["panel_url"],
                expected_domain=self.grant["origin"],
                expected_node=self.grant["node_name"],
                now=self.now, selected_capability=True,
                disposable_capability=True)
        with self.assertRaises(module.Hold):
            module.capture_selected_hidden_tty(
                io.StringIO(payload),
                target=module._SELECTED_ROOT_PACKET, now=self.now,
                selected_host=True, confirm_scope=lambda _: True)
        self.assertFalse(self.file.exists())

    def test_owned_capture_cli_is_release_hold_without_tty_or_secrets(self):
        code = ROOT / "modules/smite-unified-foreign-packet-intake.py"
        result = subprocess.run(
            [sys.executable, "-B", str(code), "--capture-owned-foreign"],
            input=json.dumps(self.grant) + "\n\n",
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("FOREIGN_PACKET=STAGED_PRIVATE", result.stdout)
        self.assertIn("Foreign Panel installation information not admitted",
                      result.stderr)
        self.assertNotIn(self.grant["installation_code"],
                         result.stdout + result.stderr)
        self.assertFalse(self.file.exists())

    def test_cli_status_only_and_never_activates(self):
        code=ROOT/"modules/smite-unified-foreign-packet-intake.py"
        check=subprocess.run([sys.executable,"-B",str(code),"--status"],
            capture_output=True,text=True,check=True)
        self.assertIn("REAL_HOST_CAPTURE=NOT_AUTHORIZED",check.stdout)
        self.assertIn("FOREIGN_CONNECTED=NOT_PROVEN",check.stdout)
        denied=subprocess.run([sys.executable,"-B",str(code),"--capture"],
            capture_output=True,text=True)
        self.assertNotEqual(denied.returncode,0)


if __name__=="__main__":
    unittest.main(verbosity=2)
