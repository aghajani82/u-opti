#!/usr/bin/env bash
# U-OPTI Smite Node Pairing Preview.
# No tunnel apply/remove, no service restart, no FRP/Backhaul/Nginx changes.
smite_node_pairing_menu() {
    local here helper candidate_helper audit_helper review_helper stage13_helper answer choice panel_image_root node_image_root review_output role
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 1
    helper="$here/smite-node-pairing.py"
    candidate_helper="$here/smite-node-auth-candidate.py"
    audit_helper="$here/smite-auth-image-overlay-audit.py"
    review_helper="$here/smite-stage11-overlay-review.py"
    stage13_helper="$here/smite-stage13-preflight.py"
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
        echo "4) Inspect Node Docker auth preflight (read-only, Standard)"
        echo "5) Prepare INERT Node auth Compose candidate (no Docker changes)"
        echo "6) Discard only the unactivated Compose candidate"
        echo "7) Audit image sources vs host overlays (read-only, offline)"
        echo "8) Prepare offline security/FRP/Backhaul overlay review bundle"
        echo "9) Final IR/KH Stage13 read-only deployment admission (always blocks activation)"
        echo "0) Back"
        echo
        read -rp "Choose [0-9]: " choice || return 0
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
            4)
                [ -f "$candidate_helper" ] && python3 -B "$candidate_helper" --preflight || echo "HOLD: Stage 9 helper unavailable or preflight failed"
                ;;
            5)
                echo "WARNING: This prepares a future STRICT auth candidate only."
                echo "It does NOT apply Compose, authenticate Node or change any tunnel."
                read -rp "Type PREPARE-AUTH-ONLY to continue: " answer || return 2
                if [ "$answer" = "PREPARE-AUTH-ONLY" ] && [ -f "$candidate_helper" ]; then
                    python3 -B "$candidate_helper" --prepare || :
                else
                    echo "Cancelled; no changes."
                fi
                ;;
            6)
                echo "Discard ONLY the untouched Stage 9 candidate; never delete Node identity or Replay."
                read -rp "Type DISCARD-CANDIDATE to continue: " answer || return 2
                if [ "$answer" = "DISCARD-CANDIDATE" ] && [ -f "$candidate_helper" ]; then
                    python3 -B "$candidate_helper" --discard || :
                else
                    echo "Cancelled; no changes."
                fi
                ;;
            7)
                echo "Stage10 compares EXTRACTED, trusted image /app sources to U-OPTI host files."
                echo "It does not build images, check image signatures or modify Docker."
                [ -f "$audit_helper" ] || { echo "HOLD: Image auditor is missing"; continue; }
                read -rp "Extracted Panel /app directory (absolute path): " panel_image_root || return 2
                read -rp "Extracted Node /app directory (absolute path): " node_image_root || return 2
                if [[ "$panel_image_root" != /* || "$node_image_root" != /* ]]; then
                    echo "HOLD: Both paths must be absolute."
                    continue
                fi
                python3 -B "$audit_helper" \
                    --panel-image-app "$panel_image_root" \
                    --node-image-app "$node_image_root" || :
                echo "NOTE: SOURCE_PARITY does not authorize enabling signed mode."
                ;;
            8)
                echo "This creates ONLY a local, private review bundle; never installs it."
                [ -f "$review_helper" ] || { echo "HOLD: Stage11 review helper unavailable"; continue; }
                read -rp "Trusted extracted Panel /app directory: " panel_image_root || return 2
                read -rp "Trusted extracted Node /app directory: " node_image_root || return 2
                read -rp "NEW offline review output directory (absolute): " review_output || return 2
                if [[ "$panel_image_root" != /* || "$node_image_root" != /* || "$review_output" != /* ]]; then
                    echo "HOLD: all paths must be absolute"
                    continue
                fi
                python3 -B "$review_helper" \
                    --panel-image-app "$panel_image_root" \
                    --node-image-app "$node_image_root" \
                    --output "$review_output" || :
                echo "NOTE: The review bundle is NEVER ready to activate by itself."
                ;;
            9)
                echo "STAGE13 IS READ-ONLY. Missing evidence returns HOLD."
                echo "Even fully passing local checks do NOT authorize real activation."
                [ -f "$stage13_helper" ] || { echo "HOLD: Stage13 checker not installed"; continue; }
                read -rp "Select actual server role (ir/kh): " role || return 2
                if [ "$role" != "ir" ] && [ "$role" != "kh" ]; then
                    echo "HOLD: Role must be ir or kh"
                    continue
                fi
                python3 -B "$stage13_helper" --role "$role" || :
                echo "NOTE: Verify cloud snapshots, Docker runtime, ingress and real client traffic separately."
                ;;
            0) return 0 ;;
            *) echo "Invalid selection" ;;
        esac
    done
}
