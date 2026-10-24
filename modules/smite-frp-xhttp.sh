#!/usr/bin/env bash
# Experimental Standard Smite FRP -> XHTTP route reconciler. No public FRPS port.
SMITE_FRP_XHTTP_CONF="${SMITE_FRP_XHTTP_CONF:-/etc/nginx/u-opti-smite-frp-xhttp.conf}"
SMITE_FRP_XHTTP_BACKEND="${SMITE_GATEWAY_BACKEND_CONF:-/etc/nginx/conf.d/u-opti-smite-panel-backend.conf}"
SMITE_FRP_XHTTP_STATE="${SMITE_STATE_FILE:-/etc/u-opti/smite/state.env}"
SMITE_FRP_XHTTP_HELPER="${SMITE_OVERLAY_DIR:-/opt/u-opti-smite}/node/frp_gateway_config.py"
# RC2 Node owns its signed WSS helper *inside* the immutable Node image.
# Do NOT create a fake legacy file just to bypass this compatibility gate.
SMITE_FRP_RC2_READY_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/smite-frp-rc2-gateway-ready.py"
SMITE_FRP_XHTTP_PATH_HELPER="${SMITE_FRP_XHTTP_PATH_HELPER:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/smite-frp-xhttp-paths.py}"
SMITE_FRP_XHTTP_PATHS="${SMITE_FRP_XHTTP_PATHS:-/etc/u-opti/smite/frp-xhttp-paths.json}"

smite_frp_xhttp_enabled() {
    [ -f "$SMITE_FRP_XHTTP_STATE" ] &&
        grep -Fxq 'SMITE_CONNECTION_MODE=standard' "$SMITE_FRP_XHTTP_STATE" ||
        return 1
    # Legacy Standard installations keep their original compatibility path.
    if [ -f "$SMITE_FRP_XHTTP_HELPER" ]; then
        return 0
    fi
    # RC2-only path: independently verify signed WSS Node state + immutable
    # image, committed overlay, protected mounts and existing IR Nginx include.
    # Fail closed: missing gate file cannot silently enable route publication.
    [ -f "$SMITE_FRP_RC2_READY_SCRIPT" ] || return 1
    python3 -B "$SMITE_FRP_RC2_READY_SCRIPT" >/dev/null
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
backend, snippet, domain = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
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
    # Smite creates tunnels.json only after its first tunnel is applied.
    # On a fresh Standard installation, this is a normal zero-tunnel state.
    # Never interpret an unavailable Docker node or a disappeared state file
    # with existing routes as an empty set: that could silently drop routes.
    if docker exec smite-node test -f /var/lib/smite-node/tunnels.json >/dev/null 2>&1; then
        if ! docker exec smite-node cat /var/lib/smite-node/tunnels.json > "$snapshot"; then
            echo "ERROR: Cannot read persisted FRP tunnels; retaining existing routes" >&2
            rm -f "$snapshot" "$candidate" "$backup"
            return 1
        fi
    elif docker exec smite-node test -d /var/lib/smite-node >/dev/null 2>&1 &&
         ! grep -Eq '^[[:space:]]*location[[:space:]]' "$SMITE_FRP_XHTTP_CONF"; then
        # No persisted tunnel file and no previously published FRP routes.
        # Do not change Nginx; keep the timer active for first tunnel creation.
        printf '{}\n' > "$snapshot"
        echo "No FRP tunnels yet; XHTTP auto-sync ready."
    else
        echo "ERROR: FRP state unavailable after routes existed, or Smite node is offline; retaining existing routes" >&2
        rm -f "$snapshot" "$candidate" "$backup"
        return 1
    fi
    if ! python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" render "$snapshot" "$candidate"; then
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


# IR-only: assign XHTTP path to a Smite FRP TCP tunnel that already exists.
# Registry rollback accompanies the Nginx renderer's independent rollback.
smite_frp_xhttp_get_path() {
    python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" get "$1"
}

# Read-only route visibility; registry state alone is not deployment proof.
smite_frp_xhttp_verify_path() {
    local port="$1" path="$2"
    [ -f "$SMITE_FRP_XHTTP_CONF" ] || return 1
    python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" check "$port" "$path" >/dev/null || return 1
    grep -Fxq "    location = $path {" "$SMITE_FRP_XHTTP_CONF" &&
    grep -Fxq "    location ^~ $path/ {" "$SMITE_FRP_XHTTP_CONF" &&
    grep -Fq "    include $SMITE_FRP_XHTTP_CONF;" "$SMITE_FRP_XHTTP_BACKEND"
}

smite_frp_xhttp_register_path() {
    local port="$1" path="$2" old_path snapshot
    smite_frp_xhttp_enabled || { echo "HOLD: Smite Standard FRP is not prepared."; return 1; }
    [ "$(id -u)" = 0 ] || { echo "HOLD: Root required"; return 1; }
    [ -f "$SMITE_FRP_XHTTP_PATH_HELPER" ] || { echo "HOLD: FRP path helper missing"; return 1; }
    # Never register guessed/unused ports. Smite must have applied the IR FRP
    # server tunnel first; KH controls the matching Xray path separately.
    snapshot="$(mktemp)" || return 1
    chmod 0600 "$snapshot"
    if ! docker exec smite-node cat /var/lib/smite-node/tunnels.json > "$snapshot" ||
       ! python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" contains "$snapshot" "$port"; then
        echo "HOLD: Create/apply the FRP TCP server tunnel in Smite first."
        rm -f "$snapshot"
        return 1
    fi
    rm -f "$snapshot"
    old_path="$(smite_frp_xhttp_get_path "$port")" || return 1
    if [ "$old_path" = "$path" ]; then
        # A matching registry value alone is NOT a published Nginx route.
        # Reconcile and verify the managed locations before reporting success.
        if ! smite_frp_xhttp_sync; then
            echo "HOLD: Saved FRP Path exists but Nginx sync failed." >&2
            return 1
        fi
        if ! smite_frp_xhttp_verify_path "$port" "$path"; then
            echo "HOLD: Saved FRP Path is NOT active in the Nginx include." >&2
            return 1
        fi
        echo "FRP XHTTP path confirmed on IR: $path"
        return 0
    fi
    if ! python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" set "$port" "$path"; then
        return 1
    fi
    if smite_frp_xhttp_sync && smite_frp_xhttp_verify_path "$port" "$path"; then
        echo "FRP XHTTP path ACTIVE on IR: $path"
        return 0
    fi
    echo "HOLD: New FRP path not applied; restoring the previous registry path." >&2
    python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" set "$port" "$old_path" || {
        echo "CRITICAL: FRP registry rollback failed; inspect privately before retry." >&2
        return 1
    }
    smite_frp_xhttp_sync || {
        echo "HOLD: Previous FRP gateway could not be reverified." >&2
        return 1
    }
    return 1
}

