#!/usr/bin/env python3
"""Disposable runner only: retained Panel upgrade with real signed images."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

if os.environ.get("UOPTI_DISPOSABLE_DOCKER_LAB") != "YES":
    raise SystemExit("HOLD: DISPOSABLE_DOCKER_LAB_REQUIRED")

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "modules" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rt = load("smite-rc7-wss-runtime")
rt.select_rc9()
panel = load("smite-rc9-retained-panel")
original = load("smite-managed-frp-control").RC9_PANEL_IMAGE


def await_panel(expected):
    for _ in range(60):
        obj = rt.inspect_container("smite-panel")
        if obj["State"].get("Health", {}).get("Status") == "healthy":
            assert obj["Config"]["Image"] == expected
            return obj
        time.sleep(2)
    raise AssertionError("Panel did not become healthy")


def exercise(work, baseline_source):
    base = work / "docker-compose.yml"
    original_source = baseline_source.read_text()
    variable = 'image: ghcr.io/zzedix/smite-panel:${SMITE_VERSION:-latest}'
    assert original_source.count(variable) == 1
    base.write_text(original_source.replace(variable, "image: " + original))
    config = work / "docker-compose.signed-control.yml"
    config.write_text("""services:
  smite-panel:
    healthcheck:
      interval: 2s
  smite-node:
    image: alpine:3.21
    container_name: smite-node
    network_mode: none
    command: ["sleep", "900"]
""")
    (work / ".env").write_text(
        "PANEL_PORT=18300\nPANEL_HOST=127.0.0.1\nPANEL_DOMAIN=panel.example.test\n"
        "SMITE_VERSION=2.0.0-rc.9\nSMITE_PANEL_AGENT_AUTH_MODE=signed\n"
        "SMITE_ENGINE_MANAGEMENT_MODE=managed\n"
    )
    for path in ("panel/data", "panel/certs"):
        (work / path).mkdir(parents=True)
    doc = {"role": "ir", "state": "COMMITTED", "project": "uopti_rc6_" + "0" * 32,
           "baseline": {"smite-panel": {"files": [str(base), str(config)]}}}
    baseline = doc["baseline"]["smite-panel"]
    with patch.object(rt.p, "PANEL", work), patch.object(panel, "STATE", work / "receipt"):
        wss = rt.overlay_path("smite-panel")
        wss.write_text(rt.p.overlay_bytes("smite-panel"))
        command = rt.compose("smite-panel", doc, True)
        try:
            rt.run([*command, "up", "-d", "--no-build", "smite-panel", "smite-node"])
            before = await_panel(original)
            node = rt.inspect_container("smite-node")["Id"]
            baseline["image_id"] = before["Image"]
            baseline["signature"] = rt.runtime_signature(before, canonical_dns=True)
            baseline["signature_policy"] = rt.DNS_EMPTY_POLICY
            baseline["compose_digest"] = rt.compose_digest(json.loads(
                rt.run(rt.compose("smite-panel", doc, False) + ["config", "--format", "json"])))
            path = panel.overlay(rt)
            path.write_bytes(panel.overlay_bytes())
            _, new = panel.compose_commands(rt, doc, installed=True)
            panel.recreate(rt, new)
            active = await_panel(panel.IMAGE)
            with patch.object(panel, "read_record", return_value={
                "phase": "COMMITTED", "image_id": active["Image"], "wss_sha": "fixture"
            }), patch.object(panel, "wss_sha", return_value="fixture"):
                panel.original_identity(rt, active, doc, original)
                try:
                    rt.check_runtime_signature(active, baseline)
                except rt.Hold:
                    for section in ("Config", "HostConfig", "Mounts"):
                        if active[section] != before[section]:
                            print("Different fixture section:", section)
                            if section != "Mounts":
                                print("Different keys:", sorted(key for key in active[section]
                                      if active[section][key] != before[section].get(key)))
                    raise
            assert rt.inspect_container("smite-node")["Id"] == node
            panel.recreate(rt, command)
            rt.check_runtime_signature(await_panel(original), baseline)
            assert rt.inspect_container("smite-node")["Id"] == node
            print("RC9_REAL_PANEL_COMPOSE_UPGRADE_AND_ROLLBACK=PASS")
        finally:
            subprocess.run(command + ["down"], check=False)


for image in (original, panel.IMAGE):
    rt.run(["docker", "pull", image], timeout=300)
trusted_lab = Path("/root")
rt.trusted_path(trusted_lab, directory=True)
with tempfile.TemporaryDirectory(prefix="retained-panel-docker-", dir=trusted_lab) as temp:
    exercise(Path(temp), Path(sys.argv[1]))
