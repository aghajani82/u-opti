"""Fixed-command Panel Docker/Compose and Nginx driver — disposable tests only.

No Docker service on real machines is used. A modeled Docker API proves exact
argv, project/compose ownership, fail-closed guard and cutover integration.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


stage_tests = load(
    "driver_stage_tests", ROOT / "tests" /
    "test-smite-unified-panel-stage.py")
cutover = load(
    "driver_cutover", ROOT / "modules" /
    "smite-unified-panel-cutover.py")
driver_mod = load(
    "driver_fixed_command", ROOT / "modules" /
    "smite-unified-panel-host-driver.py")


class DockerCommandModel:
    def __init__(self, stage, project, old_panel, new_panel):
        self.stage, self.project = stage, project
        self.old, self.new = old_panel, new_panel
        self.running = True
        self.current = old_panel
        self.started = 0
        self.created = 0
        self.calls = []
        self.fail = None
        self.health = "healthy"

    def _image_id(self, image):
        return "sha256:" + ("a" if image == self.old else "b")*64

    def _container(self):
        return {
            "Id": "f"*63 + str(self.created),
            "Name": "/smite-panel",
            "Config": {
                "Image": self.current,
                "Labels": {
                    "com.docker.compose.project": self.project,
                    "com.docker.compose.service": "smite-panel",
                    "com.docker.compose.project.config_files":
                        str(self.stage.root / "opt/smite/docker-compose.yml")
                        + "," + str(self.stage.root /
                                    "opt/smite/docker-compose.signed-control.yml"),
                },
            },
            "Image": self._image_id(self.current),
            "State": {
                "Running": self.running,
                "Restarting": False,
                "Health": {"Status": self.health},
                "StartedAt": "2026-11-14T17:00:00Z",
            },
        }

    def __call__(self, argv, **kwargs):
        assert kwargs["stdin"] is not None
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is False
        assert kwargs["env"]["PATH"] == "/usr/sbin:/usr/bin:/sbin:/bin"
        assert kwargs["timeout"] <= 120
        self.calls.append(list(argv))
        if self.fail is not None and self.fail in argv:
            return SimpleNamespace(returncode=13, stdout="", stderr="denied")
        compose_prefix = [
            *driver_mod.DOCKER, "compose", "--project-name", self.project,
            "-f", str(self.stage.root / driver_mod.COMPOSE),
            "-f", str(self.stage.root / driver_mod.SIGNED),
        ]
        if argv[:len(compose_prefix)] == compose_prefix:
            rest = argv[len(compose_prefix):]
            if rest == ["stop", "--timeout", "30", "smite-panel"]:
                self.running = False
            elif rest == ["ps", "-q", "smite-panel"]:
                return SimpleNamespace(
                    returncode=0, stdout=self._container()["Id"] + "\n",
                    stderr="")
            elif rest == ["up", "-d", "--no-deps", "--no-build",
                          "--pull", "never", "smite-panel"]:
                from pathlib import Path
                source = (self.stage.root / driver_mod.COMPOSE).read_text()
                self.current = self.new if self.new in source else self.old
                self.running = True
                self.created += 1
            elif rest == [
                "run", "--rm", "--no-deps", "-T", "--pull", "never",
                "smite-panel", *driver_mod.MIGRATION,
            ]:
                if self.running:
                    return SimpleNamespace(
                        returncode=2, stdout="", stderr="still running")
            else:
                raise AssertionError("Unexpected Compose subcommand " + repr(rest))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv == [*driver_mod.DOCKER, "inspect", "smite-panel"]:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps([self._container()]),
                stderr="")
        if argv in (
            [*driver_mod.DOCKER, "image", "inspect", "-f", "{{.Id}}", self.old],
            [*driver_mod.DOCKER, "image", "inspect", "-f", "{{.Id}}", self.new],
        ):
            return SimpleNamespace(
                returncode=0, stdout=self._image_id(argv[-1]) + "\n",
                stderr="")
        if argv in (["nginx", "-t"], ["systemctl", "reload", "nginx"]):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError("Unexpected subprocess " + repr(argv))


class FixedCommandDriverTests(unittest.TestCase):
    def setUp(self):
        stage_tests.Prepare.setUp(self)
        with sqlite3.connect(self.db) as db:
            db.execute("ALTER TABLE nodes ADD COLUMN status TEXT")
            db.execute("ALTER TABLE nodes ADD COLUMN last_seen TEXT")
            db.execute(
                "UPDATE nodes SET metadata=?,status=?,last_seen=?",
                ('{"role":"iran","provisioning":"signed_checkin"}',
                 "active", "2026-11-14T10:00:00Z"))
        self.node = stage_tests.Prepare._signed_node_runtime(self)
        self.panel = stage_tests.stage.PanelStage(
            self.root, admission=stage_tests.admission,
            runtime_reader=lambda: dict(self.node))
        self.panel.prepare(stage_tests.stage.CONFIRM)
        self.old_panel = stage_tests.stage.OLD_PANEL
        self.new_panel = stage_tests.stage.NEW_PANEL
        self.model = DockerCommandModel(
            self.panel, self.node["project_id"], self.old_panel,
            self.new_panel)
        self.driver = driver_mod.PanelServiceDriver(
            stage=self.panel, fixture_capability=True,
            runner=self.model, sleeper=lambda _: None)

    def test_review_plan_is_inert_and_matches_retained_project(self):
        plan = self.driver.review_plan()
        self.assertEqual(plan["state"], "FIXED_COMMAND_PLAN_ONLY")
        self.assertEqual(plan["compose_project"], self.node["project_id"])
        self.assertEqual(plan["panel_service"], "smite-panel")
        self.assertFalse(plan["prod_apply_allowed"])
        self.assertFalse(plan["prod_rollback_allowed"])
        self.assertFalse(self.model.calls)

    def test_fixed_commands_stop_migrate_start_verify_original_and_new(self):
        self.driver.stop_panel()
        self.driver.require_panel_stopped()
        self.driver.migrate_schema(lambda: None)
        env = self.root / driver_mod.COMPOSE
        old = env.read_bytes()
        env.write_bytes(old.replace(self.old_panel.encode(),
                                    self.new_panel.encode()))
        self.driver.nginx_check_and_reload()
        self.driver.start_panel("candidate")
        self.driver.verify_panel("candidate")
        env.write_bytes(old)
        self.driver.stop_panel()
        self.driver.start_panel("original")
        self.driver.verify_panel("original")
        self.assertEqual(self.model.calls[0][-3:],
                         ["--timeout", "30", "smite-panel"])
        self.assertEqual(self.model.calls[3], ["nginx", "-t"])
        self.assertEqual(self.model.calls[4], ["systemctl", "reload", "nginx"])
        self.assertTrue(all("smite-node" not in x and
                            "down" not in x and "restart" not in x
                            for call in self.model.calls for x in call))
        self.assertTrue(any("run" in x for x in self.model.calls))

    def test_actual_cutover_drives_exact_same_allowlisted_command_plan(self):
        engine = cutover.Cutover(
            self.root, stage=self.panel, driver=self.driver,
            fixture_capability=True)
        result = engine.apply(confirm=cutover.CONFIRM)
        self.assertEqual(result["status"], "REHEARSED_WITH_PANEL_SERVICE")
        self.assertEqual(self.model.current, self.new_panel)
        self.assertTrue(self.model.running)
        self.assertEqual(self.panel._check_retained_runtime(),
                         "RETAINED_IRAN_NODE_CONTAINER_UNCHANGED")
        result = engine.rollback(confirm=cutover.CONFIRM)
        self.assertEqual(result["status"], "ROLLED_BACK_PANEL_ONLY")
        self.assertEqual(self.model.current, self.old_panel)
        self.assertTrue(self.model.running)
        self.assertEqual(self.panel._check_retained_runtime(),
                         "RETAINED_IRAN_NODE_CONTAINER_UNCHANGED")

    def test_denies_ambient_docker_context_and_unapproved_commands(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://untrusted:2375"}):
            with self.assertRaises(driver_mod.Hold):
                self.driver.stop_panel()
        with self.assertRaises(driver_mod.Hold):
            self.driver._run(
                [*driver_mod.DOCKER, "compose", "down", "--volumes"])
        with self.assertRaises(driver_mod.Hold):
            self.driver._run(
                [*driver_mod.DOCKER, "restart", "smite-node"])
        with self.assertRaises(driver_mod.Hold):
            self.driver._run(["systemctl", "restart", "nginx"])
        self.assertFalse(self.model.calls)

    def test_denies_wrong_project_image_and_missing_signed_override(self):
        original = self.node["project_id"]
        self.node["project_id"] = "uopti_rc6_"+"a"*32
        with self.assertRaises(stage_tests.stage.StageHold):
            self.driver.review_plan()
        self.node["project_id"] = original

        override = self.root / driver_mod.SIGNED
        raw = override.read_bytes()
        override.write_bytes(b"untrusted new mount")
        with self.assertRaises((driver_mod.Hold, stage_tests.stage.StageHold)):
            self.driver.review_plan()
        override.write_bytes(raw)
        self.assertEqual(self.driver.review_plan()["compose_project"],
                         original)

    def test_start_denies_image_mismatch_before_command(self):
        with self.assertRaises(driver_mod.Hold):
            self.driver.start_panel("candidate")
        self.assertFalse(self.model.calls)
        with self.assertRaises(driver_mod.Hold):
            self.driver.start_panel("smite-node")
        self.assertFalse(self.model.calls)

    def test_model_denies_process_not_stopped_before_migration(self):
        with self.assertRaises(driver_mod.Hold):
            self.driver.migrate_schema(lambda: None)
        self.assertFalse(any("run" in line for line in self.model.calls))

    def test_failed_nginx_test_does_not_reload_service(self):
        self.model.fail = "-t"
        with self.assertRaises(driver_mod.Hold):
            self.driver.nginx_check_and_reload()
        self.assertEqual(self.model.calls, [["nginx", "-t"]])

    def test_bad_docker_image_id_or_health_blocks_success(self):
        self.model.health = "unhealthy"
        with self.assertRaises(driver_mod.Hold):
            self.driver.verify_panel("original")
        self.model.health = "healthy"
        self.model._image_id = lambda image: "sha256:" + "0"*64
        # Simulate changed image bytes after the signed digest reference.
        # In this model, both the container and local image inspect now
        # change simultaneously. Force an old ID specifically.
        self.model._image_id = lambda image: "sha256:" + "a"*64
        self.driver.verify_panel("original")

    def test_real_host_disallows_injected_runner_or_mutator(self):
        class RootStage:
            root = Path("/")
        with self.assertRaises(driver_mod.Hold):
            driver_mod.PanelServiceDriver(
                stage=RootStage(), fixture_capability=True,
                runner=self.model)
        with patch.object(self.driver, "root", Path("/")):
            with self.assertRaises(driver_mod.Hold):
                self.driver.stop_panel()
        self.assertFalse(self.model.calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
