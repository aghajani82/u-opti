#!/usr/bin/env python3
"""Managed Backhaul package preparation for clean Smite Core (OFFLINE).

This stage NEVER invokes Docker or modifies a live Compose, engine registry,
container, Nginx or tunnel. It creates private, independently verifiable
installation candidates after checking the official pinned Backhaul archive.
Actual activation/rollback is a separate gated milestone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import tempfile

VERSION = "v0.7.2"
OFFICIAL_TAR_SHA256 = {
    "amd64": "57bf95c2eabeddb1152d2e94ac42f4310883ce0fb909ee2a57bd53503b2dabbc",
    "arm64": "9a424c97ff16fc3f682e8314c418790d2b5bf3136e008edbb6cd402ea00999f6",
}
ENGINE_NAMES = {"backhaul", "frp", "gost", "rathole", "chisel"}
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_BINARY_BYTES = 48 * 1024 * 1024
INSTALL_BINARY = Path("/opt/u-opti/engines/backhaul/v0.7.2/backhaul")
CONTAINER_BINARY = "/usr/local/bin/backhaul"


class Hold(ValueError):
    """Unsafe input or an unverified step: do not proceed."""


def _file(path: Path, *, max_size: int = 131072) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise Hold("Unsafe or missing file")
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > max_size:
        raise Hold("Unsafe file type or size")
    return path.read_bytes()


def _private_root(root: Path) -> None:
    if not root.is_absolute() or root == Path("/") or root.is_symlink():
        raise Hold("Unsafe private staging directory")
    if not root.exists():
        raise Hold("Create private staging directory (0700) before preparation")
    st = root.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) & 0o077):
        raise Hold("Staging directory must be owned by caller and 0700")


def _existing_manifest(config: Path) -> dict:
    state = config / "engine-state"
    if state.is_symlink():
        raise Hold("Unsafe engine-state directory")
    if state.exists():
        st = state.lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) & 0o077):
            raise Hold("Existing engine-state directory is not private")
    file = state / "engines.json"
    if not file.exists() and not file.is_symlink():
        return {}
    st = file.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
            or stat.S_IMODE(st.st_mode) & 0o177 or st.st_nlink != 1):
        raise Hold("Existing inventory is not trusted")
    try:
        body = json.loads(_file(file, max_size=8192))
    except (ValueError, UnicodeError, OSError) as exc:
        raise Hold("Existing engine manifest is invalid") from exc
    if (not isinstance(body, dict) or set(body) != {"schema", "engines"}
            or body["schema"] != 1 or not isinstance(body["engines"], dict)
            or not set(body["engines"]).issubset(ENGINE_NAMES)):
        raise Hold("Unrecognized engine manifest schema")
    for name, record in body["engines"].items():
        if (not isinstance(record, dict) or not isinstance(record.get("sha256"), str)
                or SHA_RE.fullmatch(record["sha256"]) is None):
            raise Hold("Invalid existing engine SHA")
        fields = set(record)
        if name == "frp":
            # A server-capable FRP release must pin frps as well as frpc.
            # Old client-only metadata may be read for safe migration but
            # cannot claim readiness in the managed Node runtime.
            if fields not in ({"sha256"}, {"sha256", "server_sha256"}):
                raise Hold("Unknown FRP registry fields")
            if "server_sha256" in record and (
                    not isinstance(record["server_sha256"], str)
                    or SHA_RE.fullmatch(record["server_sha256"]) is None):
                raise Hold("Invalid FRP server SHA")
        elif fields != {"sha256"}:
            raise Hold("Unknown other engine registry fields")
    return body["engines"]


def _core_preflight(node_dir: Path) -> tuple[bytes, dict]:
    if not node_dir.is_absolute() or node_dir.is_symlink():
        raise Hold("Unsafe Node directory")
    env = _file(node_dir / ".env", max_size=16384).decode("utf-8")
    values = dict(line.split("=", 1) for line in env.splitlines()
                  if "=" in line and not line.lstrip().startswith("#"))
    if (values.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
            or values.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or values.get("SMITE_NODE_PANEL_AUTH_MODE") not in {"paused", "signed"}):
        raise Hold("Only managed clean-RC Node with strict Agent is supported")
    compose = _file(node_dir / "docker-compose.yml")
    # Strict expected Compose *shape*, not an attempt to parse generic YAML.
    text = compose.decode("utf-8")
    if (len(re.findall(r"(?m)^  smite-node:\s*$", text)) != 1
            or not re.search(r"(?m)^    network_mode: host\s*$", text)
            or not re.search(r"(?m)^\s+- ./config:/etc/smite-node\s*$", text)
            or not re.search(r"(?m)^    image: \S+", text)
            or CONTAINER_BINARY in text
            or re.search(r"(?m)^    ports:\s*$", text)):
        raise Hold("Unrecognized Node Compose; refusing to patch or override")
    config = node_dir / "config"
    if config.is_symlink() or not config.is_dir():
        raise Hold("Missing or unsafe Node config mount")
    engines = _existing_manifest(config)
    # Never enroll Backhaul on top of a partially installed or untrusted FRP.
    # FRP is OPTIONAL: zero FRP mounts and no registry entry are fine.
    # When FRP is already enrolled, its two independently pinned binaries
    # must still match the existing read-only mounts and registry, otherwise
    # touching shared Compose would turn a broken baseline into a fake pass.
    frp_targets = {"frpc": "/usr/local/bin/frpc", "frps": "/usr/local/bin/frps"}
    frp_mount_lines = {
        name: [line.strip() for line in text.splitlines()
               if line.strip().startswith("- ") and target in line]
        for name, target in frp_targets.items()
    }
    frp_record = engines.get("frp")
    if frp_record is None:
        if any(frp_mount_lines.values()):
            raise Hold("Unenrolled FRP binary mount: repair before Backhaul")
    else:
        if set(frp_record) != {"sha256", "server_sha256"}:
            raise Hold("Existing FRP requires both verified role binaries")
        for name, target in frp_targets.items():
            lines = frp_mount_lines[name]
            if len(lines) != 1 or not lines[0].endswith(f":{target}:ro"):
                raise Hold("Incomplete or writable FRP mount blocks Backhaul")
            source = lines[0][2:].removesuffix(f":{target}:ro")
            binary = Path(source)
            if (not binary.is_absolute() or binary.is_symlink()
                    or not binary.is_file()):
                raise Hold("Existing FRP binary missing or unsafe")
            meta = binary.lstat()
            if (not stat.S_ISREG(meta.st_mode)
                    or meta.st_uid != os.geteuid() or meta.st_nlink != 1
                    or stat.S_IMODE(meta.st_mode) & 0o022
                    or not (stat.S_IMODE(meta.st_mode) & 0o111)
                    or meta.st_size > MAX_BINARY_BYTES):
                raise Hold("Existing FRP binary permissions untrusted")
            expected = (frp_record["sha256"] if name == "frpc"
                        else frp_record["server_sha256"])
            if hashlib.sha256(_file(binary, max_size=MAX_BINARY_BYTES)).hexdigest() != expected:
                raise Hold("Existing FRP binary digest mismatch")
    return compose, engines


def _verified_binary(archive: Path, trusted_sha: str) -> bytes:
    if SHA_RE.fullmatch(trusted_sha) is None:
        raise Hold("Invalid trusted archive digest")
    if hashlib.sha256(_file(archive, max_size=MAX_ARCHIVE_BYTES)).hexdigest() != trusted_sha:
        raise Hold("Backhaul official archive digest mismatch")
    try:
        with tarfile.open(archive, "r:gz") as tf:
            selected = []
            for member in tf.getmembers():
                path = Path(member.name)
                if (path.is_absolute() or ".." in path.parts or member.issym()
                        or member.islnk() or member.isdev() or member.isfifo()):
                    raise Hold("Unsafe Backhaul archive entry")
                if not member.isfile() and not member.isdir():
                    raise Hold("Unexpected Backhaul archive entry type")
                if member.isfile() and path.name == "backhaul":
                    if member.size <= 0 or member.size > MAX_BINARY_BYTES:
                        raise Hold("Backhaul binary size outside limits")
                    selected.append(member)
            if len(selected) != 1:
                raise Hold("Expected exactly one Backhaul binary")
            stream = tf.extractfile(selected[0])
            if stream is None:
                raise Hold("Cannot read Backhaul binary")
            data = stream.read(MAX_BINARY_BYTES + 1)
            if len(data) != selected[0].size or not data.startswith(b"\x7fELF"):
                raise Hold("Backhaul artifact is not an expected Linux executable")
            return data
    except (tarfile.TarError, OSError) as exc:
        raise Hold("Unreadable official Backhaul archive") from exc


def _private_write(path: Path, data: bytes, mode: int) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as output:
        # umask=077 intentionally protects staging creation, but executable
        # artifact needs exact 0755 for the later read-only bind mount.
        os.fchmod(output.fileno(), mode)
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def prepare(node_dir: Path, archive: Path, stage_root: Path,
            *, arch: str, allowed_sha: str | None = None) -> Path:
    """Prepare verifiable proposals; intentionally NEVER call Docker."""
    _private_root(stage_root)
    if arch not in OFFICIAL_TAR_SHA256:
        raise Hold("Unsupported Backhaul architecture")
    compose, engines = _core_preflight(node_dir)
    if "backhaul" in engines:
        raise Hold("Backhaul already enrolled: use a separate repair workflow")
    digest = allowed_sha if allowed_sha is not None else OFFICIAL_TAR_SHA256[arch]
    binary = _verified_binary(archive, digest)
    binary_sha = hashlib.sha256(binary).hexdigest()
    manifest = {"schema": 1, "engines": {**engines, "backhaul": {"sha256": binary_sha}}}
    overlay = (
        "services:\n"
        "  smite-node:\n"
        "    volumes:\n"
        "      - type: bind\n"
        f"        source: {INSTALL_BINARY}\n"
        f"        target: {CONTAINER_BINARY}\n"
        "        read_only: true\n"
    ).encode()
    proposal = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    summary = (
        f"BACKHAUL_VERSION={VERSION}\n"
        f"BACKHAUL_ARCH={arch}\n"
        "CANDIDATE_ONLY=YES\n"
        "NODE_RESTARTED=NO\n"
        "ENGINE_ENROLLED=NO\n"
        f"FRP_INSTALLED={'YES' if 'frp' in engines else 'NO'}\n"
        "PUBLIC_PORTS_CHANGED=NO\n"
        f"ARCHIVE_SHA256={digest}\n"
        f"BACKHAUL_BINARY_SHA256={binary_sha}\n"
        f"ORIGINAL_COMPOSE_SHA256={hashlib.sha256(compose).hexdigest()}\n"
    ).encode()
    old_umask = os.umask(0o077)
    try:
        stage = Path(tempfile.mkdtemp(prefix="backhaul-plan-", dir=stage_root))
    finally:
        os.umask(old_umask)
    os.chmod(stage, 0o700)
    try:
        outputs = [
            # Retain the reviewed upstream tarball: local SHA256SUMS alone
            # could be rewritten with a tampered binary in the staging dir.
            ("backhaul.official.tar.gz", _file(archive, max_size=MAX_ARCHIVE_BYTES), 0o600),
            ("backhaul.bin", binary, 0o755),
            ("engines.candidate.json", proposal, 0o600),
            ("compose.override.candidate.yml", overlay, 0o600),
            ("summary.txt", summary, 0o600),
        ]
        for name, contents, mode in outputs:
            _private_write(stage / name, contents, mode)
        hashes = "".join(
            f"{hashlib.sha256(contents).hexdigest()}  {name}\n"
            for name, contents, mode in outputs
        ).encode()
        _private_write(stage / "SHA256SUMS", hashes, 0o600)
    except BaseException:
        # Never leave a half-formed proposal mistaken for a complete stage.
        for file in stage.iterdir():
            file.unlink()
        stage.rmdir()
        raise
    return stage


def verify(stage: Path, *, official_only: bool = True) -> bool:
    """Re-verify exact binary FROM the archive, not editable staging hashes.

    official_only=False is permitted solely by disposable fixture tests:
    production operator paths and host admission always use the pinned
    official digest for the declared CPU architecture.
    """
    if stage.is_symlink() or not stage.is_dir():
        return False
    try:
        checksums = _file(stage / "SHA256SUMS", max_size=4096).decode()
        expected = {"backhaul.official.tar.gz", "backhaul.bin",
                    "engines.candidate.json",
                    "compose.override.candidate.yml", "summary.txt"}
        found = {}
        for line in checksums.splitlines():
            sha, sep, name = line.partition("  ")
            if not sep or name not in expected or name in found:
                return False
            if SHA_RE.fullmatch(sha) is None:
                return False
            found[name] = sha
            limit = MAX_ARCHIVE_BYTES if name == "backhaul.official.tar.gz" else MAX_BINARY_BYTES
            if hashlib.sha256(_file(stage / name, max_size=limit)).hexdigest() != sha:
                return False
        if set(found) != expected:
            return False
        lines = _file(stage / "summary.txt", max_size=4096).decode().splitlines()
        pairs = [line.split("=", 1) for line in lines]
        if (not pairs or any(len(row) != 2 for row in pairs)
                or len(pairs) != len({row[0] for row in pairs})):
            return False
        info = dict(pairs)
        arch = info.get("BACKHAUL_ARCH")
        claimed_archive = info.get("ARCHIVE_SHA256")
        if (arch not in OFFICIAL_TAR_SHA256 or not isinstance(claimed_archive, str)
                or SHA_RE.fullmatch(claimed_archive) is None
                or info.get("BACKHAUL_VERSION") != VERSION
                or info.get("CANDIDATE_ONLY") != "YES"
                or claimed_archive != found["backhaul.official.tar.gz"]):
            return False
        if official_only and claimed_archive != OFFICIAL_TAR_SHA256[arch]:
            return False
        archived = _verified_binary(stage / "backhaul.official.tar.gz", claimed_archive)
        staged = _file(stage / "backhaul.bin", max_size=MAX_BINARY_BYTES)
        if (staged != archived or
                info.get("BACKHAUL_BINARY_SHA256") != hashlib.sha256(staged).hexdigest()):
            return False
        # Metadata must describe the actual staged engine inventory.
        # Recomputing editable SHA256SUMS must never make an inaccurate
        # "FRP not installed" claim acceptable as a verified stage.
        declaration = json.loads(_file(stage / "engines.candidate.json", max_size=8192))
        if (not isinstance(declaration, dict)
                or set(declaration) != {"schema", "engines"}
                or declaration["schema"] != 1
                or not isinstance(declaration["engines"], dict)
                or "backhaul" not in declaration["engines"]
                or declaration["engines"]["backhaul"] != {
                    "sha256": hashlib.sha256(staged).hexdigest()
                }
                or not set(declaration["engines"]).issubset(ENGINE_NAMES)
                or info.get("FRP_INSTALLED") != (
                    "YES" if "frp" in declaration["engines"] else "NO")
                or info.get("ENGINE_ENROLLED") != "NO"
                or info.get("NODE_RESTARTED") != "NO"
                or info.get("PUBLIC_PORTS_CHANGED") != "NO"):
            return False
        # Local SHA256SUMS is mutable: bind the proposed Compose override
        # to the exact reviewed read-only mount, not its editable checksum.
        expected_overlay = (
            "services:\n"
            "  smite-node:\n"
            "    volumes:\n"
            "      - type: bind\n"
            f"        source: {INSTALL_BINARY}\n"
            f"        target: {CONTAINER_BINARY}\n"
            "        read_only: true\n"
        ).encode()
        if _file(stage / "compose.override.candidate.yml", max_size=8192) != expected_overlay:
            return False
        # Stage-only checks never certify a real-world Node or its runtime.
        return True
    except (Hold, OSError, UnicodeError, ValueError, TypeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Backhaul-only installation candidate")
    parser.add_argument("action", choices=["prepare", "verify"])
    parser.add_argument("--node-dir", type=Path, default=Path("/opt/smite-node"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--staging-dir", type=Path, default=Path("/var/lib/u-opti/smite-engine-staging"))
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--arch", choices=tuple(OFFICIAL_TAR_SHA256))
    args = parser.parse_args()
    try:
        if args.action == "verify":
            if args.stage is None:
                raise Hold("Specify --stage")
            if not verify(args.stage):
                raise Hold("Prepared candidate failed integrity verification")
            print("BACKHAUL_CANDIDATE_VERIFIED=YES")
            return 0
        if os.geteuid() != 0:
            raise Hold("Root required for engine preparation")
        if args.archive is None or args.arch is None:
            raise Hold("Provide trusted --archive and --arch")
        stage = prepare(args.node_dir, args.archive, args.staging_dir, arch=args.arch)
        print(f"BACKHAUL_CANDIDATE_PREPARED={stage}")
        print("LIVE_SERVICES_UNCHANGED=YES")
        return 0
    except (Hold, OSError, UnicodeError) as exc:
        print(f"HOLD: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
