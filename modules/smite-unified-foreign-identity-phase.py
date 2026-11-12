#!/usr/bin/env python3
"""Trial Foreign grant->signed proof->no-overwrite identity composition.

REHEARSAL ONLY. No production CLI to redeem or promote. This composes the
existing client, Gateway admission, and promotion helpers, rather than
introducing new registration/key-generation logic. Production menu option 2
must NOT call this before the unified trial image activation gate and complete
recovery journal have been independently reviewed.

The only command-line action is an inert status description. The Python
rehearsal entry requires an explicit disposable-root capability and injected
transport; it refuses the production identity and state paths. No Docker,
Nginx, systemd, FRP, XHTTP, Sanaei, replay or runtime activation is performed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


class Hold(ValueError):
    """No exceptions expose code or persisted node secret."""


def deny():
    raise Hold("Unified Foreign identity admission HOLD; retain private state")


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename))
    if spec is None or spec.loader is None:
        deny()
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj


def _packet_record(packet):
    # Reconstruct the exact, already-validated logical content in memory.
    # Never add a code to argv, environment, stdout, a journal or Docker.
    return json.dumps({
        "protocol": "smi1",
        "panel_url": packet.scope["panel_url"],
        "node_id": packet.scope["node_id"],
        "node_name": packet.scope["node_name"],
        "origin": packet.scope["origin"],
        "control_url": packet.scope["control_url"],
        "installation_code": packet.code,
        "expires_at": packet.expires_at,
    }, separators=(",", ":"))


def rehearse(*, packet_path, state_path, gateway_path, node_env_path,
             directory, live_identity, transport, now, disposable_capability=False):
    """Exercise original grant client and promotion in an isolated fixture.

    Transport is injected intentionally; there is no default network access.
    Root / and the original host identity paths are not admitted even if
    a caller accidentally imports this helper from the live installer.
    """
    if (not disposable_capability or not callable(transport)
            or type(now) is not int):
        deny()
    private = Path(directory)
    live = Path(live_identity)
    packet_file = Path(packet_path)
    state = Path(state_path)
    gateway = Path(gateway_path)
    env = Path(node_env_path)
    paths = (private, live, packet_file, state, gateway, env)
    if any(not p.is_absolute() or '..' in p.parts for p in paths):
        deny()
    # Require all candidate paths to share one non-root disposable parent.
    if not (private.parent == live.parent == state.parent == gateway.parent
            == env.parent == packet_file.parent.parent
            and private.name == "foreign-staging"
            and packet_file.parent == private
            and live.name == "node-identity.json"
            and live.parent.name == "foreign-fixture"
            and state.name == "state.env"
            and gateway.name == "foreign-gateway.env"
            and env.name == "node.env"):
        deny()
    if live.parent == Path("/"):
        deny()
    # Do not inspect the host default /etc, /opt or /var paths even when
    # a caller supplies the fixture flag by mistake.
    if any(str(p).startswith(("/etc/u-opti/", "/opt/smite", "/var/lib/u-opti/"))
           for p in paths):
        deny()

    client = load("uopti_unified_client_phase", "smite-foreign-install-client.py")
    promotion = load("uopti_unified_promotion_phase", "smite-foreign-install-promotion.py")
    gateway_plan = load("uopti_unified_gateway_phase", "smite-unified-foreign-gateway-plan.py")
    try:
        packet = gateway_plan.private_packet(packet_file, client, promotion)
        # Both preflights happen BEFORE the one-time code can be consumed.
        admitted = gateway_plan.admit(
            packet_path=packet_file, state_path=state,
            gateway_state_path=gateway)
        if admitted != urlsplit(packet.scope["control_url"]).path:
            deny()
        promotion.verify_gateway(
            packet, state_path=state, gateway_path=gateway,
            node_env_path=env, client=client)

        encoded = _packet_record(packet)
        # A completed promotion means the live identity exists: never
        # call enroll again; check the exact receipt and signed proof instead.
        if not os.path.lexists(live):
            result = client.enroll(
                encoded, directory=private, live_identity=live,
                transport=transport, now=now)
            if result.get("status") != "enrolled":
                deny()
        promoted = promotion.promote(
            encoded, client=client, directory=private, live_identity=live,
            state_path=state, gateway_path=gateway, node_env_path=env,
            transport=transport, now=now)
        if (promoted.get("status") != "identity_promoted"
                or promoted.get("node_id") != packet.scope["node_id"]
                or promoted.get("runtime_activation") != "not_performed"):
            deny()
        return {
            "phase": "IDENTITY_PROMOTED_OFFLINE",
            "node_id": packet.scope["node_id"],
            "signed_panel_proof": "PASS",
            "runtime_activation": "NOT_PERFORMED",
            "connected": False,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            client.Hold, promotion.Hold, gateway_plan.Hold):
        deny()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", required=True)
    parser.parse_args(argv)
    print("UNIFIED_FOREIGN_IDENTITY_PHASE=REHEARSAL_ONLY")
    print("PRODUCTION_REDEEM_AND_PROMOTION=NOT_AUTHORIZED")
    print("NODE_RUNTIME=UNCHANGED")
    print("FOREIGN_CONNECTED=NOT_PROVEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
