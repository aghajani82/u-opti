"""Stage10 read-only image source versus U-OPTI host overlay regression tests."""
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules/smite-auth-image-overlay-audit.py"
spec = importlib.util.spec_from_file_location("smite_stage10_image_audit", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ImageAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = self.root / "panel_app"
        self.node = self.root / "node_app"
        self.overlays = self.root / "overlays"
        self.panel.mkdir()
        self.node.mkdir()
        self.overlays.mkdir()
        for role, required in audit.REQUIRED_MODULES.items():
            for name in required:
                path = (self.panel if role == "panel" else self.node) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("SAFE_TEST_VARIABLE = True\n")
        for role, inner in audit.SHADOWS:
            source = self.panel if role == "panel" else self.node
            path = source / inner
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("SAFE_TEST_VARIABLE = True\n")
            shadow = self.overlays / audit.OVERLAY_NAMES[(role, inner)]
            shadow.parent.mkdir(parents=True, exist_ok=True)
            shadow.write_bytes(path.read_bytes())
        self.pc = self.root / "panel-compose.yml"
        self.nc = self.root / "node-compose.yml"
        panel_mounts = [
            "      - " + str(self.overlays / audit.OVERLAY_NAMES[("panel", name)]) + ":/app/" + name + ":ro"
            for role, name in audit.SHADOWS if role == "panel"
        ]
        node_mounts = [
            "      - " + str(self.overlays / audit.OVERLAY_NAMES[("node", name)]) + ":/app/" + name + ":ro"
            for role, name in audit.SHADOWS if role == "node"
        ]
        self.pc.write_text("services:\n  smite-panel:\n    volumes:\n" + "\n".join(panel_mounts) + "\n")
        self.nc.write_text("services:\n  smite-node:\n    volumes:\n" + "\n".join(node_mounts) + "\n")
        self.arguments = dict(
            panel_root=self.panel, node_root=self.node,
            overlay_root=self.overlays,
            panel_compose=self.pc, node_compose=self.nc,
        )

    def rows(self):
        return dict(audit.assess(**self.arguments))

    def test_all_identical_is_source_parity_only_not_activation(self):
        rows = self.rows()
        self.assertEqual(rows["OVERLAY/panel/main.py"], "BYTE_IDENTICAL_SHADOW")
        self.assertEqual(rows["OVERLAY/node/app/panel_client.py"], "BYTE_IDENTICAL_SHADOW")
        self.assertFalse([x for x in rows.values() if x.startswith("HOLD_")])
        self.assertEqual(rows["DOCKER_IMAGE_PROVENANCE"], "UNVERIFIED")
        self.assertEqual(rows["PANEL_HTTPS_443_AND_HMAC"], "UNVERIFIED")
        self.assertEqual(rows["AUTH_ACTIVATION"], "BLOCKED")

    def test_obsolete_overlay_causes_hold_and_cannot_hide_old_node_client(self):
        old = self.overlays / "node/panel_client.py"
        old.write_text("# legacy insecure client\nverify = False\n")
        rows = self.rows()
        self.assertEqual(rows["OVERLAY/node/app/panel_client.py"], "HOLD_OBSOLETE_SHADOW")
        self.assertEqual(rows["AUTH_ACTIVATION"], "BLOCKED")

    def test_missing_security_file_causes_hold(self):
        (self.node / "app/agent_auth.py").unlink()
        self.assertEqual(self.rows()["IMAGE/node/app/agent_auth.py"], "HOLD_MISSING_OR_INVALID")

    def test_invalid_python_security_code_causes_hold(self):
        (self.panel / "app/node_pairing_store.py").write_text("def x(:\n")
        self.assertEqual(
            self.rows()["IMAGE/panel/app/node_pairing_store.py"], "HOLD_MISSING_OR_INVALID"
        )

    def test_symlinked_image_and_shadow_sources_refused(self):
        old = self.overlays / "panel/main.py"
        old.unlink()
        old.symlink_to(self.panel / "main.py")
        self.assertEqual(self.rows()["OVERLAY/panel/main.py"], "HOLD_MISSING_SHADOW_SOURCE")
        sec = self.node / "app/signed_panel_client.py"
        sec.unlink()
        sec.symlink_to(self.panel / "main.py")
        self.assertEqual(self.rows()["IMAGE/node/app/signed_panel_client.py"], "HOLD_MISSING_OR_INVALID")

    def test_unknown_mount_source_causes_hold(self):
        current = str(self.overlays / "panel/main.py")
        self.pc.write_text(self.pc.read_text().replace(
            current + ":/app/main.py:ro", "/tmp/untrusted-main.py:/app/main.py:ro"
        ))
        self.assertEqual(self.rows()["OVERLAY/panel/main.py"], "HOLD_UNTRUSTED_SHADOW_SOURCE")

    def test_duplicate_mount_sources_cause_hold(self):
        self.pc.write_text(self.pc.read_text() + (
            "      - " + str(self.overlays / "panel/main.py") + ":/app/main.py:ro\n"
        ))
        self.assertEqual(self.rows()["OVERLAY/panel/main.py"], "HOLD_DUPLICATE_SHADOWS")

    def test_missing_shadow_is_no_host_shadow(self):
        self.pc.write_text("\n".join(
            x for x in self.pc.read_text().split("\n") if ":/app/main.py:ro" not in x
        ))
        self.assertEqual(self.rows()["OVERLAY/panel/main.py"], "NO_HOST_SHADOW")

    def test_source_and_target_not_mutated_and_packaging(self):
        before = (
            self.pc.read_bytes(), self.nc.read_bytes(),
            (self.overlays / "panel/main.py").read_bytes()
        )
        audit.assess(**self.arguments)
        after = (
            self.pc.read_bytes(), self.nc.read_bytes(),
            (self.overlays / "panel/main.py").read_bytes()
        )
        self.assertEqual(before, after)
        src = MODULE.read_text()
        for forbidden in ("subprocess.run(", "docker compose up", "systemctl restart",
                          "os.system(", "docker pull", "docker build"):
            self.assertNotIn(forbidden, src)
        for entry in ("install.sh", "u-opti"):
            self.assertIn("smite-auth-image-overlay-audit.py", (ROOT / entry).read_text())


if __name__ == "__main__":
    unittest.main()
