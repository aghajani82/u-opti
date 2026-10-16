#!/usr/bin/env python3
"""Pure mocks for sanitized READ-ONLY IR/KH collector. No live host calls."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "modules/smite-backhaul-sidecar-collect.py"
_spec = importlib.util.spec_from_file_location("sidecar_collect_ro", SCRIPT)
collect = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(collect)

IR_SS = '\n'.join([
    'LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=54071,fd=13),("nginx",pid=54070,fd=13))',
    'LISTEN 0 128 127.0.0.1:8443 0.0.0.0:* users:(("nginx",pid=54071,fd=13))',
    'LISTEN 0 128 127.0.0.1:7000 0.0.0.0:* users:(("frps",pid=53978,fd=8))',
    'LISTEN 0 256 203.0.113.182:9999 0.0.0.0:* users:(("unknown",pid=9,fd=8))',
])
KH_SS = '\n'.join([
    'LISTEN 0 4096 127.0.0.1:56053 0.0.0.0:* users:(("xray",pid=1515,fd=11))',
    'LISTEN 0 4096 [::]:38383 [::]:* users:(("secret-daemon",pid=122,fd=2))',
])


def sample(role: str, **overrides) -> dict:
    opts = {
        "role": role,
        "raw_ss": IR_SS if role == "ir" else KH_SS,
        "network_mode": "host",
        "container_names": ["smite-node", "smite-panel"],
        "node_running": True,
        "panel_running": True if role == "ir" else None,
        "legacy_count": 0 if role == "ir" else 4,
        "existing_files": {name: False for name in collect.FILES[role]},
        "now": datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc),
    }
    opts.update(overrides)
    return collect.snapshot_from_observations(**opts)


class ReadOnlyCollectionTests(unittest.TestCase):
    def test_minimal_sanitized_host_evidence_is_never_green(self):
        for role in ("ir", "kh"):
            with self.subTest(role=role):
                s = sample(role)
                self.assertEqual(s["ports"]["network_mode"], "host")
                self.assertEqual(s["versions"], {"smite": None, "backhaul": None})
                self.assertIsNone(s["checks"]["nginx_config_syntax_ok"])
                self.assertIsNone(s["checks"]["sidecar_files_absent"] if False else
                                  s["checks"]["https_ir_route_verified"] if role == "kh" else
                                  s["checks"]["stream_sni_and_canary_reviewed"])
                self.assertTrue(s["checks"]["sidecar_files_absent"])
                self.assertTrue(s["checks"]["sidecar_names_unallocated"])
                text = json.dumps(s)
                self.assertNotIn("203.0.113.182", text)
                self.assertNotIn("secret-daemon", text)
                self.assertNotIn('"pid"', text)
                with self.assertRaisesRegex(
                    collect._gate.PreflightRefused, "version"
                ):
                    collect._gate.review(s, role, s["observed_at"] and
                                         datetime.fromisoformat(s["observed_at"]))

    def test_redact_all_nonloopback_address_families(self):
        s = sample("ir", raw_ss=IR_SS + '\n' +
            'LISTEN 0 4 [2001:db8:1234::987]:3080 [::]:* users:(("other",pid=15,fd=5))\n' +
            'LISTEN 0 8 203.0.113.67:56053 0.0.0.0:* users:(("other",pid=8,fd=5))')
        ports = s["ports"]["listeners"]
        self.assertIn(
            {"address":"2001:db8::1", "port":3080, "owner":"other"}, ports
        )
        self.assertIn(
            {"address":"192.0.2.1", "port":56053, "owner":"other"}, ports
        )
        text=json.dumps(s)
        self.assertNotIn("2001:db8:1234::987", text)
        self.assertNotIn("203.0.113.67", text)
        # Synthetic addresses must still block port ownership checks.
        with self.assertRaisesRegex(collect._gate.PreflightRefused, "version"):
            collect._gate.review(s, "ir", datetime.fromisoformat(s["observed_at"]))
        s["versions"]={"smite":"v0.1.7","backhaul":"v0.7.2"}
        with self.assertRaisesRegex(collect._gate.PreflightRefused, "port owner"):
            collect._gate.review(s, "ir", datetime.fromisoformat(s["observed_at"]))

    def test_no_false_positive_when_owner_missing(self):
        ss = IR_SS.replace(
            'users:(("frps",pid=53978,fd=8))', ''
        )
        result = sample("ir", raw_ss=ss)
        ports = result["ports"]["listeners"]
        self.assertTrue(any(
            x["port"] == 7000 and x["owner"] == "other" for x in ports
        ))
        self.assertFalse(any(
            x["port"] == 7000 and x["owner"] == "frps" for x in ports
        ))

    def test_reject_incomplete_ss_rather_than_claim_empty_ports(self):
        for record in ("LISTEN 0 10 rubbish", "LISTEN 0 10 no_colon other users:x",
                       "LISTEN 0 10 127.0.0.1:http * users:x"):
            with self.assertRaises(collect.CollectionError):
                collect.parse_ss(record, "ir")

    def test_existing_file_or_container_blocks_observation(self):
        role = "kh"
        s = sample(
            role,
            container_names=[collect.CONTAINERS[role]],
            existing_files={x: True if x.endswith("kh.toml") else False
                            for x in collect.FILES[role]},
        )
        self.assertFalse(s["checks"]["sidecar_files_absent"])
        self.assertFalse(s["checks"]["sidecar_names_unallocated"])

    def test_legacy_config_count_does_not_read_config_contents(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            folder = root / "backhaul"
            folder.mkdir()
            (folder / "private.toml").write_text('token = "DO-NOT-READ"')
            (folder / "other.log").write_text("log")
            (folder / "symlink.toml").symlink_to(folder / "private.toml")
            mounts = json.dumps([{
                "Destination": "/etc/smite-node", "Type": "bind",
                "Source": str(root),
            }])
            self.assertEqual(collect.legacy_config_count(mounts), 1)
            self.assertIsNone(collect.legacy_config_count("{}"))
            self.assertIsNone(collect.legacy_config_count("[]"))
            self.assertIsNone(collect.legacy_config_count("not-json"))

    def test_collect_does_not_invoke_docker_exec_or_read_private_files(self):
        role = "ir"
        commands = []
        def fake_run(*args):
            commands.append(args)
            if args[0] == "ss":
                return IR_SS
            if args[0:3] == ("docker", "container", "ls"):
                return "smite-node\nsmite-panel"
            if args[5] == "{{.HostConfig.NetworkMode}}":
                return "host"
            if args[5] == "{{json .Mounts}}":
                return "[]"
            if args[5] == "{{.State.Running}}":
                return "true"
            raise AssertionError(args)
        with mock.patch.object(collect, "run_readonly", side_effect=fake_run), \
             mock.patch.object(collect.os.path, "lexists", return_value=False):
            evidence = collect.collect(role)
        self.assertIsNone(evidence["baseline"]["legacy_clients"])
        self.assertTrue(evidence["checks"]["smite_panel_running"])
        self.assertEqual(evidence["ports"]["network_mode"], "host")
        self.assertTrue(all("exec" not in args and "restart" not in args and
                            "nginx" not in args for args in commands))
        self.assertNotIn("token", json.dumps(evidence))

    def test_command_allowlist_rejects_any_write_action(self):
        for argv in (
            ("docker", "exec", "smite-node", "backhaul", "-v"),
            ("docker", "restart", "smite-node"),
            ("nginx", "-t"),
            ("systemctl", "reload", "nginx"),
            ("ss", "-plntH"),
        ):
            with self.assertRaisesRegex(collect.CollectionError, "allowlist"):
                collect.run_readonly(*argv)


if __name__ == "__main__":
    unittest.main()
