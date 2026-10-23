#!/usr/bin/env python3
"""Read-only RC.1 -> RC.2 two-host upgrade admission.

No upgrade, Docker pulls, credential output, pairing, backup or config writes.
PASS only means current RC.1 baseline is consistent; snapshot and release
approval remain separate, mandatory gates.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

RC1_PANEL = (
    "ghcr.io/aghajani82/smite-panel@sha256:"
    "90b5c99af6066e0c94fd1232ecdcd77d24478b65953f4f33fad32d6fbe803f7e"
)
RC1_NODE = (
    "ghcr.io/aghajani82/smite-node@sha256:"
    "9099262bb0d5fc8b737269f3e6dc16831a1d3e8b536b7b95ba131129ed06a7ec"
)
RC2_MANIFEST_SHA = "63e3efbdec955e92deaf0a84c86cc5c8a950f48b4e0d6d301bc7f7c8354eb80b"
RC2_PANEL = (
    "ghcr.io/aghajani82/smite-panel@sha256:"
    "9101898e19631d334b754ba8e956b63ab7dfaee304a8f9b954cf30a185125e8e"
)
RC2_NODE = (
    "ghcr.io/aghajani82/smite-node@sha256:"
    "2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78"
)
CANDIDATE = Path(__file__).with_name("smite-rc2-signed-registry-candidate.json")
DOMAIN = re.compile(r"(?=.{4,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z")
CONTROL_PATH = re.compile(r"/smite-node/[A-Za-z0-9_-]{16,80}\Z")


class Hold(Exception):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Hold(reason)


def _rootpath(root: Path, absolute: str) -> Path:
    return root / absolute.lstrip("/")


def read_regular(root: Path, path: str, *, private: bool = False, limit: int = 65536) -> bytes:
    target = _rootpath(root, path)
    try:
        info = target.lstat()
        require(stat.S_ISREG(info.st_mode), "expected regular managed file missing")
        require(not info.st_mode & 0o022, "managed file is group/world-writable")
        if private:
            require(stat.S_IMODE(info.st_mode) == 0o600, "private managed file mode is not 0600")
        require(info.st_size <= limit, "managed file exceeds safety limit")
        return target.read_bytes()
    except OSError as exc:
        raise Hold("required managed file unavailable") from exc


def parse_env(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise Hold("managed state is not valid UTF-8") from exc
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        require("=" in line, "malformed managed state")
        key, value = line.split("=", 1)
        require(bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", key)), "malformed managed state key")
        require(key not in result, "duplicate managed state key")
        require("\x00" not in value, "invalid managed state value")
        result[key] = value
    return result


def check_candidate(candidate: bytes) -> None:
    require(
        hashlib.sha256(candidate).hexdigest() == RC2_MANIFEST_SHA,
        "reviewed RC.2 candidate SHA256 mismatch",
    )
    try:
        doc = json.loads(candidate)
    except (ValueError, UnicodeError) as exc:
        raise Hold("RC.2 manifest is invalid") from exc
    require(
        doc.get("version") == "2.0.0-rc.2"
        and doc.get("source_commit") == "e6c3ecce81010130ae28e7d1e37ea99b31d70c28"
        and doc.get("publish_ref") == "refs/tags/v2.0.0-rc.2"
        and doc.get("images") == {"panel": RC2_PANEL, "node": RC2_NODE}
        and doc.get("activation_allowed") is False
        and doc.get("release_approved") is False,
        "RC.2 candidate not the nonactivating signed pair",
    )


def safe_listeners(text: str) -> None:
    found_443 = False
    node_binds: list[str] = []
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 4 or tokens[0] != "LISTEN":
            continue
        local = tokens[3]
        if local.endswith(":443"):
            found_443 = True
        if local.endswith(":8888"):
            node_binds.append(local[:-5])
    require(found_443, "HTTPS/443 has no listening socket")
    require(bool(node_binds), "Node TCP/8888 is not listening")
    require(
        all(x in ("127.0.0.1", "[::1]", "::1") for x in node_binds),
        "Node TCP/8888 has a non-loopback listener",
    )


def run_command(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True,
            timeout=15, env={**os.environ, "LC_ALL": "C"},
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise Hold("read-only runtime inspection failed") from exc
    return result.stdout.strip()


def audit(role: str, *, root: Path = Path("/"), execute=run_command) -> list[str]:
    require(role in ("IR", "KH"), "unsupported server role")
    candidate = CANDIDATE.read_bytes()
    check_candidate(candidate)

    state = parse_env(read_regular(root, "/etc/u-opti/smite/state.env"))
    require(state.get("SMITE_ROLE") == ("panel-iran" if role == "IR" else "foreign"),
            "role mismatch")
    require(state.get("SMITE_CONNECTION_MODE") == "standard", "Standard mode required")
    require(state.get("SMITE_MANAGED_VERSION") == "2.0.0-rc.1",
            "baseline must be the exact RC.1 install")
    require(bool(DOMAIN.fullmatch(state.get("SMITE_PANEL_DOMAIN", ""))),
            "Panel domain is not a valid managed domain")
    execute(["nginx", "-t"])
    safe_listeners(execute(["ss", "-H", "-lnt"]))

    def verify_container(name: str, image: str) -> None:
        require(
            execute(["docker", "inspect", "-f", "{{.Config.Image}}", name]) == image,
            "running " + name + " image differs from reviewed RC.1 digest",
        )
        require(
            execute(["docker", "inspect", "-f", "{{.State.Health.Status}}", name]) == "healthy",
            name + " must be healthy before any upgrade",
        )

    verify_container("smite-node", RC1_NODE)
    facts = ["BASELINE_RC1=VERIFIED", "RC2_CANDIDATE=NONACTIVATING"]

    if role == "IR":
        verify_container("smite-panel", RC1_PANEL)
        panel = parse_env(read_regular(root, "/opt/smite/.env", private=True))
        require(
            panel.get("SMITE_NODE_REGISTRATION_MODE") == "signed"
            and panel.get("SMITE_PANEL_AGENT_AUTH_MODE") == "signed"
            and panel.get("SMITE_NODE_PAIRING_PREVIEW_ENABLED") == "true",
            "IR Panel not in signed enrollment mode",
        )
        read_regular(root, "/opt/smite/panel/data/smite.db", limit=500_000_000)
        facts.append("IR_PANEL_SIGNED_BASELINE=VERIFIED")
    else:
        node = parse_env(read_regular(root, "/opt/smite-node/.env", private=True))
        require(
            node.get("SMITE_NODE_PANEL_AUTH_MODE") == "paused"
            and node.get("SMITE_AGENT_AUTH_MODE") == "strict"
            and node.get("SMITE_ENGINE_INVENTORY_MODE") == "managed",
            "KH Node must still be paused/strict/managed",
        )
        gateway = parse_env(
            read_regular(root, "/etc/u-opti/smite/foreign-gateway.env", private=True)
        )
        domain = gateway.get("SMITE_FOREIGN_GATEWAY_DOMAIN", "")
        path = gateway.get("SMITE_FOREIGN_CONTROL_PATH", "")
        require(bool(DOMAIN.fullmatch(domain)), "KH Gateway hostname invalid")
        require(bool(CONTROL_PATH.fullmatch(path)), "KH control prefix invalid")
        require(
            gateway.get("SMITE_FOREIGN_PANEL_DOMAIN") == state["SMITE_PANEL_DOMAIN"]
            and gateway.get("SMITE_FOREIGN_GATEWAY_PUBLIC_PORT") == "443"
            and gateway.get("SMITE_FOREIGN_GATEWAY_MODE") == "https-control-path"
            and node.get("SMITE_CONTROL_ADDRESS") == "https://" + domain + path
            and node.get("PANEL_ADDRESS") == state["SMITE_PANEL_DOMAIN"] + ":443",
            "KH control metadata mismatch",
        )
        try:
            require(
                ipaddress.ip_address(gateway.get("SMITE_FOREIGN_PANEL_SOURCE_IPV4", "")).version == 4,
                "KH panel-source IPv4 invalid",
            )
        except ValueError as exc:
            raise Hold("KH panel-source IPv4 invalid") from exc
        require(
            execute(["docker", "inspect", "-f", "{{.State.Status}}", "3xui-01"]) == "running",
            "KH Sanaei container is not running",
        )
        guard = _rootpath(root, "/usr/local/lib/u-opti/modules/docker-3xui-xhttp-guard.py")
        require(guard.is_file() and not guard.is_symlink(), "KH XHTTP guard is unavailable")
        output = execute(["python3", "-B", str(guard), "--instance", "01", "--check"])
        require(
            "XHTTP_REVIEW=PASS" in output and "LEGACY_ROUTE=NO" in output,
            "KH Sanaei XHTTP baseline is not clean",
        )
        facts.append("KH_GATEWAY_XHTTP_BASELINE=VERIFIED")

    facts.extend((
        "SNAPSHOT_AND_ROLLBACK=NOT_VERIFIED",
        "INDEPENDENT_ON_HOST_COSIGN=NOT_VERIFIED",
        "LIVE_UPGRADE_AUTHORIZED=NO",
    ))
    return facts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=["IR", "KH"])
    args = parser.parse_args()
    print("RC2_READ_ONLY_PREFLIGHT_ROLE=" + args.role)
    try:
        require(os.geteuid() == 0, "root required for read-only audit")
        for item in audit(args.role):
            print(item)
    except (Hold, OSError, ValueError) as exc:
        # No sensitive file data, source paths or command stdout are emitted.
        print("RC2_PREFLIGHT=HOLD")
        print("REASON=" + str(exc))
        return 2
    print("RC2_PREFLIGHT=PASS_BASELINE_ONLY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
