#!/usr/bin/env python3
"""Independent Backhaul operator control. Live host actions deliberately OFF.

The public status/review/verify paths are READ ONLY. install/rollback invoke
ONLY the already gated disposable GitHub PR filesystem transaction. There
is NO production activation, Docker/FRP/Nginx operation, network request,
tunnel configuration or remote server operation in this module.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys

MODULES = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, MODULES / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("U-OPTI managed Backhaul helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = _load("uopti_bh_preparer", "smite-managed-backhaul.py")
transaction = _load("uopti_bh_tx", "smite-managed-backhaul-transaction.py")

ENGINES = ("backhaul", "frp", "gost", "rathole", "chisel")
ROLE = {"iran": "IR", "panel-iran": "IR", "foreign": "KH"}
EXPECTED_PROD_BINARY = package.INSTALL_BINARY
EXPECTED_TARGET = package.CONTAINER_BINARY
NODE_DEFAULT = Path("/opt/smite-node")


class Hold(ValueError):
    pass


def _trusted_env(node: Path) -> tuple[str, dict[str, str]]:
    raw = package._file(node / ".env", max_size=16384).decode("utf-8")
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep and key in {
            "NODE_ROLE", "SMITE_ENGINE_INVENTORY_MODE",
            "SMITE_AGENT_AUTH_MODE", "SMITE_NODE_PANEL_AUTH_MODE",
        }:
            if key in values:
                raise Hold("Duplicate protected Node environment setting")
            values[key] = value
    if (values.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
            or values.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or values.get("SMITE_NODE_PANEL_AUTH_MODE") not in ("paused", "signed")):
        raise Hold("Managed strict Smite Core is required; no legacy migration")
    return ROLE.get(values.get("NODE_ROLE"), "UNVERIFIED"), values


def inspect(node: Path, *, lab_binary: Path | None = None) -> dict[str, str]:
    """Local installation evidence, NOT a signed or running Node report."""
    if not node.is_absolute() or node.is_symlink() or not node.is_dir():
        raise Hold("Expected absolute, regular Smite Node directory")
    role, _ = _trusted_env(node)
    if role == "UNVERIFIED":
        raise Hold("Unknown Smite Node IR/KH role")
    compose = package._file(node / "docker-compose.yml", max_size=131072).decode("utf-8")
    if (len(re.findall(r"(?m)^  smite-node:\s*$", compose)) != 1
            or not re.search(r"(?m)^    network_mode: host\s*$", compose)
            or not re.search(r"(?m)^    image: \S+", compose)
            or not re.search(r"(?m)^\s+- ./config:/etc/smite-node\s*$", compose)
            or re.search(r"(?m)^    ports:\s*$", compose)):
        raise Hold("Unknown or unsafe Smite Node Compose layout")
    cfg = node / "config"
    if cfg.is_symlink() or not cfg.is_dir():
        raise Hold("Smite Core config bind absent or symlinked")
    declared = package._existing_manifest(cfg)
    binary = lab_binary if lab_binary is not None else EXPECTED_PROD_BINARY
    if not binary.is_absolute() or binary.is_symlink():
        raise Hold("Unsafe engine binary path")
    required_mount = f"      - {binary}:{EXPECTED_TARGET}:ro"
    has_mount = required_mount in compose.splitlines()
    any_backhaul_target = EXPECTED_TARGET in compose
    backhaul_is_declared = "backhaul" in declared
    path_exists = binary.exists() or binary.is_symlink()

    if not backhaul_is_declared:
        if any_backhaul_target or path_exists:
            return {"role": role, "state": "UNAVAILABLE", "reason": "PARTIAL_INSTALL_OR_DRIFT"}
        return {"role": role, "state": "NOT_INSTALLED", "reason": "NO_ENROLLMENT"}
    if not has_mount or compose.count(EXPECTED_TARGET) != 1 or not path_exists:
        return {"role": role, "state": "UNAVAILABLE", "reason": "MISSING_TRUSTED_READONLY_MOUNT"}

    st = binary.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
            or st.st_uid != 0 or not (st.st_mode & 0o111)
            or st.st_mode & 0o022 or st.st_size > package.MAX_BINARY_BYTES):
        return {"role": role, "state": "UNAVAILABLE", "reason": "INVALID_BINARY_PERMISSIONS"}
    value = package._file(binary, max_size=package.MAX_BINARY_BYTES)
    if hashlib.sha256(value).hexdigest() != declared["backhaul"]["sha256"]:
        return {"role": role, "state": "UNAVAILABLE", "reason": "BINARY_SHA256_MISMATCH"}
    return {"role": role, "state": "ENROLLED_UNVERIFIED", "reason": "SIGNED_NODE_RECHECK_REQUIRED"}



# RC7 already bundles the official SHA-pinned Backhaul v0.7.2 image binary.
# This opt-in verification intentionally does NOT write the engine manifest,
# start any Backhaul process or recreate the FRP-owning Node.
RC7_BUNDLED_BACKHAUL_AUDIT = r"""
import hashlib,json,os,stat
from app.config import settings
assert settings.smite_engine_inventory_mode == "managed"
assert settings.smite_engine_manifest_path == "/etc/smite-node/engine-state/engines.json"
path = "/usr/local/bin/backhaul"
meta = os.lstat(path)
assert stat.S_ISREG(meta.st_mode) and meta.st_uid == 0
assert meta.st_mode & 0o111 and not (meta.st_mode & 0o022)
assert 0 < meta.st_size <= 48*1024*1024 and meta.st_nlink == 1
fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
try:
    opened = os.fstat(fd)
    assert (opened.st_dev,opened.st_ino) == (meta.st_dev,meta.st_ino)
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb") as f:
        total = 0
        for chunk in iter(lambda:f.read(1024*1024),b""):
            total += len(chunk)
            assert total <= 48*1024*1024
            digest.update(chunk)
        assert total == meta.st_size
