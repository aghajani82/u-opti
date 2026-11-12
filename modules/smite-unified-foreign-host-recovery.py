"""Foreign host stage recovery envelope; isolated rehearsal, no host execution.

Composes the EXISTING Smite installer stage contracts; never implements a
second Docker/Sanaei/Gateway installer. Its callbacks are injected by tests,
not by public CLI or a deployed host.

Safety property: after an interrupted side-effectful stage, NEVER rerun it
based on a journal alone. Verify observed external state first; if it is
fully READY, commit and continue; if it is ABSENT or DRIFT, HOLD for a
reviewed recovery. An already completed stage is verified again on EVERY
retry, so a stale "success" journal can never declare Connected.
"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile


LOCK = "unified-foreign-host.lock"
JOURNAL = "unified-foreign-host-journal.json"
PHASES = (
    "CORE_VERIFIED", "SANAEI_INTENT", "SANAEI_RO_VERIFIED",
    "GATEWAY_INTENT", "GATEWAY_443_VERIFIED",
)


class Hold(ValueError):
    pass


def deny():
    raise Hold("Unified Foreign host stage recovery HOLD; keep existing services")


def load(name, filename):
    path = Path(__file__).with_name(filename)
    if not path.is_file() or path.is_symlink():
        deny()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        deny()
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fixture_scope(directory, packet_path):
    directory = Path(directory)
    packet_path = Path(packet_path)
    top = Path(tempfile.gettempdir()).resolve()
    if (not directory.is_absolute() or ".." in directory.parts
            or packet_path != directory / "foreign-install-packet.json"
            or directory.name != "foreign-staging"
            or directory.parent.name != "foreign-fixture"
            or directory.parent.parent.parent != top):
        deny()
    for path in (directory.parent.parent, directory.parent, directory):
        if path.is_symlink() or not path.is_dir():
            deny()
        info = path.stat()
        if (info.st_uid != os.geteuid()
                or not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o700):
            deny()


def write_journal(fd, record):
    """Durable whole-record atomic replace, only inside a held private lock."""
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    if len(payload) > 8192:
        deny()
    temporary = ".foreign-host-journal-" + secrets.token_hex(12)
    out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                  os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(out, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, JOURNAL, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def rehearse(*, directory, packet_path, now, expected_panel, expected_foreign,
             expected_node, verify_core, verify_sanaei, verify_gateway,
             install_sanaei, install_gateway, disposable_capability=False):
    """Model host stage transitions with injected witnesses and operations.

    verify_core(scope) must independently verify a signed, owned fresh Node
    paused/strict and exact image/Compose. verify_sanaei(scope) must check
    RO mount and inventory. verify_gateway(scope) must check the exact
    HTTPS/443 path, cert, current config and paused Node runtime.

    Witnesses return READY/ABSENT/DRIFT; any other value is a hard HOLD.
    This experimental function is not connected to the Smite Manager menu.
    """
    witnesses = (verify_core, verify_sanaei, verify_gateway,
                 install_sanaei, install_gateway)
    if (disposable_capability is not True or type(now) is not int
            or not all(callable(fn) for fn in witnesses)):
        deny()
    fixture_scope(directory, packet_path)

    client = load("uopti_host_client", "smite-foreign-install-client.py")
    promotion = load("uopti_host_promotion", "smite-foreign-install-promotion.py")
    try:
        # Read exact private packet; NEVER log or serialize the bearer code.
        with promotion.private_directory(directory) as fd:
            raw = promotion.read_optional(fd, "foreign-install-packet.json", client)
        if raw is None:
            deny()
        packet = client.parse_packet(raw)
        if (packet.scope["panel_url"] != client.origin(expected_panel)
                or packet.scope["origin"] != client.origin(expected_foreign)
                or packet.scope["node_name"] != expected_node
                or not now < packet.expires_at <= now + 7200):
            deny()

        # Preflight witnesses run before any host stage mutation. The signed
        # fresh core is mandatory; an unknown or conflicting component HOLDs.
        if verify_core(packet.scope) is not True:
            deny()
        initial_sanaei = verify_sanaei(packet.scope)
        initial_gateway = verify_gateway(packet.scope)
        if initial_sanaei not in ("READY", "ABSENT") or initial_gateway not in ("READY", "ABSENT"):
            deny()
        if initial_gateway == "READY" and initial_sanaei != "READY":
            deny()

        with promotion.private_directory(directory) as fd:
            lock = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW |
                           os.O_NONBLOCK, 0o600, dir_fd=fd)
            try:
                client.private_file(lock)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    deny()
                locked_raw = promotion.read_optional(
                    fd, "foreign-install-packet.json", client)
                if locked_raw != raw:
                    deny()
                baseline = {
                    "schema": 1,
                    "packet_sha256": hashlib.sha256(raw).hexdigest(),
                    "scope": packet.scope,
                }
                old = promotion.read_optional(fd, JOURNAL, client)
                if old is not None:
                    current = client.decode(old)
                    if (not isinstance(current, dict)
                            or set(current) != set(baseline) | {"phase"}
                            or any(current[k] != val for k, val in baseline.items())
                            or current["phase"] not in PHASES):
                        deny()
                    phase = current["phase"]
                else:
                    phase = "CORE_VERIFIED"
                    write_journal(fd, {**baseline, "phase": phase})

                def advance(new_phase):
                    nonlocal phase
                    if PHASES.index(new_phase) < PHASES.index(phase):
                        deny()
                    write_journal(fd, {**baseline, "phase": new_phase})
                    phase = new_phase

                # Recheck observed external state while holding the lock.
                # Neither a stale journal nor a successful callback alone is
                # enough to skip stage verification.
                if verify_core(packet.scope) is not True:
                    deny()
                sanaei = verify_sanaei(packet.scope)
                gateway = verify_gateway(packet.scope)
                if sanaei not in ("READY", "ABSENT") or gateway not in ("READY", "ABSENT"):
                    deny()
                if gateway == "READY" and sanaei != "READY":
                    deny()
                if (PHASES.index(phase) >= PHASES.index("SANAEI_RO_VERIFIED")
                        and sanaei != "READY"):
                    deny()
                if (PHASES.index(phase) >= PHASES.index("GATEWAY_443_VERIFIED")
                        and gateway != "READY"):
                    deny()

                if sanaei == "ABSENT":
                    if phase != "CORE_VERIFIED":
                        # A previous action was interrupted; "absent" is
                        # ambiguous. Never reinstall or recreate blindly.
                        deny()
                    advance("SANAEI_INTENT")
                    install_sanaei(packet.scope)
                    if verify_sanaei(packet.scope) != "READY":
                        deny()
                    advance("SANAEI_RO_VERIFIED")
                elif PHASES.index(phase) < PHASES.index("SANAEI_RO_VERIFIED"):
                    advance("SANAEI_RO_VERIFIED")

                if gateway == "ABSENT":
                    if phase != "SANAEI_RO_VERIFIED":
                        deny()
                    advance("GATEWAY_INTENT")
                    install_gateway(packet.scope)
                    if verify_gateway(packet.scope) != "READY":
                        deny()
                    advance("GATEWAY_443_VERIFIED")
                elif PHASES.index(phase) < PHASES.index("GATEWAY_443_VERIFIED"):
                    advance("GATEWAY_443_VERIFIED")

                # Even a completed journal is revalidated at return.
                if (verify_core(packet.scope) is not True
                        or verify_sanaei(packet.scope) != "READY"
                        or verify_gateway(packet.scope) != "READY"
                        or phase != "GATEWAY_443_VERIFIED"):
                    deny()
                return {
                    "phase": "GATEWAY_443_VERIFIED",
                    "node_id": packet.scope["node_id"],
                    "sanaei": "READ_ONLY_VERIFIED",
                    "gateway": "EXACT_HTTPS_443_VERIFIED",
                    "identity_promoted": False,
                    "runtime_activation": "NOT_PERFORMED",
                    "connected": False,
                }
            finally:
                os.close(lock)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        deny()
