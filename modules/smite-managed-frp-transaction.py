#!/usr/bin/env python3
"""Crash-recoverable FRP dual-binary transaction in a marked PR CI lab ONLY.

This module has NO production activation, network access, Docker/restart,
Nginx, public port, tunnel or remote Node operations. Both FRP roles are
enrolled together or rolled back together; other engines are unchanged.
"""
from __future__ import annotations
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from contextlib import contextmanager

HERE = Path(__file__).resolve().parent


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


frp = load("smite_offline_frp_txn", "smite-managed-frp.py")
lab = load("smite_reused_admission_txn", "smite-managed-backhaul-transaction.py")

MARKER = lab.MARKER
SHA = lab.SHA


class Hold(RuntimeError):
    pass


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def paths(root: Path) -> tuple[Path, Path, dict[str, Path], Path]:
    # Shared Backhaul gate guarantees GitHub PR, RUNNER_TEMP, marker and
    # strict 0700 lab/node/config/stages directory ownership before writing.
    compose, manifest, _, stages = lab.admission(root)
    binaries = {name: root / "installed" / "frp" / name for name in ("frpc", "frps")}
    journal = root / "frp-recovery-journal"
    for path in (*binaries.values(), journal):
        lab.ensure_in_lab(root, path)
    return compose, manifest, binaries, stages


@contextmanager
def lock(root: Path):
    paths(root)
    file = root / ".frp-engine.lock"
    fd = os.open(file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1):
            raise Hold("UNTRUSTED_FRP_LOCK")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Hold("ANOTHER_FRP_TRANSACTION_ACTIVE") from exc
        yield
    finally:
        os.close(fd)


def protected(root: Path) -> dict[str, str | None]:
    """Never operate when saved tunnels exist; pin identity during trial."""
    data = root / "node-data" / "tunnels.json"
    identity = root / "node" / "config" / "identity" / "node-identity.json"
    result = {}
    for name, path, limit in (("tunnels", data, 256 * 1024),
                              ("identity", identity, 8192)):
        if not path.exists() and not path.is_symlink():
            result[name] = None
            continue
        contents = lab.checked(path, max_size=limit)
        if name == "tunnels":
            try:
                parsed = json.loads(contents)
            except (ValueError, UnicodeError) as exc:
                raise Hold("CORRUPT_PERSISTED_TUNNELS") from exc
            if parsed not in ({}, []):
                raise Hold("EXISTING_TUNNELS_NO_RECREATE")
        result[name] = digest(contents)
    return result


def candidate(root: Path, stage: Path, *, fixture: bool = False):
    compose, manifest, binaries, stages = paths(root)
    lab.ensure_in_lab(root, stage)
    if stage.parent != stages:
        raise Hold("CANDIDATE_OUTSIDE_PRIVATE_STAGES")
    lab.private_dir(stage)
    if not frp.verify(stage, official_only=not fixture):
        raise Hold("FRP_CANDIDATE_VERIFICATION_FAILED")
    initial, existing = frp.core_preflight(root / "node")
    actual = lab.checked(compose, 131072)
    if initial != actual:
        raise Hold("COMPOSE_DRIFT")
    summary = dict(
        line.split("=", 1) for line in
        lab.checked(stage / "summary.txt", 4096).decode().splitlines()
    )
    if summary.get("ORIGINAL_COMPOSE_SHA256") != digest(actual):
        raise Hold("COMPOSE_CHANGED_SINCE_PREPARATION")
    if summary.get("PORT_OR_TUNNEL_INPUT") != "NOT_REQUIRED":
        raise Hold("PORT_REQUEST_DURING_ENGINE_INSTALL")
    prior = lab.checked(manifest, 8192) if manifest.exists() or manifest.is_symlink() else None
    staged_manifest = lab.checked(stage / "engines.candidate.json", 8192)
    proposed = json.loads(staged_manifest)
    staged_bin = {name: lab.checked(stage / f"{name}.bin", frp.BINARY_MAX) for name in binaries}
    expected = {"sha256": digest(staged_bin["frpc"]),
                "server_sha256": digest(staged_bin["frps"])}
    if (proposed.get("schema") != 1 or not isinstance(proposed.get("engines"), dict)
            or proposed["engines"].get("frp") != expected
            or {k: v for k, v in proposed["engines"].items() if k != "frp"} != existing):
        raise Hold("ENGINE_DECLARATION_DRIFT")
    for p in binaries.values():
        if p.exists() or p.is_symlink():
            raise Hold("FRP_BINARY_ALREADY_PRESENT")
    anchor = "      - ./config:/etc/smite-node\n"
    if actual.decode().count(anchor) != 1:
        raise Hold("AMBIGUOUS_CONFIG_MOUNT")
    inserts = "".join(
        f"      - {binaries[name]}:{frp.BINARY_PATHS[name]}:ro\n"
        for name in ("frpc", "frps")
    )
    next_compose = actual.decode().replace(anchor, anchor + inserts, 1).encode()
    if any(next_compose.count(frp.BINARY_PATHS[name].encode()) != 1 for name in binaries):
        raise Hold("AMBIGUOUS_FRP_MOUNTS")
    # The candidate's general-purpose Compose overlay was validated
    # during frp.verify(); lab install uses only private lab binary paths.
    return actual, next_compose, prior, staged_manifest, staged_bin


