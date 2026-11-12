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


def _private_fixture(path):
    target = Path(path)
    if (not target.is_absolute() or ".." in target.parts
            or target.name != "foreign-install-packet.json"
            or target.parent.name != "foreign-staging"
            or target.parent.parent.name != "foreign-fixture"
            or target.parent.parent.parent.parent != Path(tempfile.gettempdir()).resolve()):
        deny()
    if os.path.lexists(target):
        deny()  # Cannot silently rotate an existing code or a staged identity.
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


def capture_disposable(reader, *, target, expected_panel, expected_domain,
                       expected_node, now, disposable_capability=False):
    """Write the exact validated packet once in a PRIVATE disposable fixture.

    No host path, overwrite, reuse of a consumed code, secret output, child
    process, network access or implicit Node activation is permitted.
    """
    if not disposable_capability or type(now) is not int:
        deny()
    target = _private_fixture(target)
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


def capture_disposable_hidden_tty(tty, *, confirm_scope,
                                   ready=None, **kwargs):
    """Reusable single-paste operator sequence, disposable fixture ONLY.

    The callback receives only NONSECRET scope (name, Panel and Foreign
    domains, exact control URL). The operator must confirm that destination
    after terminal echo has been restored and BEFORE any private file is
    staged. This function does not redeem, run Docker or activate a Node.
    """
    if (kwargs.get("disposable_capability") is not True
            or not callable(confirm_scope)):
        deny()
    _private_fixture(kwargs.get("target"))
    raw = read_hidden_tty(tty, ready=ready)
    packet = client_module().parse_packet(raw)
    scope = dict(packet.scope)
    if confirm_scope(scope) is not True:
        deny()
    # The parser remains the single source of truth. It checks time and
    # scope again and refuses a second write to an existing private packet.
    return capture_disposable(io.StringIO(raw + "\n"), **kwargs)


def capture_selected_hidden_tty(tty, *, target, now, confirm_scope,
                                ready=None):
    """Use the existing hidden reader and exclusive 0600 stager for one paste.

    Only the operator-confirmed nonsecret scope supplies the three expected
    core fields; the same JSON is parsed a second time before staging.
    The caller's workspace must be the established 0700 disposable tree.
    No Node, Panel, Gateway or enrollment mutation is possible here.
    """
    if type(now) is not int or not callable(confirm_scope):
        deny()
    _private_fixture(target)  # Validate before accepting secret input
    raw = read_hidden_tty(tty, ready=ready)
    packet = client_module().parse_packet(raw)
    if not now < packet.expires_at <= now + 7200:
        deny()
    if confirm_scope(dict(packet.scope)) is not True:
        deny()
    return capture_disposable(
        io.StringIO(raw + "\n"), target=target,
        expected_panel=packet.scope["panel_url"],
        expected_domain=packet.scope["origin"],
        expected_node=packet.scope["node_name"],
        now=now, disposable_capability=True)


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
        _private_fixture(target)
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
