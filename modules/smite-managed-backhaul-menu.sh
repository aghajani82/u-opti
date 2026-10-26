#!/usr/bin/env bash
# Independent Smite Engine Management: Backhaul preview only.
# No installation, deletion, apt, curl, Docker, Nginx, firewall, or SSH here.
# The install button stays CLOSED pending authorized two-host acceptance.
SMITE_ENGINE_MENU_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SMITE_MANAGED_BACKHAUL_CONTROL="$SMITE_ENGINE_MENU_DIR/smite-managed-backhaul-control.py"
SMITE_MANAGED_FRP_MENU="$SMITE_ENGINE_MENU_DIR/smite-managed-frp-menu.sh"
SMITE_MANAGED_BACKHAUL_HOST_GATE="$SMITE_ENGINE_MENU_DIR/smite-managed-backhaul-host-gate.py"
SMITE_INDEPENDENT_ENGINE_HOST_GATE="$SMITE_ENGINE_MENU_DIR/smite-managed-engine-host-admission.py"
SMITE_MANAGED_NODE_DIR="${SMITE_NODE_DIR:-/opt/smite-node}"

smite_managed_bh_check() {
    local action="${1:-status}"
    case "$action" in
        status|review) ;;
        *) echo "HOLD: Only read-only actions are allowed"; return 2 ;;
    esac
    if [ ! -s "$SMITE_MANAGED_BACKHAUL_CONTROL" ] ||
       ! command -v python3 >/dev/null 2>&1; then
        echo "HOLD: Independent Backhaul operator helper is missing."
        return 2
    fi
    python3 -B "$SMITE_MANAGED_BACKHAUL_CONTROL" "$action" \
        --node-dir "$SMITE_MANAGED_NODE_DIR"
}

smite_managed_bh_host_gate() {
    local report_format="${1:-text}"
    case "$report_format" in text|json) ;; *) echo "HOLD: Unsupported report format"; return 2 ;; esac
    if [ ! -s "$SMITE_MANAGED_BACKHAUL_HOST_GATE" ]; then
        echo "HOLD: Host safety check is not installed."
        return 2
    fi
    python3 -B "$SMITE_MANAGED_BACKHAUL_HOST_GATE" --node-dir "$SMITE_MANAGED_NODE_DIR" --format "$report_format"
}

smite_managed_bh_menu() {
    local choice
    while true; do
        if [ -t 1 ] && [ -n "${TERM:-}" ]; then clear || :; fi
        echo "======================================"
        echo "       Independent Engines"
        echo "            Backhaul"
        echo "======================================"
        echo "1) Status (read-only)"
        echo "2) Review installation prerequisites"
        echo "3) Install Backhaul (not enabled yet)"
        echo "4) Show safe IR/KH report (read-only)"
        echo "5) FRP — Independent install/review"
        echo "0) Back"
        echo
        read -rp "Choose [0-5]: " choice || return 0
        choice="${choice#"${choice%%[![:space:]]*}"}"
        choice="${choice%"${choice##*[![:space:]]}"}"
        case "$choice" in
            1) smite_managed_bh_check status || : ;;
            2)
                smite_managed_bh_check review || :
                echo "===== INDEPENDENT BACKHAUL HOST PREFLIGHT (READ ONLY) ====="
                if [ -s "$SMITE_INDEPENDENT_ENGINE_HOST_GATE" ]; then
                    python3 -B "$SMITE_INDEPENDENT_ENGINE_HOST_GATE" \
                        --engine backhaul --node-dir "$SMITE_MANAGED_NODE_DIR" || :
                else
                    echo "HOLD: Common host admission helper missing."
                fi
                ;;
            4)
                echo "===== SAFE HOST REPORT (NO SECRETS) ====="
                smite_managed_bh_host_gate json || :
                ;;
            5)
                if [ ! -s "$SMITE_MANAGED_FRP_MENU" ]; then
                    echo "HOLD: Independent FRP menu missing."
                else
                    # Source checked-in module to keep role selection simple.
                    # It may only perform review and a disabled install.
                    source "$SMITE_MANAGED_FRP_MENU"
                    smite_managed_frp_menu
                fi
                ;;
            3)
                echo "HOLD: Backhaul installation on real IR/KH is disabled."
                echo "No Docker, Smite, FRP, ports, routes or files changed."
                echo "The independent install + rollback is validated in GitHub PR CI only."
                ;;
            0) return ;;
            *) echo "Invalid choice" ;;
        esac
        if [ -t 0 ]; then read -rp "Press Enter to continue..." _ || return; fi
    done
}
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    case "${1:-}" in
        --status) smite_managed_bh_check status ;;
        --review) smite_managed_bh_check review ;;
        --host-audit) smite_managed_bh_host_gate text ;;
        --host-report) smite_managed_bh_host_gate json ;;
        --install)
            echo "HOLD: Host installation disabled. No changes made." >&2
            exit 2
            ;;
        --menu) smite_managed_bh_menu ;;
        *) echo "Usage: $0 --status|--review|--host-audit|--host-report|--menu" >&2; exit 2 ;;
    esac
fi
