#!/usr/bin/env python3
"""PR-only genuine signed FRPS owner API backed by a real tracked FRPS process.

Runs INSIDE one private --network none Docker container (not an active Node).
Exact reviewed Smite source, strict HMAC and durable SQLite replay are real.
The lightweight adapter registry is an isolated test fixture; the FRPS PID
and its loopback LISTEN socket are real. No external port or production write.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import psutil
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.node_auth import sign_request
from app.replay_enrollment import provision_once
from app.routers.agent import router

TARGET = "/api/agent/frp/owners"
NODE_ID = "uopti-ci-owner1"
OTHER_ID = "uopti-ci-foreign1"


def require(value, code):
    if not value:
        raise AssertionError(code)


def main():
    require(os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
            and os.environ.get("GITHUB_REPOSITORY") == "aghajani82/u-opti",
            "OWNER_PR_ONLY")
    require(Path("/usr/local/bin/frps").is_file(), "PINNED_FRPS_MISSING")
    # Even the FRPS executable is the exact official binary mounted readonly.
    require(subprocess.run(
        ["/usr/local/bin/frps", "--version"], capture_output=True,
        text=True, timeout=8, check=True).stdout.strip() == "0.71.0",
        "FRPS_VERSION_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="uopti-owner-ci-") as tmp:
        root = Path(tmp)
        identity_dir = root / "identity"
        replay_dir = root / "replay"
        identity_dir.mkdir(mode=0o700)
        replay_dir.mkdir(mode=0o700)
        identity_file = identity_dir / "node-identity.json"
        secret = secrets.token_hex(32)
        identity_file.write_text(json.dumps({
            "node_id": NODE_ID, "node_secret": secret}, sort_keys=True) + "\n")
        identity_file.chmod(0o600)
        replay_db = replay_dir / "agent-replay.sqlite3"
        provision_once(identity_path=identity_file, replay_path=replay_db)
        require(replay_db.is_file(), "DURABLE_REPLAY_MISSING")
        settings.smite_agent_auth_mode = "strict"
        settings.smite_agent_identity_path = str(identity_file)
        settings.smite_agent_replay_db = str(replay_db)

        conf = root / "frps.toml"
        conf.write_text(
            'bindAddr = "127.0.0.1"\n'
            'bindPort = 7000\n'
            'auth.method = "token"\n'
            'auth.token = ' + json.dumps(secrets.token_hex(24)) + "\n")
        conf.chmod(0o600)
        with open(root / "frps-out.log", "wb") as log:
            process = subprocess.Popen(
                ["/usr/local/bin/frps", "-c", str(conf)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            )
        try:
            # Only a genuine process/PID owning an actual loopback LISTEN
            # permits the read-only Owner evidence to become nonempty.
            ready = False
            for _ in range(75):
                if process.poll() is not None:
                    break
                try:
                    listeners = psutil.net_connections(kind="tcp")
                    ready = any(
                        c.pid == process.pid
                        and c.status == psutil.CONN_LISTEN
                        and getattr(c.laddr, "ip", None) == "127.0.0.1"
                        and getattr(c.laddr, "port", None) == 7000
                        for c in listeners)
                    if ready:
                        break
                except (psutil.Error, OSError):
                    pass
                time.sleep(0.1)
            require(ready, "REAL_OWNER_LOOPBACK_NOT_TRACKED")

            adapter = SimpleNamespace(
                name="frp", processes={"ci-owner": process})
            manager = SimpleNamespace(
                tunnel_configs={
                    "ci-owner": {
                        "core": "frp",
                        "spec": {"mode": "server", "bind_port": 7000,
                                 "token": "NOT_TO_BE_REVEALED"}}},
                active_tunnels={"ci-owner": adapter},
            )
            app = FastAPI()
            app.state.adapter_manager = manager
            app.include_router(router, prefix="/api/agent")
            with TestClient(app) as client:
                def signed(*, node_id=NODE_ID, key=secret):
                    return sign_request(
                        secret=key, node_id=node_id, method="GET",
                        target=TARGET, body=b"")

                require(client.get(TARGET).status_code == 401,
                        "ANONYMOUS_OWNER_ACCEPTED")
                require(client.get(TARGET, headers=signed(key="f"*64)).status_code == 401,
                        "FORGED_OWNER_SIGNATURE_ACCEPTED")
                require(client.get(TARGET, headers=signed(node_id=OTHER_ID)).status_code == 401,
                        "FOREIGN_NODE_ID_ACCEPTED")
                original = signed()
                result = client.get(TARGET, headers=original)
                require(result.status_code == 200, "OWNER_SIGNED_STATUS_NOT_OK")
                body = result.json()
                require(isinstance(body, dict)
                        and set(body) == {"status", "owners"}
                        and body["status"] == "success"
                        and body["owners"] == [{
                            "tunnel_id": "ci-owner",
                            "control_port": 7000,
                            "proxy_ports": []}],
                        "TRACKED_FRPS_OWNER_LISTENER_NOT_PROVEN")
                require("NOT_TO_BE_REVEALED" not in result.text,
                        "OWNER_TOKEN_LEAK")
                require(client.get(TARGET, headers=original).status_code == 401,
                        "REPLAYED_OWNER_ACCEPTED")
                # Endpoint remains signed, but proof fails closed when its
                # PID tracking, server mode or manager mapping is wrong.
                adapter.processes["ci-owner"] = SimpleNamespace(
                    pid=process.pid + 1000000, poll=lambda: None)
                require(client.get(TARGET, headers=signed()).json()["owners"] == [],
                        "UNTRACKED_OWNER_PID_ACCEPTED")
                adapter.processes["ci-owner"] = process
                manager.tunnel_configs["ci-owner"]["spec"]["mode"] = "client"
                require(client.get(TARGET, headers=signed()).json()["owners"] == [],
                        "CLIENT_MODE_AS_OWNER_ACCEPTED")
                manager.tunnel_configs["ci-owner"]["spec"]["mode"] = "server"
                manager.active_tunnels.clear()
                require(client.get(TARGET, headers=signed()).json()["owners"] == [],
                        "MISSING_OWNER_ADAPTER_ACCEPTED")
                manager.active_tunnels["ci-owner"] = adapter
                require(client.get(TARGET, headers=signed()).json()["owners"]
                        == body["owners"], "OWNER_TRACKED_RECOVERY_FAILED")
            # Process shutdown cannot leave a stale owner claim.
            process.terminate()
            process.wait(timeout=6)
            with TestClient(app) as client:
                require(client.get(TARGET, headers=signed()).json()["owners"] == [],
                        "STOPPED_OWNER_ACCEPTED")
            print("RC7_REAL_TRACKED_FRPS_SIGNED_OWNER=PASS")
            print("RC7_REAL_OWNER_HMAC_REPLAY_AND_IDENTITY_DENIAL=PASS")
            print("RC7_REAL_OWNER_PID_AND_LISTEN_FAIL_CLOSED=PASS")
            print("RC7_FOREIGN_CHILD_SIGNED_ROUTE=NOT_PROVEN")
            print("RC7_BROKER_XHTTP_LIVE_CONTINUITY=NOT_PROVEN")
            print("INSTALL_ALLOWED=NO")
            print("ACTIVATION_GATE=HOLD")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never emit HMAC secrets/FRPS auth data or test internals.
        print("HOLD: SIGNED_TRACKED_OWNER_CI_NOT_PROVEN", file=sys.stderr)
        raise SystemExit(2) from None
