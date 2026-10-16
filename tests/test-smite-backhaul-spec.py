#!/usr/bin/env python3
"""Offline Standard Backhaul compatibility checks. No network or live edits."""
from __future__ import annotations

import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / "modules/smite-backhaul-spec.py"
module_spec = importlib.util.spec_from_file_location("bh_std_spec", target)
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)


def rejects(spec, **kwargs):
    try:
        module.compile_standard_specs(spec, **kwargs)
    except module.StandardBackhaulSpecError:
        return
    raise AssertionError(f"Unsafe Backhaul spec was accepted: {spec.keys()}")


base = {
    "uopti_standard_backhaul": True,
    "transport": "ws",
    "token": "a" * 48,
    "ports": ["56053=127.0.0.1:56053"],
}
ir, kh = module.compile_standard_specs(base)
assert ir["bind_addr"] == "127.0.0.1:3080"
assert ir["ports"] == ["127.0.0.1:56053=127.0.0.1:56053"]
assert ir["mode"] == "server"
assert kh["mode"] == "client"
assert kh["remote_addr"] == "127.0.0.1:13080"
assert kh["transport"] == ir["transport"] == "ws"
assert base["ports"] == ["56053=127.0.0.1:56053"]
assert "bind_addr" not in base

for invalid in (
    {"uopti_standard_backhaul": False},
    {"transport": "tcp"},
    {"transport": "wss"},
    {"token": "short"},
    {"ports": ["56053=0.0.0.0:56053"]},
    {"ports": ["0.0.0.0:56053=127.0.0.1:56053"]},
    {"ports": ["18476"]},
    {"ports": ["56053", "56054"]},
    {"target_host": "0.0.0.0"},
    {"tls_cert": "/tmp/cert.pem"},
):
    x = {**base, **invalid}
    rejects(x)

rejects(base, data_port=18476)
rejects(base, control_port=443)
rejects(base, bridge_port=56053)
assert module.port_number("56053", "data") == 56053
for value in (-1, 0, 10, 443, 7000, 18476, 65536, "4e3", True, None):
    try:
        module.port_number(value, "port")
    except module.StandardBackhaulSpecError:
        continue
    raise AssertionError(f"Unsafe port accepted: {value!r}")

# Guard against accidentally regressing the existing production FRP modules.
assert "smite_frp_xhttp_sync()" in (root / "modules/smite-frp-xhttp.sh").read_text()
assert 'location = /~!frp {' in (root / "modules/smite-gateway.sh").read_text()
print("Backhaul Standard isolated spec compilation: PASS")
