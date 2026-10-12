#!/usr/bin/env bash
# Experimental Standard Smite FRP -> XHTTP route reconciler. No public FRPS port.
SMITE_FRP_XHTTP_CONF="${SMITE_FRP_XHTTP_CONF:-/etc/nginx/u-opti-smite-frp-xhttp.conf}"
SMITE_FRP_XHTTP_BACKEND="${SMITE_GATEWAY_BACKEND_CONF:-/etc/nginx/conf.d/u-opti-smite-panel-backend.conf}"
SMITE_FRP_XHTTP_STATE="${SMITE_STATE_FILE:-/etc/u-opti/smite/state.env}"
SMITE_FRP_XHTTP_HELPER="${SMITE_OVERLAY_DIR:-/opt/u-opti-smite}/node/frp_gateway_config.py"

smite_frp_xhttp_enabled() {
    [ -f "$SMITE_FRP_XHTTP_HELPER" ] &&
    [ -f "$SMITE_FRP_XHTTP_STATE" ] &&
    grep -Fxq 'SMITE_CONNECTION_MODE=standard' "$SMITE_FRP_XHTTP_STATE"
}

smite_frp_xhttp_include() {
    smite_frp_xhttp_enabled || return 0
    local domain="$1"
    mkdir -p "$(dirname "$SMITE_FRP_XHTTP_CONF")" || return 1
    if [ ! -f "$SMITE_FRP_XHTTP_CONF" ]; then
        printf '%s\n' '# Managed by U-OPTI - Standard FRP XHTTP' > "$SMITE_FRP_XHTTP_CONF" || return 1
        chmod 0644 "$SMITE_FRP_XHTTP_CONF"
    fi
    python3 - "$SMITE_FRP_XHTTP_BACKEND" "$SMITE_FRP_XHTTP_CONF" "$domain" <<'PY'
from pathlib import Path
import os, sys, tempfile
backend, snippet, domain = map(Path, sys.argv[1:3]) if False else (Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
text = backend.read_text()
if not text.startswith("# Managed by U-OPTI - Smite Panel TLS backend\n") or text.count(f"server_name {domain};") != 1:
    raise SystemExit("ERROR: Unrecognized Panel TLS backend")
if "location = /~!frp {" not in text:
    raise SystemExit("ERROR: Standard FRP WSS route missing")
line = f"    include {snippet};\n"
if line in text:
    if text.count(line) != 1:
        raise SystemExit("ERROR: Repeated XHTTP include")
    print("FRP XHTTP include preserved")
    raise SystemExit(0)
anchor = "    location / {\n"
if text.count(anchor) != 1:
    raise SystemExit("ERROR: Unknown Panel location layout")
with tempfile.NamedTemporaryFile(mode="w", dir=backend.parent, prefix=".xhttp-backend-", delete=False) as f:
    f.write(text.replace(anchor, line + "\n" + anchor, 1))
    stage = Path(f.name)
os.chmod(stage, 0o644)
os.replace(stage, backend)
print("Standard FRP XHTTP include prepared")
PY
}

smite_frp_xhttp_sync() {
    smite_frp_xhttp_enabled || return 0
    [ "$(id -u)" = 0 ] || return 1
    [ -f "$SMITE_FRP_XHTTP_CONF" ] && [ -f "$SMITE_FRP_XHTTP_BACKEND" ] || return 1
    grep -Fq "    include $SMITE_FRP_XHTTP_CONF;" "$SMITE_FRP_XHTTP_BACKEND" || return 1
    local snapshot candidate backup
    snapshot="$(mktemp)" || return 1
    candidate="$(mktemp "$(dirname "$SMITE_FRP_XHTTP_CONF")/.frp-xhttp-new-XXXXXXXX")" || { rm -f "$snapshot"; return 1; }
    backup="$(mktemp "$(dirname "$SMITE_FRP_XHTTP_CONF")/.frp-xhttp-old-XXXXXXXX")" || { rm -f "$snapshot" "$candidate"; return 1; }
    chmod 0600 "$snapshot" "$candidate" "$backup"
    if ! docker exec smite-node cat /var/lib/smite-node/tunnels.json > "$snapshot"; then
        echo "ERROR: Cannot read persisted FRP tunnels; retaining existing routes" >&2
        rm -f "$snapshot" "$candidate" "$backup"
        return 1
    fi
    if ! python3 - "$snapshot" "$candidate" <<'PY'
import json, os, sys
snapshot, output = sys.argv[1:3]
if os.path.getsize(snapshot) > 1048576:
    raise SystemExit("ERROR: Tunnel state exceeds safety limit")
data = json.load(open(snapshot))
if not isinstance(data, dict):
    raise SystemExit("ERROR: Invalid tunnel state")
ports = set()
for value in data.values():
    if not isinstance(value, dict) or value.get("core") != "frp":
        continue
    spec = value.get("spec")
    if not isinstance(spec, dict) or spec.get("mode") != "server" or spec.get("type", "tcp") != "tcp":
        continue
    mappings = spec.get("ports") or [spec.get("remote_port") or spec.get("listen_port")]
    if not isinstance(mappings, list) or len(mappings) > 128:
        raise SystemExit("ERROR: Invalid FRP ports")
    for item in mappings:
        raw = item.get("remote") if isinstance(item, dict) else item
        if isinstance(raw, bool) or not isinstance(raw, (int, str)) or not str(raw).isascii() or not str(raw).isdecimal():
            raise SystemExit("ERROR: Invalid FRP remote port")
        port = int(raw)
        if not (1024 <= port <= 65535) or port in (int(spec.get("bind_port", 7000)), 443, 8000, 8443, 8888):
            raise SystemExit("ERROR: Unsafe FRP remote port")
        ports.add(port)
if len(ports) > 128:
    raise SystemExit("ERROR: Too many FRP routes")
content = ["# Managed by U-OPTI - Standard FRP XHTTP\n"]
for port in sorted(ports):
    shared = (
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "        proxy_buffering off;\n"
        "        proxy_request_buffering off;\n"
        "        proxy_connect_timeout 10s;\n"
        "        proxy_read_timeout 3600s;\n"
        "        proxy_send_timeout 3600s;\n"
    )
    content.append(f"\n    location = /{port}/web {{\n        proxy_pass http://127.0.0.1:{port}/web;\n"+shared+"    }\n")
    content.append(f"\n    location ^~ /{port}/web/ {{\n        proxy_pass http://127.0.0.1:{port}/web/;\n"+shared+"    }\n")
with open(output, "w") as f:
    f.write("".join(content))
print("Valid Standard FRP XHTTP routes:", len(ports))
PY
    then
        rm -f "$snapshot" "$candidate" "$backup"
        return 1
    fi
    rm -f "$snapshot"
    if cmp -s "$candidate" "$SMITE_FRP_XHTTP_CONF"; then
        rm -f "$candidate" "$backup"
        return 0
    fi
    cp -p "$SMITE_FRP_XHTTP_CONF" "$backup" || { rm -f "$candidate" "$backup"; return 1; }
    chmod 0644 "$candidate"
    mv -f "$candidate" "$SMITE_FRP_XHTTP_CONF" || { rm -f "$backup"; return 1; }
    if nginx -t && systemctl reload nginx; then
        echo "Standard FRP XHTTP routes updated"
        rm -f "$backup"
        return 0
    fi
    echo "ERROR: Nginx rejected XHTTP routes; reverting" >&2
    mv -f "$backup" "$SMITE_FRP_XHTTP_CONF"
    nginx -t && systemctl reload nginx || true
    return 1
}

smite_frp_xhttp_install_timer() {
    smite_frp_xhttp_enabled || return 0
    [ "$(id -u)" = 0 ] || return 1
    local script=/usr/local/lib/u-opti/modules/smite-frp-xhttp.sh
    [ -f "$script" ] || return 1
    cat > /etc/systemd/system/u-opti-smite-frp-xhttp.service <<EOF
[Unit]
Description=U-OPTI Standard FRP XHTTP route reconciliation
After=docker.service nginx.service
[Service]
Type=oneshot
ExecStart=/bin/bash $script --sync
EOF
    cat > /etc/systemd/system/u-opti-smite-frp-xhttp.timer <<'EOF'
[Unit]
Description=U-OPTI refresh FRP XHTTP routes
[Timer]
OnBootSec=20s
OnUnitInactiveSec=15s
AccuracySec=2s
Unit=u-opti-smite-frp-xhttp.service
[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload &&
    systemctl enable --now u-opti-smite-frp-xhttp.timer &&
    smite_frp_xhttp_sync
}

case "${1:-}" in
    --sync) smite_frp_xhttp_sync ;;
    --install) smite_frp_xhttp_install_timer ;;
esac
