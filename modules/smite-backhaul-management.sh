#!/usr/bin/env bash
# Standard Backhaul: candidate PREPARE / VERIFY / DISCARD ONLY, not an installer.
SMITE_BH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SMITE_BH_ROOT="${SMITE_BH_STAGE_ROOT:-/var/lib/u-opti/smite-backhaul/staging}"
SMITE_BH_STATE="${SMITE_BH_STATE_FILE:-/etc/u-opti/smite/state.env}"
SMITE_BH_OVERLAYS="${SMITE_BH_OVERLAY_ROOT:-/opt/u-opti-smite}"
SMITE_BH_IMAGE='ghcr.io/zzedix/smite-node@sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e'

# Optional additive beginner wizard. Existing Private/FRP menus remain unchanged.
if [ -s "$SMITE_BH_DIR/smite-tunnel-wizard.sh" ]; then
    source "$SMITE_BH_DIR/smite-tunnel-wizard.sh"
fi

smite_bh_role() {
    local mode role
    [ -f "$SMITE_BH_STATE" ] || { echo "ERROR: Smite state missing" >&2; return 1; }
    mode="$(sed -n 's/^SMITE_CONNECTION_MODE=//p' "$SMITE_BH_STATE" | head -n 1)"
    role="$(sed -n 's/^SMITE_ROLE=//p' "$SMITE_BH_STATE" | head -n 1)"
    [ "$mode" = standard ] || { echo "ERROR: Standard mode required" >&2; return 1; }
    case "$role" in
        panel-iran) echo ir ;;
        foreign) echo kh ;;
        *) echo "ERROR: Unsupported Smite role" >&2; return 1 ;;
    esac
}

