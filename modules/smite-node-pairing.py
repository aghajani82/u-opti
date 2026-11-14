#!/usr/bin/env python3
"""Smite U-OPTI signed pairing controller for the disposable Field Trial.

Default/status and store preparation remain inert. Live mutations are opt-in,
Standard/443 only, root-only and require UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES.
The live path enables the exact pairing ingress on IR, redeems a one-time code,
provisions Smite's own replay enrollment offline, applies the reviewed strict
Compose overlay, and verifies signed Node<->Panel traffic without legacy
fallback. No tunnel engine, Xray inbound, FRP or Backhaul is configured here.

Pairing codes and HMAC secrets are never command-line arguments or log output.
Production activation is explicitly out of scope.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import fcntl
from urllib import error, parse, request


STATE = Path("/etc/u-opti/smite/state.env")
IDENTITY_DIR = Path("/etc/u-opti/smite/identities")
IDENTITY_FILE = IDENTITY_DIR / "node-identity.json"
PANEL_DIR = Path("/opt/smite")
PANEL_ENV = PANEL_DIR / ".env"
PANEL_COMPOSE = PANEL_DIR / "docker-compose.yml"
PANEL_SECURITY_OVERRIDE = PANEL_DIR / "docker-compose.signed-control.yml"
PANEL_DB = PANEL_DIR / "panel/data/smite.db"
NODE_DIR = Path("/opt/smite-node")
NODE_COMPOSE = NODE_DIR / "docker-compose.yml"
NODE_SECURITY_CANDIDATE = NODE_DIR / "docker-compose.security-candidate.yml"
REPLAY_DIR = Path("/var/lib/u-opti/smite-node-security/replay")
REPLAY_DB = REPLAY_DIR / "agent-replay.sqlite3"
PAIRING_PRIVATE_DIR = Path("/etc/u-opti/smite/pairing")
PAIRING_SECRETS = PAIRING_PRIVATE_DIR / "panel-pairing-secrets.json"
TRUSTED_NODES_DIR = Path("/etc/u-opti/smite/panel-trusted-nodes")
APPROVED_ORIGINS = TRUSTED_NODES_DIR / "approved-origins.json"
NGINX_BACKEND = Path("/etc/nginx/conf.d/u-opti-smite-panel-backend.conf")
NGINX_PAIRING_SECRET = Path("/etc/nginx/u-opti-smite-pairing-secret.conf")
CONTAINER_IDENTITY = "/run/smite-node-identity/node-identity.json"
CONTAINER_REPLAY = "/var/lib/smite-node/auth/agent-replay.sqlite3"
CANDIDATE_HELPER = Path(__file__).with_name("smite-node-auth-candidate.py")
_NODE_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_SECRET = re.compile(r"^[a-f0-9]{64}$")
_CODE = re.compile(r"^smn1_[A-Za-z0-9_-]{32,100}$")
_DOMAIN = re.compile(
    r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class WizardHold(Exception):
    """Safe refusal: never include secret data in its message."""


# Local root bootstrap is deliberately not an HTTP endpoint. The installer
# authorizes exactly its co-located IR slot before the first admin is created.
# Use the application's reservation model and one-time code store, then redeem
# through the same verified HTTPS ingress used by manually paired Nodes.
_LOCAL_IR_RESERVE = r'''
import asyncio, json, secrets, sys
from sqlalchemy import select
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Node, Tunnel
from app import node_pairing_store as pairing
node_id, name = sys.argv[1:]
def require(condition):
    if not condition:
        raise RuntimeError('Local IR reservation admission rejected')
async def reserve():
    require(settings.smite_node_registration_mode == 'signed')
    require(settings.smite_panel_agent_auth_mode == 'signed')
    require(settings.smite_node_pairing_preview_enabled)
    async with AsyncSessionLocal() as db:
        require((await db.execute(select(Tunnel.id))).first() is None)
        rows = (await db.execute(select(Node))).scalars().all()
        if rows:
            require(len(rows) == 1)
            row = rows[0]
            require(row.id == node_id and row.name == name)
            require(row.status == 'pending')
            require(row.node_metadata == {
                'role': 'iran', 'node_name': name,
                'provisioning': 'reserved_for_pairing'})
        else:
            db.add(Node(id=node_id, name=name,
                fingerprint='reserved-' + secrets.token_hex(16), status='pending',
                node_metadata={'role': 'iran', 'node_name': name,
                               'provisioning': 'reserved_for_pairing'}))
            await db.commit()
asyncio.run(reserve())
code = pairing.issue_code(settings.db_path,
    master_key=settings.smite_node_pairing_master_key,
    node_id=node_id, role='iran', admin_id='local-root-install', ttl_seconds=600)
print(code.code)
'''


def complete_local_ir_install(state: dict[str, str]) -> None:
    """Fresh RC7 only; retain one identity across retries, never rekey it."""
    _field_trial_gate()
    if (state.get('SMITE_ROLE') != 'panel-iran'
            or state.get('SMITE_CONNECTION_MODE') != 'standard'
            or state.get('SMITE_MANAGED_VERSION') != '2.0.0-rc.7'):
        raise WizardHold('Local bootstrap requires the selected RC7 IR install')
    name = state.get('SMITE_NODE_NAME', '')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,62}', name):
        raise WizardHold('Invalid local IR name')
    domain = state.get('SMITE_PANEL_DOMAIN', '')
    secure_endpoint('https://' + domain)
    _require_no_active_engine_overlays()
    for container, expected in (
        ('smite-panel', _FOREIGN_PANEL_IMAGE_RC7),
        ('smite-node', _FOREIGN_NODE_IMAGE_RC7),
    ):
        actual = _run(['docker', 'inspect', '-f', '{{.Config.Image}}', container],
                      capture=True, timeout=15)
        if actual != expected:
            raise WizardHold('Local bootstrap image differs from selected RC7')
    _panel_compose_command()
    # Validate ownership/file set without executing the returned command. The
    # inspection must also admit the already-active candidate on a safe retry.
    _ir_node_compose_command(rollback=True)
    _private_dir(PAIRING_PRIVATE_DIR, create=True)
    lock_path = PAIRING_PRIVATE_DIR / 'local-ir-install.lock'
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WizardHold('Local IR enrollment already running') from exc
        _complete_local_ir_locked(state, name, domain)


def _complete_local_ir_locked(state: dict[str, str], name: str, domain: str) -> None:
    receipt = PAIRING_PRIVATE_DIR / 'local-ir-install.json'
    if receipt.exists() or receipt.is_symlink():
        try:
            record = json.loads(_regular(receipt, mode=0o600))
            node_id = record['node_id']
            if (str(uuid.UUID(node_id)) != node_id or
                    record != {'node_id': node_id, 'name': name, 'domain': domain}):
                raise ValueError('Receipt mismatch')
        except (ValueError, KeyError, TypeError, AssertionError) as exc:
            raise WizardHold('Local IR enrollment receipt mismatch') from exc
    else:
        if IDENTITY_FILE.exists() or IDENTITY_FILE.is_symlink():
            raise WizardHold('Existing Node identity is not installer-owned')
        # Read-only admission before pairing changes or reserving any row.
        with sqlite3.connect(PANEL_DB.absolute().as_uri() + '?mode=ro', uri=True) as db:
            if db.execute('SELECT 1 FROM nodes LIMIT 1').fetchone() or db.execute(
                    'SELECT 1 FROM tunnels LIMIT 1').fetchone():
                raise WizardHold('Local bootstrap refuses existing Nodes or tunnels')
        node_id = str(uuid.uuid4())
        _atomic_write(receipt, (json.dumps({'node_id': node_id, 'name': name,
                                          'domain': domain}) + '\n').encode(), 0o600)

    if IDENTITY_FILE.exists() or IDENTITY_FILE.is_symlink():
        stored_id, _ = _identity_record()
        if stored_id != node_id:
            raise WizardHold('Local IR identity differs from installer receipt')
    else:
        enable_panel_field_trial(state)
        prepare_store()
        code = _run(['docker', 'exec', 'smite-panel', 'python3', '-c',
                     _LOCAL_IR_RESERVE, node_id, name], capture=True, timeout=30)
        # Never print captured output, exceptions, or codes. A lost response
        # after redemption must HOLD rather than rotate an existing identity.
        if not _CODE.fullmatch(code):
            raise WizardHold('Local IR reservation did not return a pairing code')
        redeem(panel_url='https://' + domain, pairing_code=code,
               node_id=node_id, role='iran', destination=IDENTITY_FILE)

    effective = _run(['docker', 'inspect', '-f',
                      '{{range .Config.Env}}{{println .}}{{end}}', 'smite-node'],
                     capture=True, timeout=15).splitlines()
    if 'SMITE_NODE_PANEL_AUTH_MODE=signed' in effective:
        if 'SMITE_AGENT_AUTH_MODE=strict' not in effective:
            raise WizardHold('Local IR runtime is not strict')
        _local_signed_replay_probe()
        _wait_panel_signed_checkin(node_id)
        _panel_to_ir_signed_probe(node_id)
    else:
        activate_ir_node_field_trial(state)
    print('IR_INSTALL_ENROLLMENT=VERIFIED_ACTIVE')


def state_values(path: Path = STATE) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise WizardHold("Smite installation state is missing or unsafe")
    state: dict[str, str] = {}
    for row in path.read_text(encoding="utf-8").splitlines():
        if not row or row.startswith("#") or "=" not in row:
            continue
        k, v = row.split("=", 1)
        if k in ("SMITE_ROLE", "SMITE_CONNECTION_MODE", "SMITE_PANEL_DOMAIN", "SMITE_NODE_NAME", "SMITE_MANAGED_VERSION"):
            state[k] = v
    if state.get("SMITE_CONNECTION_MODE") != "standard":
        raise WizardHold("Only Standard HTTPS/443 mode is supported in this preview")
    if state.get("SMITE_ROLE") not in ("panel-iran", "iran", "foreign"):
        raise WizardHold("Unrecognized Smite installation role")
    return state


def secure_endpoint(base: str) -> str:
    if not isinstance(base, str) or any(c.isspace() for c in base):
        raise WizardHold("A clean HTTPS Panel domain is required")
    try:
        url = parse.urlsplit(base)
        port = url.port
    except ValueError as exc:
        raise WizardHold("Invalid Panel URL") from exc
    host = url.hostname
    if (
        url.scheme != "https" or not host or not _DOMAIN.fullmatch(host)
        or port not in (None, 443) or url.username or url.password
        or url.path not in ("", "/") or url.query or url.fragment
    ):
        raise WizardHold("Pairing requires a valid hostname at HTTPS/443 only")
    return f"https://{host}/api/node-pairing/redeem"


def _verify_private_dir(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise WizardHold("Identity directory does not exist (prepare it first)") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise WizardHold("Identity directory must be owned by current root user and mode 0700")


def prepare_store(path: Path = IDENTITY_DIR) -> None:
    """Create dedicated credential directory but never touch active Node."""
    if os.geteuid() != 0:
        raise WizardHold("Preparation requires root")
    if path.is_symlink():
        raise WizardHold("Refusing a symlinked identity directory")
    if not path.exists():
        # Parent is managed by U-OPTI; create only the last, non-shared directory.
        if not path.parent.is_dir() or path.parent.is_symlink():
            raise WizardHold("U-OPTI state parent is missing/unsafe")
        path.mkdir(mode=0o700)
    _verify_private_dir(path)


def _validate_identity_file(parent: Path, node_id: str, secret: str) -> None:
    _verify_private_dir(parent)
    if (
        not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id)
        or not isinstance(secret, str) or not _SECRET.fullmatch(secret)
    ):
        raise WizardHold("Invalid identity response")


def store_identity(path: Path, node_id: str, secret: str) -> None:
    """O_EXCL + NOFOLLOW: create credentials only once, never overwrite."""
    _validate_identity_file(path.parent, node_id, secret)
    if path.name != "node-identity.json":
        raise WizardHold("Unexpected identity filename")
    data = json.dumps(
        {"version": 1, "node_id": node_id, "node_secret": secret},
        sort_keys=True, separators=(",", ":"),
    ).encode("ascii")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags, 0o600)
    except FileExistsError as exc:
        raise WizardHold("Existing credentials must never be overwritten") from exc
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(data)
            destination.flush()
            os.fsync(destination.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def redeem(
    *, panel_url: str, pairing_code: str, node_id: str, role: str,
    destination: Path = IDENTITY_FILE, timeout: int = 15
) -> str:
    """One-time POST over verified HTTPS; successful response stages a key only.

    Uses stdlib TLS verified by system trust roots and hostname. No proxy env
    and no redirect; response body capped at 8 KiB. No code or secret printed.
    """
    url = secure_endpoint(panel_url)
    if not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id) or role not in ("iran", "foreign"):
        raise WizardHold("Invalid Node pairing role/identity")
    if not isinstance(pairing_code, str) or not _CODE.fullmatch(pairing_code):
        raise WizardHold("Invalid pairing code format")
    if timeout < 1 or timeout > 30:
        raise WizardHold("Invalid request timeout")
    _verify_private_dir(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise WizardHold("Identity already exists; never rotate automatically")
    encoded = json.dumps(
        {"node_id": node_id, "role": role, "pairing_code": pairing_code}
    ).encode("utf-8")
    context = ssl.create_default_context()
    opener = request.build_opener(
        request.ProxyHandler({}),
        request.HTTPSHandler(context=context),
        NoRedirect(),
    )
    req = request.Request(
        url,
        data=encoded,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cache-Control": "no-store",
        },
    )
    try:
        with opener.open(req, timeout=timeout) as response:
            if response.status != 200:
                raise WizardHold("Pairing was not accepted")
            raw = response.read(8193)
            if len(raw) > 8192:
                raise WizardHold("Oversized pairing response")
            payload = json.loads(raw)
    except (error.HTTPError, error.URLError, ssl.SSLError, TimeoutError, ValueError, UnicodeError) as exc:
        # Deliberately do NOT include request URL, HTTP body or exception.
        raise WizardHold("Pairing failed; check certificate and gateway readiness") from exc
    if not isinstance(payload, dict) or payload.get("node_id") != node_id:
        raise WizardHold("Pairing Node ID mismatch")
    store_identity(destination, node_id, payload.get("node_secret", ""))
    return node_id




def _field_trial_gate() -> None:
    if os.geteuid() != 0:
        raise WizardHold("Field Trial pairing requires root")
    if os.environ.get("UOPTI_SMITE_PAIRING_FIELD_TRIAL") != "YES":
        raise WizardHold("Explicit disposable-host Field Trial pairing approval required")


def _private_dir(path: Path, *, create: bool = False) -> None:
    if path.is_symlink():
        raise WizardHold("Private directory may not be a symlink")
    if create and not path.exists():
        parent = path.parent
        if not parent.is_dir() or parent.is_symlink():
            raise WizardHold("Private directory parent is unavailable or unsafe")
        path.mkdir(mode=0o700)
    try:
        item = path.lstat()
    except OSError as exc:
        raise WizardHold("Required private directory is unavailable") from exc
    if (
        not stat.S_ISDIR(item.st_mode)
        or item.st_uid != os.geteuid()
        or stat.S_IMODE(item.st_mode) != 0o700
    ):
        raise WizardHold("Private directory must be root-owned mode 0700")


def _regular(path: Path, *, mode: int | None = None, limit: int = 1_048_576) -> bytes:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_size > limit
            or (mode is not None and stat.S_IMODE(before.st_mode) != mode)
        ):
            raise WizardHold("Required file is unsafe")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or opened.st_size > limit
                or (mode is not None and stat.S_IMODE(opened.st_mode) != mode)
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                raise WizardHold("Required file changed during inspection")
            return stream.read(limit + 1)
    except OSError as exc:
        raise WizardHold("Required file is unavailable") from exc


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    if path.is_symlink():
        raise WizardHold("Refusing symlinked destination")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise WizardHold("Destination parent is unavailable or unsafe")
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)
        raise


def _env_map(raw: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in raw.decode("utf-8").splitlines():
        if not row or row.lstrip().startswith("#") or "=" not in row:
            continue
        key, value = row.split("=", 1)
        result[key] = value
    return result


def _env_update(raw: bytes, updates: dict[str, str]) -> bytes:
    lines = raw.decode("utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for row in lines:
        if row and not row.lstrip().startswith("#") and "=" in row:
            key = row.split("=", 1)[0]
            if key in updates:
                if key in seen:
                    raise WizardHold("Duplicate security environment key")
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(row)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    return ("\n".join(out).rstrip("\n") + "\n").encode("utf-8")


def _host_failure_context(command: list[str], stderr: str = "") -> str:
    """Only fixed labels may cross the subprocess diagnostic boundary."""
    if command == ["python3", "-B", str(CANDIDATE_HELPER), "--prepare"]:
        reasons = {
            "HOLD: Private directory must be owned and mode 0700": "private-directory-permissions",
            "HOLD: Replay storage anchor is unsafe": "unsafe-storage-anchor",
            "HOLD: Replay storage anchor is unavailable": "missing-storage-anchor",
            "HOLD: Refusing symlinked private directory": "symlinked-private-directory",
            "HOLD: Replay storage hierarchy is ambiguous or symlinked": "unsafe-storage-hierarchy",
        }
        reason = reasons.get(stderr.strip(), "helper-failed")
        return "security-candidate-prepare/" + reason
    if command[:2] == ["docker", "run"]:
        return "offline-replay-enrollment"
    if command[:2] == ["docker", "inspect"] or command[:3] == ["docker", "image", "inspect"]:
        return "docker-inspection"
    if command[:2] == ["docker", "compose"]:
        # Never echo Docker stderr: it may contain paths, environment values
        # or credentials. Report only reviewed, fixed diagnostic categories.
        error = stderr.lower()
        if "container name" in error and "already in use" in error:
            return "docker-compose/name-conflict"
        if "manifest unknown" in error or "pull access denied" in error:
            return "docker-compose/image-unavailable"
        if "no such image" in error:
            return "docker-compose/image-missing"
        if "port is already allocated" in error or "address already in use" in error:
            return "docker-compose/port-conflict"
        if "invalid mount config" in error or "error while creating mount source path" in error:
            return "docker-compose/mount-error"
        if "permission denied" in error:
            return "docker-compose/permission-denied"
        if "network" in error and "not found" in error:
            return "docker-compose/network-missing"
        return "docker-compose/unclassified"
    return "host-operation"


def _run(command: list[str], *, timeout: int = 60, capture: bool = False) -> str:
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        raise WizardHold("Host operation timed out [" + _host_failure_context(command) + "]") from exc
    except OSError as exc:
        raise WizardHold("Host operation unavailable [" + _host_failure_context(command) + "]") from exc
    if completed.returncode != 0:
        raise WizardHold(
            "Required host operation was rejected ["
            + _host_failure_context(command, completed.stderr)
            + f"; exit={completed.returncode}]"
        )
    return completed.stdout.strip() if capture else ""


def _wait_container(name: str, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = _run(
            ["docker", "inspect", "-f",
             "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
             name],
            timeout=10, capture=True,
        )
        if state in ("running healthy", "running none"):
            return
        time.sleep(2)
    raise WizardHold("Container did not become healthy")


def _expected_panel_signed_control_override() -> bytes:
    return (
        "services:\n"
        "  smite-panel:\n"
        "    volumes:\n"
        f"      - {TRUSTED_NODES_DIR}:/etc/smite-panel/trusted-nodes:ro\n"
    ).encode("utf-8")


def _panel_compose_command(*, staged_signed_control: bool = False) -> list[str]:
    """Keep RC7's actual Compose project and reviewed active file set.

    Fresh RC6/RC7 installs use a transaction-scoped COMPOSE_PROJECT_NAME.
    Reconstructing from the working directory would create a second project
    named "smite" and collide with the existing smite-panel container.
    """
    project = _run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "com.docker.compose.project"}}',
         "smite-panel"],
        timeout=15, capture=True,
    )
    if not re.fullmatch(r"uopti_rc6_[0-9a-f]{32}", project):
        raise WizardHold("Panel Compose transaction identity is missing or unexpected")

    ambient_project = os.environ.get("COMPOSE_PROJECT_NAME", "")
    if ambient_project and ambient_project != project:
        raise WizardHold("Panel Compose environment conflicts with installed transaction")

    service = _run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "com.docker.compose.service"}}',
         "smite-panel"],
        timeout=15, capture=True,
    )
    if service != "smite-panel":
        raise WizardHold("Panel container is not owned by reviewed Compose service")

    raw_files = _run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "com.docker.compose.project.config_files"}}',
         "smite-panel"],
        timeout=15, capture=True,
    )
    files = raw_files.split(",")
    base = str(PANEL_COMPOSE)
    overlay = str(PANEL_SECURITY_OVERRIDE)
    if (
        not files or files[0] != base
        or len(files) != len(set(files))
        or len(files) > 2
        or any(name not in (base, overlay) for name in files)
    ):
        raise WizardHold("Panel active Compose file set is not reviewed")
    if PANEL_SECURITY_OVERRIDE.exists() or PANEL_SECURITY_OVERRIDE.is_symlink():
        if overlay not in files:
            # This explicit admission is used ONLY by the first signed IR
            # activation, immediately after its reviewed helper stages the
            # exact expected override. An ordinary pairing enable/restart
            # still rejects a stray inactive overlay.
            if not staged_signed_control or files != [base]:
                raise WizardHold("Inactive Panel security override requires explicit review")
            actual = _regular(PANEL_SECURITY_OVERRIDE, mode=0o600, limit=32_000)
            if actual != _expected_panel_signed_control_override():
                raise WizardHold("Staged Panel signed-control override is untrusted")
            files.append(overlay)
    elif overlay in files:
        raise WizardHold("Active Panel signed-control override is missing")

    command = ["docker", "compose", "--project-name", project]
    for name in files:
        path = Path(name)
        if not path.is_file() or path.is_symlink():
            raise WizardHold("Panel active Compose file is missing or unsafe")
        command.extend(["-f", name])
    return command


def _ir_node_compose_command(*, staged_candidate: bool = False, rollback: bool = False) -> list[str]:
    """Never change Compose ownership when activating the co-located IR Node.

    An inactive candidate may be included only in the explicit activation
    operation after the reviewed candidate preparer has validated it.
    Rollback drops only this candidate, never another active overlay.
    """
    project = _run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "com.docker.compose.project"}}',
         "smite-node"],
        timeout=15, capture=True,
    )
    panel_project = _run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "com.docker.compose.project"}}',
         "smite-panel"],
        timeout=15, capture=True,
    )
    if (not re.fullmatch(r"uopti_rc6_[0-9a-f]{32}", project)
            or project != panel_project):
        raise WizardHold("Iran Node Compose project differs from installed Panel transaction")
    ambient_project = os.environ.get("COMPOSE_PROJECT_NAME", "")
    if ambient_project and ambient_project != project:
        raise WizardHold("Iran Node Compose environment conflicts with installed transaction")
    service = _run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "com.docker.compose.service"}}',
         "smite-node"],
        timeout=15, capture=True,
    )
    if service != "smite-node":
        raise WizardHold("Iran Node container is not owned by reviewed Compose service")
    raw_files = _run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "com.docker.compose.project.config_files"}}',
         "smite-node"],
        timeout=15, capture=True,
    )
    base = str(NODE_COMPOSE)
    candidate = str(NODE_SECURITY_CANDIDATE)
    files = raw_files.split(",")
    if files not in ([base], [base, candidate]):
        raise WizardHold("Iran Node active Compose file set is not reviewed")
    if (staged_candidate and files != [base]) or (
        not staged_candidate and not rollback and files != [base]
    ):
        raise WizardHold("Iran Node security candidate is already active")
    if staged_candidate:
        _regular(NODE_SECURITY_CANDIDATE, mode=0o600, limit=128_000)
    if not NODE_COMPOSE.is_file() or NODE_COMPOSE.is_symlink():
        raise WizardHold("Iran Node base Compose file is missing or unsafe")
    command = ["docker", "compose", "--project-name", project, "-f", base]
    if staged_candidate:
        command.extend(["-f", candidate])
    return command


def _pairing_secrets() -> tuple[str, str]:
    _private_dir(PAIRING_PRIVATE_DIR, create=True)
    if PAIRING_SECRETS.exists() or PAIRING_SECRETS.is_symlink():
        try:
            doc = json.loads(_regular(PAIRING_SECRETS, mode=0o600, limit=4096))
        except (ValueError, UnicodeError, TypeError) as exc:
            raise WizardHold("Stored Panel pairing secrets are invalid") from exc
        master, ingress = doc.get("master_key"), doc.get("ingress_token")
        if (
            not isinstance(master, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}=", master)
            or not isinstance(ingress, str)
            or not re.fullmatch(r"[a-f0-9]{64}", ingress)
        ):
            raise WizardHold("Stored Panel pairing secrets are invalid")
        return master, ingress
    master = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    ingress = secrets.token_hex(32)
    content = (json.dumps(
        {"schema": 1, "master_key": master, "ingress_token": ingress},
        sort_keys=True, separators=(",", ":"),
    ) + "\n").encode("ascii")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(PAIRING_SECRETS, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        PAIRING_SECRETS.unlink(missing_ok=True)
        raise
    return master, ingress


def _ensure_panel_signed_registration_schema() -> None:
    """Back up Panel SQLite once, then admit both signed-pairing schemas."""
    script = r"""
