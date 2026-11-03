#!/usr/bin/env python3
"""Stage15/RC7 bridge transaction. Never edits WSS journal, 8444 or FRPS.

The immutable WSS backend hash is checked against a durable before-image.
Only the exact derived include insertion may extend that backend. A prepared
transaction is recoverable but never admitted by the broker.
"""
import argparse
import importlib.util
import json
import os
import re
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

base = load('stage15_bridge_base', 'smite-rc5-xhttp-bridge-install.py')
need = base.require
STATE = Path('/var/lib/u-opti/smite-stage15-xhttp-bridge')
EDGE = Path('/var/lib/u-opti/smite-stage15-wss-edge/record.json')
RC7_EDGE = Path('/var/lib/u-opti/smite-rc7-wss-edge/record.json')

def edge_path():
    # A partial/symlinked generation is evidence too: never silently fall back.
    rc7 = not base.absent(RC7_EDGE.parent)
    need(not (rc7 and not base.absent(EDGE.parent)), 'AMBIGUOUS_WSS_GENERATION')
    if rc7:
        base.trusted_dir(RC7_EDGE.parent, mode=0o700)
        base.trusted_file(RC7_EDGE, mode=0o600)
    return RC7_EDGE if rc7 else EDGE

def edge_state(edge):
    if edge_path() == RC7_EDGE:
        values = edge.p.state()
        need(values.get('SMITE_ROLE') == 'panel-iran'
             and values.get('SMITE_MANAGED_VERSION') == '2.0.0-rc.7', 'IR_RC7_STATE_INVALID')
        doc = edge.journal()
        need(values.get('SMITE_PANEL_DOMAIN') == doc['domain'], 'RC7_DOMAIN_MISMATCH')
        return doc
    return edge.state()

def verify_edge(edge, doc):
    if edge_path() == RC7_EDGE:
        edge.validate_committed(doc)
    else:
        edge.verify(doc)


def candidate(original):
    need(original.count(base.admission.ROOT_LOCATION) == 1
         and b'smite-xhttp-bridge.conf' not in original
         and b'smite-xhttp-routes/' not in original, 'BRIDGE_SOURCE_LAYOUT')
    return original.replace(base.admission.ROOT_LOCATION,
                            base.admission.INCLUDE + b'\n' + base.admission.ROOT_LOCATION, 1)


def record():
    base.trusted_dir(STATE, mode=0o700)
    doc = json.loads(base.trusted_file(STATE / 'journal.json', mode=0o600))
    need(set(doc) == {'schema', 'state', 'before', 'after', 'edge', 'domain'}
         and type(doc['schema']) is int and doc['schema'] in (1, 2)
         and doc['state'] in ('PREPARED', 'COMMITTED', 'RECOVERING', 'ROLLED_BACK'),
         'INVALID_STAGE15_BRIDGE_JOURNAL')
    selected = edge_path()
    need(doc['schema'] == (2 if selected == RC7_EDGE else 1), 'BRIDGE_GENERATION_MISMATCH')
    need(isinstance(doc['domain'], str) and base.admission.DOMAIN.fullmatch(doc['domain']),
         'INVALID_BRIDGE_DOMAIN')
    old = base.trusted_file(STATE / 'backend.before', mode=0o600)
    new = candidate(old)
    need(base.digest(old) == doc['before'] and base.digest(new) == doc['after'],
         'STAGE15_BRIDGE_BACKUP_DRIFT')
    if doc['state'] != 'ROLLED_BACK':
        need(base.digest(base.trusted_file(edge_path(), mode=0o600)) == doc['edge'],
             'STAGE15_EDGE_JOURNAL_DRIFT')
    return doc, old, new


def original_backend(current, *, committed=False):
    """Called by WSS validation; no recursive WSS invocation."""
    doc, old, new = record()
    if doc['state'] == 'ROLLED_BACK':
        need(current == old and base.absent(base.BRIDGE), 'ROLLED_BACK_BRIDGE_DRIFT')
    else:
        need(current in (old, new), 'STAGE15_BACKEND_EXTERNAL_DRIFT')
        if committed:
            need(doc['state'] == 'COMMITTED' and current == new, 'STAGE15_BRIDGE_NOT_COMMITTED')
            need(base.trusted_file(base.BRIDGE, mode=0o644) == base.BRIDGE_BYTES,
                 'STAGE15_BRIDGE_CONTENT_DRIFT')
    return old


def edge_module():
    if edge_path() == RC7_EDGE:
        return load('rc7_bridge_edge', 'smite-rc7-wss-edge.py')
    return load('stage15_bridge_edge', 'smite-stage15-wss-edge.py')


