#!/usr/bin/env python3
"""Smite U-OPTI node pairing preparation and opt-in credential-only wizard.

Standard/443 only. NEVER changes running containers, legacy registration,
Panel JWT, Nginx or FRP/Backhaul settings. Pairing credentials are staged,
not yet mounted or used by Smite Node; this is not an authentication rollout.

Only --redeem touches HTTPS, and it requires two explicit operator gates.
Pairing code is entered via getpass (never command-line arguments or logs).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import ssl
import stat
import sys
from urllib import error, parse, request


STATE = Path("/etc/u-opti/smite/state.env")
IDENTITY_DIR = Path("/etc/u-opti/smite/identities")
IDENTITY_FILE = IDENTITY_DIR / "node-identity.json"
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
        if k in ("SMITE_ROLE", "SMITE_CONNECTION_MODE", "SMITE_PANEL_DOMAIN", "SMITE_NODE_NAME"):
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


def _determine_role(state: dict[str, str]) -> str:
    return "iran" if state.get("SMITE_ROLE") in ("iran", "panel-iran") else "foreign"


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--prepare-store", action="store_true")
    actions.add_argument("--redeem-preview", action="store_true")
    parser.add_argument("--state-path", type=Path, default=STATE)
    args = parser.parse_args(argv)
    try:
        state = state_values(args.state_path)
        role = _determine_role(state)
        domain = state.get("SMITE_PANEL_DOMAIN", "")
        endpoint = secure_endpoint("https://" + domain)
        print(f"ROLE={role} MODE=standard PANEL=https://{domain}:443")
        if args.status:
            identity = IDENTITY_FILE
            print("PAIRING_STAGE=PREVIEW_DISABLED_UNTIL_SERVER_ROLLOUT")
            print("CREDENTIALS=" + ("STAGED (NOT ACTIVE)" if identity.is_file() else "NOT_STAGED"))
            print("LEGACY_NODE_AUTH=NOT_SECURED_BY_THIS_WIZARD")
            return 0
        if args.prepare_store:
            prepare_store()
            print("IDENTITY_STORE=READY MODE=0700; no containers changed")
            return 0

        # An explicit double gate prevents accidental credential redemption.
        if os.geteuid() != 0 or os.environ.get("UOPTI_SMITE_PAIRING_PREVIEW") != "1":
            raise WizardHold("Pairing is still disabled; do not enable before security rollout")
        if not sys.stdin.isatty():
            raise WizardHold("Interactive terminal required for one-time code")
        print("WARNING: STAGING ONLY. This does not secure existing Node traffic.")
        confirm = input("Type PAIR-CREDENTIAL-ONLY to proceed: ").strip()
        if confirm != "PAIR-CREDENTIAL-ONLY":
            raise WizardHold("Cancelled, no changes")
        prepare_store()
        if IDENTITY_FILE.exists() or IDENTITY_FILE.is_symlink():
            raise WizardHold("Identity already staged")
        node_id = input("Admin-approved Node UUID: ").strip()
        code = getpass.getpass("One-time pairing code (hidden): ")
        redeem(
            panel_url="https://" + domain, pairing_code=code,
            node_id=node_id, role=role,
        )
        print("PAIRING_CREDENTIAL=STAGED_ONLY; never sent to live Node runtime")
        return 0
    except WizardHold as exc:
        print(f"HOLD: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
