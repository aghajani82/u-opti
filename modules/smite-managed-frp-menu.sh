#!/usr/bin/env bash
# Managed FRP operator menu — read-only review plus disabled host Install.
# Does not ask for a forwarded port, create a tunnel or touch Backhaul.
SMITE_FRP_MENU_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SMITE_MANAGED_FRP_CONTROL="$SMITE_FRP_MENU_DIR/smite-managed-frp-control.py"
SMITE_INDEPENDENT_FRP_HOST_GATE="$SMITE_FRP_MENU_DIR/smite-managed-engine-host-admission.py"
SMITE_FRP_NODE_DIR="${SMITE_NODE_DIR:-/opt/smite-node}"

smite_managed_frp_check() {
    local action="${1:-status}"
    case "$action" in status|review) ;; *) echo "HOLD: Unsupported FRP action" >&2; return 2 ;; esac
    if [ ! -s "$SMITE_MANAGED_FRP_CONTROL" ] || ! command -v python3 >/dev/null 2>&1; then
        echo "HOLD: Independent FRP review module not available." >&2; return 2
    fi
    python3 -B "$SMITE_MANAGED_FRP_CONTROL" "$action" --node-dir "$SMITE_FRP_NODE_DIR"
}

smite_managed_frp_menu() {
    local selection
    while true; do
        if [ -t 1 ] && [ -n "${TERM:-}" ]; then clear || :; fi
        echo "======================================"
        echo "    Independent Tunnel Engines"
        echo "               FRP"
        echo "======================================"
        echo "1) FRP status (read-only)"
        echo "2) Review prerequisites (no ports)"
        echo "3) Install FRP (not enabled yet)"
        echo "4) Stage15 Signed FRP readiness (read-only)"
        echo "0) Back"
        echo
        read -rp "Choose [0-4]: " selection || return 0
        selection="${selection#"${selection%%[![:space:]]*}"}"
        selection="${selection%"${selection##*[![:space:]]}"}"
        case "$selection" in
            1) smite_managed_frp_check status || : ;;
            2)
                smite_managed_frp_check review || :
                echo "===== INDEPENDENT FRP HOST PREFLIGHT (READ ONLY) ====="
                if [ -s "$SMITE_INDEPENDENT_FRP_HOST_GATE" ]; then
                    python3 -B "$SMITE_INDEPENDENT_FRP_HOST_GATE" \
                        --engine frp --node-dir "$SMITE_FRP_NODE_DIR" || :
                else
                    echo "HOLD: Common host admission helper missing."
                fi
                ;;
            3)
                echo "HOLD: FRP installation on real IR/KH is disabled."
                echo "No Backhaul, FRP, Smite, paths, ports or Docker containers changed."
                ;;
            4)
                python3 -B "$SMITE_MANAGED_FRP_CONTROL" stage15 --node-dir "$SMITE_FRP_NODE_DIR" || :
                ;;
            0) return ;;
            *) echo "Invalid choice" ;;
        esac
        if [ -t 0 ]; then read -rp "Press Enter to continue..." _ || return; fi
    done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    case "${1:-}" in
        --status) smite_managed_frp_check status ;;
        --review) smite_managed_frp_check review ;;
        --menu) smite_managed_frp_menu ;;
        --install)
            echo "HOLD: Host FRP install disabled. No changes made." >&2
            exit 2
            ;;
        *) echo "Usage: $0 --status|--review|--install|--menu" >&2; exit 2 ;;
    esac
fi
