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
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WizardHold("Required host operation failed") from exc
    if completed.returncode != 0:
        raise WizardHold("Required host operation was rejected")
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


def _panel_compose_command() -> list[str]:
    command = ["docker", "compose", "-f", str(PANEL_COMPOSE)]
    if PANEL_SECURITY_OVERRIDE.is_file() and not PANEL_SECURITY_OVERRIDE.is_symlink():
        command += ["-f", str(PANEL_SECURITY_OVERRIDE)]
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
    if not re.fullmatch(r"ghcr\.io/aghajani82/smite-node@sha256:[a-f0-9]{64}", image):
        raise WizardHold("Active Node is not an immutable signed Field Trial image")
    output = _run(
        [
            "docker", "run", "--rm", "--network", "none",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--mount", f"type=bind,source={IDENTITY_DIR},target=/run/smite-node-identity",
            "--mount", f"type=bind,source={REPLAY_DIR},target=/var/lib/smite-node/auth",
            "--entrypoint", "python3", image,
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
    override = (
        "services:\n"
        "  smite-panel:\n"
        "    volumes:\n"
        f"      - {TRUSTED_NODES_DIR}:/etc/smite-panel/trusted-nodes:ro\n"
    ).encode("utf-8")
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


def _restart_panel_with_signed_control() -> None:
    command = _panel_compose_command()
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


def activate_ir_node_field_trial(state: dict[str, str] | None = None) -> None:
    _field_trial_gate()
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

    # Fail before any Panel/Node recreate if option 2 did not complete
    # both signed-registration migrations.
    _require_panel_signed_registration_schema()

    origin_before = override_before = panel_env_before = None
    node_was_applied = False
    try:
        origin_before, override_before, panel_env_before = _panel_override_and_origin(
            node_id, node_name
        )
        _restart_panel_with_signed_control()

        _prepare_security_candidate()
        _provision_replay_once()
        _run(
            ["docker", "compose", "-f", str(NODE_COMPOSE),
             "-f", str(NODE_SECURITY_CANDIDATE), "config", "--quiet"],
            timeout=30,
        )
        _run(
            ["docker", "compose", "-f", str(NODE_COMPOSE),
             "-f", str(NODE_SECURITY_CANDIDATE),
             "up", "-d", "--no-build", "--force-recreate", "smite-node"],
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
        if node_was_applied:
            try:
                _run(
                    ["docker", "compose", "-f", str(NODE_COMPOSE),
                     "up", "-d", "--no-build", "--force-recreate", "smite-node"],
                    timeout=120,
                )
                _wait_container("smite-node", 90)
            except Exception:
                pass
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
            except Exception:
                pass
        if isinstance(exc, WizardHold):
            raise
        raise WizardHold("Signed IR Node activation failed; paused rollback was attempted") from exc

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


def _require_panel_foreign_transport() -> None:
    """Refuse IR approval until a new signed Panel image understands KH prefix."""
    image = _run(
        ["docker", "inspect", "-f", "{{.Config.Image}}", "smite-panel"],
        timeout=10, capture=True,
    )
    if image != _FOREIGN_PANEL_IMAGE_RC2:
        raise WizardHold("Panel must run the exact reviewed signed RC.2 image")
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
    if current.get("SMITE_ROLE") != "panel-iran" or current.get("SMITE_MANAGED_VERSION") != "2.0.0-rc.1":
        raise WizardHold("Only clean RC.1 IR Panel may approve a foreign origin")
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
assert p["control_url"] == sys.argv[3]
print("FOREIGN_PIN=VERIFIED")
"""
        if _run([
            "docker", "exec", "smite-panel", "python3", "-c",
            program, node_id, node_name, approved_url,
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


def _foreign_gateway_preflight(
    current: dict[str, str], *, expected_image: str = _FOREIGN_NODE_IMAGE,
) -> tuple[str, str, str]:
    """Read only managed Gateway metadata; RC.2 requires additional admission."""
    if expected_image not in (_FOREIGN_NODE_IMAGE, _FOREIGN_NODE_IMAGE_RC2):
        raise WizardHold("Foreign activation target is not a reviewed signed image")
    if current.get("SMITE_ROLE") != "foreign" or current.get("SMITE_MANAGED_VERSION") != "2.0.0-rc.1":
        raise WizardHold("Foreign activation requires the reviewed clean RC.1 Node")
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
    url = f"https://{domain}{path}"
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
    if running != expected_image:
        raise WizardHold("Foreign Node image differs from the exact approved digest")
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


def activate_foreign_node_field_trial(
    state: dict[str, str] | None = None, *, reviewed_rc2: bool = False,
) -> None:
    """KH only; require IR approval + updated signed Panel image BEFORE use.

    Never self-approve a Panel trusted origin from KH and never enable an
    unsigned fallback. A failed signed check-in returns Node to paused mode.
    Identity and Replay history are retained for operator reconciliation.
    """
    _field_trial_gate()
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
    else:
        panel, _domain, control_url = _foreign_gateway_preflight(current)
    node_id, _ = _identity_record()
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
    _run([
        "docker", "compose", "-f", str(NODE_COMPOSE),
        "-f", str(NODE_SECURITY_CANDIDATE), "config", "--quiet",
    ], timeout=30)

    recreated = False
    try:
        # Even a failed compose command may have recreated the container.
        recreated = True
        _run([
            "docker", "compose", "-f", str(NODE_COMPOSE),
            "-f", str(NODE_SECURITY_CANDIDATE),
            "up", "-d", "--no-build", "--no-deps", "--pull", "never",
            "--force-recreate", "smite-node",
        ], timeout=120)
        _wait_container("smite-node", 90)
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
    except Exception as exc:
        rollback_ok = not recreated
        if recreated:
            try:
                _run([
                    "docker", "compose", "-f", str(NODE_COMPOSE),
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


def rollback_node_to_paused_field_trial(state: dict[str, str] | None = None) -> None:
    _field_trial_gate()
    current = state_values() if state is None else state
    if current.get("SMITE_CONNECTION_MODE") != "standard":
        raise WizardHold("Signed rollback is Standard mode only")
    _regular(NODE_COMPOSE, limit=256_000)
    _run(
        ["docker", "compose", "-f", str(NODE_COMPOSE),
         "up", "-d", "--no-build", "--force-recreate", "smite-node"],
        timeout=120,
    )
    _wait_container("smite-node", 90)
    env = _run(
        ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", "smite-node"],
        timeout=10, capture=True,
    ).splitlines()
    if "SMITE_NODE_PANEL_AUTH_MODE=paused" not in env or "SMITE_AGENT_AUTH_MODE=strict" not in env:
        raise WizardHold("Node did not return to paused+strict state")
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
    actions.add_argument("--redeem-field-trial", action="store_true")
    # Backward-compatible name for older inert callers; live use still requires
    # the new explicit Field Trial gate and confirmation.
    actions.add_argument("--redeem-preview", action="store_true")
    actions.add_argument("--activate-ir-node-field-trial", action="store_true")
    actions.add_argument("--activate-foreign-node-field-trial", action="store_true")
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
