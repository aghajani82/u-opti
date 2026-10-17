#!/usr/bin/env python3
"""Opt-in two-terminal Backhaul pairing on fresh IR/KH TEST hosts.

IR: show an existing or newly created private Backhaul token on an interactive
TTY once per explicit invocation. KH: paste it into a no-echo prompt and
create/verify root-only shared.token. This is a LONG-LIVED SHARED SECRET, not
an ephemeral OTP. No files are sent to other hosts and no remote SSH keys
are required. Never use on already installed Sidecar hosts.
"""
from __future__ import annotations

import argparse
import getpass
import importlib.util
import os
import secrets
from pathlib import Path
import sys
import tomllib

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def _load(alias: str, name: str):
    spec = importlib.util.spec_from_file_location(alias, HERE / name)
    if spec is None or spec.loader is None:
        raise RuntimeError("Required Backhaul pairing module is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pair = _load("paste_pair_helpers", "smite-backhaul-sidecar-ssh-pair.py")
TOKEN = pair.TOKEN


class PasteHold(ValueError):
    pass


def _interactive() -> None:
    # A user must be present. Never reveal secrets to redirected output, logs
    # or a non-interactive session; KH getpass must support echo suppression.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise PasteHold("An interactive terminal is required")


def show_ir() -> str:
    _interactive()
    pair._trusted_role("ir")
    pair._safe_parents()
    pair._fresh("ir")
    if not TOKEN.exists() and not TOKEN.is_symlink():
        pair.token_tool.generate()
    if not pair.token_tool.inspect(TOKEN):
        raise PasteHold("Existing private IR token is missing or invalid")
    raw = TOKEN.read_bytes()
    code = pair._payload(raw).decode("ascii")
    # Caller prints only after role, fresh-host and file-mode checks pass.
    return code


def show_installed_ir() -> str:
    """Re-display an existing code after verified IR trial activation only.

    No token creation or overwrite; malformed/partial journals fail closed.
    """
    _interactive()
    pair._trusted_role("ir")
    pair._safe_parents()
    trial = _load("paste_pair_trial", "smite-backhaul-sidecar-live-trial.py")
    doc = trial._journal_read(trial._root("ir"))
    if doc.get("role") != "ir" or doc.get("phase") != "trial_active":
        raise PasteHold("IR trial is not active")
    if not pair.token_tool.inspect(TOKEN):
        raise PasteHold("Existing private IR token is absent or invalid")
    code = pair._payload(TOKEN.read_bytes()).decode("ascii")
    config_bytes, _ = trial._safe_file(pair.PRIVATE_DIR / "ir.toml", mode=0o600)
    installed = tomllib.loads(config_bytes.decode("utf-8"))["server"]["token"]
    if not isinstance(installed, str) or not secrets.compare_digest(installed, code):
        raise PasteHold("Installed Sidecar secret differs; no pairing code shown")
    return code


def paste_kh() -> str:
    _interactive()
    pair._trusted_role("kh")
    pair._safe_parents()
    # Never solicit a token when an already installed Sidecar may be active.
    pair._fresh("kh")
    # getpass disables terminal echo: token does not enter shell history/argv.
    entered = getpass.getpass("Paste IR Backhaul pairing code (hidden): ")
    if not isinstance(entered, str) or len(entered) > 128:
        raise PasteHold("Invalid pairing code")
    try:
        raw = entered.encode("ascii")
        pair._payload(raw)
    except (UnicodeError, pair.PairingHold) as exc:
        raise PasteHold("Invalid pairing code") from exc
    from io import BytesIO
    # Reuse the exact same fail-closed KH receiver as trusted SSH pairing.
    # Existing differing files are never overwritten.
    return pair.receive_kh(BytesIO(raw + b"\n"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--show-ir", action="store_true")
    modes.add_argument("--show-installed-ir", action="store_true")
    modes.add_argument("--paste-kh", action="store_true")
    parser.add_argument("--confirm", default="")
    opts = parser.parse_args()
    if (opts.show_ir or opts.show_installed_ir) and opts.confirm != "DISPLAY-IR-PRIVATE-CODE":
        print("HOLD: Explicit IR code display confirmation required.")
        return 2
    if opts.paste_kh and opts.confirm != "PASTE-KH-PRIVATE-CODE":
        print("HOLD: Explicit KH private token import confirmation required.")
        return 2
    try:
        if opts.show_ir or opts.show_installed_ir:
            code = show_installed_ir() if opts.show_installed_ir else show_ir()
            print("PRIVATE BACKHAUL SECRET — do NOT share in chat/screenshots/logs.")
            print("Copy straight to the KH Bitvise terminal; avoid saving to Notepad.")
            print("This is NOT a one-time code; protect it until you rotate the token.")
            print("PAIRING CODE: " + code)
            print("IR_PRIVATE_PAIRING_CODE_DISPLAYED")
        else:
            result = paste_kh()
            if result not in (
                "KH_PAIRING_RECEIVED_PRIVATE_AND_VALID",
                "KH_PAIRING_ALREADY_MATCHED_NO_CHANGE",
            ):
                raise PasteHold("Unexpected pairing acknowledgement")
            print(result)
            print("KH_TOKEN_CHECK_PASSED — no secrets displayed.")
    except Exception:
        # Sanitize all exceptions, even ones with private token/config material.
        print("HOLD: Two-terminal pairing refused; no active tunnel modified.")
        print("Check test-host role, existing Sidecar state and token permissions.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
