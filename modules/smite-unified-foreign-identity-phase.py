#!/usr/bin/env python3
"""Trial Foreign grant->signed proof->no-overwrite identity composition.

REHEARSAL ONLY. No production CLI to redeem or promote. This composes the
existing client, Gateway admission, and promotion helpers, rather than
introducing new registration/key-generation logic. Production menu option 2
must NOT call this before the unified trial image activation gate and complete
recovery journal have been independently reviewed.

The only command-line action is an inert status description. The Python
rehearsal entry requires an explicit disposable-root capability and injected
transport; it refuses the production identity and state paths. No Docker,
Nginx, systemd, FRP, XHTTP, Sanaei, replay or runtime activation is performed.
"""
from __future__ import annotations

import argparse
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
from urllib.parse import urlsplit


class Hold(ValueError):
    """No exceptions expose code or persisted node secret."""


def deny():
    raise Hold("Unified Foreign identity admission HOLD; retain private state")


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename))
    if spec is None or spec.loader is None:
        deny()
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj


def _packet_record(packet):
    # Reconstruct the exact, already-validated logical content in memory.
    # Never add a code to argv, environment, stdout, a journal or Docker.
    return json.dumps({
        "protocol": "smi1",
        "panel_url": packet.scope["panel_url"],
        "node_id": packet.scope["node_id"],
        "node_name": packet.scope["node_name"],
        "origin": packet.scope["origin"],
        "control_url": packet.scope["control_url"],
        "installation_code": packet.code,
        "expires_at": packet.expires_at,
    }, separators=(",", ":"))