def activate(root: Path, stage: Path, *, fixture: bool = False,
             inject: str = "") -> str:
    compose, manifest, binaries, _ = paths(root)
    journal = root / "frp-recovery-journal"
    if journal.exists() or journal.is_symlink():
        raise Hold("RECOVERY_REQUIRED_BEFORE_NEW_INSTALL")
    before, after, old_manifest, new_manifest, staged = candidate(root, stage, fixture=fixture)
    protected_before = protected(root)
    state = manifest.parent
    if state.exists() or state.is_symlink():
        lab.private_dir(state)
    modes = {
        "compose": stat.S_IMODE(compose.lstat().st_mode),
        "manifest": stat.S_IMODE(manifest.lstat().st_mode) if old_manifest is not None else None,
    }
    if modes["compose"] not in (0o600, 0o640, 0o644) or (
            old_manifest is not None and modes["manifest"] != 0o600):
        raise Hold("UNRECOGNIZED_EXISTING_FILE_MODES")
    record = {
        "schema": 1,
        "old_compose": digest(before), "new_compose": digest(after),
        "old_manifest": digest(old_manifest) if old_manifest is not None else None,
        "new_manifest": digest(new_manifest),
        "client": digest(staged["frpc"]), "server": digest(staged["frps"]),
        "compose_mode": modes["compose"], "manifest_mode": modes["manifest"],
        "protected": protected_before,
    }
    # Capture exact recovery bytes BEFORE the first mutation.
    journal.mkdir(mode=0o700)
    lab.new_file(journal / "compose.before", before, 0o600)
    if old_manifest is not None:
        lab.new_file(journal / "manifest.before", old_manifest, 0o600)
    lab.new_file(journal / "record.json",
                 (json.dumps(record, sort_keys=True) + "\n").encode(), 0o600)
    if inject == "after-journal":
        raise Hold("INJECTED_INTERRUPTION")
    binaries["frpc"].parent.mkdir(parents=True, mode=0o700, exist_ok=False)
    lab.new_file(binaries["frpc"], staged["frpc"], 0o755)
    if inject == "after-frpc":
        raise Hold("INJECTED_INTERRUPTION")
    lab.new_file(binaries["frps"], staged["frps"], 0o755)
    if inject == "after-frps":
        raise Hold("INJECTED_INTERRUPTION")
    lab.atomic(compose, after, modes["compose"])
    if inject == "after-compose":
        raise Hold("INJECTED_INTERRUPTION")
    if not state.exists():
        state.mkdir(mode=0o700)
    if old_manifest is None:
        lab.new_file(manifest, new_manifest, 0o600)
    else:
        lab.atomic(manifest, new_manifest, 0o600)
    if inject == "after-manifest":
        raise Hold("INJECTED_INTERRUPTION")
    return "FRP_LAB_DUAL_BINARIES_ENROLLED_NO_NODE_RESTART"