from pathlib import Path
import os
import sqlite3
import stat

from app.config import settings
from app.node_pairing_store import initialize_schema
from app.signed_node_registration import initialize_replay_schema

db = Path(settings.db_path).resolve()
if db.is_symlink() or not db.is_file():
    raise RuntimeError("Panel database unavailable")

backup = db.with_name(db.name + ".u-opti-pre-signed-registration.bak")
if backup.exists() or backup.is_symlink():
    item = backup.lstat()
    if (
        not stat.S_ISREG(item.st_mode)
        or item.st_uid != os.geteuid()
        or stat.S_IMODE(item.st_mode) != 0o600
        or item.st_nlink != 1
    ):
        raise RuntimeError("Existing Panel migration backup is unsafe")
else:
    old_umask = os.umask(0o077)
    try:
        source = sqlite3.connect(str(db), timeout=15)
        target = sqlite3.connect(str(backup), timeout=15)
        try:
            source.backup(target)
            if target.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise RuntimeError("Panel migration backup integrity failed")
        finally:
            target.close()
            source.close()
    finally:
        os.umask(old_umask)
    os.chmod(backup, 0o600)

item = backup.lstat()
if (
    not stat.S_ISREG(item.st_mode)
    or item.st_uid != os.geteuid()
    or stat.S_IMODE(item.st_mode) != 0o600
    or item.st_nlink != 1
    or item.st_size == 0
):
    raise RuntimeError("Panel migration backup admission failed")

