#!/usr/bin/env python3
"""Disposable transaction/recovery LAB, not an installable host executor.

Only imports for isolated tests. NO CLI, Docker, subprocess, networking,
absolute production paths, service control, or public ports. This models
the Host Plan's write ordering; production authorization remains HOLD.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import uuid

SCHEMA = 1
MARKER = b"UOPTI_DISPOSABLE_HOST_EXECUTOR_LAB_V1\n"
BINARIES = {"backhaul": ("backhaul",), "frp": ("frpc", "frps")}
MAX_FILE = 1024 * 1024
MAX_BINARY = 48 * 1024 * 1024

_guard_spec = importlib.util.spec_from_file_location(
    "smite_private_fd_guard_lab", Path(__file__).with_name("smite_fd_guard.py"))
guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(guard)


class Hold(RuntimeError):
    """An unsafe state: stop without overriding unrecognized data."""


class SimulatedCrash(RuntimeError):
    """A test-injected process/power failure. Journal remains on disk."""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(data):
    return base64.b64encode(data).decode("ascii") if data is not None else None


def decode(data):
    return base64.b64decode(data, validate=True) if data is not None else None


def canonical(data):
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _atomic(root, relative, data, mode=0o600):
    try:
        guard.replace(root, relative, data, mode)
    except (guard.UnsafePath, OSError) as exc:
        raise Hold(str(exc) if isinstance(exc, guard.UnsafePath)
                   else "UNSAFE_FD_REPLACE") from exc


def _remove(root, relative):
    try:
        guard.remove(root, relative)
    except (guard.UnsafePath, OSError) as exc:
        raise Hold(str(exc) if isinstance(exc, guard.UnsafePath)
                   else "UNSAFE_FD_REMOVE") from exc


def _validate(root):
    root = Path(root)
    # Strong lab-only path guard, including a caller-created private marker.
    if (root.is_symlink() or root.parent.resolve() != Path(tempfile.gettempdir()).resolve()
            or not root.name.startswith("uopti-engine-txn-lab-")
            or not root.is_dir()):
        raise Hold("DISPOSABLE_LAB_ROOT_REQUIRED")
    st = root.lstat()
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise Hold("UNTRUSTED_LAB_ROOT")
    if _snapshot(root, ".LAB_ONLY")["bytes"] != encode(MARKER):
        raise Hold("MISSING_LAB_MARKER")
    return root


@contextmanager
def _lock(root):
    try:
        with guard.lock(root):
            yield
    except (guard.UnsafePath, OSError) as exc:
        raise Hold(str(exc) if isinstance(exc, guard.UnsafePath)
                   else "UNSAFE_FD_LOCK") from exc


def _snapshot(root, relative, limit=MAX_FILE):
    try:
        blob, mode = guard.read(root, relative, limit)
    except (guard.UnsafePath, OSError) as exc:
        raise Hold(str(exc) if isinstance(exc, guard.UnsafePath)
                   else "UNSAFE_FD_READ") from exc
    return {"bytes": encode(blob), "sha256": sha(blob) if blob is not None else None,
            "mode": mode}


def _match(root, relative, expected):
    now = _snapshot(root, relative, MAX_BINARY if "/managed-bin/" in "/" + relative else MAX_FILE)
    return now["sha256"] == expected["sha256"] and now["mode"] == expected["mode"]


def _protected(engine):
    other = "backhaul" if engine == "frp" else "frp"
    paths = ["node/docker-compose.yml", "node/.env", "node/config/node-id",
             "node/config/replay.db", "node/config/tunnels.json",
             "node/docker-compose.managed-" + other + ".yml"]
    return paths + ["node/managed-bin/" + other + "/" + name for name in BINARIES[other]]


def _mutable(engine):
    return (["node/managed-bin/" + engine + "/" + name for name in BINARIES[engine]]
            + ["node/docker-compose.managed-" + engine + ".yml",
               "node/config/engine-state/engines.json"])


def _journal_read(root):
    encoded = _snapshot(root, ".engine-journal.json")["bytes"]
    data = decode(encoded)
    if data is None:
        return None
    try:
        entry = json.loads(data)
        seal = entry.pop("seal")
        valid = (sha(canonical(entry)) == seal and entry["schema"] == SCHEMA
                 and entry["engine"] in BINARIES
                 and set(entry["previous"]) == set(_mutable(entry["engine"]))
                 and set(entry["after"]) == set(_mutable(entry["engine"]))
                 and set(entry["protected"]) == set(_protected(entry["engine"])))
        entry["seal"] = seal
        if not valid:
            raise Hold("JOURNAL_INVALID")
        for name, snap in entry["previous"].items():
            original = decode(snap["bytes"])
            if (sha(original) if original is not None else None) != snap["sha256"]:
                raise Hold("JOURNAL_PREIMAGE_INVALID")
        return entry
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise Hold("JOURNAL_INVALID") from exc


def _journal_write(root, entry):
    document = {k: v for k, v in entry.items() if k != "seal"}
    entry["seal"] = sha(canonical(document))
    _atomic(root, ".engine-journal.json", canonical(entry), 0o600)


def _check_protected(root, entry):
    if any(not _match(root, name, snapshot) for name, snapshot in entry["protected"].items()):
        raise Hold("PROTECTED_OR_OTHER_ENGINE_DRIFT")


def _status_probe(probe, kind, engine):
    # A synthetic signed-runtime oracle, supplied by the unit test.
    # It cannot authorize real hosting and MUST NOT be replaced by a local
    # file existence / unsigned container status check in a future executor.
    verdict = probe(kind, engine)
    if not isinstance(verdict, dict) or verdict.get("signed") is not True or verdict.get("replay") is not True:
        raise Hold("SIGNED_RUNTIME_SIMULATION_FAILED")


def _verify_terminal(root, entry, probe):
    # A completed journal is historical evidence, not a permanent runtime
    # attestation. Every reuse checks file modes, hashes and simulated signed API.
    _check_protected(root, entry)
    committed = entry["state"] == "COMMITTED"
    for name in _mutable(entry["engine"]):
        expected = ({"sha256": entry["after"][name],
                     "mode": entry["after_modes"][name]}
                    if committed else entry["previous"][name])
        if not _match(root, name, expected):
            raise Hold("COMPLETED_JOURNAL_DRIFT")
    _status_probe(probe, "new" if committed else "prior", entry["engine"])


def _archive_completed(root, entry, probe):
    if entry["state"] not in ("COMMITTED", "ROLLED_BACK"):
        raise Hold("UNRESOLVED_JOURNAL")
    _verify_terminal(root, entry, probe)
    destination = "audit-" + entry["id"] + ".json"
    try:
        guard.move(root, ".engine-journal.json", destination)
    except (guard.UnsafePath, OSError) as exc:
        raise Hold("AUDIT_CONFLICT_OR_UNSAFE_PATH") from exc


def _recovery_locked(root, probe):
    entry = _journal_read(root)
    if entry is None:
        return "NO_JOURNAL"
    if entry["state"] in ("COMMITTED", "ROLLED_BACK"):
        _verify_terminal(root, entry, probe)
        return entry["state"]
    _check_protected(root, entry)
    # No blind overwrites: every tracked value must match exact old or new bytes.
    for name in _mutable(entry["engine"]):
        now = _snapshot(root, name, MAX_BINARY)
        before = entry["previous"][name]
        allowed = ((before["sha256"], before["mode"]),
                   (entry["after"][name], entry["after_modes"][name]))
        if (now["sha256"], now["mode"]) not in allowed:
            raise Hold("EXTERNAL_MUTATION_CONFLICT")
    entry["state"] = "RECOVERING"
    _journal_write(root, entry)
    for name in reversed(_mutable(entry["engine"])):
        prior = entry["previous"][name]
        old = decode(prior["bytes"])
        if old is None:
            _remove(root, name)
        else:
            _atomic(root, name, old, prior["mode"])
    _check_protected(root, entry)
    _status_probe(probe, "prior", entry["engine"])
    entry["state"] = "ROLLED_BACK"
    _journal_write(root, entry)
    return "ROLLED_BACK"


def recover(root, probe):
    root = _validate(root)
    with _lock(root):
        return _recovery_locked(root, probe)


def execute(root, engine, binaries, overlay, preview, probe, crash_at=None, *, candidate_manifest=None):
    """Mutate only disposable fixture paths; approval flags remain NO/HOLD."""
    root = _validate(root)
    if engine not in BINARIES or set(binaries) != set(BINARIES[engine]):
        raise Hold("BAD_ENGINE_OR_BINARY_SET")
    if not isinstance(overlay, bytes) or len(overlay) > MAX_FILE:
        raise Hold("BAD_OVERLAY")
    if any(not isinstance(v, bytes) or not v or len(v) > MAX_BINARY for v in binaries.values()):
        raise Hold("BAD_BINARY")
    if preview.get("CANDIDATE_COMPOSE_OVERLAY_SHA256") != sha(overlay):
        raise Hold("CANDIDATE_COMPOSE_OVERLAY_DRIFT")
    if (preview.get("STAGE_ADMISSION") != "VERIFIED_PREVIEW_ONLY"
            or preview.get("INSTALL_ALLOWED") != "NO"
            or preview.get("ACTIVATION_GATE") != "HOLD"
            or preview.get("BINARIES_SHA256") != [sha(binaries[k]) for k in BINARIES[engine]]):
        raise Hold("PLAN_PREVIEW_INVALID")
    with _lock(root):
        previous_entry = _journal_read(root)
        if previous_entry is not None:
            _archive_completed(root, previous_entry, probe)
        manifest_file = "node/config/engine-state/engines.json"
        compose = decode(_snapshot(root, "node/docker-compose.yml")["bytes"])
        if compose is None or sha(compose) != preview.get("SOURCE_COMPOSE_SHA256"):
            raise Hold("COMPOSE_DRIFT")
        existing_raw = decode(_snapshot(root, manifest_file)["bytes"])
        existing = json.loads(existing_raw) if existing_raw is not None else {"schema": 1, "engines": {}}
        if (set(existing) != {"schema", "engines"} or existing["schema"] != 1
                or not isinstance(existing["engines"], dict)
                or engine in existing["engines"]
                or not set(existing["engines"]).issubset(BINARIES)):
            raise Hold("MANIFEST_INCOMPATIBLE")
        other = "backhaul" if engine == "frp" else "frp"
        if other in existing["engines"]:
            if preview.get("OTHER_ENGINE") != "SIGNED_READY_ATTESTED_SIMULATED":
                raise Hold("OTHER_ENGINE_SIGNED_PROOF_REQUIRED")
            record = existing["engines"][other]
            for index, name in enumerate(BINARIES[other]):
                expected = record.get("sha256" if index == 0 else "server_sha256")
                saved = _snapshot(root, "node/managed-bin/" + other + "/" + name, MAX_BINARY)
                if saved["sha256"] != expected or saved["mode"] != 0o755:
                    raise Hold("OTHER_ENGINE_BINARY_UNVERIFIED")
            if _snapshot(root, "node/docker-compose.managed-" + other + ".yml")["sha256"] is None:
                raise Hold("OTHER_ENGINE_COMPOSE_MISSING")
            _status_probe(probe, "other", other)
        elif preview.get("OTHER_ENGINE") != "NOT_INSTALLED":
            raise Hold("OTHER_ENGINE_STATE_DRIFT")
        if _snapshot(root, "node/config/tunnels.json")["sha256"] != sha(b"[]\n"):
            raise Hold("SAVED_TUNNELS_OR_UNKNOWN_STATE")
        output = dict(existing["engines"])
        record = {"sha256": sha(binaries[BINARIES[engine][0]])}
        if engine == "frp":
            record["server_sha256"] = sha(binaries["frps"])
        output[engine] = record
        expected_manifest = {"schema": 1, "engines": output}
        if candidate_manifest is not None:
            # Real Stage uses pretty JSON; compare exact staged bytes AND
            # semantic engine contents rather than silently reformatting it.
            if (not isinstance(candidate_manifest, bytes)
                    or len(candidate_manifest) > 8192 or not candidate_manifest):
                raise Hold("CANDIDATE_MANIFEST_INVALID")
            try:
                parsed = json.loads(candidate_manifest)
            except (ValueError, UnicodeError, TypeError) as exc:
                raise Hold("CANDIDATE_MANIFEST_INVALID") from exc
            if parsed != expected_manifest:
                raise Hold("CANDIDATE_MANIFEST_SEMANTIC_DRIFT")
            new_manifest = candidate_manifest
        else:
            new_manifest = canonical(expected_manifest)
        if sha(new_manifest) != preview.get("CANDIDATE_MANIFEST_SHA256"):
            raise Hold("CANDIDATE_MANIFEST_DRIFT")
        mutable = _mutable(engine)
        new_values = {**{"node/managed-bin/" + engine + "/" + name: binaries[name]
                         for name in BINARIES[engine]},
                      "node/docker-compose.managed-" + engine + ".yml": overlay,
                      manifest_file: new_manifest}
        snapshots = {name: _snapshot(root, name, MAX_BINARY) for name in mutable}
        if any(snap["bytes"] is not None for name, snap in snapshots.items() if name != manifest_file):
            raise Hold("ENGINE_PARTIALLY_PRESENT")
        protected = {name: _snapshot(root, name) for name in _protected(engine)}
        entry = {"schema": SCHEMA, "id": uuid.uuid4().hex, "engine": engine,
                 "state": "PREPARED", "previous": snapshots,
                 "after": {name: sha(value) for name, value in new_values.items()},
                 "after_modes": {name: (0o755 if "/managed-bin/" in "/" + name else 0o600)
                                 for name in new_values},
                 "protected": protected}
        _journal_write(root, entry)  # fsync BEFORE any mutation
        try:
            if crash_at == "before_copy":
                raise SimulatedCrash("before_copy")
            for name in BINARIES[engine]:
                _check_protected(root, entry)
                relative = "node/managed-bin/" + engine + "/" + name
                _atomic(root, relative, binaries[name], 0o755)
                entry["state"] = "WROTE_" + name.upper()
                _journal_write(root, entry)
                if crash_at == "after_" + name:
                    raise SimulatedCrash(crash_at)
            _check_protected(root, entry)
            _atomic(root, "node/docker-compose.managed-" + engine + ".yml", overlay)
            entry["state"] = "WROTE_COMPOSE"
            _journal_write(root, entry)
            if crash_at == "after_compose":
                raise SimulatedCrash(crash_at)
            _check_protected(root, entry)
            _atomic(root, manifest_file, new_manifest)
            entry["state"] = "WROTE_MANIFEST"
            _journal_write(root, entry)
            if crash_at == "after_manifest":
                raise SimulatedCrash(crash_at)
            # Deliberately no Docker call: this models a single-Node restart.
            if crash_at == "during_restart":
                raise SimulatedCrash(crash_at)
            entry["state"] = "NODE_RESTART_SIMULATED"
            _journal_write(root, entry)
            if crash_at == "after_restart":
                raise SimulatedCrash(crash_at)
            _status_probe(probe, "new", engine)
            if crash_at == "after_signed":
                raise SimulatedCrash(crash_at)
            _check_protected(root, entry)
            if any(not _match(root, name, {"sha256": digest, "mode": entry["after_modes"][name]})
                   for name, digest in entry["after"].items()):
                raise Hold("POST_RESTART_ENGINE_DRIFT")
            entry["state"] = "COMMITTED"
            _journal_write(root, entry)
            return {"LAB_RESULT": "COMMITTED_SIMULATION_ONLY",
                    "INSTALL_ALLOWED": "NO", "ACTIVATION_GATE": "HOLD"}
        except SimulatedCrash:
            raise
        except Exception:
            _recovery_locked(root, probe)
            raise
