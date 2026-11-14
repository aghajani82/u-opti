#!/usr/bin/env python3
"""Internal Iran Panel-only cutover transaction, DISPOSABLE execution only.

Compose, schema, flags, Nginx, Panel service cutover and config-only rollback
use one sealed stage and a durable phase journal. This is an integration
rehearsal of the EXISTING production contract, not a release authorization.
The real root (/) has NO execution path while the unified pair's independently
signed manifest is trial-only. In particular, the CLI exposes review only.

All service operations are explicitly injected only into disposable fixtures.
No operation here starts, stops, recreates, or modifies smite-node, FRP,
Backhaul, Sanaei, signed replay, identities or production Docker.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

STEPS = ("COMPOSE", "STOP", "SCHEMA", "ENV", "NGINX", "START", "HEALTH")
CONFIG_STEPS = {"COMPOSE": "panel-compose",
                "ENV": "panel-env", "NGINX": "nginx-backend"}
STAGING_REL = "var/lib/u-opti/unified-panel-cutover-trial"
CONFIRM = "REHEARSE-RETAINED-IRAN-PANEL-CUTOVER"
KIND = "unified-panel-disposable-service-cutover"
VALID_PHASES = ({"COMMITTED", "BEFORE_ROLLBACK", "ROLLED_BACK"} |
                {"BEFORE_" + s for s in STEPS} |
                {"AFTER_" + s for s in STEPS})


class Hold(RuntimeError):
    pass


def deny():
    raise Hold("Panel cutover HOLD: release approval and actual host executor not authorized")


def module(filename, name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename))
    if spec is None or spec.loader is None:
        deny()
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj


class Cutover:
    def __init__(self, root=Path("/"), *, stage=None, driver=None,
                 fixture_capability=False):
        self.root = Path(root)
        if self.root != Path("/") and (not fixture_capability or
                                        stage is None or driver is None):
            deny()
        if self.root == Path("/") and (fixture_capability or stage is not None
                                       or driver is not None):
            deny()
        self.stage_mod = module("smite-unified-panel-stage.py",
                                "cutover_panel_stage")
        self.tx_mod = module("smite-unified-panel-transaction.py",
                             "cutover_panel_transaction")
        self.stage = stage if stage is not None else self.stage_mod.PanelStage()
        self.stage_hold = sys.modules[self.stage.__class__.__module__].StageHold
        if self.stage.root != self.root:
            deny()
        self.tx = self.tx_mod.PanelTransaction(
            self.root, stager=self.stage, fixture_capability=fixture_capability)
        self.folder = self.root / STAGING_REL
        self.driver = driver
        self.fixture_capability = fixture_capability

    def _check_fixture(self, confirm):
        # This is NOT an alternative approval token for the trial manifest.
        if (self.root == Path("/") or not self.fixture_capability
                or self.driver is None or confirm != CONFIRM):
            deny()

    def _read_stage_sha(self):
        raw = self.stage._read(
            self.stage_mod.STAGE_REL + "/journal.json", mode=0o600, limit=8192)
        return hashlib.sha256(raw).hexdigest()

    def _state(self):
        path = self.folder / "journal.json"
        if not path.exists() and not path.is_symlink():
            return None
        self.stage._parents(path)
        try:
            st = self.folder.lstat()
            if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
                    or stat.S_IMODE(st.st_mode) != 0o700
                    or {x.name for x in self.folder.iterdir()} != {"journal.json"}):
                deny()
            raw = self.stage._read(STAGING_REL + "/journal.json",
                                   mode=0o600, limit=8192)
            doc = self.tx_mod.checked_json(raw)
        except (OSError, ValueError, self.stage_hold,
                self.stage_mod.StageHold, self.tx_mod.Hold):
            deny()
        if (not isinstance(doc, dict)
                or set(doc) != {"schema", "kind", "source", "stage_hash",
                                   "phase", "production", "node_recreate_allowed"}
                or type(doc["schema"]) is not int or doc["schema"] != 1
                or doc["kind"] != KIND
                or doc["source"] != self.tx_mod.SOURCE_SHA
                or doc["stage_hash"] != self._read_stage_sha()
                or doc["phase"] not in VALID_PHASES
                or doc["production"] is not False
                or doc["node_recreate_allowed"] is not False):
            deny()
        return doc

    def _fsync_dir(self, folder):
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write(self, doc):
        self._check_fixture(CONFIRM)
        raw = (json.dumps(doc, sort_keys=True, separators=(",", ":")) +
               "\n").encode("ascii")
        fd, temp = tempfile.mkstemp(prefix=".cutover-", dir=self.folder)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.folder / "journal.json")
            self._fsync_dir(self.folder)
        finally:
            if os.path.lexists(temp):
                os.unlink(temp)

    @contextmanager
    def _operation(self, confirm):
        self._check_fixture(confirm)
        folder_fd = os.open(self.stage.staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(folder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                deny()
            # Verify the signed stage AND original Node ID *inside* our
            # nonblocking lock, not just before obtaining it.
            self.stage.status()
            yield
        finally:
            os.close(folder_fd)

    def _continuity(self):
        try:
            self.stage.status()   # exact Docker ID + StartedAt witness
            self.stage._preflight_database()
            self.stage._preflight_replay()
            if self.tx._live_continuity() != "HEARTBEAT_ONLY_NO_NEW_ENROLLMENT":
                deny()
            tables = self.tx._tables()
            if tables not in (set(), {"smite_foreign_install_grants",
                                     "smite_foreign_install_origins"}):
                deny()
            return tables
        except (self.tx_mod.Hold, self.stage_hold, self.stage_mod.StageHold):
            deny()

    def _check_ordered_config(self, phase, *, rolling_back=False):
        """Validate all owned files before executing *any* service callback."""
        if phase in ("COMMITTED", "BEFORE_ROLLBACK", "ROLLED_BACK"):
            if phase == "ROLLED_BACK":
                for name in self.tx_mod.CONFIG:
                    if self.tx._live(name) != self.tx._snapshot(name):
                        deny()
                return
            if rolling_back:
                for name in self.tx_mod.CONFIG:
                    allowed = {
                        self.tx._snapshot(name), self.tx._candidate(name)
                    }
                    if self.tx._live(name) not in allowed:
                        deny()
                return
            if phase == "COMMITTED":
                for name in self.tx_mod.CONFIG:
                    if self.tx._live(name) != self.tx._candidate(name):
                        deny()
                return
            deny()
        boundary, _, step = phase.partition("_")
        if boundary not in ("BEFORE", "AFTER") or step not in STEPS:
            deny()
        pos = STEPS.index(step) + int(boundary == "AFTER")
        for config_step, name in CONFIG_STEPS.items():
            index = STEPS.index(config_step)
            expected = (
                {self.tx._candidate(name)} if index < pos else
                {self.tx._snapshot(name)}
            )
            # An atomic rename may have committed immediately before a crash,
            # but its AFTER journal checkpoint may not have been written.
            if boundary == "BEFORE" and config_step == step:
                expected.add(self.tx._candidate(name))
            if self.tx._live(name) not in expected:
                deny()

    def _prewrite(self, phase, *, rollback=False):
        tables = self._continuity()
        self._check_ordered_config(phase, rolling_back=rollback)
        if not rollback and phase not in ("BEFORE_COMPOSE", "AFTER_COMPOSE",
                                         "BEFORE_STOP", "AFTER_STOP",
                                         "BEFORE_SCHEMA") and not tables:
            deny()

    def _initial(self):
        # Internal entrypoints must NOT bypass the public operation gate.
        # In particular, never mkdir a real host journal without approval.
        self._check_fixture(CONFIRM)
        self.tx.review()
        self._continuity()
        self.stage._parents(self.folder)
        if self.folder.exists() or self.folder.is_symlink():
            deny()
        self.folder.mkdir(mode=0o700)
        self._fsync_dir(self.folder.parent)
        doc = {"schema": 1, "kind": KIND,
               "source": self.tx_mod.SOURCE_SHA,
               "stage_hash": self._read_stage_sha(),
               "phase": "BEFORE_COMPOSE", "production": False,
               "node_recreate_allowed": False}
        self._write(doc)
        return doc

    def _step(self, step):
        self._check_fixture(CONFIRM)
        if step == "COMPOSE":
            if self.tx._live("panel-compose") != self.tx._candidate("panel-compose"):
                self.tx._replace(
                    "panel-compose", self.tx._candidate("panel-compose"))
        elif step == "STOP":
            self.driver.stop_panel()  # NO smite-node actions
            self.driver.require_panel_stopped()
        elif step == "SCHEMA":
            # Real execution will use the pinned new Panel image's existing
            # migration command; the disposable driver delegates only to
            # the pre-existing fixture migration implementation. NEVER run
            # it while the old Panel process can write SQLite concurrently.
            self.driver.require_panel_stopped()
            if not self.tx._tables():
                self.driver.migrate_schema(self.tx._schema_rehearsal)
            if self.tx._tables() != {"smite_foreign_install_grants",
                                    "smite_foreign_install_origins"}:
                deny()
        elif step in ("ENV", "NGINX"):
            name = CONFIG_STEPS[step]
            if self.tx._live(name) != self.tx._candidate(name):
                self.tx._replace(name, self.tx._candidate(name))
            if step == "NGINX":
                self.driver.nginx_check_and_reload()
        elif step == "START":
            self.driver.start_panel("candidate")
        elif step == "HEALTH":
            self.driver.verify_panel("candidate")
        else:
            deny()

    def apply(self, *, confirm, fail_after=None):
        with self._operation(confirm):
            doc = self._state()
            if doc is None:
                doc = self._initial()
            if doc["phase"] in ("BEFORE_ROLLBACK", "ROLLED_BACK"):
                deny()  # after rollback require a new operator review
            if doc["phase"] == "COMMITTED":
                self._prewrite("COMMITTED")
                # A durable journal records past success; it is never
                # substitute for CURRENT running Panel health.
                self.driver.verify_panel("candidate")
                self._continuity()
                return {"status": "ALREADY_REHEARSED", "production": False}
            phase = doc["phase"]
            boundary, _, step = phase.partition("_")
            if step not in STEPS:
                deny()
            start = STEPS.index(step) + int(boundary == "AFTER")
            for step in STEPS[start:]:
                proposed = "BEFORE_" + step
                # A drifted config must NEVER advance the durable journal.
                # Validate the step's pre/post image BEFORE the checkpoint.
                self._prewrite(proposed)
                doc["phase"] = proposed
                self._write(doc)
                self._step(step)
                self._prewrite(doc["phase"])
                doc["phase"] = "AFTER_" + step
                self._write(doc)
                if fail_after == step:
                    raise Hold("Injected disposal-only power-loss boundary")
            self._prewrite("AFTER_HEALTH")
            doc["phase"] = "COMMITTED"
            self._write(doc)
            return {"status": "REHEARSED_WITH_PANEL_SERVICE", "production": False,
                    "node_recreated": False}

    def rollback(self, *, confirm, fail_after=None):
        """Compensate owned config only; preserve empty additive schema/replay."""
        with self._operation(confirm):
            doc = self._state()
            if doc is None:
                deny()
            if doc["phase"] == "ROLLED_BACK":
                self._continuity()
                self._check_ordered_config("ROLLED_BACK", rolling_back=True)
                self.driver.verify_panel("original")
                return {"status": "ALREADY_ROLLED_BACK", "production": False}
            if doc["phase"] == "BEFORE_ROLLBACK":
                self._prewrite(doc["phase"], rollback=True)
            else:
                # Before beginning compensation, require the ORIGINAL
                # ordered phase. Mixed owned preimages are allowed ONLY
                # after our durable BEFORE_ROLLBACK checkpoint.
                self._prewrite(doc["phase"])
            doc["phase"] = "BEFORE_ROLLBACK"
            self._write(doc)
            # Stop ONLY Panel. Each action is idempotent after a crash.
            self.driver.stop_panel()
            self.driver.require_panel_stopped()
            if fail_after == "STOP":
                raise Hold("Injected disposal-only rollback interruption")
            self._prewrite("BEFORE_ROLLBACK", rollback=True)
            for name in ("nginx-backend", "panel-env", "panel-compose"):
                if self.tx._live(name) != self.tx._snapshot(name):
                    self.tx._replace(name, self.tx._snapshot(name))
                self._prewrite("BEFORE_ROLLBACK", rollback=True)
                if fail_after == name:
                    raise Hold("Injected disposal-only config rollback interruption")
            self.driver.nginx_check_and_reload()
            self.driver.start_panel("original")
            self.driver.verify_panel("original")
            self._continuity()
            if any(self.tx._live(name) != self.tx._snapshot(name)
                   for name in self.tx_mod.CONFIG):
                deny()
            doc["phase"] = "ROLLED_BACK"
            self._write(doc)
            return {"status": "ROLLED_BACK_PANEL_ONLY", "production": False,
                    "database_rewound": False, "node_recreated": False}

    def review(self):
        """Only public interface: inspect the sealed stage; do NOT execute."""
        if self.root == Path("/"):
            # Even the root read-only CLI must validate the same fixed
            # Docker/Compose project and signed-control overlay as the
            # service driver, AND independently verify both Cosign digests.
            # These facts never convert a trial into a release approval.
            driver_module = module(
                "smite-unified-panel-host-driver.py",
                "cutover_panel_fixed_driver")
            try:
                transaction = self.tx.review()
                checked = driver_module.PanelServiceDriver(
                    stage=self.stage).review_plan()
            except (self.tx_mod.Hold, driver_module.Hold, self.stage_hold):
                deny()
            if (transaction.get("status") != "REVIEWED_PREIMAGES_ONLY"
                    or transaction.get("live_activation_allowed") is not False):
                deny()
            if (checked.get("state") != "FIXED_COMMAND_PLAN_ONLY"
                    or checked.get("panel_service") != "smite-panel"
                    or checked.get("node_recreate_allowed") is not False
                    or checked.get("prod_apply_allowed") is not False
                    or checked.get("prod_rollback_allowed") is not False):
                deny()
            return {"status": "READ_ONLY_RELEASE_HOLD",
                    "driver": "FIXED_COMMAND_PLAN_VERIFIED",
                    "baseline_and_preimages": "VERIFIED",
                    "production": False}
        self.stage.status()
        doc = self._state()
        return {"status": "READ_ONLY_DISPOSABLE_REVIEW",
                "phase": None if doc is None else doc["phase"],
                "production": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True, action="store_true")
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            deny()
        report = Cutover().review()
    except (Hold, OSError, ValueError, TypeError, KeyError):
        print("IR_PANEL_CUTOVER=HOLD")
        return 2
    print("IR_PANEL_CUTOVER=" + report["status"])
    print("IR_PANEL_BASELINE_AND_PREIMAGES=" + report["baseline_and_preimages"])
    print("IR_NODE_RECREATE=NO")
    print("PRODUCTION_EXECUTION_AUTHORIZED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