initialize_schema(db)
initialize_replay_schema(db)

with sqlite3.connect(str(db), timeout=15) as conn:
    pairing = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='smite_node_identities'"
    ).fetchone()[0]
    replay = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='smite_node_inbound_nonces'"
    ).fetchone()[0]
if pairing != 1 or replay != 1:
    raise RuntimeError("Signed Panel schema verification failed")

print("PANEL_SIGNED_SCHEMA=READY")
"""
    result = _run(
        ["docker", "exec", "smite-panel", "python3", "-c", script],
        timeout=60, capture=True,
    )
    if result != "PANEL_SIGNED_SCHEMA=READY":
        raise WizardHold("Panel signed schema migration admission failed")


def _require_panel_signed_registration_schema() -> None:
    """Read-only activation preflight: never create a missing Panel schema."""
    script = r"""
from pathlib import Path
import sqlite3
from app.config import settings

db = Path(settings.db_path).resolve()
if not db.is_file() or db.is_symlink():
    print("PANEL_SIGNED_REGISTRATION_SCHEMA=MISSING")
else:
    try:
        with sqlite3.connect(db.absolute().as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
            pairing = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name='smite_node_identities'"
            ).fetchone()[0]
            replay = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name='smite_node_inbound_nonces'"
            ).fetchone()[0]
        print(
            "PANEL_SIGNED_REGISTRATION_SCHEMA=READY"
            if pairing == 1 and replay == 1
            else "PANEL_SIGNED_REGISTRATION_SCHEMA=MISSING"
        )
    except sqlite3.Error:
        print("PANEL_SIGNED_REGISTRATION_SCHEMA=MISSING")
"""
    result = _run(
        ["docker", "exec", "smite-panel", "python3", "-c", script],
        timeout=20, capture=True,
    )
    if result != "PANEL_SIGNED_REGISTRATION_SCHEMA=READY":
        raise WizardHold(
            "Panel signed-registration replay schema is missing; "
            "run secure Panel pairing enablement first"
        )


def _render_pairing_location() -> str:
    return """    # BEGIN U-OPTI SMITE SIGNED PAIRING REDEEM
    location = /api/node-pairing/redeem {
        limit_except POST { deny all; }
        client_max_body_size 16k;
        proxy_http_version 1.1;
        proxy_request_buffering on;
        include /etc/nginx/u-opti-smite-pairing-secret.conf;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Connection "";
        proxy_pass http://127.0.0.1:8000;
        proxy_connect_timeout 5s;
        proxy_read_timeout 15s;
        proxy_send_timeout 15s;
        proxy_cache off;
        add_header Cache-Control "no-store" always;
        access_log off;
    }
    # END U-OPTI SMITE SIGNED PAIRING REDEEM