smite_bh_safe_root() {
    [[ "$SMITE_BH_ROOT" = /* ]] && [ "$SMITE_BH_ROOT" != / ] &&
        [ ! -L "$SMITE_BH_ROOT" ] && [ ! -L "$(dirname "$SMITE_BH_ROOT")" ]
}

smite_bh_stage_path() {
    local id="${1:-}"
    [[ "$id" =~ ^prepare-[0-9]{8}-[0-9]{6}-[[:alnum:]]{6}$ ]] || {
        echo "ERROR: Invalid preparation ID" >&2; return 1; }
    smite_bh_safe_root || { echo "ERROR: Unsafe stage root" >&2; return 1; }
    printf '%s/%s\n' "$SMITE_BH_ROOT" "$id"
}

smite_bh_preflight() {
    local role="$1" f mount version
    [ "$(id -u)" = 0 ] || { echo "ERROR: Root required" >&2; return 1; }
    for f in docker python3 sha256sum nginx ss; do
        command -v "$f" >/dev/null 2>&1 || { echo "ERROR: Missing $f" >&2; return 1; }
    done
    for f in smite-backhaul-spec.py smite-backhaul-standard.sh smite-backhaul-node-patch.py smite-backhaul-panel-patch.py; do
        [ -s "$SMITE_BH_DIR/$f" ] || { echo "ERROR: Missing Backhaul module $f" >&2; return 1; }
    done
    [ "$(docker inspect smite-node --format '{{.Config.Image}}' 2>/dev/null)" = "$SMITE_BH_IMAGE" ] ||
        { echo "ERROR: Unsupported Smite Node image" >&2; return 1; }
    [ "$(docker inspect smite-node --format '{{.State.Running}}' 2>/dev/null)" = true ] ||
        { echo "ERROR: Smite Node not running" >&2; return 1; }
    version="$(docker exec smite-node backhaul -v 2>/dev/null)" || return 1
    [ "$version" = v0.7.2 ] || { echo "ERROR: Backhaul must be v0.7.2" >&2; return 1; }
    mount="$(docker inspect smite-node --format '{{range .Mounts}}{{if eq .Destination "/app/app/core_adapters.py"}}{{.Source}}{{end}}{{end}}' 2>/dev/null)" || return 1
    [ "$mount" = "$SMITE_BH_OVERLAYS/node/core_adapters.py" ] && [ -s "$mount" ] ||
        { echo "ERROR: Unexpected Node adapter mount" >&2; return 1; }
    # This preflight is PREPARE-ONLY. Active Smite Backhaul clients are
    # compatible with staging copied files but NOT evidence that live
    # activation is safe. Never stop or change the existing processes.
    local active_processes existing_configs
    active_processes="$(pgrep -xc backhaul 2>/dev/null)" || active_processes=0
    [[ "$active_processes" =~ ^[0-9]+$ ]] || {
        echo "ERROR: Cannot inspect Backhaul processes" >&2; return 1; }
    existing_configs="$(docker exec smite-node sh -c '
        if [ -d /etc/smite-node/backhaul ]; then
            find /etc/smite-node/backhaul -maxdepth 1 -type f -name "*.toml" | wc -l
        else
            printf "0\n"
        fi
    ' 2>/dev/null)" || { echo "ERROR: Cannot inventory Backhaul TOMLs" >&2; return 1; }
    existing_configs="$(printf "%s" "$existing_configs" | tr -d "[:space:]")"
    [[ "$existing_configs" =~ ^[0-9]+$ ]] || {
        echo "ERROR: Invalid Backhaul TOML inventory" >&2; return 1; }
    if [ "$active_processes" -gt 0 ] || [ "$existing_configs" -gt 0 ]; then
        echo "WARNING: Existing Backhaul processes=$active_processes, configs=$existing_configs."
        echo "WARNING: Prepare-only allowed. Activation/rollback requires separate review."
    fi
    nginx -t >/dev/null 2>&1 || { echo "ERROR: Existing Nginx is not valid" >&2; return 1; }
    if [ "$role" = ir ]; then
        [ "$(docker inspect smite-panel --format '{{.State.Running}}' 2>/dev/null)" = true ] || {
            echo "ERROR: Panel not running" >&2; return 1; }
        for f in main.py node_client.py tunnels.py; do
            [ -s "$SMITE_BH_OVERLAYS/panel/$f" ] || {
                echo "ERROR: Missing Panel overlay $f" >&2; return 1; }
        done
        for f in 3080 56053; do
            if ss -lntH | grep -Eq ":$f[[:space:]]"; then
                echo "ERROR: IR reserved port $f in use" >&2; return 1
            fi
        done
        ss -lntH | grep -Eq '127\.0\.0\.1:7000[[:space:]]' || {
            echo "ERROR: FRP controller unexpectedly absent" >&2; return 1; }
    elif [ "$role" = kh ]; then
        ! ss -lntH | grep -Eq ':13080[[:space:]]' || {
            echo "ERROR: KH bridge port already in use" >&2; return 1; }
        ss -lntH | grep -Eq '127\.0\.0\.1:56053[[:space:]]' || {
            echo "ERROR: KH Xray port missing" >&2; return 1; }
    else
        echo "ERROR: Invalid role" >&2; return 1
    fi
    echo "Prepare-only preflight PASS ($role). No active services modified."
}

smite_bh_verify_stage() {
    local stage
    stage="$(smite_bh_stage_path "${1:-}")" || return 1
    [ -d "$stage" ] && [ ! -L "$stage" ] && [ -s "$stage/SHA256SUMS" ] || {
        echo "ERROR: Missing or incomplete stage" >&2; return 1; }
    (cd "$stage" && sha256sum -c SHA256SUMS) || {
        echo "ERROR: Candidate tampered or corrupted" >&2; return 1; }
    echo "VERIFIED STAGING ONLY. No live mounts or routes installed."
}

smite_bh_prepare() {
    local role="$1" stage f
    smite_bh_preflight "$role" || return 1
    smite_bh_safe_root || { echo "ERROR: Unsafe staging root" >&2; return 1; }
    umask 077
    mkdir -p -m 0700 "$SMITE_BH_ROOT" || return 1
    chmod 0700 "$SMITE_BH_ROOT" || return 1
    stage="$(mktemp -d "$SMITE_BH_ROOT/prepare-$(date +%Y%m%d-%H%M%S)-XXXXXX")" || return 1
    mkdir -p "$stage/original/node" "$stage/candidate/node" "$stage/candidate/nginx" ||
        { rm -rf -- "$stage"; return 1; }
    cp -- "$SMITE_BH_OVERLAYS/node/core_adapters.py" "$stage/original/node/core_adapters.py" ||
        { rm -rf -- "$stage"; return 1; }
    python3 "$SMITE_BH_DIR/smite-backhaul-node-patch.py" \
        "$stage/original/node/core_adapters.py" "$stage/candidate/node/core_adapters.py" ||
        { rm -rf -- "$stage"; return 1; }
    cp -- "$SMITE_BH_DIR/smite-backhaul-spec.py" "$stage/candidate/node/uopti_backhaul_standard.py" ||
        { rm -rf -- "$stage"; return 1; }
    if [ "$role" = ir ]; then
        mkdir -p "$stage/original/panel" "$stage/candidate/panel" || { rm -rf -- "$stage"; return 1; }
        for f in main.py node_client.py tunnels.py; do
            cp -- "$SMITE_BH_OVERLAYS/panel/$f" "$stage/original/panel/$f" ||
                { rm -rf -- "$stage"; return 1; }
        done
        python3 "$SMITE_BH_DIR/smite-backhaul-panel-patch.py" "$stage/original/panel" \
            "$stage/candidate/panel" || { rm -rf -- "$stage"; return 1; }
        cp -- "$SMITE_BH_DIR/smite-backhaul-spec.py" \
            "$stage/candidate/panel/uopti_backhaul_standard.py" || \
            { rm -rf -- "$stage"; return 1; }
        bash "$SMITE_BH_DIR/smite-backhaul-standard.sh" --render-ir-control 3080 \
            > "$stage/candidate/nginx/ir-control.conf" || { rm -rf -- "$stage"; return 1; }
        bash "$SMITE_BH_DIR/smite-backhaul-standard.sh" --render-ir-xhttp 56053 /56053/www kh.kolbe1.ir \
            > "$stage/candidate/nginx/ir-xhttp.conf" || { rm -rf -- "$stage"; return 1; }
    else
        bash "$SMITE_BH_DIR/smite-backhaul-standard.sh" --render-kh-bridge ir.kolbe1.ir 13080 \
            > "$stage/candidate/nginx/kh-bridge.conf" || { rm -rf -- "$stage"; return 1; }
    fi
    if ! python3 - "$stage/candidate" <<'PY'
import ast
from pathlib import Path
import sys
for file in Path(sys.argv[1]).rglob("*.py"):
    ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
print("Python overlay syntax OK")
PY
    then rm -rf -- "$stage"; return 1; fi
    echo "$role" > "$stage/ROLE"
    cat > "$stage/NOT-INSTALLED.txt" <<'EOF'
Candidate only. Not installed, mounted, routed or activated.
Do not manually mount these until an audited activation/rollback procedure exists.
EOF
    (cd "$stage" && find original candidate -type f -print0 | sort -z |
        xargs -0 sha256sum > SHA256SUMS) || { rm -rf -- "$stage"; return 1; }
    smite_bh_verify_stage "${stage##*/}" || { rm -rf -- "$stage"; return 1; }
    echo "PREPARED: ${stage##*/} ($role). Live FRP, Nginx, Smite and Xray unchanged."
}

smite_bh_discard_unused() {
    local stage
    [ "$(id -u)" = 0 ] || { echo "ERROR: Root required" >&2; return 1; }
    stage="$(smite_bh_stage_path "${1:-}")" || return 1
    [ -d "$stage" ] && [ ! -L "$stage" ] && [ -f "$stage/NOT-INSTALLED.txt" ] || {
        echo "ERROR: Unrecognized preparation ID" >&2; return 1; }
    rm -rf -- "$stage" || return 1
    echo "Discarded unused candidate only. No live rollback was needed."
}

smite_bh_status() {
    local role
    role="$(smite_bh_role)" || return 1
    echo "Backhaul Standard: candidate preparation only ($role); NOT activated."
    echo "Relevant listeners:"
    ss -lntp 2>/dev/null | grep -E ':(443|7000|18476|3080|13080|56053)[[:space:]]' || true
    echo "Candidate IDs:"
    if smite_bh_safe_root && [ -d "$SMITE_BH_ROOT" ]; then
        find "$SMITE_BH_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'prepare-*' -printf '%f\n'
    fi
}

smite_bh_management_menu() {
    local choice role id answer
    while true; do
        clear
        echo "========== Standard Backhaul =========="
        echo "PREPARATION ONLY - NO LIVE ACTIVATION"
        echo "1) Read-only status"
        echo "2) Preflight"
        echo "3) Prepare candidate overlays and Nginx snippets"
        echo "4) Verify staged candidate ID"
        echo "5) Discard UNUSED candidate ID"
        echo "0) Back"
        read -rp "Choose [0-5]: " choice
        case "$choice" in
            1) smite_bh_status ;;
            2) role="$(smite_bh_role)" && smite_bh_preflight "$role" ;;
            3) role="$(smite_bh_role)" && smite_bh_prepare "$role" ;;
            4) read -rp "Preparation ID: " id; smite_bh_verify_stage "$id" ;;
            5) read -rp "Preparation ID: " id
               read -rp "Discard unused candidate only? [y/N]: " answer
               [ "$answer" = y ] && smite_bh_discard_unused "$id" ;;
            0) return ;;
            *) echo "Invalid selection." ;;
        esac
        read -rp "Press Enter to continue..."
    done
}

