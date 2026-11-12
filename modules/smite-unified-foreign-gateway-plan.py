#!/usr/bin/env python3
"""Read-only, exact Panel-issued Foreign Gateway control-path admission.

Used ONLY when the opt-in unified Foreign coordinator supplies a private
one-use installation packet. Never generates a replacement control path,
edits a file, activates a Node, imports identity, or contacts a network.
Outputs only /smite-node/<32 hex>, NEVER the credential.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import urlsplit


class Hold(ValueError):
    pass


def deny():
    raise Hold("Foreign Gateway unified packet admission HOLD")


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename))
    if spec is None or spec.loader is None:
        deny()
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj


def private_packet(path, client, promotion):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or path.name != 'foreign-install-packet.json':
        deny()
    try:
        with promotion.private_directory(path.parent) as folder:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
            try:
                client.private_file(fd)
                raw = os.read(fd, 8193)
                if len(raw) > 8192:
                    deny()
                return client.parse_packet(raw)
            finally:
                os.close(fd)
    except (OSError, ValueError):
        deny()


def safe_site(path):
    """Optional existing Nginx site, read only; deny ambiguous control paths."""
    if path is None:
        return None
    site = Path(path)
    if not site.is_absolute() or '..' in site.parts:
        deny()
    try:
        # Reject symlink ancestors to prevent a fake "absent site" or
        # surprise alternate vhost. A missing Nginx directory is acceptable
        # on a FRESH host; the later installer will prepare it separately.
        for parent in reversed(site.parents):
            if parent == Path('/'):
                continue
            if parent.is_symlink():
                deny()
            if parent.exists():
                info = parent.lstat()
                if (not stat.S_ISDIR(info.st_mode)
                        or info.st_mode & 0o022):
                    deny()
        # The ordinary gateway renderer selects /etc/nginx/sites-available,
        # including the shared 3xui-<domain> server. Keep this helper inert.
        if not site.exists() and not site.is_symlink():
            return None
        info = site.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or info.st_mode & 0o022 or info.st_size > 262144):
            deny()
        fd = os.open(site, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            if os.fstat(handle.fileno()).st_ino != info.st_ino:
                deny()
            raw = handle.read(262145)
        if len(raw) > 262144:
            deny()
        return raw.decode('utf-8')
    except (OSError, UnicodeError):
        deny()


def admit(*, packet_path, state_path, gateway_state_path=None, site_path=None):
    client = load_module('uopti_unified_foreign_client', 'smite-foreign-install-client.py')
    promotion = load_module('uopti_unified_foreign_promotion', 'smite-foreign-install-promotion.py')
    packet = private_packet(packet_path, client, promotion)
    state = promotion.read_env(state_path)
    scope = packet.scope
    panel = urlsplit(scope['panel_url']).hostname
    foreign = urlsplit(scope['origin']).hostname
    path = urlsplit(scope['control_url']).path
    if (state.get('SMITE_ROLE') != 'foreign'
            or state.get('SMITE_MANAGED_VERSION') != '2.0.0-rc.7'
            or state.get('SMITE_CONNECTION_MODE') != 'standard'
            or state.get('SMITE_PANEL_DOMAIN') != panel
            or state.get('SMITE_FOREIGN_DOMAIN') != foreign
            or state.get('SMITE_NODE_NAME') != scope['node_name']
            or not re.fullmatch(r'/smite-node/[0-9a-f]{32}', path)):
        deny()

    if gateway_state_path is not None:
        gateway_file = Path(gateway_state_path)
        if gateway_file.exists() or gateway_file.is_symlink():
            gateway = promotion.read_env(gateway_file)
            if (gateway.get('SMITE_FOREIGN_GATEWAY_DOMAIN') != foreign
                    or gateway.get('SMITE_FOREIGN_PANEL_DOMAIN') != panel
                    or gateway.get('SMITE_FOREIGN_CONTROL_PATH') != path
                    or gateway.get('SMITE_FOREIGN_GATEWAY_MODE') != 'https-control-path'
                    or gateway.get('SMITE_FOREIGN_GATEWAY_PUBLIC_PORT') != '443'):
                deny()

    site = safe_site(site_path)
    if site is not None:
        # Existing 3xUI, FRP and WSS location blocks are preserved; an
        # unrelated/stale Smite control prefix must not be overwritten.
        matches = re.findall(
            r'(?m)^\s*location\s+\^~\s+(/smite-node/[^\s{]+)/\s*\{', site)
        if matches and (len(matches) != 1 or matches[0] != path):
            deny()
        begin = site.count('# BEGIN U-OPTI SMITE FOREIGN CONTROL')
        end = site.count('# END U-OPTI SMITE FOREIGN CONTROL')
        if begin != end or begin > 1 or (begin and matches != [path]):
            deny()
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet-file', required=True)
    parser.add_argument('--state-file', required=True)
    parser.add_argument('--gateway-state-file')
    parser.add_argument('--site-file')
    args = parser.parse_args(argv)
    try:
        result = admit(
            packet_path=args.packet_file,
            state_path=args.state_file,
            gateway_state_path=args.gateway_state_file,
            site_path=args.site_file)
        print(result)
        return 0
    except (Hold, OSError, ValueError, TypeError, KeyError):
        print('HOLD: Panel-issued Foreign control path was not admitted', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
