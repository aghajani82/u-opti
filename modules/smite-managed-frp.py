#!/usr/bin/env python3
"""Independent managed FRP v0.71.0 package candidate (OFFLINE ONLY).

This preparer never installs software, starts FRP/Backhaul, restarts Node,
publishes ports or writes to the existing Smite Core. It validates BOTH
official FRP role binaries then stages a private, inert enrollment proposal.
A separate audited host executor is still required and is NOT enabled.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("bh_shared_manifest", HERE / "smite-managed-backhaul.py")
assert _spec and _spec.loader
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)

VERSION = "v0.71.0"
# fatedier/frp v0.71.0 release checksums (NOT latest-channel aliases).
OFFICIAL_TAR_SHA256 = {
    "amd64": "84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716",
    "arm64": "f33c293c275d8fc68c654b6fba8f10b2551d6463d09a9fc9cffb7227eae82266",
}
ELF_MACHINE = {"amd64": 62, "arm64": 183}
ARCHIVE_MAX = 32 * 1024 * 1024
BINARY_MAX = 48 * 1024 * 1024
INSTALL_ROOT = Path("/opt/u-opti/engines/frp/v0.71.0")
BINARY_PATHS = {"frpc": "/usr/local/bin/frpc", "frps": "/usr/local/bin/frps"}
SHA = re.compile(r"^[0-9a-f]{64}$")


class Hold(ValueError):
    pass


def core_preflight(node: Path) -> tuple[bytes, dict]:
    if not node.is_absolute() or node.is_symlink() or not node.is_dir():
        raise Hold("UNSAFE_NODE_DIR")
    text = shared._file(node / ".env", max_size=16384).decode()
    values = {}
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in ("NODE_ROLE", "SMITE_AGENT_AUTH_MODE",
                   "SMITE_NODE_PANEL_AUTH_MODE", "SMITE_ENGINE_INVENTORY_MODE"):
            if key in values:
                raise Hold("DUPLICATE_CORE_ENV")
            values[key] = value
    if (values.get("NODE_ROLE") not in ("iran", "panel-iran", "foreign")
            or values.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or values.get("SMITE_NODE_PANEL_AUTH_MODE") not in ("paused", "signed")
            or values.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"):
        raise Hold("MANAGED_STRICT_CORE_REQUIRED")
    raw = shared._file(node / "docker-compose.yml", max_size=131072)
    compose = raw.decode()
    if (len(re.findall(r"(?m)^  smite-node:\s*$", compose)) != 1
            or not re.search(r"(?m)^    network_mode: host\s*$", compose)
            or not re.search(r"(?m)^\s+- ./config:/etc/smite-node\s*$", compose)
            or re.search(r"(?m)^    ports:\s*$", compose)
            or not re.search(r"(?m)^    image: \S+", compose)):
        raise Hold("UNREVIEWED_NODE_COMPOSE")
    config = node / "config"
    if config.is_symlink() or not config.is_dir():
        raise Hold("MISSING_TRUSTED_NODE_CONFIG")
    manifest = shared._existing_manifest(config)
    # Existing Backhaul MAY coexist. Only partial/untrusted FRP mounts block.
    for target in BINARY_PATHS.values():
        if target in compose:
            raise Hold("FRP_ALREADY_MOUNTED_OR_PARTIAL")
    if "frp" in manifest:
        raise Hold("FRP_ALREADY_ENROLLED")
    if "/usr/local/bin/backhaul" in compose and "backhaul" not in manifest:
        raise Hold("UNENROLLED_BACKHAUL_MOUNT")
    return raw, manifest


def _elf(binary: bytes, *, arch: str) -> None:
    if (len(binary) < 20 or binary[:4] != b"\x7fELF"
            or binary[4] != 2 or binary[5] != 1
            or struct.unpack_from("<H", binary, 18)[0] != ELF_MACHINE[arch]):
        raise Hold("NOT_REVIEWED_ARCH_ELF")


def unpack(archive: Path, *, arch: str, trusted_sha: str) -> dict[str, bytes]:
    if arch not in OFFICIAL_TAR_SHA256 or not SHA.fullmatch(trusted_sha):
        raise Hold("INVALID_ARCH_OR_SHA")
    archive_bytes = shared._file(archive, max_size=ARCHIVE_MAX)
    if hashlib.sha256(archive_bytes).hexdigest() != trusted_sha:
        raise Hold("OFFICIAL_FRP_ARCHIVE_SHA_MISMATCH")
    found = {}
    expected_dir = f"frp_{VERSION.removeprefix('v')}_linux_{arch}"
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive_file:
            members = archive_file.getmembers()
            if len(members) > 150:
                raise Hold("EXCESSIVE_ARCHIVE_MEMBERS")
            for member in members:
                path = Path(member.name)
                if (path.is_absolute() or ".." in path.parts or member.issym()
                        or member.islnk() or member.isdev() or member.isfifo()
                        or not (member.isfile() or member.isdir())):
                    raise Hold("UNSAFE_ARCHIVE_ENTRY")
                if path.parts and path.parts[0] != expected_dir:
                    raise Hold("UNEXPECTED_FRP_ARCHIVE_ROOT")
                if member.isfile() and path.name in BINARY_PATHS:
                    if (len(path.parts) != 2 or path.parts[0] != expected_dir
                            or member.size <= 0 or member.size > BINARY_MAX
                            or path.name in found):
                        raise Hold("AMBIGUOUS_FRP_BINARY")
                    file = archive_file.extractfile(member)
                    if file is None:
                        raise Hold("MISSING_FRP_ARCHIVE_CONTENT")
                    contents = file.read(BINARY_MAX + 1)
                    if len(contents) != member.size:
                        raise Hold("TRUNCATED_FRP_BINARY")
                    _elf(contents, arch=arch)
                    found[path.name] = contents
    except (tarfile.TarError, OSError) as exc:
        raise Hold("UNREADABLE_FRP_ARCHIVE") from exc
    if set(found) != set(BINARY_PATHS):
        raise Hold("BOTH_FRPC_AND_FRPS_REQUIRED")
    return found


def prepare(node: Path, archive: Path, stage_root: Path, *, arch: str,
            allowed_sha: str | None = None) -> Path:
    shared._private_root(stage_root)
    raw, engines = core_preflight(node)
    if arch not in OFFICIAL_TAR_SHA256:
        raise Hold("UNSUPPORTED_ARCH")
    digest = OFFICIAL_TAR_SHA256[arch] if allowed_sha is None else allowed_sha
    binaries = unpack(archive, arch=arch, trusted_sha=digest)
    hashes = {k: hashlib.sha256(v).hexdigest() for k, v in binaries.items()}
    manifest = {
        "schema": 1,
        "engines": {
            **engines,
            "frp": {"sha256": hashes["frpc"], "server_sha256": hashes["frps"]},
        },
    }
    override = (
        "services:\n  smite-node:\n    volumes:\n"
        + "".join(
            f"      - type: bind\n        source: {INSTALL_ROOT / binary}\n"
            f"        target: {target}\n        read_only: true\n"
            for binary, target in BINARY_PATHS.items()
        )
    ).encode()
    proposal = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    summary = (
        f"FRP_VERSION={VERSION}\nFRP_ARCH={arch}\n"
        "CANDIDATE_ONLY=YES\nENGINE_ENROLLED=NO\n"
        "NODE_RESTARTED=NO\nPUBLIC_PORTS_CHANGED=NO\n"
        "BACKHAUL_INSTALL_REQUIRED=NO\n"
        "PORT_OR_TUNNEL_INPUT=NOT_REQUIRED\n"
        f"ARCHIVE_SHA256={digest}\n"
        f"FRPC_SHA256={hashes['frpc']}\nFRPS_SHA256={hashes['frps']}\n"
        f"ORIGINAL_COMPOSE_SHA256={hashlib.sha256(raw).hexdigest()}\n"
    ).encode()
    previous_mask = os.umask(0o077)
    try:
        stage = Path(tempfile.mkdtemp(prefix="frp-plan-", dir=stage_root))
    finally:
        os.umask(previous_mask)
    os.chmod(stage, 0o700)
    try:
        outputs = [
            # Keep the *real official tarball* in the private stage. An
            # attacker cannot forge modified binaries merely by rewriting
            # SHA256SUMS and copying an official archive digest into text.
            ("frp.official.tar.gz", shared._file(archive, max_size=ARCHIVE_MAX), 0o600),
            ("frpc.bin", binaries["frpc"], 0o755),
            ("frps.bin", binaries["frps"], 0o755),
            ("engines.candidate.json", proposal, 0o600),
            ("compose.override.candidate.yml", override, 0o600),
            ("summary.txt", summary, 0o600),
        ]
        for name, data, mode in outputs:
            shared._private_write(stage / name, data, mode)
        checksums = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n"
            for name, data, mode in outputs
        ).encode()
        shared._private_write(stage / "SHA256SUMS", checksums, 0o600)
    except BaseException:
        for file in stage.iterdir():
            file.unlink()
        stage.rmdir()
        raise
    return stage


def verify(stage: Path, *, official_only: bool = True) -> bool:
    try:
        if stage.is_symlink() or not stage.is_dir():
            return False
        required = {"frp.official.tar.gz", "frpc.bin", "frps.bin",
                    "engines.candidate.json",
                    "compose.override.candidate.yml", "summary.txt"}
        entries = {}
        for line in shared._file(stage / "SHA256SUMS", max_size=4096).decode().splitlines():
            digest, sep, filename = line.partition("  ")
            if not sep or filename not in required or filename in entries or not SHA.fullmatch(digest):
                return False
            entries[filename] = digest
            if hashlib.sha256(shared._file(stage / filename, max_size=BINARY_MAX)).hexdigest() != digest:
                return False
        if set(entries) != required:
            return False
        lines = shared._file(stage / "summary.txt", max_size=4096).decode().splitlines()
        if any("=" not in line for line in lines):
            return False
        pairs = [line.split("=", 1) for line in lines]
        if len(pairs) != len({key for key, value in pairs}):
            return False
        info = dict(pairs)
        arch = info.get("FRP_ARCH")
        if (arch not in OFFICIAL_TAR_SHA256 or info.get("FRP_VERSION") != VERSION
                or info.get("CANDIDATE_ONLY") != "YES"
                or info.get("FRPC_SHA256") != entries["frpc.bin"]
                or info.get("FRPS_SHA256") != entries["frps.bin"]):
            return False
        if info.get("ARCHIVE_SHA256") != entries["frp.official.tar.gz"]:
            return False
        if official_only and info.get("ARCHIVE_SHA256") != OFFICIAL_TAR_SHA256[arch]:
            return False
        # Always re-extract and compare BOTH binaries to the archive whose
        # checksum is trusted. This prevents stage-content checksum forgery.
        unpacked = unpack(stage / "frp.official.tar.gz", arch=arch,
                          trusted_sha=info["ARCHIVE_SHA256"])
        for binary in ("frpc", "frps"):
            staged = shared._file(stage / f"{binary}.bin", max_size=BINARY_MAX)
            _elf(staged, arch=arch)
            if staged != unpacked[binary]:
                return False
        expected_overlay = (
            "services:\\n  smite-node:\\n    volumes:\\n"
            + "".join(
                f"      - type: bind\\n        source: {INSTALL_ROOT / name}\\n"
                f"        target: {target}\\n        read_only: true\\n"
                for name, target in BINARY_PATHS.items()
            )
        ).encode().replace(b"\\n", b"\n")
        if shared._file(stage / "compose.override.candidate.yml", max_size=8192) != expected_overlay:
            return False
        manifest = json.loads(shared._file(stage / "engines.candidate.json", max_size=8192))
        return (manifest.get("schema") == 1 and isinstance(manifest.get("engines"), dict)
                and manifest["engines"].get("frp") == {
                    "sha256": entries["frpc.bin"], "server_sha256": entries["frps.bin"]
                })
    except (ValueError, OSError, UnicodeError, KeyError, TypeError):
        return False


def main() -> int:
    p = argparse.ArgumentParser(description="Offline FRP engine candidate, not a host installer")
    p.add_argument("action", choices=("prepare", "verify"))
    p.add_argument("--node-dir", type=Path, default=Path("/opt/smite-node"))
    p.add_argument("--archive", type=Path)
    p.add_argument("--arch", choices=tuple(OFFICIAL_TAR_SHA256))
    p.add_argument("--staging-dir", type=Path, default=Path("/var/lib/u-opti/smite-engine-staging"))
    p.add_argument("--stage", type=Path)
    args = p.parse_args()
    try:
        if args.action == "verify":
            if args.stage is None or not verify(args.stage):
                raise Hold("UNVERIFIED_FRP_CANDIDATE")
            print("FRP_CANDIDATE_VERIFIED=YES")
            print("REAL_HOST_ACTIVATION=HOLD")
            return 0
        if os.geteuid() != 0:
            raise Hold("ROOT_REQUIRED_FOR_OFFLINE_PREPARATION")
        if args.archive is None or args.arch is None:
            raise Hold("ARCHIVE_AND_ARCH_REQUIRED")
        stage = prepare(args.node_dir, args.archive, args.staging_dir, arch=args.arch)
        print(f"FRP_CANDIDATE_PREPARED={stage}")
        print("LIVE_SERVICES_UNCHANGED=YES")
        print("REAL_HOST_ACTIVATION=HOLD")
        return 0
    except (Hold, shared.Hold, OSError, UnicodeError) as exc:
        reason = str(exc)
        print("HOLD: " + (reason if re.fullmatch("[A-Z0-9_]+", reason) else "FRP_ADMISSION_FAILED"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