def effective():
    code, config = base.admission._run([base.NGINX, '-T'])
    need(code == 0, 'NGINX_EFFECTIVE_UNAVAILABLE')
    for p in (base.BACKEND, base.BRIDGE):
        need(config.count(f'# configuration file {p}:') == 1, 'BRIDGE_NOT_EFFECTIVE')
    need(config.count(base.admission.INCLUDE.decode().strip()) == 1
         and config.count(base.BRIDGE_BYTES.decode().strip()) == 1,
         'BRIDGE_INCLUDE_NOT_UNIQUE')


def plan():
    base.host_gate()
    need(base.absent(STATE) and base.absent(base.TX_DIR), 'EXISTING_BRIDGE_JOURNAL')
    need(base.absent(base.BRIDGE) and base.absent(base.admission.LEGACY), 'NOT_CLEAN_STAGE15')
    need(base.admission.checked_empty_route_directory(base.ROUTE_DIR), 'PREPARED_ROUTE_DIRECTORY_REQUIRED')
    need(not base.admission._timer_is_unsafe(), 'COMPETING_ROUTE_PUBLISHER')
    edge = edge_module()
    doc = edge_state(edge)
    need(doc['state'] == 'COMMITTED', 'WSS_EDGE_NOT_COMMITTED')
    verify_edge(edge, doc)
    old = base.trusted_file(base.BACKEND, mode=0o644)
    new = candidate(old)
    need(base.admission.OLD_INCLUDE not in old, 'LEGACY_INCLUDE_FORBIDDEN')
    base.probe_panel(doc['domain'])
    return {'schema': 2 if edge_path() == RC7_EDGE else 1, 'state': 'PREPARED', 'before': base.digest(old),
            'after': base.digest(new), 'edge': base.digest(base.trusted_file(edge_path(), mode=0o600)),
            'domain': doc['domain']}, old, new


def save(doc):
    base.replace_file(STATE / 'journal.json', (json.dumps(doc, sort_keys=True) + '\n').encode(), 0o600)


def invariants(doc, old):
    need(base.digest(base.trusted_file(edge_path(), mode=0o600)) == doc['edge'], 'WSS_JOURNAL_CHANGED')
    edge = edge_module()
    e = edge_state(edge)
    if doc['schema'] == 2:
        need(e['state'] == 'COMMITTED' and e['domain'] == doc['domain']
             and e['tls_before'] == base.digest(old), 'WSS_BINDING_CHANGED')
        original = base.trusted_file(edge.STATE / 'map.before', mode=0o600)
        stream = base.trusted_file(edge.q.STREAM_SOURCE)
        alt, mapping = edge.render(e['domain'], e['peer'], before=old,
                                   stream=stream, mapping=original)
        need(base.digest(original) == e['map_before']
             and base.digest(stream) == e['stream']
             and base.digest(alt) == e['alternate']
             and base.digest(mapping) == e['map_after']
             and base.trusted_file(edge.q.ALT_CANDIDATE, mode=0o644) == alt
             and base.trusted_file(edge.q.FRP_MAP, mode=e['map_mode']) == mapping,
             'WSS_PROTECTED_CONTENT_CHANGED')
        return
    need(e['state'] == 'COMMITTED' and e['domain'] == doc['domain']
         and e['backend'] == base.digest(old), 'WSS_BINDING_CHANGED')
    need(base.digest(base.trusted_file(edge.edge.STREAM_SOURCE)) == e['stream']
         and base.trusted_file(edge.edge.FRP_MAP).decode() == e['new_map']
         and base.trusted_file(edge.edge.ALT_CANDIDATE).decode() == e['alt'],
         'WSS_PROTECTED_CONTENT_CHANGED')


