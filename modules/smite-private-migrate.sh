#!/bin/bash

# U-OPTI - Smite Private Network Migration
# Moves an existing Smite private-mode deployment from provider-owned private
# addresses to the U-OPTI WireGuard overlay in explicit, role-aware phases.
# The provider network is never removed by this helper.

SMITE_PRIVATE_MIGRATE_CORE_STATE="${SMITE_PRIVATE_MIGRATE_CORE_STATE:-/etc/u-opti/smite/state.env}"
SMITE_PRIVATE_MIGRATE_NODE_ENV="${SMITE_PRIVATE_MIGRATE_NODE_ENV:-/opt/smite-node/.env}"
SMITE_PRIVATE_MIGRATE_NODE_COMPOSE="${SMITE_PRIVATE_MIGRATE_NODE_COMPOSE:-/opt/smite-node/docker-compose.yml}"
SMITE_PRIVATE_MIGRATE_PANEL_COMPOSE="${SMITE_PRIVATE_MIGRATE_PANEL_COMPOSE:-/opt/smite/docker-compose.yml}"
SMITE_PRIVATE_MIGRATE_PANEL_DB="${SMITE_PRIVATE_MIGRATE_PANEL_DB:-/opt/smite/panel/data/smite.db}"
SMITE_PRIVATE_MIGRATE_BACKUP_ROOT="${SMITE_PRIVATE_MIGRATE_BACKUP_ROOT:-$SMITE_PRIVATE_STATE_DIR/migration-backups}"
SMITE_PRIVATE_MIGRATE_LAST_BACKUP="${SMITE_PRIVATE_MIGRATE_LAST_BACKUP:-$SMITE_PRIVATE_STATE_DIR/migration-last-backup}"

smite_private_migrate_env_value() {
    local file="$1"
    local key="$2"
    [ -f "$file" ] || return 0
    awk -F= -v key="$key" '$1 == key {print substr($0, index($0, "=") + 1); exit}' "$file"
}

smite_private_migrate_set_key() {
    local file="$1"
    local key="$2"
    local value="$3"

    python3 - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
if not path.is_file():
    raise SystemExit(f"ERROR: Missing file: {path}")
lines = path.read_text().splitlines()
indexes = [i for i, line in enumerate(lines) if line.startswith(key + "=")]
if len(indexes) != 1:
    raise SystemExit(f"ERROR: Expected exactly one {key}= entry in {path}; found {len(indexes)}. Refusing unsafe update.")
lines[indexes[0]] = f"{key}={value}"
tmp = path.with_name(path.name + ".u-opti-migrate.tmp")
tmp.write_text("\n".join(lines) + "\n")
tmp.chmod(path.stat().st_mode & 0o777)
tmp.replace(path)
PY
}