# IR: save a validated XHTTP profile BEFORE creating the Smite UI tunnel.
# No Nginx route is published for unapplied ports. Existing applied tunnels
# still use guarded register+sync. Timer publishes saved profile after Apply.
smite_frp_xhttp_stage_path() {
    local port="$1" path="$2" snapshot=""
    smite_frp_xhttp_enabled || { echo "HOLD: Standard FRP gateway missing."; return 2; }
    [ "$(id -u)" -eq 0 ] && [ -f "$SMITE_FRP_XHTTP_PATH_HELPER" ] || {
        echo "HOLD: Root and trusted FRP XHTTP path helper required."; return 2;
    }
    snapshot="$(mktemp)" || return 2
    chmod 0600 "$snapshot"
    if docker exec smite-node test -f /var/lib/smite-node/tunnels.json >/dev/null 2>&1; then
        if ! docker exec smite-node cat /var/lib/smite-node/tunnels.json > "$snapshot"; then
            echo "HOLD: Cannot read applied Smite tunnel state; no profile saved."
            rm -f "$snapshot"
            return 2
        fi
    elif docker exec smite-node test -d /var/lib/smite-node >/dev/null 2>&1; then
        printf '{}\n' > "$snapshot"
    else
        echo "HOLD: Smite node state unavailable; no profile saved."
        rm -f "$snapshot"
        return 2
    fi
    if python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" contains "$snapshot" "$port" >/dev/null 2>&1; then
        rm -f "$snapshot"
        smite_frp_xhttp_register_path "$port" "$path" || return 2
        smite_frp_xhttp_verify_path "$port" "$path" || return 2
        echo "FRP_XHTTP_PATH_ACTIVE=$path"
        return 0
    fi
    if ! python3 -B "$SMITE_FRP_XHTTP_PATH_HELPER" set "$port" "$path" --snapshot "$snapshot"; then
        rm -f "$snapshot"
        echo "HOLD: Pending FRP profile rejected; no active route changed."
        return 2
    fi
    rm -f "$snapshot"
    echo "FRP_XHTTP_PROFILE_SAVED_PENDING_TUNNEL=$port $path"
    echo "No Nginx forwarding was activated. Apply the FRP TCP server tunnel in"
    echo "Smite UI, then let the FRP XHTTP sync timer publish the saved route."
    echo "Run FRP option 3 VERIFY on IR afterwards; only then test a real client."
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
