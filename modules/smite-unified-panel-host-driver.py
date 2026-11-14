#!/usr/bin/env python3
"""Fixed-command Iran Panel Docker/Compose and Nginx driver, release HOLD.

The only executable mode is an explicitly injected DISPOSABLE test root.
On a real host root='/' ONLY review_plan() is available. This is not an
operator approval token and never promotes the trial signed Panel image.

An independently approved release and host executor are still required.
Never touch smite-node, FRP, Backhaul, Sanaei or pairing/replay databases.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import time


DOCKER = ("docker", "--host", "unix:///var/run/docker.sock")
COMPOSE = "opt/smite/docker-compose.yml"
SIGNED = "opt/smite/docker-compose.signed-control.yml"
PANEL = "smite-panel"
MIGRATION = (
    "python3", "-m", "app.foreign_install_migration",
    "--migrate", "--confirm", "PREPARE-FOREIGN-INSTALL-TRIAL-SCHEMA",
)
DENIED_ENV = (
    "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG",
    "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH",
    "COMPOSE_PROJECT_NAME", "COMPOSE_FILE", "COMPOSE_PROFILES",
    "COMPOSE_ENV_FILES", "COMPOSE_PROJECT_DIRECTORY",
)
ALLOWED_STATES = ("candidate", "original")
CANONICAL = {
    "source", "project", "node_id", "node_started_at",
    "old_panel", "new_panel", "base_compose", "signed_compose",
}


class Hold(RuntimeError):
    pass


def deny():
    raise Hold("IR Panel fixed-command driver HOLD; live activation forbidden")


class PanelServiceDriver:
    def __init__(self, *, stage, fixture_capability=False, runner=None,
                 sleeper=None):
        self.stage = stage
        self.root = Path(stage.root)
        self._fixture = fixture_capability
        if self.root == Path("/"):
            if fixture_capability or runner is not None or sleeper is not None:
                deny()
        elif not fixture_capability or runner is None:
            deny()
        if self.root.is_symlink() or not self.root.is_absolute():
            deny()
        self._runner = runner or subprocess.run
        self._sleep = sleeper or time.sleep

    def _guard(self):
        # No live execution, including from direct calls to private methods.
        # A mocked "release_approved" boolean is NEVER an authorization.
        if self.root == Path("/") or not self._fixture:
            deny()
        if any(os.environ.get(k) for k in DENIED_ENV):
            deny()
        if self.stage.root != self.root:
            deny()
        self.stage.status()

    def _node(self):
        # Validated stage status rechecks exact retained Docker ID/StartedAt.
        self.stage.status()
        # The pre-existing stage private runtime snapshot contains no secret.
        path = self.stage.staging / "iran-node-runtime.json"
        if not path.is_file() or path.is_symlink():
            deny()
        try:
            evidence = json.loads(self.stage._read(
                str(path.relative_to(self.root)), mode=0o600, limit=2048))
            proof = self.stage._check_runtime_evidence(evidence)
        except (ValueError, TypeError, KeyError, OSError, AttributeError):
            deny()
        return proof

    def plan(self):
        """Read-only exact project and inputs; safe on an installed host."""
        proof = self._node()
        project = proof["project_id"]
        if not re.fullmatch(r"uopti_rc6_[a-f0-9]{32}", project):
            deny()
        files = (self.root / COMPOSE, self.root / SIGNED)
        for path in files:
            self.stage._parents(path)
            if path.is_symlink() or not path.is_file():
                deny()
        from importlib import util
        # Model/config have already been sealed by Stage.status.
        installed = self.stage._read(
            "opt/smite/docker-compose.signed-control.yml",
            mode=0o600, limit=32000)
        expected = (
            "services:\n"
            "  smite-panel:\n"
            "    volumes:\n"
            "      - /etc/u-opti/smite/panel-trusted-nodes:"
            "/etc/smite-panel/trusted-nodes:ro\n"
        ).encode("ascii")
        if installed != expected:
            deny()
        # Stage candidates are pinned images, not runtime-controlled tags.
        source_file = Path(__file__).with_name("smite-unified-panel-stage.py")
        spec = util.spec_from_file_location("panel_driver_constants", source_file)
        if spec is None or spec.loader is None:
            deny()
        mod = util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        current = self.stage._read(mod.COMPOSE_REL, limit=262144).decode("utf-8")
        original = self.stage._read(
            mod.STAGE_REL + "/before-panel-compose",
            mode=0o600, limit=262144).decode("utf-8")
        old_line = "    image: " + mod.OLD_PANEL
        new_line = "    image: " + mod.NEW_PANEL
        if (proof["install_source"] !=
                "9a1270b31e8d44f13d09b71ab6b9798410b09c12"
                or original.splitlines().count(old_line) != 1
                or original.splitlines().count(new_line) != 0
                or (current.splitlines().count(old_line),
                    current.splitlines().count(new_line)) not in ((1, 0), (0, 1))):
            deny()
        return {
            "source": mod.SOURCE,
            "project": project,
            "node_id": proof["container_id"],
            "node_started_at": proof["started_at"],
            "old_panel": mod.OLD_PANEL,
            "new_panel": mod.NEW_PANEL,
            "base_compose": str(files[0]),
            "signed_compose": str(files[1]),
        }

    def _command(self):
        info = self.plan()
        if set(info) != CANONICAL:
            deny()
        return [
            *DOCKER, "compose", "--project-name", info["project"],
            "-f", info["base_compose"],
            "-f", info["signed_compose"],
        ]

    def _run(self, argv, *, capture=False, timeout=60):
        self._guard()
        # This must never be callable with a Node/FRP/tunnel argument.
        if not isinstance(argv, list) or not all(
            isinstance(v, str) and v for v in argv
        ):
            deny()
        base = self._command()
        allowed = (
            base + ["stop", "--timeout", "30", PANEL],
            base + ["ps", "-q", PANEL],
            base + ["run", "--rm", "--no-deps", "-T", "--pull", "never",
                    PANEL, *MIGRATION],
            base + ["up", "-d", "--no-deps", "--no-build",
                    "--pull", "never", PANEL],
            [*DOCKER, "inspect", PANEL],
            [*DOCKER, "image", "inspect", "-f", "{{.Id}}",
             self.plan()["old_panel"]],
            [*DOCKER, "image", "inspect", "-f", "{{.Id}}",
             self.plan()["new_panel"]],
            ["nginx", "-t"],
            ["systemctl", "reload", "nginx"],
        )
        if argv not in allowed:
            deny()
        try:
            completed = self._runner(
                argv, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, check=False, timeout=timeout,
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                     "LANG": "C", "LC_ALL": "C"},
            )
            if completed.returncode != 0:
                deny()
            if capture:
                if not isinstance(completed.stdout, str) or len(
                    completed.stdout
                ) > 131072:
                    deny()
                return completed.stdout.strip()
            return ""
        except (subprocess.TimeoutExpired, OSError):
            deny()

    def _compose(self, *args, capture=False, timeout=60):
        return self._run(self._command() + list(args),
                         capture=capture, timeout=timeout)

    def _panel(self):
        raw = self._run([*DOCKER, "inspect", PANEL],
                        capture=True, timeout=15)
        try:
            objects = json.loads(raw)
            if not isinstance(objects, list) or len(objects) != 1:
                deny()
            obj = objects[0]
            if not isinstance(obj, dict):
                deny()
            cfg = obj["Config"]
            state = obj["State"]
            labels = cfg["Labels"]
            proof = self.plan()
            if (obj.get("Name") != "/" + PANEL
                    or labels.get("com.docker.compose.project") != proof["project"]
                    or labels.get("com.docker.compose.service") != PANEL
                    or labels.get("com.docker.compose.project.config_files") !=
                       proof["base_compose"] + "," + proof["signed_compose"]):
                deny()
            return obj
        except (ValueError, KeyError, TypeError, AttributeError):
            deny()

    def _expected(self, name):
        if name not in ALLOWED_STATES:
            deny()
        return self.plan()["new_panel" if name == "candidate" else "old_panel"]

    def stop_panel(self):
        self._guard()
        self._compose("stop", "--timeout", "30", PANEL)
        self.require_panel_stopped()

    def require_panel_stopped(self):
        self._guard()
        obj = self._panel()
        if obj["State"].get("Running") is not False:
            deny()

    def migrate_schema(self, callback=None):
        self._guard()
        if callback is not None:
            # Live source migration must come from the signed image, never
            # a caller-injected SQL callback. Fixture cutover supplies its
            # local schema executor, which is limited to the fake root.
            if self.root == Path("/") or not callable(callback):
                deny()
        self.require_panel_stopped()
        self._compose(
            "run", "--rm", "--no-deps", "-T", "--pull", "never",
            PANEL, *MIGRATION, timeout=90)
        # On disposable stage fixtures the migration callback proves the
        # same canonical GRANT_DDL. It is NEVER a host-migration shortcut.
        if callback is not None:
            callback()

    def nginx_check_and_reload(self):
        self._guard()
        self._run(["nginx", "-t"], timeout=20)
        self._run(["systemctl", "reload", "nginx"], timeout=20)

    def start_panel(self, selected):
        self._guard()
        expected = self._expected(selected)
        # Deny a wrong image even before an up which might recreate the Panel.
        compose_image = self.stage._read(
            "opt/smite/docker-compose.yml", limit=262144)
        if ("    image: " + expected + "\n").encode("ascii") not in compose_image:
            deny()
        self._compose("up", "-d", "--no-deps", "--no-build", "--pull",
                      "never", PANEL, timeout=90)

    def verify_panel(self, selected):
        self._guard()
        expected = self._expected(selected)
        last_error = None
        for attempt in range(10):
            obj = self._panel()
            state = obj["State"]
            if (obj["Config"].get("Image") == expected
                    and state.get("Running") is True
                    and state.get("Restarting") is not True
                    and (state.get("Health") or {}).get("Status", "healthy") ==
                    "healthy"):
                actual = self._run(
                    [*DOCKER, "image", "inspect", "-f", "{{.Id}}", expected],
                    capture=True, timeout=15)
                if obj.get("Image") != actual:
                    deny()
                if (self._compose("ps", "-q", PANEL, capture=True, timeout=15)
                        != obj.get("Id")):
                    deny()
                self.stage._check_retained_runtime()
                return
            if attempt < 9:
                self._sleep(2)
        deny()

    def review_plan(self):
        """No Docker/Nginx execution and no host file writes."""
        plan = self.plan()
        return {
            "state": "FIXED_COMMAND_PLAN_ONLY",
            "compose_project": plan["project"],
            "panel_service": PANEL,
            "node_recreate_allowed": False,
            "prod_apply_allowed": False,
            "prod_rollback_allowed": False,
            "checked_stage": True,
        }