"""


def _patch_nginx_pairing(domain: str, ingress: str) -> tuple[bytes, bytes | None]:
    backend_before = _regular(NGINX_BACKEND, limit=256_000)
    text = backend_before.decode("utf-8")
    if (
        not text.startswith("# Managed by U-OPTI - Smite Panel TLS backend\n")
        or f"server_name {domain};" not in text
    ):
        raise WizardHold("Smite TLS backend is not the reviewed U-OPTI layout")
    marker = "# BEGIN U-OPTI SMITE SIGNED PAIRING REDEEM"
    if marker in text:
        if text.count(marker) != 1 or "include /etc/nginx/u-opti-smite-pairing-secret.conf;" not in text:
            raise WizardHold("Existing pairing location has unexpected drift")
    else:
        anchor = "    location / {\n"
        if text.count(anchor) != 1:
            raise WizardHold("Smite TLS backend root location is ambiguous")
        text = text.replace(anchor, _render_pairing_location() + anchor, 1)

    include_before = None
    if NGINX_PAIRING_SECRET.exists() or NGINX_PAIRING_SECRET.is_symlink():
        include_before = _regular(NGINX_PAIRING_SECRET, mode=0o600, limit=4096)
    secret_line = f'proxy_set_header X-Smite-Pairing-Ingress "{ingress}";\n'.encode("ascii")
    _atomic_write(NGINX_PAIRING_SECRET, secret_line, 0o600)
    _atomic_write(NGINX_BACKEND, text.encode("utf-8"), stat.S_IMODE(NGINX_BACKEND.stat().st_mode))
    return backend_before, include_before


def enable_panel_field_trial(state: dict[str, str] | None = None) -> None:
    _field_trial_gate()
    _require_no_active_engine_overlays()
    current = state_values() if state is None else state
    if current.get("SMITE_ROLE") != "panel-iran":
        raise WizardHold("Panel pairing activation is IR Panel only")
    domain = current.get("SMITE_PANEL_DOMAIN", "")
    secure_endpoint("https://" + domain)

    panel_env_before = _regular(PANEL_ENV, mode=0o600, limit=64_000)
    panel_values = _env_map(panel_env_before)
    if (
        panel_values.get("SMITE_NODE_REGISTRATION_MODE") != "signed"
        or panel_values.get("SMITE_PANEL_AGENT_AUTH_MODE") != "signed"
    ):
        raise WizardHold("Panel is not the clean-RC signed baseline")
    _regular(PANEL_COMPOSE, limit=256_000)
    if not NGINX_BACKEND.is_file() or NGINX_BACKEND.is_symlink():
        raise WizardHold("Configure the reviewed Smite HTTPS/443 gateway first")

    master, ingress = _pairing_secrets()
    backend_before: bytes | None = None
    include_before: bytes | None = None
    try:
        # Both migrations are required for signed Node check-in. The helper
        # takes a private SQLite backup before the replay schema is added.
        _ensure_panel_signed_registration_schema()

        updated = _env_update(panel_env_before, {
            "SMITE_NODE_PAIRING_PREVIEW_ENABLED": "true",
            "SMITE_NODE_PAIRING_MASTER_KEY": master,
            "SMITE_NODE_PAIRING_INGRESS_TOKEN": ingress,
        })
        _atomic_write(PANEL_ENV, updated, 0o600)
        backend_before, include_before = _patch_nginx_pairing(domain, ingress)

        _run(["nginx", "-t"], timeout=20)
        command = _panel_compose_command()
        _run(command + ["up", "-d", "--no-build", "--force-recreate", "smite-panel"], timeout=120)
        _wait_container("smite-panel", 90)
        check = _run(
            ["docker", "exec", "smite-panel", "python3", "-c",
             "from app.config import settings; "
             "assert settings.smite_node_pairing_preview_enabled is True; "
             "assert settings.smite_node_registration_mode == 'signed'; "
             "assert settings.smite_panel_agent_auth_mode == 'signed'; "
             "assert bool(settings.smite_node_pairing_master_key); "
             "assert bool(settings.smite_node_pairing_ingress_token); "
             "print('PANEL_SIGNED_PAIRING_RUNTIME=READY')"],
            timeout=20, capture=True,
        )
        if check != "PANEL_SIGNED_PAIRING_RUNTIME=READY":
            raise WizardHold("Panel pairing runtime verification failed")
        _run(["systemctl", "reload", "nginx"], timeout=30)
    except Exception as exc:
        try:
            _atomic_write(PANEL_ENV, panel_env_before, 0o600)
            if backend_before is not None:
                _atomic_write(
                    NGINX_BACKEND, backend_before,
                    stat.S_IMODE(NGINX_BACKEND.stat().st_mode),
                )
            if include_before is None:
                NGINX_PAIRING_SECRET.unlink(missing_ok=True)
            else:
                _atomic_write(NGINX_PAIRING_SECRET, include_before, 0o600)
            _run(["nginx", "-t"], timeout=20)
            _run(["systemctl", "reload", "nginx"], timeout=30)
            command = _panel_compose_command()
            _run(command + ["up", "-d", "--no-build", "--force-recreate", "smite-panel"], timeout=120)
            _wait_container("smite-panel", 90)
        except Exception:
            pass
        if isinstance(exc, WizardHold):
            raise
        raise WizardHold("Panel pairing activation failed and rollback was attempted") from exc

    print("PANEL_PAIRING_SCHEMA=READY")
    print("PANEL_SIGNED_REGISTRATION_REPLAY_SCHEMA=READY")
    print("PANEL_PAIRING_HTTPS_443_EXACT_PATH=READY")
    print("PANEL_PAIRING_PREVIEW=ENABLED_FIELD_TRIAL")
    print("LEGACY_NODE_REGISTRATION=DISABLED")
    print("PRODUCTION_ACTIVATION=NO")


def _identity_record(path: Path | None = None) -> tuple[str, str]:
    path = IDENTITY_FILE if path is None else path
    _verify_private_dir(path.parent)
    try:
        doc = json.loads(_regular(path, mode=0o600, limit=4096))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise WizardHold("Paired Node identity is invalid") from exc
    node_id, secret = doc.get("node_id"), doc.get("node_secret")
    if (
        not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id)
        or not isinstance(secret, str) or not _SECRET.fullmatch(secret)
    ):
        raise WizardHold("Paired Node identity is invalid")
    return node_id, secret


def _replay_artifacts_valid() -> bool:
    node_id, secret = _identity_record()
    marker = IDENTITY_DIR / "replay-enrollment.json"
    if not marker.exists() and not REPLAY_DB.exists():
        return False
    if not marker.exists() or not REPLAY_DB.exists():
        raise WizardHold("Partial replay enrollment detected; quarantine and review")
    try:
        doc = json.loads(_regular(marker, mode=0o600, limit=4096))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise WizardHold("Replay enrollment marker is invalid") from exc
    expected_binding = hmac.new(
        secret.encode("ascii"),
        b"smite-replay-key-binding-v1:" + node_id.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if (
        set(doc) != {"schema", "node_id", "replay_database", "status", "key_binding"}
        or doc.get("schema") != 1
        or doc.get("node_id") != node_id
        or doc.get("replay_database") != CONTAINER_REPLAY
        or doc.get("status") != "ENROLLMENT_STARTED"
        or not isinstance(doc.get("key_binding"), str)
        or not hmac.compare_digest(doc["key_binding"], expected_binding)
    ):
        raise WizardHold("Replay enrollment identity/key continuity failed")
    _regular(REPLAY_DB, mode=0o600, limit=256 * 1024 * 1024)
    try:
        with sqlite3.connect(
            REPLAY_DB.absolute().as_uri() + "?mode=ro", uri=True, timeout=3
        ) as db:
            if db.execute("PRAGMA user_version").fetchone() != (1,):
                raise WizardHold("Replay database schema is untrusted")
            nodes = db.execute("SELECT node_id FROM replay_store_identity").fetchall()
            if nodes != [(node_id,)]:
                raise WizardHold("Replay database Node identity mismatch")
            db.execute("SELECT node_id,nonce,expires_at FROM agent_nonces LIMIT 0")
    except sqlite3.Error as exc:
        raise WizardHold("Replay database validation failed") from exc
    return True


def _prepare_security_candidate() -> None:
    if not CANDIDATE_HELPER.is_file() or CANDIDATE_HELPER.is_symlink():
        raise WizardHold("Reviewed Node security candidate helper is unavailable")
    result = _run(
        ["python3", "-B", str(CANDIDATE_HELPER), "--prepare"],
        timeout=30, capture=True,
    )
    if "STAGE9=" not in result or "COMPOSE_CANDIDATE=INERT_NOT_APPLIED" not in result:
        raise WizardHold("Node security candidate preparation failed")
    _regular(NODE_SECURITY_CANDIDATE, mode=0o600, limit=128_000)


def _provision_replay_once() -> None:
    if _replay_artifacts_valid():
        return
    _private_dir(REPLAY_DIR)
    image = _run(
        ["docker", "inspect", "-f", "{{.Config.Image}}", "smite-node"],
        timeout=10, capture=True,
    )
    # Independently reviewed Smite Stage15 run 40461876836, job 122048191494,
    # source 4e16633a304db6c03f7f2911cc7d77213b0c4ec1. This is a test-only
    # Docker image ID, NOT a signed production registry digest. Recheck the running
    # container and the local tag to the exact reviewed IMAGE ID; use only
    # the immutable ID for one-time offline Replay provisioning. Do not
    # broaden acceptance to arbitrary local tags or disable signed checks.
    if image == "smite-node:stage15-local":
        replay_image = _require_stage15_identity("node")
    elif re.fullmatch(r"ghcr\.io/aghajani82/smite-node@sha256:[a-f0-9]{64}", image):
        replay_image = image  # Existing immutable GHCR path remains unchanged.
    else:
        raise WizardHold("Active Node is not an admitted immutable Field Trial image")
    output = _run(
        [
            "docker", "run", "--rm", "--pull", "never", "--network", "none",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,source={IDENTITY_DIR},target=/run/smite-node-identity",
            "--mount", f"type=bind,source={REPLAY_DIR},target=/var/lib/smite-node/auth",
            "--entrypoint", "python3", replay_image,
            "-m", "app.replay_enrollment",
            "--identity", CONTAINER_IDENTITY,
            "--replay-db", CONTAINER_REPLAY,
            "--confirm-first-provision",
        ],
        timeout=90, capture=True,
    )
    if (
        "REPLAY_DB_FIRST_ENROLLMENT=PROVISIONED" not in output
        or "ENROLLMENT_MARKER=PERSISTENT_IN_IDENTITY_DIRECTORY" not in output
    ):
        raise WizardHold("Reviewed one-time replay enrollment did not complete")
    if not _replay_artifacts_valid():
        raise WizardHold("Replay enrollment artifacts failed local validation")


def _panel_override_and_origin(node_id: str, node_name: str) -> tuple[bytes | None, bytes | None, bytes]:
    _private_dir(TRUSTED_NODES_DIR, create=True)
    origin_before = None
    nodes: dict[str, dict[str, str]] = {}
    if APPROVED_ORIGINS.exists() or APPROVED_ORIGINS.is_symlink():
        origin_before = _regular(APPROVED_ORIGINS, mode=0o600, limit=64_000)
        try:
            old = json.loads(origin_before)
        except (ValueError, UnicodeError, TypeError) as exc:
            raise WizardHold("Approved Node origin file is invalid") from exc
        if old.get("version") != 1 or not isinstance(old.get("nodes"), dict):
            raise WizardHold("Approved Node origin schema is invalid")
        nodes = old["nodes"]
    expected = {
        "role": "iran",
        "node_name": node_name,
        "origin": "http://127.0.0.1:8888",
        "control_url": "http://127.0.0.1:8888/api/agent",
    }
    existing = nodes.get(node_id)
    if existing is not None and existing != expected:
        raise WizardHold("Existing approved Node origin conflicts with paired identity")
    nodes[node_id] = expected
    payload = (json.dumps(
        {"version": 1, "nodes": nodes},
        sort_keys=True, separators=(",", ":"),
    ) + "\n").encode("utf-8")
    _atomic_write(APPROVED_ORIGINS, payload, 0o600)

    override_before = None
    if PANEL_SECURITY_OVERRIDE.exists() or PANEL_SECURITY_OVERRIDE.is_symlink():
        override_before = _regular(PANEL_SECURITY_OVERRIDE, mode=0o600, limit=32_000)
    override = _expected_panel_signed_control_override()
    if override_before is not None and override_before != override:
        raise WizardHold("Panel signed-control Compose override has unexpected drift")
    _atomic_write(PANEL_SECURITY_OVERRIDE, override, 0o600)

    env_before = _regular(PANEL_ENV, mode=0o600, limit=64_000)
    _atomic_write(
        PANEL_ENV,
        _env_update(env_before, {
            "SMITE_SIGNED_NODE_ORIGINS_PATH":
                "/etc/smite-panel/trusted-nodes/approved-origins.json",
        }),
        0o600,
    )
    return origin_before, override_before, env_before


def _restart_panel_with_signed_control(*, staged_signed_control: bool = False) -> None:
    command = _panel_compose_command(staged_signed_control=staged_signed_control)
    _run(command + ["config", "--quiet"], timeout=30)
    _run(command + ["up", "-d", "--no-build", "--force-recreate", "smite-panel"], timeout=120)
    _wait_container("smite-panel", 90)


def _local_signed_replay_probe() -> None:
    script = r'''
import json, secrets, urllib.error, urllib.request
from app.agent_auth import read_identity
from app.node_auth import sign_request
node_id, secret = read_identity("/run/smite-node-identity/node-identity.json")
target="/api/agent/status"
url="http://127.0.0.1:8888"+target
headers=sign_request(secret=secret,node_id=node_id,method="GET",target=target,
                     body=b"",nonce=secrets.token_hex(16))
req=urllib.request.Request(url,headers=headers)
with urllib.request.urlopen(req,timeout=5) as response:
    data=json.load(response)
    assert response.status==200 and data.get("status")=="ok"
try:
    urllib.request.urlopen(req,timeout=5)
except urllib.error.HTTPError as exc:
    assert exc.code==401
else:
    raise SystemExit(2)
print("LOCAL_SIGNED_HMAC_REPLAY=PASS")
'''
    result = _run(
        ["docker", "exec", "smite-node", "python3", "-c", script],
        timeout=20, capture=True,
    )
    if result != "LOCAL_SIGNED_HMAC_REPLAY=PASS":
        raise WizardHold("Local signed HMAC/replay probe failed")


def _wait_panel_signed_checkin(node_id: str, timeout: int = 50) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with sqlite3.connect(
                PANEL_DB.absolute().as_uri() + "?mode=ro", uri=True, timeout=2
            ) as db:
                row = db.execute(
                    "SELECT status, metadata FROM nodes WHERE id=?", (node_id,)
                ).fetchone()
            if row is not None and row[0] == "active":
                meta = json.loads(row[1] or "{}")
                if meta.get("provisioning") == "signed_checkin":
                    return
        except (sqlite3.Error, ValueError, TypeError):
            pass
        time.sleep(2)
    raise WizardHold("Signed Node check-in did not reach active state")


def _panel_to_ir_signed_probe(node_id: str) -> None:
    script = (
        "import asyncio,sys; "
        "from app.node_client import NodeClient; "
        "result=asyncio.run(NodeClient().get_tunnel_status(sys.argv[1])); "
        "assert isinstance(result,dict) and result.get('status')=='ok'; "
        "print('PANEL_TO_IR_SIGNED_HMAC=PASS')"
    )
    result = _run(
        ["docker", "exec", "smite-panel", "python3", "-c", script, node_id],
        timeout=30, capture=True,
    )
    if result != "PANEL_TO_IR_SIGNED_HMAC=PASS":
        raise WizardHold("Panel-to-Iran signed HMAC probe failed")


def _require_no_active_engine_overlays() -> None:
    for path in (NODE_DIR / "docker-compose.frp-stage15.yml",
                 NODE_DIR / "docker-compose.wss-stage15.yml",
                 PANEL_DIR / "docker-compose.wss-stage15.yml"):
        if path.exists() or path.is_symlink():
            raise WizardHold("Roll back tunnels, WSS and FRP through their wizard before pairing reactivation")


def activate_ir_node_field_trial(state: dict[str, str] | None = None) -> None:
    _field_trial_gate()
    _require_no_active_engine_overlays()
    current = state_values() if state is None else state
    if current.get("SMITE_ROLE") != "panel-iran":
        raise WizardHold("This activation step currently admits only the co-located IR Node")
    node_name = current.get("SMITE_NODE_NAME", "")
    if not node_name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", node_name):
        raise WizardHold("IR Node name is unavailable or invalid")
    node_id, _ = _identity_record()
    node_env = _regular(NODE_DIR / ".env", mode=0o600, limit=64_000)
    values = _env_map(node_env)
    if (
        values.get("SMITE_NODE_PANEL_AUTH_MODE") != "paused"
        or values.get("SMITE_AGENT_AUTH_MODE") != "strict"
        or values.get("PANEL_ADDRESS") != current.get("SMITE_PANEL_DOMAIN", "") + ":443"
    ):
        raise WizardHold("IR Node is not at the reviewed paused+strict HTTPS/443 baseline")

    # Preflight both original transaction owners BEFORE staging any files.
    # An unexpected/inactive Panel overlay must fail before mutations.
    _panel_compose_command()
    _ir_node_compose_command()

    # Fail before any Panel/Node recreate if option 2 did not complete
    # both signed-registration migrations.
    _require_panel_signed_registration_schema()

    origin_before = override_before = panel_env_before = None
    node_was_applied = False
    node_recreate_attempted = False
    try:
        origin_before, override_before, panel_env_before = _panel_override_and_origin(
            node_id, node_name
        )
        _restart_panel_with_signed_control(staged_signed_control=True)

        _prepare_security_candidate()
        _provision_replay_once()
        command = _ir_node_compose_command(staged_candidate=True)
        _run(command + ["config", "--quiet"], timeout=30)
        node_recreate_attempted = True
        _run(
            command + ["up", "-d", "--no-build", "--force-recreate", "smite-node"],
            timeout=120,
        )
        node_was_applied = True
        _wait_container("smite-node", 90)
        effective = _run(
            ["docker", "inspect", "-f",
             "{{range .Config.Env}}{{println .}}{{end}}", "smite-node"],
            timeout=10, capture=True,
        )
        if (
            "SMITE_NODE_PANEL_AUTH_MODE=signed" not in effective.splitlines()
            or "SMITE_AGENT_AUTH_MODE=strict" not in effective.splitlines()
        ):
            raise WizardHold("Signed Node environment was not applied")
        _local_signed_replay_probe()
        _wait_panel_signed_checkin(node_id)
        _panel_to_ir_signed_probe(node_id)
    except Exception as exc:
        node_rollback_ok = not node_recreate_attempted
        if node_recreate_attempted:
            try:
                command = _ir_node_compose_command(rollback=True)
                _run(command + ["up", "-d", "--no-build", "--force-recreate", "smite-node"],
                     timeout=120)
                _wait_container("smite-node", 90)
                effective = _run(
                    ["docker", "inspect", "-f",
                     "{{range .Config.Env}}{{println .}}{{end}}", "smite-node"],
                    timeout=10, capture=True,
                ).splitlines()
                node_rollback_ok = (
                    "SMITE_NODE_PANEL_AUTH_MODE=paused" in effective
                    and "SMITE_AGENT_AUTH_MODE=strict" in effective
                )
            except Exception:
                node_rollback_ok = False
        panel_rollback_ok = panel_env_before is None
        if panel_env_before is not None:
            try:
                _atomic_write(PANEL_ENV, panel_env_before, 0o600)
                if origin_before is None:
                    APPROVED_ORIGINS.unlink(missing_ok=True)
                else:
                    _atomic_write(APPROVED_ORIGINS, origin_before, 0o600)
                if override_before is None:
                    PANEL_SECURITY_OVERRIDE.unlink(missing_ok=True)
                else:
                    _atomic_write(PANEL_SECURITY_OVERRIDE, override_before, 0o600)
                _restart_panel_with_signed_control()
                panel_rollback_ok = True
            except Exception:
                panel_rollback_ok = False
        if not node_rollback_ok or not panel_rollback_ok:
            raise WizardHold(
                "CRITICAL: Signed IR activation failed and safe Panel/Node "
                "rollback could not be verified; stop and inspect host"
            ) from exc
        if isinstance(exc, WizardHold):
            raise
        raise WizardHold("Signed IR Node activation failed; paused rollback verified") from exc

    print("IR_SIGNED_NODE_RUNTIME=ACTIVE_FIELD_TRIAL")
    print("IR_SIGNED_NODE_CHECKIN=PASS")
    print("IR_LOCAL_HMAC_REPLAY=PASS")
    print("PANEL_TO_IR_SIGNED_HMAC=PASS")
    print("LEGACY_AUTH_FALLBACK=NO")
    print("PRODUCTION_ACTIVATION=NO")



# Signed KH activation is separate from IR's co-located Node workflow.
# It MUST wait for the reviewed Panel image to support path-pinned HTTPS.
_FOREIGN_NODE_IMAGE = (
    "ghcr.io/aghajani82/smite-node@sha256:"
    "9099262bb0d5fc8b737269f3e6dc16831a1d3e8b536b7b95ba131129ed06a7ec"
)
# A separate opt-in RC.2 lane; the existing RC.1 lane stays immutable.
_FOREIGN_NODE_IMAGE_RC2 = (
    "ghcr.io/aghajani82/smite-node@sha256:"
    "2338f101b4a1615ec966b9c6f7a3d3ff2bd3361d80956281cf40a61e7a458f78"
)
_FOREIGN_PANEL_IMAGE_RC2 = (
    "ghcr.io/aghajani82/smite-panel@sha256:"
    "9101898e19631d334b754ba8e956b63ab7dfaee304a8f9b954cf30a185125e8e"
)
_FOREIGN_PANEL_IMAGE_RC7 = "ghcr.io/aghajani82/smite-panel@sha256:180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8"
_FOREIGN_NODE_IMAGE_RC7 = "ghcr.io/aghajani82/smite-node@sha256:03ae4ca0f6d516374671fad4e32d44c13fbb46d0e4309bccb0265230d6fc4263"
# Branch-signed candidate for explicit *read-only* admission only. This image
# is not accepted by the existing foreign runtime activation or rollback path.
_FOREIGN_NODE_IMAGE_UNIFIED_TRIAL = (
    "ghcr.io/aghajani82/smite-node@sha256:"
    "2f63b5e1b3d262bf29bd2feaeec11b30b910c14e4d4b31ce4bb17e4fb24e2f4b"
)
_FOREIGN_RC2_COMPOSE_SHA = "8339ee07dcc3fe68da65dd8cb993b11d8da20b69b0470c032f8d504b0ea9de4e"
_FOREIGN_PATH = re.compile(r"/smite-node/[A-Za-z0-9_-]{16,80}\Z")



def _approved_foreign_control_url(url: str) -> tuple[str, str]:
    """Canonical operator-approved KH path; never derive it from Node metadata."""
    try:
        parts = parse.urlsplit(url)
        host, port = parts.hostname, parts.port
    except (ValueError, TypeError, AttributeError) as exc:
        raise WizardHold("Foreign HTTPS/443 control URL invalid") from exc
    if (
        not isinstance(url, str) or any(x.isspace() for x in url)
        or parts.scheme != "https" or not host or not _DOMAIN.fullmatch(host)
        or port not in (None, 443)
        or parts.username is not None or parts.password is not None
        or parts.query or parts.fragment
        or not _FOREIGN_PATH.fullmatch(parts.path)
    ):
        raise WizardHold("Foreign gateway hostname, port or prefix unapproved")
    return f"https://{host}:443", f"https://{host}{parts.path}"


# Stage15 source 4e16633a304db6c03f7f2911cc7d77213b0c4ec1; independently
# verified build IDs in Smite run 40461876836 / job 122048191494.
# Test artifacts only: never registry digests or production attestations.
_STAGE15_IMAGE_IDS = {
    "panel": "sha256:51f7e45e06e8cc59f4f04972090962b9c8d6db8aad2ec1591fc5ede0da112ae9",
    "node": "sha256:a417e8c28426da5eaf16d59925d5c89b52dbf7849ca560dfa9a765a1266b3991",
}


# Additional independently verified pair, NOT a replacement or arbitrary tag.
# Smite PR39 source 6981bd91; build 40830661751 / artifact 12878322384.
_STAGE15_FRP071_IMAGE_IDS = {'panel': 'sha256:e2345c7a4bf17cd9507ecf065cc736f4c2abfbe276a8c334805f4e52bb3808b5', 'node': 'sha256:cf0f3b12fc2c31cb0847fd5206304837661019d8f604853a8e956448c2576265'}

def _require_stage15_identity(role: str) -> str:
    if role not in _STAGE15_IMAGE_IDS:
        raise WizardHold("Unknown Stage15 image role")
    name = "smite-" + role
    tag = name + ":stage15-local"
    expected = _STAGE15_IMAGE_IDS[role]
    running = _run(["docker", "inspect", "-f", "{{.Image}}", name],
                   timeout=10, capture=True)
    local = _run(["docker", "image", "inspect", "-f", "{{.Id}}", tag],
                 timeout=10, capture=True)
    if running not in (expected, _STAGE15_FRP071_IMAGE_IDS[role]) or local != running:
        raise WizardHold("Stage15 running image and local tag must match the reviewed build")
    return running


def _require_stage15_foreign_compose(url: str, panel: str) -> None:
    """Check the resolved clean-install configuration before signed activation."""
    raw = _run(["docker", "compose", "-f", str(NODE_COMPOSE),
                "config", "--format", "json"], timeout=30, capture=True)
    try:
        service = json.loads(raw)["services"]["smite-node"]
        env = service["environment"]
        command = service["command"]
        if (
            service.get("image") != "smite-node:stage15-local"
            or service.get("network_mode") != "host"
            or service.get("ports") or service.get("privileged")
            or not isinstance(command, list)
            or command[:3] != ["uvicorn", "main:app", "--host"]
            or command[3:6] != ["127.0.0.1", "--port", "8888"]
            or env.get("SMITE_NODE_PANEL_AUTH_MODE") != "paused"
            or env.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or env.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
            or env.get("PANEL_ADDRESS") != panel + ":443"
            or env.get("SMITE_CONTROL_ADDRESS") != url
        ):
            raise WizardHold("Stage15 Foreign effective Compose security has drifted")
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise WizardHold("Stage15 Foreign effective Compose invalid") from exc
    if _run(["docker", "inspect", "-f", "{{.State.Health.Status}}", "smite-node"],
            timeout=10, capture=True) != "healthy":
        raise WizardHold("Stage15 Foreign Node is not healthy")


def _require_panel_foreign_transport() -> None:
    """Admit reviewed image identity AND the path-pinned signed implementation."""
    image = _run(
        ["docker", "inspect", "-f", "{{.Config.Image}}", "smite-panel"],
        timeout=10, capture=True,
    )
    if image == "smite-panel:stage15-local":
        _require_stage15_identity("panel")
    elif image not in (_FOREIGN_PANEL_IMAGE_RC2, _FOREIGN_PANEL_IMAGE_RC7):
        raise WizardHold("Panel must run exact reviewed RC.2 or pinned Stage15 with foreign HMAC support")
    check = r"""