def rehearse(*, packet_path, state_path, gateway_path, node_env_path,
             directory, live_identity, transport, now, disposable_capability=False):
    """Exercise original grant client and promotion in an isolated fixture.

    Transport is injected intentionally; there is no default network access.
    Root / and the original host identity paths are not admitted even if
    a caller accidentally imports this helper from the live installer.
    """
    if (not disposable_capability or not callable(transport)
            or type(now) is not int):
        deny()
    private = Path(directory)
    live = Path(live_identity)
    packet_file = Path(packet_path)
    state = Path(state_path)
    gateway = Path(gateway_path)
    env = Path(node_env_path)
    paths = (private, live, packet_file, state, gateway, env)
    if any(not p.is_absolute() or '..' in p.parts for p in paths):
        deny()
    # Require all candidate paths to share one non-root disposable parent.
    if not (private.parent == live.parent == state.parent == gateway.parent
            == env.parent == packet_file.parent.parent
            and private.name == "foreign-staging"
            and packet_file.parent == private
            and live.name == "node-identity.json"
            and live.parent.name == "foreign-fixture"
            and state.name == "state.env"
            and gateway.name == "foreign-gateway.env"
            and env.name == "node.env"):
        deny()
    if live.parent == Path("/"):
        deny()
    # Enforce an OS temporary directory nested exactly as:
    # <tempfile.gettempdir()>/<private-tmpdir>/foreign-fixture.
    # Merely naming an arbitrary host path "foreign-fixture" is not a grant
    # to stage a new identity under /etc, /var, /root or an active project.
    top = Path(tempfile.gettempdir()).resolve()
    if live.parent.parent.parent != top:
        deny()
    for parent in (live.parent.parent, live.parent):
        if parent.is_symlink() or not parent.is_dir():
            deny()
        info = parent.stat()
        if (info.st_uid != os.geteuid()
                or not stat.S_ISDIR(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o700):
            deny()

    client = load("uopti_unified_client_phase", "smite-foreign-install-client.py")
    promotion = load("uopti_unified_promotion_phase", "smite-foreign-install-promotion.py")
    gateway_plan = load("uopti_unified_gateway_phase", "smite-unified-foreign-gateway-plan.py")
    try:
        packet = gateway_plan.private_packet(packet_file, client, promotion)
        # Both preflights happen BEFORE the one-time code can be consumed.
        admitted = gateway_plan.admit(
            packet_path=packet_file, state_path=state,
            gateway_state_path=gateway)
        if admitted != urlsplit(packet.scope["control_url"]).path:
            deny()
        promotion.verify_gateway(
            packet, state_path=state, gateway_path=gateway,
            node_env_path=env, client=client)

        encoded = _packet_record(packet)
        # A completed promotion means the live identity exists: never
        # call enroll again; check the exact receipt and signed proof instead.
        if not os.path.lexists(live):
            result = client.enroll(
                encoded, directory=private, live_identity=live,
                transport=transport, now=now)
            if result.get("status") != "enrolled":
                deny()
        promoted = promotion.promote(
            encoded, client=client, directory=private, live_identity=live,
            state_path=state, gateway_path=gateway, node_env_path=env,
            transport=transport, now=now)
        if (promoted.get("status") != "identity_promoted"
                or promoted.get("node_id") != packet.scope["node_id"]
                or promoted.get("runtime_activation") != "not_performed"):
            deny()
        return {
            "phase": "IDENTITY_PROMOTED_OFFLINE",
            "node_id": packet.scope["node_id"],
            "signed_panel_proof": "PASS",
            "runtime_activation": "NOT_PERFORMED",
            "connected": False,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            client.Hold, promotion.Hold, gateway_plan.Hold):
        deny()


# The pre-existing enrollment and promotion modules already own their
# credential/identity receipts. This is ONLY an operation-level interruption
# marker and lock; it must never become another source of truth for identity.
_TX_LOCK = "unified-foreign-transaction.lock"
_TX_JOURNAL = "unified-foreign-transaction.json"


def _fixture_boundary(*, directory, live_identity, packet_path,
                      state_path, gateway_path, node_env_path):
    """Repeat the exact disposable root restriction BEFORE creating a lock."""
    private, live = Path(directory), Path(live_identity)
    packet = Path(packet_path)
    paths = [private, live, packet, Path(state_path),
             Path(gateway_path), Path(node_env_path)]
    if any(not p.is_absolute() or ".." in p.parts for p in paths):
        deny()
    if (private.name != "foreign-staging"
            or live.name != "node-identity.json"
            or private.parent != live.parent
            or private.parent.name != "foreign-fixture"
            or packet != private / "foreign-install-packet.json"
            or Path(state_path) != live.parent / "state.env"
            or Path(gateway_path) != live.parent / "foreign-gateway.env"
            or Path(node_env_path) != live.parent / "node.env"
            or live.parent.parent.parent != Path(tempfile.gettempdir()).resolve()):
        deny()
    for folder in (live.parent.parent, live.parent, private):
        if folder.is_symlink() or not folder.is_dir():
            deny()
        status = folder.stat()
        if (status.st_uid != os.geteuid()
                or not stat.S_ISDIR(status.st_mode)
                or stat.S_IMODE(status.st_mode) != 0o700):
            deny()


def _write_journal_once_locked(fd, record):
    """Atomic+fsynced journal update; no credentials, no identity mutation."""
    data = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("ascii")
    temp = ".unified-journal-" + secrets.token_hex(16)
    handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=fd)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, _TX_JOURNAL, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temp, dir_fd=fd)
        except FileNotFoundError:
            pass


