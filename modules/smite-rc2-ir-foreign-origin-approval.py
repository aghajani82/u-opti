#!/usr/bin/env python3
"""IR-only KH RC.2 foreign origin review and explicit single-origin approval.

A --plan verifies the reserved node-kh and manually entered private KH HTTPS
control URL, without displaying it. Separate --apply explicitly consents to
the ONLY live mutation: additive root-owned origin trust with rollback.

No pairing code, identity, replay, Node/Panel recreate, Nginx reload or
production authorization.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import stat
import sys
from urllib import error, request

HERE = Path(__file__).resolve().parent
PAIRING = HERE / "smite-node-pairing.py"
ADMISSION = HERE / "smite-rc2-foreign-pairing-admission.py"
PAIRING_BLOB = "861e2735f76bb0b3947ab89e0b0bc28fde31c52c"
ADMISSION_BLOB = "67d4621b88c6f795573e60b5014c9d64bd6521bc"
KH_HOST = "https://kh.kolbe1.ir"
URL_RULE = re.compile(r"^https://kh\.kolbe1\.ir/smite-node/[A-Za-z0-9_-]{16,80}$")
NODE_NAME = "node-kh"


class Hold(Exception):
    pass


def require(value, reason):
    if not value:
        raise Hold(reason)


def checked_module(path, expected, name):
    try:
        st = path.lstat()
        require(
            stat.S_ISREG(st.st_mode) and st.st_uid == 0
            and stat.S_IMODE(st.st_mode) == 0o600
            and st.st_nlink == 1 and st.st_size <= 100000,
            "STAGED_SOURCE_METADATA",
        )
        data = path.read_bytes()
        require(len(data) <= 100000, "STAGED_SOURCE_SIZE")
        header = b"blob " + str(len(data)).encode() + b"\0"
        require(hashlib.sha1(header + data).hexdigest() == expected,
                "STAGED_SOURCE_HASH")
    except OSError as exc:
        raise Hold("STAGED_SOURCE_MISSING") from exc
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None,
            "STAGED_SOURCE_IMPORT")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reserved_node(pairing):
    state = pairing.state_values()
    require(
        state.get("SMITE_ROLE") == "panel-iran"
        and state.get("SMITE_CONNECTION_MODE") == "standard"
        and state.get("SMITE_PANEL_DOMAIN") == "ir.kolbe1.ir"
        and state.get("SMITE_MANAGED_VERSION") == "2.0.0-rc.1",
        "IR_MANAGED_STATE",
    )
    dbpath = pairing.PANEL_DB
    require(dbpath.is_file() and not dbpath.is_symlink(), "PANEL_DB")
    try:
        with sqlite3.connect(
            dbpath.absolute().as_uri() + "?mode=ro", uri=True, timeout=5,
        ) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute(
                "SELECT id,name,status,metadata FROM nodes"
            ).fetchall()
    except sqlite3.Error as exc:
        raise Hold("PANEL_DB_READ") from exc
    foreign = []
    for node_id, name, status, raw in rows:
        try:
            meta = json.loads(raw or "{}")
        except (ValueError, TypeError) as exc:
            raise Hold("NODE_METADATA_INVALID") from exc
        require(isinstance(meta, dict), "NODE_METADATA_INVALID")
        if meta.get("role") == "foreign":
            require(
                name == NODE_NAME and status == "pending"
                and meta.get("node_name") == NODE_NAME
                and meta.get("provisioning") == "reserved_for_pairing"
                and re.fullmatch(r"[A-Za-z0-9_-]{8,80}", str(node_id)) is not None,
                "FOREIGN_RESERVATION_DRIFT",
            )
            foreign.append(node_id)
    require(len(foreign) == 1, "FOREIGN_RESERVATION_COUNT")
    try:
        trusted = json.loads(pairing._regular(
            pairing.APPROVED_ORIGINS, mode=0o600, limit=64000,
        ))
    except (ValueError, TypeError) as exc:
        raise Hold("TRUST_SCHEMA") from exc
    require(
        isinstance(trusted, dict) and set(trusted) == {"version", "nodes"}
        and trusted.get("version") == 1
        and isinstance(trusted.get("nodes"), dict),
        "TRUST_SCHEMA",
    )
    values = list(trusted["nodes"].values())
    require(
        values and all(isinstance(v, dict) for v in values)
        and any(v.get("role") == "iran" for v in values)
        and all(v.get("role") != "foreign" for v in values),
        "TRUST_BASELINE_DRIFT",
    )
    return state, foreign[0]


def hidden_url():
    try:
        value = getpass.getpass(
            "Paste KH private HTTPS/443 control URL (hidden): "
        ).strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise Hold("URL_INPUT_CANCELLED") from exc
    require(URL_RULE.fullmatch(value), "UNAPPROVED_KH_CONTROL_URL")
    return value


def verify_gateway(pairing, url):
    origin, canonical = pairing._approved_foreign_control_url(url)
    require(origin == KH_HOST + ":443" and canonical == url,
            "GATEWAY_URL_NONCANONICAL")
    opener = request.build_opener(
        request.ProxyHandler({}),
        request.HTTPSHandler(context=ssl.create_default_context()),
        pairing.NoRedirect(),
    )
    try:
        with opener.open(url + "/", timeout=12) as response:
            require(response.status == 200 and
                    json.loads(response.read(257))
                    == {"status": "ok", "service": "smite-node"},
                    "GATEWAY_NOT_READY")
    except (error.HTTPError, error.URLError, ValueError, OSError) as exc:
        raise Hold("GATEWAY_TLS_READINESS") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--plan", action="store_true")
    selector.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    print("===== IR RC2 KH FOREIGN ORIGIN APPROVAL =====")
    try:
        require(os.geteuid() == 0 and
                socket.gethostname().split(".")[0].lower() == "ir",
                "IR_ROOT_ONLY")
        require(sys.stdin.isatty(), "INTERACTIVE_TTY_REQUIRED")
        pairing = checked_module(PAIRING, PAIRING_BLOB, "rc2_origin_pairing")
        admission = checked_module(
            ADMISSION, ADMISSION_BLOB, "rc2_origin_admission",
        )
        require(
            admission.admit_ir() == [
                "IR_PANEL_RC2_SIGNED=PASS",
                "IR_LOCAL_NODE_RC1=UNCHANGED",
                "IR_TRUST_MOUNT=READ_ONLY",
                "IR_FOREIGN_PATH_HMAC_POLICY=PASS",
                "IR_HTTPS_STATUS=PASS",
            ],
            "IR_INDEPENDENT_ADMISSION",
        )
        state, node_id = reserved_node(pairing)
        url = hidden_url()
        verify_gateway(pairing, url)
        pairing._require_panel_signed_registration_schema()
        pairing._require_panel_foreign_transport()
        print("IR_RC2_PANEL_ADMISSION=PASS")
        print("NODE_KH_RESERVATION=PASS")
        print("KH_PRIVATE_TLS443_READINESS=PASS")
        print("IR_FOREIGN_ORIGIN_PLAN=PASS_READ_ONLY")
        if args.plan:
            print("ORIGIN_APPROVAL=NOT_APPLIED")
            print("LIVE_CHANGES=NONE")
            return 0

        require(
            os.environ.get("UOPTI_SMITE_PAIRING_FIELD_TRIAL") == "YES"
            and os.environ.get("UOPTI_SMITE_IR_RC2_ORIGIN_APPROVAL") == "YES",
            "EXPLICIT_DUAL_CONSENT_REQUIRED",
        )
        print("TARGET=ONE_FOREIGN_TRUST_RECORD")
        print("OTHER_COMPONENT_CHANGES=NO")
        try:
            choice = input(
                "Type APPROVE-KH-ORIGIN to continue, or CANCEL: "
            ).strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise Hold("OPERATOR_CANCELLED") from exc
        require(choice == "APPROVE-KH-ORIGIN", "OPERATOR_CANCELLED")
        pairing.approve_foreign_origin_field_trial(
            node_id=node_id, node_name=NODE_NAME, control_url=url, state=state,
        )
        print("IR_FOREIGN_ORIGIN_APPROVAL=PASS")
        print("KH_SIGNED_PAIRING=NOT_ACTIVATED")
        print("LIVE_RESTARTS=NONE")
        return 0
    except Hold as exc:
        print("IR_FOREIGN_ORIGIN_APPROVAL=HOLD")
        print("REASON=" + str(exc))
        print("DO_NOT_REPEAT_AFTER_PARTIAL_FAILURE=YES")
        return 2
    except Exception:
        # Do not print secrets, UUIDs or private URLs from internal exceptions.
        print("IR_FOREIGN_ORIGIN_APPROVAL=HOLD")
        print("DO_NOT_REPEAT_AFTER_PARTIAL_FAILURE=YES")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
