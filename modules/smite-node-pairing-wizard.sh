#!/usr/bin/env bash
# U-OPTI Smite Signed Pairing — disposable Field Trial controller.
# Production is never authorized by this menu.
smite_node_pairing_menu() {
    local here helper answer choice
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 1
    helper="$here/smite-node-pairing.py"

    if [ ! -f "$helper" ] || ! python3 -m py_compile "$helper" >/dev/null 2>&1; then
        echo "HOLD: Smite signed-pairing controller is unavailable."
        return 2
    fi

    while true; do
        echo
        echo "======================================"
        echo "        Smite Signed Pairing"
        echo "          FIELD TRIAL ONLY"
        echo "======================================"
        echo "1) Status / readiness (read-only)"
        echo "2) Enable secure Panel pairing on HTTPS/443 (IR)"
        echo "3) Redeem one-time pairing code on this Node"
        echo "4) Activate signed IR Node runtime"
        echo "5) Roll back Node runtime to paused + strict"
        echo "6) Show safe pairing order"
        echo "7) Activate signed KH Node runtime (foreign; reviewed Panel required)"
        echo "8) Approve foreign KH Gateway origin on IR (Panel only)"
        echo "0) Back"
        echo
        read -rp "Choose [0-8]: " choice || return 0
        choice="${choice#"${choice%%[![:space:]]*}"}"
        choice="${choice%"${choice##*[![:space:]]}"}"

        case "$choice" in
            1)
                python3 -B "$helper" --status || :
                ;;
            2)
                echo
                echo "IR only. This enables the reviewed exact pairing endpoint on"
                echo "the existing HTTPS/443 gateway and restarts only smite-panel."
                echo "No tunnel engine, Xray inbound or extra public port is touched."
                read -rp "Type ENABLE-IR-SIGNED-PAIRING to continue: " answer || return 2
                if [ "$answer" = "ENABLE-IR-SIGNED-PAIRING" ]; then
                    UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES \
                        python3 -B "$helper" --enable-panel-field-trial || :
                else
                    echo "Cancelled; no changes."
                fi
                ;;
            3)
                echo
                echo "Use this only after the Panel shows the reserved Node and"
                echo "you created its short-lived one-time pairing code."
                UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES \
                    python3 -B "$helper" --redeem-field-trial || :
                ;;
            4)
                echo
                echo "IR only for this gate. The paired credential is mounted read-only,"
                echo "Smite provisions its one-time replay DB offline, then Node switches"
                echo "from paused to signed. Failure attempts a paused rollback."
                read -rp "Type ACTIVATE-IR-SIGNED-NODE to continue: " answer || return 2
                if [ "$answer" = "ACTIVATE-IR-SIGNED-NODE" ]; then
                    UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES \
                        python3 -B "$helper" --activate-ir-node-field-trial || :
                else
                    echo "Cancelled; no changes."
                fi
                ;;
            5)
                echo
                echo "This drops only the signed runtime overlay."
                echo "Pairing identity and replay history are preserved."
                read -rp "Type PAUSE-SIGNED-NODE to continue: " answer || return 2
                if [ "$answer" = "PAUSE-SIGNED-NODE" ]; then
                    UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES \
                        python3 -B "$helper" --rollback-node-field-trial || :
                else
                    echo "Cancelled; no changes."
                fi
                ;;
            6)
                echo
                echo "Safe IR order:"
                echo "  1. Core install stays paused + strict."
                echo "  2. Enable Panel secure pairing over existing TLS/443."
                echo "  3. In Iran Nodes, reserve by NAME only."
                echo "  4. Create one short-lived pairing code."
                echo "  5. Redeem it locally; secret never appears in logs."
                echo "  6. Activate signed IR runtime."
                echo "  7. Require Node->Panel signed check-in AND Panel->Node HMAC/replay PASS."
                echo
                echo "KH order: install Foreign Node, install/attach Sanaei, configure Gateway."
                echo "Then reserve KH on Panel, approve its origin on IR, redeem on KH, activate KH."
                ;;
            7)
                echo
                echo "KH ONLY: requires externally approved foreign Node origin"
                echo "on IR, reviewed RC.2 or pinned Stage15 Panel and one-time identity."
                echo "This command will apply the signed security overlay, create"
                echo "durable local Replay state, and may recreate ONLY smite-node."
                echo "Failure attempts a paused/strict Node rollback; identity and"
                echo "Replay history are intentionally retained."
                read -rp "Type ACTIVATE-KH-SIGNED-NODE to continue: " answer || return 2
                if [ "$answer" = "ACTIVATE-KH-SIGNED-NODE" ]; then
                    UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES \
                        python3 -B "$helper" --activate-foreign-node-field-trial || :
                else
                    echo "Cancelled; no changes."
                fi
                ;;
            8)
                echo
                echo "IR ONLY: requires an admin-reserved pending KH Node UUID,"
                echo "reviewed Panel image with pinned HTTPS/443 path support,"
                echo "and verified remote TLS. This records an exact trusted"
                echo "origin without restarting Panel or creating pairing codes."
                read -rp "Type APPROVE-KH-PIN to continue: " answer || return 2
                if [ "$answer" = "APPROVE-KH-PIN" ]; then
                    UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES \
                        python3 -B "$helper" --approve-foreign-origin-field-trial || :
                else
                    echo "Cancelled; no changes."
                fi
                ;;
            0)
                return 0
                ;;
            *)
                echo "Invalid selection."
                ;;
        esac
    done
}
