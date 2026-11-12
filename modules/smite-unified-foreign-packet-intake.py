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
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", required=True)
    parser.parse_args(argv)
    print("PANEL_FOREIGN_PACKET_INTAKE=DISPOSABLE_REHEARSAL_ONLY")
    print("REAL_HOST_CAPTURE=NOT_AUTHORIZED")
    print("NODE_ACTIVATION=NOT_PERFORMED")
    print("FOREIGN_CONNECTED=NOT_PROVEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