import inspect
from app.signed_agent_transport import validate_foreign_gateway_prefix, signed_agent_call
from app.node_client import NodeClient
assert 'gateway_control_url' in inspect.signature(signed_agent_call).parameters
assert 'pin["control_url"]' in inspect.getsource(NodeClient._signed_agent_request)
assert validate_foreign_gateway_prefix(
    origin="https://kh.example.net:443",
    control_url="https://kh.example.net/smite-node/0123456789abcdef",
) == "https://kh.example.net:443/smite-node/0123456789abcdef"
print("PANEL_FOREIGN_HMAC_GATEWAY=READY")
"""
    if _run(
        ["docker", "exec", "smite-panel", "python3", "-c", check],
        timeout=20, capture=True,
    ) != "PANEL_FOREIGN_HMAC_GATEWAY=READY":
        raise WizardHold("Panel image lacks reviewed foreign path-pinned HMAC")


def approve_foreign_origin_field_trial(
    *, node_id: str, node_name: str, control_url: str,
    state: dict[str, str] | None = None,
) -> None:
    """IR only; additive trust record, no Panel restart or unsigned fallback."""
    _field_trial_gate()
    current = state_values() if state is None else state
    if (current.get("SMITE_ROLE") != "panel-iran"
            or current.get("SMITE_MANAGED_VERSION") not in ("2.0.0-rc.1", "2.0.0-rc.7")):
        raise WizardHold("Foreign origin approval requires reviewed signed IR Panel")
    if not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id):
        raise WizardHold("Approved foreign Node UUID invalid")
    if (
        not isinstance(node_name, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", node_name)
        or node_name == current.get("SMITE_NODE_NAME")
    ):
        raise WizardHold("Approved foreign Node name invalid")
    origin, approved_url = _approved_foreign_control_url(control_url)
    panel_env = _env_map(_regular(PANEL_ENV, mode=0o600, limit=64_000))
    if (
        panel_env.get("SMITE_NODE_REGISTRATION_MODE") != "signed"
        or panel_env.get("SMITE_PANEL_AGENT_AUTH_MODE") != "signed"
        or panel_env.get("SMITE_NODE_PAIRING_PREVIEW_ENABLED") != "true"
        or panel_env.get("SMITE_SIGNED_NODE_ORIGINS_PATH")
            != "/etc/smite-panel/trusted-nodes/approved-origins.json"
    ):
        raise WizardHold("IR signed Panel origin trust is not configured")
    _require_panel_signed_registration_schema()
    _require_panel_foreign_transport()
    _private_dir(TRUSTED_NODES_DIR)
    _regular(PANEL_SECURITY_OVERRIDE, mode=0o600, limit=32_000)
    mount = _run([
        "docker", "inspect", "-f",
        '{{range .Mounts}}{{if eq .Destination "/etc/smite-panel/trusted-nodes"}}{{.Source}}{{end}}{{end}}',
        "smite-panel",
    ], timeout=10, capture=True)
    if mount != str(TRUSTED_NODES_DIR):
        raise WizardHold("IR Panel approved Node directory is not mounted")
    if PANEL_DB.is_symlink() or not PANEL_DB.is_file():
        raise WizardHold("IR Panel pairing database unavailable")
    try:
        with sqlite3.connect(
            PANEL_DB.absolute().as_uri() + "?mode=ro", uri=True, timeout=3,
        ) as database:
            row = database.execute(
                "SELECT name,status,metadata FROM nodes WHERE id=?", (node_id,),
            ).fetchone()
        meta = json.loads(row[2]) if row else None
    except (sqlite3.Error, ValueError, TypeError) as exc:
        raise WizardHold("IR Panel reserved Node record invalid") from exc
    if (
        row is None or row[0] != node_name or row[1] != "pending"
        or not isinstance(meta, dict)
        or meta.get("role") != "foreign"
        or meta.get("node_name") != node_name
        or meta.get("provisioning") != "reserved_for_pairing"
    ):
        raise WizardHold("IR Panel must first reserve this exact foreign UUID/name")
    opener = request.build_opener(
        request.ProxyHandler({}),
        request.HTTPSHandler(context=ssl.create_default_context()),
        NoRedirect(),
    )
    try:
        with opener.open(approved_url + "/", timeout=12) as response:
            payload = json.loads(response.read(257))
            if response.status != 200 or payload != {
                "status": "ok", "service": "smite-node",
            }:
                raise WizardHold("KH HTTPS transport readiness not verified")
    except (error.HTTPError, error.URLError, ValueError, ssl.SSLError, TimeoutError) as exc:
        raise WizardHold("KH TLS gateway readiness not verified") from exc
    if not APPROVED_ORIGINS.is_file() or APPROVED_ORIGINS.is_symlink():
        raise WizardHold("IR trusted Node approval file missing")
    old = _regular(APPROVED_ORIGINS, mode=0o600, limit=64_000)
    try:
        record = json.loads(old)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise WizardHold("IR trusted Node records invalid") from exc
    if (
        not isinstance(record, dict) or set(record) != {"version", "nodes"}
        or record["version"] != 1 or not isinstance(record["nodes"], dict)
    ):
        raise WizardHold("IR trusted Node store schema mismatch")
    entries = record["nodes"]
    desired = {
        "role": "foreign", "node_name": node_name,
        "origin": origin, "control_url": approved_url,
    }
    if node_id in entries and entries[node_id] != desired:
        raise WizardHold("Existing foreign Node approval conflicts")
    for other, pin in entries.items():
        if other != node_id and not isinstance(pin, dict):
            raise WizardHold("Existing trusted Node record invalid")
        if other != node_id and (
            pin.get("node_name") == node_name or pin.get("origin") == origin
        ):
            raise WizardHold("Foreign name/origin already approved for other Node")
    if entries.get(node_id) == desired:
        print("FOREIGN_ORIGIN_APPROVAL=ALREADY_PINNED")
        return
    entries[node_id] = desired
    new = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(new) > 64_000:
        raise WizardHold("Approved Node store size exceeded")
    _atomic_write(APPROVED_ORIGINS, new, 0o600)
    try:
        program = r"""
