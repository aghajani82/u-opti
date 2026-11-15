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

        return _execute_original_identity(
            packet, client=client, promotion=promotion, transport=transport,
            directory=private, live_identity=live, state_path=state,
            gateway_path=gateway, node_env_path=env, now=now)
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            client.Hold, promotion.Hold, gateway_plan.Hold):
        deny()


def _execute_original_identity(packet, *, client, promotion, transport,
                               directory, live_identity, state_path,
                               gateway_path, node_env_path, now):
    """Reuse the original grant client, HMAC proof and no-overwrite promoter."""
    encoded = _packet_record(packet)
    # A completed promotion means the live_identity identity exists: never
    # call enroll again; check the exact receipt and signed proof instead.
    if not os.path.lexists(live_identity):
        result = client.enroll(
            encoded, directory=directory, live_identity=live_identity,
            transport=transport, now=now)
        if result.get("status") != "enrolled":
            deny()
    promoted = promotion.promote(
        encoded, client=client, directory=directory, live_identity=live_identity,
        state_path=state_path, gateway_path=gateway_path, node_env_path=node_env_path,
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


# Selected option 2 uses only these original, root-owned managed paths.
# The private Panel packet must survive a shell interruption, unlike an
# ephemeral installer tempdir. No bearer code or secret is passed by argv.
_SELECTED_PRIVATE = Path("/var/lib/u-opti/rc6-install-journal/foreign-staging")
_SELECTED_PACKET = _SELECTED_PRIVATE / "foreign-install-packet.json"
_SELECTED_STATE = Path("/etc/u-opti/smite/state.env")
_SELECTED_GATEWAY = Path("/etc/u-opti/smite/foreign-gateway.env")
_SELECTED_NODE_ENV = Path("/opt/smite-node/.env")
_SELECTED_IDENTITY = Path("/etc/u-opti/smite/identities/node-identity.json")


def _selected_expired_packet_resume(packet, raw, *, client, promotion,
                                    directory, live_identity):
    """Read-only proof that the expired smi1 bearer already has an owner.

    An expired NEW code can never start Core/enrollment. An interrupted
    identity whose exact old private packet, stage secret and original
    INTENT/promotion receipts survive may continue using fresh signed
    Panel STATUS; the original client does not redeem an expired code.
    This neither renews a code nor creates a new Node/secret.
    """
    try:
        with promotion.private_directory(directory) as fd:
            tx_raw = promotion.read_optional(fd, _TX_JOURNAL, client)
            staged_raw = promotion.read_optional(
                fd, "foreign-install-identity.json", client)
            prepared_raw = promotion.read_optional(
                fd, "foreign-install-promotion-prepared.json", client)
            completed_raw = promotion.read_optional(
                fd, "foreign-install-promotion-completed.json", client)
        if tx_raw is None or staged_raw is None:
            deny()
        tx = client.decode(tx_raw)
        expected = {
            "schema": 2,
            "packet_sha256": hashlib.sha256(raw).hexdigest(),
            "expires_at": packet.expires_at,
            "node_id": packet.scope["node_id"],
            "scope": packet.scope,
        }
        if (not isinstance(tx, dict)
                or tx not in (
                    {**expected, "phase": "INTENT"},
                    {**expected, "phase": "IDENTITY_PROMOTED_OFFLINE"})):
            deny()
        staged = client.decode(staged_raw)
        if (not isinstance(staged, dict)
                or set(staged) != {"schema", "scope", "node_secret"}
                or staged["schema"] != 1
                or staged["scope"] != packet.scope
                or not isinstance(staged["node_secret"], str)
                or len(staged["node_secret"]) != 64
                or any(c not in "0123456789abcdef"
                       for c in staged["node_secret"])):
            deny()
        with promotion.private_directory(live_identity.parent) as fd:
            identity_raw = promotion.read_optional(
                fd, live_identity.name, client, limit=4096)
        # The ORIGINAL promoter writes its PREPARED receipt *before*
        # linking live identity. Reconstruct that exact prospective payload
        # solely from the already persisted 0600 staged secret. This is
        # read-only, never creates a key/file and never trusts a bare receipt.
        # A crash can leave PREPARED without live identity, or COMPLETED
        # before the separate transaction journal reaches PROMOTED_OFFLINE.
        payload = json.dumps({
            "version": 1,
            "node_id": packet.scope["node_id"],
            "node_secret": staged["node_secret"],
        }, sort_keys=True, separators=(",", ":")).encode("ascii")
        receipt = {
            "schema": 1, "scope": packet.scope,
            "destination": str(live_identity),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        if identity_raw is not None and identity_raw != payload:
            deny()
        if prepared_raw is not None:
            if client.decode(prepared_raw) != receipt:
                deny()
        elif identity_raw is not None:
            # The original promoter must write PREPARED first.
            deny()
        if completed_raw is not None:
            if (identity_raw is None or prepared_raw is None
                    or client.decode(completed_raw) !=
                    {**receipt, "status": "completed"}):
                deny()
        if tx["phase"] == "IDENTITY_PROMOTED_OFFLINE":
            if completed_raw is None or identity_raw is None:
                deny()
        # A valid COMPLETED receipt with INTENT means a crash happened
        # between two original fsynced journals. Resume may finish that
        # journal only after a fresh signed Panel STATUS proof.
        return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        deny()


def _selected_option2_boundary(*, packet_path, state_path, gateway_path,
                               node_env_path, directory, live_identity,
                               installer_pid):
    """Fail closed on the REAL root before any identity journal or network.

    The original pairing release gate is the single authorization source.
    Current RC9 has activation_allowed=false, so this path refuses BEFORE
    any redeem, secret staging or host change. No environment flag or test
    callback may authorize a real host.
    """
    if (os.geteuid() != 0
            or type(installer_pid) is not int or installer_pid <= 1
            or tuple(map(Path, (packet_path, state_path, gateway_path,
                                node_env_path, directory, live_identity)))
            != (_SELECTED_PACKET, _SELECTED_STATE, _SELECTED_GATEWAY,
                _SELECTED_NODE_ENV, _SELECTED_PRIVATE, _SELECTED_IDENTITY)):
        deny()
    for name in ("smite-node-pairing.py", "smite-rc6-install-journal.py",
                 "smite-unified-foreign-gateway-plan.py"):
        path = Path(__file__).with_name(name)
        if path.is_symlink() or not path.is_file():
            deny()
    pairing = load("uopti_selected_existing_pairing", "smite-node-pairing.py")
    core = load("uopti_selected_existing_core_owner", "smite-rc6-install-journal.py")
    plan = load("uopti_selected_existing_gateway", "smite-unified-foreign-gateway-plan.py")
    client = load("uopti_selected_existing_grant", "smite-foreign-install-client.py")
    promotion = load("uopti_selected_existing_promoter", "smite-foreign-install-promotion.py")
    try:
        # Same signed two-image release policy as original Pairing activation.
        pairing._require_unified_foreign_release()
        with promotion.private_directory(_SELECTED_PRIVATE) as fd:
            raw = promotion.read_optional(
                fd, "foreign-install-packet.json", client)
        if raw is None:
            deny()
        packet = client.parse_packet(raw)
        scope = packet.scope
        # The Panel grant's two-hour TTL applies to REDEMPTION, not to
        # continued use of an already staged, scope-bound identity.
        # An expired grant without an original INTENT+staged secret is HOLD.
        import time
        expired = int(time.time()) >= packet.expires_at
        if expired:
            _selected_expired_packet_resume(
                packet, raw, client=client, promotion=promotion,
                directory=_SELECTED_PRIVATE,
                live_identity=_SELECTED_IDENTITY)
        owner = core.Journal()
        if expired:
            # Original foreign_resume(None) still proves current immutable
            # Docker/Compose/paused+strict/Sanaei RO runtime. Scope MUST be
            # matched separately against the original Core's saved 5-tuple.
            record = owner.load()
            exact = owner.foreign_inputs(record)
            expected = (
                urlsplit(scope["panel_url"]).hostname,
                urlsplit(scope["origin"]).hostname,
                scope["node_name"], scope["node_id"],
                urlsplit(scope["control_url"]).path)
            if tuple(exact[key] for key in (
                    "panel_domain", "foreign_domain", "node_name",
                    "node_id", "control_path")) != expected:
                deny()
        stage, _project = owner.foreign_resume(
            None if expired else str(_SELECTED_PACKET),
            attached_sanaei=True, installer_pid=installer_pid)
        if stage != "CORE_COMMITTED":
            deny()
        control = plan.admit(packet_path=_SELECTED_PACKET,
                             state_path=_SELECTED_STATE,
                             gateway_state_path=_SELECTED_GATEWAY)
        pairing._require_no_active_engine_overlays()
        current = pairing.state_values()
        panel, foreign, url = pairing._foreign_gateway_preflight(
            current, review_unified_trial=True)
        if (control != urlsplit(scope["control_url"]).path
                or scope["control_url"] != url
                or urlsplit(scope["panel_url"]).hostname != panel
                or urlsplit(scope["origin"]).hostname != foreign
                or scope["node_name"] != current.get("SMITE_NODE_NAME")):
            deny()
        promotion.verify_gateway(
            packet, state_path=_SELECTED_STATE, gateway_path=_SELECTED_GATEWAY,
            node_env_path=_SELECTED_NODE_ENV, client=client)
        # No untrusted staging directory/symlink can be created by this
        # identity transaction: the original owner must have prepared it.
        with promotion.private_directory(_SELECTED_IDENTITY.parent):
            pass
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            RuntimeError):
        deny()


def rehearse_transaction(*, packet_path, state_path, gateway_path,
                         node_env_path, directory, live_identity, transport,
                         now, disposable_capability=False,
                         selected_capability=False, installer_pid=None):
    """Run existing grant/promote steps once with a crash-recoverable lock.

    The production CLI provides no entry to this function. The operation
    journal only records INTENT/IDENTITY_PROMOTED_OFFLINE, never Connected.
    A replacement code after expiry must retain the exact scope and staged
    key. Re-running a completed journal *still* checks
    fresh signed proof through the existing promotion module.
    """
    if (not callable(transport) or type(now) is not int):
        deny()
    if selected_capability is True:
        if disposable_capability is True:
            deny()
        _selected_option2_boundary(
            directory=directory, live_identity=live_identity,
            packet_path=packet_path, state_path=state_path,
            gateway_path=gateway_path, node_env_path=node_env_path,
            installer_pid=installer_pid)
    elif disposable_capability is True and selected_capability is False:
        _fixture_boundary(
            directory=directory, live_identity=live_identity,
            packet_path=packet_path, state_path=state_path,
            gateway_path=gateway_path, node_env_path=node_env_path)
    else:
        deny()
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
                if selected_capability is True:
                    # The same transaction/lock/receipts, with the original
                    # client and promoter (real TLS/443) after the reviewed
                    # release and exact root boundary. No runtime activation.
                    result = _execute_original_identity(
                        packet, client=client, promotion=promotion,
                        transport=transport, directory=directory,
                        live_identity=live_identity, state_path=state_path,
                        gateway_path=gateway_path,
                        node_env_path=node_env_path, now=now)
                else:
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


def selected_option2_transaction(installer_pid):
    """The original transaction selected by option 2, never manual Pairing.

    The CLI supplies only a process lease. All managed paths are fixed here,
    all credentials stay in the existing private 0600 packet/staged secret,
    and the original signed release gate independently decides admission.
    """
    import time
    client = load("uopti_selected_tls_client", "smite-foreign-install-client.py")
    return rehearse_transaction(
        packet_path=_SELECTED_PACKET, state_path=_SELECTED_STATE,
        gateway_path=_SELECTED_GATEWAY, node_env_path=_SELECTED_NODE_ENV,
        directory=_SELECTED_PRIVATE, live_identity=_SELECTED_IDENTITY,
        transport=client.post, now=int(time.time()),
        selected_capability=True, installer_pid=installer_pid)


def selected_option2_activate(installer_pid):
    """Finish the ORIGINAL selected Foreign install with original Pairing.

    This adapter does not create a key, a new Node, new Nginx paths, another
    install journal or a second activation implementation. The previous
    signed-identity transaction independently rechecks its original Core,
    immutable Panel scope, HTTPS/443 Gateway and HMAC proof before any
    runtime change. Existing Pairing owns the signed Node recreation,
    dual-direction Panel check-in and verified paused rollback.
    """
    result = selected_option2_transaction(installer_pid)
    if (result.get("journal") != "IDENTITY_PROMOTED_OFFLINE"
            or result.get("signed_panel_proof") != "PASS"
            or result.get("runtime_activation") != "NOT_PERFORMED"
            or result.get("connected") is not False):
        deny()
    client = load("uopti_selected_activation_packet_client",
                  "smite-foreign-install-client.py")
    promotion = load("uopti_selected_activation_promotion",
                     "smite-foreign-install-promotion.py")
    pairing = load("uopti_selected_activation_original_pairing",
                   "smite-node-pairing.py")
    try:
        # No one-time bearer code appears in the activation call or argv.
        with promotion.private_directory(_SELECTED_PRIVATE) as folder:
            raw = promotion.read_optional(
                folder, "foreign-install-packet.json", client)
            prepared = promotion.read_optional(
                folder, "foreign-install-promotion-prepared.json", client)
            completed = promotion.read_optional(
                folder, "foreign-install-promotion-completed.json", client)
            receipt_raw = promotion.read_optional(
                folder, _TX_JOURNAL, client)
        if None in (raw, prepared, completed, receipt_raw):
            deny()
        packet = client.parse_packet(raw)
        identity = pairing._identity_record()
        if (identity[0] != packet.scope["node_id"]
                or result["node_id"] != identity[0]):
            deny()
        # The SAME original promotion and transaction receipts must remain
        # present and agree; never adopt an unowned or swapped live identity.
        promoted = client.decode(completed)
        expected_prepared = client.decode(prepared)
        journal = client.decode(receipt_raw)
        if (promoted != {**expected_prepared, "status": "completed"}
                or expected_prepared.get("scope") != packet.scope
                or expected_prepared.get("destination") !=
                   str(_SELECTED_IDENTITY)
                or journal.get("phase") != "IDENTITY_PROMOTED_OFFLINE"
                or journal.get("scope") != packet.scope
                or journal.get("packet_sha256") !=
                   hashlib.sha256(raw).hexdigest()
                or journal.get("node_id") != identity[0]):
            deny()
        # The transaction and original promoter signed their own state,
        # but the retained live identity must STILL be the exact bytes
        # written by that promoter at this final activation boundary.
        # Never activate a changed/rotated secret, a symlink, hardlink,
        # missing identity or a receipt with a detached SHA-256.
        with promotion.private_directory(_SELECTED_IDENTITY.parent) as folder:
            live_raw = promotion.read_optional(
                folder, _SELECTED_IDENTITY.name, client, limit=4096)
        original_payload = json.dumps({
            "version": 1, "node_id": identity[0],
            "node_secret": identity[1],
        }, sort_keys=True, separators=(",", ":")).encode("ascii")
        if (live_raw != original_payload
                or expected_prepared.get("sha256") !=
                   hashlib.sha256(original_payload).hexdigest()):
            deny()
        pairing._require_unified_foreign_release()
        # There is NO alternative activation: original Pairing verifies
        # paused/strict RO-Sanaei and exact compose/digest, performs signed
        # check-in both ways, then re-proves the same identity/replay.
        # On failure it owns the signed->paused stage-local compensation.
        pairing.activate_foreign_node_field_trial(
            reviewed_unified_trial=True)
        return {"status": "SIGNED_BIDIRECTIONAL_CONNECTED",
                "node_id": identity[0]}
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            RuntimeError, pairing.WizardHold):
        deny()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--selected-foreign", action="store_true")
    mode.add_argument("--activate-selected-foreign", action="store_true")
    mode.add_argument("--verify-owned-expired-resume", action="store_true")
    parser.add_argument("--installer-pid", type=int)
    args = parser.parse_args(argv)
    if args.status:
        print("UNIFIED_FOREIGN_IDENTITY_PHASE=REHEARSAL_ONLY")
        print("PRODUCTION_REDEEM_AND_PROMOTION=NOT_AUTHORIZED")
        print("NODE_RUNTIME=UNCHANGED")
        print("FOREIGN_CONNECTED=NOT_PROVEN")
        return 0
    try:
        if args.verify_owned_expired_resume:
            # NO host operation, redeem or Docker. Only the signed release
            # and exact prior staged INTENT allow reuse of an expired code.
            pairing = load("uopti_expired_existing_release",
                           "smite-node-pairing.py")
            pairing._require_unified_foreign_release()
            client = load("uopti_expired_existing_client",
                          "smite-foreign-install-client.py")
            promotion = load("uopti_expired_existing_promotion",
                             "smite-foreign-install-promotion.py")
            if os.geteuid() != 0:
                deny()
            with promotion.private_directory(_SELECTED_PRIVATE) as folder:
                raw = promotion.read_optional(
                    folder, "foreign-install-packet.json", client)
            if raw is None:
                deny()
            packet = client.parse_packet(raw)
            import time
            if int(time.time()) < packet.expires_at:
                deny()
            _selected_expired_packet_resume(
                packet, raw, client=client, promotion=promotion,
                directory=_SELECTED_PRIVATE, live_identity=_SELECTED_IDENTITY)
            print("FOREIGN_PACKET=REUSED_EXPIRED_OWNED_IDENTITY")
            return 0
        if args.activate_selected_foreign:
            activation = selected_option2_activate(args.installer_pid)
            if activation.get("status") != "SIGNED_BIDIRECTIONAL_CONNECTED":
                deny()
            print("FOREIGN_CONNECTED=SIGNED_BIDIRECTIONAL_VERIFIED")
            return 0
        result = selected_option2_transaction(args.installer_pid)
        if (result.get("phase") != "IDENTITY_PROMOTED_OFFLINE"
                or result.get("journal") != "IDENTITY_PROMOTED_OFFLINE"
                or result.get("signed_panel_proof") != "PASS"
                or result.get("runtime_activation") != "NOT_PERFORMED"
                or result.get("connected") is not False):
            deny()
    except (Hold, OSError, ValueError, TypeError, KeyError, AttributeError,
            RuntimeError):
        print("UNIFIED_FOREIGN_IDENTITY=HOLD_RELEASE_OR_ORIGINAL_JOURNAL",
              file=sys.stderr)
        print("FOREIGN_CONNECTED=NOT_PROVEN", file=sys.stderr)
        return 2
    print("UNIFIED_FOREIGN_IDENTITY=SIGNED_PROOF_RETAINED_NOT_ACTIVATED")
    print("FOREIGN_CONNECTED=NOT_PROVEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