def restore():
    # A kill between the before-image and journal writes cannot have changed
    # Nginx: mutations start only after the journal is durable. Reconcile only
    # this exact empty/preparation layout; never guess at other partial state.
    if base.absent(STATE / 'journal.json'):
        base.trusted_dir(STATE, mode=0o700)
        need({p.name for p in STATE.iterdir()} <= {'backend.before'}, 'UNKNOWN_PARTIAL_BRIDGE_STATE')
        need(base.absent(base.BRIDGE), 'PARTIAL_BRIDGE_ALREADY_PRESENT')
        current = base.trusted_file(base.BACKEND, mode=0o644)
        edge_doc = json.loads(base.trusted_file(edge_path(), mode=0o600))
        need(edge_doc.get('state') == 'COMMITTED' and edge_doc.get('tls_before' if edge_path() == RC7_EDGE else 'backend') == base.digest(current),
             'PARTIAL_BACKEND_DRIFT')
        if not base.absent(STATE / 'backend.before'):
            need(base.trusted_file(STATE / 'backend.before', mode=0o600) == current, 'PARTIAL_BACKUP_DRIFT')
            (STATE / 'backend.before').unlink()
        STATE.rmdir(); base.sync_dir(STATE.parent)
        return
    doc, old, new = record()
    invariants(doc, old)
    need(base.trusted_file(base.BACKEND, mode=0o644) in (old, new), 'BACKEND_EXTERNAL_DRIFT')
    base.trusted_dir(base.ROUTE_DIR, mode=0o755)
    for entry in base.ROUTE_DIR.iterdir():
        need(entry.name.startswith('.') and entry.name.endswith('.transaction.json'), 'ROUTES_REQUIRE_SEPARATE_ROLLBACK')
        route = json.loads(base.trusted_file(entry, mode=0o600))
        need(route.get('state') == 'ROLLED_BACK', 'ROUTE_TRANSACTION_REQUIRES_RECOVERY')
    if not base.absent(base.BRIDGE):
        need(base.trusted_file(base.BRIDGE, mode=0o644) == base.BRIDGE_BYTES, 'BRIDGE_EXTERNAL_DRIFT')
    doc['state'] = 'RECOVERING'; save(doc)
    base.replace_file(base.BACKEND, old, 0o644)
    if not base.absent(base.BRIDGE):
        base.BRIDGE.unlink(); base.sync_dir(base.BRIDGE.parent)
    base.nginx_test(); base.nginx_reload(); base.probe_panel(doc['domain'])
    doc['state'] = 'ROLLED_BACK'; save(doc)


def apply():
    doc, old, new = plan()
    STATE.mkdir(mode=0o700); base.sync_dir(STATE.parent)
    base.new_file(STATE / 'backend.before', old, 0o600)
    base.new_file(STATE / 'journal.json', (json.dumps(doc, sort_keys=True) + '\n').encode(), 0o600)
    try:
        invariants(doc, old)
        need(base.trusted_file(base.BACKEND, mode=0o644) == old, 'BACKEND_CHANGED')
        base.new_file(base.BRIDGE, base.BRIDGE_BYTES, 0o644)
        base.replace_file(base.BACKEND, new, 0o644)
        base.nginx_test(); effective(); base.nginx_reload(); base.probe_panel(doc['domain'])
        invariants(doc, old)
        doc['state'] = 'COMMITTED'; save(doc)
        verify()
    except Exception:
        restore()
        raise base.Hold('STAGE15_BRIDGE_FAILURE_ROLLED_BACK')


def verify():
    base.host_gate()
    doc, old, new = record()
    original_backend(base.trusted_file(base.BACKEND, mode=0o644), committed=True)
    need(doc['state'] == 'COMMITTED', 'STAGE15_BRIDGE_NOT_COMMITTED')
    invariants(doc, old)
    edge = edge_module(); verify_edge(edge, edge_state(edge))
    base.trusted_dir(base.ROUTE_DIR, mode=0o755)
    base.nginx_test(); effective(); base.probe_panel(doc['domain'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['plan', 'apply', 'verify', 'rollback', 'recover'])
    args = p.parse_args()
    fd = None
    try:
        base.host_gate()
        if args.action in ('apply', 'rollback', 'recover'):
            need(sys.stdin.isatty(), 'ROOT_INTERACTIVE_APPROVAL_REQUIRED')
            challenge = args.action.upper() + '-IR-STAGE15-BRIDGE-SNAPSHOT'
            need(input('Type ' + challenge + ': ') == challenge, 'OPERATOR_CANCELLED')
        fd = base.lock_host()
        if args.action == 'plan': plan()
        elif args.action == 'verify': verify()
        elif args.action == 'apply': apply()
        else: restore()
        print('STAGE15_XHTTP_BRIDGE=' + args.action.upper() + '_PASS')
        print('FRPS_RESTART=NO')
        return 0
    except Exception as exc:
        reason = str(exc)
        print('HOLD: ' + (reason if re.fullmatch('[A-Z0-9_]{1,100}', reason)
                          else 'UNTRUSTED_BRIDGE_STATE'), file=sys.stderr)
        return 2
    finally:
        if fd is not None: os.close(fd)

if __name__ == '__main__':
    raise SystemExit(main())
