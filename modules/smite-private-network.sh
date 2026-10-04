#!/bin/bash

# U-OPTI - Smite Provider-Independent Private Network entry point
#
# The supported provider-independent transport is EasyTier over WSS/TCP 443.
# Keep this compatibility entry point so Docker -> Smite -> Private Network
# remains stable for clean installs and upgrades from older U-OPTI releases.
#
# Gateway-first test flow:
# In Private Network mode the Smite Panel gateway may be prepared before the
# first Backhaul tunnel exists. Public exposure is unchanged: Nginx owns TCP
# 443 and the future Backhaul data listener stays on loopback 127.0.0.1:9443.

SMITE_PRIVATE_MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SMITE_PRIVATE_EASYTIER_MODULE="$SMITE_PRIVATE_MODULE_DIR/smite-easytier.sh"

if [ ! -f "$SMITE_PRIVATE_EASYTIER_MODULE" ]; then
    SMITE_PRIVATE_EASYTIER_ERROR="EasyTier Private Network module is missing: $SMITE_PRIVATE_EASYTIER_MODULE"
elif ! bash -n "$SMITE_PRIVATE_EASYTIER_MODULE" >/dev/null 2>&1; then
    SMITE_PRIVATE_EASYTIER_ERROR="EasyTier Private Network module failed Bash syntax validation."
else
    # shellcheck disable=SC1090
    source "$SMITE_PRIVATE_EASYTIER_MODULE"
fi

# ---------------------------------------------------------------------------
# Gateway-first compatibility layer (test branch)
# ---------------------------------------------------------------------------
# smite-gateway.sh is sourced before this file by docker.sh. Preserve the
# validated v0.15.0 implementations under private names, then override only
# the small pieces required to support:
#
#   EasyTier -> Smite nodes -> 443 Gateway -> first Backhaul tunnel
#
# This keeps the stable gateway transaction/rollback code intact and avoids
# opening any additional public ports.
# ---------------------------------------------------------------------------

smite_private_clone_function() {
    local source_name="$1"
    local target_name="$2"
    local definition=""

    declare -F "$source_name" >/dev/null 2>&1 || return 1
    declare -F "$target_name" >/dev/null 2>&1 && return 0

    definition="$(declare -f "$source_name")" || return 1
    definition="${definition/$source_name/$target_name}"
    eval "$definition"
}

smite_private_clone_function \
    smite_gateway_private_backhaul_listener_ready \
    smite_private_gateway_listener_ready_actual || true
smite_private_clone_function \
    smite_gateway_prepare_private_backhaul \
    smite_private_gateway_prepare_backhaul_legacy || true
smite_private_clone_function \
    smite_gateway_write_stream \
    smite_private_gateway_write_stream_legacy || true
smite_private_clone_function \
    smite_gateway_switch_local_node_to_443 \
    smite_private_gateway_switch_node_legacy || true
smite_private_clone_function \
    smite_gateway_rollback_transaction \
    smite_private_gateway_rollback_legacy || true

SMITE_PRIVATE_GATEWAY_ALLOW_EMPTY_BACKHAUL=0
SMITE_PRIVATE_GATEWAY_MARKER_CREATED=0
SMITE_PRIVATE_GATEWAY_NODE_MARKER="${SMITE_PRIVATE_GATEWAY_NODE_MARKER:-${SMITE_NODE_DIR:-/opt/smite-node}/config/u-opti-gateway.env}"
SMITE_PRIVATE_GATEWAY_NODE_OVERLAY="${SMITE_PRIVATE_GATEWAY_NODE_OVERLAY:-/opt/u-opti-smite/node/core_adapters.py}"

smite_private_gateway_active_backhaul_count() {
    local db="${SMITE_GATEWAY_DB:-${SMITE_PANEL_DIR:-/opt/smite}/panel/data/smite.db}"

    [ -f "$db" ] || {
        printf '0'
        return 0
    }

    sqlite3 "$db" \
        "SELECT count(*) FROM tunnels WHERE core='backhaul' AND status='active';" \
        2>/dev/null | head -n1
}