smite_private_migrate_peer_ip() {
    local file=""
    local value=""
    local count=0
    local selected=""

    for file in "$SMITE_PRIVATE_PEERS_DIR"/*.env; do
        [ -f "$file" ] || continue
        value="$(smite_private_migrate_env_value "$file" SMITE_PRIVATE_PEER_IP)"
        [ -n "$value" ] || continue
        selected="$value"
        count=$((count + 1))
    done

    [ "$count" -eq 1 ] || return 1
    printf '%s' "$selected"
}

smite_private_migrate_wait_healthy() {
    local container="$1"
    local elapsed=0
    local state=""
    local health=""

    if declare -F smite_wait_healthy >/dev/null 2>&1; then
        smite_wait_healthy "$container" 90
        return
    fi

    while [ "$elapsed" -lt 90 ]; do
        state="$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
        health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || true)"
        if [ "$state" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "none" ]; }; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    return 1
}

smite_private_migrate_preflight() {
    local role=""
    local local_ip=""
    local panel_ip=""
    local peer_ip=""
    local core_mode=""
    local core_role=""
    local handshake="0"

    [ "$EUID" -eq 0 ] || { echo "ERROR: Root privileges are required."; return 1; }
    command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker is required."; return 1; }
    command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required."; return 1; }
    [ -f "$SMITE_PRIVATE_STATE_FILE" ] || { echo "ERROR: Smite Private Network is not initialized."; return 1; }
    [ -f "$SMITE_PRIVATE_MIGRATE_CORE_STATE" ] || { echo "ERROR: Smite state file is missing."; return 1; }
    [ -f "$SMITE_PRIVATE_MIGRATE_NODE_ENV" ] || { echo "ERROR: Smite node environment is missing."; return 1; }
    [ -f "$SMITE_PRIVATE_MIGRATE_NODE_COMPOSE" ] || { echo "ERROR: Smite node Compose file is missing."; return 1; }

    role="$(smite_private_state_value SMITE_PRIVATE_ROLE)"
    local_ip="$(smite_private_state_value SMITE_PRIVATE_LOCAL_IP)"
    panel_ip="$(smite_private_state_value SMITE_PRIVATE_PANEL_IP)"
    core_mode="$(smite_private_migrate_env_value "$SMITE_PRIVATE_MIGRATE_CORE_STATE" SMITE_CONNECTION_MODE)"
    core_role="$(smite_private_migrate_env_value "$SMITE_PRIVATE_MIGRATE_CORE_STATE" SMITE_ROLE)"

    case "$role" in
        panel)
            [ "$core_role" = "panel-iran" ] || { echo "ERROR: Smite role does not match Panel / Iran."; return 1; }
            peer_ip="$(smite_private_migrate_peer_ip)" || { echo "ERROR: Panel migration currently requires exactly one paired Foreign node."; return 1; }
            ;;
        foreign)
            [ "$core_role" = "foreign" ] || { echo "ERROR: Smite role does not match Foreign node."; return 1; }
            peer_ip="$panel_ip"
            ;;
        *) echo "ERROR: Unsupported Private Network role: ${role:-unknown}"; return 1 ;;
    esac

    [ "$core_mode" = "private" ] || { echo "ERROR: Existing Smite installation is not in private mode."; return 1; }
    smite_private_interface_up || { echo "ERROR: $SMITE_PRIVATE_INTERFACE is not UP."; return 1; }

    handshake="$(smite_private_latest_handshake)"
    if ! [[ "$handshake" =~ ^[0-9]+$ ]] || [ "$handshake" -eq 0 ]; then
        echo "ERROR: WireGuard does not have a completed handshake yet."
        return 1
    fi

    ping -c 1 -W 3 "$peer_ip" >/dev/null 2>&1 || { echo "ERROR: WireGuard peer $peer_ip is not reachable."; return 1; }

    if [ "$role" = "panel" ]; then
        curl -fsS --max-time 5 "http://${peer_ip}:8888/" >/dev/null 2>&1 || { echo "ERROR: Foreign Node API is not reachable over WireGuard."; return 1; }
    else
        curl -fsS --max-time 5 "http://${panel_ip}:8000/" >/dev/null 2>&1 || { echo "ERROR: Panel API is not reachable over WireGuard."; return 1; }
    fi

    return 0
}

smite_private_migrate_create_backup() {
    local role="$1"
    local timestamp=""
    local backup_dir=""

    timestamp="$(date -u +%Y%m%d-%H%M%S)"
    backup_dir="$SMITE_PRIVATE_MIGRATE_BACKUP_ROOT/${role}-${timestamp}"
    install -d -m 0700 "$SMITE_PRIVATE_MIGRATE_BACKUP_ROOT" "$backup_dir" || return 1
    cp -a "$SMITE_PRIVATE_MIGRATE_CORE_STATE" "$backup_dir/state.env" || return 1
    cp -a "$SMITE_PRIVATE_MIGRATE_NODE_ENV" "$backup_dir/node.env" || return 1

    if [ "$role" = "panel" ] && [ -f "$SMITE_PRIVATE_MIGRATE_PANEL_DB" ]; then
        sqlite3 "$SMITE_PRIVATE_MIGRATE_PANEL_DB" ".backup '$backup_dir/smite.db'" || return 1
    fi
    if [ "$role" = "foreign" ] && [ -d /opt/smite-node/config/backhaul ]; then
        cp -a /opt/smite-node/config/backhaul "$backup_dir/backhaul" || return 1
    fi

    printf '%s\n' "$backup_dir" > "$SMITE_PRIVATE_MIGRATE_LAST_BACKUP" || return 1
    chmod 0600 "$SMITE_PRIVATE_MIGRATE_LAST_BACKUP"
    printf '%s' "$backup_dir"
}

smite_private_migrate_restore_backup() {
    local backup_dir="$1"
    [ -d "$backup_dir" ] || return 1
    [ -f "$backup_dir/state.env" ] && cp -a "$backup_dir/state.env" "$SMITE_PRIVATE_MIGRATE_CORE_STATE"
    [ -f "$backup_dir/node.env" ] && cp -a "$backup_dir/node.env" "$SMITE_PRIVATE_MIGRATE_NODE_ENV"
}

smite_private_migrate_recreate_node() {
    docker compose -f "$SMITE_PRIVATE_MIGRATE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node || return 1
    smite_private_migrate_wait_healthy smite-node
}

smite_private_migrate_panel_metadata_value() {
    local node_name="$1"
    local json_key="$2"
    local escaped_name="${node_name//\'/\'\'}"
    sqlite3 "$SMITE_PRIVATE_MIGRATE_PANEL_DB" "SELECT json_extract(metadata, '$.${json_key}') FROM nodes WHERE json_extract(metadata, '$.node_name')='$escaped_name' LIMIT 1;" 2>/dev/null
}

smite_private_migrate_wait_panel_metadata() {
    local node_name="$1"
    local json_key="$2"
    local expected="$3"
    local elapsed=0
    local actual=""

    while [ "$elapsed" -lt 40 ]; do
        actual="$(smite_private_migrate_panel_metadata_value "$node_name" "$json_key")"
        [ "$actual" = "$expected" ] && return 0
        sleep 2
        elapsed=$((elapsed + 2))
    done

    echo "ERROR: Panel metadata did not update as expected."
    echo "Node         : $node_name"
    echo "Metadata key : $json_key"
    echo "Expected     : $expected"
    echo "Actual       : ${actual:-empty}"
    return 1
}

smite_private_migrate_panel_local() {
    local panel_ip=""
    local node_name=""
    local backup_dir=""
    local confirm=""

    panel_ip="$(smite_private_state_value SMITE_PRIVATE_LOCAL_IP)"
    node_name="$(smite_private_migrate_env_value "$SMITE_PRIVATE_MIGRATE_CORE_STATE" SMITE_NODE_NAME)"

    echo "Role                 : Panel / Iran"
    echo "New Panel private IP : $panel_ip"
    echo "Iran node             : $node_name"
    echo
    echo "The provider private network is NOT removed."
    read -rp "Migrate local Smite addressing to WireGuard? [y/N]: " confirm
    case "$confirm" in y|Y|yes|YES) ;; *) echo "Migration cancelled."; return 1 ;; esac

    backup_dir="$(smite_private_migrate_create_backup panel)" || { echo "ERROR: Could not create migration backup."; return 1; }

    if ! smite_private_migrate_set_key "$SMITE_PRIVATE_MIGRATE_CORE_STATE" SMITE_PANEL_PRIVATE_IP "$panel_ip" || \
       ! smite_private_migrate_set_key "$SMITE_PRIVATE_MIGRATE_NODE_ENV" SMITE_BACKHAUL_ADDRESS "$panel_ip" || \
       ! smite_private_migrate_recreate_node || \
       ! smite_private_migrate_wait_panel_metadata "$node_name" backhaul_address "$panel_ip"; then
        echo "Local Panel migration failed. Restoring backup..."
        smite_private_migrate_restore_backup "$backup_dir" || true
        smite_private_migrate_recreate_node >/dev/null 2>&1 || true
        echo "Rollback attempted. Provider private network was never removed."
        return 1
    fi

    echo "Panel / Iran local migration: OK"
    echo "Backup: $backup_dir"
    echo "Panel metadata backhaul_address now uses $panel_ip"
}

smite_private_migrate_foreign_local() {
    local panel_ip=""
    local foreign_ip=""
    local node_name=""
    local backup_dir=""
    local confirm=""
    local elapsed=0

    panel_ip="$(smite_private_state_value SMITE_PRIVATE_PANEL_IP)"
    foreign_ip="$(smite_private_state_value SMITE_PRIVATE_LOCAL_IP)"
    node_name="$(smite_private_migrate_env_value "$SMITE_PRIVATE_MIGRATE_CORE_STATE" SMITE_NODE_NAME)"

    echo "Role                   : Foreign Node"
    echo "New Panel private IP   : $panel_ip"
    echo "New Foreign private IP : $foreign_ip"
    echo "Foreign node           : $node_name"
    echo
    echo "The provider private network is NOT removed."
    read -rp "Migrate local Smite addressing to WireGuard? [y/N]: " confirm
    case "$confirm" in y|Y|yes|YES) ;; *) echo "Migration cancelled."; return 1 ;; esac

    backup_dir="$(smite_private_migrate_create_backup foreign)" || { echo "ERROR: Could not create migration backup."; return 1; }

    if ! smite_private_migrate_set_key "$SMITE_PRIVATE_MIGRATE_CORE_STATE" SMITE_PANEL_PRIVATE_IP "$panel_ip" || \
       ! smite_private_migrate_set_key "$SMITE_PRIVATE_MIGRATE_CORE_STATE" SMITE_FOREIGN_PRIVATE_IP "$foreign_ip" || \
       ! smite_private_migrate_set_key "$SMITE_PRIVATE_MIGRATE_NODE_ENV" PANEL_ADDRESS "${panel_ip}:8000" || \
       ! smite_private_migrate_set_key "$SMITE_PRIVATE_MIGRATE_NODE_ENV" SMITE_CONTROL_ADDRESS "http://${foreign_ip}:8888" || \
       ! smite_private_migrate_recreate_node; then
        echo "Local Foreign migration failed. Restoring backup..."
        smite_private_migrate_restore_backup "$backup_dir" || true
        smite_private_migrate_recreate_node >/dev/null 2>&1 || true
        echo "Rollback attempted. Provider private network was never removed."
        return 1
    fi

    while [ "$elapsed" -lt 40 ]; do
        docker logs --since 90s smite-node 2>&1 | grep -q 'Node registered successfully' && break
        sleep 2
        elapsed=$((elapsed + 2))
    done

    if [ "$elapsed" -ge 40 ]; then
        echo "ERROR: Foreign node registration success was not observed. Restoring backup..."
        smite_private_migrate_restore_backup "$backup_dir" || true
        smite_private_migrate_recreate_node >/dev/null 2>&1 || true
        return 1
    fi

    echo "Foreign local migration: OK"
    echo "Backup: $backup_dir"
    echo "The node registered through Panel address ${panel_ip}:8000"
}

smite_private_migrate_local() {
    local role=""
    clear
    echo "======================================"
    echo "      Migrate Local Smite"
    echo "======================================"
    echo

    if ! smite_private_migrate_preflight; then smite_private_pause; return; fi
    role="$(smite_private_state_value SMITE_PRIVATE_ROLE)"
    case "$role" in
        panel) smite_private_migrate_panel_local ;;
        foreign) smite_private_migrate_foreign_local ;;
    esac
    smite_private_pause
}

smite_private_migrate_finalize_panel() {
    local role=""
    local panel_ip=""
    local foreign_ip=""
    local iran_name=""
    local foreign_name=""
    local iran_meta=""
    local foreign_meta=""
    local confirm=""
    local elapsed=0

    clear
    echo "======================================"
    echo "    Finalize Smite WireGuard Move"
    echo "======================================"
    echo

    if ! smite_private_migrate_preflight; then smite_private_pause; return; fi
    role="$(smite_private_state_value SMITE_PRIVATE_ROLE)"
    [ "$role" = "panel" ] || { echo "ERROR: Finalize/Reapply must run on Panel / Iran."; smite_private_pause; return; }
    [ -f "$SMITE_PRIVATE_MIGRATE_PANEL_DB" ] || { echo "ERROR: Panel database is missing."; smite_private_pause; return; }
    [ -f "$SMITE_PRIVATE_MIGRATE_PANEL_COMPOSE" ] || { echo "ERROR: Panel Compose file is missing."; smite_private_pause; return; }

    panel_ip="$(smite_private_state_value SMITE_PRIVATE_LOCAL_IP)"
    foreign_ip="$(smite_private_migrate_peer_ip)" || { echo "ERROR: Expected exactly one Foreign peer."; smite_private_pause; return; }
    iran_name="$(smite_private_migrate_env_value "$SMITE_PRIVATE_MIGRATE_CORE_STATE" SMITE_NODE_NAME)"
    foreign_name="$(sqlite3 "$SMITE_PRIVATE_MIGRATE_PANEL_DB" "SELECT json_extract(metadata, '$.node_name') FROM nodes WHERE json_extract(metadata, '$.role')='foreign' AND status='active';" 2>/dev/null)"

    if [ -z "$foreign_name" ] || [ "$(printf '%s\n' "$foreign_name" | sed '/^$/d' | wc -l)" -ne 1 ]; then
        echo "ERROR: Finalize currently requires exactly one active Foreign Smite node."
        smite_private_pause
        return
    fi

    iran_meta="$(smite_private_migrate_panel_metadata_value "$iran_name" backhaul_address)"
    foreign_meta="$(smite_private_migrate_panel_metadata_value "$foreign_name" control_address)"

    echo "Iran node metadata    : ${iran_meta:-empty}"
    echo "Expected              : $panel_ip"
    echo "Foreign node metadata : ${foreign_meta:-empty}"
    echo "Expected              : http://${foreign_ip}:8888"
    echo

    if [ "$iran_meta" != "$panel_ip" ] || [ "$foreign_meta" != "http://${foreign_ip}:8888" ]; then
        echo "ERROR: Both nodes have not completed local migration yet."
        echo "Run Migrate Local Smite on IR and KH before Finalize."
        smite_private_pause
        return
    fi

    echo "Finalize restarts the Smite Panel so startup reapply rebuilds active tunnels"
    echo "using the new node metadata. Provider private networking remains connected."
    echo
    read -rp "Finalize and reapply active tunnels? [y/N]: " confirm
    case "$confirm" in y|Y|yes|YES) ;; *) echo "Finalize cancelled."; smite_private_pause; return ;; esac

    docker compose -f "$SMITE_PRIVATE_MIGRATE_PANEL_COMPOSE" up -d --no-build --force-recreate smite-panel || { echo "ERROR: Failed to recreate Smite Panel."; smite_private_pause; return; }
    smite_private_migrate_wait_healthy smite-panel || { echo "ERROR: Smite Panel did not become healthy."; smite_private_pause; return; }

    echo "Waiting for active Backhaul to reapply over WireGuard..."
    while [ "$elapsed" -lt 60 ]; do
        if ss -nt state established 2>/dev/null | awk -v peer="$foreign_ip" '$4 ~ /:3080$/ && index($5, peer ":") == 1 {found=1} END {exit(found ? 0 : 1)}'; then
            echo "Backhaul WireGuard path: ESTABLISHED"
            echo "Foreign source          : $foreign_ip"
            echo "Iran destination        : $panel_ip:3080"
            echo "Provider private network: Still connected / unchanged"
            smite_private_pause
            return
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    echo "WARNING: New Backhaul connection was not observed within 60 seconds."
    echo "Do NOT remove the provider private network."
    smite_private_pause
}

smite_private_migrate_status() {
    local role=""
    local local_ip=""
    local panel_ip=""
    local peer_ip=""

    clear
    echo "======================================"
    echo "      Smite Migration Status"
    echo "======================================"
    echo

    role="$(smite_private_state_value SMITE_PRIVATE_ROLE)"
    local_ip="$(smite_private_state_value SMITE_PRIVATE_LOCAL_IP)"
    panel_ip="$(smite_private_state_value SMITE_PRIVATE_PANEL_IP)"

    echo "Private role         : ${role:-Unknown}"
    echo "WireGuard local IP   : ${local_ip:-Unknown}"
    echo "WireGuard panel IP   : ${panel_ip:-Unknown}"
    echo "Smite state panel IP : $(smite_private_migrate_env_value "$SMITE_PRIVATE_MIGRATE_CORE_STATE" SMITE_PANEL_PRIVATE_IP)"
    echo "Smite state foreign  : $(smite_private_migrate_env_value "$SMITE_PRIVATE_MIGRATE_CORE_STATE" SMITE_FOREIGN_PRIVATE_IP)"
    echo "PANEL_ADDRESS        : $(smite_private_migrate_env_value "$SMITE_PRIVATE_MIGRATE_NODE_ENV" PANEL_ADDRESS)"
    echo "CONTROL_ADDRESS      : $(smite_private_migrate_env_value "$SMITE_PRIVATE_MIGRATE_NODE_ENV" SMITE_CONTROL_ADDRESS)"
    echo "BACKHAUL_ADDRESS     : $(smite_private_migrate_env_value "$SMITE_PRIVATE_MIGRATE_NODE_ENV" SMITE_BACKHAUL_ADDRESS)"

    if [ "$role" = "panel" ] && [ -f "$SMITE_PRIVATE_MIGRATE_PANEL_DB" ]; then
        echo
        echo "Panel DB metadata:"
        sqlite3 "$SMITE_PRIVATE_MIGRATE_PANEL_DB" <<'SQL' 2>/dev/null
.headers on
.mode column
SELECT json_extract(metadata,'$.node_name') AS node_name,
       json_extract(metadata,'$.role') AS role,
       json_extract(metadata,'$.control_address') AS control_address,
       json_extract(metadata,'$.backhaul_address') AS backhaul_address
FROM nodes;
SQL
        peer_ip="$(smite_private_migrate_peer_ip 2>/dev/null || true)"
        if [ -n "$peer_ip" ]; then
            echo
            if ss -nt state established 2>/dev/null | awk -v peer="$peer_ip" '$4 ~ /:3080$/ && index($5, peer ":") == 1 {found=1} END {exit(found ? 0 : 1)}'; then
                echo "Backhaul over WireGuard: ESTABLISHED"
            else
                echo "Backhaul over WireGuard: Not observed"
            fi
        fi
    fi

    smite_private_pause
}

smite_private_migrate_rollback_local() {
    local backup_dir=""
    local confirm=""

    clear
    echo "======================================"
    echo "     Roll Back Local Migration"
    echo "======================================"
    echo

    [ -f "$SMITE_PRIVATE_MIGRATE_LAST_BACKUP" ] || { echo "No migration backup marker was found."; smite_private_pause; return; }
    backup_dir="$(cat "$SMITE_PRIVATE_MIGRATE_LAST_BACKUP" 2>/dev/null)"
    [ -n "$backup_dir" ] && [ -d "$backup_dir" ] || { echo "ERROR: Last migration backup is unavailable."; smite_private_pause; return; }

    echo "Backup: $backup_dir"
    echo "This restores local Smite state and node .env, then recreates smite-node."
    echo "It does NOT change WireGuard or provider networking."
    read -rp "Restore this backup? [y/N]: " confirm
    case "$confirm" in y|Y|yes|YES) ;; *) echo "Rollback cancelled."; smite_private_pause; return ;; esac

    if ! smite_private_migrate_restore_backup "$backup_dir" || ! smite_private_migrate_recreate_node; then
        echo "ERROR: Rollback could not be completed cleanly."
        smite_private_pause
        return
    fi

    echo "Local Smite rollback: OK"
    echo "Provider private network and WireGuard were unchanged."
    smite_private_pause
}

show_smite_private_migration_menu() {
    while true; do
        clear
        echo "======================================"
        echo "       Smite Network Migration"
        echo "======================================"
        echo
        echo "1) Migration Status"
        echo "2) Migrate Local Smite to WireGuard"
        echo "3) Finalize / Reapply Backhaul (Panel)"
        echo "4) Roll Back Local Smite Migration"
        echo
        echo "0) Back"
        echo
        read -rp "Please enter your selection [0-4]: " SMITE_PRIVATE_MIGRATE_CHOICE
        case "$SMITE_PRIVATE_MIGRATE_CHOICE" in
            1) smite_private_migrate_status ;;
            2) smite_private_migrate_local ;;
            3) smite_private_migrate_finalize_panel ;;
            4) smite_private_migrate_rollback_local ;;
            0) break ;;
            *) echo; echo "Invalid selection!"; sleep 2 ;;
        esac
    done
}