import sys
from app.signed_node_origins import approved_node
p=approved_node(sys.argv[1])
assert p["role"] == "foreign"
assert p["node_name"] == sys.argv[2]
# Panel canonicalizes HTTPS/443 with an explicit :443 for BOTH fields.
# Compare against the exact approved normalized origin and path, not the
# original user-entered URL whose spelling may omit the default port.
assert p["origin"] == sys.argv[3]
assert p["control_url"] == sys.argv[4]
print("FOREIGN_PIN=VERIFIED")
"""
        canonical_control = origin + parse.urlsplit(approved_url).path
        if _run([
            "docker", "exec", "smite-panel", "python3", "-c",
            program, node_id, node_name, origin, canonical_control,
        ], capture=True, timeout=20) != "FOREIGN_PIN=VERIFIED":
            raise WizardHold("IR Panel did not accept foreign Node approval")
    except Exception as exc:
        try:
            if _regular(APPROVED_ORIGINS, mode=0o600, limit=64_000) != new:
                raise WizardHold("Concurrent trusted origin change detected")
            _atomic_write(APPROVED_ORIGINS, old, 0o600)
        except Exception as bad_rollback:
            raise WizardHold("CRITICAL: IR foreign approval rollback NOT verified") from bad_rollback
        raise WizardHold("IR foreign Node approval rejected and restored") from exc
    print("FOREIGN_ORIGIN_APPROVAL=PINNED_FIELD_TRIAL")
    print("PAIRING_CODE=NOT_CREATED")
    print("PANEL_RUNTIME=UNCHANGED")
    print("PRODUCTION_ACTIVATION=NO")


def _rc7_foreign_compose_command(
    *, staged_candidate: bool = False, rollback: bool = False,
    verify_active_candidate: bool = False,
) -> list[str]:
    """Preserve the existing RC7 Compose owner before and AFTER activation.

    The post-apply witness is read-only and never authorizes a new trial
    digest or alternative Compose project. An unexpected active file set
    must enter the existing failed-activation rollback.
    """
    if (type(staged_candidate) is not bool or type(rollback) is not bool
            or type(verify_active_candidate) is not bool
            or (verify_active_candidate and (staged_candidate or rollback))):
        raise WizardHold("Foreign RC7 Compose review selector invalid")
    project = _run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "com.docker.compose.project"}}', "smite-node"],
        timeout=15, capture=True,
    )
    if not re.fullmatch(r"uopti_rc6_[0-9a-f]{32}", project):
        raise WizardHold("Foreign RC7 Compose project is not the fresh transaction")
    ambient = os.environ.get("COMPOSE_PROJECT_NAME", "")
    if ambient and ambient != project:
        raise WizardHold("Foreign RC7 ambient Compose project conflicts")
    service = _run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "com.docker.compose.service"}}', "smite-node"],
        timeout=15, capture=True,
    )
    raw_files = _run(
        ["docker", "inspect", "-f",
         '{{index .Config.Labels "com.docker.compose.project.config_files"}}',
         "smite-node"],
        timeout=15, capture=True,
    )
    base, candidate = str(NODE_COMPOSE), str(NODE_SECURITY_CANDIDATE)
    active = raw_files.split(",")
    if service != "smite-node" or active not in ([base], [base, candidate]):
        raise WizardHold("Foreign RC7 active Compose files are not reviewed")
    if verify_active_candidate:
        if active != [base, candidate]:
            raise WizardHold("Foreign RC7 signed candidate Compose was not actually applied")
    elif not rollback and active != [base]:
        raise WizardHold("Foreign RC7 signed candidate is already active")
    if NODE_COMPOSE.is_symlink() or not NODE_COMPOSE.is_file():
        raise WizardHold("Foreign RC7 base Compose is unsafe or missing")
    command = ["docker", "compose", "--project-name", project, "-f", base]
    if staged_candidate or verify_active_candidate:
        _regular(NODE_SECURITY_CANDIDATE, mode=0o600, limit=128_000)
        command.extend(["-f", candidate])
    return command


def _foreign_gateway_preflight(
    current: dict[str, str], *, expected_image: str | None = None,
    allow_unattached_sanaei: bool = False,
    review_unified_trial: bool = False,
) -> tuple[str, str, str]:
    """Read-only managed Gateway metadata; unified trial never activates."""
    version = current.get("SMITE_MANAGED_VERSION")
    if current.get("SMITE_ROLE") != "foreign" or version not in ("2.0.0-rc.1", "2.0.0-rc.7"):
        raise WizardHold("Foreign activation requires an exact reviewed signed Node")
    if review_unified_trial:
        if (type(review_unified_trial) is not bool
                or version != "2.0.0-rc.7"
                or expected_image not in (None, _FOREIGN_NODE_IMAGE_UNIFIED_TRIAL)
                or allow_unattached_sanaei):
            raise WizardHold("Unified Foreign image review is exact RC7 read-only only")
        expected_image = _FOREIGN_NODE_IMAGE_UNIFIED_TRIAL
    elif version == "2.0.0-rc.7":
        if expected_image not in (None, _FOREIGN_NODE_IMAGE_RC7):
            raise WizardHold("RC7 cannot activate using an earlier Foreign image")
        expected_image = _FOREIGN_NODE_IMAGE_RC7
    elif expected_image is None:
        expected_image = _FOREIGN_NODE_IMAGE
    if expected_image not in (_FOREIGN_NODE_IMAGE, _FOREIGN_NODE_IMAGE_RC2,
                              _FOREIGN_NODE_IMAGE_RC7, _FOREIGN_NODE_IMAGE_UNIFIED_TRIAL):
        raise WizardHold("Foreign activation image not reviewed")
    if expected_image == _FOREIGN_NODE_IMAGE_UNIFIED_TRIAL and not review_unified_trial:
        raise WizardHold("Unified signed trial image not authorized for legacy activation")
    gateway = STATE.parent / "foreign-gateway.env"
    data = _env_map(_regular(gateway, mode=0o600, limit=8192))
    domain = data.get("SMITE_FOREIGN_GATEWAY_DOMAIN", "")
    panel = data.get("SMITE_FOREIGN_PANEL_DOMAIN", "")
    source_ip = data.get("SMITE_FOREIGN_PANEL_SOURCE_IPV4", "")
    path = data.get("SMITE_FOREIGN_CONTROL_PATH", "")
    if (
        not _DOMAIN.fullmatch(domain)
        or panel != current.get("SMITE_PANEL_DOMAIN")
        or not _FOREIGN_PATH.fullmatch(path)
        or data.get("SMITE_FOREIGN_GATEWAY_PUBLIC_PORT") != "443"
        or data.get("SMITE_FOREIGN_GATEWAY_MODE") != "https-control-path"
    ):
        raise WizardHold("Foreign HTTPS/443 gateway state is missing or unreviewed")
    try:
        import ipaddress
        if ipaddress.ip_address(source_ip).version != 4:
            raise ValueError()
    except ValueError as exc:
        raise WizardHold("Foreign Panel IPv4 allow-list is invalid") from exc
    env = _env_map(_regular(NODE_DIR / ".env", mode=0o600, limit=64_000))
    # Exact Panel-issued smi1 scope explicitly pins HTTPS/443. Admit
    # that spelling ONLY for signed trial read-only review; official RC7
    # activation/rollback keeps the established Gateway URL contract.
    url = (f"https://{domain}:443{path}" if review_unified_trial
           else f"https://{domain}{path}")
    if (
        env.get("SMITE_NODE_PANEL_AUTH_MODE") != "paused"
        or env.get("SMITE_AGENT_AUTH_MODE") != "strict"
        or env.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
        or env.get("PANEL_ADDRESS") != panel + ":443"
        or env.get("SMITE_CONTROL_ADDRESS") != url
    ):
        raise WizardHold("Foreign Node paused/strict control metadata has changed")
    _regular(NODE_COMPOSE, limit=256_000)
    running = _run(
        ["docker", "inspect", "-f", "{{.Config.Image}}", "smite-node"],
        capture=True, timeout=10,
    )
    if running == "smite-node:stage15-local" and expected_image == _FOREIGN_NODE_IMAGE:
        # The ordinary wizard supports this exact proven Clean-RC pair.
        # The separately frozen RC.2 lane must never accept local substitutes.
        _require_stage15_identity("node")
        _require_stage15_foreign_compose(url, panel)
    elif running != expected_image:
        raise WizardHold("Foreign Node image differs from the exact approved digest")
    if expected_image in (_FOREIGN_NODE_IMAGE_RC7, _FOREIGN_NODE_IMAGE_UNIFIED_TRIAL):
        base_command = _rc7_foreign_compose_command()
        raw = _run(base_command + ["config", "--format", "json"], timeout=30, capture=True)
        try:
            service = json.loads(raw)["services"]["smite-node"]
            environment = service["environment"]
            command = service["command"]
            volumes = service.get("volumes", [])
            sanaei_mounts = [
                v for v in volumes if isinstance(v, dict)
                and v.get("target") == "/run/smite-sanaei-ro"
            ]
            if allow_unattached_sanaei:
                # Narrow recovery from the operator's verified staging-order
                # mistake. The identity is already stored but never mounted;
                # strict/paused runtime must still point at the empty RO mount.
                expected_sanaei = "false"
                expected_mount = str(NODE_DIR / ".sanaei-empty")
            else:
                expected_sanaei = "true"
                expected_mount = "/opt/3x-ui/instances/01/db"
            valid_sanaei = (
                len(sanaei_mounts) == 1
                and sanaei_mounts[0].get("source") == expected_mount
                and sanaei_mounts[0].get("read_only") is True
                and environment.get("SMITE_SANAEI_INVENTORY_ENABLED") == expected_sanaei
            )
            if (
                service.get("image") != expected_image
                or service.get("network_mode") != "host"
                or service.get("ports") or service.get("privileged")
                # Exact immutable RC7 upstream Compose baseline. These
                # capabilities and the single TUN device already exist in
                # the installed Node; accepting them does not add privileges.
                # Reject any different/extra capability or host device.
                or service.get("cap_add") not in (
                    ["NET_ADMIN", "SYS_MODULE"],
                    ["SYS_MODULE", "NET_ADMIN"],
                )
                or service.get("devices") not in (
                    ["/dev/net/tun:/dev/net/tun"],
                    ["/dev/net/tun:/dev/net/tun:rwm"],
                    [{"source": "/dev/net/tun", "target": "/dev/net/tun", "permissions": "rwm"}],
                )
                or not isinstance(command, list)
                or command[:6] != ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8888"]
                or environment.get("SMITE_NODE_PANEL_AUTH_MODE") != "paused"
                or environment.get("SMITE_AGENT_AUTH_MODE") != "strict"
                or environment.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
                or environment.get("PANEL_ADDRESS") != panel + ":443"
                or environment.get("SMITE_CONTROL_ADDRESS") != url
                or environment.get("NODE_ROLE") != "foreign"
                or not valid_sanaei
            ):
                raise WizardHold("RC7 Foreign effective Compose security has drifted")
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise WizardHold("RC7 Foreign effective Compose invalid") from exc
        if _run(["docker", "inspect", "-f", "{{.State.Health.Status}}",
                 "smite-node"], timeout=10, capture=True) != "healthy":
            raise WizardHold("RC7 Foreign Node is not healthy")
    if expected_image == _FOREIGN_NODE_IMAGE_RC2:
        # Refuse a one-line image pin swap unless *all* paused/strict managed
        # effective Compose settings stay identical to reviewed RC.2 baseline.
        original = _regular(NODE_COMPOSE, limit=256_000)
        if hashlib.sha256(original).hexdigest() != _FOREIGN_RC2_COMPOSE_SHA:
            raise WizardHold("Foreign RC.2 Compose SHA256 differs from reviewed trial")
        raw = _run([
            "docker", "compose", "-f", str(NODE_COMPOSE),
            "config", "--format", "json",
        ], capture=True, timeout=30)
        try:
            service = json.loads(raw)["services"]["smite-node"]
            if (
                service.get("image") != _FOREIGN_NODE_IMAGE_RC2
                or service.get("network_mode") != "host"
                or service.get("environment", {}).get("SMITE_NODE_PANEL_AUTH_MODE") != "paused"
                or service["environment"].get("SMITE_AGENT_AUTH_MODE") != "strict"
                or service["environment"].get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
            ):
                raise WizardHold("Foreign RC.2 effective Compose security has drifted")
        except (KeyError, ValueError, TypeError) as exc:
            raise WizardHold("Foreign RC.2 effective Compose invalid") from exc
        if _run([
            "docker", "inspect", "-f", "{{.State.Health.Status}}", "smite-node",
        ], capture=True, timeout=10) != "healthy":
            raise WizardHold("Foreign RC.2 Node is not healthy")
    # Read-only TLS check uses existing Nginx gateway, not WAN:8888.
    response = _run([
        "curl", "--noproxy", "*", "-4", "-fSs",
        "--max-time", "12", "--resolve", f"{domain}:443:127.0.0.1",
        url + "/",
    ], capture=True, timeout=18)
    try:
        payload = json.loads(response)
    except (ValueError, TypeError) as exc:
        raise WizardHold("Foreign control HTTPS readiness is not JSON") from exc
    if payload != {"status": "ok", "service": "smite-node"}:
        raise WizardHold("Foreign control HTTPS readiness is not approved")
    return panel, domain, url


def staged_foreign_sanaei_admission(
    current: dict[str, str] | None = None, *, verify_attached: bool = False,
) -> None:
    """RC7 KH only: read-only staged-identity gate; never replace a key.

    This is deliberately NOT an alternative pairing/redemption/activation
    path. It only audits the exact paused/strict base Compose before the
    existing Sanaei read-only mount helper may recreate a paused Node.
    """
    _field_trial_gate()
    state = state_values() if current is None else current
    if (state.get("SMITE_ROLE") != "foreign"
            or state.get("SMITE_CONNECTION_MODE") != "standard"
            or state.get("SMITE_MANAGED_VERSION") != "2.0.0-rc.7"):
        raise WizardHold("Staged Sanaei recovery requires the reviewed RC7 Foreign role")
    _identity_record()  # Validate owner, mode, private directory and secret, never print it.
    _require_no_active_engine_overlays()
    for artifact in (
        NODE_SECURITY_CANDIDATE,
        REPLAY_DB,
        IDENTITY_DIR / "replay-enrollment.json",
    ):
        if artifact.exists() or artifact.is_symlink():
            raise WizardHold("Staged Sanaei recovery refuses signed/replay runtime artifacts")
    _foreign_gateway_preflight(
        state, allow_unattached_sanaei=not verify_attached,
    )
    runtime = _run([
        "docker", "inspect", "-f",
        "{{range .Config.Env}}{{println .}}{{end}}", "smite-node",
    ], timeout=10, capture=True).splitlines()
    for value in (
        "SMITE_NODE_PANEL_AUTH_MODE=paused",
        "SMITE_AGENT_AUTH_MODE=strict",
        "SMITE_ENGINE_INVENTORY_MODE=managed",
    ):
        if value not in runtime:
            raise WizardHold("Staged Sanaei recovery requires paused/strict managed runtime")
    print("KH_SANAEI_STAGED_IDENTITY=" +
          ("READY_READ_ONLY" if verify_attached else "ADMISSION_PASS_READ_ONLY"))
    print("PAIRING_IDENTITY=PRESERVED")
    print("NODE_RUNTIME=PAUSED_STRICT")


def _rc7_foreign_pinned_image_verified(
    *, review_unified_trial: bool = False,
) -> None:
    """Existing immutable image witness; trial selection is read-only only."""
    if type(review_unified_trial) is not bool:
        raise WizardHold("Foreign signed image review selector invalid")
    expected = (_FOREIGN_NODE_IMAGE_UNIFIED_TRIAL if review_unified_trial
                else _FOREIGN_NODE_IMAGE_RC7)
    lane = "unified trial" if review_unified_trial else "RC7"
    image = _run(
        ["docker", "inspect", "-f", "{{.Config.Image}}", "smite-node"],
        timeout=10, capture=True,
    )
    if image != expected:
        raise WizardHold(f"Foreign {lane} running image is not the published signed digest")
    actual = _run(
        ["docker", "inspect", "-f", "{{.Image}}", "smite-node"],
        timeout=10, capture=True,
    )
    pinned = _run(
        ["docker", "image", "inspect", "-f", "{{.Id}}", expected],
        timeout=10, capture=True,
    )
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", actual) or actual != pinned:
        raise WizardHold(f"Foreign {lane} effective image ID differs from pinned image")


def _rc7_foreign_paused_rollback_verified(
    *, expected_identity: tuple[str, str] | None = None,
    require_replay: bool = False,
    review_unified_trial: bool = False,
) -> None:
    """Verify existing paused/identity/replay contract, including inert trial."""
    if type(review_unified_trial) is not bool:
        raise WizardHold("Foreign paused review selector invalid")
    if review_unified_trial:
        _rc7_foreign_pinned_image_verified(review_unified_trial=True)
    else:
        # Official RC7 runtime activation/rollback retains its pinned default.
        _rc7_foreign_pinned_image_verified()
    environment = _run(
        ["docker", "inspect", "-f",
         "{{range .Config.Env}}{{println .}}{{end}}", "smite-node"],
        timeout=10, capture=True,
    ).splitlines()
    for key, value in (
        ("SMITE_NODE_PANEL_AUTH_MODE", "paused"),
        ("SMITE_AGENT_AUTH_MODE", "strict"),
        ("SMITE_ENGINE_INVENTORY_MODE", "managed"),
    ):
        matched = [line for line in environment if line.startswith(key + "=")]
        if matched != [key + "=" + value]:
            raise WizardHold("Foreign RC7 rollback effective auth is not paused+strict+managed")
    if expected_identity is not None and _identity_record() != expected_identity:
        raise WizardHold("Foreign RC7 rollback paired identity changed")
    if require_replay and not _replay_artifacts_valid():
        raise WizardHold("Foreign RC7 rollback replay identity is not retained")


def _require_unified_foreign_release() -> None:
    """Reuse the existing exact signed Panel/Node trial-pair verifier.

    This is a FAIL-CLOSED release boundary. The pinned trial manifest
    explicitly says activation_allowed=false; no runtime write follows
    until a separately reviewed signed release permits host activation.
    """
    import importlib.util
    module_path = Path(__file__).with_name("smite-unified-trial-pair-admission.py")
    manifest = Path(__file__).with_name("smite-unified-trial-registry-pair.json")
    trust = Path(__file__).with_name("smite-rc7-sigstore-trusted-root.json")
    if any(path.is_symlink() or not path.is_file()
           for path in (module_path, manifest, trust)):
        raise WizardHold("Unified signed release verification inputs unavailable")
    spec = importlib.util.spec_from_file_location(
        "uopti_existing_unified_pair_admission", module_path)
    if spec is None or spec.loader is None:
        raise WizardHold("Unified signed pair verifier unavailable")
    signed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signed)
    try:
        approved = signed.verify(
            manifest=manifest,
            manifest_sha256="61149003bbf966445bb25d0f94a4e666bb57b4544a5565703af55b30afa41c84",
            source_sha="de0677d015a00160970ed57bba565adc4fafe8eb",
            trusted_root=trust)
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            signed.Hold) as exc:
        raise WizardHold("Unified signed pair release verification failed") from exc
    if (approved.get("status") != "verified_trial_pair"
            or approved.get("node") != _FOREIGN_NODE_IMAGE_UNIFIED_TRIAL
            or approved.get("panel") !=
              "ghcr.io/aghajani82/smite-panel@sha256:a4142110b058b02a5325e8f2130f2faa5daa5fc0aa3faad82bb4389948d4385f"
            or approved.get("host_activation_allowed") is not True):
        raise WizardHold("Unified signed pair NOT released for host activation")


def activate_foreign_node_field_trial(
    state: dict[str, str] | None = None, *, reviewed_rc2: bool = False,
    reviewed_unified_trial: bool = False,
) -> None:
    """KH only; require IR approval + updated signed Panel image BEFORE use.

    Never self-approve a Panel trusted origin from KH and never enable an
    unsigned fallback. A failed signed check-in returns Node to paused mode.
    Identity and Replay history are retained for operator reconciliation.
    """
    if (type(reviewed_rc2) is not bool or type(reviewed_unified_trial) is not bool
            or (reviewed_rc2 and reviewed_unified_trial)):
        raise WizardHold("Foreign signed image selector invalid")
    _field_trial_gate()
    if reviewed_unified_trial:
        _require_unified_foreign_release()
    _require_no_active_engine_overlays()
    current = state_values() if state is None else state
    if reviewed_rc2:
        # In addition to the frozen exact image, every independently reviewed
        # RC.2 safety check must still pass before *any* pairing mutation.
        if os.environ.get("UOPTI_SMITE_RC2_FOREIGN_PAIRING_FIELD_TRIAL") != "YES":
            raise WizardHold("Explicit RC.2 foreign activation consent missing")
        gate = Path(__file__).with_name("smite-rc2-foreign-pairing-admission.py")
        if not gate.is_file() or gate.is_symlink():
            raise WizardHold("RC.2 foreign read-only admission module unavailable")
        _regular(gate, limit=128_000)
        if _run([
            "python3", "-B", str(gate), "--role", "KH",
        ], capture=True, timeout=90).splitlines()[-3:] != [
            "RC2_FOREIGN_PAIRING_ADMISSION=PASS_READ_ONLY",
            "FOREIGN_PAIRING=NOT_ACTIVATED",
            "LIVE_CHANGES=NONE",
        ]:
            raise WizardHold("RC.2 foreign read-only admission failed")
        panel, _domain, control_url = _foreign_gateway_preflight(
            current, expected_image=_FOREIGN_NODE_IMAGE_RC2,
        )
    elif reviewed_unified_trial:
        panel, _domain, control_url = _foreign_gateway_preflight(
            current, review_unified_trial=True)
    else:
        panel, _domain, control_url = _foreign_gateway_preflight(current)
    rc7 = current.get("SMITE_MANAGED_VERSION") == "2.0.0-rc.7"
    if reviewed_unified_trial and not rc7:
        raise WizardHold("Unified signed pair requires exact RC7 Foreign baseline")
    if rc7:
        _rc7_foreign_compose_command()
        # The trial selector cannot silently adopt the old official RC7 image.
        if reviewed_unified_trial:
            _rc7_foreign_pinned_image_verified(review_unified_trial=True)
        else:
            _rc7_foreign_pinned_image_verified()
    node_id, node_secret = _identity_record()
    retained_identity = (node_id, node_secret)
    helper = Path(__file__).with_name("smite-foreign-gateway-signed-check.py")
    if not helper.is_file() or helper.is_symlink():
        raise WizardHold("Reviewed signed Gateway check helper is unavailable")
    _regular(helper, limit=128_000)
    node_name = current.get("SMITE_NODE_NAME", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", node_name):
        raise WizardHold("Foreign Node name is not approved")

    # Stage and validate all independent local inputs before runtime changes.
    _prepare_security_candidate()
    _provision_replay_once()
    candidate_command = (
        _rc7_foreign_compose_command(staged_candidate=True) if rc7
        else ["docker", "compose", "-f", str(NODE_COMPOSE),
              "-f", str(NODE_SECURITY_CANDIDATE)]
    )
    _run(candidate_command + ["config", "--quiet"], timeout=30)

    recreated = False
    try:
        # Even a failed compose command may have recreated the container.
        recreated = True
        _run(candidate_command + [
            "up", "-d", "--no-build", "--no-deps", "--pull", "never",
            "--force-recreate", "smite-node",
        ], timeout=120)
        _wait_container("smite-node", 90)
        if rc7:
            # A successful compose up is insufficient: inspect the actual
            # live container labels, local pinned image and candidate file
            # AFTER it is recreated and BEFORE any signed proof is claimed.
            _rc7_foreign_compose_command(verify_active_candidate=True)
            if reviewed_unified_trial:
                _rc7_foreign_pinned_image_verified(review_unified_trial=True)
            else:
                _rc7_foreign_pinned_image_verified()
        effective = _run([
            "docker", "inspect", "-f",
            "{{range .Config.Env}}{{println .}}{{end}}", "smite-node",
        ], timeout=10, capture=True).splitlines()
        if (
            "SMITE_NODE_PANEL_AUTH_MODE=signed" not in effective
            or "SMITE_AGENT_AUTH_MODE=strict" not in effective
            or "SMITE_ENGINE_INVENTORY_MODE=managed" not in effective
        ):
            raise WizardHold("Foreign Node signed runtime did not apply")
        _local_signed_replay_probe()

        # The Panel replies READY only after signed KH check-in AND an
        # authenticated Panel -> KH agent status. No anonymous enumeration.
        verified = False
        for attempt in range(8):
            try:
                _run([
                    "python3", "-B", str(helper),
                    "--panel-domain", panel,
                    "--node-name", node_name,
                    "--control-url", control_url,
                ], timeout=25)
                verified = True
                break
            except WizardHold:
                if attempt < 7:
                    time.sleep(4)
        if not verified:
            raise WizardHold("Foreign signed dual-direction verification incomplete")
        # Keep evidence of the SAME pinned signed candidate at completion.
        # A changed Compose label/image after the Panel probe is a failure,
        # not a successful Connected report.
        if rc7:
            _rc7_foreign_compose_command(verify_active_candidate=True)
            if reviewed_unified_trial:
                _rc7_foreign_pinned_image_verified(review_unified_trial=True)
            else:
                _rc7_foreign_pinned_image_verified()
        # A Connected result must not hide an identity rotation or lost
        # replay binding. Reuse the existing owner-only identity/replay checks.
        if _identity_record() != retained_identity or not _replay_artifacts_valid():
            raise WizardHold("Foreign signed proof did not retain identity and replay")
    except Exception as exc:
        rollback_ok = not recreated
        if recreated:
            try:
                rollback_command = (
                    _rc7_foreign_compose_command(rollback=True) if rc7
                    else ["docker", "compose", "-f", str(NODE_COMPOSE)]
                )
                _run(rollback_command + [
                    "up", "-d", "--no-build", "--no-deps", "--pull", "never",
                    "--force-recreate", "smite-node",
                ], timeout=120)
                _wait_container("smite-node", 90)
                effective = _run([
                    "docker", "inspect", "-f",
                    "{{range .Config.Env}}{{println .}}{{end}}", "smite-node",
                ], timeout=10, capture=True).splitlines()
                rollback_ok = (
                    "SMITE_NODE_PANEL_AUTH_MODE=paused" in effective
                    and "SMITE_AGENT_AUTH_MODE=strict" in effective
                )
                if rollback_ok and rc7:
                    if reviewed_unified_trial:
                        _rc7_foreign_paused_rollback_verified(
                            expected_identity=retained_identity,
                            require_replay=True, review_unified_trial=True)
                    else:
                        _rc7_foreign_paused_rollback_verified(
                            expected_identity=retained_identity,
                            require_replay=True)
                    # Verify the *observed* post-recreate Compose owner now
                    # has ONLY the original base file. A pre-rollback
                    # command is not proof that Docker applied that file.
                    _rc7_foreign_compose_command()
            except Exception:
                rollback_ok = False
        if not rollback_ok:
            raise WizardHold(
                "CRITICAL: Foreign signed activation failed; paused rollback "
                "NOT verified. Stop and inspect Node manually."
            ) from exc
        raise WizardHold(
            "Foreign signed verification failed; Node paused again. "
            "Identity and Replay retained for reconciliation."
        ) from exc

    print("KH_SIGNED_NODE_RUNTIME=ACTIVE_FIELD_TRIAL")
    print("KH_LOCAL_HMAC_REPLAY=PASS")
    print("KH_TO_PANEL_SIGNED_CHECKIN_AND_GATEWAY=PASS")
    print("PANEL_TO_KH_SIGNED_HMAC=PASS")
    print("LEGACY_AUTH_FALLBACK=NO")
    print("PRODUCTION_ACTIVATION=NO")


def rollback_node_to_paused_field_trial(
    state: dict[str, str] | None = None, *, reviewed_unified_trial: bool = False,
) -> None:
    if type(reviewed_unified_trial) is not bool:
        raise WizardHold("Foreign rollback image selector invalid")
    _field_trial_gate()
    if reviewed_unified_trial:
        _require_unified_foreign_release()
    _require_no_active_engine_overlays()
    current = state_values() if state is None else state
    if current.get("SMITE_CONNECTION_MODE") != "standard":
        raise WizardHold("Signed rollback is Standard mode only")
    _regular(NODE_COMPOSE, limit=256_000)
    rc7_foreign = (
        current.get("SMITE_ROLE") == "foreign"
        and current.get("SMITE_MANAGED_VERSION") == "2.0.0-rc.7"
    )
    if reviewed_unified_trial and not rc7_foreign:
        raise WizardHold("Unified rollback requires exact RC7 Foreign baseline")
    if rc7_foreign:
        if reviewed_unified_trial:
            _rc7_foreign_pinned_image_verified(review_unified_trial=True)
        else:
            _rc7_foreign_pinned_image_verified()
    # Capture original identity/replay before any possible recreation.
    # A missing identity is allowed for an unpaired recovery; an existing,
    # unsafe or partially provisioned identity must never be overwritten.
    retained_identity = None
    retained_replay = False
    if rc7_foreign and (IDENTITY_FILE.exists() or IDENTITY_FILE.is_symlink()):
        retained_identity = _identity_record()
        retained_replay = _replay_artifacts_valid()
    command = (
        _rc7_foreign_compose_command(rollback=True)
        if rc7_foreign
        else ["docker", "compose", "-f", str(NODE_COMPOSE)]
    )
    _run(command + [
        "up", "-d", "--no-build", "--force-recreate", "smite-node",
    ], timeout=120)
    _wait_container("smite-node", 90)
    env = _run(
        ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", "smite-node"],
        timeout=10, capture=True,
    ).splitlines()
    if "SMITE_NODE_PANEL_AUTH_MODE=paused" not in env or "SMITE_AGENT_AUTH_MODE=strict" not in env:
        raise WizardHold("Node did not return to paused+strict state")
    if rc7_foreign:
        if reviewed_unified_trial:
            _rc7_foreign_paused_rollback_verified(
                expected_identity=retained_identity,
                require_replay=retained_replay,
                review_unified_trial=True)
        else:
            _rc7_foreign_paused_rollback_verified(
                expected_identity=retained_identity,
                require_replay=retained_replay)
        # This is a separate read-only *after* witness, not the prior
        # command selection. Never claim safe rollback while the failed
        # signed candidate/foreign Compose files remain active.
        _rc7_foreign_compose_command()
    print("NODE_RUNTIME=PAUSED_STRICT")
    print("PAIRING_IDENTITY=PRESERVED")
    print("REPLAY_HISTORY=PRESERVED")
    print("LEGACY_AUTH_FALLBACK=NO")


def _determine_role(state: dict[str, str]) -> str:
    return "iran" if state.get("SMITE_ROLE") in ("iran", "panel-iran") else "foreign"


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--prepare-store", action="store_true")
    actions.add_argument("--enable-panel-field-trial", action="store_true")
    actions.add_argument("--complete-local-ir-install", action="store_true")
    actions.add_argument("--redeem-field-trial", action="store_true")
    # Backward-compatible name for older inert callers; live use still requires
    # the new explicit Field Trial gate and confirmation.
    actions.add_argument("--redeem-preview", action="store_true")
    actions.add_argument("--activate-ir-node-field-trial", action="store_true")
    actions.add_argument("--activate-foreign-node-field-trial", action="store_true")
    actions.add_argument("--admit-staged-foreign-sanaei", action="store_true")
    actions.add_argument("--verify-staged-foreign-sanaei", action="store_true")
    # Separate explicit RC.2 lane; never switch the existing RC.1 wizard silently.
    actions.add_argument("--activate-foreign-node-rc2-field-trial", action="store_true")
    actions.add_argument("--approve-foreign-origin-field-trial", action="store_true")
    actions.add_argument("--rollback-node-field-trial", action="store_true")
    parser.add_argument("--state-path", type=Path, default=STATE)
    args = parser.parse_args(argv)
    try:
        state = state_values(args.state_path)
        role = _determine_role(state)
        domain = state.get("SMITE_PANEL_DOMAIN", "")
        secure_endpoint("https://" + domain)
        print(f"ROLE={role} MODE=standard PANEL=https://{domain}:443")

        if args.admit_staged_foreign_sanaei or args.verify_staged_foreign_sanaei:
            staged_foreign_sanaei_admission(
                state, verify_attached=args.verify_staged_foreign_sanaei,
            )
            return 0

        if args.status:
            identity = IDENTITY_FILE
            panel_enabled = False
            if PANEL_ENV.is_file() and not PANEL_ENV.is_symlink():
                try:
                    values = _env_map(_regular(PANEL_ENV, mode=0o600, limit=64_000))
                    panel_enabled = values.get("SMITE_NODE_PAIRING_PREVIEW_ENABLED") == "true"
                except WizardHold:
                    panel_enabled = False
            print("PANEL_PAIRING=" + ("ENABLED" if panel_enabled else "NOT_ENABLED"))
            print("CREDENTIALS=" + ("STAGED" if identity.is_file() else "NOT_STAGED"))
            replay = "READY" if identity.is_file() and _replay_artifacts_valid() else "NOT_PROVISIONED"
            print("REPLAY_ENROLLMENT=" + replay)
            return 0

        if args.prepare_store:
            prepare_store()
            print("IDENTITY_STORE=READY MODE=0700; no containers changed")
            return 0

        if args.enable_panel_field_trial:
            enable_panel_field_trial(state)
            return 0

        if args.complete_local_ir_install:
            complete_local_ir_install(state)
            return 0

        if args.activate_ir_node_field_trial:
            activate_ir_node_field_trial(state)
            return 0

        if args.activate_foreign_node_field_trial:
            activate_foreign_node_field_trial(state)
            return 0
        if args.activate_foreign_node_rc2_field_trial:
            activate_foreign_node_field_trial(state, reviewed_rc2=True)
            return 0

        if args.approve_foreign_origin_field_trial:
            _field_trial_gate()
            if state.get("SMITE_ROLE") != "panel-iran" or not sys.stdin.isatty():
                raise WizardHold("Interactive IR Panel required for foreign approval")
            print("FIELD TRIAL: approve one reserved KH origin on IR.")
            confirm = input("Type APPROVE-KH-CONTROL to proceed: ").strip()
            if confirm != "APPROVE-KH-CONTROL":
                raise WizardHold("Cancelled; no changes")
            node_id = input("Admin-reserved foreign Node UUID: ").strip()
            node_name = input("Reserved foreign Node name: ").strip()
            url = input("Approved KH HTTPS/443 control URL: ").strip()
            approve_foreign_origin_field_trial(
                node_id=node_id, node_name=node_name, control_url=url, state=state,
            )
            return 0

        if args.rollback_node_field_trial:
            rollback_node_to_paused_field_trial(state)
            return 0

        # Pairing-code redemption remains an interactive secret entry.
        _field_trial_gate()
        if not sys.stdin.isatty():
            raise WizardHold("Interactive terminal required for one-time pairing code")
        print("FIELD TRIAL: one-time HTTPS/443 pairing credential redemption.")
        confirm = input("Type PAIR-SIGNED-NODE to proceed: ").strip()
        if confirm != "PAIR-SIGNED-NODE":
            raise WizardHold("Cancelled, no changes")
        prepare_store()
        if IDENTITY_FILE.exists() or IDENTITY_FILE.is_symlink():
            raise WizardHold("Identity already staged; never overwrite automatically")
        node_id = input("Admin-approved Node UUID: ").strip()
        code = getpass.getpass("One-time pairing code (hidden): ")
        redeem(
            panel_url="https://" + domain, pairing_code=code,
            node_id=node_id, role=role,
        )
        print("PAIRING_CREDENTIAL=STAGED_FOR_SIGNED_ACTIVATION")
        print("NODE_RUNTIME=STILL_PAUSED")
        return 0
    except WizardHold as exc:
        print(f"HOLD: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
