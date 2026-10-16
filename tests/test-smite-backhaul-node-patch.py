#!/usr/bin/env python3
"""CI: Standard Backhaul node-guard and upstream adapter fixture, offline only."""
from __future__ import annotations

import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compiler = load("bh_standard", root / "modules/smite-backhaul-spec.py")
patcher = load("bh_patch", root / "modules/smite-backhaul-node-patch.py")

base = {
    "uopti_standard_backhaul": True,
    "transport": "ws",
    "token": "strong-token-with-at-least-24-character-length",
    "ports": ["56053=127.0.0.1:56053"],
}

ir, kh = compiler.compile_standard_specs(base)
assert compiler.normalize_node_spec(ir) == ir
assert compiler.normalize_node_spec(kh) == kh
assert ir["bind_addr"] == "127.0.0.1:3080"
assert ir["ports"] == ["127.0.0.1:56053=127.0.0.1:56053"]
assert kh["remote_addr"] == "127.0.0.1:13080"
assert "bind_addr" not in base


def rejected(spec, **kwargs):
    try:
        compiler.compile_standard_specs({**base, **spec}, **kwargs)
    except compiler.StandardBackhaulSpecError:
        return
    raise AssertionError("Unsafe spec was accepted")


for case in (
    {"uopti_standard_backhaul": False},
    {"transport": "tcp"},
    {"transport": "wss"},
    {"type": "tcp"},
    {"token": "weak"},
    {"ports": ["56053=0.0.0.0:56053"]},
    {"ports": ["0.0.0.0:56053=127.0.0.1:56053"]},
    {"ports": ["18476"]},
    {"ports": ["56053", "56054"]},
    {"target_host": "0.0.0.0"},
    {"local_ip": "0.0.0.0"},
    {"bind_ip": "0.0.0.0"},
    {"bind_addr": "0.0.0.0:3080"},
    {"bind_addr": "127.0.0.1:7000"},
    {"remote_addr": "ir.kolbe1.ir:443"},
    {"public_port": 3080},
    {"listen_port": 3080},
    {"target_port": 7000},
    {"server_options": {"pprof": True}},
    {"client_options": {"edge_ip": "example.org"}},
    {"pprof": True},
    {"web_port": 7777},
    {"accept_udp": True},
    {"tls_cert": "/tmp/cert.pem"},
    {"mode": "unexpected"},
    {"data_port": 18476},
    {"control_port": 443},
    {"bridge_port": 56053},
):
    rejected(case)

for case in (
    {"uopti_standard_backhaul": False, "mode": "server"},
    {**base},
    {**base, "mode": "other"},
    {**base, "mode": "server", "bind_addr": "0.0.0.0:3080"},
):
    try:
        compiler.normalize_node_spec(case)
    except compiler.StandardBackhaulSpecError:
        continue
    raise AssertionError("Unsafe node spec was accepted")

# A pinned v0.1.7-compatible fixture: patcher must preserve all non-Backhaul
# code, insert validation BEFORE pre-existing process removal, prevent
# Standard token logging and securely write TOML with mode 0600.
fixture = (
    "class RatholeAdapter:\n    pass\n\n"
    "class BackhaulAdapter:\n"
    "    def apply(self, tunnel_id: str, spec: Dict[str, Any]):\n"
    "        \"\"\"Apply Backhaul tunnel - supports both server and client modes\"\"\"\n"
    "        if tunnel_id in self.processes:\n"
    "            self.remove(tunnel_id)\n"
    "        mode = spec.get('mode', 'client')\n"
    "        if mode == 'server':\n"
    "            config_path.write_text(self._render_toml({\"server\": server_config}), encoding=\"utf-8\")\n"
    "            log_fh.write(self._render_toml({\"server\": server_config}))\n"
    "        else:\n"
    "            config_path.write_text(self._render_toml({\"client\": config_dict}), encoding=\"utf-8\")\n"
    "            log_fh.write(self._render_toml({\"client\": config_dict}))\n"
    "\nclass ChiselAdapter:\n    pass\n"
)
patched = patcher.patch_source(fixture)
assert patcher.patch_source(patched) == patched
assert patched.index("normalize_node_spec(spec)") < patched.index("self.remove(tunnel_id)")
assert patched.count("os.O_NOFOLLOW") == 2
assert patched.count("os.fchmod(") == 2
assert patched.count('if not spec.get("uopti_standard_backhaul"):') == 2
assert patched.startswith("class RatholeAdapter:")
assert patched.endswith("class ChiselAdapter:\n    pass\n")
assert "self.remove(tunnel_id)" in patched
assert "class FrpAdapter" not in patched
for corrupt in (fixture.replace("class BackhaulAdapter:", "class OtherAdapter:"),
                fixture.replace('log_fh.write(self._render_toml({"server": server_config}))', "pass")):
    try:
        patcher.patch_source(corrupt)
    except ValueError:
        continue
    raise AssertionError("Unexpected adapter layout accepted")

print("Backhaul Standard node adapter candidate patch: PASS")
