"""Stage11 offline security image review-bundle tests (no Docker/VPS)."""
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "modules/smite-stage11-overlay-review.py"
spec = importlib.util.spec_from_file_location("smite_stage11_overlay_review", FILE)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class Stage11ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.panel = root / "panel-app"
        self.node = root / "node-app"
        self.host = root / "host-overlays"
        self.dest = root / "private-review"
        for dir in (self.panel, self.node, self.host):
            dir.mkdir(mode=0o700)
        for role, module, host_name in tool.SHADOWS:
            sample = "SECURITY_MODULE = True\n"
            for marker in tool.CONTRACTS.get((role, module), ()):
                sample += "# " + marker + "\n"
            src = (self.panel if role == "panel" else self.node) / module
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(sample)
            overlay = self.host / host_name
            overlay.parent.mkdir(parents=True, exist_ok=True)
            overlay.write_text(sample)
        self.kwargs = {
            "panel_root": self.panel, "node_root": self.node,
            "host_overlays": self.host, "destination": self.dest,
        }

    def test_parity_copies_to_private_review_bundle_no_live_change(self):
        old = (self.host / "panel/main.py").read_bytes()
        rows = tool.prepare(**self.kwargs)
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(row["status"] == "SOURCE_PARITY_ONLY" for row in rows))
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.dest / "panel/main.py").stat().st_mode), 0o600)
        self.assertEqual((self.host / "panel/main.py").read_bytes(), old)
        j = json.loads((self.dest / "REVIEW.json").read_text())
        self.assertFalse(j["activation_allowed"])
        self.assertFalse(j["source_images_provenance_verified"])
        self.assertFalse(j["old_host_mounts_modified"])
        with self.assertRaises(tool.Hold):
            tool.prepare(**self.kwargs)

    def test_old_frp_and_backhaul_overlay_features_are_flagged(self):
        host = self.host / "node/panel_client.py"
        host.write_text(host.read_text() +
                        '# SMITE_CONTROL_ADDRESS\n# SMITE_BACKHAUL_ADDRESS\n')
        host2 = self.host / "panel/main.py"
        host2.write_text(host2.read_text() +
                         '# existing_ports = server_spec.get("ports", [])\n')
        rows = tool.prepare(**self.kwargs)
        files = {row["role"] + "/" + row["module"]: row for row in rows}
        self.assertEqual(files["node/app/panel_client.py"]["host_feature_conflicts"], 2)
        self.assertEqual(files["panel/main.py"]["host_feature_conflicts"], 1)
        self.assertEqual(files["node/app/panel_client.py"]["status"], "HOLD_REVIEW_REQUIRED")
        self.assertFalse(json.loads((self.dest / "REVIEW.json").read_text())["activation_allowed"])

    def test_missing_image_security_hook_holds(self):
        path = self.panel / "app/node_client.py"
        path.write_text("NO_SIGNING = True\n")
        rows = tool.prepare(**self.kwargs)
        a = [x for x in rows if x["role"] == "panel" and x["module"] == "app/node_client.py"][0]
        self.assertEqual(a["status"], "HOLD_REVIEW_REQUIRED")
        self.assertGreater(a["missing_image_guards"], 0)

    def test_symlink_or_invalid_source_rejected_before_creating_bundle(self):
        path = self.panel / "app/routers/nodes.py"
        path.unlink()
        path.symlink_to(self.node / "app/core_adapters.py")
        with self.assertRaises(tool.Hold):
            tool.prepare(**self.kwargs)
        self.assertFalse(self.dest.exists())

    def test_no_live_compose_or_service_commands(self):
        s = FILE.read_text()
        for forbidden in ("subprocess.run(", "docker compose up",
                          "docker restart", "systemctl restart", "docker pull",
                          "os.system("):
            self.assertNotIn(forbidden, s)
        for name in ("install.sh", "u-opti"):
            self.assertIn("smite-stage11-overlay-review.py", (ROOT / name).read_text())


if __name__ == "__main__":
    unittest.main()
