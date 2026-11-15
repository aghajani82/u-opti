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
import time
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
                        or (info.st_mode & 0o022
                            and not (info.st_mode & stat.S_ISVTX and info.st_uid == 0))):
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
            or state.get('SMITE_MANAGED_VERSION') not in ('2.0.0-rc.7', '2.0.0-rc.9')
            or (state.get('SMITE_MANAGED_VERSION') == '2.0.0-rc.9'
                and state.get('SMITE_UPSTREAM_REF') != 'e7f76185e9a7da51d7069d5d0a829dc192cc1e06')
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


def precore_fields(packet_path, *, now=None, for_core_owner=False):
    """Return only pre-validated nonsecret Node/domain fields for SAME option 2.

    The privately staged packet is the single authority for fresh Foreign
    core prompts; the grant must be fresh before any host installation.
    This does not redeem a code, issue origin trust or permit activation.
    """
    client = load_module('uopti_unified_precore_client', 'smite-foreign-install-client.py')
    promotion = load_module('uopti_unified_precore_promotion', 'smite-foreign-install-promotion.py')
    packet = private_packet(packet_path, client, promotion)
    moment = int(time.time()) if now is None else now
    if type(moment) is not int or not moment < packet.expires_at <= moment + 7200:
        deny()
    from urllib.parse import urlsplit as split
    panel = split(packet.scope['panel_url']).hostname
    foreign = split(packet.scope['origin']).hostname
    name = packet.scope['node_name']
    if panel == foreign:
        deny()
    # The original Core Journal needs Node ID and control-path too, but
    # never the one-use installation code. Reuse the SAME private packet
    # parsing and time window used by the existing Foreign core prompts.
    if for_core_owner is True:
        return (panel, foreign, name, packet.scope['node_id'],
                split(packet.scope['control_url']).path)
    if for_core_owner is not False:
        deny()
    # The already-validated exact 443 control URL is set before first
    # Node boot, so the Gateway can verify it without recreating the Node.
    return panel, foreign, name, packet.scope['control_url']


def _prepairing_exact_scope(*, packet_path, state_path, gateway_state_path,
                            node_env_path, site_path):
    """Unchanged original read-only scope, Gateway and Node verification.

    Both a FRESH bearer and an independently proven already-staged expired
    bearer must pass ALL of these same checks. A receipt alone is never a
    reason to skip the original Node .env or Gateway security witness.
    """
    client = load_module("uopti_pre_pair_client", "smite-foreign-install-client.py")
    promotion = load_module(
        "uopti_pre_pair_promotion", "smite-foreign-install-promotion.py")
    packet = private_packet(packet_path, client, promotion)
    control = admit(
        packet_path=packet_path, state_path=state_path,
        gateway_state_path=gateway_state_path, site_path=site_path)
    if (control != urlsplit(packet.scope["control_url"]).path
            or promotion.verify_gateway(
                packet, state_path=state_path,
                gateway_path=gateway_state_path,
                node_env_path=node_env_path, client=client) is not True):
        deny()
    return "FOREIGN_SIGNED_PAIRING_PREFLIGHT=EXACT_READ_ONLY"


def prepairing_read_only(*, packet_path, state_path, gateway_state_path,
                         node_env_path, site_path, now=None):
    """Original fresh-only pre-promotion verification, including 2h TTL."""
    precore_fields(packet_path, now=now)
    return _prepairing_exact_scope(
        packet_path=packet_path, state_path=state_path,
        gateway_state_path=gateway_state_path,
        node_env_path=node_env_path, site_path=site_path)


# Original selected Foreign path only. Does NOT change legacy RC7 admission.
_SELECTED_ROOT_PACKET = Path(
    "/var/lib/u-opti/rc6-install-journal/foreign-staging/foreign-install-packet.json")
_SELECTED_ROOT_IDENTITY = Path(
    "/etc/u-opti/smite/identities/node-identity.json")
_SELECTED_ROOT_STATE = Path("/etc/u-opti/smite/state.env")
_SELECTED_ROOT_GATEWAY = Path("/etc/u-opti/smite/foreign-gateway.env")
_SELECTED_ROOT_NODE_ENV = Path("/opt/smite-node/.env")


