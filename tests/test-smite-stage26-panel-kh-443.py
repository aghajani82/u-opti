#!/usr/bin/env python3
"""Stage26 real Panel -> TLS/443 Nginx -> strict KH Agent integration test.

Disposable PR CI ONLY. Root commands bind 127.0.0.1:443 on the ephemeral
runner and add a temporary /etc/hosts DNS mapping for a trusted test name.
No VPS, Docker, tunnels, public 443 listener, real IPs, external network or
system Nginx reload. Actual Smite Panel/Node transport code is imported.
"""
from __future__ import annotations

import asyncio
import contextlib
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_EVENT_NAME") != "pull_request":
    raise SystemExit("HOLD: Stage26 may run only on disposable GitHub PR runners")

ROOT = Path(__file__).resolve().parents[1]
SMITE = ROOT / ".stage20-smite-src"
if not (SMITE / "panel/app/signed_agent_transport.py").is_file() or not (
    SMITE / "node/app/routers/agent.py"
).is_file():
    raise SystemExit("HOLD: reviewed same-SHA Panel + Node sources missing")
HOST = "kh.stage26.test"
NODE_ID = "b3bfbd2e-3247-4f04-b74c-c22a164b0312"


def cmd(*arguments, ok=True):
    completed = subprocess.run(arguments, text=True, capture_output=True, timeout=35)
    if ok and completed.returncode != 0:
        # Commands never contain actual credentials.
        raise AssertionError("Stage26 command failed: " + repr(arguments[:3])
                             + " / " + completed.stderr[-350:])
    return completed


def ensure(condition, title):
    if not condition:
        raise AssertionError(title)


def wait_for(check, title):
    for _ in range(70):
        try:
            if check():
                return
        except (OSError, ValueError):
            pass
        time.sleep(.15)
    raise AssertionError("Stage26 readiness failed: " + title)


def local_health():
    c = http.client.HTTPConnection("127.0.0.1", 18888, timeout=2)
    try:
        c.request("GET", "/stage26-ready")
        reply = c.getresponse()
        reply.read()
        return reply.status == 200
    finally:
        c.close()


def nginx_config(directory: Path, cert: Path, key: Path, state: str):
    if state == "pass":
        handler = (
            "location /api/agent/ {\n"
            "  proxy_pass http://127.0.0.1:18888;\n"
            '  proxy_set_header Host "$host";\n'
            "  proxy_http_version 1.1;\n"
            "  proxy_request_buffering on;\n"
            "  proxy_redirect off;\n"
            "}\n"
        )
    elif state == "rewrite":
        handler = (
            "location = /api/agent/status {\n"
            "  proxy_pass http://127.0.0.1:18888/api/agent/status?modified=1;\n"
            "}\n"
            "location /api/agent/ { return 403; }\n"
        )
    elif state == "redirect":
        handler = (
            "location = /api/agent/status {\n"
            '  return 302 "https://kh.stage26.test/api/agent/status";\n'
            "}\n"
            "location /api/agent/ { return 403; }\n"
        )
    else:
        raise AssertionError("Unknown lab config")
    return (
        f"pid {directory}/nginx.pid;\n"
        f"error_log {directory}/nginx-errors.log warn;\n"
        "events { worker_connections 128; }\n"
        "http {\n"
        " access_log off;\n"
        " server {\n"
        "  listen 127.0.0.1:443 ssl;\n"
        f"  server_name {HOST};\n"
        f"  ssl_certificate {cert};\n"
        f"  ssl_certificate_key {key};\n"
        "  ssl_protocols TLSv1.2 TLSv1.3;\n"
        f"{handler}"
        "  location / { return 404; }\n"
        " }\n"
        "}\n"
    )


