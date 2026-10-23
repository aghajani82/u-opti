#!/usr/bin/env python3
"""Read-only, fail-closed IR Panel RC.1 -> RC.2 Compose review.

Checks the *effective* combined Panel Compose and signed overlay, but cannot
deploy, download, edit a file, change managed version, or authorize a rollout.
It never prints environment contents or credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

PANEL_COMPOSE = Path("/opt/smite/docker-compose.yml")
SIGNED_OVERLAY = Path("/opt/smite/docker-compose.signed-control.yml")
RC1_PANEL = (
    "ghcr.io/aghajani82/smite-panel@sha256:"
    "90b5c99af6066e0c94fd1232ecdcd77d24478b65953f4f33fad32d6fbe803f7e"
)
RC1_NODE = (
    "ghcr.io/aghajani82/smite-node@sha256:"
    "9099262bb0d5fc8b737269f3e6dc16831a1d3e8b536b7b95ba131129ed06a7ec"
)
RC2_PANEL = (
    "ghcr.io/aghajani82/smite-panel@sha256:"
    "9101898e19631d334b754ba8e956b63ab7dfaee304a8f9b954cf30a185125e8e"
)
KNOWN_HASHES = {
    "panel": "a8a2ae3faa44ed9b2bf7818df44c3c81936009d5b72598d14ab2336221f48f83",
    "overlay": "0e7d1d9c10237e216e73ca4d893e675bedd1385826e5fa10f3a311bb1968b3f6",
}
REQUIRED_MOUNTS = {
    "/app/data": ("/opt/smite/panel/data", False),
    "/app/certs": ("/opt/smite/panel/certs", False),
    "/app/config/.env": ("/opt/smite/.env", True),
    "/app/config/docker-compose.yml": ("/opt/smite/docker-compose.yml", True),
    "/etc/smite-panel/trusted-nodes": (
        "/etc/u-opti/smite/panel-trusted-nodes", True,
    ),
}
ENV_REQUIRED = {
    "SMITE_NODE_REGISTRATION_MODE": "signed",
    "SMITE_PANEL_AGENT_AUTH_MODE": "signed",
    "SMITE_NODE_PAIRING_PREVIEW_ENABLED": "true",
    "SMITE_SIGNED_NODE_ORIGINS_PATH":
        "/etc/smite-panel/trusted-nodes/approved-origins.json",
}


class ReviewHold(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewHold(message)


def validate_combined_compose(doc: object) -> None:
    require(isinstance(doc, dict), "effective Compose JSON invalid")
    services = doc.get("services")
    require(isinstance(services, dict), "Compose services missing")
    panel = services.get("smite-panel")
    require(isinstance(panel, dict), "Panel service missing")
    require(panel.get("image") == RC1_PANEL, "Panel image differs from exact RC.1 baseline")
    require(panel.get("container_name") == "smite-panel", "Panel service renamed")
    require(panel.get("network_mode") == "host", "Panel network mode changed")
    require(panel.get("restart") == "unless-stopped", "Panel restart policy changed")
    require(isinstance(panel.get("healthcheck"), dict), "Panel healthcheck missing")
    environment = panel.get("environment")
    require(isinstance(environment, dict), "Resolved Panel environment unavailable")
    for key, required in ENV_REQUIRED.items():
        require(environment.get(key) == required, "Signed Panel configuration mismatch")

    volumes = panel.get("volumes")
    require(isinstance(volumes, list), "Panel mounts missing")
    seen: dict[str, tuple[str, bool]] = {}
    for mount in volumes:
        require(isinstance(mount, dict), "Unreviewed Panel volume syntax")
        target = mount.get("target")
        require(isinstance(target, str), "Panel mount target missing")
        require(target not in seen, "Duplicate Panel mount destination")
        seen[target] = (mount.get("source"), mount.get("read_only") is True)
    for target, (source, read_only) in REQUIRED_MOUNTS.items():
        require(seen.get(target) == (source, read_only),
                "Critical Panel bind/RO security mount changed")

    require(
        all(
            service.get("image") != RC2_PANEL
            for service in services.values()
            if isinstance(service, dict)
        ),
        "RC.2 Panel unexpectedly present before cutover",
    )


def plan_exact_panel_image_replacement(current: bytes) -> bytes:
    """Return proposed Compose bytes in memory; never write live files.

    The only proposed change is the one reviewed Panel immutable image line.
    Exact baseline hash and a single, whole-line image occurrence are required
    so a second service, comment, templated image or local security setting
    cannot be silently changed.
    """
    require(
        hashlib.sha256(current).hexdigest() == KNOWN_HASHES["panel"],
        "Panel Compose does not match approved immutable baseline",
    )
    old = ("    image: " + RC1_PANEL + "\n").encode("ascii")
    new = ("    image: " + RC2_PANEL + "\n").encode("ascii")
    require(current.count(old) == 1, "Expected Panel image line not unique")
    proposed = current.replace(old, new, 1)
    require(proposed != current, "Image change missing")
    require(proposed.replace(new, old, 1) == current,
            "Proposed change includes more than Panel immutable image")
    return proposed


def run_readonly(command: list[str]) -> str:
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=40, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReviewHold("Read-only Docker inspection unavailable") from exc
    require(done.returncode == 0, "Read-only Docker inspection failed")
    require(len(done.stdout) <= 1_500_000, "Docker inspection output too large")
    return done.stdout.strip()


def review(*, compose: Path = PANEL_COMPOSE,
           overlay: Path = SIGNED_OVERLAY, execute=run_readonly) -> list[str]:
    for label, path in (("panel", compose), ("overlay", overlay)):
        try:
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode), "Required Compose file not regular")
            require(info.st_size < 262_144, "Required Compose file too large")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ReviewHold("Required Compose file unavailable") from exc
        require(digest == KNOWN_HASHES[label], "Reviewed Compose SHA256 changed")

    # Compute an exact, reversible single-image patch in memory only.
    baseline = compose.read_bytes()
    proposed = plan_exact_panel_image_replacement(baseline)
    proposed_hash = hashlib.sha256(proposed).hexdigest()

    raw = execute([
        "docker", "compose",
        "-f", str(compose),
        "-f", str(overlay),
        "config", "--format", "json",
    ])
    try:
        config = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ReviewHold("Effective Compose JSON invalid") from exc
    validate_combined_compose(config)

    for service, baseline in (("smite-panel", RC1_PANEL), ("smite-node", RC1_NODE)):
        current_image = execute([
            "docker", "inspect", "-f", "{{.Config.Image}}", service,
        ])
        require(current_image == baseline, "Running RC.1 image mismatch")
        health = execute([
            "docker", "inspect", "-f", "{{.State.Health.Status}}", service,
        ])
        require(health == "healthy", "Running RC.1 container not healthy")

    return [
        "IR_PANEL_RC1_RUNTIME=VERIFIED",
        "IR_LOCAL_SIGNED_NODE_RC1_RUNTIME=VERIFIED",
        "IR_SIGNED_COMPOSE_EFFECTIVE=VERIFIED",
        "IR_PANEL_DATABASE_AND_TRUST_MOUNTS=VERIFIED",
        "RC2_PANEL_CANDIDATE=" + RC2_PANEL,
        "IR_PANEL_ORIGINAL_COMPOSE_SHA256=" + KNOWN_HASHES["panel"],
        "IR_PANEL_PROPOSED_COMPOSE_SHA256=" + proposed_hash,
        "IR_PANEL_PROPOSED_DIFF=EXACT_PANEL_IMAGE_LINE_ONLY",
        "IR_ROLLBACK_IMAGE=" + RC1_PANEL,
        "THIS_IS_ONLY_A_READ_ONLY_MIGRATION_PLAN=YES",
        "RC2_DEPLOYMENT_AUTHORIZED=NO",
        "LIVE_CHANGES=NONE",
    ]


def main() -> int:
    print("===== IR RC2 PANEL-ONLY COMPOSE REVIEW =====")
    try:
        require(os.geteuid() == 0, "Root required for read-only inspection")
        for line in review():
            print(line)
    except (ReviewHold, OSError, ValueError, TypeError):
        # Never print the Docker Compose JSON, env values, identities or secrets.
        print("IR_RC2_PANEL_COMPOSE_REVIEW=HOLD")
        print("LIVE_CHANGES=NONE")
        return 2
    print("IR_RC2_PANEL_COMPOSE_REVIEW=PASS_PLAN_ONLY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
