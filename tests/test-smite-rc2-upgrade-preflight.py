#!/usr/bin/env python3
"""Offline RC2 read-only admission matrix for snapshot-backed two-host lab."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-rc2-upgrade-preflight.py"
spec = importlib.util.spec_from_file_location("rc2_preflight", SOURCE)
pre = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pre)


def make_file(root: Path, name: str, value: str, *, private=False):
    path = root / name.lstrip("/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600 if private else 0o640)
    return path


class Fixture:
    def __init__(self, root: Path, role: str):
        self.root = root
        self.role = role
        self.queries: list[list[str]] = []
        self.images = {"smite-node": pre.RC1_NODE, "smite-panel": pre.RC1_PANEL}
        self.health = {"smite-node": "healthy", "smite-panel": "healthy"}
        self.status = {"3xui-01": "running"}
        self.listeners = (
            "LISTEN 0 511 0.0.0.0:443 0.0.0.0:*\n"
            "LISTEN 0 4096 127.0.0.1:8888 0.0.0.0:*\n"
        )
        state = (
            "SMITE_ROLE=" + ("panel-iran" if role == "IR" else "foreign") + "\n"
            "SMITE_CONNECTION_MODE=standard\n"
            "SMITE_MANAGED_VERSION=2.0.0-rc.1\n"
            "SMITE_PANEL_DOMAIN=ir.kolbe1.ir\n"
            "SMITE_NODE_NAME=" + ("node-ir" if role == "IR" else "node-kh") + "\n"
        )
        make_file(root, "/etc/u-opti/smite/state.env", state)
        if role == "IR":
            make_file(root, "/opt/smite/.env", (
                "SMITE_NODE_REGISTRATION_MODE=signed\n"
                "SMITE_PANEL_AGENT_AUTH_MODE=signed\n"
                "SMITE_NODE_PAIRING_PREVIEW_ENABLED=true\n"
                "SMITE_PRIVATE_KEY=SHOULD_NEVER_BE_PRINTED\n"
            ), private=True)
            make_file(root, "/opt/smite/panel/data/smite.db",
                      "synthetic-fixture-database")
        else:
            make_file(root, "/opt/smite-node/.env", (
                "SMITE_NODE_PANEL_AUTH_MODE=paused\n"
                "SMITE_AGENT_AUTH_MODE=strict\n"
                "SMITE_ENGINE_INVENTORY_MODE=managed\n"
                "SMITE_CONTROL_ADDRESS=https://kh.kolbe1.ir/smite-node/322983983580c8eb\n"
                "PANEL_ADDRESS=ir.kolbe1.ir:443\n"
                "SMITE_NODE_HMAC_SECRET=SHOULD_NEVER_BE_PRINTED\n"
            ), private=True)
            make_file(root, "/etc/u-opti/smite/foreign-gateway.env", (
                "SMITE_FOREIGN_GATEWAY_DOMAIN=kh.kolbe1.ir\n"
                "SMITE_FOREIGN_PANEL_DOMAIN=ir.kolbe1.ir\n"
                "SMITE_FOREIGN_PANEL_SOURCE_IPV4=91.107.174.237\n"
                "SMITE_FOREIGN_CONTROL_PATH=/smite-node/322983983580c8eb\n"
                "SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443\n"
                "SMITE_FOREIGN_GATEWAY_MODE=https-control-path\n"
            ), private=True)
            make_file(root,
                      "/usr/local/lib/u-opti/modules/docker-3xui-xhttp-guard.py",
                      "#!/usr/bin/env python3\n")

    def run(self, command: list[str]):
        self.queries.append(command)
        if command == ["nginx", "-t"]:
            return ""
        if command == ["ss", "-H", "-lnt"]:
            return self.listeners
        if command[:3] == ["docker", "inspect", "-f"]:
            prop, name = command[3], command[4]
            if prop == "{{.Config.Image}}":
                return self.images[name]
            if prop == "{{.State.Health.Status}}":
                return self.health[name]
            if prop == "{{.State.Status}}":
                return self.status[name]
        if command[0] == "python3" and command[-2:] == ["01", "--check"]:
            return "XHTTP_REVIEW=PASS ROUTES=1 LEGACY_ROUTE=NO"
        raise AssertionError("Unexpected command in read-only preflight")


class RC2UpgradePreflightTests(unittest.TestCase):
    def with_fixture(self, role, check):
        with tempfile.TemporaryDirectory() as workspace:
            fx = Fixture(Path(workspace), role)
            check(fx)

    def test_valid_ir_baseline_only(self):
        def check(fx):
            facts = pre.audit("IR", root=fx.root, execute=fx.run)
            self.assertIn("IR_PANEL_SIGNED_BASELINE=VERIFIED", facts)
            self.assertIn("SNAPSHOT_AND_ROLLBACK=NOT_VERIFIED", facts)
            self.assertIn("LIVE_UPGRADE_AUTHORIZED=NO", facts)
            self.assertFalse(any("SHOULD_NEVER" in value for value in facts))
            self.assertNotIn("3xui-01", str(fx.queries))
        self.with_fixture("IR", check)

    def test_valid_kh_gateway_and_xhttp_baseline_only(self):
        def check(fx):
            facts = pre.audit("KH", root=fx.root, execute=fx.run)
            self.assertIn("KH_GATEWAY_XHTTP_BASELINE=VERIFIED", facts)
            self.assertIn("LIVE_UPGRADE_AUTHORIZED=NO", facts)
            for cmd in fx.queries:
                self.assertNotIn("force-recreate", cmd)
                self.assertNotIn("pull", cmd)
                self.assertNotIn("up", cmd)
                self.assertNotIn("rm", cmd)
                self.assertNotIn("down", cmd)
            self.assertNotIn("322983983580c8eb", " ".join(facts))
        self.with_fixture("KH", check)

    def test_rejects_non_loopback_node_listener(self):
        def check(fx):
            for address in ("0.0.0.0:8888", "[::]:8888", "91.107.185.50:8888"):
                fx.listeners = (
                    "LISTEN 0 511 0.0.0.0:443 0.0.0.0:*\n"
                    + "LISTEN 0 4096 " + address + " 0.0.0.0:*\n"
                )
                with self.subTest(address=address), self.assertRaisesRegex(
                    pre.Hold, "non-loopback"
                ):
                    pre.audit("KH", root=fx.root, execute=fx.run)
        self.with_fixture("KH", check)

    def test_rejects_changed_image_and_unhealthy_node(self):
        def check(fx):
            fx.images["smite-node"] = pre.RC2_NODE
            with self.assertRaisesRegex(pre.Hold, "differs"):
                pre.audit("IR", root=fx.root, execute=fx.run)
            fx.images["smite-node"] = pre.RC1_NODE
            fx.health["smite-node"] = "starting"
            with self.assertRaisesRegex(pre.Hold, "healthy"):
                pre.audit("IR", root=fx.root, execute=fx.run)
        self.with_fixture("IR", check)

    def test_rejects_kh_legacy_or_changed_control_metadata(self):
        def check(fx):
            env = fx.root / "opt/smite-node/.env"
            base = env.read_text()
            env.write_text(base.replace("SMITE_AGENT_AUTH_MODE=strict",
                                        "SMITE_AGENT_AUTH_MODE=legacy"))
            with self.assertRaisesRegex(pre.Hold, "paused/strict/managed"):
                pre.audit("KH", root=fx.root, execute=fx.run)
            env.write_text(base.replace("https://kh.kolbe1.ir/smite-node/",
                                        "https://kh.kolbe1.ir/unscoped/"))
            with self.assertRaisesRegex(pre.Hold, "control metadata mismatch"):
                pre.audit("KH", root=fx.root, execute=fx.run)
        self.with_fixture("KH", check)

    def test_missing_or_nonprivate_files_are_rejected(self):
        def check(fx):
            env = fx.root / "opt/smite/.env"
            env.chmod(0o644)
            with self.assertRaisesRegex(pre.Hold, "mode is not 0600"):
                pre.audit("IR", root=fx.root, execute=fx.run)
            env.chmod(0o600)
            env.unlink()
            env.symlink_to("/etc/passwd")
            with self.assertRaises(pre.Hold):
                pre.audit("IR", root=fx.root, execute=fx.run)
        self.with_fixture("IR", check)

    def test_rejects_malformed_or_duplicate_managed_state(self):
        with self.assertRaisesRegex(pre.Hold, "duplicate"):
            pre.parse_env(b"SMITE_ROLE=foreign\nSMITE_ROLE=panel-iran\n")
        with self.assertRaisesRegex(pre.Hold, "malformed"):
            pre.parse_env(b"export SMITE_ROLE=foreign\n")
        with self.assertRaisesRegex(pre.Hold, "UTF-8"):
            pre.parse_env(b"\xff")

    def test_version_holds_on_rc2_until_migration_plan_exists(self):
        def check(fx):
            state = fx.root / "etc/u-opti/smite/state.env"
            state.write_text(state.read_text().replace("2.0.0-rc.1", "2.0.0-rc.2"))
            with self.assertRaisesRegex(pre.Hold, "exact RC.1"):
                pre.audit("IR", root=fx.root, execute=fx.run)
        self.with_fixture("IR", check)

    def test_manifest_must_be_exact_nonactivating_signed_pair(self):
        original = pre.CANDIDATE.read_bytes()
        pre.check_candidate(original)
        with self.assertRaisesRegex(pre.Hold, "SHA256 mismatch"):
            pre.check_candidate(original.replace(b'"activation_allowed":false',
                                                 b'"activation_allowed":true'))

    def test_db_never_read_and_symlink_rejected(self):
        def check(fx):
            db = fx.root / "opt/smite/panel/data/smite.db"
            self.assertIsNone(pre.check_regular_metadata(fx.root,
                "/opt/smite/panel/data/smite.db"))
            db.unlink()
            db.symlink_to("/etc/passwd")
            with self.assertRaises(pre.Hold):
                pre.check_regular_metadata(fx.root,
                    "/opt/smite/panel/data/smite.db")
        self.with_fixture("IR", check)


if __name__ == "__main__":
    unittest.main()
