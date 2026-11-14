"""Foreign host stage recovery envelope; isolated rehearsal, no host execution.

Composes the EXISTING Smite installer stage contracts; never implements a
second Docker/Sanaei/Gateway installer. Its callbacks are injected by tests,
not by public CLI or a deployed host.

Safety property: after an interrupted side-effectful stage, NEVER rerun it
based on a journal alone. Verify observed external state first; if it is
fully READY, commit and continue; if it is ABSENT, only an explicitly
supplied, ownership-checked rollback may restore that stage to its initial
state. DRIFT always HOLDs; so does failed compensation. Existing completed
stages are reverified on EVERY retry. Never declare Connected.
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
             install_sanaei, install_gateway,
             rollback_sanaei=None, rollback_gateway=None,
             disposable_capability=False):
    """Model host stage transitions with injected witnesses and operations.

    verify_core(scope) must independently verify a signed, owned fresh Node
    paused/strict and exact image/Compose. verify_sanaei(scope) must check
    RO mount and inventory. verify_gateway(scope) must check the exact
    HTTPS/443 path, cert, current config and paused Node runtime.

    Witnesses return READY/ABSENT/DRIFT; any other value is a hard HOLD.
    Optional rollback callbacks model the ORIGINAL owner's existing private
    snapshots/rollback, not a new installer. They may be used only after
    the matching *_INTENT journal and with exact independent post-witness.
    They must return ROLLED_BACK_VERIFIED, or the journal stays in INTENT.
    The next invocation with the same option then retries that step.
    This experimental function is not connected to the Smite Manager menu.
    """
    witnesses = (verify_core, verify_sanaei, verify_gateway,
                 install_sanaei, install_gateway)
    if (disposable_capability is not True or type(now) is not int
            or not all(callable(fn) for fn in witnesses)
            or any(fn is not None and not callable(fn)
                   for fn in (rollback_sanaei, rollback_gateway))):
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
                    "schema": 2,
                    "packet_sha256": hashlib.sha256(raw).hexdigest(),
                    "expires_at": packet.expires_at,
                    "scope": packet.scope,
                }
                old = promotion.read_optional(fd, JOURNAL, client)
                if old is not None:
                    current = client.decode(old)
                    if (not isinstance(current, dict)
                            or current.get("phase") not in PHASES):
                        deny()
                    phase = current["phase"]
                    if current.get("schema") == 1:
                        legacy = {key: value for key, value in baseline.items() if key != "expires_at"}
                        legacy["schema"] = 1
                        if current != {**legacy, "phase": phase}:
                            deny()
                    elif (set(current) != set(baseline) | {"phase"}
                          or current["schema"] != 2
                          or current["scope"] != packet.scope
                          or type(current["expires_at"]) is not int):
                        deny()
                    elif current["packet_sha256"] != baseline["packet_sha256"]:
                        if current["expires_at"] > now:
                            deny()
                    elif current["expires_at"] != packet.expires_at:
                        deny()
                else:
                    phase = "CORE_VERIFIED"
                    write_journal(fd, {**baseline, "phase": phase})

                def advance(new_phase):
                    nonlocal phase
                    if PHASES.index(new_phase) < PHASES.index(phase):
                        deny()
                    write_journal(fd, {**baseline, "phase": new_phase})
                    phase = new_phase

                def compensate(intent, prior, rollback, witness):
                    """Rewind ONLY the interrupted stage, never a committed one."""
                    nonlocal phase
                    if phase != intent or rollback is None:
                        deny()
                    if verify_core(packet.scope) is not True:
                        deny()
                    if intent == "SANAEI_INTENT":
                        # No Gateway may have been configured by this stage.
                        if verify_gateway(packet.scope) != "ABSENT":
                            deny()
                    elif intent == "GATEWAY_INTENT":
                        if verify_sanaei(packet.scope) != "READY":
                            deny()
                    else:
                        deny()
                    # Ambiguous, unowned/foreign mutations are always HOLD.
                    # The callback itself must own and validate its original
                    # snapshot, no-symlink paths and target permissions.
                    if witness(packet.scope) not in ("READY", "ABSENT"):
                        deny()
                    if rollback(packet.scope) != "ROLLED_BACK_VERIFIED":
                        deny()
                    # A callback success without a fresh witness is NOT a
                    # verified rollback. Retain the durable INTENT journal.
                    if (verify_core(packet.scope) is not True
                            or witness(packet.scope) != "ABSENT"
                            or (intent == "SANAEI_INTENT" and
                                verify_gateway(packet.scope) != "ABSENT")
                            or (intent == "GATEWAY_INTENT" and
                                verify_sanaei(packet.scope) != "READY")):
                        deny()
                    write_journal(fd, {**baseline, "phase": prior})
                    phase = prior

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

                # Preserve the existing cursor when accepting a replacement
                # code for the same reserved Node after expiry.
                if old is not None and current != {**baseline, "phase": phase}:
                    advance(phase)

                if sanaei == "ABSENT":
                    if phase == "SANAEI_INTENT":
                        # Prior attempt interrupted: compensate first, then
                        # the SAME option will retry from CORE_VERIFIED.
                        compensate("SANAEI_INTENT", "CORE_VERIFIED",
                                   rollback_sanaei, verify_sanaei)
                        deny()
                    if phase != "CORE_VERIFIED":
                        deny()
                    advance("SANAEI_INTENT")
                    try:
                        install_sanaei(packet.scope)
                    except (OSError, ValueError, RuntimeError):
                        compensate("SANAEI_INTENT", "CORE_VERIFIED",
                                   rollback_sanaei, verify_sanaei)
                        deny()
                    if verify_sanaei(packet.scope) != "READY":
                        compensate("SANAEI_INTENT", "CORE_VERIFIED",
                                   rollback_sanaei, verify_sanaei)
                        deny()
                    advance("SANAEI_RO_VERIFIED")
                elif PHASES.index(phase) < PHASES.index("SANAEI_RO_VERIFIED"):
                    advance("SANAEI_RO_VERIFIED")

                if gateway == "ABSENT":
                    if phase == "GATEWAY_INTENT":
                        compensate("GATEWAY_INTENT", "SANAEI_RO_VERIFIED",
                                   rollback_gateway, verify_gateway)
                        deny()
                    if phase != "SANAEI_RO_VERIFIED":
                        deny()
                    advance("GATEWAY_INTENT")
                    try:
                        install_gateway(packet.scope)
                    except (OSError, ValueError, RuntimeError):
                        compensate("GATEWAY_INTENT", "SANAEI_RO_VERIFIED",
                                   rollback_gateway, verify_gateway)
                        deny()
                    if verify_gateway(packet.scope) != "READY":
                        compensate("GATEWAY_INTENT", "SANAEI_RO_VERIFIED",
                                   rollback_gateway, verify_gateway)
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


def rehearse_option2(*, directory, packet_path, state_path,
                     gateway_path, node_env_path, live_identity,
                     now, expected_panel, expected_foreign, expected_node,
                     verify_core, verify_sanaei, verify_gateway,
                     install_sanaei, install_gateway, transport,
                     rollback_sanaei=None, rollback_gateway=None,
                     disposable_capability=False):
    """Compose the TWO EXISTING Foreign per-stage journals in option-2 order.

    Disposable-only continuation. Never introduces a second pairing
    identity or a second Sanaei/Gateway installer. The Host journal owns
    only core/Sanaei/Gateway; the Identity journal owns code redemption,
    verified signed proof and atomic identity promotion.

    The identities/paths/transport boundary is proved BEFORE the first
    potentially mutating host callback. No real host execution is
    exposed, no foreign Node runtime is started, and Connected is NEVER
    claimed merely from a Panel redeem result.
    """
    if (disposable_capability is not True or type(now) is not int
            or not callable(transport)):
        deny()
    # Validate BOTH independent existing operation boundaries BEFORE
    # the host stage executor can install anything. The identity phase
    # has a stricter path contract, not a substitute for the host check.
    fixture_scope(directory, packet_path)
    identity = load("uopti_option2_existing_identity",
                    "smite-unified-foreign-identity-phase.py")
    try:
        identity._fixture_boundary(
            directory=directory, live_identity=live_identity,
            packet_path=packet_path, state_path=state_path,
            gateway_path=gateway_path, node_env_path=node_env_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        deny()

    # All predicates are the EXISTING signed/owned RC7 adapters. A failed
    # or interrupted Sanaei/Gateway stage is compensated only under its
    # durable HOST_INTENT checkpoint. The identity code is not consumed
    # until both host stages have been independently verified.
    host = rehearse(
        directory=directory, packet_path=packet_path, now=now,
        expected_panel=expected_panel, expected_foreign=expected_foreign,
        expected_node=expected_node, verify_core=verify_core,
        verify_sanaei=verify_sanaei, verify_gateway=verify_gateway,
        install_sanaei=install_sanaei, install_gateway=install_gateway,
        rollback_sanaei=rollback_sanaei, rollback_gateway=rollback_gateway,
        disposable_capability=True)
    if (host.get("phase") != "GATEWAY_443_VERIFIED"
            or host.get("identity_promoted") is not False
            or host.get("runtime_activation") != "NOT_PERFORMED"
            or host.get("connected") is not False):
        deny()

    # Reuse original grant client, signed HMAC proof and non-overwrite
    # identity promoter. The identity module owns its own private lock
    # and resumption journal; no additional secret or duplicate identity.
    result = identity.rehearse_transaction(
        packet_path=packet_path, state_path=state_path,
        gateway_path=gateway_path, node_env_path=node_env_path,
        directory=directory, live_identity=live_identity,
        transport=transport, now=now, disposable_capability=True)
    if (result.get("phase") != "IDENTITY_PROMOTED_OFFLINE"
            or result.get("journal") != "IDENTITY_PROMOTED_OFFLINE"
            or result.get("signed_panel_proof") != "PASS"
            or result.get("node_id") != host.get("node_id")
            or result.get("runtime_activation") != "NOT_PERFORMED"
            or result.get("activation_allowed") is not False
            or result.get("connected") is not False):
        deny()

    # Independently recheck the same retained Node and live-like host
    # witnesses after signed promotion. A post-redeem Gateway or mount
    # drift cannot silently become a successful unified install receipt.
    client = load("uopti_option2_packet_client",
                  "smite-foreign-install-client.py")
    promotion = load("uopti_option2_packet_promotion",
                     "smite-foreign-install-promotion.py")
    try:
        with promotion.private_directory(directory) as fd:
            raw = promotion.read_optional(
                fd, "foreign-install-packet.json", client)
        if raw is None:
            deny()
        packet = client.parse_packet(raw)
        if (packet.scope["node_id"] != host["node_id"]
                or packet.scope["node_name"] != expected_node
                or packet.scope["panel_url"] != client.origin(expected_panel)
                or packet.scope["origin"] != client.origin(expected_foreign)
                or verify_core(packet.scope) is not True
                or verify_sanaei(packet.scope) != "READY"
                or verify_gateway(packet.scope) != "READY"):
            deny()
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        deny()
    return {
        "phase": "FOREIGN_OPTION2_OFFLINE_READY",
        "host_journal": "GATEWAY_443_VERIFIED",
        "identity_journal": "IDENTITY_PROMOTED_OFFLINE",
        "node_id": host["node_id"],
        "sanaei": "READ_ONLY_VERIFIED",
        "gateway": "EXACT_HTTPS_443_VERIFIED",
        "signed_panel_proof": "PASS",
        "runtime_activation": "NOT_PERFORMED",
        "activation_allowed": False,
        "connected": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", required=True)
    parser.parse_args(argv)
    print("UNIFIED_FOREIGN_HOST_RECOVERY=DISPOSABLE_REHEARSAL_ONLY")
    print("HOST_STAGE_EXECUTION=NOT_AUTHORIZED")
    print("ACTIVATION_ALLOWED=NO")
    print("FOREIGN_CONNECTED=NOT_PROVEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
