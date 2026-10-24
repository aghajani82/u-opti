#!/usr/bin/env python3
"""RC.2 WSS edge real temporary-filesystem / fake systemd+nginx tests."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"modules/smite-rc2-frp-wss-edge-executor.py"
spec=importlib.util.spec_from_file_location("wss_edge_tx",PATH)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

BACKEND=(
    "# Managed by U-OPTI - Smite Panel TLS backend\n"
    "server {\n"
    "    listen 127.0.0.1:8443 ssl;\n"
    "    server_name ir.kolbe1.ir;\n"
    "    ssl_certificate /etc/letsencrypt/live/ir.kolbe1.ir/fullchain.pem;\n"
    "    location = /custom/abc {\n"
    "        proxy_pass http://127.0.0.1:32000;\n"
    "    }\n"
    "    location / {\n"
    "        proxy_pass http://127.0.0.1:8000;\n"
    "    }\n"
    "}\n"
)
MAP=(
    '# U-OPTI FRP TLS/SNI allowlist (SNI + source IPv4 required)\n'
    '    "old.example.org|8.8.8.8" 127.0.0.1:7001;\n'
)
STREAM=(
    "# Managed by U-OPTI - Smite TCP/443 SNI gateway\n"
    'stream {\n'
    '    map "$ssl_preread_server_name|$remote_addr" $uopti_frp_canary_backend {\n'
    '        include /etc/nginx/u-opti-smite-frp-sni-map.conf;\n'
    '        default $uopti_smite_backend;\n'
    '    }\n'
    '    server {\n'
    '        listen 443;\n'
    '        ssl_preread on;\n'
    '        proxy_pass $uopti_frp_canary_backend;\n'
    '    }\n'
    '}\n'
)
IP="8.8.4.4"

class EdgeTransaction(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="rc2-wss-edge-test-")
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        self.nginx=root/"nginx";self.nginx.mkdir(mode=0o700)
        self.state_root=root/"state";self.state_root.mkdir(mode=0o700)
        self.tls=self.nginx/"backend.conf";self.tls.write_text(BACKEND)
        self.stream=self.nginx/"stream.conf";self.stream.write_text(STREAM)
        self.map=self.nginx/"map.conf";self.map.write_text(MAP)
        # The planner resolves the active include path; the fake stream must
        # point to the corresponding isolated temporary map, not /etc/nginx.
        self.stream.write_text(STREAM.replace(
            "/etc/nginx/u-opti-smite-frp-sni-map.conf",str(self.map)))
        self.alt=self.nginx/"alt.conf"
        self.state=self.state_root/"wss"
        self.log=[]
        objs = [
            (mod,"STATE",self.state),
            (mod,"JOURNAL",self.state/"record.json"),
            (mod,"OLD_MAP",self.state/"stream-map.before"),
            (mod,"LOCK",root/"lock"),
            (mod.edge,"TLS_SOURCE",self.tls),
            (mod.edge,"STREAM_SOURCE",self.stream),
            (mod.edge,"FRP_MAP",self.map),
            (mod.edge,"ALT_CANDIDATE",self.alt),
        ]
        for obj,name,value in objs:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        def safe_file(path,limit=mod.MAX_BYTES):
            if path.is_symlink() or not path.is_file():
                raise mod.Hold("UNTRUSTED_FILE")
            return path.read_bytes()
        def safe_dir(path,private=False):
            st=path.lstat()
            if not stat.S_ISDIR(st.st_mode):
                raise mod.Hold("UNSAFE_STATE_DIRECTORY")
            if private and stat.S_IMODE(st.st_mode)!=0o700:
                raise mod.Hold("UNSAFE_STATE_DIRECTORY_MODE")
        def fake_lock():
            return os.open(mod.LOCK,os.O_RDWR|os.O_CREAT,0o600)
        def run(command,timeout=30):
            self.log.append(tuple(command))
        self.fake_run=run
        for name,fn in [("safe_file",safe_file),("safe_dir",safe_dir),
                        ("lock",fake_lock),("verify_host",lambda:None),
                        ("run",run)]:
            p=patch.object(mod,name,fn);p.start();self.addCleanup(p.stop)
        p=patch.object(mod.edge,"loopback_port_free",lambda port:None)
        p.start();self.addCleanup(p.stop)

    def call_apply(self,**kwargs):
        mod.apply(IP,mod.sha(BACKEND.encode()),mod.sha(MAP.encode()),**kwargs)

    def test_commits_preserving_old_backend_and_rolls_back_exact_bytes(self):
        self.call_apply()
        record=mod.journal_record()
        self.assertEqual(record["state"],"COMMITTED")
        self.assertEqual(record["peer_ip"],IP)
        self.assertEqual(self.tls.read_text(),BACKEND)
        self.assertEqual(self.stream.read_text(),STREAM)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE(mod.JOURNAL.stat().st_mode),0o600)
        self.assertIn('location = /~!frp',self.alt.read_text())
        self.assertIn(f'"ir.kolbe1.ir|{IP}"',self.map.read_text())
        self.assertEqual(self.log.count(("systemctl","reload","nginx")),1)
        mod.verify()
        mod.rollback()
        self.assertEqual(self.map.read_text(),MAP)
        self.assertFalse(self.alt.exists())
        self.assertFalse(self.state.exists())
        self.assertEqual(self.tls.read_text(),BACKEND)
        self.assertEqual(self.stream.read_text(),STREAM)
        self.assertEqual(self.log.count(("systemctl","reload","nginx")),2)

    def test_wrong_pins_no_mutation(self):
        with self.assertRaisesRegex(mod.Hold,"PINNED_SOURCE_DRIFT"):
            mod.apply(IP,"0"*64,mod.sha(MAP.encode()))
        self.assertFalse(self.state.exists())
        self.assertFalse(self.alt.exists())
        self.assertEqual(self.map.read_text(),MAP)
        self.assertEqual(self.log,[])

    def test_simulated_power_loss_after_alt_is_explicitly_recoverable(self):
        with self.assertRaisesRegex(RuntimeError,"SIMULATED_POWER_LOSS"):
            self.call_apply(inject="after-alt")
        self.assertTrue(self.alt.exists())
        self.assertEqual(mod.journal_record()["state"],"PREPARED")
        with self.assertRaisesRegex(mod.Hold,"UNRESOLVED_WSS_JOURNAL"):
            self.call_apply()
        mod.recover()
        self.assertFalse(self.alt.exists())
        self.assertFalse(self.state.exists())
        self.assertEqual(self.map.read_text(),MAP)

    def test_simulated_power_loss_after_map_is_explicitly_recoverable(self):
        with self.assertRaisesRegex(RuntimeError,"SIMULATED_POWER_LOSS"):
            self.call_apply(inject="after-map")
        self.assertIn(IP,self.map.read_text())
        mod.recover()
        self.assertFalse(self.alt.exists())
        self.assertEqual(self.map.read_text(),MAP)

    def test_nginx_reload_failure_forces_rollback_and_no_second_apply(self):
        first={"count":0}
        def run(command,timeout=30):
            self.log.append(tuple(command))
            if command==["systemctl","reload","nginx"]:
                first["count"]+=1
                if first["count"]==1:
                    raise mod.Hold("SERVICE_OPERATION_FAILED")
        with patch.object(mod,"run",run):
            with self.assertRaisesRegex(mod.Hold,"EDGE_ACTIVATION_FAILED_ROLLED_BACK"):
                self.call_apply()
        self.assertEqual(self.map.read_text(),MAP)
        self.assertFalse(self.alt.exists())
        self.assertFalse(self.state.exists())
        self.assertEqual(first["count"],2)

    def test_oob_map_change_refuses_destructive_rollback(self):
        self.call_apply()
        self.map.write_text("modified by operator\n")
        with self.assertRaisesRegex(mod.Hold,"EXTERNAL_STREAM_MAP_DRIFT"):
            mod.rollback()
        self.assertTrue(self.alt.exists())
        self.assertTrue(mod.JOURNAL.exists())

    def test_oob_backend_change_refuses_destructive_rollback(self):
        self.call_apply()
        self.tls.write_text(BACKEND+"\n")
        with self.assertRaisesRegex(mod.Hold,"PROTECTED_NGINX_INPUT_DRIFT"):
            mod.rollback()
        self.assertTrue(mod.JOURNAL.exists())

    def test_recovery_cannot_roll_back_committed_state(self):
        self.call_apply()
        with self.assertRaisesRegex(mod.Hold,"USE_ROLLBACK_FOR_COMMITTED"):
            mod.recover()
        self.assertTrue(self.state.exists())

    def test_no_node_compose_or_firewall_changes(self):
        source=PATH.read_text()
        for forbidden in ("docker compose up", "--force-recreate",
                          "systemctl restart", "ufw ", "iptables ",
                          "/api/agent/tunnels/apply"):
            self.assertNotIn(forbidden,source)
        self.assertIn('SNAPSHOT_CONFIRM',source)
        self.assertIn('TRIAL_FLAG',source)
        self.assertIn('UNRESOLVED_WSS_JOURNAL',source)


if __name__=="__main__":
    unittest.main(verbosity=2)