def rollback(root: Path) -> str:
    compose, manifest, binaries, _ = paths(root)
    journal = root / "frp-recovery-journal"
    lab.private_dir(journal)
    record = json.loads(lab.checked(journal / "record.json", 4096))
    if not isinstance(record, dict) or record.get("schema") != 1:
        raise Hold("UNTRUSTED_FRP_RECOVERY_JOURNAL")
    for name in ("old_compose", "new_compose", "new_manifest", "client", "server"):
        if not isinstance(record.get(name), str) or not SHA.fullmatch(record[name]):
            raise Hold("CORRUPT_FRP_RECOVERY_HASH")
    if record.get("old_manifest") is not None and (
            not isinstance(record["old_manifest"], str)
            or not SHA.fullmatch(record["old_manifest"])):
        raise Hold("CORRUPT_PRIOR_MANIFEST_HASH")
    if record.get("compose_mode") not in (0o600, 0o640, 0o644) or (
            record.get("old_manifest") is not None and record.get("manifest_mode") != 0o600):
        raise Hold("UNSAFE_RESTORE_MODES")
    baseline = lab.checked(journal / "compose.before", 131072)
    previous = (lab.checked(journal / "manifest.before", 8192)
                if record["old_manifest"] is not None else None)
    if digest(baseline) != record["old_compose"] or (
            previous is not None and digest(previous) != record["old_manifest"]):
        raise Hold("RECOVERY_BACKUP_TAMPERED")
    if record.get("protected") != protected(root):
        raise Hold("PROTECTED_NODE_IDENTITY_OR_TUNNELS_CHANGED")
    current_compose = lab.checked(compose, 131072)
    if digest(current_compose) not in (record["old_compose"], record["new_compose"]):
        raise Hold("COMPOSE_MODIFIED_EXTERNALLY_NO_OVERWRITE")
    if manifest.exists() or manifest.is_symlink():
        current = digest(lab.checked(manifest, 8192))
        allowed = {record["new_manifest"]}
        if record["old_manifest"] is not None:
            allowed.add(record["old_manifest"])
        if current not in allowed:
            raise Hold("REGISTRY_CHANGED_EXTERNALLY_NO_OVERWRITE")
    elif record["old_manifest"] is not None:
        # A deleted manifest indicates possible out-of-band intervention.
        raise Hold("OLD_REGISTRY_REMOVED_EXTERNALLY")
    for name, path in binaries.items():
        if path.exists() or path.is_symlink():
            if digest(lab.checked(path, frp.BINARY_MAX)) != record["client" if name == "frpc" else "server"]:
                raise Hold("FRP_BINARY_CHANGED_EXTERNALLY_NO_OVERWRITE")
    # All proofs were checked *before* any rollback modification.
    if digest(current_compose) != record["old_compose"]:
        lab.atomic(compose, baseline, record["compose_mode"])
    if previous is None:
        if manifest.exists():
            manifest.unlink()
    elif manifest.read_bytes() != previous:
        lab.atomic(manifest, previous, 0o600)
    for path in binaries.values():
        if path.exists():
            path.unlink()
    if binaries["frpc"].parent.exists() and not any(binaries["frpc"].parent.iterdir()):
        binaries["frpc"].parent.rmdir()
        if not any(binaries["frpc"].parent.parent.iterdir()):
            binaries["frpc"].parent.parent.rmdir()
    if manifest.parent.exists() and not any(manifest.parent.iterdir()):
        manifest.parent.rmdir()
    for p in journal.iterdir():
        p.unlink()
    journal.rmdir()
    return "FRP_LAB_EXACT_ROLLBACK_CONFIRMED_NO_OTHER_ENGINE_CHANGED"


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="CI-only FRP dual-binary transaction, NEVER on VPS")
    parser.add_argument("action", choices=("activate", "rollback"))
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--stage", type=Path)
    args = parser.parse_args()
    try:
        with lock(args.lab_root):
            if args.action == "activate":
                if args.stage is None:
                    raise Hold("FRP_STAGE_REQUIRED")
                result = activate(args.lab_root, args.stage)
            else:
                result = rollback(args.lab_root)
        print(result)
        return 0
    except (Hold, lab.Hold, frp.Hold, frp.shared.Hold, OSError, ValueError) as exc:
        message = str(exc)
        # Raw paths or secrets must never be reflected from errors.
        print("HOLD: " + (message if message.isupper() and message.replace("_", "").isalnum() else "FRP_TRANSACTION_UNAVAILABLE"),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
