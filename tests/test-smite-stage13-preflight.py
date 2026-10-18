"""Stage13 honest, read-only IR/KH preflight tests with temporary fixtures."""
import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules/smite-stage13-preflight.py"
spec = importlib.util.spec_from_file_location("smite_stage13_admission", MODULE)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)

audit_file = ROOT / "modules/smite-auth-image-overlay-audit.py"
audit_spec = importlib.util.spec_from_file_location("smite_stage10_audit_fixture", audit_file)
source_audit = importlib.util.module_from_spec(audit_spec)
audit_spec.loader.exec_module(source_audit)


class Stage13PreflightTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        def private_dir(name):
            p = root / name
            p.mkdir(mode=0o700)
            return p
        identity_dir = private_dir("identities")
        replay_dir = private_dir("replay")
        approved_dir = private_dir("approved")
        manifests_dir = private_dir("manifests")
        self.p = gate.Paths(
            state=root / "state.env",
            identity=identity_dir / "node-identity.json",
            node_compose=root / "docker-compose-node.yml",
            node_candidate=root / "docker-compose.security-candidate.yml",
            replay_dir=replay_dir,
            image_lock=manifests_dir / "security-image-lock.json",
            snapshot_receipt=manifests_dir / "snapshot-receipt.json",
            panel_compose=root / "docker-compose-panel.yml",
            approved_origins=approved_dir / "approved-origins.json",
            nginx_vhost=root / "nginx-site.conf",
            panel_app=root / "image-panel",
            node_app=root / "image-node",
            overlays=root / "overlays",
        )
        for folder in (self.p.panel_app, self.p.node_app, self.p.overlays):
            folder.mkdir()
        self.p.identity.write_text(json.dumps({
            "node_id": "cccccccc-1111-2222-3333-444444444444",
            "node_secret": "f" * 64,
        }))
        self.p.identity.chmod(0o600)
        self.p.state.write_text("SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n")
        self.p.node_compose.write_text(
            "services:\n  smite-node:\n    network_mode: host\n"
            '    command: ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"]\n'
            "    volumes:\n"
        )
        self.p.node_candidate.write_text(
            "# U-OPTI SMITE NODE SECURITY STAGE9 CANDIDATE - INERT\n"
            "services:\n  smite-node:\n"
            "    volumes:\n"
            "      - /identity:/run/smite-node-identity:ro\n"
            "      - /data:/var/lib/smite-node/auth:rw\n"
            "    environment:\n"
            "      SMITE_AGENT_AUTH_MODE: strict\n"
            "      SMITE_NODE_PANEL_AUTH_MODE: signed\n"
            '    healthcheck: ["http://127.0.0.1:8888/"]\n'
        )
        self.p.node_candidate.chmod(0o600)
        self.p.image_lock.write_text(json.dumps({
            "version": 1, "images": {
                "panel": "ghcr.io/example/smite-panel@sha256:" + "a" * 64,
                "node": "ghcr.io/example/smite-node@sha256:" + "b" * 64
            }
        }))
        self.p.image_lock.chmod(0o600)
        self.p.snapshot_receipt.write_text(json.dumps({
            "version": 1, "snapshots": {
                "ir": "snapshot-ir-12345", "kh": "snapshot-kh-12345"
            }, "rollback_steps_reviewed": True
        }))
        self.p.snapshot_receipt.chmod(0o600)
        self.p.approved_origins.write_text(json.dumps({
            "version": 1, "nodes": {
                "dddddddd-1111-2222-3333-444444444444": {
                    "role": "foreign", "origin": "https://kh.example.net:443",
                    "control_url": "https://kh.example.net/path",
                }
            }
        }))
        self.p.approved_origins.chmod(0o600)
        self.p.nginx_vhost.write_text(
            "server {\n listen 443 ssl;\n"
            " location ^~ /api/agent/ {\n"
            "  allow 198.51.100.2;\n  deny all;\n"
            "  proxy_pass http://127.0.0.1:8888;\n }\n}\n"
        )
        for role, paths in source_audit.REQUIRED_MODULES.items():
            for filename in paths:
                dest = (self.p.panel_app if role == "panel" else self.p.node_app) / filename
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text("valid = True\n")
        for role, name in source_audit.SHADOWS:
            source = (self.p.panel_app if role == "panel" else self.p.node_app) / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("valid = True\n")
            target = self.p.overlays / source_audit.OVERLAY_NAMES[(role, name)]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        panel_mounts = [
            f"      - {self.p.overlays / source_audit.OVERLAY_NAMES[('panel', name)]}:/app/{name}:ro"
            for role, name in source_audit.SHADOWS if role == "panel"
        ]
        node_mounts = [
            f"      - {self.p.overlays / source_audit.OVERLAY_NAMES[('node', name)]}:/app/{name}:ro"
            for role, name in source_audit.SHADOWS if role == "node"
        ]
        self.p.panel_compose.write_text(
            "services:\n  smite-panel:\n    volumes:\n" + "\n".join(panel_mounts) + "\n"
        )
        with self.p.node_compose.open("a") as f:
            f.write("\n".join(node_mounts) + "\n")

    def result(self, role="kh"):
        return dict(gate.audit(role, self.p))

    def test_local_evidence_can_pass_but_no_activation_permission(self):
        results = self.result()
        local = {key: value for key, value in results.items()
                 if value in ("PASS_LOCAL_EVIDENCE", "HOLD")}
        self.assertTrue(local)
        self.assertEqual(set(local.values()), {"PASS_LOCAL_EVIDENCE"}, results)
        self.assertEqual(results["AUTH_ACTIVATION"], "BLOCKED")
        for key in ("IMAGE_REGISTRY_ATTESTATION", "RUNNING_IMAGE_AND_DOCKER_MOUNTS",
                    "EFFECTIVE_NGINX_TLS_CERT_HMAC_PATH",
                    "CLOUD_SNAPSHOT_EXISTS_AND_RESTORE_WORKS",
                    "FRP_BACKHAUL_XHTTP_REAL_TRAFFIC"):
            self.assertEqual(results[key], "UNVERIFIED")

    def test_wrong_role_private_mode_and_missing_identity_hold(self):
        self.assertEqual(self.result("ir")["STANDARD_ROLE"], "HOLD")
        self.p.state.write_text("SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=private\n")
        self.assertEqual(self.result()["STANDARD_ROLE"], "HOLD")
        self.p.state.write_text("SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n")
        self.p.identity.chmod(0o644)
        self.assertEqual(self.result()["PAIRED_NODE_IDENTITY"], "HOLD")
        self.p.identity.chmod(0o600)
        self.p.identity.unlink()
        self.assertEqual(self.result()["PAIRED_NODE_IDENTITY"], "HOLD")

    def test_stale_shadow_untrusted_candidate_and_fake_image_pin_hold(self):
        (self.p.overlays / "node/panel_client.py").write_text("legacy = True\n")
        self.assertEqual(
            self.result()["SECURITY_IMAGE_OVERLAY_SOURCE_PARITY"], "HOLD"
        )
        self.p.node_candidate.chmod(0o644)
        self.assertEqual(self.result()["NODE_COMPOSE_AND_INERT_CANDIDATE"], "HOLD")
        self.p.image_lock.write_text('{"version":1,"images":{"panel":"latest","node":"latest"}}')
        self.assertEqual(self.result()["IMAGE_DIGEST_DECLARATION"], "HOLD")

    def test_missing_two_host_snapshots_and_replay_private_storage_hold(self):
        self.p.snapshot_receipt.write_text(json.dumps({
            "version": 1, "snapshots": {"kh": "snapshot-kh-12345"},
            "rollback_steps_reviewed": True,
        }))
        self.assertEqual(self.result()["TWO_HOST_SNAPSHOT_RECEIPT"], "HOLD")
        self.p.replay_dir.chmod(0o755)
        self.assertEqual(self.result()["PERSISTENT_REPLAY_PERMISSIONS"], "HOLD")

    def test_rewritten_nginx_path_is_refused_and_ir_role_scoped(self):
        self.p.nginx_vhost.write_text(self.p.nginx_vhost.read_text().replace(
            "proxy_pass http://127.0.0.1:8888;",
            "proxy_pass http://127.0.0.1:8888/;",
        ))
        self.assertEqual(self.result()["SIGNED_443_NGINX_SOURCE"], "HOLD")
        self.p.state.write_text("SMITE_ROLE=panel-iran\nSMITE_CONNECTION_MODE=standard\n")
        self.p.nginx_vhost.write_text(
            "server { listen 443 ssl;\n"
            " location ^~ /api/node-control/ {\n"
            " proxy_pass http://127.0.0.1:8000;\n }\n}\n"
        )
        result = self.result("ir")
        self.assertEqual(result["STANDARD_ROLE"], "PASS_LOCAL_EVIDENCE")
        self.assertEqual(result["SIGNED_443_NGINX_SOURCE"], "PASS_LOCAL_EVIDENCE")
        self.assertEqual(result["APPROVED_NODE_ORIGINS"], "PASS_LOCAL_EVIDENCE")
        self.assertEqual(result["AUTH_ACTIVATION"], "BLOCKED")

    def test_does_not_modify_input_files_or_log_credentials(self):
        before = self.p.identity.read_bytes()
        with patch("builtins.print") as log:
            items = gate.audit("kh", self.p)
            for key, value in items:
                print(f"{key}={value}")
        output = " ".join(str(c.args) for c in log.call_args_list)
        self.assertNotIn("f" * 64, output)
        self.assertEqual(before, self.p.identity.read_bytes())
        self.assertNotIn("subprocess.run(", MODULE.read_text())
        self.assertNotIn("subprocess.Popen(", MODULE.read_text())
        self.assertNotIn("os.system(", MODULE.read_text())
        self.assertNotIn("docker compose up", MODULE.read_text())
        self.assertNotIn("systemctl restart", MODULE.read_text())
        for file in ("install.sh", "u-opti"):
            self.assertIn("smite-stage13-preflight.py", (ROOT / file).read_text())


if __name__ == "__main__":
    unittest.main()
