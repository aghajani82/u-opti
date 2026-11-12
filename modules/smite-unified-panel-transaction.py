#!/usr/bin/env python3
"""Signed Panel transaction REVIEW and isolated apply/rollback REHEARSAL.

Production CLI is read-only. The rehearsal engine *refuses root='/'* and
requires an explicitly injected disposable-root capability. It never
invokes Docker, Nginx, a host shell, a network request or a live service.
A future independently reviewed production executor must provide service
health gates, per-step recovery and an operator approval before activation.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile

STAGE_MODULE = "smite-unified-panel-stage"
REHEARSAL_REL = "var/lib/u-opti/unified-panel-trial-rehearsal"
CONFIRM = "REHEARSE-UNIFIED-PANEL-ON-DISPOSABLE-ROOT"
SOURCE_SHA = "b865be93e22153c60769f6329e6e55e781494ded"
CONFIG = {
    "panel-compose": "opt/smite/docker-compose.yml",
    "panel-env": "opt/smite/.env",
    "nginx-backend": "etc/nginx/conf.d/u-opti-smite-panel-backend.conf",
}
STEPS = ("COMPOSE", "SCHEMA", "ENV", "NGINX")
GRANT_DDL = (
    """CREATE TABLE smite_foreign_install_grants (
    code_hash TEXT PRIMARY KEY, node_id TEXT NOT NULL,
    node_name TEXT NOT NULL, origin TEXT NOT NULL,
    control_url TEXT NOT NULL, issued_by TEXT NOT NULL,
    issued_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
    consumed_at INTEGER, revoked_at INTEGER)""",
    """CREATE TABLE smite_foreign_install_origins (
    node_id TEXT PRIMARY KEY, node_name TEXT NOT NULL,
    origin TEXT NOT NULL, control_url TEXT NOT NULL,
    grant_hash TEXT NOT NULL UNIQUE, approved_at INTEGER NOT NULL)""",
)


class Hold(RuntimeError):
    pass


def deny():
    raise Hold("Signed Panel rollout HOLD; no production operation authorized")


def load_stage():
    path = Path(__file__).with_name(STAGE_MODULE + ".py")
    spec = importlib.util.spec_from_file_location("u_opti_trial_stage_rollback", path)
    if not spec or not spec.loader:
        deny()
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def checked_json(raw: bytes):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                deny()
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, TypeError):
        deny()


class PanelTransaction:
    def __init__(self, root: Path = Path("/"), *, stager=None, fixture_capability=False):
        # An injected disposable stager may have been imported with a
        # distinct module name. Reuse ITS exact exception/constants rather
        # than loading an unrelated duplicate of the same Python module.
        self.stage_mod = (sys.modules[stager.__class__.__module__]
                          if stager is not None else load_stage())
        self.stage = stager or self.stage_mod.PanelStage(root)
        self.root = self.stage.root
        self.rehearsal = self.root / REHEARSAL_REL
        self.fixture_capability = fixture_capability

    def _snapshot(self, name: str) -> bytes:
        return self.stage._read(self.stage_mod.STAGE_REL + "/before-" + name, mode=0o600)

    def _candidate(self, name: str) -> bytes:
        return self.stage._read(self.stage_mod.STAGE_REL + "/candidate-" + name, mode=0o600)

    def _live(self, name: str) -> bytes:
        rel = CONFIG[name] if name in CONFIG else self.stage_mod.FILE_MAP[name][0]
        mode = self.stage_mod.FILE_MAP[name][1]
        limit = self.stage_mod.FILE_MAP[name][2]
        return self.stage._read(rel, mode=mode, limit=limit)

    def _tables(self):
        db = self.root / self.stage_mod.DB_REL
        with closing(sqlite3.connect(db.absolute().as_uri() + "?mode=ro",
                                     uri=True, timeout=5)) as conn:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('smite_foreign_install_grants','smite_foreign_install_origins')")}
            return names

    def review(self):
        """Verify exact signed pair, stage and current preimages; ZERO writes."""
        try:
            self.stage.status()
            self.stage._signed_pair()
            for name in self.stage_mod.FILE_MAP:
                if self._live(name) != self._snapshot(name):
                    deny()
            self.stage._preflight_database()
            self.stage._preflight_replay()
            if self._tables():
                deny()
            originals, candidates = self.stage._collect()
            if any(originals[name] != self._snapshot(name)
                   for name in self.stage_mod.FILE_MAP):
                deny()
            if any(candidates[name] != self._candidate(name)
                   for name in CONFIG):
                deny()
            if self.rehearsal.exists() or self.rehearsal.is_symlink():
                deny()
        except (OSError, ValueError, KeyError, sqlite3.Error,
                self.stage_mod.StageHold):
            deny()
        return {
            "status": "REVIEWED_PREIMAGES_ONLY",
            "source_sha": SOURCE_SHA,
            "steps": ["COMPOSE_IMAGE", "ADDITIVE_SCHEMA", "PANEL_FLAGS", "NGINX_443"],
            "rollback": "CONFIG_ONLY_IF_NO_NEW_ENROLLMENT",
            "live_activation_allowed": False,
        }

    def _check_fixture(self, confirm):
        if (not self.fixture_capability or self.root.resolve() == Path("/")
                or confirm != CONFIRM):
            deny()

    def _fsync_directory(self, folder: Path):
        descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _journal_write(self, journal):
        raw = (json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n").encode()
        # Private fsynced temp file; durable rename and directory sync. Never
        # change the signed original stage journal.
        descriptor, tmp = tempfile.mkstemp(prefix=".journal-", dir=self.rehearsal)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.rehearsal / "journal.json")
            self._fsync_directory(self.rehearsal)
        finally:
            if os.path.lexists(tmp):
                os.unlink(tmp)

    def _journal_read(self):
        path = self.rehearsal / "journal.json"
        self.stage._parents(path)
        info = self.rehearsal.lstat()
        if (not stat.S_ISDIR(info.st_mode) or
                info.st_uid != os.geteuid() or
                stat.S_IMODE(info.st_mode) != 0o700 or
                {p.name for p in self.rehearsal.iterdir()} != {"journal.json"}):
            deny()
        try:
            raw = self.stage._read(REHEARSAL_REL + "/journal.json", mode=0o600, limit=8192)
        except (OSError, self.stage_mod.StageHold):
            deny()
        journal = checked_json(raw)
        phases = ({"REHEARSED", "ROLLED_BACK", "BEFORE_ROLLBACK"} |
                  {"BEFORE_" + x for x in STEPS} |
                  {"AFTER_" + x for x in STEPS})
        if (not isinstance(journal, dict)
                or set(journal) != {"schema","kind","source","phase","production",
                                   "database_rollback","snapshots"}
                or journal.get("schema") != 1
                or journal.get("kind") != "unified-panel-disposable-rehearsal"
                or journal.get("source") != SOURCE_SHA
                or journal.get("phase") not in phases
                or journal.get("production") is not False
                or journal.get("database_rollback") is not False
                or journal.get("snapshots") != {
                    name:digest(self._snapshot(name)) for name in CONFIG}):
            deny()
        return journal

    def _replace(self, name, content):
        """Replace only a previously reviewed fixture config with matching mode."""
        live_path = self.root / CONFIG[name]
        self.stage._parents(live_path)
        if self._live(name) not in (self._snapshot(name), self._candidate(name)):
            deny()
        before = live_path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            deny()
        descriptor, tmp = tempfile.mkstemp(prefix=".uopti-rehearsal-",dir=live_path.parent)
        try:
            os.fchmod(descriptor, stat.S_IMODE(before.st_mode))
            with os.fdopen(descriptor,"wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, live_path)
            self._fsync_directory(live_path.parent)
        finally:
            if os.path.lexists(tmp):
                os.unlink(tmp)

    def _schema_rehearsal(self):
        db = self.root / self.stage_mod.DB_REL
        try:
            with closing(sqlite3.connect(db, timeout=8)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    if self._tables():
                        deny()
                    for sql in GRANT_DDL:
                        conn.execute(sql)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        except sqlite3.Error:
            deny()

    def rehearse(self, *, confirm: str, fail_after=None):
        """Test-only! Never accepts a real / host or real service capability."""
        self._check_fixture(confirm)
        self.review()
        self.stage._parents(self.rehearsal)
        self.rehearsal.mkdir(mode=0o700)
        journal = {
            "schema":1, "kind":"unified-panel-disposable-rehearsal",
            "source":SOURCE_SHA, "phase":"BEFORE_COMPOSE",
            "production":False, "database_rollback":False,
            "snapshots": {name:digest(self._snapshot(name)) for name in CONFIG},
        }
        self._journal_write(journal)
        for step in STEPS:
            journal["phase"] = "BEFORE_" + step
            self._journal_write(journal)
            if step == "SCHEMA":
                self._schema_rehearsal()
            else:
                name = {"COMPOSE":"panel-compose","ENV":"panel-env",
                        "NGINX":"nginx-backend"}[step]
                self._replace(name, self._candidate(name))
            journal["phase"] = "AFTER_" + step
            self._journal_write(journal)
            if fail_after == step:
                raise Hold("Simulated interruption; explicit rollback required")
        journal["phase"] = "REHEARSED"
        self._journal_write(journal)
        return {"status":"REHEARSED_OFFLINE","schema":"ADDITIVE_ONLY",
                "production":False,"runtime_started":False}

    def _new_enrollment(self):
        db = self.root / self.stage_mod.DB_REL
        snapshot = self.stage.staging / "panel-db.sqlite3"
        try:
            with closing(sqlite3.connect(db.absolute().as_uri() + "?mode=ro",
                                         uri=True, timeout=5)) as live, closing(
                sqlite3.connect(snapshot.absolute().as_uri() + "?mode=ro",
                                uri=True, timeout=5)) as old:
                past = old.execute("SELECT * FROM smite_node_identities ORDER BY node_id").fetchall()
                current = live.execute("SELECT * FROM smite_node_identities ORDER BY node_id").fetchall()
                if past != current:
                    return True
                expected = {"smite_foreign_install_grants","smite_foreign_install_origins"}
                names = {row[0] for row in live.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if names & expected not in (set(), expected):
                    return True
                for name in names & expected:
                    if live.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]:
                        return True
                return False
        except sqlite3.Error:
            return True

    def _replay_drift(self):
        """Avoid automatic rollback if fresh signed commands consumed nonces."""
        live = self.root / self.stage_mod.REPLAY_DB_REL
        original = self.stage.staging / "iran-replay.sqlite3"
        try:
            with closing(sqlite3.connect(live.absolute().as_uri() + "?mode=ro",
                                         uri=True, timeout=5)) as current, closing(
                sqlite3.connect(original.absolute().as_uri() + "?mode=ro",
                                uri=True, timeout=5)) as previous:
                for table in ("replay_store_identity", "agent_nonces"):
                    rows = "SELECT * FROM " + table + " ORDER BY 1,2,3" if table == "agent_nonces" else "SELECT * FROM " + table + " ORDER BY 1"
                    if current.execute(rows).fetchall() != previous.execute(rows).fetchall():
                        return True
            return False
        except sqlite3.Error:
            return True

    def rollback_rehearsal(self, *, confirm: str):
        """Restore ONLY owned config files; never rewind DB, replay or identity."""
        self._check_fixture(confirm)
        journal = self._journal_read()
        if journal["phase"] == "ROLLED_BACK":
            return {"status":"ALREADY_ROLLED_BACK","schema":"PRESERVED"}
        if self._new_enrollment() or self._replay_drift():
            deny()
        # Refuse to restore any old config if security identities or replay
        # history drifted; a new grant or key must never be disconnected.
        for name in self.stage_mod.FILE_MAP:
            if name in CONFIG:
                if self._live(name) not in (self._snapshot(name),self._candidate(name)):
                    deny()
            elif self._live(name) != self._snapshot(name):
                deny()
        self.stage._preflight_replay()
        journal["phase"] = "BEFORE_ROLLBACK"
        self._journal_write(journal)
        for name in ("nginx-backend","panel-env","panel-compose"):
            if self._live(name) != self._snapshot(name):
                self._replace(name,self._snapshot(name))
        journal["phase"] = "ROLLED_BACK"
        self._journal_write(journal)
        return {"status":"ROLLED_BACK_OFFLINE","schema":"PRESERVED",
                "runtime_started":False, "production":False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            deny()
        result = PanelTransaction().review()
    except (Hold, OSError, ValueError, TypeError):
        print("UNIFIED_PANEL_EXECUTION=HOLD")
        return 2
    print("UNIFIED_PANEL_EXECUTION="+result["status"])
    print("REAL_APPLY_AND_ROLLBACK=NOT_IMPLEMENTED")
    print("LIVE_SERVICES_AND_FRP=UNTOUCHED")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
