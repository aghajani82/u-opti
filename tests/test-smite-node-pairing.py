#!/usr/bin/env python3
"""Offline secure Smite Node pairing preview tests (no network/VPS)."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
import hashlib
import hmac
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "modules/smite-node-pairing.py"
spec = importlib.util.spec_from_file_location("uopti_pairing_preview", HELPER)
pairing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pairing)


class PreviewTests(unittest.TestCase):
    def test_exact_https_origin(self):
        self.assertEqual(
            pairing.secure_endpoint("https://iran01.kolbe1.ir:443/"),
            "https://iran01.kolbe1.ir/api/node-pairing/redeem",
        )
        bad = (
            "http://iran01.kolbe1.ir", "https://iran01.kolbe1.ir:8888",
            "https://iran01.kolbe1.ir:8000", "https://127.0.0.1",
            "https://user:pass@iran01.kolbe1.ir",
            "https://iran01.kolbe1.ir?token=leak",
            "https://iran01.kolbe1.ir/api/nodes",
            "https://iran01.kolbe1.ir/#fragment", "https://localhost",
            "https://iran01.kolbe1.ir:bad",
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(pairing.WizardHold):
                pairing.secure_endpoint(value)

    def test_standard_only_and_role(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state"
            path.write_text(
                "SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n"
                "SMITE_PANEL_DOMAIN=iran01.kolbe1.ir\n"
            )
            self.assertEqual(pairing._determine_role(pairing.state_values(path)), "foreign")
            path.write_text("SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=private\n")
            with self.assertRaises(pairing.WizardHold):
                pairing.state_values(path)

    def test_private_exclusive_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder) / "identity"
            parent.mkdir(mode=0o700)
            path = parent / "node-identity.json"
            node_id = "bbbbbbbb-1111-2222-3333-444444444444"
            pairing.store_identity(path, node_id, "a" * 64)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text())["node_secret"], "a" * 64)
            with self.assertRaises(pairing.WizardHold):
                pairing.store_identity(path, node_id, "b" * 64)
            self.assertEqual(json.loads(path.read_text())["node_secret"], "a" * 64)

    def test_reject_world_readable_identity_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "open"
            path.mkdir(mode=0o755)
            with self.assertRaises(pairing.WizardHold):
                pairing.store_identity(path / "node-identity.json", "node-abcdefgh", "f" * 64)
            link = Path(folder) / "symlink"
            link.symlink_to(path, target_is_directory=True)
            with self.assertRaises(pairing.WizardHold):
                pairing.prepare_store(link)

    def test_tls_validated_post_and_no_redirect_or_proxy(self):
        with tempfile.TemporaryDirectory() as folder:
            private = Path(folder) / "identities"
            private.mkdir(mode=0o700)
            target = private / "node-identity.json"
            node_id = "node-uniquekey"
            code = "smn1_" + "X" * 43
            secret = "c" * 64
            invoked = []

            class Response:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self, maximum):
                    self_test.assertEqual(maximum, 8193)
                    return json.dumps({"node_id": node_id, "node_secret": secret}).encode()
            self_test = self

            class Opener:
                def open(self, req, timeout):
                    self_test.assertEqual(req.full_url, "https://iran01.kolbe1.ir/api/node-pairing/redeem")
                    self_test.assertNotIn(code, req.full_url)
                    self_test.assertEqual(json.loads(req.data)["pairing_code"], code)
                    invoked.append(timeout)
                    return Response()

            with patch.object(pairing.request, "build_opener", return_value=Opener()) as build:
                with patch.object(pairing.ssl, "create_default_context", return_value=Mock()) as tls:
                    with patch("sys.stdout", io.StringIO()) as display:
                        result = pairing.redeem(
                            panel_url="https://iran01.kolbe1.ir",
                            pairing_code=code, node_id=node_id,
                            role="foreign", destination=target,
                        )
                    self.assertEqual(display.getvalue(), "")
                    self.assertEqual(result, node_id)
                    self.assertTrue(invoked)
                    tls.assert_called_once_with()
                    args = build.call_args.args
                    self.assertEqual(args[0].proxies, {})
                    self.assertIsInstance(args[2], pairing.NoRedirect)
                    self.assertIsInstance(args[1], pairing.request.HTTPSHandler)
            self.assertEqual(json.loads(target.read_text())["node_secret"], secret)
            with self.assertRaises(pairing.WizardHold):
                pairing.redeem(
                    panel_url="https://iran01.kolbe1.ir",
                    pairing_code=code, node_id=node_id,
                    role="foreign", destination=target,
                )

    def test_preview_network_off_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state"
            path.write_text(
                "SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n"
                "SMITE_PANEL_DOMAIN=iran01.kolbe1.ir\n"
            )
            with patch.dict(os.environ, {"UOPTI_SMITE_PAIRING_PREVIEW": ""}):
                with patch.object(pairing, "redeem") as network:
                    with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
                        rc = pairing.run(["--redeem-preview", "--state-path", str(path)])
                    self.assertEqual(rc, 2)
                    network.assert_not_called()

    def test_field_trial_env_update_and_exact_pairing_location(self):
        raw = (
            b"SMITE_NODE_REGISTRATION_MODE=signed\n"
            b"SMITE_PANEL_AGENT_AUTH_MODE=signed\n"
            b"SMITE_NODE_PAIRING_PREVIEW_ENABLED=false\n"
        )
        updated = pairing._env_update(raw, {
            "SMITE_NODE_PAIRING_PREVIEW_ENABLED": "true",
            "SMITE_NODE_PAIRING_MASTER_KEY": "A" * 43 + "=",
            "SMITE_NODE_PAIRING_INGRESS_TOKEN": "b" * 64,
        })
        self.assertEqual(updated.count(b"SMITE_NODE_PAIRING_PREVIEW_ENABLED="), 1)
        self.assertIn(b"SMITE_NODE_PAIRING_PREVIEW_ENABLED=true", updated)
        self.assertIn(b"SMITE_NODE_PAIRING_MASTER_KEY=", updated)
        self.assertIn(b"SMITE_NODE_PAIRING_INGRESS_TOKEN=", updated)

        location = pairing._render_pairing_location()
        self.assertIn("location = /api/node-pairing/redeem", location)
        self.assertIn("include /etc/nginx/u-opti-smite-pairing-secret.conf;", location)
        self.assertIn("proxy_pass http://127.0.0.1:8000;", location)
        self.assertIn("access_log off;", location)
        self.assertNotIn("node_secret", location)
        self.assertNotIn("pairing_code", location)

    def test_panel_signed_schema_migration_and_activation_preflight(self):
        with patch.object(
            pairing, "_run", return_value="PANEL_SIGNED_SCHEMA=READY"
        ) as runner:
            pairing._ensure_panel_signed_registration_schema()
        command = runner.call_args.args[0]
        self.assertEqual(command[:4], ["docker", "exec", "smite-panel", "python3"])
        script = command[-1]
        self.assertIn("u-opti-pre-signed-registration.bak", script)
        self.assertIn("source.backup(target)", script)
        self.assertIn("initialize_schema(db)", script)
        self.assertIn("initialize_replay_schema(db)", script)
        self.assertIn("smite_node_inbound_nonces", script)
        self.assertNotIn("node_secret", script)

        with patch.object(
            pairing, "_run",
            return_value="PANEL_SIGNED_REGISTRATION_SCHEMA=READY",
        ):
            pairing._require_panel_signed_registration_schema()
        with patch.object(
            pairing, "_run",
            return_value="PANEL_SIGNED_REGISTRATION_SCHEMA=MISSING",
        ):
            with self.assertRaisesRegex(
                pairing.WizardHold, "signed-registration replay schema is missing"
            ):
                pairing._require_panel_signed_registration_schema()

        source = HELPER.read_text()
        enable_start = source.index("def enable_panel_field_trial")
        activate_start = source.index("def activate_ir_node_field_trial")
        enable_body = source[enable_start:activate_start]
        activate_body = source[activate_start:source.index("\ndef ", activate_start + 5)]
        self.assertIn("_ensure_panel_signed_registration_schema()", enable_body)
        self.assertIn("_require_panel_signed_registration_schema()", activate_body)
        self.assertIn("PANEL_SIGNED_REGISTRATION_REPLAY_SCHEMA=READY", enable_body)

    def test_private_pairing_secret_store_never_prints_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            parent = root / "smite"
            parent.mkdir(mode=0o700)
            private = parent / "pairing"
            secret_file = private / "panel-pairing-secrets.json"
            with (
                patch.object(pairing, "PAIRING_PRIVATE_DIR", private),
                patch.object(pairing, "PAIRING_SECRETS", secret_file),
                patch("sys.stdout", io.StringIO()) as display,
            ):
                first = pairing._pairing_secrets()
                second = pairing._pairing_secrets()
            self.assertEqual(first, second)
            self.assertEqual(display.getvalue(), "")
            self.assertEqual(stat.S_IMODE(secret_file.stat().st_mode), 0o600)
            self.assertRegex(first[0], r"^[A-Za-z0-9_-]{43}=$")
            self.assertRegex(first[1], r"^[a-f0-9]{64}$")

    def test_replay_marker_db_and_key_binding_must_match_pairing_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            identity_dir = root / "identity"
            replay_dir = root / "replay"
            identity_dir.mkdir(mode=0o700)
            replay_dir.mkdir(mode=0o700)
            identity = identity_dir / "node-identity.json"
            marker = identity_dir / "replay-enrollment.json"
            database = replay_dir / "agent-replay.sqlite3"
            node_id = "node-ir-fieldtrial-0001"
            secret = "d" * 64

            identity.write_text(json.dumps({
                "version": 1, "node_id": node_id, "node_secret": secret,
            }))
            identity.chmod(0o600)
            binding = hmac.new(
                secret.encode("ascii"),
                b"smite-replay-key-binding-v1:" + node_id.encode("ascii"),
                hashlib.sha256,
            ).hexdigest()
            marker.write_text(json.dumps({
                "schema": 1, "node_id": node_id,
                "replay_database": pairing.CONTAINER_REPLAY,
                "status": "ENROLLMENT_STARTED",
                "key_binding": binding,
            }))
            marker.chmod(0o600)
            with sqlite3.connect(database) as db:
                db.execute(
                    "CREATE TABLE agent_nonces("
                    "node_id TEXT NOT NULL, nonce TEXT NOT NULL, "
                    "expires_at INTEGER NOT NULL, PRIMARY KEY(node_id,nonce))"
                )
                db.execute(
                    "CREATE TABLE replay_store_identity(node_id TEXT NOT NULL PRIMARY KEY)"
                )
                db.execute("INSERT INTO replay_store_identity(node_id) VALUES (?)", (node_id,))
                db.execute("PRAGMA user_version=1")
            database.chmod(0o600)

            with (
                patch.object(pairing, "IDENTITY_DIR", identity_dir),
                patch.object(pairing, "IDENTITY_FILE", identity),
                patch.object(pairing, "REPLAY_DIR", replay_dir),
                patch.object(pairing, "REPLAY_DB", database),
            ):
                self.assertTrue(pairing._replay_artifacts_valid())
                changed = json.loads(marker.read_text())
                changed["key_binding"] = "0" * 64
                marker.write_text(json.dumps(changed))
                marker.chmod(0o600)
                with self.assertRaises(pairing.WizardHold):
                    pairing._replay_artifacts_valid()

    def test_foreign_gateway_preflight_trusts_only_managed_pinned_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / "foreign-gateway.env"
            node = root / "node"
            node.mkdir()
            env = node / ".env"
            compose = node / "docker-compose.yml"
            compose.write_text("services:\n  smite-node:\n    image: signed\n")
            values = {
                "SMITE_FOREIGN_GATEWAY_DOMAIN": "kh.kolbe1.ir",
                "SMITE_FOREIGN_PANEL_DOMAIN": "ir.kolbe1.ir",
                "SMITE_FOREIGN_PANEL_SOURCE_IPV4": "91.107.174.237",
                "SMITE_FOREIGN_CONTROL_PATH": "/smite-node/322983983580c8eb",
                "SMITE_FOREIGN_GATEWAY_PUBLIC_PORT": "443",
                "SMITE_FOREIGN_GATEWAY_MODE": "https-control-path",
            }
            def write_state(data):
                state.write_text("".join(f"{k}={v}\n" for k,v in data.items()))
                state.chmod(0o600)
            write_state(values)
            control = "https://kh.kolbe1.ir/smite-node/322983983580c8eb"
            env.write_text(
                "SMITE_NODE_PANEL_AUTH_MODE=paused\n"
                "SMITE_AGENT_AUTH_MODE=strict\n"
                "SMITE_ENGINE_INVENTORY_MODE=managed\n"
                "PANEL_ADDRESS=ir.kolbe1.ir:443\n"
                f"SMITE_CONTROL_ADDRESS={control}\n"
            )
            env.chmod(0o600)
            current = {
                "SMITE_ROLE": "foreign",
                "SMITE_MANAGED_VERSION": "2.0.0-rc.1",
                "SMITE_PANEL_DOMAIN": "ir.kolbe1.ir",
            }
            seen = []
            def run_stub(command, **kwargs):
                seen.append(command)
                if command[:2] == ["docker","inspect"]:
                    return pairing._FOREIGN_NODE_IMAGE
                if command[0] == "curl":
                    self.assertIn("--resolve", command)
                    self.assertIn("kh.kolbe1.ir:443:127.0.0.1", command)
                    self.assertEqual(command[-1], control + "/")
                    return '{"status":"ok","service":"smite-node"}'
                raise AssertionError(command)
            with (
                patch.object(pairing, "STATE", root / "state.env"),
                patch.object(pairing, "NODE_DIR", node),
                patch.object(pairing, "NODE_COMPOSE", compose),
                patch.object(pairing, "_run", side_effect=run_stub),
            ):
                self.assertEqual(
                    pairing._foreign_gateway_preflight(current),
                    ("ir.kolbe1.ir", "kh.kolbe1.ir", control),
                )
                self.assertEqual(len(seen), 2)

                changed = dict(values)
                changed["SMITE_FOREIGN_CONTROL_PATH"] = "/api/agent"
                write_state(changed)
                with self.assertRaises(pairing.WizardHold):
                    pairing._foreign_gateway_preflight(current)
                write_state(values)

                env.write_text(env.read_text().replace(
                    "SMITE_AGENT_AUTH_MODE=strict",
                    "SMITE_AGENT_AUTH_MODE=legacy",
                ))
                with self.assertRaises(pairing.WizardHold):
                    pairing._foreign_gateway_preflight(current)

    def test_foreign_activation_uses_signed_only_and_rolls_back_on_failure(self):
        current = {
            "SMITE_ROLE": "foreign",
            "SMITE_CONNECTION_MODE": "standard",
            "SMITE_MANAGED_VERSION": "2.0.0-rc.1",
            "SMITE_NODE_NAME": "node-kh",
            "SMITE_PANEL_DOMAIN": "ir.kolbe1.ir",
        }
        control = "https://kh.kolbe1.ir/smite-node/322983983580c8eb"
        node_id = "22222222-3333-4444-5555-666666666666"

        for approval in (True, False):
            with self.subTest(signed_panel_approves=approval):
                commands = []
                active = [False]
                def fake_run(command, **kwargs):
                    commands.append(command)
                    if command[:2] == ["docker", "compose"]:
                        if "up" in command:
                            active[0] = (
                                str(pairing.NODE_SECURITY_CANDIDATE) in command
                            )
                        return ""
                    if command[:2] == ["docker", "inspect"]:
                        return "\n".join([
                            f"SMITE_NODE_PANEL_AUTH_MODE={'signed' if active[0] else 'paused'}",
                            "SMITE_AGENT_AUTH_MODE=strict",
                            "SMITE_ENGINE_INVENTORY_MODE=managed",
                        ])
                    if command[:2] == ["python3", "-B"]:
                        if approval:
                            return ""
                        raise pairing.WizardHold("Signed KH gateway not ready")
                    raise AssertionError(command)

                with (
                    patch.object(pairing, "_field_trial_gate"),
                    patch.object(pairing, "_foreign_gateway_preflight",
                                 return_value=("ir.kolbe1.ir","kh.kolbe1.ir",control)),
                    patch.object(pairing, "_identity_record", return_value=(node_id,b"a"*64)),
                    patch.object(pairing, "_regular", return_value=b""),
                    patch.object(pairing, "_prepare_security_candidate") as stage,
                    patch.object(pairing, "_provision_replay_once") as replay,
                    patch.object(pairing, "_wait_container") as wait,
                    patch.object(pairing, "_local_signed_replay_probe") as hmac_probe,
                    patch.object(pairing, "_run", side_effect=fake_run),
                    patch.object(pairing.time, "sleep") as sleeper,
                    patch("sys.stdout", io.StringIO()) as display,
                ):
                    if approval:
                        pairing.activate_foreign_node_field_trial(current)
                        self.assertIn(
                            "KH_TO_PANEL_SIGNED_CHECKIN_AND_GATEWAY=PASS",
                            display.getvalue(),
                        )
                        self.assertTrue(active[0])
                        self.assertEqual(
                            len([x for x in commands
                                 if x[:2] == ["docker","compose"] and "up" in x]), 1,
                        )
                    else:
                        with self.assertRaisesRegex(
                            pairing.WizardHold,
                            "Node paused again",
                        ):
                            pairing.activate_foreign_node_field_trial(current)
                        self.assertFalse(active[0])
                        self.assertEqual(
                            len([x for x in commands
                                 if x[:2] == ["docker","compose"] and "up" in x]), 2,
                        )
                        self.assertEqual(sleeper.call_count, 7)
                    stage.assert_called_once()
                    replay.assert_called_once()
                    hmac_probe.assert_called_once()
                    wait.assert_called()
                self.assertFalse(any("/api/nodes" in str(c) for c in commands))
                self.assertFalse(any("verify=False" in str(c) for c in commands))

    def test_foreign_activation_does_not_modify_panel_or_legacy_gateway(self):
        source = HELPER.read_text()
        activation = source.split("def activate_foreign_node_field_trial(",1)[1].split(
            "\ndef rollback_node_to_paused_field_trial(",1
        )[0]
        self.assertIn("_foreign_gateway_preflight(current)", activation)
        self.assertIn("_provision_replay_once()", activation)
        self.assertIn("_local_signed_replay_probe()", activation)
        self.assertIn("smite-foreign-gateway-signed-check.py", activation)
        self.assertIn("Node paused again", activation)
        self.assertNotIn("smite-panel", activation)
        self.assertNotIn("systemctl reload nginx", activation)
        self.assertNotIn("/api/nodes", activation)
        self.assertNotIn("SMITE_AGENT_AUTH_MODE=legacy", activation)
        wizard = (ROOT / "modules/smite-node-pairing-wizard.sh").read_text()
        self.assertIn("Activate signed KH Node runtime", wizard)
        self.assertIn("ACTIVATE-KH-SIGNED-NODE", wizard)
        self.assertIn("--activate-foreign-node-field-trial", wizard)


    def test_foreign_origin_approval_is_additive_ir_only_and_rollback_safe(self):
        import contextlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / "panel.env"
            env.write_text(
                "SMITE_NODE_REGISTRATION_MODE=signed\n"
                "SMITE_PANEL_AGENT_AUTH_MODE=signed\n"
                "SMITE_NODE_PAIRING_PREVIEW_ENABLED=true\n"
                "SMITE_SIGNED_NODE_ORIGINS_PATH="
                "/etc/smite-panel/trusted-nodes/approved-origins.json\n"
            )
            env.chmod(0o600)
            trusted = root / "trusted"
            trusted.mkdir(mode=0o700)
            approved = trusted / "approved-origins.json"
            initial = {"version": 1, "nodes": {
                "node-ir-abcdefgh": {
                    "role": "iran",
                    "node_name": "node-ir",
                    "origin": "http://127.0.0.1:8888",
                    "control_url": "http://127.0.0.1:8888/api/agent",
                },
            }}
            approved.write_text(json.dumps(initial))
            approved.chmod(0o600)
            override = root / "docker-compose.signed-control.yml"
            override.write_text("services: {}\n")
            override.chmod(0o600)
            database = root / "smite.db"
            node_id = "11111111-2222-3333-4444-555555555555"
            with sqlite3.connect(database) as db:
                db.execute(
                    "CREATE TABLE nodes "
                    "(id TEXT, name TEXT, status TEXT, metadata TEXT)"
                )
                db.execute(
                    "INSERT INTO nodes VALUES(?,?,?,?)",
                    (node_id,"node-kh","pending",json.dumps({
                        "role": "foreign",
                        "node_name": "node-kh",
                        "provisioning": "reserved_for_pairing",
                    })),
                )

            class Response:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *_): return False
                def read(self, n):
                    assert n == 257
                    return b'{"status":"ok","service":"smite-node"}'

            class Opener:
                def open(self, url, timeout):
                    self_test.assertEqual(
                        url,
                        "https://kh.kolbe1.ir/smite-node/322983983580c8eb/",
                    )
                    self_test.assertEqual(timeout, 12)
                    return Response()

            self_test = self
            good = [True]
            seen = []
            def local_run(cmd, **kwargs):
                seen.append(cmd)
                if cmd[:2] == ["docker", "inspect"]:
                    return str(trusted)
                if cmd[:2] == ["docker", "exec"]:
                    return "FOREIGN_PIN=VERIFIED" if good[0] else "WRONG"
                raise AssertionError(cmd)

            current = {
                "SMITE_ROLE": "panel-iran",
                "SMITE_MANAGED_VERSION": "2.0.0-rc.1",
                "SMITE_PANEL_DOMAIN": "ir.kolbe1.ir",
                "SMITE_NODE_NAME": "node-ir",
            }
            arg = dict(
                node_id=node_id, node_name="node-kh",
                control_url="https://kh.kolbe1.ir/smite-node/322983983580c8eb",
                state=current,
            )
            with (
                patch.object(pairing, "PANEL_ENV", env),
                patch.object(pairing, "PANEL_SECURITY_OVERRIDE", override),
                patch.object(pairing, "PANEL_DB", database),
                patch.object(pairing, "TRUSTED_NODES_DIR", trusted),
                patch.object(pairing, "APPROVED_ORIGINS", approved),
                patch.object(pairing, "_field_trial_gate"),
                patch.object(pairing, "_require_panel_signed_registration_schema"),
                patch.object(pairing, "_require_panel_foreign_transport") as panel_guard,
                patch.object(pairing, "_run", side_effect=local_run),
                patch.object(pairing.request, "build_opener", return_value=Opener()),
                patch("sys.stdout", io.StringIO()) as output,
            ):
                pairing.approve_foreign_origin_field_trial(**arg)
                self.assertIn("FOREIGN_ORIGIN_APPROVAL=PINNED", output.getvalue())
                records = json.loads(approved.read_text())["nodes"]
                self.assertEqual(records["node-ir-abcdefgh"], initial["nodes"]["node-ir-abcdefgh"])
                self.assertEqual(records[node_id]["role"], "foreign")
                self.assertEqual(records[node_id]["node_name"], "node-kh")
                self.assertEqual(stat.S_IMODE(approved.stat().st_mode), 0o600)
                pairing.approve_foreign_origin_field_trial(**arg)
                self.assertIn("ALREADY_PINNED", output.getvalue())

                # Bad path fails before any origin write, Docker call, or TLS call.
                preserved = approved.read_bytes()
                with self.assertRaises(pairing.WizardHold):
                    pairing.approve_foreign_origin_field_trial(**{
                        **arg, "control_url": "https://kh.kolbe1.ir/api/agent",
                    })
                self.assertEqual(approved.read_bytes(), preserved)

                # Independent name cannot silently overwrite the approval.
                with self.assertRaises(pairing.WizardHold):
                    pairing.approve_foreign_origin_field_trial(**{
                        **arg, "node_name": "node-foreign-changed",
                    })
                self.assertEqual(approved.read_bytes(), preserved)

                approved.write_text(json.dumps(initial))
                approved.chmod(0o600)
                good[0] = False
                with self.assertRaisesRegex(
                    pairing.WizardHold, "original approval restored|rejected and restored",
                ):
                    pairing.approve_foreign_origin_field_trial(**arg)
                self.assertEqual(json.loads(approved.read_text()), initial)
                panel_guard.assert_called()
            self.assertFalse(any("force-recreate" in str(x) for x in seen))

    def test_foreign_approval_rejects_other_hosts_and_untrusted_urls(self):
        good = "https://kh.kolbe1.ir/smite-node/322983983580c8eb"
        self.assertEqual(
            pairing._approved_foreign_control_url(good),
            ("https://kh.kolbe1.ir:443",good),
        )
        for invalid in (
            "http://kh.kolbe1.ir/smite-node/322983983580c8eb",
            "https://kh.kolbe1.ir:8888/smite-node/322983983580c8eb",
            "https://91.107.185.50/smite-node/322983983580c8eb",
            "https://kh.kolbe1.ir/smite-node/../../api",
            "https://kh.kolbe1.ir/smite-node/%33" + "22983983580c8eb",
            "https://kh.kolbe1.ir/api/agent",
            "https://user:pass@kh.kolbe1.ir/smite-node/322983983580c8eb",
            good + "?token=x",
            good + "#fragment",
        ):
            with self.subTest(url=invalid), self.assertRaises(pairing.WizardHold):
                pairing._approved_foreign_control_url(invalid)

    def test_live_field_trial_actions_remain_explicitly_gated(self):
        with patch.object(pairing.os, "geteuid", return_value=0):
            with patch.dict(os.environ, {"UOPTI_SMITE_PAIRING_FIELD_TRIAL": ""}):
                with self.assertRaises(pairing.WizardHold):
                    pairing._field_trial_gate()
            with patch.dict(os.environ, {"UOPTI_SMITE_PAIRING_FIELD_TRIAL": "YES"}):
                pairing._field_trial_gate()

    def test_packaging_and_cli_no_existing_wizard_edits(self):
        wrapper = (ROOT / "modules/smite-node-pairing-wizard.sh").read_text()
        install = (ROOT / "install.sh").read_text()
        launcher = (ROOT / "u-opti").read_text()
        for name in ("smite-node-pairing.py", "smite-node-pairing-wizard.sh"):
            self.assertIn('    "' + name + '"', install)
            self.assertEqual(launcher.count('                "' + name + '"'), 2)
            self.assertEqual(launcher.count('["' + name + '"]="$BASE_URL/modules/' + name + '"'), 1)
            self.assertEqual(launcher.count('["' + name + '"]="$TEMP_DIR/' + name + '"'), 1)
        self.assertIn('if [ "${1:-}" = "--smite-pairing" ]', launcher)
        self.assertIn("smite_node_pairing_menu()", wrapper)
        self.assertIn("Enable secure Panel pairing on HTTPS/443 (IR)", wrapper)
        self.assertIn("Activate signed IR Node runtime", wrapper)
        self.assertIn("UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES", wrapper)
        self.assertNotIn("node_secret", wrapper)
        self.assertNotIn("pairing_code", wrapper)


if __name__ == "__main__":
    unittest.main()