# UI consolidation only: legacy installers are retained behind Advanced Tools.
# No change to existing FRP/Backhaul installers, ownership or on-host state.
docker_smite_advanced_menu() {
    local choice
    while true; do
        clear
        echo "======================================"
        echo "      Advanced & Legacy Tools"
        echo "======================================"
        echo "1) Standard FRP Test Guide (read-only)"
        echo "2) FRP setup (beginner + Advanced)"
        echo "3) Legacy Backhaul offline preparation (NOT installer)"
        echo "0) Back"
        read -rp "Choose [0-3]: " choice || return
        case "$choice" in
            1) docker_smite_frp_standard_guide ;;
            2) smite_frp_wizard_menu ;;
            3) smite_bh_management_menu ;;
            0) return ;;
            *) echo "Invalid selection." ;;
        esac
    done
}

docker_smite_management_menu() {
    local choice role
    while true; do
        clear
        echo "======================================"
        echo "          Smite Management"
        echo "======================================"
        echo "1) Private Network Wizard"
        echo "2) Tunnel Management (FRP / Backhaul / Rathole)"
        echo "3) Status & Diagnostics"
        echo "4) Advanced & Legacy Tools"
        echo "5) Independent Engines (Backhaul review)"
        echo "0) Back"
        read -rp "Choose [0-5]: " choice || return
        case "$choice" in
            1) docker_smite_open_setup_wizard ;;
            2) if declare -F smite_tw_menu >/dev/null 2>&1; then
                   smite_tw_menu
               else
                   echo "Tunnel Wizard missing; update U-OPTI from main first."
               fi ;;
            3) if declare -F smite_tw_choose_role >/dev/null 2>&1 &&
                  declare -F twcc_menu >/dev/null 2>&1; then
                   role="$(smite_tw_choose_role)" || continue
                   twcc_menu "$role"
               else
                   echo "Status module missing; update U-OPTI from main first."
               fi ;;
            4) docker_smite_advanced_menu ;;
            5)
                if [ -s "$SMITE_BH_DIR/smite-managed-backhaul-menu.sh" ]; then
                    # Separate from FRP-dependent legacy Backhaul sidecar.
                    source "$SMITE_BH_DIR/smite-managed-backhaul-menu.sh"
                    smite_managed_bh_menu
                else
                    echo "HOLD: Independent Backhaul module is missing."
                fi
                ;;
            0) return ;;
            *) echo "Invalid selection." ;;
        esac
    done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    case "${1:-}" in
        --status) smite_bh_status ;;
        --preflight) role="$(smite_bh_role)" && smite_bh_preflight "$role" ;;
        --prepare) role="$(smite_bh_role)" && smite_bh_prepare "$role" ;;
        --verify) smite_bh_verify_stage "${2:-}" ;;
        --discard-unused) smite_bh_discard_unused "${2:-}" ;;
        *) echo "Usage: $0 --status|--preflight|--prepare|--verify ID|--discard-unused ID" >&2; exit 2 ;;
    esac
fi
