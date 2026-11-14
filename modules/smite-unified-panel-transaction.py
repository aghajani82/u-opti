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
from contextlib import closing, contextmanager
import fcntl
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
import time

STAGE_MODULE = "smite-unified-panel-stage"
REHEARSAL_REL = "var/lib/u-opti/unified-panel-trial-rehearsal"
CONFIRM = "REHEARSE-UNIFIED-PANEL-ON-DISPOSABLE-ROOT"
SOURCE_SHA = "0f03ad84a3ad57d89b99bbfb8e3af898de77f677"
CONFIG = {
    "panel-compose": "opt/smite/docker-compose.yml",
    "panel-env": "opt/smite/.env",
    "nginx-backend": "etc/nginx/conf.d/u-opti-smite-panel-backend.conf",
}
STEPS = ("COMPOSE", "SCHEMA", "ENV", "NGINX")
STEP_CONFIG = {"COMPOSE": "panel-compose", "ENV": "panel-env", "NGINX": "nginx-backend"}
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
    def __init__(self, root: Path = Path("/"), *, stager=None, fixture_capability=False,
                 fixture_migration=None):
        # An injected disposable stager may have been imported with a
        # distinct module name. Reuse ITS exact exception/constants rather
        # than loading an unrelated duplicate of the same Python module.
        self.stage_mod = (sys.modules[stager.__class__.__module__]
                          if stager is not None else load_stage())
        self.stage = stager or self.stage_mod.PanelStage(root)
        self.root = self.stage.root
        self.rehearsal = self.root / REHEARSAL_REL
        self.fixture_capability = fixture_capability
        self.fixture_migration = fixture_migration

    def _snapshot(self, name: str) -> bytes:
        return self.stage._read(self.stage_mod.STAGE_REL + "/before-" + name, mode=0o600)

    def _candidate(self, name: str) -> bytes:
        return self.stage._read(self.stage_mod.STAGE_REL + "/candidate-" + name, mode=0o600)

    def _live(self, name: str) -> bytes:
        rel = CONFIG[name] if name in CONFIG else self.stage_mod.FILE_MAP[name][0]
        mode = self.stage_mod.FILE_MAP[name][1]
        limit = self.stage_mod.FILE_MAP[name][2]
        return self.stage._read(rel, mode=mode, limit=limit)

    def _live_continuity(self):
        """Read-only *candidate* reconciliation for a running Iran Panel.

        Heartbeats advance signed inbound/replay nonces and last_seen while
        an operator stages a Panel upgrade. They are not new Foreign grants.
        This is NOT permission to mutate a running Panel or to roll it back:
        the existing fixture rollback remains stricter. Every persistent
        identity, reservation, pairing code, origin and other Node field
        must remain exact. No live service or database is modified.
        """
        db = self.root / self.stage_mod.DB_REL
        old_db = self.stage.staging / "panel-db.sqlite3"
        replay = self.root / self.stage_mod.REPLAY_DB_REL
        old_replay = self.stage.staging / "iran-replay.sqlite3"

        def open_ro(path):
            self.stage._parents(path)
            if path.is_symlink() or not path.is_file():
                deny()
            return sqlite3.connect(path.absolute().as_uri() + "?mode=ro",
                                   uri=True, timeout=5)

        def schema(conn, table):
            return conn.execute("PRAGMA table_info(" + table + ")").fetchall()

        def rows(conn, table):
            return conn.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()

        # Snapshot both signed nonce tables against one bounded clock.
        # A live, unexpired replay nonce cannot disappear from the retained
        # baseline: that would permit reuse before its original expiry.
        now = int(time.time())

        def nonce_drift_only(live, old, table, iran_ids):
            expected = {"node_id", "nonce", "expires_at"}
            left_cols = [r[1] for r in schema(old, table)]
            right_cols = [r[1] for r in schema(live, table)]
            if (schema(old, table) != schema(live, table)
                    or set(left_cols) != expected
                    or set(right_cols) != expected):
                deny()
            def keyed(conn):
                result = {}
                for node, nonce, expiry in conn.execute(
                        "SELECT node_id,nonce,expires_at FROM " + table):
                    if (node not in iran_ids or not isinstance(nonce, str)
                            or not nonce or type(expiry) is not int
                            or (node, nonce) in result):
                        deny()
                    result[(node, nonce)] = expiry
                return result
            past, current = keyed(old), keyed(live)
            # Fresh Iran nonces and deletion of EXPIRED nonces are ordinary
            # signed traffic. An active nonce must not vanish early: losing
            # it could admit an otherwise still valid replay/HMAC request.
            # Never accept changed expiry values for the same nonce.
            if any(
                (current[key] != expiry if key in current else expiry >= now)
                for key, expiry in past.items()
            ):
                deny()

        try:
            with closing(open_ro(db)) as live, closing(open_ro(old_db)) as old:
                for table in ("smite_node_identities", "smite_node_pairing_codes"):
                    if schema(live, table) != schema(old, table) or rows(live, table) != rows(old, table):
                        deny()
                identities = old.execute(
                    "SELECT node_id FROM smite_node_identities "
                    "WHERE node_role='iran' AND revoked_at IS NULL").fetchall()
                iran_ids = {row[0] for row in identities}
                if len(iran_ids) != 1:
                    deny()
                before_cols = [row[1] for row in schema(old, "nodes")]
                after_cols = [row[1] for row in schema(live, "nodes")]
                if before_cols != after_cols or "id" not in before_cols:
                    deny()
                def node_map(conn):
                    data = {}
                    for entry in rows(conn, "nodes"):
                        mapping = dict(zip(before_cols, entry))
                        key = mapping["id"]
                        if not isinstance(key, str) or key in data:
                            deny()
                        data[key] = mapping
                    return data
                past, current = node_map(old), node_map(live)
                if set(past) != set(current) or not iran_ids <= set(past):
                    deny()
                for node_id in past:
                    a, b = past[node_id], current[node_id]
                    if node_id in iran_ids:
                        # Both snapshots must already identify the original
                        # authenticated local Iran Node; this is not an
                        # admission for an unpaired legacy/foreign record.
                        ma = json.loads(a.get("metadata") or "{}")
                        mb = json.loads(b.get("metadata") or "{}")
                        if (not isinstance(ma, dict) or not isinstance(mb, dict)
                                or any(meta.get("role") != "iran" or
                                       meta.get("provisioning") != "signed_checkin"
                                       for meta in (ma, mb))):
                            deny()
                    for key in before_cols:
                        if key in ("last_seen", "metadata"):
                            continue
                        if a[key] != b[key]:
                            deny()
                    if a.get("metadata") != b.get("metadata"):
                        if node_id not in iran_ids:
                            deny()
                        # Only FRP *telemetry* may change on a previously
                        # signed Iran Node. No role, provisioning, control
                        # URL or other metadata field can be rewritten.
                        ma = json.loads(a["metadata"] or "{}")
                        mb = json.loads(b["metadata"] or "{}")
                        if (not isinstance(ma, dict) or not isinstance(mb, dict)
                                or ma.get("role") != "iran"
                                or ma.get("provisioning") != "signed_checkin"):
                            deny()
                        for item in ("frp_connected", "frp_remote_port"):
                            ma.pop(item, None)
                            mb.pop(item, None)
                        if ma != mb:
                            deny()
                    if (node_id not in iran_ids and a.get("last_seen") != b.get("last_seen")):
                        deny()
                nonce_drift_only(live, old, "smite_node_inbound_nonces", iran_ids)
                optional = {"smite_foreign_install_grants", "smite_foreign_install_origins"}
                present = {row[0] for row in live.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if present & optional not in (set(), optional):
                    deny()
                for table in present & optional:
                    if live.execute("SELECT count(*) FROM " + table).fetchone()[0]:
                        deny()

            with closing(open_ro(replay)) as live, closing(open_ro(old_replay)) as old:
                if (schema(old, "replay_store_identity") !=
                        schema(live, "replay_store_identity")
                        or rows(old, "replay_store_identity") !=
                            rows(live, "replay_store_identity")):
                    deny()
                nonce_drift_only(live, old, "agent_nonces", iran_ids)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error,
                json.JSONDecodeError, self.stage_mod.StageHold):
            deny()
        return "HEARTBEAT_ONLY_NO_NEW_ENROLLMENT"

    def _tables(self):
        """Refuse partial/wrong Foreign schema during a resumed transaction.

        A SELECT ... LIMIT 0 proves column spelling but NOT the UNIQUE
        constraints needed for single-use grants and exact origin binding.
        Compare the *whole* table and index layouts with the pinned Smite
        migration schema already represented by GRANT_DDL. Never change the
        live database; the scratch template exists only in memory.
        """
        db = self.root / self.stage_mod.DB_REL
        expected = {"smite_foreign_install_grants",
                    "smite_foreign_install_origins"}
        with closing(sqlite3.connect(db.absolute().as_uri() + "?mode=ro",
                                     uri=True, timeout=5)) as conn:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('smite_foreign_install_grants','smite_foreign_install_origins')")}
            if not names:
                return names
            if names != expected:
                deny()
            # The pinned additive Smite schema defines no triggers. An
            # unrelated trigger could intercept one-use grant issuance or
            # change origin binding even when columns/indexes look intact.
            if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='trigger' "
                    "AND tbl_name IN "
                    "('smite_foreign_install_grants','smite_foreign_install_origins') "
                    "LIMIT 1").fetchone() is not None:
                deny()

            def shape(connection, table):
                columns = connection.execute(
                    "PRAGMA table_info(" + table + ")").fetchall()
                indexes = connection.execute(
                    "PRAGMA index_list(" + table + ")").fetchall()
                details = []
                for row in indexes:
                    # Names come from the live SQLite schema; never interpret
                    # arbitrary index names as SQL syntax.
                    if not isinstance(row[1], str) or not re.fullmatch(
                            r"[A-Za-z0-9_]{1,128}", row[1]):
                        deny()
                    details.append((row, connection.execute(
                        "PRAGMA index_xinfo(" + row[1] + ")").fetchall()))
                return columns, details

            with closing(sqlite3.connect(":memory:")) as template:
                for ddl in GRANT_DDL:
                    template.execute(ddl)
                for table in sorted(expected):
                    if shape(conn, table) != shape(template, table):
                        deny()
            return names

    def review(self, *, resume_rolled_back=False):
        """Verify exact signed pair, stage and current preimages; ZERO writes."""
        try:
            self.stage.status()
            self.stage._signed_pair()
            for name in self.stage_mod.FILE_MAP:
                if self._live(name) != self._snapshot(name):
                    deny()
            self.stage._preflight_database()
            self.stage._preflight_replay()
            # The same sealed stage is reviewed differently on an active
            # Panel: tolerate ONLY ephemeral signed Iran heartbeats, never
            # new identities, grants, pairing codes or altered metadata.
            # No actual production apply path is enabled.
            if self.root == Path("/"):
                baseline = self.stage.live_baseline_report()
                if (baseline.get("IR_INSTALL_CHECKPOINT") != "COMPLETE"
                        or baseline.get("IR_GATEWAY_TLS443") != "PASS"
                        or baseline.get("IR_PANEL_LOOPBACK") != "PASS"
                        or baseline.get("IR_ADMIN") != "PRESENT"
                        or baseline.get("IR_SIGNED_RUNTIME_AND_REPLAY") != "VERIFIED_READ_ONLY"
                        or baseline.get("IR_SIGNED_TWO_WAY") !=
                            "PASS_EXISTING_SIGNED_CONTROL_PROBES"):
                    deny()
                self._live_continuity()
            elif self._new_enrollment() or self._replay_drift():
                deny()
            if resume_rolled_back:
                if self._journal_read()["phase"] != "ROLLED_BACK":
                    deny()
            elif self._tables():
                deny()
            originals, candidates = self.stage._collect()
            if any(originals[name] != self._snapshot(name)
                   for name in self.stage_mod.FILE_MAP):
                deny()
            if any(candidates[name] != self._candidate(name)
                   for name in CONFIG):
                deny()
            if not resume_rolled_back and (self.rehearsal.exists() or self.rehearsal.is_symlink()):
                deny()
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error,
                self.stage_mod.StageHold):
            deny()
        return {
            "status": "REVIEWED_PREIMAGES_ONLY",
            "source_sha": SOURCE_SHA,
            "steps": ["COMPOSE_IMAGE", "ADDITIVE_SCHEMA", "PANEL_FLAGS", "NGINX_443"],
            "rollback": "CONFIG_ONLY_IF_NO_NEW_ENROLLMENT",
            "live_activation_allowed": False,
        }

    def review_retained_config_rollback(self):
        """Read-only preflight for the *real* Iran Panel config-only recovery.

        Unlike the disposable rollback rehearsal, a running Iran Node
        legitimately records fresh HMAC/replay nonces and last_seen during
        an upgrade. Rewinding either DB or requiring byte-identical replay
        would be unsafe/impossible. Admit ONLY the already-reviewed Iran
        heartbeat changes, and ONLY with the exact signed post-upgrade
        config + empty canonical additive Foreign tables.

        This is NOT an executor, runtime-health proof or release approval.
        It does not edit files, Docker, Nginx, SQLite, replay or journal.
        """
        try:
            self.stage.status()  # includes independently regenerated candidates
            self.stage._signed_pair()
            self.stage._preflight_database()
            self.stage._preflight_replay()
            if self._tables() != {
                    "smite_foreign_install_grants",
                    "smite_foreign_install_origins"}:
                deny()
            if self._live_continuity() != "HEARTBEAT_ONLY_NO_NEW_ENROLLMENT":
                deny()
            # Require a FULL verified candidate at this decision boundary;
            # don't invent a phase for mixed/stale config during a crash.
            for name in self.stage_mod.FILE_MAP:
                required = (self._candidate(name) if name in CONFIG
                            else self._snapshot(name))
                if self._live(name) != required:
                    deny()
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error,
                self.stage_mod.StageHold):
            deny()
        return {
            "status": "RETAINED_CONFIG_ROLLBACK_PREFLIGHT_READ_ONLY",
            "production_apply_allowed": False,
            "production_rollback_allowed": False,
            "runtime_health_verified": False,
            "database_rewind_allowed": False,
            "replay_rewind_allowed": False,
            "iran_node_recreate_allowed": False,
            "source_sha": SOURCE_SHA,
        }

    def _check_fixture(self, confirm):
        if (not self.fixture_capability or self.root.resolve() == Path("/")
                or confirm != CONFIRM):
            deny()

    @contextmanager
    def _operation(self, confirm):
        self._check_fixture(confirm)
        try:
            self.stage.status()
        except (OSError, ValueError, self.stage_mod.StageHold):
            deny()
        # Lock the sealed stage directory without editing it. Apply, retry and
        # compensation for the same staged transaction share this descriptor.
        descriptor = os.open(self.stage.staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                deny()
            yield
        finally:
            os.close(descriptor)

    def _fsync_directory(self, folder: Path):
        descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _journal_write(self, journal):
        self._check_fixture(CONFIRM)
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
        self._check_fixture(CONFIRM)
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
        self._check_fixture(CONFIRM)
        db = self.root / self.stage_mod.DB_REL
        if self.fixture_migration is not None:
            if self.fixture_migration(db) not in ("READY", "ALREADY_READY"):
                deny()
            return
        try:
            with closing(sqlite3.connect(db, timeout=8)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    if self._tables():
                        # A previous rollback retains the empty additive
                        # tables. Validate them instead of rebuilding them.
                        if self._new_enrollment():
                            deny()
                    else:
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
        with self._operation(confirm):
            return self._rehearse_locked(fail_after)

    def _rehearse_locked(self, fail_after):
        self._check_fixture(CONFIRM)
        if os.path.lexists(self.rehearsal):
            journal = self._journal_read()
            phase = journal["phase"]
            if phase in ("BEFORE_ROLLBACK", "ROLLED_BACK"):
                self._rollback_locked()
                self.review(resume_rolled_back=True)
                start = 0
            else:
                start = self._resume_index(phase)
        else:
            self.review()
            self.stage._parents(self.rehearsal)
            self.rehearsal.mkdir(mode=0o700)
            self._fsync_directory(self.rehearsal.parent)
            journal = {
                "schema":1, "kind":"unified-panel-disposable-rehearsal",
                "source":SOURCE_SHA, "phase":"BEFORE_COMPOSE",
                "production":False, "database_rollback":False,
                "snapshots": {name:digest(self._snapshot(name)) for name in CONFIG},
            }
            start = 0
        if journal["phase"] == "REHEARSED":
            return {"status":"REHEARSED_OFFLINE","schema":"ADDITIVE_ONLY",
                    "production":False,"runtime_started":False}
        for step in STEPS[start:]:
            journal["phase"] = "BEFORE_" + step
            self._journal_write(journal)
            if step == "SCHEMA":
                self._schema_rehearsal()
                if not self._tables() or self._new_enrollment():
                    deny()
            else:
                name = STEP_CONFIG[step]
                candidate = self._candidate(name)
                if self._live(name) != candidate:
                    self._replace(name, candidate)
                if self._live(name) != candidate:
                    deny()
            journal["phase"] = "AFTER_" + step
            self._journal_write(journal)
            if fail_after == step:
                raise Hold("Simulated interruption; explicit rollback required")
        self._resume_index("REHEARSED", verify_pair=False)
        journal["phase"] = "REHEARSED"
        self._journal_write(journal)
        return {"status":"REHEARSED_OFFLINE","schema":"ADDITIVE_ONLY",
                "production":False,"runtime_started":False}

    def _resume_index(self, phase, *, verify_pair=True):
        """Revalidate the completed steps and tolerate only the current step's pre/post image."""
        boundary, _, interrupted = phase.partition("_")
        start = len(STEPS) if phase == "REHEARSED" else (
            STEPS.index(interrupted) + (boundary == "AFTER"))
        try:
            if verify_pair:
                self.stage._signed_pair()
            self.stage._preflight_database()
            self.stage._preflight_replay()
            if self._new_enrollment() or self._replay_drift():
                deny()
            for name in self.stage_mod.FILE_MAP.keys() - CONFIG.keys():
                if self._live(name) != self._snapshot(name):
                    deny()
            for step, name in STEP_CONFIG.items():
                index = STEPS.index(step)
                allowed = (self._candidate(name),) if index < start else (self._snapshot(name),)
                if boundary == "BEFORE" and step == interrupted:
                    allowed += (self._candidate(name),)
                if self._live(name) not in allowed:
                    deny()
            tables_present = bool(self._tables())
            if start > STEPS.index("SCHEMA") and not tables_present:
                deny()
        except (OSError, ValueError, self.stage_mod.StageHold, sqlite3.Error):
            deny()
        return start

    def _new_enrollment(self):
        db = self.root / self.stage_mod.DB_REL
        snapshot = self.stage.staging / "panel-db.sqlite3"
        try:
            with closing(sqlite3.connect(db.absolute().as_uri() + "?mode=ro",
                                         uri=True, timeout=5)) as live, closing(
                sqlite3.connect(snapshot.absolute().as_uri() + "?mode=ro",
                                uri=True, timeout=5)) as old:
                # This existing Panel rollback must not run after
                # an operator has started ANY new or changed signed pairing
                # state, even before a Foreign grant is issued/redeemed.
                # Include pending codes and inbound nonces: reverting Panel
                # config after either action can break the same signed
                # Iran/Foreign Node. SELECT * also catches metadata/column
                # drift in existing nodes, not just ID/name changes.
                for table in (
                    "smite_node_identities",
                    "nodes",
                    "smite_node_pairing_codes",
                    "smite_node_inbound_nonces",
                ):
                    statement = "SELECT * FROM " + table + " ORDER BY 1"
                    if (old.execute(statement).fetchall()
                            != live.execute(statement).fetchall()):
                        return True
                expected = {"smite_foreign_install_grants","smite_foreign_install_origins"}
                names = {row[0] for row in live.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if names & expected not in (set(), expected):
                    return True
                if names & expected:
                    live.execute("""SELECT code_hash,node_id,node_name,origin,control_url,
                        issued_by,issued_at,expires_at,consumed_at,revoked_at
                        FROM smite_foreign_install_grants LIMIT 0""")
                    live.execute("""SELECT node_id,node_name,origin,control_url,
                        grant_hash,approved_at FROM smite_foreign_install_origins LIMIT 0""")
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

    def rollback_rehearsal(self, *, confirm: str,
                           allow_iran_heartbeat=False):
        """Restore ONLY owned config; optionally model live signed heartbeats.

        The heartbeat setting is FIXTURE-ONLY, behind the original disposable
        root + confirmation gate. The production CLI exposes no rollback.
        """
        with self._operation(confirm):
            return self._rollback_locked(
                allow_iran_heartbeat=allow_iran_heartbeat)

    def _rollback_locked(self, *, allow_iran_heartbeat=False):
        self._check_fixture(CONFIRM)
        # The original staged SQLite snapshot and replay evidence must still
        # match the sealed journal before ANY config restoration is attempted.
        try:
            self.stage.status()
            self.stage._preflight_database()
        except (OSError, ValueError, self.stage_mod.StageHold):
            deny()
        journal = self._journal_read()
        rolled_back = journal["phase"] == "ROLLED_BACK"
        # An interrupted/partial migration with missing uniqueness is not
        # safe to treat as completed just because its tables are empty.
        # Verify schema BEFORE restoring even one owned config file.
        tables = self._tables()
        if allow_iran_heartbeat:
            # Reuse the SAME already-reviewed read-only continuity witness
            # as prospective production rollback, but never rewind replay.
            # Strictly require the canonical additive schema and reject
            # any new reservation, pending code, grant or identity drift.
            if (tables != {"smite_foreign_install_grants",
                           "smite_foreign_install_origins"}
                    or self._live_continuity() !=
                        "HEARTBEAT_ONLY_NO_NEW_ENROLLMENT"):
                deny()
        elif self._new_enrollment() or self._replay_drift():
            deny()
        # Refuse to restore any old config if security identities or replay
        # history drifted; a new grant or key must never be disconnected.
        for name in self.stage_mod.FILE_MAP:
            allowed = (self._snapshot(name),)
            if name in CONFIG and not rolled_back:
                allowed += (self._candidate(name),)
            if self._live(name) not in allowed:
                deny()
        self.stage._preflight_replay()
        if rolled_back:
            return {"status":"ALREADY_ROLLED_BACK","schema":"PRESERVED"}
        journal["phase"] = "BEFORE_ROLLBACK"
        self._journal_write(journal)
        for name in ("nginx-backend","panel-env","panel-compose"):
            if self._live(name) != self._snapshot(name):
                self._replace(name,self._snapshot(name))
        if any(self._live(name) != self._snapshot(name) for name in CONFIG):
            deny()
        journal["phase"] = "ROLLED_BACK"
        self._journal_write(journal)
        return {"status":"ROLLED_BACK_OFFLINE","schema":"PRESERVED",
                "runtime_started":False, "production":False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--review", action="store_true")
    action.add_argument("--review-rollback", action="store_true")
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            deny()
        manager = PanelTransaction()
        result = (manager.review_retained_config_rollback()
                  if args.review_rollback else manager.review())
    except (Hold, OSError, ValueError, TypeError):
        print("UNIFIED_PANEL_EXECUTION=HOLD")
        return 2
    print("UNIFIED_PANEL_EXECUTION="+result["status"])
    print("REAL_APPLY_AND_ROLLBACK=NOT_IMPLEMENTED")
    print("LIVE_SERVICES_AND_FRP=UNTOUCHED")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
