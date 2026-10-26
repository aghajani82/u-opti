#!/usr/bin/env python3
"""Validate real-Compose-derived isolated Node runtime is fail-closed."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULES=Path(__file__).resolve().parents[0]
f=MODULES/"smite-managed-backhaul-compose-fixture.py"
spec=importlib.util.spec_from_file_location("smite_ci_compose_fixture",f)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ComposeProof(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runner=Path(self.tmp.name)
        self.lab=self.runner/"backhaul-txn-fixture"
        self.lab.mkdir(mode=0o700)
        (self.lab/"EXPERIMENTAL-LAB").write_text("U-OPTI-BACKHAUL-ISOLATED-LAB-V1\n")
        (self.lab/"node").mkdir()
        (self.lab/"node/config").mkdir()
        (self.lab/"node-data").mkdir()
        self.source=self.lab/"reviewed"
        (self.source/"node/app").mkdir(parents=True)
        (self.source/"node/app/agent_auth.py").write_text("# fake reviewed source\n")
        (self.source/"node/main.py").write_text("# fake main\n")
        self.parsed={"services":{"smite-node":{
            "image":"ghcr.io/zzedix/smite-node:reviewed",
            "network_mode":"host",
            "cap_add":["NET_ADMIN"],
            "healthcheck":{"test":mod.HEALTH_TEST},
            "volumes":[
                {"type":"bind","source":str(self.lab/"node/config"),"target":"/etc/smite-node","read_only":False},
                {"type":"volume","source":"smite-node-data","target":"/var/lib/smite-node"},
            ],
        }}}
        self.env=patch.dict(os.environ,{"GITHUB_ACTIONS":"true",
                    "GITHUB_EVENT_NAME":"pull_request",
                    "GITHUB_REPOSITORY":"aghajani82/u-opti",
                    "RUNNER_TEMP":str(self.runner)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_absent_derived_compose_drops_all_host_privileges(self):
        obj=mod.checked(self.lab,"absent","12345",self.parsed,self.source)
        service=obj["services"]["smite-node"]
        self.assertEqual(service["network_mode"],"none")
        self.assertTrue(service["read_only"])
        self.assertEqual(service["cap_drop"],["ALL"])
        self.assertFalse(service.get("cap_add"))
        self.assertFalse(service.get("ports"))
        self.assertEqual(service["image"],mod.IMAGE)
        self.assertTrue(all(m["target"]!="/usr/local/bin/backhaul" for m in service["volumes"]))
        self.assertEqual(set(obj["services"]),{"smite-node"})
        self.assertIn("no-new-privileges:true",service["security_opt"])
        self.assertEqual(service["healthcheck"]["test"], mod.HEALTH_TEST)
        self.assertEqual(service["healthcheck"]["interval"], "2s")

    def test_ready_requires_exact_readonly_host_artifact(self):
        self.parsed["services"]["smite-node"]["volumes"].append({
            "type":"bind", "source":str(self.lab/"installed/backhaul"),
            "target":"/usr/local/bin/backhaul","read_only":True,
        })
        obj=mod.checked(self.lab,"ready","12345",self.parsed,self.source)
        mounts=obj["services"]["smite-node"]["volumes"]
        self.assertEqual(len([m for m in mounts if m["target"]=="/usr/local/bin/backhaul"]),1)
        self.assertTrue([m for m in mounts if m["target"]=="/usr/local/bin/backhaul"][0]["read_only"])
        self.parsed["services"]["smite-node"]["volumes"][-1]["read_only"]=False
        with self.assertRaisesRegex(mod.Hold,"UNVERIFIED_ENGINE_BIND"):
            mod.checked(self.lab,"ready","12345",self.parsed,self.source)

    def test_wrong_source_extra_service_public_ports_are_held(self):
        self.parsed["services"]["smite-node"]["volumes"][0]["source"]="/opt/production/node/config"
        with self.assertRaisesRegex(mod.Hold,"WRONG_CORE_CONFIG_SOURCE"):
            mod.checked(self.lab,"absent","12345",self.parsed,self.source)
        self.parsed["services"]["smite-node"]["volumes"][0]["source"]=str(self.lab/"node/config")
        self.parsed["services"]["second"]={"image":"unsafe"}
        with self.assertRaisesRegex(mod.Hold,"UNEXPECTED_COMPOSE_SERVICES"):
            mod.checked(self.lab,"absent","12345",self.parsed,self.source)
        self.parsed["services"].pop("second")
        self.parsed["services"]["smite-node"]["ports"]=["8888:8888"]
        with self.assertRaisesRegex(mod.Hold,"UNEXPECTED_PRODUCTION_NETWORK"):
            mod.checked(self.lab,"absent","12345",self.parsed,self.source)

    def test_unreviewed_unauthenticated_agent_healthcheck_denied(self):
        # A strict Node cannot use an unsigned Agent status healthcheck.
        self.parsed["services"]["smite-node"]["healthcheck"]["test"] = [
            "CMD", "python", "-c",
            "import urllib.request; urllib.request.urlopen('http://localhost:8888/api/agent/status')",
        ]
        with self.assertRaisesRegex(mod.Hold, "UNREVIEWED_NODE_HEALTHCHECK"):
            mod.checked(self.lab,"absent","12345",self.parsed,self.source)

    def test_frp_pair_isolated_only_when_both_exact_readonly_mounts_present(self):
        # FRP uses a different explicitly named lab, never production paths.
        renamed = self.runner / "uopti-official-frp-pair"
        self.lab.rename(renamed)
        self.lab = renamed
        self.source = self.lab / "reviewed"
        self.parsed["services"]["smite-node"]["volumes"][0]["source"] = str(
            self.lab / "node/config")
        mounts = self.parsed["services"]["smite-node"]["volumes"]
        for name in ("frpc", "frps"):
            mounts.append({
                "type": "bind",
                "source": str(self.lab / "installed/frp" / name),
                "target": "/usr/local/bin/" + name,
                "read_only": True,
            })
        ok = mod.checked(self.lab, "ready", "12345", self.parsed,
                         self.source, "frp")
        service = ok["services"]["smite-node"]
        self.assertEqual(service["container_name"], "uopti-managed-api-12345-ready")
        self.assertNotEqual(service["container_name"], "frps")
        self.assertEqual(service["network_mode"], "none")
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertNotIn("ports", service)
        created = {m["target"]: m for m in service["volumes"]}
        for name in ("frpc", "frps"):
            item = created["/usr/local/bin/" + name]
            self.assertEqual(item["source"], str(self.lab / "installed/frp" / name))
            self.assertTrue(item["read_only"])
        self.assertNotIn("/usr/local/bin/backhaul", created)
        mounts[-1]["read_only"] = False
        with self.assertRaisesRegex(mod.Hold, "UNVERIFIED_ENGINE_BIND"):
            mod.checked(self.lab, "ready", "12345", self.parsed, self.source, "frp")
        mounts.pop()
        with self.assertRaisesRegex(mod.Hold, "UNVERIFIED_ENGINE_BIND"):
            mod.checked(self.lab, "ready", "12345", self.parsed, self.source, "frp")

    def test_frp_and_backhaul_mount_mixing_is_denied(self):
        self.parsed["services"]["smite-node"]["volumes"].append({
            "type": "bind", "source": "/unsafe/frpc",
            "target": "/usr/local/bin/frpc", "read_only": True,
        })
        with self.assertRaisesRegex(mod.Hold, "UNEXPECTED_OTHER_ENGINE_MOUNT"):
            mod.checked(self.lab, "absent", "12345", self.parsed,
                        self.source, "backhaul")

    def test_not_pr_and_invalid_lab_never_accepted(self):
        with patch.dict(os.environ,{"GITHUB_ACTIONS":"false"}):
            with self.assertRaisesRegex(mod.Hold,"NOT_GITHUB_PR"):
                mod.checked(self.lab,"absent","12345",self.parsed,self.source)
        with self.assertRaisesRegex(mod.Hold,"INVALID_PHASE_OR_RUN_ID"):
            mod.checked(self.lab,"remove","12345",self.parsed,self.source)
        with self.assertRaisesRegex(mod.Hold,"INVALID_PHASE_OR_RUN_ID"):
            mod.checked(self.lab,"absent","123;rm",self.parsed,self.source)
        (self.lab/"EXPERIMENTAL-LAB").write_text("wrong\n")
        with self.assertRaisesRegex(mod.Hold,"LAB_MARKER_MISSING"):
            mod.checked(self.lab,"absent","12345",self.parsed,self.source)

    def test_not_an_onhost_runtime_executor(self):
        src=f.read_text()
        for denied in ("subprocess.run","docker compose up","systemctl","os.system(",
                       "cap_add\": [\"NET_ADMIN","network_mode\": \"host"):
            self.assertNotIn(denied,src)


if __name__=="__main__":
    unittest.main(verbosity=2)