smite_private_gateway_install_node_hook() {
    local overlay="$SMITE_PRIVATE_GATEWAY_NODE_OVERLAY"

    [ -f "$overlay" ] || {
        echo "ERROR: Smite node compatibility overlay was not found:"
        echo "$overlay"
        return 1
    }

    python3 - "$overlay" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
marker = "U-OPTI private gateway runtime remap"

if marker in text:
    print("Smite node Backhaul gateway hook: already installed")
    raise SystemExit(0)

old = '''            logger.info(f"Backhaul {mode} tunnel {tunnel_id}: processed ports: {ports} (count: {len(ports)})")
            
            server_config: Dict[str, Any] = {
'''

new = '''            logger.info(f"Backhaul {mode} tunnel {tunnel_id}: processed ports: {ports} (count: {len(ports)})")

            # U-OPTI private gateway runtime remap.
            # Keep the logical Smite/Public port as 443 in the Panel/UI, but
            # when the U-OPTI shared 443 gateway is active on the Iran node,
            # bind Backhaul data to loopback instead. Nginx remains the only
            # public owner of TCP/443 and forwards RAW/default traffic here.
            gateway_marker = Path("/etc/smite-node/u-opti-gateway.env")
            if gateway_marker.exists():
                gateway_data_port = None
                try:
                    for raw_line in gateway_marker.read_text(encoding="utf-8").splitlines():
                        key, sep, value = raw_line.partition("=")
                        if key.strip() == "U_OPTI_SMITE_GATEWAY_PRIVATE_DATA_PORT" and sep:
                            candidate = value.strip()
                            if candidate.isdigit() and 1 <= int(candidate) <= 65535:
                                gateway_data_port = int(candidate)
                            break
                except Exception as marker_error:
                    logger.warning(f"Could not read U-OPTI gateway marker: {marker_error}")

                if gateway_data_port:
                    remapped_ports = []
                    remapped = False
                    for item in ports:
                        entry = str(item)
                        if "=" in entry:
                            left, right = entry.split("=", 1)
                            listen_port = left.rsplit(":", 1)[-1] if ":" in left else left
                            if listen_port == "443":
                                entry = f"127.0.0.1:{gateway_data_port}={right}"
                                remapped = True
                        elif entry == "443":
                            target_host = spec.get("target_host", "127.0.0.1")
                            target_port = spec.get("target_port") or 443
                            entry = f"127.0.0.1:{gateway_data_port}={target_host}:{target_port}"
                            remapped = True
                        remapped_ports.append(entry)

                    if remapped:
                        ports = remapped_ports
                        logger.info(
                            f"U-OPTI private gateway remapped Backhaul public 443 "
                            f"to 127.0.0.1:{gateway_data_port}: {ports}"
                        )
            
            server_config: Dict[str, Any] = {
'''

count = text.count(old)
if count != 1:
    raise SystemExit(
        f"ERROR: Expected exactly one Backhaul adapter insertion point; found {count}. Refusing unsafe patch."
    )

updated = text.replace(old, new, 1)
compile(updated, str(path), "exec")
path.write_text(updated)
print("Smite node Backhaul gateway hook: installed")
PY
}

smite_private_gateway_write_marker() {
    local marker="$SMITE_PRIVATE_GATEWAY_NODE_MARKER"
    local data_port="${SMITE_GATEWAY_PRIVATE_DATA_PORT:-9443}"

    mkdir -p "$(dirname "$marker")" || return 1

    if [ -f "$marker" ]; then
        if grep -qx "U_OPTI_SMITE_GATEWAY_PRIVATE_DATA_PORT=$data_port" "$marker"; then
            echo "Smite node gateway marker: already configured"
            SMITE_PRIVATE_GATEWAY_MARKER_CREATED=0
            return 0
        fi

        echo "ERROR: Existing Smite gateway marker has unexpected content:"
        echo "$marker"
        return 1
    fi

    printf 'U_OPTI_SMITE_GATEWAY_PRIVATE_DATA_PORT=%s\n' "$data_port" > "$marker" || return 1
    chmod 0600 "$marker" || return 1
    SMITE_PRIVATE_GATEWAY_MARKER_CREATED=1
    echo "Smite node gateway marker: $marker"
}

