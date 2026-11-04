#!/usr/bin/env python3
"""Host Backhaul safety gate; no VPS mutation, no network/FRP control."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import stat
from types import SimpleNamespace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules" / "smite-managed-backhaul-host-gate.py"
spec = importlib.util.spec_from_file_location("bh_gate_review", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

COMPOSE = """services:
  smite-node:
    image: smite-node:stage15-local
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
      - node-data:/var/lib/smite-node

volumes:
  node-data:
    name: smite-node-data
"""
RC6_ID = "uopti_rc6_" + "7" * 32
RC6_VOLUME = RC6_ID + "_node-data"
RC6_JOURNAL = {
    "schema": 1, "source": "9a1270b31e8d44f13d09b71ab6b9798410b09c12",
    "state": "COMMITTED", "id": RC6_ID, "role": "panel-iran",
}
ENV = """NODE_ROLE=foreign
SMITE_NODE_PANEL_AUTH_MODE=signed
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
"""


class ReadOnlyGate(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.node = self.root / "node"
        self.node.mkdir()
        self.cfg = self.node / "config"
        self.cfg.mkdir()
        self.data = self.root / "data"
        self.data.mkdir()
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE)
        self.runtime = {
            "Name": "/smite-node",
            "State": {"Running": True},
            "Config": {"Image": "smite-node:stage15-local", "Env": ["TOKEN=DONT_PRINT"]},
            "HostConfig": {"NetworkMode": "host", "PortBindings": {}},
            "Mounts": [
                {"Type": "bind", "Destination": "/etc/smite-node", "Source": str(self.cfg)},
                {"Type": "volume", "Name": "smite-node-data", "Driver": "local",
                 "Destination": "/var/lib/smite-node", "Source": str(self.data)},
            ],
        }
        real = gate._local_file
        def runner_file(path, *, max_bytes, require_root=False):
            # CI fixtures have runner ownership; only skip UID gate here.
            return real(path, max_bytes=max_bytes, require_root=False)
        self._patch = patch.object(gate, "_local_file", side_effect=runner_file)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def report(self):
        return gate.audit(self.node, runtime=self.runtime, min_bytes=4096)

    def test_good_local_evidence_is_not_deployment_permission(self):
        status = self.report()
        self.assertEqual(status["NODE_ROLE"], "KH")
        self.assertEqual(status["LOCAL_CORE"], "MANAGED_STRICT")
        self.assertEqual(status["DOCKER_NODE"], "RUNNING_REVIEWED_IMAGE")
        self.assertEqual(status["PERSISTENT_DATA"], "LOCAL_NAMED_VOLUME_CONFIRMED")
        self.assertEqual(status["PERSISTED_TUNNELS"], "ZERO")
        self.assertEqual(status["DISK_SPACE"], "MINIMUM_AVAILABLE")
        self.assertEqual(status["HOST_PREFLIGHT"], "PASS_LOCAL_ONLY_INCOMPLETE")
        self.assertEqual(status["HOST_INSTALL_AUTHORIZED"], "NO")
        self.assertIn("UNVERIFIED", status["SNAPSHOT_AND_CONSOLE"])
        self.assertIn("UNVERIFIED", status["NGINX_443_AND_FIREWALL_EXPOSURE"])
        self.assertEqual(status["FRP_INSTALL_REQUIRED"], "NO")
        self.assertNotIn("DONT_PRINT", str(status))



    def use_rc6_ir(self):
        """Model the real IR layout, leaving the production gate HOLD."""
        (self.node / ".env").write_text(ENV.replace("NODE_ROLE=foreign", "NODE_ROLE=iran"))
        (self.node / "docker-compose.yml").write_text(
            COMPOSE.replace("name: smite-node-data", "name: " + RC6_VOLUME))
        self.runtime["Mounts"][1]["Name"] = RC6_VOLUME

    def test_committed_rc6_volume_proves_ir_compose_and_runtime_without_activation(self):
        self.use_rc6_ir()
        with patch.object(gate, "_read_rc6_journal_bytes",
                          return_value=json.dumps(RC6_JOURNAL).encode()):
            result = self.report()
        self.assertEqual(result["NODE_ROLE"], "IR")
        self.assertEqual(result["PERSISTENT_DATA"], "LOCAL_NAMED_VOLUME_CONFIRMED")
        self.assertEqual(result["VOLUME_PROOF"], "COMMITTED_RC6_JOURNAL")
        self.assertEqual(result["HOST_PREFLIGHT"], "PASS_LOCAL_ONLY_INCOMPLETE")
        self.assertEqual(result["HOST_INSTALL_AUTHORIZED"], "NO")

    def test_committed_rc6_keeps_existing_tunnels_on_hold(self):
        self.use_rc6_ir()
        (self.data / "tunnels.json").write_text(json.dumps({
            "frp": {"core": "frp", "spec": {"secret": "DONT_PRINT"}}
        }))
        with patch.object(gate, "_read_rc6_journal_bytes",
                          return_value=json.dumps(RC6_JOURNAL).encode()):
            result = self.report()
        self.assertEqual(result["HOST_PREFLIGHT"], "HOLD_EXISTING_TUNNELS")
        self.assertEqual(result["HOST_INSTALL_AUTHORIZED"], "NO")
        self.assertNotIn("DONT_PRINT", str(result))

    def test_rc6_journal_must_be_committed_matching_role_and_source(self):
        self.use_rc6_ir()
        bad_cases = [
            {"state": "INSTALLING"}, {"state": "ROLLED_BACK"},
            {"role": "foreign"}, {"source": "0" * 40},
            {"schema": 2}, {"id": "uopti_rc6_" + "0" * 32},
        ]
        for change in bad_cases:
            with self.subTest(change=change):
                value = dict(RC6_JOURNAL, **change)
                with patch.object(gate, "_read_rc6_journal_bytes",
                                  return_value=json.dumps(value).encode()):
                    result = self.report()
                self.assertEqual(result["HOST_PREFLIGHT"], "HOLD")
                self.assertEqual(result["HOLD_REASON"], "UNTRUSTED_RC6_JOURNAL")

    def test_rc6_wrong_runtime_name_and_untrusted_journal_hold(self):
        self.use_rc6_ir()
        raw = json.dumps(RC6_JOURNAL).encode()
        with patch.object(gate, "_read_rc6_journal_bytes", return_value=raw):
            self.runtime["Mounts"][1]["Name"] = "smite-node-data"
            self.assertEqual(self.report()["HOLD_REASON"], "WRONG_NODE_NAMED_VOLUME")
            self.runtime["Mounts"][1]["Name"] = RC6_VOLUME
            self.runtime["Mounts"][1]["Type"] = "bind"
            self.assertEqual(self.report()["HOLD_REASON"], "WRONG_NODE_NAMED_VOLUME")
        with patch.object(gate, "_read_rc6_journal_bytes",
                          side_effect=gate.GateHold("UNTRUSTED_RC6_JOURNAL")):
            self.assertEqual(self.report()["HOLD_REASON"], "UNTRUSTED_RC6_JOURNAL")

    def test_rc6_unrelated_prefix_duplicate_declarations_and_extra_names_hold(self):
        self.use_rc6_ir()
        source = (self.node / "docker-compose.yml").read_text()
        for variant in (
            source.replace(RC6_VOLUME, "uopti_rc6_" + "a" * 32 + "_node-data"),
            source.replace("    name: " + RC6_VOLUME,
                           "    name: " + RC6_VOLUME + "\n    name: " + RC6_VOLUME),
            source + "\nvolumes:\n  node-data:\n    name: " + RC6_VOLUME + "\n",
        ):
            with self.subTest(variant=variant[-80:]):
                (self.node / "docker-compose.yml").write_text(variant)
                with patch.object(gate, "_read_rc6_journal_bytes",
                                  return_value=json.dumps(RC6_JOURNAL).encode()):
                    self.assertEqual(self.report()["HOST_PREFLIGHT"], "HOLD")
        (self.node / "docker-compose.yml").write_text(source)

    def test_rc6_json_duplicate_keys_and_journal_file_security_fail(self):
        double = (b'{"schema":1,"source":"' +
                  RC6_JOURNAL["source"].encode() +
                  b'","state":"COMMITTED","role":"panel-iran","id":"' +
                  RC6_ID.encode() + b'","id":"' + RC6_ID.encode() + b'"}')
        with self.assertRaises(gate.GateHold):
            gate._committed_rc6_volume(double, "IR")
        with self.assertRaises(gate.GateHold):
            gate._read_rc6_journal_bytes(self.root / "nonexistent" / "current.json")
        unowned = self.root / "current.json"
        unowned.write_text(json.dumps(RC6_JOURNAL))
        with self.assertRaises(gate.GateHold):
            gate._read_rc6_journal_bytes(unowned)

    def test_static_volume_works_without_rc6_journal(self):
        with patch.object(gate, "_read_rc6_journal_bytes",
                          side_effect=AssertionError("static volume needs no RC6 journal")):
            result = self.report()
        self.assertEqual(result["VOLUME_PROOF"], "REVIEWED_STATIC_VOLUME")
        self.assertEqual(result["HOST_INSTALL_AUTHORIZED"], "NO")

    def test_registry_candidate_requires_exact_external_digest_pin(self):
        self.runtime["Config"]["Image"] = "ghcr.io/aghajani82/smite-node@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        self.assertEqual(self.report()["HOLD_REASON"], "EXPECTED_NODE_DIGEST_REQUIRED")
        accepted = gate.audit(
            self.node, runtime=self.runtime, min_bytes=4096,
            expected_node_image="ghcr.io/aghajani82/smite-node@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        self.assertEqual(accepted["HOST_PREFLIGHT"], "PASS_LOCAL_ONLY_INCOMPLETE")
        self.assertEqual(
            accepted["IMAGE_REFERENCE_CLASS"], "OPERATOR_PINNED_DIGEST_UNATTESTED"
        )
        self.assertEqual(accepted["HOST_INSTALL_AUTHORIZED"], "NO")
        mismatch = gate.audit(
            self.node, runtime=self.runtime, min_bytes=4096,
            expected_node_image="ghcr.io/aghajani82/smite-node@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )
        self.assertEqual(mismatch["HOLD_REASON"], "NODE_IMAGE_DIGEST_MISMATCH")
        malformed = gate.audit(
            self.node, runtime=self.runtime, min_bytes=4096,
            expected_node_image="ghcr.io/aghajani82/smite-node:latest",
        )
        self.assertEqual(malformed["HOLD_REASON"], "INVALID_EXPECTED_NODE_DIGEST")

    def test_old_vendor_digest_is_not_implicitly_reviewed_anymore(self):
        self.runtime["Config"]["Image"] = (
            "ghcr.io/zzedix/smite-node@sha256:"
            "967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
        )
        out = self.report()
        self.assertEqual(out["HOLD_REASON"], "UNREVIEWED_NODE_IMAGE")
        self.assertEqual(out["HOST_INSTALL_AUTHORIZED"], "NO")

    def test_local_test_image_cannot_claim_external_registry_pin(self):
        out = gate.audit(
            self.node, runtime=self.runtime, min_bytes=4096,
            expected_node_image="ghcr.io/aghajani82/smite-node@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        self.assertEqual(out["HOLD_REASON"], "LOCAL_TEST_IMAGE_CANNOT_SATISFY_PIN")

    def test_existing_tunnels_block_recreation_even_when_engine_absent(self):
        (self.data / "tunnels.json").write_text(json.dumps({
            "live": {"core": "frp", "spec": {"mode": "client", "token": "DONT_PRINT"}}
        }))
        out = self.report()
        self.assertEqual(out["PERSISTED_TUNNELS"], "EXISTING_DO_NOT_RESTART")
        self.assertEqual(out["HOST_PREFLIGHT"], "HOLD_EXISTING_TUNNELS")
        self.assertEqual(out["HOST_INSTALL_AUTHORIZED"], "NO")
        self.assertNotIn("DONT_PRINT", str(out))

    def test_preservation_receipts_hash_exact_bytes_without_leaking_tunnels(self):
        raw_id = "a" * 64
        self.runtime["Id"] = raw_id
        missing = self.report()
        self.assertEqual(missing["PERSISTED_TUNNEL_REGISTRY_SHA256"], "ABSENT")
        self.assertEqual(missing["NODE_CONTAINER_ID_SHA256"],
                         hashlib.sha256(raw_id.encode()).hexdigest())
        self.assertNotIn(raw_id, str(missing))

        saved = self.data / "tunnels.json"
        original = json.dumps({"live": {
            "core": "frp", "spec": {"token": "SECRET_TUNNEL_A", "port": 20182}
        }}).encode()
        saved.write_bytes(original)
        existing = self.report()
        self.assertEqual(existing["PERSISTED_TUNNELS"], "EXISTING_DO_NOT_RESTART")
        self.assertEqual(existing["HOST_PREFLIGHT"], "HOLD_EXISTING_TUNNELS")
        self.assertEqual(existing["PERSISTED_TUNNEL_REGISTRY_SHA256"],
                         hashlib.sha256(original).hexdigest())
        self.assertNotIn("SECRET_TUNNEL_A", str(existing))
        self.assertNotIn("20182", str(existing))
        self.assertEqual(existing["HOST_INSTALL_AUTHORIZED"], "NO")

        # Changing one byte of retained route data must change the receipt.
        changed = original.replace(b"20182", b"20183")
        saved.write_bytes(changed)
        drift = self.report()
        self.assertNotEqual(existing["PERSISTED_TUNNEL_REGISTRY_SHA256"],
                            drift["PERSISTED_TUNNEL_REGISTRY_SHA256"])
        self.assertEqual(drift["HOST_PREFLIGHT"], "HOLD_EXISTING_TUNNELS")
        self.assertEqual(drift["HOST_INSTALL_AUTHORIZED"], "NO")

    def test_empty_registry_and_missing_identity_are_not_falsely_attested(self):
        self.runtime["Id"] = "not-a-docker-id"
        self.assertEqual(self.report()["NODE_CONTAINER_ID_SHA256"], "UNVERIFIED")
        saved = self.data / "tunnels.json"
        saved.write_bytes(b"{}")
        local = self.report()
        self.assertEqual(local["PERSISTED_TUNNELS"], "ZERO")
        self.assertEqual(local["PERSISTED_TUNNEL_REGISTRY_SHA256"],
                         hashlib.sha256(b"{}").hexdigest())
        self.assertNotEqual(local["PERSISTED_TUNNEL_REGISTRY_SHA256"], "ABSENT")
        self.assertEqual(local["HOST_INSTALL_AUTHORIZED"], "NO")

    def test_bad_saved_tunnels_do_not_produce_a_trusted_registry_hash(self):
        self.runtime["Id"] = "b" * 64
        saved = self.data / "tunnels.json"
        saved.write_text('{"broken": {"core": "frp", "spec": "not-a-dict"}}')
        state = self.report()
        self.assertEqual(state["HOST_PREFLIGHT"], "HOLD")
        self.assertEqual(state["PERSISTED_TUNNEL_REGISTRY_SHA256"], "UNVERIFIED")
        self.assertEqual(state["HOLD_REASON"], "UNTRUSTED_TUNNEL_REGISTRY")

    def test_wrong_source_mount_and_docker_port_bindings_are_held(self):
        self.runtime["Mounts"][0]["Source"] = str(self.root / "wrong")
        self.assertEqual(self.report()["HOLD_REASON"], "WRONG_NODE_CONFIG_VOLUME")
        self.runtime["Mounts"][0]["Source"] = str(self.cfg)
        self.runtime["HostConfig"]["PortBindings"] = {"8888/tcp": [{"HostPort": "8888"}]}
        self.assertEqual(self.report()["HOLD_REASON"], "PUBLISHED_DOCKER_PORTS")

    def test_named_volume_mismatch_and_duplicate_mounts_fail_closed(self):
        data = self.runtime["Mounts"][1]
        data["Name"] = "unrelated-data-volume"
        self.assertEqual(self.report()["HOLD_REASON"], "WRONG_NODE_NAMED_VOLUME")
        data["Name"] = "smite-node-data"
        data["Type"] = "bind"
        self.assertEqual(self.report()["HOLD_REASON"], "WRONG_NODE_NAMED_VOLUME")
        data["Type"] = "volume"
        data["Driver"] = "local"
        self.runtime["Mounts"].append(dict(data))
        self.assertEqual(self.report()["HOLD_REASON"], "DUPLICATE_PERSISTENT_MOUNT")
        self.runtime["Mounts"].pop()

    def test_actual_compose_must_declare_named_volume(self):
        (self.node / "docker-compose.yml").write_text(
            COMPOSE.replace("      - node-data:/var/lib/smite-node\n", "")
        )
        self.assertEqual(self.report()["HOLD_REASON"], "UNTRUSTED_NODE_COMPOSE")

    def test_json_report_redacts_every_sensitive_source(self):
        with patch.object(gate, "read_only_docker_inspect", return_value=self.runtime):
            report = self.report()
        blob = json.dumps(report)
        self.assertNotIn("DONT_PRINT", blob)
        self.assertNotIn(str(self.data), blob)
        self.assertNotIn(str(self.cfg), blob)
        self.assertNotIn("TOKEN", blob)
        self.assertEqual(report["HOST_INSTALL_AUTHORIZED"], "NO")

    def test_not_running_unreviewed_image_and_bridge_mode_held(self):
        self.runtime["State"]["Running"] = False
        self.assertEqual(self.report()["HOLD_REASON"], "NODE_NOT_RUNNING")
        self.runtime["State"]["Running"] = True
        self.runtime["Config"]["Image"] = "unreviewed/node:latest"
        self.assertEqual(self.report()["HOLD_REASON"], "UNREVIEWED_NODE_IMAGE")
        self.runtime["Config"]["Image"] = "smite-node:stage15-local"
        self.runtime["HostConfig"]["NetworkMode"] = "bridge"
        self.assertEqual(self.report()["HOLD_REASON"], "UNEXPECTED_NODE_NETWORK")

    def test_duplicate_managed_env_and_unsafe_compose_fails_closed(self):
        (self.node / ".env").write_text(ENV + "SMITE_AGENT_AUTH_MODE=legacy\n")
        self.assertEqual(self.report()["HOLD_REASON"], "DUPLICATE_CORE_ENV")
        (self.node / ".env").write_text(ENV)
        (self.node / "docker-compose.yml").write_text(COMPOSE + "    ports:\n      - 8888:8888\n")
        self.assertEqual(self.report()["HOLD_REASON"], "UNTRUSTED_NODE_COMPOSE")

    def test_invalid_saved_tunnels_symlink_and_low_disk_fails(self):
        saved = self.data / "tunnels.json"
        saved.write_text('{"a": {"spec": {"mode": "client"}}}')
        self.assertEqual(self.report()["HOLD_REASON"], "UNTRUSTED_TUNNEL_REGISTRY")
        saved.unlink()
        saved.symlink_to(self.node / ".env")
        self.assertEqual(self.report()["HOLD_REASON"], "LOCAL_SYMLINK")
        saved.unlink()
        self.assertEqual(
            gate.audit(self.node, runtime=self.runtime, min_bytes=10**15)["HOLD_REASON"],
            "INSUFFICIENT_FREE_DISK",
        )

    def test_frp_process_names_and_start_ticks_are_hashed_without_argv(self):
        proc = self.root / "proc"
        proc.mkdir()

        def put(pid, name, start):
            p = proc / str(pid)
            p.mkdir()
            (p / "comm").write_text(name + "\n")
            fields = ["S"] + ["0"] * 18 + [str(start)]
            (p / "stat").write_text(
                f"{pid} ({name}) " + " ".join(fields) + "\n"
            )
        put(1001, "frpc", 312)
        put(1002, "frps", 445)
        put(999, "unrelated", 122)
        result = gate.frp_process_footprint(proc)
        self.assertEqual(result["FRPC_PROCESS_LOCAL"], "OBSERVED_UNATTESTED")
        self.assertEqual(result["FRPS_PROCESS_LOCAL"], "OBSERVED_UNATTESTED")
        expected = hashlib.sha256(b"1001:312").hexdigest()
        self.assertEqual(result["FRPC_INSTANCE_SHA256"], expected)
        self.assertNotIn("1001", str(result))
        self.assertNotIn("1002", str(result))
        put(1003, "frps", 500)
        changed = gate.frp_process_footprint(proc)
        self.assertNotEqual(result["FRPS_INSTANCE_SHA256"],
                            changed["FRPS_INSTANCE_SHA256"])
        (proc / "1003" / "stat").write_text("invalid process stat")
        rejected = gate.frp_process_footprint(proc)
        self.assertEqual(rejected["FRPC_PROCESS_LOCAL"], "UNVERIFIED")
        self.assertEqual(rejected["FRPS_INSTANCE_SHA256"], "UNVERIFIED")

    def test_frp_process_symlink_metadata_never_read(self):
        proc = self.root / "proc"
        proc.mkdir()
        p = proc / "24"
        p.mkdir()
        (self.root / "secret").write_text("TOP_SECRET")
        (p / "comm").symlink_to(self.root / "secret")
        state = gate.frp_process_footprint(proc)
        self.assertEqual(state["FRPC_PROCESS_LOCAL"], "UNVERIFIED")
        self.assertNotIn("TOP_SECRET", str(state))

    def test_broker_socket_footprint_requires_exact_root_socket_shape(self):
        socket_path = self.root / "smite" / "xhttp-broker.sock"
        parent = SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o750, st_uid=0, st_gid=39100)
        entry = SimpleNamespace(
            st_mode=stat.S_IFSOCK | 0o660, st_uid=0, st_gid=39100,
            st_nlink=1, st_dev=42, st_ino=77)

        def fake_stat(path):
            if path == socket_path.parent:
                return parent
            if path == socket_path:
                return entry
            raise AssertionError("UNEXPECTED_SOCKET_PATH")

        good = gate.broker_socket_footprint(socket_path, stat_fn=fake_stat)
        self.assertEqual(good["BROKER_SOCKET_LOCAL"], "PRESENT_UNATTESTED")
        self.assertEqual(good["BROKER_SOCKET_ID_SHA256"],
                         hashlib.sha256(b"42:77").hexdigest())
        self.assertNotIn("39100", str(good))

        entry.st_mode = stat.S_IFLNK | 0o777
        bad = gate.broker_socket_footprint(socket_path, stat_fn=fake_stat)
        self.assertEqual(bad["BROKER_SOCKET_LOCAL"], "UNTRUSTED")
        self.assertEqual(bad["BROKER_SOCKET_ID_SHA256"], "UNVERIFIED")
        entry.st_mode = stat.S_IFSOCK | 0o660
        entry.st_uid = 1000
        self.assertEqual(
            gate.broker_socket_footprint(socket_path, stat_fn=fake_stat)[
                "BROKER_SOCKET_LOCAL"], "UNTRUSTED")

        def missing(path):
            raise FileNotFoundError(path)
        self.assertEqual(gate.broker_socket_footprint(
            socket_path, stat_fn=missing)["BROKER_SOCKET_LOCAL"], "ABSENT")

    def test_wss_edge_local_journal_is_private_committed_or_unverified(self):
        data = json.dumps({
            "schema": 1, "state": "COMMITTED",
            "peer": "PRIVATE_PEER_ADDRESS", "domain": "secret.example",
        }).encode()
        path = Mock()
        path.exists.return_value = True
        path.is_symlink.return_value = False
        path.lstat.return_value = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_uid=0,
            st_nlink=1, st_size=len(data))
        with patch.object(gate, "_local_file", return_value=data):
            good = gate.wss_edge_footprint(path)
        self.assertEqual(good["WSS_EDGE_JOURNAL_LOCAL"],
                         "COMMITTED_LOCAL_UNATTESTED")
        self.assertEqual(good["WSS_EDGE_JOURNAL_SHA256"],
                         hashlib.sha256(data).hexdigest())
        self.assertNotIn("PRIVATE_PEER_ADDRESS", str(good))
        self.assertNotIn("secret.example", str(good))

        with patch.object(gate, "_local_file",
                          return_value=b'{"schema":1,"state":"COMMITTED","state":"HOLD"}'):
            bad = gate.wss_edge_footprint(path)
        self.assertEqual(bad["WSS_EDGE_JOURNAL_LOCAL"], "UNVERIFIED")
        self.assertEqual(bad["WSS_EDGE_JOURNAL_SHA256"], "UNVERIFIED")
        path.lstat.return_value.st_mode = stat.S_IFREG | 0o644
        self.assertEqual(gate.wss_edge_footprint(path)[
            "WSS_EDGE_JOURNAL_LOCAL"], "UNVERIFIED")
        path.exists.return_value = False
        self.assertEqual(gate.wss_edge_footprint(path)[
            "WSS_EDGE_JOURNAL_LOCAL"], "ABSENT")

    def test_ir_saved_tunnels_still_hold_with_local_process_socket_hints(self):
        self.use_rc6_ir()
        (self.data / "tunnels.json").write_text(json.dumps({
            "frp": {"core": "frp", "spec": {"secret": "SHOULD_NOT_PRINT"}}
        }))
        with patch.object(gate, "_read_rc6_journal_bytes",
                          return_value=json.dumps(RC6_JOURNAL).encode()), \
             patch.object(gate, "frp_process_footprint",
                          return_value={
                              "FRPC_PROCESS_LOCAL": "OBSERVED_UNATTESTED",
                              "FRPS_PROCESS_LOCAL": "OBSERVED_UNATTESTED",
                              "FRPC_INSTANCE_SHA256": "a"*64,
                              "FRPS_INSTANCE_SHA256": "b"*64,
                          }), \
             patch.object(gate, "broker_socket_footprint",
                          return_value={
                              "BROKER_SOCKET_LOCAL": "PRESENT_UNATTESTED",
                              "BROKER_SOCKET_ID_SHA256": "c"*64,
                          }), \
             patch.object(gate, "wss_edge_footprint",
                          return_value={
                              "WSS_EDGE_JOURNAL_LOCAL": "COMMITTED_LOCAL_UNATTESTED",
                              "WSS_EDGE_JOURNAL_SHA256": "d"*64,
                          }):
            report = self.report()
        self.assertEqual(report["FRPC_INSTANCE_SHA256"], "a"*64)
        self.assertEqual(report["BROKER_SOCKET_ID_SHA256"], "c"*64)
        self.assertEqual(report["WSS_EDGE_JOURNAL_SHA256"], "d"*64)
        self.assertEqual(report["PERSISTED_TUNNELS"], "EXISTING_DO_NOT_RESTART")
        self.assertEqual(report["HOST_PREFLIGHT"], "HOLD_EXISTING_TUNNELS")
        self.assertEqual(report["HOST_INSTALL_AUTHORIZED"], "NO")
        self.assertNotIn("SHOULD_NOT_PRINT", str(report))

    def test_node_env_and_docker_data_can_never_be_logged(self):
        cli = subprocess.run([sys.executable, "-B", str(SCRIPT), "--node-dir", str(self.node)],
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(cli.returncode, 2)  # Root ownership/real Docker gate.
        self.assertIn("HOST_INSTALL_AUTHORIZED=NO", cli.stdout)
        self.assertIn("BACKHAUL_ACTIVATION_GATE=HOLD", cli.stdout)
        self.assertNotIn("DONT_PRINT", cli.stdout + cli.stderr)

    def test_docker_inspect_command_is_the_only_allowed_read_only_probe(self):
        out = Mock(returncode=0, stdout=json.dumps([self.runtime]), stderr="DONT_PRINT")
        called = []
        def fake_run(args, **kwargs):
            called.append(args)
            return out
        found = gate.read_only_docker_inspect(runner=fake_run)
        self.assertEqual(found["Name"], "/smite-node")
        self.assertEqual(called, [["docker", "inspect", "--type=container", "smite-node"]])
        with self.assertRaises(gate.GateHold):
            gate.read_only_docker_inspect(name="smite-node;rm -rf /", runner=fake_run)
        self.assertEqual(len(called), 1)

    def test_no_service_mutations_in_gate(self):
        body = SCRIPT.read_text()
        for fragment in ("docker compose up", "docker restart", "systemctl restart",
                         "subprocess.Popen", "os.system(", "curl ", "iptables ",
                         "nginx -s", "ssh ", "sudo "):
            self.assertNotIn(fragment, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
