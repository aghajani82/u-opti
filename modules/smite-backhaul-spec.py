#!/usr/bin/env python3
"""Pure, opt-in Standard Backhaul v0.7.2 spec validation for Smite v0.1.7.

Not a live installer. Neither starts Backhaul nor modifies any files.
The Smite adapter/panel integration must use this helper only when a
tunnel is explicitly marked uopti_standard_backhaul=true.
"""
from __future__ import annotations

from copy import deepcopy

FLAG = "uopti_standard_backhaul"
RESERVED = {443, 7000, 8000, 8443, 8888, 18476}
LOCALHOST = "127.0.0.1"


class StandardBackhaulSpecError(ValueError):
    pass


def port_number(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise StandardBackhaulSpecError(f"{label}: integer port required")
    raw = str(value)
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 5:
        raise StandardBackhaulSpecError(f"{label}: numeric port required")
    port = int(raw)
    if port < 1024 or port > 65535 or port in RESERVED:
        raise StandardBackhaulSpecError(f"{label}: forbidden or out of range")
    return port


def _port_mapping(mapping: object, port: int) -> None:
    # Smite v0.1.7 may already expand "PORT" to "PORT=127.0.0.1:PORT".
    # Every form must be narrowed to loopback on both ends.
    val = str(mapping)
    acceptable = {
        str(port),
        f"{port}={LOCALHOST}:{port}",
        f"{LOCALHOST}:{port}={LOCALHOST}:{port}",
    }
    if val not in acceptable:
        raise StandardBackhaulSpecError(
            "Standard Backhaul supports one loopback-only equal-port mapping"
        )


def compile_standard_specs(
    incoming: dict,
    *,
    data_port: int = 56053,
    control_port: int = 3080,
    bridge_port: int = 13080,
) -> tuple[dict, dict]:
    """Return independent server/client specs (without modifying caller data).

    Smite must pass the server to the IR node and the client to KH. These
    specs deliberately use Backhaul 'ws' rather than its insecure native WSS.
    KH Nginx's loopback bridge performs CA + hostname verified HTTPS to IR.
    """
    if not isinstance(incoming, dict) or incoming.get(FLAG) is not True:
        raise StandardBackhaulSpecError("Standard Backhaul must be explicitly selected")
    p = port_number(data_port, "data_port")
    c = port_number(control_port, "control_port")
    b = port_number(bridge_port, "bridge_port")
    if len({p, c, b}) != 3:
        raise StandardBackhaulSpecError("Data, control and bridge ports must differ")
    if incoming.get("transport", incoming.get("type", "ws")) != "ws":
        raise StandardBackhaulSpecError("Standard Backhaul requires WS, not raw TCP/WSS")
    if incoming.get("tls_cert") or incoming.get("tls_key"):
        raise StandardBackhaulSpecError("TLS terminates at Nginx, not the Backhaul process")
    token = incoming.get("token")
    if not isinstance(token, str) or len(token) < 24 or not token.strip():
        raise StandardBackhaulSpecError("A strong generated Backhaul token is required")
    mappings = incoming.get("ports", [p])
    if not isinstance(mappings, list) or len(mappings) != 1:
        raise StandardBackhaulSpecError("Exactly one data-port mapping is required")
    _port_mapping(mappings[0], p)
    if any(incoming.get(k) not in (None, "", LOCALHOST) for k in ("target_host", "local_ip")):
        raise StandardBackhaulSpecError("Target must remain on KH loopback")
    # Remove conflicting network bind hints in both outputs to prevent
    # later adapter logic from unintentionally reinstating wildcard binding.
    server = deepcopy(incoming)
    client = deepcopy(incoming)
    server.update(
        mode="server",
        transport="ws",
        type="ws",
        bind_addr=f"{LOCALHOST}:{c}",
        bind_ip=LOCALHOST,
        control_port=c,
        ports=[f"{LOCALHOST}:{p}={LOCALHOST}:{p}"],
        target_host=LOCALHOST,
        public_port=p,
        listen_port=p,
    )
    client.update(
        mode="client",
        transport="ws",
        type="ws",
        remote_addr=f"{LOCALHOST}:{b}",
        control_port=c,
        ports=[f"{LOCALHOST}:{p}={LOCALHOST}:{p}"],
        target_host=LOCALHOST,
    )
    return server, client