def prepairing_owned_expired(*, packet_path, state_path, gateway_state_path,
                            node_env_path, site_path, now=None):
    """Same FULL pre-Pairing checks after separately verified staged identity.

    A consumed one-use grant cannot be redeemed again after TTL. Only the
    existing immutable RC9 signed release and the ORIGINAL exact private
    INTENT/staged-identity/promotion receipts permit skipping the fresh
    bearer-time check. All other Gateway/Node checks remain mandatory.
    This function is read-only; no host operations or credentials printed.
    """
    if (Path(packet_path) != _SELECTED_ROOT_PACKET
            or Path(state_path) != _SELECTED_ROOT_STATE
            or Path(gateway_state_path) != _SELECTED_ROOT_GATEWAY
            or Path(node_env_path) != _SELECTED_ROOT_NODE_ENV
            or not Path(site_path).is_absolute()):
        deny()
    try:
        pairing = load_module(
            "uopti_existing_expired_pairing_release", "smite-node-pairing.py")
        pairing._require_unified_foreign_release()
        client = load_module(
            "uopti_existing_expired_gateway_client", "smite-foreign-install-client.py")
        promotion = load_module(
            "uopti_existing_expired_gateway_promotion", "smite-foreign-install-promotion.py")
        identity = load_module(
            "uopti_existing_expired_original_identity", "smite-unified-foreign-identity-phase.py")
        packet = private_packet(packet_path, client, promotion)
        moment = int(time.time()) if now is None else now
        if type(moment) is not int or moment < packet.expires_at:
            deny()
        with promotion.private_directory(_SELECTED_ROOT_PACKET.parent) as folder:
            raw = promotion.read_optional(
                folder, _SELECTED_ROOT_PACKET.name, client)
        if raw is None or client.parse_packet(raw) != packet:
            deny()
        identity._selected_expired_packet_resume(
            packet, raw, client=client, promotion=promotion,
            directory=_SELECTED_ROOT_PACKET.parent,
            live_identity=_SELECTED_ROOT_IDENTITY)
    except Exception:
        # Release, malicious receipt, changed packet or unsafe on-disk
        # ownership all HOLD before any Node/Gateway mutation.
        deny()
    return _prepairing_exact_scope(
        packet_path=packet_path, state_path=state_path,
        gateway_state_path=gateway_state_path,
        node_env_path=node_env_path, site_path=site_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet-file', required=True)
    parser.add_argument('--state-file')
    parser.add_argument('--gateway-state-file')
    parser.add_argument('--site-file')
    parser.add_argument('--precore-fields', action='store_true')
    parser.add_argument('--prepairing-read-only', action='store_true')
    parser.add_argument('--prepairing-owned-expired', action='store_true')
    parser.add_argument('--node-env-file')
    args = parser.parse_args(argv)
    try:
        if args.precore_fields:
            if (args.prepairing_read_only or args.prepairing_owned_expired or args.node_env_file
                    or args.state_file or args.gateway_state_file
                    or args.site_file):
                deny()
            # Four already-validated nonsecret fields; never include
            # node_id, installation_code, private HMAC secret or packet JSON.
            result = precore_fields(args.packet_file)
            for field in result:
                print(field)
        elif args.prepairing_read_only or args.prepairing_owned_expired:
            if (not all((args.state_file, args.gateway_state_file,
                         args.site_file, args.node_env_file))
                    or (args.prepairing_read_only and args.prepairing_owned_expired)):
                deny()
            fn = (prepairing_owned_expired if args.prepairing_owned_expired
                  else prepairing_read_only)
            print(fn(
                packet_path=args.packet_file, state_path=args.state_file,
                gateway_state_path=args.gateway_state_file,
                site_path=args.site_file, node_env_path=args.node_env_file))
        else:
            if args.prepairing_owned_expired or args.node_env_file or not args.state_file:
                deny()
            result = admit(
                packet_path=args.packet_file,
                state_path=args.state_file,
                gateway_state_path=args.gateway_state_file,
                site_path=args.site_file)
            print(result)
        return 0
    except (Hold, OSError, ValueError, TypeError, KeyError):
        print('HOLD: Panel-issued Foreign control scope was not admitted', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
