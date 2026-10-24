#!/usr/bin/env python3
"""Real pinned Smite FastAPI + persistent SQLite in-process integration.

CI ONLY: ASGI TestClient, no listening socket, Docker, server, real TLS,
public ports, or production files. Host transaction uses disposable lab.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SMITE = ROOT / ".managed-smite-source"
if not (SMITE / "node/app/agent_auth.py").is_file():
    raise RuntimeError("PINNED_SMITE_SOURCE_MISSING")
sys.path.insert(0, str(SMITE / "node"))

from app import engine_inventory as inventory
from app import node_auth
from app.agent_auth import DurableNonceStore
from app.replay_enrollment import provision_once, ReplayEnrollmentHold
from app.replay_restore_hold import quarantine
from app.config import settings
from app.routers.agent import router

spec = importlib.util.spec_from_file_location(
    "uopti_signed_probe_real_asgi_lab", ROOT / "tests/lab/smite_signed_runtime_probe.py")
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)
spec = importlib.util.spec_from_file_location(
    "uopti_host_lab_real_asgi", ROOT / "tests/lab/smite_host_executor.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

NODE_ID = "bbbbbbbb-1111-2222-3333-444444444444"
SECRET = b"b" * 64
ORIGIN = "https://node-kh.example.test:443"
ENGINES_ZERO = {n: "not-installed" for n in probe.EXPECTED_ENGINES}
ENGINES_BH = dict(ENGINES_ZERO, backhaul="ready")


class Adapters:
    def __init__(self):
        self.active_tunnels = {}
        self.apply_calls = []
        self.remove_calls = []

    async def apply_tunnel(self, *, tunnel_id, tunnel_core, spec):
        self.apply_calls.append((tunnel_id, tunnel_core))

    async def remove_tunnel(self, tunnel_id):
        self.remove_calls.append(tunnel_id)

    async def get_tunnel_status(self, tunnel_id):
        return {"running": False}


class RealFastAPIWithTestClient(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="uopti-fastapi-agent-ci-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.identity_dir = self.work / "identity"
        self.replay_dir = self.work / "replay"
        self.manifest_dir = self.work / "engine-state"
        for p in (self.identity_dir, self.replay_dir, self.manifest_dir):
            p.mkdir(mode=0o700)
        self.identity = self.identity_dir / "node-identity.json"
        self.identity.write_text(json.dumps({
            "version": 1, "node_id": NODE_ID, "node_secret": SECRET.decode()
        }))
        self.identity.chmod(0o600)
        self.replay = self.replay_dir / "agent-replay.sqlite3"
        # Explicit offline pairing/bootstrap: production must never create
        # a missing replay database while handling a request.
        provision_once(identity_path=self.identity, replay_path=self.replay)
        self.enrollment_marker = self.identity_dir / "replay-enrollment.json"
        self.assertTrue(self.enrollment_marker.is_file())
        self.manifest = self.manifest_dir / "engines.json"
        self.binary = self.work / "managed-backhaul"
        self.binary.write_bytes(b"CI-ONLY-SYNTHETIC-BACKHAUL-NOT-EXECUTABLE")
        self.binary.chmod(0o755)
        keys = ("smite_agent_auth_mode", "smite_agent_identity_path",
                "smite_agent_replay_db", "smite_engine_inventory_mode",
                "smite_engine_manifest_path")
        prior = {k: getattr(settings, k) for k in keys}
        self.addCleanup(lambda: [setattr(settings, k, v) for k, v in prior.items()])
        settings.smite_agent_auth_mode = "strict"
        settings.smite_agent_identity_path = str(self.identity)
        settings.smite_agent_replay_db = str(self.replay)
        settings.smite_engine_inventory_mode = "managed"
        settings.smite_engine_manifest_path = str(self.manifest)
        self.binary_patch = patch.object(
            inventory, "binary_path_for_engine",
            side_effect=lambda name: self.binary if name == "backhaul"
            else self.work / ("not-installed-" + name))
        self.binary_patch.start()
        self.addCleanup(self.binary_patch.stop)
        self.uid_patch = patch.object(inventory, "ROOT_BINARY_UID", os.geteuid())
        self.uid_patch.start()
        self.addCleanup(self.uid_patch.stop)
        self.adapters = Adapters()
        self.create_app()
        self.addCleanup(self._close_app)

    def _close_app(self):
        self.client.close()

    def create_app(self):
        # Fresh ASGI app/adapter models a Node app rebuild but preserves
        # identity, manifest, and the actual durable SQLite Replay database.
        self.adapters = Adapters()
        app = FastAPI()
        app.state.adapter_manager = self.adapters
        app.include_router(router, prefix="/api/agent")
        self.client = TestClient(app, base_url=ORIGIN)

    def recreate(self):
        self.client.close()
        self.create_app()

    def sign(self, target="/api/agent/status", *, nonce=None, timestamp=None,
             secret=SECRET):
        return node_auth.sign_request(
            secret=secret, node_id=NODE_ID, method="GET", target=target,
            body=b"", timestamp=timestamp, nonce=nonce)

    def transport(self, *, origin, target, method, body, headers,
                  verify_tls, allow_redirects):
        # Deliberate ASGI substitute for HTTPS; transport TLS is NOT tested.
        if not verify_tls or allow_redirects or origin != ORIGIN or method != "GET":
            raise RuntimeError("UNSAFE_ASGI_TEST_TRANSPORT")
        response = self.client.request(
            method, target, content=body, headers=headers,
            follow_redirects=False)
        return probe.Reply(
            status=response.status_code, body=response.content,
            tls_verified=True, origin=origin, target=target,
            redirected=response.is_redirect)

    def verifier(self):
        return probe.MockOnlySignedRuntimeVerifier(
            node_id=NODE_ID, secret=SECRET, origin=ORIGIN,
            approved_origin=ORIGIN, signer=node_auth.sign_request,
            transport=self.transport)

    def enroll_backhaul(self):
        self.manifest.write_text(json.dumps({"schema": 1, "engines": {
            "backhaul": {"sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest()}
        }}))
        self.manifest.chmod(0o600)

    def test_authentication_and_durable_nonce_survive_asgi_recreate(self):
        self.assertEqual(self.client.get("/api/agent/status").status_code, 401)
        original_identity = self.identity.read_bytes()
        header = self.sign(nonce="1" * 32)
        self.assertEqual(self.client.get("/api/agent/status", headers=header).status_code, 200)
        self.recreate()
        self.assertEqual(self.client.get("/api/agent/status", headers=header).status_code, 401)
        self.assertEqual(self.client.get("/api/agent/status", headers=self.sign()).status_code, 200)
        self.assertTrue(self.replay.is_file())
        self.assertEqual(stat.S_IMODE(self.replay.stat().st_mode), 0o600)
        self.assertEqual(self.identity.read_bytes(), original_identity)
        self.assertEqual(self.verifier().check(ENGINES_ZERO)["ACTIVATION_GATE"], "HOLD")

    def test_replay_is_rejected_by_independent_python_process(self):
        # A completely new Python interpreter imports the reviewed Node
        # routes and opens the SAME persistent, private SQLite replay DB.
        signature = self.sign(nonce="d" * 32)
        self.assertEqual(
            self.client.get("/api/agent/status", headers=signature).status_code, 200)
        script = """
