#!/usr/bin/env python3
"""Prepare-only transaction for the exact signed unified-install Panel trial.

Stage a consistent private SQLite snapshot, existing config/secret snapshots,
and inert candidate files. No Docker, Nginx, SQLite migration, firewall or
active-file modifications. Applying/rolling back LIVE state is NOT implemented
here; a later separately reviewed executor must validate this journal again.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

SOURCE = "de0677d015a00160970ed57bba565adc4fafe8eb"
MANIFEST_HASH = "61149003bbf966445bb25d0f94a4e666bb57b4544a5565703af55b30afa41c84"
OLD_PANEL = "ghcr.io/aghajani82/smite-panel@sha256:180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8"
NEW_PANEL = "ghcr.io/aghajani82/smite-panel@sha256:a4142110b058b02a5325e8f2130f2faa5daa5fc0aa3faad82bb4389948d4385f"
NEW_NODE = "ghcr.io/aghajani82/smite-node@sha256:2f63b5e1b3d262bf29bd2feaeec11b30b910c14e4d4b31ce4bb17e4fb24e2f4b"
STAGE_REL = "var/lib/u-opti/unified-panel-trial-stage"
PANEL_REL = "opt/smite/.env"
COMPOSE_REL = "opt/smite/docker-compose.yml"
SIGNED_COMPOSE_REL = "opt/smite/docker-compose.signed-control.yml"
ORIGINS_REL = "etc/u-opti/smite/panel-trusted-nodes/approved-origins.json"
NGINX_REL = "etc/nginx/conf.d/u-opti-smite-panel-backend.conf"
STATE_REL = "etc/u-opti/smite/state.env"
SECRET_REL = "etc/nginx/u-opti-smite-pairing-secret.conf"
PAIRING_REL = "etc/u-opti/smite/pairing/panel-pairing-secrets.json"
DB_REL = "opt/smite/panel/data/smite.db"
IR_ID_REL = "etc/u-opti/smite/identities/node-identity.json"
REPLAY_MARKER_REL = "etc/u-opti/smite/identities/replay-enrollment.json"
REPLAY_DB_REL = "var/lib/u-opti/smite-node-security/replay/agent-replay.sqlite3"
FILE_MAP = {
    "panel-env": (PANEL_REL, 0o600, 65536),
    "panel-compose": (COMPOSE_REL, None, 262144),
    "panel-signed-compose": (SIGNED_COMPOSE_REL, 0o600, 32000),
    "panel-approved-origins": (ORIGINS_REL, 0o600, 64000),
    "nginx-backend": (NGINX_REL, None, 262144),
    "smite-state": (STATE_REL, None, 16384),
    "nginx-ingress-key": (SECRET_REL, 0o600, 4096),
    "pairing-secrets": (PAIRING_REL, 0o600, 4096),
    "iran-identity": (IR_ID_REL, 0o600, 4096),
    "iran-replay-marker": (REPLAY_MARKER_REL, 0o600, 4096),
}
BASE_SCHEMA = (
    "SELECT id,name,metadata FROM nodes LIMIT 0",
    "SELECT node_id,node_role,encrypted_secret,paired_at,revoked_at FROM smite_node_identities LIMIT 0",
    "SELECT code_hash,node_id,consumed_at FROM smite_node_pairing_codes LIMIT 0",
    "SELECT node_id,nonce,expires_at FROM smite_node_inbound_nonces LIMIT 0",
)
CONFIRM = "STAGE-SIGNED-UNIFIED-PANEL-TRIAL"


class StageHold(RuntimeError):
    pass


def deny():
    raise StageHold("Unified Panel trial staging HOLD; live installation unchanged")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        deny()
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def _env(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        deny()
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if not sep or not re.fullmatch("[A-Z][A-Z0-9_]*", name) or name in result:
            deny()
        result[name] = value
    return result


def _candidate_env(raw: bytes) -> bytes:
    original = _env(raw)
    if (original.get("SMITE_NODE_REGISTRATION_MODE") != "signed"
            or original.get("SMITE_PANEL_AGENT_AUTH_MODE") != "signed"
            or original.get("SMITE_NODE_PAIRING_PREVIEW_ENABLED") != "true"
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}=", original.get("SMITE_NODE_PAIRING_MASTER_KEY", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", original.get("SMITE_NODE_PAIRING_INGRESS_TOKEN", ""))
            or original.get("SMITE_FOREIGN_INSTALL_ENABLED", "false") != "false"
            or original.get("SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED", "false") != "false"):
        deny()
    updates = {
        "SMITE_FOREIGN_INSTALL_ENABLED": "true",
        "SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED": "true",
    }
    lines = []
    for line in raw.decode("utf-8").splitlines():
        key = line.partition("=")[0]
        if key in updates:
            lines.append(key + "=" + updates.pop(key))
        else:
            lines.append(line)
    for key,value in updates.items():
        lines.append(key + "=" + value)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _candidate_compose(raw: bytes) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        deny()
    # Exact old RC7 image only, in the pinned Smite Panel service. Never
    # replace Node/FRP/Backhaul images or an unrecognized Compose project.
    service = re.search(
        r"(?ms)^  smite-panel:\n(?P<body>.*?)(?=^  [a-zA-Z][a-zA-Z0-9_-]*:\n|\\Z)",
        text)
    if (not service or text.count("  smite-panel:\n") != 1
            or service.group("body").count("    image: " + OLD_PANEL + "\n") != 1
            or text.count("    image: " + OLD_PANEL + "\n") != 1
            or "    image: " + NEW_PANEL + "\n" in text):
        deny()
    return text.replace("    image: " + OLD_PANEL + "\n",
                        "    image: " + NEW_PANEL + "\n", 1).encode("utf-8")


class PanelStage:
    def __init__(self, root: Path = Path("/"), admission=None):
        self.root = Path(root)
        if not self.root.is_absolute() or self.root.is_symlink() or not self.root.is_dir():
            deny()
        self.staging = self.root / STAGE_REL
        self._admission = admission

    def _at(self, relative: str) -> Path:
        return self.root / relative

    def _parents(self, path: Path):
        if not path.is_relative_to(self.root) or ".." in path.parts:
            deny()
        current = path.parent
        while True:
            try:
                info = current.lstat()
            except OSError:
                deny()
            if (not stat.S_ISDIR(info.st_mode) or
                    info.st_uid != os.geteuid() or info.st_mode & 0o022):
                deny()
            if current == self.root:
                break
            current = current.parent

    def _read(self, relative: str, *, mode=None, limit=262144) -> bytes:
        path = self._at(relative)
        self._parents(path)
        try:
            st = path.lstat()
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                    or st.st_nlink != 1 or st.st_size > limit
                    or st.st_mode & 0o022
                    or (mode is not None and stat.S_IMODE(st.st_mode) != mode)):
                deny()
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as item:
                opened = os.fstat(item.fileno())
                if ((opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino)
                        or opened.st_mode & 0o022 or opened.st_nlink != 1):
                    deny()
                content = item.read(limit + 1)
            if len(content) > limit:
                deny()
            return content
        except OSError:
            deny()

    def _write(self, name: str, content: bytes):
        if not re.fullmatch(r"[a-z0-9.-]{1,75}", name):
            deny()
        p = self.staging / name
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as item:
            item.write(content)
            item.flush()
            os.fsync(item.fileno())
        self._sync_dir()

    def _sync_dir(self):
        fd = os.open(self.staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _signed_pair(self):
        pair = _module("smite-unified-trial-pair-admission")
        if self._admission is None:
            receipt = pair.verify(
                manifest=Path(__file__).with_name("smite-unified-trial-registry-pair.json"),
                manifest_sha256=MANIFEST_HASH, source_sha=SOURCE,
                trusted_root=Path(__file__).with_name("smite-rc7-sigstore-trusted-root.json"))
        else:
            receipt = self._admission()
        if (not isinstance(receipt, dict)
                or receipt.get("status") != "verified_trial_pair"
                or receipt.get("source_sha") != SOURCE
                or receipt.get("panel") != NEW_PANEL
                or receipt.get("node") != NEW_NODE
                or receipt.get("host_activation_allowed") is not False):
            deny()

    def _verify_iran_node(self, conn):
        state = _env(self._read(STATE_REL, limit=16384))
        identity = json.loads(self._read(IR_ID_REL, mode=0o600, limit=4096))
        node_id = identity.get("node_id")
        node_name = state.get("SMITE_NODE_NAME", "")
        if (not isinstance(node_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", node_id)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", node_name)):
            deny()
        rows = conn.execute(
            "SELECT nodes.name, identities.node_role, identities.revoked_at, "
            "length(identities.encrypted_secret) "
            "FROM nodes JOIN smite_node_identities AS identities "
            "ON nodes.id = identities.node_id WHERE nodes.id = ?", (node_id,)
        ).fetchall()
        if (len(rows) != 1 or rows[0][:3] != (node_name, "iran", None)
                or not rows[0][3]):
            deny()

    def _preflight_database(self):
        db = self._at(DB_REL)
        self._parents(db)
        try:
            st = db.lstat()
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                    or st.st_nlink != 1 or st.st_mode & 0o022):
                deny()
            with sqlite3.connect(db.absolute().as_uri() + "?mode=ro", uri=True, timeout=10) as conn:
                for sql in BASE_SCHEMA:
                    conn.execute(sql)
                self._verify_iran_node(conn)
                if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    deny()
        except (OSError, sqlite3.Error):
            deny()

    def _preflight_replay(self):
        """Verify replay history is bound to the existing immutable Iran key."""
        try:
            identity = json.loads(self._read(IR_ID_REL, mode=0o600, limit=4096))
            marker = json.loads(self._read(REPLAY_MARKER_REL, mode=0o600, limit=4096))
            node_id = identity.get("node_id")
            secret = identity.get("node_secret")
            if (not isinstance(node_id, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", node_id)
                    or not isinstance(secret, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", secret)
                    or marker.get("schema") != 1
                    or marker.get("node_id") != node_id
                    or marker.get("replay_database") !=
                        "/var/lib/smite-node/auth/agent-replay.sqlite3"
                    or marker.get("status") != "ENROLLMENT_STARTED"):
                deny()
            expected = hmac.new(
                secret.encode("ascii"),
                b"smite-replay-key-binding-v1:" + node_id.encode("ascii"),
                hashlib.sha256).hexdigest()
            if (not isinstance(marker.get("key_binding"), str)
                    or not hmac.compare_digest(marker["key_binding"], expected)):
                deny()
            replay = self._at(REPLAY_DB_REL)
            self._parents(replay)
            st = replay.lstat()
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                    or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600):
                deny()
            with sqlite3.connect(replay.absolute().as_uri() + "?mode=ro",
                                 uri=True, timeout=8) as conn:
                if (conn.execute("PRAGMA quick_check").fetchone() != ("ok",)
                        or conn.execute("PRAGMA user_version").fetchone() != (1,)
                        or conn.execute("SELECT node_id FROM replay_store_identity").fetchall()
                            != [(node_id,)]):
                    deny()
                conn.execute("SELECT node_id,nonce,expires_at FROM agent_nonces LIMIT 0")
        except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
            deny()

    def _replay_snapshot(self):
        source = self._at(REPLAY_DB_REL)
        destination = self.staging / "iran-replay.sqlite3"
        try:
            with closing(sqlite3.connect(source.absolute().as_uri() + "?mode=ro",
                                         uri=True, timeout=10)) as existing:
                with closing(sqlite3.connect(destination, timeout=15)) as copy:
                    existing.backup(copy)
                    # WAL mode is copied from the live source; canonicalize
                    # ONLY the private snapshot before closing its connection.
                    if copy.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                        deny()
            os.chmod(destination, 0o600)
            with closing(sqlite3.connect(destination.absolute().as_uri() + "?mode=ro",
                                         uri=True, timeout=8)) as copy:
                if (copy.execute("PRAGMA quick_check").fetchone() != ("ok",)
                        or copy.execute("PRAGMA user_version").fetchone() != (1,)):
                    deny()
                expected = json.loads(self._read(IR_ID_REL, mode=0o600))["node_id"]
                if copy.execute("SELECT node_id FROM replay_store_identity").fetchall() != [(expected,)]:
                    deny()
                copy.execute("SELECT node_id,nonce,expires_at FROM agent_nonces LIMIT 0")
            with open(destination, "rb") as handle:
                os.fsync(handle.fileno())
            self._sync_dir()
            return destination.read_bytes()
        except (OSError, sqlite3.Error, ValueError, TypeError):
            deny()

    def _database_snapshot(self):
        db = self._at(DB_REL)
        self._parents(db)
        st = db.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_nlink != 1 or st.st_mode & 0o022):
            deny()
        dest = self.staging / "panel-db.sqlite3"
        # Snapshot committed rows, WAL included; never raw-copy a live SQLite DB.
        try:
            with closing(sqlite3.connect(db.absolute().as_uri() + "?mode=ro",
                                         uri=True, timeout=10)) as src:
                for sql in BASE_SCHEMA:
                    src.execute(sql)
                if src.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    deny()
                with closing(sqlite3.connect(dest, timeout=15)) as target:
                    src.backup(target)
                    if target.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                        deny()
            os.chmod(dest, 0o600)
            with closing(sqlite3.connect(dest.absolute().as_uri() + "?mode=ro",
                                         uri=True)) as copy:
                for sql in BASE_SCHEMA:
                    copy.execute(sql)
                self._verify_iran_node(copy)
                if copy.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    deny()
            with open(dest, "rb") as handle:
                os.fsync(handle.fileno())
            self._sync_dir()
        except (OSError, sqlite3.Error):
            deny()
        return dest.read_bytes()

    def _collect(self):
        records = {}
        for label,(path,mode,limit) in FILE_MAP.items():
            records[label] = self._read(path, mode=mode, limit=limit)
        state = _env(records["smite-state"])
        env = _env(records["panel-env"])
        if (state.get("SMITE_ROLE") != "panel-iran"
                or state.get("SMITE_CONNECTION_MODE", "standard") != "standard"
                or env.get("PANEL_DOMAIN") != state.get("SMITE_PANEL_DOMAIN")
                or env.get("DB_TYPE") != "sqlite"
                or env.get("DB_PATH") != "./data/smite.db"):
            deny()
        domain = state.get("SMITE_PANEL_DOMAIN", "")
        if not re.fullmatch(r"(?=.{4,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z", domain):
            deny()
        identity = json.loads(records["iran-identity"])
        origins = json.loads(records["panel-approved-origins"])
        expected_override = (
            "services:\n"
            "  smite-panel:\n"
            "    volumes:\n"
            "      - /etc/u-opti/smite/panel-trusted-nodes:/etc/smite-panel/trusted-nodes:ro\n"
        ).encode("ascii")
        if (not isinstance(identity, dict) or not isinstance(origins, dict)
                or not isinstance(identity.get("node_id"), str)
                or records["panel-signed-compose"] != expected_override
                or env.get("SMITE_SIGNED_NODE_ORIGINS_PATH") !=
                   "/etc/smite-panel/trusted-nodes/approved-origins.json"
                or origins.get("version") != 1
                or not isinstance(origins.get("nodes"), dict)
                or origins["nodes"].get(identity.get("node_id")) != {
                    "role": "iran",
                    "node_name": state.get("SMITE_NODE_NAME"),
                    "origin": "http://127.0.0.1:8888",
                    "control_url": "http://127.0.0.1:8888/api/agent",
                }):
            deny()
        pairing = json.loads(records["pairing-secrets"])
        if (pairing.get("schema") != 1
                or env.get("SMITE_NODE_PAIRING_MASTER_KEY") != pairing.get("master_key")
                or env.get("SMITE_NODE_PAIRING_INGRESS_TOKEN") != pairing.get("ingress_token")
                or records["nginx-ingress-key"] !=
                    ('proxy_set_header X-Smite-Pairing-Ingress "' +
                     pairing["ingress_token"] + '";\n').encode("ascii")):
            deny()
        try:
            rendered = _module("smite-foreign-install-panel-ingress").render(
                records["nginx-backend"], domain)
        except ValueError:
            deny()
        live = {
            "panel-env": _candidate_env(records["panel-env"]),
            "panel-compose": _candidate_compose(records["panel-compose"]),
            "nginx-backend": rendered,
        }
        return records, live

    def verify_live_baseline(self):
        """Inspect the running transaction before preparing a live-host snapshot."""
        if self.root != Path("/"):
            deny()
        if any(os.environ.get(name) for name in (
                "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY",
                "DOCKER_CERT_PATH", "COMPOSE_FILE", "COMPOSE_PROFILES",
                "COMPOSE_ENV_FILES")):
            deny()
        journal_module = _module("smite-rc6-install-journal")
        pairing = _module("smite-node-pairing")
        journal = journal_module.Journal()
        try:
            for folder in (journal.folder, *journal.folder.parents):
                journal_module.trusted(folder, True)
            if stat.S_IMODE(journal.folder.lstat().st_mode) != 0o700:
                deny()
            record = journal.load()
            journal._ir_witness(record)
            if record["ir_phase"] != "COMPLETE":
                deny()
            command = pairing._panel_compose_command()
            if command != [
                "docker", "compose", "--project-name", record["id"],
                "-f", "/" + COMPOSE_REL, "-f", "/" + SIGNED_COMPOSE_REL,
            ]:
                deny()
            pairing._run(command + ["config", "--quiet"], timeout=30)
        except (OSError, ValueError, TypeError, KeyError, IndexError,
                journal_module.Hold, pairing.WizardHold):
            deny()

    def prepare(self, confirm: str):
        if confirm != CONFIRM:
            deny()
        # Signature validation MUST precede any output directory creation.
        self._signed_pair()
        if self.staging.exists() or self.staging.is_symlink():
            deny()
        if self.root == Path("/"):
            self.verify_live_baseline()
        originals, candidates = self._collect()
        # Reject missing/drifted DB schema before creating ANY transaction state.
        self._preflight_database()
        self._preflight_replay()
        self._parents(self.staging)
        self.staging.mkdir(mode=0o700)
        try:
            manifest = {"schema":1, "state":"PREPARED_ONLY",
                        "source_sha":SOURCE, "panel_image":NEW_PANEL,
                        "node_image":NEW_NODE, "live_write":False,
                        "snapshots":{}, "candidates":{}}
            for label,content in originals.items():
                name = "before-" + label
                self._write(name, content)
                manifest["snapshots"][name] = _sha(content)
            database = self._database_snapshot()
            manifest["snapshots"]["panel-db.sqlite3"] = _sha(database)
            replay = self._replay_snapshot()
            manifest["snapshots"]["iran-replay.sqlite3"] = _sha(replay)
            for label,content in candidates.items():
                name = "candidate-" + label
                self._write(name, content)
                manifest["candidates"][name] = _sha(content)
            # COMMIT LAST: crash before this retains a quarantine directory.
            self._write("journal.json", (json.dumps(manifest,sort_keys=True) + "\n").encode())
            return self.status()
        except Exception:
            # Do not delete partial private evidence or automatically retry.
            deny()

    def status(self):
        self._parents(self.staging / "journal.json")
        st = self.staging.lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) != 0o700):
            deny()
        journal = json.loads(self._read(STAGE_REL + "/journal.json",mode=0o600,limit=8192))
        if (not isinstance(journal,dict) or journal.get("schema") != 1
                or journal.get("state") != "PREPARED_ONLY"
                or journal.get("source_sha") != SOURCE
                or journal.get("panel_image") != NEW_PANEL
                or journal.get("node_image") != NEW_NODE
                or journal.get("live_write") is not False
                or set(journal.get("snapshots",{})) !=
                    {"before-" + label for label in FILE_MAP} | {"panel-db.sqlite3","iran-replay.sqlite3"}
                or set(journal.get("candidates",{})) !=
                    {"candidate-panel-env","candidate-panel-compose","candidate-nginx-backend"}):
            deny()
        # Reject unreviewed extras/links, including a leftover SQLite WAL or
        # a partially completed second attempt masquerading as one journal.
        expected_names = set(journal["snapshots"]) | set(journal["candidates"]) | {"journal.json"}
        if {entry.name for entry in self.staging.iterdir()} != expected_names:
            deny()
        for group in ("snapshots","candidates"):
            for filename,digest in journal[group].items():
                if not re.fullmatch("[a-f0-9]{64}",digest):
                    deny()
                content = self._read(STAGE_REL + "/" + filename,
                                     mode=0o600,limit=32_000_000)
                if _sha(content) != digest:
                    deny()
        return {"state":"PREPARED_ONLY", "signature_pair":"EXACT_PINNED",
                "live_writes":"NONE", "activation_allowed":False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--stage",action="store_true")
    action.add_argument("--status",action="store_true")
    action.add_argument("--verify-live-baseline",action="store_true")
    parser.add_argument("--confirm",default="")
    args=parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            deny()
        manager=PanelStage()
        if args.verify_live_baseline:
            manager.verify_live_baseline()
            manager._collect()
            manager._preflight_database()
            manager._preflight_replay()
            status = {"state":"LIVE_BASELINE_VERIFIED"}
        else:
            status=manager.prepare(args.confirm) if args.stage else manager.status()
    except (StageHold,OSError,ValueError,KeyError,sqlite3.Error):
        print("UNIFIED_PANEL_TRANSACTION=HOLD")
        return 2
    print("UNIFIED_PANEL_TRANSACTION="+status["state"])
    print("LIVE_CONFIG_AND_CONTAINER_CHANGES=NONE")
    print("FOREIGN_INSTALL_ACTIVATION_ALLOWED=NO")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
