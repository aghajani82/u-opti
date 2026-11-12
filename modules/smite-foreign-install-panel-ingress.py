"""Offline Nginx 443 ingress renderer for the signed Foreign installation trial.

No file writes, reloads, schema migration, flag enablement or host commands.
The caller must first admit an exact signed trial Panel image and the existing
U-OPTI TLS backend/pairing secret before applying any rendered bytes.
"""
from __future__ import annotations

import re


class IngressHold(ValueError):
    pass


def deny():
    raise IngressHold("Foreign installation HTTPS ingress HOLD")


BEGIN_REDEEM = "    # BEGIN U-OPTI FOREIGN INSTALL REDEEM\n"
END_REDEEM = "    # END U-OPTI FOREIGN INSTALL REDEEM\n"
BEGIN_PROOF = "    # BEGIN U-OPTI FOREIGN INSTALL SIGNED PROOF\n"
END_PROOF = "    # END U-OPTI FOREIGN INSTALL SIGNED PROOF\n"
ANCHOR = "    location / {\n"
SECRET = "include /etc/nginx/u-opti-smite-pairing-secret.conf;"
STRIP = '        proxy_set_header X-Smite-Pairing-Ingress "";\n'


def _location(path, *, ingress):
    header = ("        " + SECRET + "\n") if ingress else STRIP
    # Exact match ensures the bearer-code POST never inherits broad root
    # handling and no path-prefix or duplicate URL can authenticate.
    return (
        "    location = " + path + " {\n"
        "        limit_except POST { deny all; }\n"
        "        client_max_body_size 8k;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_request_buffering on;\n"
        + header +
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        '        proxy_set_header Connection "";\n'
        "        proxy_pass http://127.0.0.1:8000;\n"
        "        proxy_connect_timeout 5s;\n"
        "        proxy_read_timeout 15s;\n"
        "        proxy_send_timeout 15s;\n"
        "        proxy_cache off;\n"
        '        add_header Cache-Control "no-store" always;\n'
        "        access_log off;\n"
        "    }\n"
    )


REDEEM = BEGIN_REDEEM + _location("/api/foreign-install/redeem", ingress=True) + END_REDEEM
PROOF = BEGIN_PROOF + _location("/api/node-control/installation-status", ingress=False) + END_PROOF


def render(backend: bytes, domain: str) -> bytes:
    """Return the reviewed config; idempotent and fail-closed on drift."""
    if (not isinstance(backend, bytes) or len(backend) > 256_000
            or not isinstance(domain, str)
            or not re.fullmatch(
                r"(?=.{4,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z",
                domain)):
        deny()
    try:
        text = backend.decode("utf-8")
    except UnicodeError:
        deny()
    if (not text.startswith("# Managed by U-OPTI - Smite Panel TLS backend\n")
            or text.count("server {\n") != 1
            or text.count("    server_name " + domain + ";\n") != 1
            or text.count(ANCHOR) != 1
            or text.count("    # BEGIN U-OPTI SMITE SIGNED PAIRING REDEEM") != 1
            or text.count(SECRET) < 1):
        deny()
    # Only the exact upstream pairing header include can be used for the new
    # route. A forged fallback root header must never get forwarded.
    existing_pairing = re.search(
        r"    # BEGIN U-OPTI SMITE SIGNED PAIRING REDEEM\n"
        r"(?P<block>.*?)"
        r"    # END U-OPTI SMITE SIGNED PAIRING REDEEM\n",
        text, re.DOTALL)
    if (not existing_pairing
            or existing_pairing.group("block").count(SECRET) != 1
            or "    location = /api/node-pairing/redeem {\n" not in existing_pairing.group("block")
            or "proxy_pass http://127.0.0.1:8000;" not in existing_pairing.group("block")):
        deny()
    base = text.find(ANCHOR)
    end = text.find("    }\n", base)
    if end < 0:
        deny()
    root = text[base:end]
    if (root.count("proxy_pass http://127.0.0.1:8000;") != 1
            or root.count("proxy_set_header Host $host;") != 1):
        deny()
    if re.search(r"(?m)^\s*proxy_set_header\s+X-Smite-Pairing-Ingress\b", root):
        if root.count(STRIP) != 1:
            deny()
    else:
        root = root.replace(
            "        proxy_set_header Host $host;\n",
            "        proxy_set_header Host $host;\n" + STRIP, 1)
        text = text[:base] + root + text[end:]

    present = [marker in text for marker in
               (BEGIN_REDEEM, END_REDEEM, BEGIN_PROOF, END_PROOF)]
    if any(present) and not all(present):
        deny()
    if all(present):
        # Drift in any previously provisioned exact location is never repaired
        # implicitly: require an operator-reviewed rollback before retry.
        for begin, end_marker, expected in (
                (BEGIN_REDEEM, END_REDEEM, REDEEM),
                (BEGIN_PROOF, END_PROOF, PROOF)):
            if text.count(begin) != 1 or text.count(end_marker) != 1:
                deny()
            first = text.find(begin)
            last = text.find(end_marker, first)
            if last < 0 or text[first:last+len(end_marker)] != expected:
                deny()
        return text.encode("utf-8")

    for path in ("/api/foreign-install/redeem", "/api/node-control/installation-status"):
        if re.search(r"(?m)^\s*location\s+(?:=\s*)?" + re.escape(path) + r"(?=[\s/{])", text):
            deny()
    text = text.replace(ANCHOR, REDEEM + "\n" + PROOF + "\n" + ANCHOR, 1)
    return text.encode("utf-8")