except BaseException:
    try: os.close(fd)
    except OSError: pass
    raise
print(json.dumps({"sha256":digest.hexdigest()},sort_keys=True))
"""

# A signed GET uses the reviewed Node's own HMAC identity and durable replay
# nonce; no outbound network, proxy or redirect is permitted.
RC7_BUNDLED_SIGNED_INVENTORY = r"""
import json,secrets,urllib.request
from app.agent_auth import read_identity
from app.node_auth import sign_request
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None
node_id,secret=read_identity('/run/smite-node-identity/node-identity.json')
target='/api/agent/engines'
headers=sign_request(secret=secret,node_id=node_id,method='GET',target=target,
                     body=b'',nonce=secrets.token_hex(16))
url='http://127.0.0.1:8888'+target
request=urllib.request.Request(url,headers=headers,method='GET')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
with opener.open(request,timeout=6) as response:
    assert response.status==200 and response.geturl()==url
    raw=response.read(4097)
    assert 0<len(raw)<=4096
    json.loads(raw)
print(raw.decode('utf-8'))
"""

RC7_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _strict_rc7_response(raw: str, *, kind: str) -> dict:
    if not isinstance(raw, str) or not 0 < len(raw.encode("utf-8")) <= 4096:
        raise Hold("RC7_BUNDLED_READONLY_PROOF_INVALID")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Hold("RC7_BUNDLED_READONLY_PROOF_INVALID")
            result[key] = value
        return result
    try:
        doc = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise Hold("RC7_BUNDLED_READONLY_PROOF_INVALID") from exc
    if kind == "binary":
        if (not isinstance(doc, dict) or set(doc) != {"sha256"}
                or not isinstance(doc["sha256"], str)
                or RC7_SHA256.fullmatch(doc["sha256"]) is None):
            raise Hold("RC7_BUNDLED_BINARY_UNTRUSTED")
    elif kind == "inventory":
        if (not isinstance(doc, dict) or set(doc) != {"mode", "engines"}
                or doc["mode"] != "managed"
                or not isinstance(doc["engines"], dict)
                or set(doc["engines"]) != set(ENGINES)
                or any(type(value) is not str
                       or value not in ("ready", "not-installed", "unavailable")
                       for value in doc["engines"].values())):
            raise Hold("RC7_BUNDLED_INVENTORY_UNTRUSTED")
    else:
        raise Hold("RC7_BUNDLED_READONLY_PROOF_INVALID")
    return doc


def verify_rc7_bundled_backhaul(role: str) -> dict[str, str]:
    """Reviewed RC7 runtime and signed engine-inventory *preflight only*.

    No install, no manifest write, no output of hashes/Node identities.
    The authenticated Agent read consumes a durable replay nonce, but no
    service/process/configuration is changed. A PASS is not permission.
    """
    if role not in ("ir", "foreign"):
        raise Hold("RC7_BUNDLED_ROLE_INVALID")
    if os.geteuid() != 0:
        raise Hold("RC7_BUNDLED_ROOT_REQUIRED")
    frp = _load("uopti_bh_rc7_runtime_probe", "smite-rc7-frp-enrollment.py")
    try:
        with frp.rt.locked():
            doc = frp.node_details()
            if doc.get("role") != role:
                raise Hold("RC7_BUNDLED_RUNTIME_ROLE_MISMATCH")
            runtime = frp.rt.inspect_container("smite-node")
            mounts = runtime.get("Mounts")
            if not isinstance(mounts, list):
                raise Hold("RC7_BUNDLED_MOUNT_INVENTORY_UNTRUSTED")
            for mount in mounts:
                if not isinstance(mount, dict):
                    raise Hold("RC7_BUNDLED_MOUNT_INVENTORY_UNTRUSTED")
                destination = mount.get("Destination")
                if not isinstance(destination, str):
                    raise Hold("RC7_BUNDLED_MOUNT_INVENTORY_UNTRUSTED")
                if (destination in ("/usr", "/usr/local",
                                    "/usr/local/bin", "/usr/local/bin/backhaul")
                        or destination.startswith("/usr/local/bin/backhaul/")):
                    raise Hold("RC7_BUNDLED_BACKHAUL_EXTERNAL_MOUNT")
            frp.rt.signed_probe()
            binary = _strict_rc7_response(
                frp.rt.run(["docker","exec","smite-node","python3","-B","-c",
                            RC7_BUNDLED_BACKHAUL_AUDIT],timeout=30),
                kind="binary")
            inventory = _strict_rc7_response(
                frp.rt.run(["docker","exec","smite-node","python3","-B","-c",
                            RC7_BUNDLED_SIGNED_INVENTORY],timeout=30),
                kind="inventory")
            if inventory["engines"]["frp"] != "ready":
                raise Hold("RC7_BUNDLED_EXISTING_FRP_NOT_READY")
            if inventory["engines"]["backhaul"] != "not-installed":
                raise Hold("RC7_BUNDLED_BACKHAUL_ALREADY_ENROLLED_OR_UNAVAILABLE")
            if not RC7_SHA256.fullmatch(binary["sha256"]):
                raise Hold("RC7_BUNDLED_BINARY_UNTRUSTED")
    except frp.Hold as exc:
        # Preserve only a fixed local HOLD, never an untrusted verifier body.
        raise Hold("RC7_BUNDLED_RUNTIME_UNVERIFIED") from exc
    except (OSError, RuntimeError, TypeError, KeyError, AttributeError,
            ValueError) as exc:
        if isinstance(exc, Hold):
            raise
        # Never leak Docker stdout, secrets, process IDs or image metadata.
        raise Hold("RC7_BUNDLED_READONLY_PROBE_FAILED") from exc
    return {
        "RC7_BACKHAUL_IMAGE_BINARY": "OBSERVED_PINNED_IMAGE_NO_MOUNT",
        "RC7_BACKHAUL_ENGINE": "NOT_INSTALLED_SIGNED_INVENTORY",
        "RC7_FRP_ENGINE": "READY_SIGNED_INVENTORY",
        "RC7_SIGNED_REPLAY": "PASS",
        "NODE_RECREATED": "NO",
        "FRP_OR_TUNNELS_CHANGED": "NOT_REQUESTED",
        "SIGNED_OWNER_CHILD_CONTINUITY": "NOT_PROVEN",
        "INSTALL_ALLOWED": "NO",
        "ACTIVATION_GATE": "HOLD",
    }


def verified_candidate(stage: Path) -> dict[str, str]:
    if stage.is_symlink() or not stage.is_absolute():
        raise Hold("Unsafe candidate path")
    if not package.verify(stage):
        raise Hold("Unverified or corrupted Backhaul candidate")
    summary = transaction.parse_summary(stage)
    arch = summary.get("BACKHAUL_ARCH")
    if (arch not in package.OFFICIAL_TAR_SHA256
            or summary.get("ARCHIVE_SHA256") != package.OFFICIAL_TAR_SHA256[arch]
            or summary.get("BACKHAUL_VERSION") != package.VERSION
            or summary.get("CANDIDATE_ONLY") != "YES"):
        raise Hold("Only officially pinned Backhaul v0.7.2 candidates allowed")
    return {"state": "VERIFIED_CANDIDATE_ONLY", "engine": "backhaul", "arch": arch}


def _format(status: dict[str, str]) -> None:
    for key, value in status.items():
        print(f"{key.upper()}={value}")


@contextmanager
def _lab_lock(root: Path):
    # No lock creation is possible until the PR-only lab admission passes.
    transaction.admission(root)
    # All managed engines mutate the SAME Node Compose and manifest.
    # FRP and Backhaul installs are independent, not concurrently writable.
    file = root / ".smite-engine-transaction.lock"
    fd = os.open(file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1):
            raise Hold("Unsafe transaction lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Hold("Another Backhaul engine transaction is in progress") from exc
        yield
    finally:
        os.close(fd)


def exercise(root: Path, *, action: str, stage: Path | None = None) -> dict[str, str]:
    """Only operates on a marked, private, disposable GitHub runner lab."""
    if action not in ("install", "rollback"):
        raise Hold("Unknown experimental action")
    with _lab_lock(root):
        node = root / "node"
        bin_file = root / "installed" / "backhaul"
        if action == "install":
            if stage is None:
                raise Hold("Verified stage required")
            verified_candidate(stage)
            before = inspect(node, lab_binary=bin_file)
            if before["state"] != "NOT_INSTALLED":
                raise Hold("Backhaul not cleanly absent; repair is separate")
            transaction.activate(root, stage)
            result = inspect(node, lab_binary=bin_file)
            if result["state"] != "ENROLLED_UNVERIFIED":
                raise Hold("Post-transaction evidence mismatch: recovery journal retained")
            return {"state": "LAB_INSTALLED_UNVERIFIED",
                    "next": "SIGNED_NODE_RUNTIME_PROOF_REQUIRED"}
        # Never erase another engine if the backup record is untrusted.
        transaction.rollback(root)
        result = inspect(node, lab_binary=bin_file)
        if result["state"] != "NOT_INSTALLED":
            raise Hold("Rollback evidence incomplete")
        return {"state": "LAB_EXACT_ROLLBACK_CONFIRMED",
                "next": "NO_LIVE_SERVICES_TOUCHED"}


def main() -> int:
    arg = argparse.ArgumentParser(description="Managed Backhaul: safe review, CI-only activation")
    arg.add_argument("action", choices=("status", "review", "verify-stage", "install", "rollback", "verify-rc7-bundle"))
    arg.add_argument("--node-dir", type=Path, default=NODE_DEFAULT)
    arg.add_argument("--role", choices=("ir", "foreign"))
    arg.add_argument("--stage", type=Path)
    arg.add_argument("--lab-root", type=Path)
    args = arg.parse_args()
    try:
        if args.action == "verify-rc7-bundle":
            if not args.role:
                raise Hold("RC7_BUNDLED_ROLE_REQUIRED")
            _format(verify_rc7_bundled_backhaul(args.role))
        elif args.action in ("install", "rollback"):
            if args.lab_root is None:
                raise Hold("Real host engine activation is NOT enabled; no server changed")
            _format(exercise(args.lab_root, action=args.action, stage=args.stage))
        elif args.action == "verify-stage":
            if args.stage is None:
                raise Hold("--stage required")
            _format(verified_candidate(args.stage))
        elif args.action == "status":
            _format(inspect(args.node_dir))
            print("SIGNED_NODE_STATUS=NOT_QUERIED")
        elif args.action == "review":
            result = inspect(args.node_dir)
            _format(result)
            print("INSTALL_ALLOWED=NO")
            print("HOST_DOCKER_ACTIONS=NONE")
            print("FRP_DEPENDENCY=NONE")
            print("PORT_OR_TUNNEL_INPUT=NOT_REQUIRED")
            print("NEXT=CI_ONLY_UNTIL_HOST_ROLLBACK_APPROVAL")
        return 0
    except (Hold, package.Hold, transaction.Hold, OSError, ValueError, UnicodeError) as error:
        print(f"HOLD: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
