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
    for _ in range(40):
        line = reader.readline(8194)
        if not isinstance(line, str) or not line or "\x00" in line:
            deny()
        size += len(line.encode("utf-8"))
        if size > 8192:
            deny()
        if line.rstrip("\r\n") == "":
            finished = True
            break
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
                    temporary = ".packet-renew-" + secrets.token_hex(16)
                    output = os.open(temporary, os.O_WRONLY | os.O_CREAT |
                                     os.O_EXCL | os.O_NOFOLLOW, 0o600,
                                     dir_fd=directory)
                    try:
                        with os.fdopen(output, "wb") as stream:
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temporary, target.name, src_dir_fd=directory,
                                   dst_dir_fd=directory)
                        os.fsync(directory)
                    finally:
                        try:
                            os.unlink(temporary, dir_fd=directory)
                        except FileNotFoundError:
                            pass
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
                       allow_expired_renewal=False):
    """Write the exact validated packet once in a PRIVATE disposable fixture.

    No host path, overwrite, reuse of a consumed code, secret output, child
    process, network access or implicit Node activation is permitted.
    """
    if not disposable_capability or type(now) is not int:
        deny()
    target = _private_fixture(target, allow_existing=allow_expired_renewal)
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
                         expected_node=None, allow_expired_renewal=False):
    """One verified hidden paste for BOTH existing intake callers.

    Always validate the private destination and grant expiry BEFORE showing
    the nonsecret scope. Only the single original stager writes the 0600
    packet. The optional expected scope preserves independent trial tests;
    the selected one-choice caller instead uses the Panel-issued scope.
    """
    if type(now) is not int or not callable(confirm_scope):
        deny()
    _private_fixture(target, allow_existing=allow_expired_renewal)
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
        now=now, disposable_capability=True,
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
                                ready=None):
    """Existing selected option-2 intake using the SAME hidden/staging path."""
    return _capture_hidden_once(
        tty, target=target, now=now, confirm_scope=confirm_scope,
        ready=ready, allow_expired_renewal=True)


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
    args = parser.parse_args(argv)
    if args.status:
        print("PANEL_FOREIGN_PACKET_INTAKE=DISPOSABLE_REHEARSAL_ONLY")
        print("REAL_HOST_CAPTURE=NOT_AUTHORIZED")
        print("NODE_ACTIVATION=NOT_PERFORMED")
        print("FOREIGN_CONNECTED=NOT_PROVEN")
        return 0
    target = (Path(args.capture_selected_foreign) / "foreign-fixture" /
              "foreign-staging" / "foreign-install-packet.json")
    try:
        _private_fixture(target, allow_existing=True)
        print("Paste Iran Panel's complete Foreign installation JSON and"
              " finish with an empty line. Input is hidden.",
              file=sys.stderr, flush=True)
        with open("/dev/tty", "r", encoding="utf-8", newline="") as tty:
            capture_selected_hidden_tty(
                tty, target=target, now=int(time.time()),
                confirm_scope=lambda scope: _confirm_selected_scope(tty, scope))
        print("FOREIGN_PACKET=STAGED_PRIVATE")
        print("FOREIGN_CONNECTED=NOT_PROVEN")
        return 0
    except (Hold, OSError, UnicodeError, ValueError, TypeError, EOFError):
        print("HOLD: Foreign Panel installation information not admitted",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