async def main_tests(root: Path, ca: Path, identity_secret: str):
    # The PANEL code imports its own "app" package only here. The NODE
    # runs in a separate uvicorn process with the Node-specific package.
    sys.path.insert(0, str(SMITE / "panel"))
    from cryptography.fernet import Fernet
    from sqlalchemy import select
    from app.database import engine, AsyncSessionLocal
    from app.models import Base, Node
    from app.config import settings
    from app import node_pairing_store
    from app.node_client import NodeClient
    from app.agent_request_signer import prepare_agent_request
    from app.signed_agent_transport import signed_agent_call, SignedAgentUnavailable
    import certifi
    import httpx

    database = root / "panel.sqlite3"
    settings.db_path = str(database)
    settings.smite_panel_agent_auth_mode = "signed"
    master = Fernet.generate_key().decode("ascii")
    settings.smite_node_pairing_master_key = master
    approved = root / "trusted"
    approved.mkdir(mode=0o700)
    origins = approved / "node-origins.json"
    origins.write_text(json.dumps({"version": 1, "nodes": {NODE_ID: {
        "role": "foreign", "node_name": "node-kh",
        "origin": f"https://{HOST}:443",
        "control_url": f"https://{HOST}/private-agent-gateway",
    }}}))
    origins.chmod(0o600)
    settings.smite_signed_node_origins_path = str(origins)

    # The engine is created at module import, before any settings mutation;
    # give it the database path up front using DB_PATH before import.
    ensure(engine.url.database == str(database), "Panel database engine not isolated")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        session.add(Node(
            id=NODE_ID, name="node-kh", fingerprint="stage26-local-only",
            status="pending",
            node_metadata={"role": "foreign", "node_name": "node-kh",
                           "provisioning": "reserved_for_pairing",
                           "api_address": "http://untrusted.invalid:8888"},
        ))
        await session.commit()
    node_pairing_store.initialize_schema(database)
    issued = node_pairing_store.issue_code(
        database, master_key=master, node_id=NODE_ID,
        role="foreign", admin_id="stage26-admin",
    )
    redeemed = node_pairing_store.redeem_code(
        database, master_key=master, code=issued.code,
        node_id=NODE_ID, role="foreign",
    )
    ensure(redeemed.secret == identity_secret, "Panel and KH identity key differ")
    # A key alone MUST NOT authorize control. With Nginx already running,
    # no attempt to contact an unapproved legacy target is allowed.
    client = NodeClient()
    with patch.object(certifi, "where", return_value=str(ca)):
        pending = await client.get_tunnel_status(NODE_ID)
        ensure(pending["status"] == "error", "Pending KH got signed control")

        async with AsyncSessionLocal() as session:
            node = (await session.execute(select(Node).where(Node.id == NODE_ID))).scalar_one()
            node.status = "active"
            node.node_metadata = {"role": "foreign", "node_name": "node-kh",
                                  "provisioning": "signed_checkin",
                                  "api_address": "http://untrusted.invalid:8888"}
            await session.commit()

        # Actual Panel NodeClient, real HMAC transport, real verified TLS
        # and Nginx URI passthrough to actual strict Agent router.
        ready = await client.get_tunnel_status(NODE_ID)
        if ready.get("status") != "ok":
            # No secrets/headers/full exceptions leave the CI environment.
            print("STAGE26_PANEL_CONTROL_RESULT=" + str(ready.get("status")))
            try:
                await signed_agent_call(
                    node_id=NODE_ID, address=f"https://{HOST}", using_frp=False,
                    method="GET", target="/api/agent/status", timeout=4,
                )
            except Exception as exc:
                print("STAGE26_TRANSPORT_FAILURE=" + type(exc).__name__)
                if exc.__cause__ is not None:
                    print("STAGE26_TRANSPORT_ROOT=" + type(exc.__cause__).__name__)
        ensure(ready.get("status") == "ok" and ready.get("active_tunnels") == 0,
               "Signed Panel->KH status via verified TLS failed")

        payload = {"tunnel_id": "inert-frp", "core": "frp", "type": "tcp",
                   "spec": {"local": "127.0.0.1:18081"}}
        applied = await client.send_to_node(NODE_ID, "/api/agent/tunnels/apply", payload)
        ensure(applied.get("status") == "success", "Signed Apply not accepted")
        result = await client.get_tunnel_status(NODE_ID)
        ensure(result.get("active_tunnels") == 1,
               "Fake adapter did not record exactly one signed Apply")
        removed = await client.send_to_node(
            NODE_ID, "/api/agent/tunnels/remove", {"tunnel_id": "inert-frp"})
        ensure(removed.get("status") == "success", "Signed Remove not accepted")
        ensure((await client.get_tunnel_status(NODE_ID)).get("active_tunnels") == 0,
               "Signed Remove did not reach real protected endpoint")
        print("STAGE26_REAL_PANEL_NODECLIENT_NGINX_TLS443_AGENT=PASS")
        print("STAGE26_SIGNED_STATUS_APPLY_REMOVE_INERT_ADAPTER=PASS")

        # No individual nonce can execute twice. A signed POST tampered in
        # transit with the exact original HMAC must be rejected.
        body, headers = prepare_agent_request(
            secret=redeemed.secret, node_id=NODE_ID, method="POST",
            target="/api/agent/tunnels/apply", payload=payload,
            nonce="c" * 32,
        )
        async with httpx.AsyncClient(
            verify=True, trust_env=False, follow_redirects=False, timeout=5
        ) as transport:
            url = f"https://{HOST}/api/agent/tunnels/apply"
            first = await transport.post(url, content=body, headers=headers)
            second = await transport.post(url, content=body, headers=headers)
            altered = await transport.post(
                url, content=body + b" ", headers=headers)
            ensure(first.status_code == 200, "Valid manual signed request failed")
            ensure(second.status_code == 401, "Repeated signature/nonce accepted")
            ensure(altered.status_code == 401, "Tampered HMAC body accepted")
        print("STAGE26_HMAC_REPLAY_AND_TAMPER_REJECTED=PASS")

        # Mocking ONLY the test trust-anchor loader still leaves the real
        # HTTPS certificate and SNI verification fully enabled. The wrong
        # trust file must fail; never fall back to HTTP or verify=False.
    other = root / "untrusted.crt"
    key = root / "untrusted.key"
    cmd("openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-nodes", "-days", "1", "-keyout", str(key), "-out", str(other),
        "-subj", "/CN=untrusted.stage26.test")
    with patch.object(certifi, "where", return_value=str(other)):
        result = await client.get_tunnel_status(NODE_ID)
        ensure(result.get("status") == "error", "Unknown CA was trusted")
    print("STAGE26_TLS_UNKNOWN_CA_FAILS_CLOSED=PASS")

    await engine.dispose()


