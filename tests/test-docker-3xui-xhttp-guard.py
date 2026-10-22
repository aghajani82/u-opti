#!/usr/bin/env python3
"""Offline tests for KH's explicit XHTTP port/path allowlist."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

target = Path(__file__).resolve().parents[1] / "modules/docker-3xui-xhttp-guard.py"
spec = importlib.util.spec_from_file_location("guard", target)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def db(self, root, rows):
        path = Path(root) / "x-ui.db"
        with sqlite3.connect(path) as cx:
            cx.execute("CREATE TABLE inbounds (enable INTEGER, port INTEGER, listen TEXT, "
                       "protocol TEXT, stream_settings TEXT)")
            cx.executemany("INSERT INTO inbounds VALUES (?,?,?,?,?)", rows)
        return path

    def inbound(self, port=45121, path="/45121/a/", listen="127.0.0.1",
                enable=1, network="xhttp", security="none"):
        return (enable, port, listen, "vless",
                json.dumps({"network":network, "security":security,
                            "xhttpSettings":{"path":path}}))

    def listener(self, port, address="127.0.0.1"):
        return f'LISTEN 0 4096 {address}:{port} 0.0.0.0:* users:(("xray",pid=1,fd=5))\n'

    def test_dynamic_port_and_path_are_unrestricted_by_fixed_number(self):
        with tempfile.TemporaryDirectory() as directory:
            db = self.db(directory, [self.inbound(), self.inbound(45234, "/45234/web/test")])
            allowed = guard.validate_inbounds(db, {2053}, self.listener(45121)+self.listener(45234))
            self.assertEqual(allowed, {"/45121/a":45121, "/45234/web/test":45234})
            conf = guard.render(allowed)
            self.assertIn("location = /45121/a {", conf)
            self.assertIn("location ^~ /45234/web/test/ {", conf)
            self.assertNotIn("$fwdport", conf)

    def test_public_and_reserved_and_cross_port_paths_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = [(self.inbound(listen="0.0.0.0"),self.listener(45121)),
                     (self.inbound(),self.listener(45121,"0.0.0.0")),
                     (self.inbound(2053,"/2053/a"),self.listener(2053)),
                     (self.inbound(path="/45122/wrong"),self.listener(45121)),
                     (self.inbound(security="tls"),self.listener(45121))]
            for item, listener in cases:
                db = self.db(directory,[item])
                with self.assertRaises(guard.Hold):
                    guard.validate_inbounds(db, {2053}, listener)
                db.unlink()

    def test_disabled_inbounds_never_published(self):
        with tempfile.TemporaryDirectory() as directory:
            db = self.db(directory,[self.inbound(enable=0)])
            self.assertEqual(guard.validate_inbounds(db,set(),""), {})

    def test_migrate_known_vhost_only(self):
        site = """# U-OPTI-MANAGED-3XUI-NGINX
server {
    server_name kh.example.test;
    location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {
        if ($content_type ~* "^application/grpc") {
            grpc_pass grpc://127.0.0.1:$fwdport;
            break;
        }
        proxy_pass http://127.0.0.1:$fwdport$is_args$args;
    }
}
"""
        updated = guard.harden(site, "kh.example.test")
        self.assertIn("location ~ ^/[0-9]+/ { return 404; }",updated)
        self.assertIn("include /etc/nginx/u-opti-3xui-xhttp-kh.example.test/*.conf;",updated)
        self.assertEqual(updated,guard.harden(updated,"kh.example.test"))
        with self.assertRaises(guard.Hold):
            guard.harden(site.replace("grpc_pass","different"),"kh.example.test")


if __name__ == "__main__":
    unittest.main()
