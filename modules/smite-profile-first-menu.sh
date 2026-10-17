#!/usr/bin/env bash
# NON-SECRET profile-first plan; no Smite, Docker, Xray, Nginx or tunnel writes.
ROLE="$1"
case "$ROLE" in ir|kh) ;; *) echo "HOLD: role must be ir or kh"; exit 2 ;; esac
HERE="$(cd "$(dirname "$0")" && pwd)"
HELPER="$HERE/smite-profile-first.py"
[ -s "$HELPER" ] || { echo "HOLD: Missing profile helper"; exit 2; }
while true; do
    echo "===== PROFILE FIRST | ROLE=$ROLE ====="
    echo "1) Validate + save BOTH XHTTP ports/Paths on THIS host"
    echo "2) Show saved profiles"
    echo "3) Show Sanaei-first installation order"
    echo "0) Back"
    read -rp "Choose [0-3]: " choice || exit 0
    case "$choice" in
        1)
            read -rp "FRP Xray inbound port: " fp || exit 2
            read -rp "FRP XHTTP base Path: " fx || exit 2
            read -rp "Backhaul Xray inbound port: " bp || exit 2
            read -rp "Backhaul XHTTP base Path: " bx || exit 2
            if ! python3 -B "$HELPER" --check --frp-port "$fp" --frp-path "$fx" --backhaul-port "$bp" --backhaul-path "$bx"; then
                echo "HOLD: Invalid/overlapping plan. No change."
                continue
            fi
            if python3 -B "$HELPER" --show >/dev/null 2>&1; then
                read -rp "To replace an UNAPPLIED plan type REPLACE-UNAPPLIED-PROFILES: " approve || exit 2
                [ "$approve" = "REPLACE-UNAPPLIED-PROFILES" ] || { echo "No change."; continue; }
                python3 -B "$HELPER" --save --replace --confirm "$approve" --frp-port "$fp" --frp-path "$fx" --backhaul-port "$bp" --backhaul-path "$bx"
            else
                python3 -B "$HELPER" --save --frp-port "$fp" --frp-path "$fx" --backhaul-port "$bp" --backhaul-path "$bx"
            fi
            ;;
        2) python3 -B "$HELPER" --show || : ;;
        3)
            echo "KH: Install Docker + Sanaei 3x-UI FIRST, and configure Nginx/SSL."
            echo "KH: Make TWO distinct VLESS/XHTTP loopback inbounds."
            echo "KH: Save ports and Paths here, before Smite exists."
            echo "IR: Install Docker, Smite Panel+IR Node Standard and HTTPS/443."
            echo "IR: Save the SAME non-secret 4 profile values here."
            echo "KH: Install Smite Foreign Node Standard + HTTPS control Gateway."
            echo "IR: FRP option 2 -> save FRP port/Path -> apply Smite UI FRP TCP."
            echo "IR: Backhaul START HERE -> install IR Sidecar using saved values."
            echo "KH: Backhaul START HERE -> hidden pairing -> install KH Sidecar."
            echo "BOTH: audits, real client connections, sequential reboots."
            echo "Backhaul activation remains TEST VPS ONLY with snapshot+console."
            ;;
        0) exit 0 ;;
        *) echo "Invalid choice" ;;
    esac
done