def main():
    with tempfile.TemporaryDirectory(prefix="smite-stage26-") as work:
        root = Path(work)
        processes = []
        mapping = False
        conf = root / "nginx.conf"
        node = None
        try:
            ident = root / "identities"
            replay = root / "replay"
            ident.mkdir(mode=0o700)
            replay.mkdir(mode=0o700)

            # Panel must use its own encrypted secret; the Node must own
            # the same credential. It is generated by the Panel test setup
            # and passed to the Node only after pairing is completed.
            from cryptography.fernet import Fernet
            master = Fernet.generate_key().decode("ascii")
            # Pairing setup and key transport are implemented in Python
            # test harness. This fixture's key never appears in logs.
            import secrets
            paired_secret = secrets.token_hex(32)
            idfile = ident / "node-identity.json"
            idfile.write_text(json.dumps({
                "node_id": NODE_ID, "node_secret": paired_secret,
            }))
            idfile.chmod(0o600)

            env = dict(os.environ)
            env.update({
                "PYTHONPATH": str(SMITE / "node") + os.pathsep
                    + str(ROOT / "tests" / "fixtures"),
                "SMITE_AGENT_AUTH_MODE": "strict",
                "SMITE_NODE_PANEL_AUTH_MODE": "paused",
                "SMITE_AGENT_IDENTITY_PATH": str(idfile),
                "SMITE_AGENT_REPLAY_DB": str(replay / "nonce.sqlite3"),
            })
            node = subprocess.Popen([
                sys.executable, "-m", "uvicorn", "stage26_kh_agent:app",
                "--host", "127.0.0.1", "--port", "18888",
                "--no-access-log", "--log-level", "error",
            ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(node)
            wait_for(lambda: node.poll() is None and local_health(), "strict Agent startup")

            cert = root / "stage26.crt"
            key = root / "stage26.key"
            cmd("openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-nodes", "-days", "1", "-keyout", str(key), "-out", str(cert),
                "-subj", f"/CN={HOST}", "-addext", f"subjectAltName=DNS:{HOST}")

            conf.write_text(nginx_config(root, cert, key, "pass"))
            def nginx(*flags, ok=True):
                return cmd("sudo", "-n", "nginx", *flags, "-p", str(root) + "/",
                           "-c", str(conf), ok=ok)
            nginx("-t")
            # No outside interface is bound. Temporary root-only Nginx
            # exists exclusively on the disposable runner's loopback.
            gateway = subprocess.Popen(
                ["sudo", "-n", "nginx", "-p", str(root) + "/", "-c",
                 str(conf), "-g", "daemon off;"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            processes.append(gateway)
            # DNS name must match the actual TLS certificate SAN and origin
            # pin; hosts mapping is temporary on the disposable runner only.
            cmd("sudo", "-n", "sh", "-c",
                f"printf '\\n127.0.0.1 {HOST} # stage26-ci-only\\n' >> /etc/hosts")
            mapping = True
            wait_for(lambda: socket.create_connection(("127.0.0.1", 443), timeout=1).close()
                     is None, "ephemeral TLS/443 backend")
            # Set the DB path before importing Panel's async engine.
            os.environ["DB_PATH"] = str(root / "panel.sqlite3")
            # Direct use of actual pairing store needs matching secret;
            # monkeypatch the random generator only within this disposable
            # pairing issuance call, not any transport/security validation.
            from unittest.mock import patch as mock
            from importlib import import_module
            sys.path.insert(0, str(SMITE / "panel"))
            from app import node_pairing_store
            # Scope the one fixture-secret override to 32-byte
            # credential minting only. Genuine HMAC request nonces use
            # secrets.token_hex(16) and MUST retain their 32-char length.
            true_hex = node_pairing_store.secrets.token_hex
            def only_fixture_identity(size=None):
                if size == 32:
                    return paired_secret
                return true_hex(size)
            with mock.object(node_pairing_store.secrets, "token_hex",
                             side_effect=only_fixture_identity):
                asyncio.run(main_tests(root, cert, paired_secret))

            def reload(mode):
                conf.write_text(nginx_config(root, cert, key, mode))
                nginx("-t")
                nginx("-s", "reload")
                time.sleep(.35)

            # Check actual Panel transport does not tolerate a path rewrite,
            # redirect or silently use the legacy node_address HTTP path.
            import certifi
            from app.node_client import NodeClient
            client = NodeClient()
            async def test_bad_response():
                with patch.object(certifi, "where", return_value=str(cert)):
                    result = await client.get_tunnel_status(NODE_ID)
                    ensure(result.get("status") == "error",
                           "Unexpected success through modified gateway")
            reload("rewrite")
            asyncio.run(test_bad_response())
            reload("redirect")
            asyncio.run(test_bad_response())
            reload("pass")
            async def check_recovered():
                with patch.object(certifi, "where", return_value=str(cert)):
                    return await client.get_tunnel_status(NODE_ID)
            assert asyncio.run(check_recovered())["status"] == "ok"
            print("STAGE26_REWRITTEN_PATH_REDIRECT_DENIED_AND_ROLLBACK=PASS")
            print("STAGE26_PRODUCTION_IR_KH_UNCHANGED=YES")
        finally:
            if conf.exists():
                with contextlib.suppress(Exception):
                    cmd("sudo", "-n", "nginx", "-s", "quit", "-p",
                        str(root) + "/", "-c", str(conf), ok=False)
            for p in reversed(processes):
                if p.poll() is None:
                    p.terminate()
                try:
                    p.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    p.kill()
            if mapping:
                # /etc/hosts may be a mounted file on a runner. Modify it
                # in-place rather than relying on a rename-based sed -i.
                with contextlib.suppress(Exception):
                    cmd("sudo", "-n", "sh", "-c",
                        f"grep -v ' # stage26-ci-only$' /etc/hosts > {root}/hosts-clean && "
                        f"cat {root}/hosts-clean > /etc/hosts")


if __name__ == "__main__":
    main()
