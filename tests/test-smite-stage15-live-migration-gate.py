"""Offline migration gate regressions. Never needs Docker, root, IR or KH."""
import importlib.util
import pathlib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-stage15-live-migration-gate.py"
spec = importlib.util.spec_from_file_location("stage15_live_migration_gate", SOURCE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def runtime(image, *, running=True, healthy="healthy", restarts=0):
    return {"Image": image, "State": {"Running": running,
            "Health": {"Status": healthy}}, "RestartCount": restarts}


class GateTests(unittest.TestCase):
    def test_panel_compose_only_and_host_network(self):
        panel = {"Config": {"Labels": {
            "com.docker.compose.project.config_files": ",".join([
                "/opt/smite/docker-compose.yml",
                "/opt/smite/docker-compose.signed-control.yml",
                "/opt/smite/docker-compose.wss-stage15.yml"
            ])}}}
        with mock.patch.object(gate, "command", return_value=
                '{"services":{"smite-panel":{"network_mode":"host"}}}') as cmd:
            gate.panel_compose_only(panel)
            self.assertNotIn("up", cmd.call_args.args)
            self.assertNotIn("restart", cmd.call_args.args)
        with mock.patch.object(gate, "command", return_value=
                '{"services":{"smite-panel":{"network_mode":"host"},'
                '"smite-node":{"network_mode":"host"}}}'):
            with self.assertRaisesRegex(gate.Hold, "PANEL_COMPOSE_HAS_OTHER_SERVICES"):
                gate.panel_compose_only(panel)
        with mock.patch.object(gate, "command", return_value=
                '{"services":{"smite-panel":{"network_mode":"host",'
                '"depends_on":{"smite-node":{}}}}}'):
            with self.assertRaisesRegex(gate.Hold, "PANEL_HAS_DEPENDENCIES"):
                gate.panel_compose_only(panel)

    def test_image_health_and_restart_drift(self):
        gate.require_runtime(runtime(gate.NODE), gate.NODE)
        for changed in (
            runtime("sha256:other"), runtime(gate.NODE, running=False),
            runtime(gate.NODE, healthy="unhealthy"),
            runtime(gate.NODE, restarts=1),
        ):
            with self.assertRaises(gate.Hold):
                gate.require_runtime(changed, gate.NODE)

    def test_frps_singleton_exact_four_loopback_ports(self):
        sockets = "\n".join(
            f'LISTEN 0 4096 127.0.0.1:{port} 0.0.0.0:* users:(("frps",pid=131,fd=3))'
            for port in gate.OWNER_PORTS
        )
        observed = gate.listener_pids(sockets, gate.OWNER_PORTS, "frps")
        self.assertEqual(set().union(*observed.values()), {131})
        with self.assertRaisesRegex(gate.Hold, "UNEXPECTED_OWNER_LISTENER"):
            gate.listener_pids(sockets +
                '\nLISTEN 0 4096 127.0.0.1:9999 0.0.0.0:* users:(("frps",pid=131,fd=4))',
                gate.OWNER_PORTS, "frps")
        with self.assertRaisesRegex(gate.Hold, "UNEXPECTED_OWNER_LISTENER"):
            gate.listener_pids(sockets.replace('127.0.0.1:38658', '127.0.0.1:38659'),
                               gate.OWNER_PORTS, "frps")

    def test_public_frps_listener_is_rejected(self):
        sockets = "\n".join(
            f'LISTEN 0 4096 127.0.0.1:{port} 0.0.0.0:* users:(("frps",pid=131,fd=3))'
            for port in gate.OWNER_PORTS
        )
        with self.assertRaisesRegex(gate.Hold, "PUBLIC_OR_NON_LOOPBACK_FRPS"):
            gate.listener_pids(sockets.replace("127.0.0.1:7000", "0.0.0.0:7000"),
                               gate.OWNER_PORTS, "frps")

    def test_ir_audit_is_read_only_and_blocks_preview(self):
        panel = runtime(gate.IR_PANEL)
        node = runtime(gate.NODE)
        sockets = "\n".join(
            f'LISTEN 0 4096 127.0.0.1:{p} 0.0.0.0:* users:(("frps",pid=131,fd=3))'
            for p in gate.OWNER_PORTS
        )
        calls = []
        def inspect(name):
            return {"smite-panel": panel, "smite-node": node}[name]
        def command(*args):
            calls.append(args)
            return sockets
        with mock.patch.object(gate.os, "geteuid", return_value=0), \
             mock.patch.object(gate.socket, "gethostname", return_value="ir"), \
             mock.patch.object(gate, "inspect", side_effect=inspect), \
             mock.patch.object(gate, "panel_compose_only"), \
             mock.patch.object(gate, "process_ids",
                               side_effect=lambda name, executable=None: (
                                   {131, 555} if name == "smite-node" else {999})), \
             mock.patch.object(gate, "command", side_effect=command), \
             mock.patch("builtins.print") as printed:
            gate.audit("ir")
        text = "\n".join(" ".join(str(y) for y in c.args) for c in printed.call_args_list)
        self.assertIn("NODE_RECREATE_WITHOUT_MAINTENANCE=BLOCKED", text)
        self.assertIn("UNSIGNED_PREVIEW_ACTIVATION=DENIED", text)
        self.assertIn("LIVE_MIGRATION_AUTHORIZED=NO", text)
        self.assertEqual(calls, [("ss", "-Hlntp")])

    def test_kh_frpc_count_drift_blocks(self):
        node = runtime(gate.NODE)
        ui = runtime("sha256:unrelated", healthy="ignored")
        with mock.patch.object(gate.os, "geteuid", return_value=0), \
             mock.patch.object(gate.socket, "gethostname", return_value="kh"), \
             mock.patch.object(gate, "inspect",
                               side_effect=lambda name: {"smite-node": node,
                                                          "3xui-01": ui}[name]), \
             mock.patch.object(gate, "process_ids", return_value={13, 1318}):
            with self.assertRaisesRegex(gate.Hold, "KH_FRPC_COUNT_DRIFT"):
                gate.audit("kh")

    def test_immutable_no_apply_entry_point(self):
        source = SOURCE.read_text()
        self.assertNotIn("docker compose up", source)
        self.assertNotIn('"docker", "restart"', source)
        self.assertNotIn('"docker", "stop"', source)
        self.assertNotIn('"docker", "load"', source)
        self.assertNotIn("systemctl", source)
        self.assertNotIn("nginx -s reload", source)
        self.assertNotIn("sqlite3.connect", source)
        self.assertEqual(gate.main.__code__.co_argcount, 0)


if __name__ == "__main__":
    unittest.main()
