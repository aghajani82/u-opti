#!/usr/bin/env bash
# U-OPTI Smite Node Pairing Preview.
# No tunnel apply/remove, no service restart, no FRP/Backhaul/Nginx changes.
smite_node_pairing_menu() {
    local here helper answer choice
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 1
    helper="$here/smite-node-pairing.py"
    if [ ! -f "$helper" ]; then
        echo "HOLD: Pairing helper not installed"
        return 2
    fi
    while true; do
        echo
        echo "======================================"
        echo "       Smite Node Pairing Preview"
        echo "======================================"
        echo "1) Check current Standard HTTPS/443 pairing readiness (read-only)"
        echo "2) Prepare private identity directory (no service changes)"
        echo "3) Show safe Panel -> Node enrollment order"
        echo "0) Back"
        echo
        read -rp "Choose [0-3]: " choice || return 0
        case "$choice" in
            1)
                python3 -B "$helper" --status || :
                ;;
            2)
                echo "Prepare a root-owned 0700 directory for FUTURE credentials."
                echo "This does not connect Node, enable auth or change any tunnel."
                read -rp "Type PREPARE-ONLY to continue: " answer || return 2
                if [ "$answer" = "PREPARE-ONLY" ]; then
                    python3 -B "$helper" --prepare-store || :
                else
                    echo "Cancelled, no changes."
                fi
                ;;
            3)
                echo "1. Admin verifies existing node identity out-of-band."
                echo "2. Panel prepares a short-lived code (JWT-admin only)."
                echo "3. Node validates HTTPS/443 certificate before redemption."
                echo "4. Node stores its secret privately; never displays it."
                echo "5. Signed Panel <-> Node traffic activated ONLY after both"
                echo "   services, U-OPTI overlays and gateway are tested."
                echo "6. Existing FRP/Backhaul client traffic validated again."
                echo
                echo "CURRENT STATUS: pairing redemption and machine auth"
                echo "are NOT enabled by this U-OPTI preview menu."
                ;;
            0) return 0 ;;
            *) echo "Invalid selection" ;;
        esac
    done
}
