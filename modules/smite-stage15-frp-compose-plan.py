#!/usr/bin/env python3
"""Stage15 signed FRP v0.71.0 Compose admission — READ ONLY, never an installer.

The installed Stage15 Node includes legacy frpc/frps v0.65.0. This review
requires an independently SHA256-verified official v0.71.0 dual-binary stage,
then compares effective Docker Compose *before* and *after* a read-only bind
overlay. Only two binary mounts may differ; signed auth, replay, identity,
Nginx, network and all other service configuration must remain identical.

The effective overlay is NOT written, applied or mounted. Not production
authorization. A separate audited host executor + signed restart/replay proof
is required before enabling FRP/WSS or opening a tunnel.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent


class Hold(RuntimeError):
    pass


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    if spec is None or spec.loader is None:
        raise Hold("REVIEWED_MODULE_MISSING")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


frp = load("frp_stage15_candidate", "smite-managed-frp.py")
control = load("frp_stage15_signed_gate", "smite-managed-frp-control.py")
EXPECTED_MOUNTS = {
    "/usr/local/bin/frpc": str(frp.INSTALL_ROOT / "frpc"),
    "/usr/local/bin/frps": str(frp.INSTALL_ROOT / "frps"),
}
# The existing official candidate is independently attested by frp.verify().
# Its Compose candidate has implicit bind.create_host_path=true. Never apply
# that permissive mount: harden the prospective in-memory proposal instead.
STAGED_OVERLAY = (
    "services:\n"
    "  smite-node:\n"
    "    volumes:\n"
    + "".join(
        "      - type: bind\n"
        f"        source: {src}\n"
        f"        target: {dst}\n"
        "        read_only: true\n"
        for dst, src in EXPECTED_MOUNTS.items()
    )
)
OVERLAY = STAGED_OVERLAY.replace(
    "        read_only: true\n",
    "        read_only: true\n"
    "        bind:\n"
    "          create_host_path: false\n",
)



def compose_read(argv: list[str], *, stdin: str | None = None) -> str:
    """Compose config only: no up, restart, pull, port publication or writes."""
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise Hold("REMOTE_DOCKER_CONTEXT_UNREVIEWED")
    if argv[:2] != ["docker", "compose"] or "config" not in argv:
        raise Hold("NON_READ_ONLY_COMPOSE_ACTION")
    try:
        proc = subprocess.run(argv, input=stdin, capture_output=True,
                              text=True, timeout=40, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("DOCKER_COMPOSE_CONFIG_FAILED") from exc
    if proc.returncode or len(proc.stdout) > 524288:
        raise Hold("DOCKER_COMPOSE_CONFIG_FAILED")
    return proc.stdout


def validate_config(before: dict, after: dict) -> dict[str, str]:
    """Exact full-config comparison allowing only two new bind mounts."""
    try:
        old_service = before["services"]["smite-node"]
        new_service = after["services"]["smite-node"]
        old_volumes, new_volumes = old_service["volumes"], new_service["volumes"]
        if not isinstance(old_volumes, list) or not isinstance(new_volumes, list):
            raise Hold("UNREVIEWED_SIGNED_COMPOSE_VOLUMES")
        if (old_service.get("image") != "smite-node:stage15-local"
                or old_service.get("network_mode") != "host"
                or old_service.get("ports")
                or old_service.get("privileged")
                or old_service.get("command") != [
                    "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"
                ]):
            raise Hold("STAGE15_SIGNED_BASE_COMPOSE_DRIFT")
        env = old_service.get("environment")
        if not isinstance(env, dict) or any(
            env.get(k) != v for k, v in {
                "SMITE_NODE_PANEL_AUTH_MODE": "signed",
                "SMITE_AGENT_AUTH_MODE": "strict",
                "SMITE_ENGINE_INVENTORY_MODE": "managed",
            }.items()
        ):
            raise Hold("STAGE15_SIGNED_BASE_COMPOSE_DRIFT")
        if not re.fullmatch(r"[a-z0-9.-]+:443", env.get("PANEL_ADDRESS", "")):
            raise Hold("STAGE15_SIGNED_BASE_COMPOSE_DRIFT")
        if env.get("SMITE_FRP_STANDARD_WSS") == "1":
            raise Hold("WSS_PREACTIVATED_WITHOUT_PROOF")
        baseline_targets = [v.get("target") for v in old_volumes]
        if len(set(baseline_targets)) != len(baseline_targets):
            raise Hold("DUPLICATE_BASE_MOUNT")
        if any(target in baseline_targets for target in EXPECTED_MOUNTS):
            raise Hold("FRP_BINARY_MOUNT_ALREADY_PRESENT")
        expected = {}
        for mount in new_volumes:
            if not isinstance(mount, dict) or "target" not in mount:
                raise Hold("UNREVIEWED_PROSPECTIVE_MOUNT")
            target = mount["target"]
            if target in EXPECTED_MOUNTS:
                if target in expected:
                    raise Hold("DUPLICATE_FRP_PROSPECTIVE_MOUNT")
                if (mount.get("type") != "bind"
                        or mount.get("source") != EXPECTED_MOUNTS[target]
                        or mount.get("read_only") is not True
                        or mount.get("bind", {}).get("create_host_path") is not False):
                    raise Hold("UNTRUSTED_FRP_BINARY_MOUNT")
                expected[target] = mount
        if set(expected) != set(EXPECTED_MOUNTS):
            raise Hold("INCOMPLETE_DUAL_BINARY_MOUNT")
        other = [v for v in new_volumes if v["target"] not in EXPECTED_MOUNTS]
        if other != old_volumes:
            raise Hold("EXISTING_SIGNED_MOUNTS_CHANGED")
        normalized = copy.deepcopy(after)
        normalized["services"]["smite-node"]["volumes"] = copy.deepcopy(old_volumes)
        if normalized != before:
            raise Hold("SIGNED_COMPOSE_UNRELATED_DRIFT")
        return {
            "FRP_MOUNTS": "TWO_READ_ONLY_BINDS_ONLY",
            "SIGNED_COMPOSE": "UNCHANGED_EXCEPT_FRP_BINARIES",
        }
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        if isinstance(exc, Hold):
            raise
        raise Hold("COMPOSE_DOCUMENT_MALFORMED") from exc


def review(
    node: Path, stage: Path, *,
    official_verify=None,
    signed_readiness=None,
    run=None,
) -> dict[str, str]:
    official_verify = frp.verify if official_verify is None else official_verify
    signed_readiness = control.stage15_readiness if signed_readiness is None else signed_readiness
    run = compose_read if run is None else run
    if (not node.is_absolute() or node.is_symlink() or not node.is_dir()
            or not stage.is_absolute() or stage.is_symlink() or not stage.is_dir()):
        raise Hold("UNTRUSTED_STAGE15_REVIEW_PATH")
    if not official_verify(stage):
        raise Hold("OFFICIAL_FRP_071_PAIR_NOT_VERIFIED")
    signed = signed_readiness(node)
    if (signed.get("STAGE15_IMAGE") != "PINNED_TEST_ID_MATCH"
            or signed.get("SIGNED_NODE") != "HEALTHY_LOCAL_RUNTIME_ONLY"
            or signed.get("FRP_0_71_MANAGED_MATCH") != "NO"
            or signed.get("HOST_FRP_INSTALL") !=
                "HOLD_VERSION_AND_SIGNED_WSS_ADMISSION"):
        raise Hold("STAGE15_SIGNED_RUNTIME_NOT_ADMITTED")
    # FRP's official stage verifier checks archive, dual ELF binaries,
    # checksums and exactly the expected offline proposal.
    stage_overlay = frp.shared._file(stage / "compose.override.candidate.yml",
                                     max_size=8192)
    if stage_overlay != STAGED_OVERLAY.encode():
        raise Hold("OFFICIAL_FRP_COMPOSE_CANDIDATE_DRIFT")
    cmd = ["docker", "compose", "-f", str(node / "docker-compose.yml"),
           "-f", str(node / "docker-compose.security-candidate.yml")]
    try:
        before = json.loads(run(cmd + ["config", "--format", "json"]))
        after = json.loads(run(cmd + ["-f", "-", "config", "--format", "json"],
                               stdin=OVERLAY))
    except (ValueError, UnicodeError, TypeError, json.JSONDecodeError) as exc:
        raise Hold("DOCKER_COMPOSE_JSON_INVALID") from exc
    result = validate_config(before, after)
    return {
        "STAGE15_FRP_COMPOSE_PLAN": "PASS_READ_ONLY",
        "ROLE": signed.get("ROLE", "UNKNOWN"),
        "OFFICIAL_FRP_VERSION": "v0.71.0",
        "LEGACY_IMAGE_FRP": "v0.65.0_NOT_SELECTED",
        **result,
        "CANDIDATE_OVERLAY_SHA256": hashlib.sha256(OVERLAY.encode()).hexdigest(),
        "SIGNED_HMAC_REPLAY_PROOF": "NOT_QUERIED",
        "FRP_HOST_TRANSACTION": "NOT_IMPLEMENTED",
        "FRP_WSS_ACTIVATION": "NOT_PERFORMED",
        "PUBLIC_PORTS_CHANGED": "NO",
        "LIVE_CHANGES": "NONE",
        "APPLY_ALLOWED": "NO",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan",))
    parser.add_argument("--node-dir", type=Path, default=Path("/opt/smite-node"))
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    try:
        for key, val in review(args.node_dir, args.stage).items():
            print(f"{key}={val}")
        return 0
    except (Hold, frp.Hold, frp.shared.Hold, control.Hold,
            OSError, ValueError, UnicodeError, subprocess.SubprocessError) as exc:
        reason = str(exc)
        safe = reason if re.fullmatch(r"[A-Z0-9_]{1,100}", reason) else "STAGE15_FRP_PLAN_UNTRUSTED"
        print("HOLD: " + safe, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
