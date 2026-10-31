#!/usr/bin/env python3
"""Static, OFFLINE-only preflight for a disposable HTTPS Passkey browser lab.

No network, no socket, no subprocess, no Docker/Node/Panel/Broker access.
A PASS here is NOT a WebAuthn hardware test, deployment authorization,
release approval, root service configuration or permission to publish.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

class LabHold(RuntimeError):
    pass

# Fixed sources; a passing manifest is a review record, not an executable
# launcher. Real browser TLS/trust and authenticator evidence require a
# separate human-observed run on a disposable, isolated test machine.
EXPECTED = {
    "schema": 1,
    "kind": "stage15-passkey-browser-lab-offline-v1",
    "host_boundary": "disposable-standalone-machine",
    "approval_origin": "https://passkey-lab.test",
    "panel_origin": "https://panel-lab.test",
    "test_only_host_resolution": "127.0.0.1",
    "bind_address": "127.0.0.1",
    "https_port": 443,
    "tls": "trusted-disposable-lab-ca",
    "approval_socket": "temporary-lab-only",
    "credential_store": "new-empty-temporary-lab-only",
    "source": "isolated-reviewed-checkout",
    "broker": "disabled",
    "grant_writer": "disabled",
    "signed_ir_kh": "synthetic-only",
    "real_ir_kh_connectivity": "denied",
    "frp_owner": "never-touch",
    "production_dns": "no",
    "production_nginx": "no",
    "production_keys": "no",
    "production_database": "no",
    "web_approval_marker": "absent",
    "route_publication": "disabled",
    "physical_passkeys_verified": False,
    "hardware_independence_verified": False,
    "field_trial_authorized": False,
}

def validate(document):
    if type(document) is not dict or set(document) != set(EXPECTED):
        raise LabHold("LAB_MANIFEST_SCHEMA_HOLD")
    for k, expected in EXPECTED.items():
        if type(document[k]) is not type(expected) or document[k] != expected:
            raise LabHold("LAB_MANIFEST_ISOLATION_HOLD")
    for key in ("approval_origin", "panel_origin"):
        raw = document[key]
        url = urlsplit(raw)
        if (url.scheme != "https" or url.port is not None
            or url.username or url.password or url.query or url.fragment
            or url.path or url.hostname not in
                ("passkey-lab.test", "panel-lab.test")
            or raw != "https://" + url.hostname):
            raise LabHold("LAB_BROWSER_ORIGIN_HOLD")
    if document["approval_origin"] == document["panel_origin"]:
        raise LabHold("LAB_ORIGIN_SEPARATION_HOLD")
    return {
        "isolation_contract": "PASS_STATIC_ONLY",
        "real_tls_and_dns": "NOT_VERIFIED",
        "physical_primary_passkey": "NOT_TESTED",
        "physical_backup_passkey": "NOT_TESTED",
        "independent_hardware": "NOT_VERIFIED",
        "recovery": "NOT_TESTED_ON_HARDWARE",
        "approval_or_grant": "DISABLED",
        "publish_fourth_route": "DENIED",
        "live_ir_kh_changes": "FORBIDDEN",
    }

def check_file(path: Path):
    # This entrypoint is for CI/operator manual review of a lab manifest.
    # It does not read credentials, configure TLS or touch host resources.
    try:
        data=Path(path).read_text(encoding="utf-8")
        if len(data) > 8192:
            raise LabHold("LAB_MANIFEST_OVERSIZE")
        doc=json.loads(data)
    except (OSError, ValueError, UnicodeError) as exc:
        raise LabHold("LAB_MANIFEST_UNAVAILABLE") from exc
    return validate(doc)

if __name__ == "__main__":
    raise SystemExit("OFFLINE_LIBRARY_ONLY_NO_BROWSER_OR_LIVE_ACTIVATION")
