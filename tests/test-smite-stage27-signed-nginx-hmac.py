#!/usr/bin/env python3
"""Stage27: actual Stage12 Nginx candidate -> TLS/443 -> pinned Smite strict Node.

PR-only disposable GitHub runner. Nginx binds 127.0.0.1:443; Node binds
127.0.0.1:18888. No public listener, Docker, real tunnels, host-site edits,
IP routing edits, /etc/hosts edits, release, or IR/KH servers.
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
    raise SystemExit("HOLD: STAGE27_REQUIRES_DISPOSABLE_PR_RUNNER")

ROOT = Path(__file__).resolve().parents[1]
SMITE = ROOT / ".stage27-smite-src"
if not (SMITE / "node/app/agent_auth.py").is_file():
    raise SystemExit("HOLD: PINNED_SMITE_NOT_CHECKED_OUT")
spec = importlib.util.spec_from_file_location(
    "stage27_nginx_inert_candidate", ROOT / "modules/smite-stage12-nginx-hmac-plan.py")
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)
spec = importlib.util.spec_from_file_location(
    "stage27_pinned_smite_hmac", SMITE / "node/app/node_auth.py")
signer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signer)

HOST = "kh.stage27.test"
NODE_ID = "bbbbbbbb-1111-2222-3333-444444444444"
BACKEND = "127.0.0.1:18888"
SIGN_PATH = "/api/agent/status"


def require(test: bool, label: str) -> None:
    if not test:
        raise AssertionError(label)


def run(*argv: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=50)
    if proc.returncode:
        # Commands do not include credentials. Limit diagnostic exposure.
        raise AssertionError("STAGE27_CHILD_COMMAND_FAILED " + repr(argv[:3])
                             + " " + proc.stderr[-350:])
    return proc


def request(context: ssl.SSLContext, method: str, target: str,
            *, body: bytes | None = None, headers: dict | None = None,
            hostname: str = HOST, source_ip: str = "127.0.0.1") -> tuple[int, bytes]:
    class LoopbackVerifiedTLS(http.client.HTTPSConnection):
        def connect(self) -> None:
            sock = socket.create_connection(("127.0.0.1", 443), timeout=4,
                                            source_address=(source_ip, 0))
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)

    connection = LoopbackVerifiedTLS(hostname, 443, timeout=6, context=context)
    try:
        connection.request(method, target, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def checked_json(body: bytes) -> dict:
    value = json.loads(body)
    require(isinstance(value, dict), "STAGE27_RESPONSE_NOT_JSON_OBJECT")
    return value


def private_nginx_config(root: Path, crt: Path, key: Path, location: str) -> str:
    return (
        f"pid {root}/nginx.pid;\n"
        f"error_log {root}/nginx-error.log warn;\n"
        "events { worker_connections 128; }\n"
        "http {\n"
        "  access_log off;\n"
        "  server {\n"
        "    listen 127.0.0.1:443 ssl;\n"
        f"    server_name {HOST};\n"
        f"    ssl_certificate {crt};\n"
        f"    ssl_certificate_key {key};\n"
        "    ssl_protocols TLSv1.2 TLSv1.3;\n"
        f"    {location}\n"
        "    location / { return 404; }\n"
        "  }\n"
        "}\n"
    )


def main() -> None:
    processes: list[subprocess.Popen] = []
    with tempfile.TemporaryDirectory(prefix="uopti-stage27-loopback-") as dirname:
        root = Path(dirname)
        identity_dir, replay_dir = root / "identity", root / "replay"
        identity_dir.mkdir(mode=0o700)
        replay_dir.mkdir(mode=0o700)
        credential = identity_dir / "node-identity.json"
        replay = replay_dir / "agent-replay.sqlite3"
        # Disposable fixture only. Do not expose this key to logs.
        key_bytes = b"b" * 64
        credential.write_text(json.dumps({
            "version": 1, "node_id": NODE_ID, "node_secret": key_bytes.decode()
        }))
        credential.chmod(0o600)
        env = {**os.environ,
               "PYTHONPATH": str(SMITE / "node") + os.pathsep
                             + str(ROOT / "tests/fixtures"),
               "SMITE_AGENT_AUTH_MODE": "strict",
               "SMITE_ENGINE_INVENTORY_MODE": "managed",
               "SMITE_AGENT_IDENTITY_PATH": str(credential),
               "SMITE_AGENT_REPLAY_DB": str(replay)}
        # Explicit one-time offline bootstrap. The actual Agent request
        # must NOT create its own replay database.
        subprocess.run([
            sys.executable, "-c",
            "from app.agent_auth import DurableNonceStore; "
            "import os; "
            "DurableNonceStore.initialize_new(os.environ['SMITE_AGENT_REPLAY_DB'], "
            + repr(NODE_ID) + ")"
        ], env=env, check=True, capture_output=True, timeout=30)
        require(replay.is_file() and (replay.stat().st_mode & 0o777) == 0o600,
                "STAGE27_REPLAY_BOOTSTRAP_MISSING")

        cert, private_key = root / "test.crt", root / "test.key"
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "1", "-keyout", str(private_key),
            "-out", str(cert), "-subj", f"/CN={HOST}",
            "-addext", f"subjectAltName=DNS:{HOST}")
        real_candidate = plan.render(panel_ip="198.51.100.24")
        require("proxy_pass http://127.0.0.1:8888;" in real_candidate,
                "STAGE12_CANDIDATE_HAS_DIFFERENT_UPSTREAM")
        require("proxy_pass http://127.0.0.1:8888/;" not in real_candidate,
                "STAGE12_CANDIDATE_REWRITES_PATH")
        # SINGLE deliberately scoped ephemeral test substitution: the
        # candidate's Node loopback port becomes the isolated test port.
        location = real_candidate.replace(
            "proxy_pass http://127.0.0.1:8888;",
            "proxy_pass http://127.0.0.1:18888;")
        require("location ^~ /api/agent/" in location
                and "deny all;" in location
                and "allow 127.0.0.1;" in location,
                "STAGE12_LOCATION_POLICY_CHANGED")
        cfg = root / "nginx.conf"
        cfg.write_text(private_nginx_config(root, cert, private_key, location))
        node = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "stage26_kh_agent:app",
             "--host", "127.0.0.1", "--port", "18888",
             "--no-access-log", "--log-level", "error"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(node)
        try:
            for _ in range(80):
                if node.poll() is not None:
                    raise AssertionError("STAGE27_NODE_DIED")
                try:
                    c = http.client.HTTPConnection("127.0.0.1", 18888, timeout=1)
                    c.request("GET", "/stage26-ready")
                    response = c.getresponse()
                    response.read()
                    c.close()
                    if response.status == 200:
                        break
                except (OSError, ValueError):
                    time.sleep(.2)
            else:
                raise AssertionError("STAGE27_NODE_NOT_READY")
            def nginx(*args: str) -> None:
                run("sudo", "-n", "nginx", *args, "-p", str(root) + "/",
                    "-c", str(cfg))
            nginx("-t")
            gateway = subprocess.Popen([
                "sudo", "-n", "nginx", "-p", str(root) + "/",
                "-c", str(cfg), "-g", "daemon off;"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(gateway)
            tls = ssl.create_default_context(cafile=str(cert))
            require(tls.verify_mode == ssl.CERT_REQUIRED and tls.check_hostname,
                    "STAGE27_UNVERIFIED_TLS_CONTEXT")
            for _ in range(80):
                try:
                    request(tls, "GET", "/stage27-nonexistent")
                    break
                except OSError:
                    time.sleep(.2)
            else:
                raise AssertionError("STAGE27_TLS_NOT_READY")
            # Exact real certificate/SNI verification. A fake host or
            # unknown CA must not be silently accepted.
            try:
                request(ssl.create_default_context(), "GET", SIGN_PATH)
            except ssl.SSLError:
                pass
            else:
                raise AssertionError("STAGE27_UNTRUSTED_CA_ACCEPTED")
            try:
                request(tls, "GET", SIGN_PATH, hostname="wrong.stage27.test")
            except ssl.SSLError:
                pass
            else:
                raise AssertionError("STAGE27_BAD_HOSTNAME_ACCEPTED")
            print("STAGE27_TLS443_CA_SNI_REAL_VERIFICATION=PASS")

            # Stage28: the Stage12 candidate ACL must use the true socket
            # peer, not caller-provided forwarding headers. 127.0.0.2
            # is an independent loopback source, NOT in the allow list.
            # A denied request must not consume its signed Node nonce.
            denied = signer.sign_request(
                secret=key_bytes, node_id=NODE_ID, method="GET",
                target=SIGN_PATH, body=b"", nonce="2" * 32)
            forged_forwarded = {
                **denied,
                "X-Forwarded-For": "198.51.100.24",
                "X-Real-IP": "198.51.100.24",
                "Forwarded": "for=198.51.100.24;proto=https",
            }
            require(request(tls, "GET", SIGN_PATH, headers=forged_forwarded,
                            source_ip="127.0.0.2")[0] == 403,
                    "STAGE28_FORGED_PANEL_IP_BYPASSED_SOURCE_ACL")
            require(request(tls, "GET", SIGN_PATH, headers=denied)[0] == 200,
                    "STAGE28_NGINX_DENIED_REQUEST_CONSUMED_HMAC_NONCE")
            require(request(tls, "GET", SIGN_PATH, headers=denied)[0] == 401,
                    "STAGE28_REPLAY_NOT_DENIED_AFTER_VALID_SOURCE")
            require(request(tls, "GET", SIGN_PATH, source_ip="127.0.0.2")[0] == 403,
                    "STAGE28_UNSIGNED_FORBIDDEN_SOURCE_NOT_DENIED")
            print("STAGE28_REAL_SOURCE_IP_ACL_FORGED_HEADERS_REJECTED=PASS")

            require(request(tls, "GET", SIGN_PATH)[0] == 401,
                    "STAGE27_UNSIGNED_AGENT_ACCEPTED")
            signed = signer.sign_request(
                secret=key_bytes, node_id=NODE_ID,
                method="GET", target=SIGN_PATH, body=b"", nonce="a" * 32)
            status, output = request(tls, "GET", SIGN_PATH, headers=signed)
            require(status == 200 and checked_json(output)["status"] == "ok",
                    "STAGE27_SIGNED_STATUS_CHANGED_THROUGH_PROXY")
            require(request(tls, "GET", SIGN_PATH, headers=signed)[0] == 401,
                    "STAGE27_REPLAY_NOT_REJECTED")

            query = "/api/agent/tunnels/status?tunnel_id=alpha-123"
            signature = signer.sign_request(
                secret=key_bytes, node_id=NODE_ID, method="GET",
                target=query, body=b"", nonce="c" * 32)
            code, payload = request(tls, "GET", query, headers=signature)
            require(code == 200 and checked_json(payload)["data"] == {"running": False},
                    "STAGE27_QUERY_NOT_PRESERVED")
            require(request(tls, "GET",
                "/api/agent/tunnels/status?tunnel_id=alpha-124",
                headers=signature)[0] == 401,
                "STAGE27_QUERY_TAMPER_ACCEPTED")
            require(request(tls, "GET", query, headers=signature)[0] == 401,
                    "STAGE27_QUERY_NONCE_REPLAY_ACCEPTED")
            print("STAGE27_UNCHANGED_QUERY_AND_REPLAY=PASS")

            body = b'{"tunnel_id":"no-real-tunnel"}'
            signed_post = signer.sign_request(
                secret=key_bytes, node_id=NODE_ID, method="POST",
                target="/api/agent/tunnels/remove", body=body,
                nonce="d" * 32)
            header = {**signed_post, "Content-Type": "application/json"}
            code, payload = request(tls, "POST", "/api/agent/tunnels/remove",
                                    body=body, headers=header)
            require(code == 200 and checked_json(payload)["status"] == "success",
                    "STAGE27_POST_RAW_BODY_NOT_PRESERVED")
            require(request(tls, "POST", "/api/agent/tunnels/remove",
                body=body + b" ", headers=header)[0] == 401,
                "STAGE27_TAMPERED_POST_ACCEPTED")
            require(request(tls, "POST", "/api/agent/tunnels/remove",
                body=body, headers=header)[0] == 401,
                "STAGE27_POST_NONCE_REPLAY_ACCEPTED")
            require(request(tls, "PUT", SIGN_PATH)[0] == 403,
                    "STAGE27_NGINX_METHOD_ACL_MISSING")
            print("STAGE27_SIGNED_RAW_POST_AND_ACCESS_POLICY=PASS")

            # A deliberately wrong path rewrite MUST fail, even with a
            # correctly signed original target.
            def reload(extra: str) -> None:
                cfg.write_text(private_nginx_config(
                    root, cert, private_key, extra + "\n" + location))
                nginx("-t")
                nginx("-s", "reload")
                time.sleep(.5)

            reload(
                "location = /api/agent/status { "
                "proxy_pass http://127.0.0.1:18888/api/agent/status?modified=1; }")
            different = signer.sign_request(
                secret=key_bytes, node_id=NODE_ID,
                method="GET", target=SIGN_PATH, body=b"", nonce="e" * 32)
            require(request(tls, "GET", SIGN_PATH, headers=different)[0] == 401,
                    "STAGE27_REWRITTEN_HMAC_TARGET_ACCEPTED")
            reload("location = /api/agent/status { "
                   "return 302 https://kh.stage27.test/api/agent/status; }")
            require(request(tls, "GET", SIGN_PATH)[0] == 302,
                    "STAGE27_REDIRECT_PREVENTION_NOT_EXERCISED")
            cfg.write_text(private_nginx_config(root, cert, private_key, location))
            nginx("-t")
            nginx("-s", "reload")
            time.sleep(.5)
            fresh = signer.sign_request(
                secret=key_bytes, node_id=NODE_ID,
                method="GET", target=SIGN_PATH, body=b"", nonce="f" * 32)
            require(request(tls, "GET", SIGN_PATH, headers=fresh)[0] == 200,
                    "STAGE27_GATEWAY_RESTORE_FAILED")
            print("STAGE27_REWRITE_REDIRECT_DENIED_AND_RESTORED=PASS")

            # Stage28: read_identity reads the private pairing record on
            # each request. A different Node ID must NOT inherit authorization
            # just because the old HMAC key is still present.
            original_identity = credential.read_bytes()
            credential.write_text(json.dumps({
                "version": 1, "node_id": "cccccccc-1111-2222-3333-444444444444",
                "node_secret": key_bytes.decode()
            }))
            credential.chmod(0o600)
            incompatible = signer.sign_request(
                secret=key_bytes, node_id=NODE_ID,
                method="GET", target=SIGN_PATH, body=b"", nonce="3" * 32)
            require(request(tls, "GET", SIGN_PATH, headers=incompatible)[0] == 401,
                    "STAGE28_DIFFERENT_NODE_ID_REUSED_OLD_HMAC")
            credential.write_bytes(original_identity)
            credential.chmod(0o600)
            require(request(tls, "GET", SIGN_PATH, headers=incompatible)[0] == 200,
                    "STAGE28_ORIGINAL_PAIRING_NOT_RECOVERED")
            require(request(tls, "GET", SIGN_PATH, headers=incompatible)[0] == 401,
                    "STAGE28_PAIRING_RESTORE_REPLAY_ACCEPTED")
            print("STAGE28_PAIRED_IDENTITY_DRIFT_DENIED=PASS")

            # A freshly initialized replay DB tied to ANOTHER paired Node
            # must not be accepted even with the correct original HMAC.
            # This is NOT an approved replay store restore procedure.
            original_replay = replay_dir / "preserved-original.sqlite3"
            foreign_replay = replay_dir / "foreign-node.sqlite3"
            init = (
                "from app.agent_auth import DurableNonceStore;"
                "DurableNonceStore.initialize_new("
                "os.environ['SMITE_AGENT_FOREIGN_REPLAY'],"
                "'cccccccc-1111-2222-3333-444444444444')"
            )
            import_env = dict(env)
            import_env["SMITE_AGENT_FOREIGN_REPLAY"] = str(foreign_replay)
            subprocess.run(
                [sys.executable, "-c", "import os;" + init],
                env=import_env, capture_output=True, timeout=30, check=True)
            os.replace(replay, original_replay)
            os.replace(foreign_replay, replay)
            unrelated = signer.sign_request(
                secret=key_bytes, node_id=NODE_ID,
                method="GET", target=SIGN_PATH, body=b"", nonce="4" * 32)
            require(request(tls, "GET", SIGN_PATH, headers=unrelated)[0] == 503,
                    "STAGE28_OTHER_NODE_REPLAY_DB_ACCEPTED")
            # Restore the *same* original DB bytes and history while all
            # authentication was denied; never restore a stale copy.
            os.replace(replay, foreign_replay)
            os.replace(original_replay, replay)
            require(request(tls, "GET", SIGN_PATH, headers=unrelated)[0] == 200,
                    "STAGE28_CONTINUOUS_REPLAY_STORE_NOT_RECOVERED")
            require(request(tls, "GET", SIGN_PATH, headers=unrelated)[0] == 401,
                    "STAGE28_REPLAY_AFTER_RECOVERY_ACCEPTED")
            print("STAGE28_FOREIGN_NODE_REPLAY_DB_DENIED=PASS")

            replay.unlink()
            lost = signer.sign_request(
                secret=key_bytes, node_id=NODE_ID,
                method="GET", target=SIGN_PATH, body=b"", nonce="1" * 32)
            require(request(tls, "GET", SIGN_PATH, headers=lost)[0] == 503,
                    "STAGE27_LOST_REPLAY_NOT_FAIL_CLOSED")
            require(not replay.exists(), "STAGE27_NODE_RECREATED_LOST_REPLAY_DB")
            print("STAGE27_REPLAY_DB_LOSS_STILL_HOLD_OVER_TLS443=PASS")
            print("STAGE27_INSTALL_ALLOWED=NO")
            print("STAGE27_IR_KH_UNCHANGED=YES")
        finally:
            # Only stop the isolated sandbox's own Nginx config.
            if cfg.exists() and len(processes) > 1:
                subprocess.run(
                    ["sudo", "-n", "nginx", "-s", "quit",
                     "-p", str(root) + "/", "-c", str(cfg)],
                    capture_output=True, timeout=8, check=False)
            for process in reversed(processes):
                try:
                    process.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)


if __name__ == "__main__":
    main()