def rehearse_transaction(*, packet_path, state_path, gateway_path,
                         node_env_path, directory, live_identity, transport,
                         now, disposable_capability=False):
    """Run existing grant/promote steps once with a crash-recoverable lock.

    The production CLI provides no entry to this function. The operation
    journal only records INTENT/IDENTITY_PROMOTED_OFFLINE, never Connected.
    A replacement code after expiry must retain the exact scope and staged
    key. Re-running a completed journal *still* checks
    fresh signed proof through the existing promotion module.
    """
    if (not disposable_capability or not callable(transport)
            or type(now) is not int):
        deny()
    _fixture_boundary(
        directory=directory, live_identity=live_identity,
        packet_path=packet_path, state_path=state_path,
        gateway_path=gateway_path, node_env_path=node_env_path)
    client = load("uopti_journal_client", "smite-foreign-install-client.py")
    promotion = load("uopti_journal_promotion", "smite-foreign-install-promotion.py")
    gateway_plan = load("uopti_journal_gateway", "smite-unified-foreign-gateway-plan.py")

    # Validate the exact signed Panel scope and the already prepared
    # Gateway/Node before committing INTENT or consuming a one-use code.
    try:
        packet = gateway_plan.private_packet(packet_path, client, promotion)
        gateway_plan.admit(
            packet_path=packet_path, state_path=state_path,
            gateway_state_path=gateway_path)
        promotion.verify_gateway(
            packet, state_path=state_path, gateway_path=gateway_path,
            node_env_path=node_env_path, client=client)
        with promotion.private_directory(directory) as fd:
            lock = os.open(_TX_LOCK, os.O_RDWR | os.O_CREAT |
                           os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=fd)
            try:
                client.private_file(lock)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    deny()
                # Verify exact raw packet under the transaction lock,
                # not merely the parsed scope. Different code with the
                # same Node/domain must never be silently adopted.
                raw = promotion.read_optional(
                    fd, "foreign-install-packet.json", client)
                if raw is None or client.parse_packet(raw) != packet:
                    deny()
                fingerprint = hashlib.sha256(raw).hexdigest()
                expected = {
                    "schema": 2,
                    "packet_sha256": fingerprint,
                    "expires_at": packet.expires_at,
                    "node_id": packet.scope["node_id"],
                    "scope": packet.scope,
                }
                previous = promotion.read_optional(fd, _TX_JOURNAL, client)
                if previous is not None:
                    journal = client.decode(previous)
                    phase = journal.get("phase")
                    if phase not in ("INTENT", "IDENTITY_PROMOTED_OFFLINE"):
                        deny()
                    if journal.get("schema") == 1:
                        legacy = {key: value for key, value in expected.items() if key != "expires_at"}
                        legacy["schema"] = 1
                        if journal != {**legacy, "phase": phase}:
                            deny()
                    elif (set(journal) != set(expected) | {"phase"}
                          or journal["schema"] != 2 or journal["scope"] != expected["scope"]
                          or journal["node_id"] != expected["node_id"]
                          or type(journal["expires_at"]) is not int):
                        deny()
                    elif journal["packet_sha256"] != fingerprint:
                        if (phase != "INTENT" or os.path.lexists(live_identity)
                                or journal["expires_at"] > now
                                or not now < packet.expires_at <= now + 7200):
                            deny()
                    elif journal["expires_at"] != packet.expires_at:
                        deny()
                elif not now < packet.expires_at <= now + 7200:
                    # Do not pin an expired first packet to a new transaction.
                    deny()
                if previous is None or phase == "INTENT":
                    _write_journal_once_locked(fd, {**expected, "phase": "INTENT"})
                # On lost ACK, process interruption or incomplete
                # promotion the existing client and promoter reconcile
                # with their *original* key, signed HMAC proof and
                # PREPARED/COMPLETED receipts.
                result = rehearse(
                    packet_path=packet_path, state_path=state_path,
                    gateway_path=gateway_path, node_env_path=node_env_path,
                    directory=directory, live_identity=live_identity,
                    transport=transport, now=now,
                    disposable_capability=True)
                if (result.get("phase") != "IDENTITY_PROMOTED_OFFLINE"
                        or result.get("connected") is not False):
                    deny()
                _write_journal_once_locked(
                    fd, {**expected, "phase": "IDENTITY_PROMOTED_OFFLINE"})
                return {
                    **result,
                    "journal": "IDENTITY_PROMOTED_OFFLINE",
                    "activation_allowed": False,
                }
            finally:
                os.close(lock)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        deny()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", required=True)
    parser.parse_args(argv)
    print("UNIFIED_FOREIGN_IDENTITY_PHASE=REHEARSAL_ONLY")
    print("PRODUCTION_REDEEM_AND_PROMOTION=NOT_AUTHORIZED")
    print("NODE_RUNTIME=UNCHANGED")
    print("FOREIGN_CONNECTED=NOT_PROVEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
