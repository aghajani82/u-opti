#!/usr/bin/env python3
"""Explicit KH-only RC.2 one-time credential redemption; inert --plan default.

No Node restart, Compose writes, pairing-code issuance, trusted origin changes,
Replay enrollment, or signed runtime activation. Do not paste secrets in logs.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.util
import os
from pathlib import Path
import socket
import stat
import sys

HERE = Path(__file__).resolve().parent
PAIRING = HERE / "smite-node-pairing.py"
ADMISSION = HERE / "smite-rc2-foreign-pairing-admission.py"
PAIRING_BLOB = "861e2735f76bb0b3947ab89e0b0bc28fde31c52c"
ADMISSION_BLOB = "67d4621b88c6f795573e60b5014c9d64bd6521bc"


class Hold(Exception):
    pass


def require(ok, reason):
    if not ok:
        raise Hold(reason)


def load_checked(path, expected, name):
    # No import/exec of source until exact Git content blob is validated.
    try:
        entry = path.lstat()
        require(
            stat.S_ISREG(entry.st_mode)
            and entry.st_uid == 0
            and stat.S_IMODE(entry.st_mode) == 0o600
            and entry.st_nlink == 1
            and entry.st_size <= 100000,
            "STAGED_FILE_NOT_PRIVATE",
        )
        data = path.read_bytes()
        require(len(data) <= 100000, "STAGED_SOURCE_TOO_LARGE")
        blob = b"blob " + str(len(data)).encode() + b"\0" + data
        require(hashlib.sha1(blob).hexdigest() == expected,
                "STAGED_SOURCE_HASH")
    except OSError as exc:
        raise Hold("STAGED_SOURCE_MISSING") from exc
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def empty_secure_store(pairing):
    directory = pairing.IDENTITY_DIR
    if directory.is_symlink():
        raise Hold("IDENTITY_DIRECTORY_SYMLINK")
    if directory.exists():
        d = directory.lstat()
        require(
            stat.S_ISDIR(d.st_mode) and d.st_uid == 0
            and stat.S_IMODE(d.st_mode) == 0o700,
            "IDENTITY_DIRECTORY_UNSAFE",
        )
    else:
        parent = directory.parent
        try:
            p = parent.lstat()
        except OSError as exc:
            raise Hold("IDENTITY_PARENT_MISSING") from exc
        require(stat.S_ISDIR(p.st_mode) and not parent.is_symlink(),
                "IDENTITY_PARENT_UNSAFE")
    for p in (
        pairing.IDENTITY_FILE,
        pairing.IDENTITY_DIR / "replay-enrollment.json",
        pairing.REPLAY_DB,
    ):
        require(not p.exists() and not p.is_symlink(),
                "IDENTITY_OR_REPLAY_ALREADY_EXISTS")


def preflight(pairing, admission):
    require(
        admission.admit_kh() == [
            "KH_NODE_RC2_PAUSED=PASS",
            "KH_GATEWAY_TLS443=PASS",
            "KH_SANAEI_XHTTP=UNCHANGED",
            "KH_TO_IR_HTTPS=PASS",
            "KH_FOREIGN_SIGNED_RUNTIME=NOT_ACTIVATED",
        ],
        "KH_RC2_ADMISSION",
    )
    state = pairing.state_values()
    require(
        state.get("SMITE_ROLE") == "foreign"
        and state.get("SMITE_NODE_NAME") == "node-kh"
        and state.get("SMITE_PANEL_DOMAIN") == "ir.kolbe1.ir"
        and state.get("SMITE_MANAGED_VERSION") == "2.0.0-rc.1",
        "KH_MANAGED_STATE",
    )
    require(
        pairing.secure_endpoint("https://ir.kolbe1.ir")
        == "https://ir.kolbe1.ir/api/node-pairing/redeem",
        "PANEL_REDEMPTION_ENDPOINT",
    )
    empty_secure_store(pairing)
    print("KH_RC2_ADMISSION=PASS")
    print("KH_REDEEM_SOURCE=VERIFIED")
    print("KH_LOCAL_IDENTITY=ABSENT")
    print("KH_REPLAY=ABSENT")
    print("KH_ONE_TIME_REDEEM_PLAN=PASS_READ_ONLY")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--plan", action="store_true")
    choice.add_argument("--redeem", action="store_true")
    args = parser.parse_args(argv)
    print("===== KH RC2 ONE-TIME PAIRING REDEMPTION =====")
    try:
        require(
            os.geteuid() == 0
            and socket.gethostname().split(".")[0].lower() == "kh",
            "KH_ROOT_ONLY",
        )
        require(sys.stdin.isatty(), "INTERACTIVE_TTY_REQUIRED")
        pairing = load_checked(PAIRING, PAIRING_BLOB, "kh_signed_pairing")
        admission = load_checked(ADMISSION, ADMISSION_BLOB, "kh_redeem_admission")
        preflight(pairing, admission)
        if args.plan:
            print("PAIRING_CODE=NOT_CONSUMED")
            print("LIVE_CHANGES=NONE")
            return 0

        require(
            os.environ.get("UOPTI_SMITE_PAIRING_FIELD_TRIAL") == "YES"
            and os.environ.get("UOPTI_SMITE_RC2_KH_REDEEM") == "YES",
            "EXPLICIT_DUAL_CONSENT_REQUIRED",
        )
        print("ONE_TIME_CODE_WILL_BE_CONSUMED=YES")
        print("KH_NODE_RUNTIME=STAYS_PAUSED")
        print("NO_REPLAY_ENROLLMENT=YES")
        try:
            confirm = input(
                "Type REDEEM-KH-ONCE to authorize, or CANCEL: "
            ).strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise Hold("OPERATOR_CANCELLED") from exc
        require(confirm == "REDEEM-KH-ONCE", "OPERATOR_CANCELLED")

        # Create only the private directory, no file/credential until Panel
        # returns authenticated HTTPS 200 and valid scoped Node secret.
        pairing.prepare_store()
        empty_secure_store(pairing)
        try:
            node_id = getpass.getpass(
                "Reserved node-kh UUID from Panel (hidden): "
            ).strip()
            code = getpass.getpass(
                "One-time Panel pairing code (hidden): "
            ).strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise Hold("PRIVATE_INPUT_CANCELLED") from exc
        require(
            pairing._NODE_ID.fullmatch(node_id) is not None,
            "NODE_ID_FORMAT",
        )
        require(
            pairing._CODE.fullmatch(code) is not None,
            "PAIRING_CODE_FORMAT",
        )
        pairing.redeem(
            panel_url="https://ir.kolbe1.ir",
            pairing_code=code,
            node_id=node_id,
            role="foreign",
        )
        saved_id, _secret = pairing._identity_record()
        require(saved_id == node_id, "STORED_IDENTITY_MISMATCH")
        require(
            not pairing.REPLAY_DB.exists()
            and not (pairing.IDENTITY_DIR / "replay-enrollment.json").exists(),
            "REPLAY_WAS_UNEXPECTEDLY_CREATED",
        )
        print("KH_SIGNED_IDENTITY=STAGED_VALID")
        print("KH_REPLAY=NOT_PROVISIONED")
        print("KH_NODE_RUNTIME=UNCHANGED_PAUSED")
        print("KH_PAIRING_REDEMPTION=PASS")
        print("SIGNED_ACTIVATION=NOT_PERFORMED")
        return 0
    except Hold as exc:
        print("KH_REDEEM=HOLD")
        print("REASON=" + str(exc))
    except Exception:
        # The server may have consumed a code before writing the local file.
        # Never automatically retry/reissue/rotate without both-side audit.
        print("KH_REDEEM=HOLD")
    print("DO_NOT_RETRY_WITHOUT_BOTH_SIDES_AUDIT=YES")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
