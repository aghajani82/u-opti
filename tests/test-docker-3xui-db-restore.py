import contextlib
import importlib.util
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock


source = Path(__file__).resolve().parents[1] / "modules/docker-3xui-db-restore.py"
spec = importlib.util.spec_from_file_location("restore", source)
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


def create_database(path, values, sub_id):
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE settings (id INTEGER PRIMARY KEY, key TEXT, value TEXT);
            CREATE TABLE inbounds (enable INTEGER, settings TEXT);
            CREATE TABLE clients (enable INTEGER, sub_id TEXT);
        """)
        db.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", values.items())
        db.execute("INSERT INTO clients VALUES (1, ?)", (sub_id,))


class RestoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.base = root / "01"
        self.nginx = root / "nginx"
        self.site = self.nginx / "sites-available/3xui-example.org"
        self.live = self.base / "db/x-ui.db"
        self.source = root / "backup.db"
        self.snippet = self.nginx / "u-opti-3xui-subscription-example.org/public-url.conf"
        self.live.parent.mkdir(parents=True)
        self.site.parent.mkdir(parents=True)
        enabled = self.nginx / "sites-enabled"
        enabled.mkdir()
        (enabled / self.site.name).symlink_to(self.site)
        (self.base / "state.env").write_text(
            "DOMAIN=example.org\nCONTAINER_NAME=3xui-01\nSUBSCRIPTION_PORT=2095\n"
        )
        self.compat = self.base / "compat.env"
        self.compat.write_text("WEB_BASE_PATH=/new-panel/\n")
        self.site.write_text(
            "# U-OPTI-MANAGED-3XUI-NGINX\n"
            "# Web Base Path: /new-panel/\n"
            "    location = /new-panel {\n"
            "        return 301 /new-panel/;\n"
            "    }\n"
            "    location ^~ /new-panel/ {\n"
            "    }\n"
            "    # Sanaei Subscription\n"
        )
        create_database(self.live, {
            "webBasePath": "/new-panel/", "webPort": "2053", "subListen": "127.0.0.1",
            "subPort": "2095", "secret": "destination-secret", "subURI": "https://example.org/sub/",
        }, "destination")
        create_database(self.source, {
            "webBasePath": "/old-panel/", "webPort": "2087", "subPort": "2096",
            "subPath": "/old-backend/", "subURI": "https://example.org/old-sub/",
            "subClashEnable": "true", "subClashPath": "/clash-backend/",
            "subClashURI": "https://example.org/mihomo/",
        }, "original-client")

    def do_restore(self, failure=None):
        def command(*args, **kwargs):
            if args[:2] == ("docker", "inspect"):
                return "true"
            return ""

        with mock.patch.object(restore, "run", side_effect=command), \
             mock.patch.object(restore.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, "", "")), \
             mock.patch.object(restore, "verify_routes", side_effect=failure) as verify, \
             mock.patch("builtins.input", return_value="y"):
            restore.restore_locked("01", self.base, self.source, self.nginx)
            return verify.call_args.args

    def test_old_urls_and_identifier_with_destination_ports(self):
        _, panel, routes, subs, _ = self.do_restore()
        self.assertEqual(panel, "/old-panel/")
        self.assertIn(("subClashURI", "/mihomo/", "/clash-backend/"), routes)
        self.assertEqual(subs, ["original-client"])
        with contextlib.closing(restore.read_db(self.live)) as db:
            config = restore.settings(db)
        self.assertEqual(config["webPort"], "2053")
        self.assertEqual(config["subPort"], "2095")
        self.assertEqual(config["secret"], "destination-secret")
        self.assertEqual(config["subURI"], "https://example.org/old-sub/")
        self.assertEqual(config["subPath"], "/sub/")
        self.assertIn("127.0.0.1:2095/clash-backend/;", self.snippet.with_name("restored-formats.conf").read_text())
        self.assertIn("rewrite ^/old-sub/(.*)$ /sub/$1 last;", self.snippet.read_text())
        self.assertIn("location ^~ /old-panel/ {", self.site.read_text())
        self.assertEqual(self.compat.read_text(), "WEB_BASE_PATH=/old-panel/\n")
        self.assertEqual(restore.subscription_ids(self.live), ["original-client"])

    def test_failed_check_restores_database_site_and_preserves_custom_files(self):
        original_site = self.site.read_bytes()
        self.snippet.parent.mkdir()
        sibling = self.snippet.parent / "custom.conf"
        sibling.write_text("custom")
        with self.assertRaises(restore.RestoreError):
            self.do_restore(restore.RestoreError("HTTPS check failed"))
        self.assertEqual(self.site.read_bytes(), original_site)
        self.assertEqual(self.compat.read_text(), "WEB_BASE_PATH=/new-panel/\n")
        self.assertFalse(self.snippet.exists())
        self.assertEqual(sibling.read_text(), "custom")
        self.assertEqual(restore.subscription_ids(self.live), ["destination"])

    def set_clash_paths(self, public, backend):
        with contextlib.closing(sqlite3.connect(self.live)) as db, db:
            db.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", (
                ("subClashEnable", "true"),
                ("subClashPath", backend),
                ("subClashURI", f"https://example.org{public}"),
            ))

    def test_sync_adds_https_route_and_does_not_reload_twice(self):
        self.set_clash_paths("/mihomo/", "/clash-backend/")
        db_before = self.live.read_bytes()
        snippet = self.snippet.with_name("restored-formats.conf")
        with mock.patch.object(restore, "run") as run:
            restore.sync_subscription_formats(self.base, self.nginx)
            restore.sync_subscription_formats(self.base, self.nginx)
        self.assertIn("include " + str(snippet.parent / "*.conf") + ";", self.site.read_text())
        self.assertIn("location ^~ /mihomo/ {", snippet.read_text())
        self.assertIn("proxy_pass http://127.0.0.1:2095/clash-backend/;", snippet.read_text())
        self.assertEqual(self.live.read_bytes(), db_before)
        self.assertEqual(run.call_args_list.count(mock.call("systemctl", "reload", "nginx")), 1)

    def test_sync_refuses_sub_path_overlap_before_nginx_change(self):
        self.set_clash_paths("/mihomo/", "/sub/")
        before = self.site.read_bytes()
        with mock.patch.object(restore, "run") as run, self.assertRaisesRegex(restore.RestoreError, "Keep /sub/"):
            restore.sync_subscription_formats(self.base, self.nginx)
        self.assertEqual(self.site.read_bytes(), before)
        self.assertFalse(self.snippet.parent.exists())
        run.assert_not_called()

    def test_sync_restores_files_if_nginx_rejects_route(self):
        self.set_clash_paths("/mihomo/", "/clash-backend/")
        self.snippet.parent.mkdir()
        snippet = self.snippet.with_name("restored-formats.conf")
        snippet.write_text("# old route\n")
        before = self.site.read_bytes()
        fail = subprocess.CalledProcessError(1, "nginx")
        with mock.patch.object(restore, "run", side_effect=["", fail, "", ""]):
            with self.assertRaises(subprocess.CalledProcessError):
                restore.sync_subscription_formats(self.base, self.nginx)
        self.assertEqual(self.site.read_bytes(), before)
        self.assertEqual(snippet.read_text(), "# old route\n")

    def test_foreign_domain_and_reserved_paths_are_rejected(self):
        with self.assertRaises(restore.RestoreError):
            restore.public_path({"subURI": "https://old.example/sub/"}, "subURI", "/sub/", "example.org")
        with self.assertRaises(restore.RestoreError):
            restore.render_subscriptions([("subURI", "/12345/xhttp/", "/sub/")], "/panel/", 2095)


if __name__ == "__main__":
    unittest.main()
