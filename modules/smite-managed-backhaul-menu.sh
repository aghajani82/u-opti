#!/usr/bin/env bash
# Independent Smite Engine Management: Backhaul preview only.
# No installation, deletion, apt, curl, Docker, Nginx, firewall, or SSH here.
# The install button stays CLOSED pending authorized two-host acceptance.
SMITE_ENGINE_MENU_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SMITE_MANAGED_BACKHAUL_CONTROL="$SMITE_ENGINE_MENU_DIR/smite-managed-backhaul-control.py"
SMITE_MANAGED_FRP_MENU="$SMITE_ENGINE_MENU_DIR/smite-managed-frp-menu.sh"
SMITE_MANAGED_BACKHAUL_HOST_GATE="$SMITE_ENGINE_MENU_DIR/smite-managed-backhaul-host-gate.py"
SMITE_INDEPENDENT_ENGINE_HOST_GATE="$SMITE_ENGINE_MENU_DIR/smite-managed-engine-host-admission.py"
SMITE_MANAGED_BACKHAUL_HOST_EXECUTOR="$SMITE_ENGINE_MENU_DIR/smite-managed-backhaul-host-executor.py"
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
                    # Optional independent signed release evidence for this
                    # read-only review. Four explicit external pins are
                    # required; the verifier rejects incomplete/forged proof.
                    # A Docker-reported digest is never used as the source.
                    local -a signed_pair_args=()
                    [ -z "${SMITE_BH_PAIR_MANIFEST:-}" ] || signed_pair_args+=(
                        --signed-pair-manifest "$SMITE_BH_PAIR_MANIFEST")
                    [ -z "${SMITE_BH_PAIR_SHA256:-}" ] || signed_pair_args+=(
                        --signed-pair-manifest-sha256 "$SMITE_BH_PAIR_SHA256")
                    [ -z "${SMITE_BH_PAIR_SOURCE_SHA:-}" ] || signed_pair_args+=(
                        --signed-pair-source-sha "$SMITE_BH_PAIR_SOURCE_SHA")
                    [ -z "${SMITE_BH_PAIR_PUBLISH_REF:-}" ] || signed_pair_args+=(
                        --signed-pair-publish-ref "$SMITE_BH_PAIR_PUBLISH_REF")
                    # Use the selected RC7 release pins on an ordinary menu
                    # run. A partial explicit override must still fail closed.
                    if [ "${#signed_pair_args[@]}" -eq 0 ]; then
                        signed_pair_args=(
                            --signed-pair-manifest "$SMITE_ENGINE_MENU_DIR/smite-selected-candidate.json"
                            --signed-pair-manifest-sha256 58bebfc605a5c1a64cf02ce38e6397dbcdae5f1c3289a01952f361b6a8aa660e
                            --signed-pair-source-sha 9a1270b31e8d44f13d09b71ab6b9798410b09c12
                            --signed-pair-publish-ref refs/tags/v2.0.0-rc.7)
                    fi
                    # The four independent pins must be complete. A partial
                    # override must never fall back to the selected RC7 pair.
                    local signed_pair_complete=yes
                    if [ "${#signed_pair_args[@]}" -ne 8 ]; then
                        signed_pair_complete=no
                    fi
                    [ -z "${SMITE_BH_PAIR_TRUSTED_ROOT:-}" ] || signed_pair_args+=(
                        --signed-pair-trusted-root "$SMITE_BH_PAIR_TRUSTED_ROOT")
                    python3 -B "$SMITE_INDEPENDENT_ENGINE_HOST_GATE" \
                        --engine backhaul --node-dir "$SMITE_MANAGED_NODE_DIR" \
                        "${signed_pair_args[@]}" || :
                    echo "===== EXISTING RC7 RETAINED-NODE REVIEW (READ ONLY) ====="
                    # Reuse the already reviewed executor, not the legacy
                    # Compose-recreating trial install. Never derive the
                    # expected image from mutable Docker labels or a tag.
                    # A different externally supplied pair must fail closed
                    # against this selected RC7 immutable Node image pin.
                    local review_arch=""
                    case "$(uname -m)" in
                        x86_64) review_arch=amd64 ;;
                        aarch64) review_arch=arm64 ;;
                    esac
                    if [ "$signed_pair_complete" != yes ]; then
                        echo "HOLD: Complete external signed Panel/Node pair pins required."
                    elif [ "$SMITE_MANAGED_NODE_DIR" != /opt/smite-node ]; then
                        echo "HOLD: Retained-node review requires the managed Node path."
                    elif [ -z "$review_arch" ]; then
                        echo "HOLD: Unsupported Backhaul review architecture."
                    elif [ ! -f "$SMITE_MANAGED_BACKHAUL_HOST_EXECUTOR" ] ||
                         [ -L "$SMITE_MANAGED_BACKHAUL_HOST_EXECUTOR" ] ||
                         [ ! -s "$SMITE_MANAGED_BACKHAUL_HOST_EXECUTOR" ]; then
                        echo "HOLD: Existing retained-node review executor missing."
                    else
                        python3 -B "$SMITE_MANAGED_BACKHAUL_HOST_EXECUTOR" review-in-place \
                            --arch "$review_arch" \
                            --confirm-role REVIEW-BACKHAUL-IN-PLACE \
                            --expected-node-image \
                            "ghcr.io/aghajani82/smite-node@sha256:03ae4ca0f6d516374671fad4e32d44c13fbb46d0e4309bccb0265230d6fc4263" \
                            "${signed_pair_args[@]}" || :
                    fi
                else
                    echo "HOLD: Common host admission helper missing."
                fi
                echo "===== RC7 BUNDLED BACKHAUL + SIGNED INVENTORY (REVIEW ONLY) ====="
                if [ -s "$SMITE_MANAGED_BACKHAUL_CONTROL" ]; then
                    # No role prompt, extra menu item or caller-controlled
                    # identity. The Python helper validates the actual
                    # /opt/smite-node root and checks its RC7 committed role.
                    # Signed GETs consume a replay nonce; NO tunnel Apply,
                    # Docker recreate, FRPS stop or manifest edit occurs.
                    python3 -B "$SMITE_MANAGED_BACKHAUL_CONTROL" \
                        verify-rc7-bundle --auto-role \
                        --node-dir "$SMITE_MANAGED_NODE_DIR" || :
                else
                    echo "HOLD: RC7 bundled engine checker missing."
                fi
                echo "INSTALL_ALLOWED=NO"
                echo "ACTIVATION_GATE=HOLD"
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
