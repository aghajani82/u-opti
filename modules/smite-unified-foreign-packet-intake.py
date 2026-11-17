#!/usr/bin/env python3
"""Trial-only private capture of the Panel's multiline Foreign install packet.

This is a building block for Smite Manager option 2, NOT a standalone
installer, credential redeemer, activation tool or replacement for the
existing Foreign client. The CLI exposes status ONLY; the only capture
path is an internal disposable-fixture API used by tests.

The operator copies JSON displayed by ForeignInstallDialog on the IR Panel,
pastes it into one terminal prompt on the Foreign server, and finishes with
an empty line. The future installed flow must disable TTY echo while reading
and call this admission before starting expensive host installation. The
2-hour TTL starts when the Panel *issues* the code, not at Foreign install.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import termios
import time
from urllib.parse import urlsplit


class Hold(ValueError):
    pass


def deny():
    raise Hold("Foreign installation information HOLD; request a fresh Panel code")


def client_module():
    path = Path(__file__).with_name("smite-foreign-install-client.py")
    if path.is_symlink() or not path.is_file():
        deny()
    spec = importlib.util.spec_from_file_location("foreign_operator_packet_client", path)
    if spec is None or spec.loader is None:
        deny()
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def read_multiline(reader):
    """Read until one EMPTY line; bounded; never display/copy private JSON."""
    chunks = []
    size = 0
    finished = False
    # Terminal paste tools may prepend a newline before the opening brace.
    # Do not treat that as end-of-packet: it previously left the complete
    # secret JSON queued for the U-OPTI menu and caused repeated invalid
    # selections. Only a bounded empty preamble is ignored. The packet
    # itself remains strictly parsed and requires its own blank terminator.
    preamble_blanks = 0
    started = False
    for _ in range(40):
        line = reader.readline(8194)
        if not isinstance(line, str) or not line or "\x00" in line:
            deny()
        size += len(line.encode("utf-8"))
        if size > 8192:
            deny()
        if line.rstrip("\r\n") == "":
            if not started:
                preamble_blanks += 1
                if preamble_blanks > 2:
                    deny()
                continue
            finished = True
            break
        started = True
        chunks.append(line)
    if not finished:
        deny()
    data = "".join(chunks)
    if not data or len(data.encode("utf-8")) > 8192:
        deny()
    return data


def _private_fixture(path, *, allow_existing=False):
    target = Path(path)
    if (not target.is_absolute() or ".." in target.parts
            or target.name != "foreign-install-packet.json"
            or target.parent.name != "foreign-staging"
            or target.parent.parent.name != "foreign-fixture"
            or target.parent.parent.parent.parent != Path(tempfile.gettempdir()).resolve()):
        deny()
    if not allow_existing and os.path.lexists(target):
        deny()  # The original first-write path never overwrites a packet.
    for item in (target.parent.parent.parent, target.parent.parent, target.parent):
        if item.is_symlink():
            deny()
        try:
            info = item.lstat()
        except OSError:
            deny()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            deny()
    return target



_SELECTED_ROOT_PACKET = Path(
    "/var/lib/u-opti/rc6-install-journal/foreign-staging/foreign-install-packet.json")


def _selected_root_target(path, *, allow_existing=False):
    """Exact original option-2 private root packet, no second stager.

    Both signed release approval and the ORIGINAL root-owned operation
    directory are required. This is an admission guard, not authorization
    to install a Node or activate a Panel pair.
    """
    target = Path(path)
    if (os.geteuid() != 0 or target != _SELECTED_ROOT_PACKET
            or ".." in target.parts or
            (not allow_existing and os.path.lexists(target))):
        deny()
    pairing_file = Path(__file__).with_name("smite-node-pairing.py")
    if pairing_file.is_symlink() or not pairing_file.is_file():
        deny()
    spec = importlib.util.spec_from_file_location(
        "uopti_existing_selected_release_gate", pairing_file)
    if spec is None or spec.loader is None:
        deny()
    pairing = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = pairing
    spec.loader.exec_module(pairing)
    try:
        # RC9 currently fails this immutable verified policy, so this
        # function cannot write to a host until separately released.
        pairing._require_unified_foreign_release()
        promotion_file = Path(__file__).with_name(
            "smite-foreign-install-promotion.py")
        if promotion_file.is_symlink() or not promotion_file.is_file():
            deny()
        spec = importlib.util.spec_from_file_location(
            "uopti_original_selected_private_directory", promotion_file)
        if spec is None or spec.loader is None:
            deny()
        promotion = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = promotion
        spec.loader.exec_module(promotion)
        # Existing no-follow, owner+mode 0700 directory-fd walk.
        with promotion.private_directory(target.parent):
            pass
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            RuntimeError):
        deny()
    return target


# The existing disposable reissue journal lives beside its fixture.
# The real option-2 stages instead belong to the ORIGINAL RC9 Core Journal.
# Never mistake one receipt for the other or silently reset a Node.
_SELECTED_ROOT_IDENTITY = Path(
    "/etc/u-opti/smite/identities/node-identity.json")


def _replace_private_packet(fd, name, data):
    """Original fsynced 0600 replacement under an already held private lock."""
    temporary = ".packet-renew-" + secrets.token_hex(16)
    output = os.open(temporary, os.O_WRONLY | os.O_CREAT |
                     os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(output, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def _original_core_reissue_witness(journal, owner, packet, installer_pid):
    """Read-only SAME foreign Core owner; never reparse expired bearer TTL.

    This delegates the actual Docker/Compose/Sanaei verification to the
    existing RC9 Core Journal rather than inventing a replacement witness.
    """
    record = journal.load()
    if (record.get("source") != owner.RC9_SOURCE
            or record.get("role") != "foreign"
            or record.get("foreign_resumable_version") != 1
            or record.get("state") not in ("INSTALLING", "COMMITTED")):
        deny()
    exact = journal.foreign_inputs(record)
    expected = (
        urlsplit(packet.scope["panel_url"]).hostname,
        urlsplit(packet.scope["origin"]).hostname,
        packet.scope["node_name"], packet.scope["node_id"],
        urlsplit(packet.scope["control_url"]).path,
    )
    if tuple(exact[key] for key in (
            "panel_domain", "foreign_domain", "node_name",
            "node_id", "control_path")) != expected:
        deny()
    # The expired code cannot redeem. Only the host-state witness omits
    # revalidating that OLD code's TTL; the NEW grant is checked separately.
    stage = None
    for attached in (False, True):
        try:
            stage, project = journal.foreign_resume(
                attached_sanaei=attached, installer_pid=installer_pid)
            break
        except owner.Hold:
            continue
    if (stage not in ("CORE_PENDING", "CORE_READY_TO_COMMIT",
                      "CORE_COMMITTED") or project != record.get("id")):
        deny()
    return stage


def _original_unstarted_core_packet_witness(journal, owner, files, fd, client):
    """Only a never-started RC9 Foreign Core may reissue its expired packet.

    An exact signed Panel packet was already stored, but the operator may
    have paused more than two hours *before* the original Core Journal
    began. This read-only branch uses the ORIGINAL journal's own TARGETS
    to reject any existing Smite installation and checks that not even an
    INTENT or staged secret exists. It never creates a new Core owner.
    Return False only when an existing Core journal must verify itself.
    """
    if os.path.lexists(journal.path):
        # Present (including unsafe symlinks) is never "fresh". The
        # original journal load/signature/runtime witness must decide.
        return False
    if any(os.path.lexists(journal.root / rel) for rel in owner.TARGETS):
        deny()
    for name in (
        "unified-foreign-host.lock",
        "unified-foreign-host-journal.json",
        "unified-foreign-transaction.lock",
        "unified-foreign-transaction.json",
        "foreign-install-identity.json",
        "foreign-install-promotion-prepared.json",
        "foreign-install-promotion-completed.json",
    ):
        # Missing is the ONLY allowed state. Files/symlinks/hardlinks
        # either count as committed state or are refused by read_optional.
        if files.read_optional(fd, name, client) is not None:
            deny()
    return True


def _renew_expired_owned_root(*, target, data, packet, now, client,
                             installer_pid=None):
    """Reissue a 2-hour IR Panel grant to the SAME paused Foreign owner only.

    The original RC9 Core Journal, its image/Compose/runtime witness and the
    original Identity INTENT receipt are the authorities here. This function
    never creates a new installation owner, key, promotion or Host journal.
    The selected intake already required the original signed Pairing release.
    """
    if target != _SELECTED_ROOT_PACKET:
        deny()
    core_path = Path(__file__).with_name("smite-rc6-install-journal.py")
    promotion_path = Path(__file__).with_name(
        "smite-foreign-install-promotion.py")
    if any(p.is_symlink() or not p.is_file() for p in
           (core_path, promotion_path)):
        deny()

    def existing(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            deny()
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    owner = existing("uopti_selected_original_core_renewal", core_path)
    files = existing("uopti_selected_original_promotion_renewal", promotion_path)
    try:
        with files.private_directory(target.parent) as directory:
            # Same existing enrollment.lock as the original client: a
            # competing redeem/proof cannot rotate the bearer code halfway.
            lock = os.open("enrollment.lock", os.O_RDWR | os.O_CREAT |
                           os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
            try:
                client.private_file(lock)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                previous = files.read_optional(directory, target.name, client)
                if previous is None:
                    deny()
                old = client.parse_packet(previous)
                if data == previous and now < old.expires_at:
                    return {"status": "ALREADY_STAGED_PRIVATE",
                            "node_name": packet.scope["node_name"],
                            "expires_at": packet.expires_at,
                            "connected": False}
                if (now < old.expires_at or old.scope != packet.scope
                        or old.code == packet.code
                        or not now < packet.expires_at <= now + 7200):
                    deny()
                # Once promoted or an independently signed Node identity
                # exists, the old code is irrelevant. Never reissue/rekey.
                if (os.path.lexists(_SELECTED_ROOT_IDENTITY)
                        or os.path.lexists(_SELECTED_ROOT_IDENTITY.parent /
                                           "replay-enrollment.json")
                        or files.read_optional(directory,
                            "foreign-install-promotion-prepared.json",
                            client) is not None
                        or files.read_optional(directory,
                            "foreign-install-promotion-completed.json",
                            client) is not None):
                    deny()
                intent_raw = files.read_optional(
                    directory, "unified-foreign-transaction.json", client)
                if intent_raw is not None:
                    intent = client.decode(intent_raw)
                    if intent != {
                        "schema": 2,
                        "packet_sha256": hashlib.sha256(previous).hexdigest(),
                        "expires_at": old.expires_at,
                        "scope": old.scope,
                        "node_id": old.scope["node_id"],
                        "phase": "INTENT",
                    }:
                        deny()
                staged_raw = files.read_optional(
                    directory, "foreign-install-identity.json", client)
                if staged_raw is not None:
                    staged = client.decode(staged_raw)
                    if (not isinstance(staged, dict)
                            or set(staged) != {"schema", "scope", "node_secret"}
                            or staged["schema"] != 1
                            or staged["scope"] != old.scope
                            or not isinstance(staged["node_secret"], str)
                            or len(staged["node_secret"]) != 64
                            or any(x not in "0123456789abcdef"
                                   for x in staged["node_secret"])):
                        deny()
                journal = owner.Journal()
                # An expired code *before Core ever starts* must not strand
                # the operator or demand a new Node. In that one narrow
                # case no Core owner or identity is ever minted; the only
                # write below replaces the old private bearer packet.
                if not _original_unstarted_core_packet_witness(
                        journal, owner, files, directory, client):
                    _original_core_reissue_witness(
                        journal, owner, packet, installer_pid)
                if files.read_optional(directory, target.name, client) != previous:
                    deny()
                # Replacing the original packet is the ONLY write to
                # installation state. Core/Host/Identity remain unchanged.
                _replace_private_packet(directory, target.name, data)
                return {"status": "RENEWED_PRIVATE",
                        "node_name": packet.scope["node_name"],
                        "expires_at": packet.expires_at,
                        "connected": False}
            finally:
                os.close(lock)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        deny()


def _renew_expired_disposable(*, target, data, packet, now, client):
    """Repair the existing Foreign resume path for one expired Panel grant.

    The *already existing* host-recovery journal is the owner of this scope.
    Lock against both host stage recovery and signed enrollment. Never alter
    an active grant, a different reserved Node, a published identity, or a
    journal whose preimage cannot be independently verified.

    Only the private packet is replaced atomically; the original recovery
    journal remains in place and revalidates all completed host witnesses
    when it adopts the new code on next resume. No runtime/network writes.
    """
    host = Path(__file__).with_name("smite-unified-foreign-host-recovery.py")
    promotion = Path(__file__).with_name("smite-foreign-install-promotion.py")
    if (host.is_symlink() or not host.is_file()
            or promotion.is_symlink() or not promotion.is_file()):
        deny()
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            deny()
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    journal_owner = load("foreign_existing_host_recovery_contract", host)
    files = load("foreign_existing_promotion_file_admission", promotion)
    try:
        with files.private_directory(target.parent) as directory:
            try:
                lock = os.open(journal_owner.LOCK, os.O_RDWR | os.O_NOFOLLOW |
                               os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                # Before the first host recovery stage, its owner lock does
                # not exist. Re-pasting byte-for-byte identical live input is
                # read-only/idempotent; a DIFFERENT grant is never admitted.
                old = files.read_optional(directory, target.name, client)
                if old == data and now < client.parse_packet(old).expires_at:
                    return {"status": "ALREADY_STAGED_PRIVATE",
                            "node_name": packet.scope["node_name"],
                            "expires_at": packet.expires_at, "connected": False}
                deny()
            try:
                client.private_file(lock)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                original = files.read_optional(directory, target.name, client)
                if original is None:
                    deny()
                prior = client.parse_packet(original)
                # Idempotent re-paste of the exact still-valid packet never
                # changes a file or consumes a new grant.
                if data == original and now < prior.expires_at:
                    return {"status": "ALREADY_STAGED_PRIVATE",
                            "node_name": packet.scope["node_name"],
                            "expires_at": packet.expires_at, "connected": False}

                if (prior.expires_at > now
                        or prior.scope != packet.scope
                        or prior.code == packet.code):
                    deny()
                saved = files.read_optional(directory, journal_owner.JOURNAL, client)
                if saved is None:
                    deny()
                record = client.decode(saved)
                if (not isinstance(record, dict)
                        or set(record) != {
                            "schema", "packet_sha256", "expires_at", "scope", "phase"}
                        or record["schema"] != 2
                        or type(record["expires_at"]) is not int
                        or record["expires_at"] != prior.expires_at
                        or record["scope"] != prior.scope
                        or record["phase"] not in journal_owner.PHASES
                        or record["packet_sha256"] != hashlib.sha256(original).hexdigest()):
                    deny()
                # New grants may never silently displace an enrolled,
                # promoted or already-published Node runtime identity.
                if (files.read_optional(directory,
                        "foreign-install-promotion-prepared.json", client) is not None
                        or files.read_optional(directory,
                        "foreign-install-promotion-completed.json", client) is not None):
                    deny()
                identity = files.read_optional(
                    directory, "foreign-install-identity.json", client)
                if identity is not None:
                    record_identity = client.decode(identity)
                    if (not isinstance(record_identity, dict)
                            or set(record_identity) != {
                                "schema", "scope", "node_secret"}
                            or record_identity["schema"] != 1
                            or record_identity["scope"] != packet.scope
                            or not isinstance(record_identity["node_secret"], str)
                            or len(record_identity["node_secret"]) != 64
                            or any(c not in "0123456789abcdef"
                                   for c in record_identity["node_secret"])):
                        deny()

                # Serialize with the existing enrollment client too. An
                # unknown lock or identity state is always a HOLD.
                enroll_lock = os.open("enrollment.lock", os.O_RDWR | os.O_CREAT |
                                      os.O_NOFOLLOW | os.O_NONBLOCK, 0o600,
                                      dir_fd=directory)
                try:
                    client.private_file(enroll_lock)
                    fcntl.flock(enroll_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Recheck proofs AFTER acquiring both locks. No file is
                    # trusted merely because it passed an earlier read.
                    if (files.read_optional(directory, target.name, client)
                            != original
                            or files.read_optional(
                                directory, journal_owner.JOURNAL, client) != saved
                            or files.read_optional(
                                directory, "foreign-install-identity.json", client)
                                != identity
                            or files.read_optional(
                                directory, "foreign-install-promotion-prepared.json",
                                client) is not None
                            or files.read_optional(
                                directory, "foreign-install-promotion-completed.json",
                                client) is not None):
                        deny()
                    _replace_private_packet(directory, target.name, data)
                finally:
                    os.close(enroll_lock)
                return {"status": "RENEWED_PRIVATE",
                        "node_name": packet.scope["node_name"],
                        "expires_at": packet.expires_at, "connected": False}
            finally:
                os.close(lock)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        deny()


def capture_disposable(reader, *, target, expected_panel, expected_domain,
                       expected_node, now, disposable_capability=False,
                       allow_expired_renewal=False, selected_capability=False,
                       installer_pid=None):
    """Write the exact validated packet once in a PRIVATE disposable fixture.

    No host path, overwrite, reuse of a consumed code, secret output, child
    process, network access or implicit Node activation is permitted.
    """
    if type(now) is not int:
        deny()
    if selected_capability is True and disposable_capability is False:
        target = _selected_root_target(
            target, allow_existing=allow_expired_renewal)
    elif selected_capability is False and disposable_capability is True:
        target = _private_fixture(
            target, allow_existing=allow_expired_renewal)
    else:
        deny()
    c = client_module()
    try:
        raw = read_multiline(reader)
        packet = c.parse_packet(raw)
        if (c.origin(expected_panel) != packet.scope["panel_url"]
                or c.origin(expected_domain) != packet.scope["origin"]
                or packet.scope["node_name"] != expected_node
                or not now < packet.expires_at <= now + 7200):
            deny()
        # Re-encode canonical complete source fields. No secrets in argv,
        # stdout, logs or environment. Permissions are verified via fd.
        record = c.decode(raw)
        data = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(data) > 8192:
            deny()
        if allow_expired_renewal and os.path.lexists(target):
            if selected_capability is True:
                return _renew_expired_owned_root(
                    target=target, data=data, packet=packet, now=now,
                    client=c, installer_pid=installer_pid)
            return _renew_expired_disposable(
                target=target, data=data, packet=packet, now=now, client=c)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(directory)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                deny()
            temporary = ".packet-" + secrets.token_hex(16)
            fd = os.open(temporary,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.link(temporary, target.name,
                        src_dir_fd=directory, dst_dir_fd=directory,
                        follow_symlinks=False)
                os.fsync(directory)
            finally:
                os.unlink(temporary, dir_fd=directory)
        finally:
            os.close(directory)
        return {"status": "STAGED_PRIVATE", "node_name": packet.scope["node_name"],
                "expires_at": packet.expires_at, "connected": False}
    except (OSError, UnicodeError, ValueError, TypeError, c.Hold):
        deny()



def read_hidden_tty(stream, *, ready=None):
    """Capture exactly one complete multiline paste with terminal echo off.

    The caller must provide a true controlling TTY stream, never a shell
    command-line argument or an environment variable with a bearer secret.
    All terminal flags are restored on normal exit, invalid input and Ctrl-C.
    The optional ready hook is only for an isolated PTY test harness.
    """
    try:
        fd = stream.fileno()
        if not os.isatty(fd):
            deny()
        saved = termios.tcgetattr(fd)
        hidden = saved.copy()
        hidden[3] &= ~(termios.ECHO | termios.ECHONL | termios.ECHOE | termios.ECHOK)
        termios.tcsetattr(fd, termios.TCSADRAIN, hidden)
    except (OSError, ValueError, termios.error):
        deny()
    try:
        if ready is not None:
            ready()
        return read_multiline(stream)
    finally:
        # Restoring terminal state takes priority on malformed input and
        # cancellation; never include private input in an exception.
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _capture_hidden_once(tty, *, target, now, confirm_scope, ready,
                         expected_panel=None, expected_domain=None,
                         expected_node=None, allow_expired_renewal=False,
                         selected_host=False, installer_pid=None):
    """One verified hidden paste for BOTH existing intake callers.

    Always validate the private destination and grant expiry BEFORE showing
    the nonsecret scope. Only the single original stager writes the 0600
    packet. The optional expected scope preserves independent trial tests;
    the selected one-choice caller instead uses the Panel-issued scope.
    """
    if type(now) is not int or not callable(confirm_scope):
        deny()
    if selected_host is True:
        _selected_root_target(target, allow_existing=allow_expired_renewal)
    elif selected_host is False:
        _private_fixture(target, allow_existing=allow_expired_renewal)
    else:
        deny()
    raw = read_hidden_tty(tty, ready=ready)
    packet = client_module().parse_packet(raw)
    scope = packet.scope
    if not now < packet.expires_at <= now + 7200:
        deny()
    # Legacy disposable harnesses can additionally pin their destination.
    c = client_module()
    if ((expected_panel is not None and c.origin(expected_panel) != scope["panel_url"])
            or (expected_domain is not None and c.origin(expected_domain) != scope["origin"])
            or (expected_node is not None and expected_node != scope["node_name"])):
        deny()
    if confirm_scope(dict(scope)) is not True:
        deny()
    # Reuse original no-overwrite, fsynced, 0600 stager and parser. No second
    # grant/Node identity, alternate code format, or host write is created.
    return capture_disposable(
        io.StringIO(raw + "\n"), target=target,
        expected_panel=scope["panel_url"],
        expected_domain=scope["origin"],
        expected_node=scope["node_name"],
        now=now, disposable_capability=not selected_host,
        selected_capability=selected_host, installer_pid=installer_pid,
        allow_expired_renewal=allow_expired_renewal)


def capture_disposable_hidden_tty(tty, *, confirm_scope, ready=None, **kwargs):
    """Existing disposable harness; now delegates to the same hidden intake."""
    if kwargs.get("disposable_capability") is not True:
        deny()
    return _capture_hidden_once(
        tty, target=kwargs.get("target"), now=kwargs.get("now"),
        confirm_scope=confirm_scope, ready=ready,
        expected_panel=kwargs.get("expected_panel"),
        expected_domain=kwargs.get("expected_domain"),
        expected_node=kwargs.get("expected_node"))


def capture_selected_hidden_tty(tty, *, target, now, confirm_scope,
                                ready=None, selected_host=False,
                                installer_pid=None):
    """Existing selected intake; root only after original signed release."""
    return _capture_hidden_once(
        tty, target=target, now=now, confirm_scope=confirm_scope,
        ready=ready, allow_expired_renewal=True,
        selected_host=selected_host, installer_pid=installer_pid)


def _confirm_selected_scope(tty, scope):
    # Called AFTER hidden reading restores terminal ECHO; never print code.
    print("Confirm Iran Panel:", scope["panel_url"], file=sys.stderr)
    print("Foreign Node:", scope["node_name"], file=sys.stderr)
    print("Foreign Gateway:", scope["origin"], file=sys.stderr)
    print("Node control:", scope["control_url"], file=sys.stderr)
    print("Confirm this Panel-issued Node? [y/N]: ",
          file=sys.stderr, end="", flush=True)
    return tty.readline().strip().lower() in ("y", "yes")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--capture-selected-foreign", metavar="PRIVATE_WORKSPACE")
    actions.add_argument("--capture-owned-foreign", action="store_true")
    parser.add_argument("--installer-pid", type=int)
    args = parser.parse_args(argv)
    if args.status:
        print("PANEL_FOREIGN_PACKET_INTAKE=DISPOSABLE_REHEARSAL_ONLY")
        print("REAL_HOST_CAPTURE=NOT_AUTHORIZED")
        print("NODE_ACTIVATION=NOT_PERFORMED")
        print("FOREIGN_CONNECTED=NOT_PROVEN")
        return 0
    selected_host = args.capture_owned_foreign
    target = (_SELECTED_ROOT_PACKET if selected_host else
              Path(args.capture_selected_foreign) / "foreign-fixture" /
              "foreign-staging" / "foreign-install-packet.json")
    try:
        if selected_host:
            _selected_root_target(target, allow_existing=True)
        else:
            _private_fixture(target, allow_existing=True)
        with open("/dev/tty", "r", encoding="utf-8", newline="") as tty:
            capture_selected_hidden_tty(
                tty, target=target, now=int(time.time()),
                selected_host=selected_host,
                installer_pid=args.installer_pid if selected_host else None,
                # Show the prompt only AFTER ECHO is actually disabled.
                # This is also the ready point used by the isolated PTY tests.
                ready=lambda: print(
                    "Paste Iran Panel's complete Foreign installation JSON and"
                    " finish with an empty line. Input is hidden.",
                    file=sys.stderr, flush=True),
                confirm_scope=lambda scope: _confirm_selected_scope(tty, scope))
        print("FOREIGN_PACKET=STAGED_PRIVATE")
        print("FOREIGN_CONNECTED=NOT_PROVEN")
        return 0
    except (Hold, OSError, UnicodeError, ValueError, TypeError, EOFError,
            RuntimeError):
        # Discard any queued remainder of a failed terminal paste before
        # restoring control to the Bash menu; never echo or log credentials.
        try:
            with open("/dev/tty", "r", encoding="utf-8") as tty:
                if os.isatty(tty.fileno()):
                    termios.tcflush(tty.fileno(), termios.TCIFLUSH)
        except (OSError, ValueError, termios.error):
            pass
        print("HOLD: Foreign Panel installation information not admitted",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
