#!/usr/bin/env python3
"""Offline regression: retained FRP WSS + Backhaul WS/TLS route coexistence.

Only localhost Nginx in a temporary sandbox. Dynamic port substitutions are
test-only. This does not prove a real WS data-plane, remote owner/child
continuity, or authorization to Apply a production Backhaul tunnel.
"""
from __future__ import annotations

from contextlib import ExitStack
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "modules/smite-gateway.sh"
RENDER = ROOT / "modules/smite-backhaul-standard.sh"


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def nginx_config(root: Path, servers: str) -> Path:
    (root / "logs").mkdir(exist_ok=True)
    (root / "client_body_temp").mkdir(exist_ok=True)
    config = root / "nginx.conf"
    config.write_text(
        f"worker_processes 1;\npid {root}/nginx.pid;\n"
        f"error_log {root}/logs/error.log warn;\n"
        "events { worker_connections 256; }\n"
        f"http {{ access_log off; client_body_temp_path {root}/client_body_temp;\n"
        f"{servers}\n}}\n"
    )
    return config


def spawn_nginx(stack: ExitStack, root: Path, config: Path) -> None:
    cmd = ["nginx", "-p", str(root) + "/", "-c", str(config)]
    subprocess.run(cmd + ["-t"], check=True, capture_output=True, text=True)
    proc = subprocess.Popen(cmd + ["-g", "daemon off;"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def close():
        proc.terminate()
        try:
            proc.communicate(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=2)
    stack.callback(close)
    time.sleep(.15)
    if proc.poll() is not None:
        raise AssertionError("isolated Nginx exited unexpectedly")


def mock_upstream(stack: ExitStack, label: str, local_port: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = f'{label}|{self.path}|{self.headers.get("Upgrade", "")}'.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", local_port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    stack.callback(lambda: (server.shutdown(), server.server_close(), thread.join(2)))


def request(tls: bool, port_number: int, path: str, *, upgrade: bool = False,
            trusted_ca: Path | None = None):
    if tls:
        assert trusted_ca is not None
        context = ssl.create_default_context(cafile=str(trusted_ca))

        class PinnedLoopbackHTTPS(HTTPSConnection):
            def connect(self):
                sock = socket.create_connection(("127.0.0.1", self.port), self.timeout)
                self.sock = context.wrap_socket(sock, server_hostname="ir.example.test")

        conn = PinnedLoopbackHTTPS("ir.example.test", port_number, timeout=3,
                                  context=context)
    else:
        conn = HTTPConnection("127.0.0.1", port_number, timeout=3)
    try:
        headers = {"Host": "ir.example.test"}
        if upgrade:
            headers.update({"Upgrade": "websocket", "Connection": "Upgrade"})
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        return response.status, response.read().decode(errors="replace")
    finally:
        conn.close()


class Shared443Regression(unittest.TestCase):
    def test_real_nginx_shared_tls_ws_frp_and_backhaul(self):
        self.assertIsNotNone(shutil.which("nginx"), "real Nginx required, no silent CI skip")
        self.assertIsNotNone(shutil.which("openssl"), "OpenSSL required, no silent CI skip")
        gateway = GATEWAY.read_text()
        match = re.search(r'(?m)^block = """(\s*# BEGIN U-OPTI STANDARD FRP WSS.*?)"""',
                          gateway, re.DOTALL)
        self.assertIsNotNone(match, "actual FRP WSS gateway block was not found")
        frp = match.group(1)
        self.assertIn("location = /~!frp {", frp)
        self.assertIn("proxy_pass http://127.0.0.1:7000;", frp)
        bh = subprocess.check_output(["bash", str(RENDER), "--render-ir-control", "3080"],
                                     text=True)
        foreign = subprocess.check_output(
            ["bash", str(RENDER), "--render-kh-bridge", "ir.example.test", "13080"],
            text=True)
        self.assertEqual(bh.count("proxy_pass http://127.0.0.1:3080;"), 2)
        self.assertEqual(foreign.count("proxy_ssl_verify on;"), 2)
        self.assertIn("proxy_pass https://ir.example.test:443;", foreign)
        self.assertNotIn("location = /~!frp", bh)

        with tempfile.TemporaryDirectory(prefix="uopti-shared443-") as tmp:
            base = Path(tmp)
            cert = base / "ir.crt"
            key = base / "ir.key"
            other = base / "wrong-ca.crt"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-days", "1", "-subj", "/CN=ir.example.test",
                            "-addext", "subjectAltName=DNS:ir.example.test",
                            "-keyout", str(key), "-out", str(cert)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-days", "1", "-subj", "/CN=wrong.example.test",
                            "-keyout", str(base / "wrong-ca.key"), "-out", str(other)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ir_https, kh_bridge, kh_bad = port(), port(), port()
            frp_port, bh_port, child_port, panel_port = port(), port(), port(), port()
            self.assertEqual(len({ir_https, kh_bridge, kh_bad, frp_port, bh_port,
                                  child_port, panel_port}), 7)
            # Test-only rewrite of the canonical loopback ports. Never export
            # or apply this configuration to a host or to a live namespace.
            frp = frp.replace("127.0.0.1:7000", f"127.0.0.1:{frp_port}")
            bh = bh.replace("127.0.0.1:3080", f"127.0.0.1:{bh_port}")
            ir = f"""server {{
                listen 127.0.0.1:{ir_https} ssl;
                server_name ir.example.test;
                ssl_certificate {cert};
                ssl_certificate_key {key};
                {frp}
                {bh}
                location = /20182/category-software-99 {{
                    proxy_pass http://127.0.0.1:{child_port};
                }}
                location ^~ /20182/category-software-99/ {{
                    proxy_pass http://127.0.0.1:{child_port};
                }}
                location / {{ proxy_pass http://127.0.0.1:{panel_port}; }}
            }}"""
            # Strict upstream certificate/SNI verification survives the
            # disposable port rewrite; no production config is modified.
            foreign = (foreign.replace("127.0.0.1:13080", f"127.0.0.1:{kh_bridge}")
                       .replace("https://ir.example.test:443",
                                f"https://127.0.0.1:{ir_https}")
                       .replace("/etc/ssl/certs/ca-certificates.crt", str(cert)))
            bad = (foreign.replace(f"127.0.0.1:{kh_bridge}", f"127.0.0.1:{kh_bad}")
                   .replace(str(cert), str(other))
                   # Stop test-only reuse of a previously verified session
                   # concealing the deliberately wrong trust root.
                   .replace("proxy_ssl_verify on;",
                            "proxy_ssl_verify on;\n        proxy_ssl_session_reuse off;"))
            ir_dir, kh_dir = base / "ir", base / "foreign"
            ir_dir.mkdir()
            kh_dir.mkdir()
            with ExitStack() as stack:
                for name, p in (("frp", frp_port), ("backhaul", bh_port),
                                ("child20182", child_port), ("panel", panel_port)):
                    mock_upstream(stack, name, p)
                spawn_nginx(stack, ir_dir, nginx_config(ir_dir, ir))
                spawn_nginx(stack, kh_dir, nginx_config(kh_dir, foreign + "\n" + bad))
                for path, label in (
                    ("/~!frp", "frp"),
                    ("/channel", "backhaul"),
                    ("/tunnel/alpha", "backhaul"),
                    ("/20182/category-software-99", "child20182"),
                    ("/20182/category-software-99/other", "child20182"),
                    ("/api/status", "panel"),
                ):
                    with self.subTest(path=path):
                        status, body = request(True, ir_https, path, upgrade=True,
                                               trusted_ca=cert)
                        self.assertEqual(status, 200)
                        upgraded = "websocket" if label in ("frp", "backhaul") else ""
                        self.assertEqual(body, f"{label}|{path}|{upgraded}")
                # /tunnel (without slash) is not the signed /tunnel/ID route.
                status, _ = request(True, ir_https, "/tunnel", trusted_ca=cert)
                self.assertEqual(status, 301)
                for path in ("/channel", "/tunnel/alpha"):
                    status, _ = request(False, kh_bad, path, upgrade=True)
                    self.assertEqual(status, 502, "wrong TLS CA must fail closed")
                    status, body = request(False, kh_bridge, path, upgrade=True)
                    self.assertEqual(status, 200)
                    self.assertEqual(body, f"backhaul|{path}|websocket")
                status, body = request(True, ir_https, "/~!frp", upgrade=True,
                                       trusted_ca=cert)
                self.assertEqual((status, body), (200, "frp|/~!frp|websocket"))


if __name__ == "__main__":
    unittest.main()