smite_private_gateway_remove_created_marker() {
    [ "$SMITE_PRIVATE_GATEWAY_MARKER_CREATED" = "1" ] || return 0

    rm -f "$SMITE_PRIVATE_GATEWAY_NODE_MARKER"
    SMITE_PRIVATE_GATEWAY_MARKER_CREATED=0

    if docker inspect smite-node >/dev/null 2>&1 && [ -f "${SMITE_NODE_COMPOSE:-/opt/smite-node/docker-compose.yml}" ]; then
        docker compose -f "${SMITE_NODE_COMPOSE:-/opt/smite-node/docker-compose.yml}" \
            up -d --no-build --force-recreate smite-node >/dev/null 2>&1 || true
    fi
}

smite_private_gateway_activate_node_runtime() {
    local compose_file="${SMITE_NODE_COMPOSE:-/opt/smite-node/docker-compose.yml}"

    smite_private_gateway_install_node_hook || return 1
    smite_private_gateway_write_marker || return 1

    [ -f "$compose_file" ] || {
        echo "ERROR: Local Smite node compose file was not found:"
        echo "$compose_file"
        smite_private_gateway_remove_created_marker
        return 1
    }

    echo "Reloading Iran Smite Node with private 443 runtime mapping..."
    if ! docker compose -f "$compose_file" up -d --no-build --force-recreate smite-node; then
        echo "ERROR: Failed to recreate smite-node with the private gateway hook."
        smite_private_gateway_remove_created_marker
        return 1
    fi

    if declare -F smite_gateway_wait_healthy >/dev/null 2>&1; then
        if ! smite_gateway_wait_healthy smite-node 90; then
            echo "ERROR: smite-node did not become healthy with the private gateway hook."
            smite_private_gateway_remove_created_marker
            return 1
        fi
    fi

    echo "Private Backhaul runtime: logical 443 -> 127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT:-9443}"
    return 0
}

# Preserve the real listener check for status/repair logic. Only the legacy
# stream writer gets a temporary "ready" result while there is no Backhaul
# yet, allowing the Panel gateway to come online first.
smite_gateway_private_backhaul_listener_ready() {
    if declare -F smite_private_gateway_listener_ready_actual >/dev/null 2>&1 && \
       smite_private_gateway_listener_ready_actual; then
        return 0
    fi

    if [ "${SMITE_PRIVATE_GATEWAY_ALLOW_EMPTY_BACKHAUL:-0}" = "1" ] && \
       [ "$(smite_gateway_connection_mode)" = "private" ] && \
       [ "$(smite_private_gateway_active_backhaul_count)" = "0" ]; then
        return 0
    fi

    return 1
}