import json, sys
from fastapi import FastAPI
from fastapi.testclient import TestClient
sys.path.insert(0, sys.argv[1])
from app.config import settings
from app.routers.agent import router
from app import node_auth
settings.smite_agent_auth_mode = "strict"
settings.smite_agent_identity_path = sys.argv[2]
settings.smite_agent_replay_db = sys.argv[3]
settings.smite_engine_inventory_mode = "managed"
settings.smite_engine_manifest_path = sys.argv[4]
app = FastAPI()
app.state.adapter_manager = type("Empty", (), {"active_tunnels": {}})()
app.include_router(router, prefix="/api/agent")
with TestClient(app, base_url="https://node-kh.example.test:443") as client:
    reused = client.get("/api/agent/status", headers=json.loads(sys.argv[5]))
    fresh = node_auth.sign_request(
        secret=b"b" * 64, node_id="bbbbbbbb-1111-2222-3333-444444444444",
        method="GET", target="/api/agent/status", body=b"")
    accepted = client.get("/api/agent/status", headers=fresh)
print(json.dumps({"reused": reused.status_code, "new": accepted.status_code}))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, str(SMITE / "node"),
             str(self.identity), str(self.replay), str(self.manifest),
             json.dumps(signature)],
            capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip()),
                         {"reused": 401, "new": 200})
        self.assertEqual(stat.S_IMODE(self.replay.stat().st_mode), 0o600)

    def test_missing_replay_database_stays_missing_after_restart_and_503(self):
        initial = self.sign(nonce="a" * 32)
        self.assertEqual(self.client.get("/api/agent/status", headers=initial).status_code, 200)
        self.replay.unlink()
        with self.assertRaisesRegex(ReplayEnrollmentHold, "already started"):
            provision_once(identity_path=self.identity, replay_path=self.replay)
        self.assertTrue(self.enrollment_marker.is_file())
        fresh = self.sign(nonce="b" * 32)
        self.assertEqual(self.client.get("/api/agent/status", headers=fresh).status_code, 503)
        self.assertFalse(self.replay.exists())
        self.recreate()
        self.assertEqual(self.client.get("/api/agent/status", headers=initial).status_code, 503)
        self.assertEqual(self.client.get("/api/agent/status", headers=fresh).status_code, 503)
        self.assertFalse(self.replay.exists())
        # Enrollment metadata is independent from the missing replay volume.
        with self.assertRaises(ReplayEnrollmentHold):
            provision_once(identity_path=self.identity, replay_path=self.replay)
        self.assertFalse(self.replay.exists())

    def test_known_stale_snapshot_quarantine_survives_app_restart(self):
        # Genuine same-Node stale SQLite restoration: old snapshot predates
        # a successful signed request, and the independent identity marker
        # must block ALL future signed routes until reviewed recovery.
        stale = self.replay_dir / "older-same-node-snapshot.sqlite3"
        shutil.copy2(self.replay, stale)
        used = self.sign(nonce="c" * 32)
        self.assertEqual(self.client.get("/api/agent/status", headers=used).status_code, 200)
        quarantine(identity_path=self.identity, replay_path=self.replay)
        hold = self.identity_dir / "replay-restore-hold.json"
        self.assertTrue(hold.is_file())
        shutil.copy2(stale, self.replay)
        self.assertEqual(self.client.get("/api/agent/status", headers=used).status_code, 503)
        self.assertEqual(self.client.get("/api/agent/status",
                                         headers=self.sign()).status_code, 503)
        self.recreate()
        self.assertEqual(self.client.get("/api/agent/status",
                                         headers=self.sign()).status_code, 503)
        self.assertTrue(hold.exists())
        with self.assertRaises(Exception):
            quarantine(identity_path=self.identity, replay_path=self.replay)

    def test_replay_bootstrap_cannot_reset_existing_node(self):
        with self.assertRaises(ReplayEnrollmentHold):
            provision_once(identity_path=self.identity, replay_path=self.replay)
        with self.assertRaises(Exception):
            DurableNonceStore.initialize_new(self.replay, NODE_ID)
        self.assertEqual(self.verifier().check(ENGINES_ZERO)["ACTIVATION_GATE"], "HOLD")

    def test_inventory_real_endpoint_managed_state_digest_and_role(self):
        self.enroll_backhaul()
        before = self.verifier().check(ENGINES_BH)
        self.assertEqual(before["INVENTORY_MATCH"], "YES")
        self.recreate()
        self.assertEqual(self.verifier().check(ENGINES_BH)["INVENTORY_MATCH"], "YES")
        self.binary.write_bytes(b"TAMPERED")
        with self.assertRaisesRegex(probe.Hold, "SIGNED_ENGINE_INVENTORY_MISMATCH"):
            self.verifier().check(ENGINES_BH)
        self.assertEqual(self.verifier().check(
            dict(ENGINES_BH, backhaul="unavailable"))["ACTIVATION_GATE"], "HOLD")

    def test_missing_frps_prevents_forged_ready_frp(self):
        # A valid, executable frpc fixture alone is never sufficient for FRP.
        frpc = self.work / "not-installed-frp"
        frpc.write_bytes(b"FRPC-CI-VALID-WITHOUT-FRPS")
        frpc.chmod(0o755)
        self.manifest.write_text(json.dumps({"schema": 1, "engines": {
            "frp": {"sha256": hashlib.sha256(frpc.read_bytes()).hexdigest(),
                    "server_sha256": "e" * 64}
        }}))
        self.manifest.chmod(0o600)
        with self.assertRaisesRegex(probe.Hold, "SIGNED_ENGINE_INVENTORY_MISMATCH"):
            self.verifier().check(dict(ENGINES_ZERO, frp="ready"))
        self.assertEqual(self.verifier().check(
            dict(ENGINES_ZERO, frp="unavailable"))["ACTIVATION_GATE"], "HOLD")

    def test_fail_closed_on_identity_and_replay_store_faults(self):
        self.replay_dir.chmod(0o755)
        with self.assertRaises(probe.Hold):
            self.verifier().check(ENGINES_ZERO)
        self.replay_dir.chmod(0o700)
        self.identity.chmod(0o644)
        with self.assertRaises(probe.Hold):
            self.verifier().check(ENGINES_ZERO)
        self.identity.chmod(0o600)
        self.assertEqual(self.verifier().check(ENGINES_ZERO)["INSTALL_ALLOWED"], "NO")

    def test_legacy_mode_is_not_signed_acceptance(self):
        settings.smite_agent_auth_mode = "legacy"
        self.assertEqual(self.client.get("/api/agent/status").status_code, 200)
        with self.assertRaisesRegex(probe.Hold, "SIGNED_NODE_AUTH_POLICY_FAILED"):
            self.verifier().check(ENGINES_ZERO)

    def test_real_endpoint_rejects_wrong_hmac_path_clock_and_replay(self):
        target = "/api/agent/status"
        signed = self.sign(nonce="8" * 32)
        self.assertEqual(self.client.get(
            target, headers=self.sign(secret=b"a" * 64)).status_code, 401)
        self.assertEqual(self.client.get(
            target + "?unexpected=1", headers=signed).status_code, 401)
        self.assertEqual(self.client.get(target, headers=self.sign(
            nonce="9" * 32, timestamp=int(time.time())-120)).status_code, 401)
        self.assertEqual(self.client.get(target, headers=signed).status_code, 200)
        self.assertEqual(self.client.get(target, headers=signed).status_code, 401)

    def test_managed_no_engine_never_applies_tunnel(self):
        import json as jsonlib
        payload = {"tunnel_id": "not-ready", "core": "backhaul",
                   "type": "tcp", "spec": {}}
        raw = jsonlib.dumps(payload, separators=(",", ":")).encode()
        headers = node_auth.sign_request(
            secret=SECRET, node_id=NODE_ID, method="POST",
            target="/api/agent/tunnels/apply", body=raw)
        response = self.client.post(
            "/api/agent/tunnels/apply", content=raw, headers=headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.adapters.apply_calls, [])

    def test_actual_endpoint_gate_drives_disposable_crash_and_recovery(self):
        with tempfile.TemporaryDirectory(prefix="uopti-engine-txn-lab-") as folder:
            home = Path(folder)
            home.chmod(0o700)
            (home / ".LAB_ONLY").write_bytes(lab.MARKER)
            node = home / "node"
            (node / "config/engine-state").mkdir(parents=True, mode=0o700)
            (node / "docker-compose.yml").write_bytes(b"services:\n  smite-node:\n    image: ci-pinned\n")
            (node / ".env").write_bytes(b"SMITE_AGENT_AUTH_MODE=strict\n")
            (node / "config/node-id").write_bytes(b"UNCHANGED-NODE")
            (node / "config/replay.db").write_bytes(b"UNCHANGED-REPLAY-MODEL")
            (node / "config/tunnels.json").write_bytes(b"[]\n")

            self.manifest = node / "config/engine-state/engines.json"
            self.binary = node / "managed-bin/backhaul/backhaul"
            settings.smite_engine_manifest_path = str(self.manifest)

            engine = b"BACKHAUL-SYNTHETIC-CI-ONLY"
            override = b"services:\n  smite-node:\n    volumes: []\n"
            candidate = lab.canonical({"schema": 1, "engines": {
                "backhaul": {"sha256": lab.sha(engine)}
            }})
            preview = {
                "STAGE_ADMISSION": "VERIFIED_PREVIEW_ONLY",
                "INSTALL_ALLOWED": "NO",
                "ACTIVATION_GATE": "HOLD",
                "BINARIES_SHA256": [lab.sha(engine)],
                "CANDIDATE_COMPOSE_OVERLAY_SHA256": lab.sha(override),
                "SOURCE_COMPOSE_SHA256": lab.sha((node / "docker-compose.yml").read_bytes()),
                "CANDIDATE_MANIFEST_SHA256": lab.sha(candidate),
                "OTHER_ENGINE": "NOT_INSTALLED",
            }

            def probe_running(kind, engine_name):
                expected = ENGINES_BH if kind == "new" else ENGINES_ZERO
                evidence = self.verifier().check(expected)
                return {"signed": evidence["INVENTORY_MATCH"] == "YES",
                        "replay": evidence["ACTIVATION_GATE"] == "HOLD"}

            with self.assertRaises(lab.SimulatedCrash):
                lab.execute(home, "backhaul", {"backhaul": engine},
                            override, preview, probe_running,
                            crash_at="after_manifest", candidate_manifest=candidate)
            self.assertEqual(lab.recover(home, probe_running), "ROLLED_BACK")
            self.assertEqual(self.verifier().check(ENGINES_ZERO)["ACTIVATION_GATE"], "HOLD")
            output = lab.execute(home, "backhaul", {"backhaul": engine},
                                 override, preview, probe_running,
                                 candidate_manifest=candidate)
            self.assertEqual(output["INSTALL_ALLOWED"], "NO")
            self.assertEqual(lab.recover(home, probe_running), "COMMITTED")
            self.recreate()
            self.assertEqual(self.verifier().check(ENGINES_BH)["INVENTORY_MATCH"], "YES")
            self.assertEqual((node / "config/node-id").read_bytes(), b"UNCHANGED-NODE")
            self.assertEqual((node / "config/replay.db").read_bytes(),
                             b"UNCHANGED-REPLAY-MODEL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
