"""Disposable real Nginx TLS proxy test. NO host reload or production changes.

The test intentionally uses a self-signed cert and an unverified LOCAL test
client only; the production Foreign install client still verifies public TLS.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import importlib.util
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


renderer = module("foreign_install_nginx_renderer", "modules/smite-foreign-install-panel-ingress.py")
fixture = module("foreign_install_ingress_fixture", "tests/test-smite-foreign-install-panel-ingress.py")
TOKEN = "c" * 64


class Echo(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        self.rfile.read(size)
        data = json.dumps({"method": "POST", "path": self.path,
                           "ingress": self.headers.get("X-Smite-Pairing-Ingress")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


class ActualNginx(unittest.TestCase):
    def test_exact_ingress_and_method_barriers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mock = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
            thread = threading.Thread(target=mock.serve_forever, daemon=True)
            thread.start()
            process = None
            try:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                cert = root / "cert.pem"
                key = root / "key.pem"
                subprocess.run([
                    "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
                    "-keyout", str(key), "-out", str(cert), "-days", "1",
                    "-subj", "/CN=panel.example.com"], check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                secret = root / "ingress-secret.conf"
                secret.write_text('proxy_set_header X-Smite-Pairing-Ingress "' + TOKEN + '";\n')
                backend = renderer.render(fixture.baseline(), "panel.example.com").decode()
                # Fixture-only substitutions AFTER validating production template.
                backend = (backend
                    .replace("listen 127.0.0.1:8443 ssl;", f"listen 127.0.0.1:{port} ssl;")
                    .replace("http://127.0.0.1:8000", f"http://127.0.0.1:{mock.server_port}")
                    .replace("/etc/nginx/u-opti-smite-pairing-secret.conf", str(secret))
                    .replace("/etc/letsencrypt/live/panel.example.com/fullchain.pem", str(cert))
                    .replace("/etc/letsencrypt/live/panel.example.com/privkey.pem", str(key)))
                site = root / "backend.conf"
                site.write_text(backend)
                config = root / "nginx.conf"
                config.write_text(
                    f"worker_processes 1;\npid {root}/nginx.pid;\n"
                    "events { worker_connections 256; }\n"
                    f"http {{\n  error_log {root}/error.log notice;\n"
                    "  access_log off;\n"
                    f"  include {site};\n}}\n")
                check = subprocess.run(["nginx", "-t", "-p", str(root)+"/", "-c", str(config)],
                                       capture_output=True, timeout=10)
                self.assertEqual(check.returncode, 0, check.stderr.decode(errors="replace"))
                process = subprocess.Popen(
                    ["nginx", "-p", str(root)+"/", "-c", str(config), "-g", "daemon off;"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                for _ in range(60):
                    with socket.socket() as conn:
                        if conn.connect_ex(("127.0.0.1", port)) == 0:
                            break
                    if process.poll() is not None:
                        self.fail("Disposable Nginx failed to start")
                    time.sleep(.1)
                else:
                    self.fail("Disposable Nginx did not listen")

                def send(method, path, body=b"{}"):
                    # Local fixture only; no actual public TLS verification is claimed.
                    conn = http.client.HTTPSConnection(
                        "127.0.0.1", port, timeout=5,
                        context=ssl._create_unverified_context())
                    try:
                        conn.request(method, path, body=body, headers={
                            "Host":"panel.example.com", "X-Smite-Pairing-Ingress":"forged"})
                        reply = conn.getresponse()
                        payload = reply.read(16384)
                        return reply.status, payload
                    finally:
                        conn.close()

                for path, expected in (
                    ("/api/foreign-install/redeem", TOKEN),
                    ("/api/node-control/installation-status", None),
                    ("/api/foreign-install/issue", None),
                    ("/api/node-pairing/redeem", TOKEN),
                ):
                    with self.subTest(path=path):
                        status, data = send("POST", path)
                        self.assertEqual(status,200)
                        self.assertEqual(json.loads(data)["ingress"], expected)
                self.assertEqual(send("GET", "/api/foreign-install/redeem", b"")[0],403)
                self.assertEqual(send("GET", "/api/node-control/installation-status", b"")[0],403)
                self.assertEqual(send("POST", "/api/foreign-install/redeem", b"x"*9000)[0],413)
            finally:
                if process is not None:
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=5)
                mock.shutdown()
                mock.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