smite_gateway_prepare_private_backhaul() {
    local count="0"

    [ "$(smite_gateway_connection_mode)" = "private" ] || return 0

    count="$(smite_private_gateway_active_backhaul_count)"
    [[ "$count" =~ ^[0-9]+$ ]] || count=0

    if [ "$count" -eq 0 ]; then
        SMITE_GATEWAY_PRIVATE_DB_BACKUP=""
        SMITE_GATEWAY_PRIVATE_BACKHAUL_CHANGED=0
        echo "Private Mode: no active Backhaul tunnel exists yet."
        echo "Preparing Panel HTTPS/443 first; Backhaul will attach to loopback ${SMITE_GATEWAY_PRIVATE_DATA_PORT:-9443} when created."
        return 0
    fi

    # Gateway-first installations keep logical port 443 in Smite while the
    # Iran node runtime maps it to loopback 9443. If that listener already
    # exists, no database migration is required.
    if [ -f "$SMITE_PRIVATE_GATEWAY_NODE_MARKER" ] && \
       declare -F smite_private_gateway_listener_ready_actual >/dev/null 2>&1 && \
       smite_private_gateway_listener_ready_actual; then
        SMITE_GATEWAY_PRIVATE_DB_BACKUP=""
        SMITE_GATEWAY_PRIVATE_BACKHAUL_CHANGED=0
        echo "Private Mode Backhaul runtime is already attached to 127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT:-9443}."
        return 0
    fi

    if declare -F smite_private_gateway_prepare_backhaul_legacy >/dev/null 2>&1; then
        smite_private_gateway_prepare_backhaul_legacy
        return $?
    fi

    echo "ERROR: Legacy Private Backhaul preparation function is unavailable."
    return 1
}

smite_gateway_write_stream() {
    local rc=0

    if [ "$(smite_gateway_connection_mode)" = "private" ] && \
       [ "$(smite_private_gateway_active_backhaul_count)" = "0" ]; then
        SMITE_PRIVATE_GATEWAY_ALLOW_EMPTY_BACKHAUL=1
        echo "Private Mode RAW backend will be reserved at 127.0.0.1:${SMITE_GATEWAY_PRIVATE_DATA_PORT:-9443}."
        echo "No Backhaul listener is required until the first tunnel is created."
    fi

    if declare -F smite_private_gateway_write_stream_legacy >/dev/null 2>&1; then
        smite_private_gateway_write_stream_legacy "$@"
        rc=$?
    else
        echo "ERROR: Legacy Smite gateway stream writer is unavailable."
        rc=1
    fi

    SMITE_PRIVATE_GATEWAY_ALLOW_EMPTY_BACKHAUL=0
    return "$rc"
}

smite_gateway_switch_local_node_to_443() {
    if [ "$(smite_gateway_connection_mode)" = "private" ]; then
        local current_panel_address=""

        if [ -f "${SMITE_NODE_DIR:-/opt/smite-node}/.env" ]; then
            current_panel_address="$(awk -F= '$1 == "PANEL_ADDRESS" {print substr($0, index($0,"=")+1); exit}' "${SMITE_NODE_DIR:-/opt/smite-node}/.env")"
        fi

        echo "Private Mode: keeping Iran node PANEL_ADDRESS=${current_panel_address:-unchanged}"
        smite_private_gateway_activate_node_runtime
        return $?
    fi

    if declare -F smite_private_gateway_switch_node_legacy >/dev/null 2>&1; then
        smite_private_gateway_switch_node_legacy "$@"
        return $?
    fi

    echo "ERROR: Legacy Smite node gateway switch function is unavailable."
    return 1
}

smite_gateway_rollback_transaction() {
    local rc=0

    if declare -F smite_private_gateway_rollback_legacy >/dev/null 2>&1; then
        smite_private_gateway_rollback_legacy "$@" || rc=$?
    else
        echo "WARNING: Legacy Smite gateway rollback function is unavailable."
        rc=1
    fi

    smite_private_gateway_remove_created_marker || true
    return "$rc"
}

show_smite_private_network_menu() {
    local previous_umask
    previous_umask="$(umask)"

    if declare -F show_smite_easytier_menu >/dev/null 2>&1; then
        show_smite_easytier_menu
        umask "$previous_umask"
        return
    fi

    clear
    echo "======================================"
    echo "      Smite Private Network"
    echo "======================================"
    echo
    echo "EasyTier Private Network is not available."
    if [ -n "${SMITE_PRIVATE_EASYTIER_ERROR:-}" ]; then
        echo "$SMITE_PRIVATE_EASYTIER_ERROR"
    fi
    echo
    read -rp "Press Enter to return..."
    umask "$previous_umask"
}
