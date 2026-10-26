#!/usr/bin/env python3
"""Read-only, fail-closed mixed-RC.2 Smite foreign signed pairing admission.

IR: exact RC.2 Panel, signed RC.1 local Node, trusted origins mount, signed
gateway-prefix transport and HTTPS Panel status.
KH: exact RC.2 paused Node, managed RC.1 state, one-line Node Compose,
private HTTPS/443 gateway, XHTTP/Nginx and explicit security modes.
This tool does NOT reserve a Node, read/print pairing keys, sign a request,
enroll, approve any origin, write configuration, pull or recreate containers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

PANEL_IMAGE = ("ghcr.io/aghajani82/smite-panel@sha256:"
               "9101898e19631d334b754ba8e956b63ab7dfaee304a8f9b954cf30a185125e8e")
IR_NODE_IMAGE = ("ghcr.io/aghajani82/smite-node@sha256:"
                 "9099262bb0d5fc8b737269f3e6dc16831a1d3e8b536b7b95ba131129ed06a7ec")
KH_NODE_IMAGE = ("ghcr.io/aghajani82/smite-node@sha256:"
                 "2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78")
SANAEI_IMAGE = "sha256:6c7e73c5bc4b6d7d70866616f78d6c9866b4904defad3077c1e2b5c1c89c2ec1"
IR_COMPOSE = Path("/opt/smite/docker-compose.yml")
IR_OVERLAY = Path("/opt/smite/docker-compose.signed-control.yml")
KH_COMPOSE = Path("/opt/smite-node/docker-compose.yml")
STATE = Path("/etc/u-opti/smite/state.env")
GATEWAY = Path("/etc/u-opti/smite/foreign-gateway.env")
KH_ENV = Path("/opt/smite-node/.env")
IR_COMPOSE_SHA = "adc4dfb3031d5f2b5c007241589ed96fe9679ac2df29da62853192c7d716ca5a"
IR_OVERLAY_SHA = "0e7d1d9c10237e216e73ca4d893e675bedd1385826e5fa10f3a311bb1968b3f6"
KH_COMPOSE_SHA = "8339ee07dcc3fe68da65dd8cb993b11d8da20b69b0470c032f8d504b0ea9de4e"
IR_DOMAIN = "ir.kolbe1.ir"
KH_DOMAIN = "kh.kolbe1.ir"
FOREIGN_PATH = re.compile(r"/smite-node/[A-Za-z0-9_-]{16,80}\Z")
SECURITY = {"SMITE_AGENT_AUTH_MODE": "strict",
            "SMITE_NODE_PANEL_AUTH_MODE": "paused",
            "SMITE_ENGINE_INVENTORY_MODE": "managed"}

PANEL_SCRIPT = r'''
import inspect
from app.signed_agent_transport import (
    SignedAgentUnavailable, validate_foreign_gateway_prefix, signed_agent_call,
)
from app.node_client import NodeClient

origin = "https://kh.example.net:443"
control = "https://kh.example.net/smite-node/0123456789abcdef"
assert validate_foreign_gateway_prefix(
    origin=origin, control_url=control
) == origin + "/smite-node/0123456789abcdef"
assert "gateway_control_url" in inspect.signature(signed_agent_call).parameters
source = inspect.getsource(signed_agent_call)
client = inspect.getsource(NodeClient._signed_agent_request)
for needle in ("url = wire_base + target", "target=target",
               "verify=True", "trust_env=False", "follow_redirects=False"):
    assert needle in source
for needle in ('pin["control_url"]', "approved_node(node_id)"):
    assert needle in client
for bad in (
    "http://kh.example.net/smite-node/0123456789abcdef",
    "https://other.example.net/smite-node/0123456789abcdef",
    "https://kh.example.net:444/smite-node/0123456789abcdef",
    "https://kh.example.net/smite-node/x",
    control + "?debug=1",
):
    try:
        validate_foreign_gateway_prefix(origin=origin, control_url=bad)
    except SignedAgentUnavailable:
        pass
    else:
        raise AssertionError("unapproved foreign gateway accepted")
print("PANEL_FOREIGN_TRANSPORT=PASS")
'''


class Hold(Exception):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Hold(reason)


def file_bytes(path: Path, *, private: bool = False, limit: int = 262144) -> bytes:
    try:
        before = path.lstat()
        require(
            stat.S_ISREG(before.st_mode) and before.st_uid == 0
            and before.st_nlink == 1 and not (before.st_mode & 0o022)
            and before.st_size <= limit
            and (not private or stat.S_IMODE(before.st_mode) == 0o600),
            "PRIVATE_FILE_METADATA_UNSAFE",
        )
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            require(
                (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino)
                and opened.st_uid == 0 and opened.st_nlink == 1
                and opened.st_size <= limit,
                "FILE_CHANGED_DURING_READ",
            )
            data = stream.read(limit + 1)
        require(len(data) <= limit, "FILE_TOO_LARGE")
        return data
    except OSError as exc:
        raise Hold("FILE_MISSING") from exc


def env_map(data: bytes) -> dict[str, str]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise Hold("INVALID_ENV_ENCODING") from exc
    parsed: dict[str, str] = {}
    for line in lines:
        if not line or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        require(
            bool(separator) and bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", key))
            and key not in parsed,
            "INVALID_OR_DUPLICATE_ENV",
        )
        parsed[key] = value
    return parsed


def command(argv: list[str], *, timeout: int = 30) -> str:
    # All callers pass immutable, narrowly-scoped read-only argv.
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, check=False,
            timeout=timeout, stdin=subprocess.DEVNULL,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("READ_ONLY_COMMAND_UNAVAILABLE") from exc
    require(result.returncode == 0 and len(result.stdout) <= 1_000_000,
            "READ_ONLY_COMMAND_FAILED")
    return result.stdout.strip()


def checked_digest(path: Path, expected: str) -> None:
    require(hashlib.sha256(file_bytes(path)).hexdigest() == expected,
            "COMPOSE_HASH_DRIFT")


def container(image_name: str, expected_image: str, execute=command) -> None:
    require(
        execute(["docker", "inspect", "-f", "{{.Config.Image}}", image_name])
        == expected_image, "CONTAINER_IMAGE_DRIFT",
    )
    require(
        execute(["docker", "inspect", "-f", "{{.State.Health.Status}}", image_name])
        == "healthy", "CONTAINER_NOT_HEALTHY",
    )


def status_200(url: str, *, resolve: str | None = None, execute=command) -> None:
    cmd = ["curl", "--noproxy", "*", "-4", "--silent", "--show-error",
           "--fail", "--max-time", "15", "-o", "/dev/null",
           "-w", "%{http_code}"]
    if resolve:
        cmd += ["--resolve", resolve]
    cmd.append(url)
    require(execute(cmd, timeout=20) == "200", "HTTPS_STATUS_NOT_OK")


def admit_ir(*, read=file_bytes, execute=command) -> list[str]:
    state = env_map(read(STATE))
    require(state.get("SMITE_ROLE") == "panel-iran"
            and state.get("SMITE_CONNECTION_MODE") == "standard"
            and state.get("SMITE_PANEL_DOMAIN") == IR_DOMAIN
            and state.get("SMITE_MANAGED_VERSION") == "2.0.0-rc.1",
            "IR_MIXED_VERSION_STATE_DRIFT")

    # The original IR Node remains RC.1; the Panel is RC.2.
    for filename, sha in ((IR_COMPOSE, IR_COMPOSE_SHA),
                          (IR_OVERLAY, IR_OVERLAY_SHA)):
        require(hashlib.sha256(read(filename)).hexdigest() == sha,
                "IR_COMPOSE_DRIFT")
    raw = execute(["docker", "compose", "-f", str(IR_COMPOSE),
                   "-f", str(IR_OVERLAY), "config", "--format", "json"])
    try:
        panel = json.loads(raw)["services"]["smite-panel"]
        require(panel["image"] == PANEL_IMAGE and panel["network_mode"] == "host",
                "IR_EFFECTIVE_PANEL_DRIFT")
        for key, value in (
            ("SMITE_NODE_REGISTRATION_MODE", "signed"),
            ("SMITE_PANEL_AGENT_AUTH_MODE", "signed"),
            ("SMITE_NODE_PAIRING_PREVIEW_ENABLED", "true"),
            ("SMITE_SIGNED_NODE_ORIGINS_PATH",
             "/etc/smite-panel/trusted-nodes/approved-origins.json"),
        ):
            require(panel["environment"].get(key) == value,
                    "IR_SIGNED_ENV_DRIFT")
        mounts = {
            m["target"]: (m["source"], m.get("read_only") is True)
            for m in panel["volumes"]
        }
        require(
            mounts.get("/etc/smite-panel/trusted-nodes") ==
            ("/etc/u-opti/smite/panel-trusted-nodes", True),
            "IR_APPROVED_ORIGINS_MOUNT_DRIFT",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise Hold("IR_EFFECTIVE_PANEL_INVALID") from exc

    container("smite-panel", PANEL_IMAGE, execute)
    container("smite-node", IR_NODE_IMAGE, execute)
    require(
        execute(["docker", "exec", "smite-panel",
                 "python3", "-c", PANEL_SCRIPT], timeout=30)
        == "PANEL_FOREIGN_TRANSPORT=PASS",
        "PANEL_FOREIGN_TRANSPORT_UNAVAILABLE",
    )
    status_200("https://" + IR_DOMAIN + "/api/status", execute=execute)
    return [
        "IR_PANEL_RC2_SIGNED=PASS",
        "IR_LOCAL_NODE_RC1=UNCHANGED",
        "IR_TRUST_MOUNT=READ_ONLY",
        "IR_FOREIGN_PATH_HMAC_POLICY=PASS",
        "IR_HTTPS_STATUS=PASS",
    ]


def admit_kh(*, read=file_bytes, execute=command) -> list[str]:
    state = env_map(read(STATE))
    require(state.get("SMITE_ROLE") == "foreign"
            and state.get("SMITE_CONNECTION_MODE") == "standard"
            and state.get("SMITE_PANEL_DOMAIN") == IR_DOMAIN
            and state.get("SMITE_MANAGED_VERSION") == "2.0.0-rc.1",
            "KH_MIXED_VERSION_STATE_DRIFT")
    require(
        hashlib.sha256(read(KH_COMPOSE)).hexdigest() == KH_COMPOSE_SHA,
        "KH_COMPOSE_DRIFT",
    )
    gateway = env_map(read(GATEWAY, private=True, limit=8192))
    node_env = env_map(read(KH_ENV, private=True, limit=65536))
    control_prefix = gateway.get("SMITE_FOREIGN_CONTROL_PATH", "")
    require(bool(FOREIGN_PATH.fullmatch(control_prefix)),
            "KH_GATEWAY_PREFIX_UNSAFE")
    require(
        gateway.get("SMITE_FOREIGN_GATEWAY_DOMAIN") == KH_DOMAIN
        and gateway.get("SMITE_FOREIGN_PANEL_DOMAIN") == IR_DOMAIN
        and gateway.get("SMITE_FOREIGN_GATEWAY_PUBLIC_PORT") == "443"
        and gateway.get("SMITE_FOREIGN_GATEWAY_MODE") == "https-control-path",
        "KH_GATEWAY_METADATA_DRIFT",
    )
    from ipaddress import IPv4Address
    try:
        IPv4Address(gateway["SMITE_FOREIGN_PANEL_SOURCE_IPV4"])
    except (KeyError, ValueError) as exc:
        raise Hold("KH_SOURCE_ALLOWLIST_INVALID") from exc
    require(
        all(node_env.get(k) == v for k, v in SECURITY.items())
        and node_env.get("PANEL_ADDRESS") == IR_DOMAIN + ":443"
        and node_env.get("SMITE_CONTROL_ADDRESS") ==
            "https://" + KH_DOMAIN + control_prefix,
        "KH_PAUSED_CONTROL_DRIFT",
    )
    raw = execute(["docker", "compose", "-f", str(KH_COMPOSE),
                   "config", "--format", "json"])
    try:
        service = json.loads(raw)["services"]["smite-node"]
        require(service["image"] == KH_NODE_IMAGE
                and service["network_mode"] == "host"
                and all(service["environment"].get(k) == v
                        for k, v in SECURITY.items()),
                "KH_EFFECTIVE_SECURITY_DRIFT")
    except (KeyError, TypeError, ValueError) as exc:
        raise Hold("KH_EFFECTIVE_NODE_INVALID") from exc

    container("smite-node", KH_NODE_IMAGE, execute)
    runtime = execute(["docker", "inspect", "-f",
                       "{{range .Config.Env}}{{println .}}{{end}}", "smite-node"])
    require(all(k + "=" + v in runtime.splitlines()
                for k, v in SECURITY.items()),
            "KH_RUNTIME_SECURITY_DRIFT")
    require(execute(["docker", "inspect", "-f", "{{.Image}}", "3xui-01"])
            == SANAEI_IMAGE, "KH_SANAEI_IMAGE_DRIFT")
    require(execute(["docker", "inspect", "-f", "{{.State.Status}}", "3xui-01"])
            == "running", "KH_SANAEI_NOT_RUNNING")
    execute(["nginx", "-t"])
    guard = execute(["python3", "-B",
                     "/usr/local/lib/u-opti/modules/docker-3xui-xhttp-guard.py",
                     "--instance", "01", "--check"])
    require("XHTTP_REVIEW=PASS" in guard and "ROUTES=1" in guard
            and "LEGACY_ROUTE=NO" in guard, "KH_XHTTP_DRIFT")
    listeners = execute(["ss", "-H", "-lnt"])
    found = [row.split()[3] for row in listeners.splitlines()
             if len(row.split()) >= 4 and row.split()[3].endswith(":8888")]
    require(found and all(x in ("127.0.0.1:8888", "[::1]:8888")
                          for x in found), "KH_NODE_NOT_LOOPBACK_ONLY")

    url = "https://" + KH_DOMAIN + control_prefix + "/"
    reply = execute(["curl", "--noproxy", "*", "-4", "--fail",
                     "--silent", "--show-error", "--max-time", "15",
                     "--resolve", KH_DOMAIN + ":443:127.0.0.1", url],
                    timeout=20)
    try:
        require(json.loads(reply) == {"status": "ok", "service": "smite-node"},
                "KH_TLS_GATEWAY_NOT_READY")
    except (ValueError, TypeError) as exc:
        raise Hold("KH_TLS_GATEWAY_INVALID_JSON") from exc
    status_200("https://" + IR_DOMAIN + "/api/status", execute=execute)
    return [
        "KH_NODE_RC2_PAUSED=PASS",
        "KH_GATEWAY_TLS443=PASS",
        "KH_SANAEI_XHTTP=UNCHANGED",
        "KH_TO_IR_HTTPS=PASS",
        "KH_FOREIGN_SIGNED_RUNTIME=NOT_ACTIVATED",
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("IR", "KH"))
    args = parser.parse_args(argv)
    print("===== RC2 FOREIGN SIGNED PAIRING ADMISSION =====")
    print("ROLE=" + args.role)
    try:
        require(os.geteuid() == 0, "ROOT_REQUIRED")
        import socket
        require(socket.gethostname().split(".")[0].lower() == args.role.lower(),
                "WRONG_HOST")
        lines = admit_ir() if args.role == "IR" else admit_kh()
        for line in lines:
            print(line)
    except (Hold, OSError, ValueError, TypeError, KeyError):
        print("RC2_FOREIGN_PAIRING_ADMISSION=HOLD")
        print("LIVE_CHANGES=NONE")
        return 2
    print("RC2_FOREIGN_PAIRING_ADMISSION=PASS_READ_ONLY")
    print("FOREIGN_PAIRING=NOT_ACTIVATED")
    print("LIVE_CHANGES=NONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
