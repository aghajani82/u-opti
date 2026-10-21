#!/usr/bin/env bash
# Safe, hermetic shell tests: no live host actions and no Docker calls.
set -euo pipefail
trap 'echo "FAILED TUNNEL MENU TEST at line $LINENO" >&2' ERR
cd "$(dirname "$0")/.."

bash -n modules/smite-tunnel-wizard.sh
grep -Fq '"smite-tunnel-wizard.sh"' install.sh
grep -Fq '"smite-tunnel-wizard.sh"' u-opti
grep -Fq '"smite-backhaul-sidecar.py"' install.sh
grep -Fq '"smite-backhaul-sidecar.py"' u-opti
grep -Fq 'smite_tw_backhaul_prepare()' modules/smite-tunnel-wizard.sh
grep -Fq -- '--data-port "$data_port" --xhttp-path "$xhttp_path"' modules/smite-tunnel-wizard.sh
grep -Fq 'This is an OFFLINE PREVIEW' modules/smite-tunnel-wizard.sh
grep -Fq 'START HERE - Guided Pair + Install' modules/smite-tunnel-wizard.sh
grep -Fq 'smite_tw_backhaul_quick_start()' modules/smite-tunnel-wizard.sh
grep -Fq 'Check installation / troubleshoot (read-only)' modules/smite-tunnel-wizard.sh
grep -Fq 'smite_tw_backhaul_guided_prepare()' modules/smite-tunnel-wizard.sh
grep -Fq 'smite_tw_backhaul_guided_trial_install()' modules/smite-tunnel-wizard.sh
grep -Fq 'smite_tw_backhaul_install_badge()' modules/smite-tunnel-wizard.sh
grep -Fq 'XHTTP base Path [/$port/www]' modules/smite-tunnel-wizard.sh
grep -Fq -- '--data-port "$port" --xhttp-path "$path"' modules/smite-tunnel-wizard.sh
grep -Fq -- '--diagnose --role "$role"' modules/smite-tunnel-wizard.sh
grep -Fq 'INSTALLATION NOT STARTED' modules/smite-tunnel-wizard.sh
grep -Fq '"smite-backhaul-sidecar-guided-trial.py"' install.sh
grep -Fq '"smite-backhaul-sidecar-guided-trial.py"' u-opti
grep -Fq 'smite_tw_backhaul_secure_pair()' modules/smite-tunnel-wizard.sh
grep -Fq 'smite_tw_backhaul_paste_pair()' modules/smite-tunnel-wizard.sh
grep -Fq '"smite-backhaul-sidecar-paste-pair.py"' install.sh
grep -Fq '"smite-backhaul-sidecar-paste-pair.py"' u-opti
grep -Fq '"smite-backhaul-sidecar-ssh-pair.py"' install.sh
grep -Fq '"smite-backhaul-sidecar-ssh-pair.py"' u-opti
grep -Fq '"smite-backhaul-sidecar-guided-prep.py"' install.sh
grep -Fq '"smite-backhaul-sidecar-guided-prep.py"' u-opti
grep -Fq 'PREPARE-PRIVATE-OFFLINE' modules/smite-tunnel-wizard.sh
grep -Fq 'smite_tw_backhaul_readiness()' modules/smite-tunnel-wizard.sh
grep -Fq 'smite_tw_backhaul_admission()' modules/smite-tunnel-wizard.sh
grep -Fq 'smite_tw_backhaul_live_trial()' modules/smite-tunnel-wizard.sh
grep -Fq '"smite-backhaul-sidecar-live-trial.py"' install.sh
grep -Fq '"smite-backhaul-sidecar-live-trial.py"' u-opti
grep -Fq '"smite-backhaul-sidecar-admission.py"' install.sh
grep -Fq '"smite-backhaul-sidecar-admission.py"' u-opti
grep -Fq '"smite-backhaul-sidecar-readiness.py"' install.sh
grep -Fq '"smite-backhaul-sidecar-nginx-plan.py"' install.sh
grep -Fq '"smite-backhaul-sidecar-nginx-plan.py"' u-opti
grep -Fq 'smite_tw_backhaul_nginx_plan()' modules/smite-tunnel-wizard.sh
grep -Fq '"smite-backhaul-sidecar-readiness.py"' u-opti
grep -Fq 'IR HTTPS domain (required)' modules/smite-tunnel-wizard.sh
grep -Fq 'KH upstream/Xray Host domain (required)' modules/smite-tunnel-wizard.sh
grep -Fq '["smite-tunnel-wizard.sh"]="$BASE_URL/modules/smite-tunnel-wizard.sh"' u-opti
grep -Fq '["smite-tunnel-wizard.sh"]="$TEMP_DIR/smite-tunnel-wizard.sh"' u-opti
grep -Fq 'smite_tw_menu()' modules/smite-tunnel-wizard.sh
grep -Fq 'twcc_menu()' modules/smite-tunnel-control-center.sh
grep -Fq 'source "$SMITE_BH_DIR/smite-tunnel-wizard.sh"' modules/smite-backhaul-management.sh
grep -Fq '3) Tunnel Management (FRP / Backhaul / Rathole)' modules/smite-backhaul-management.sh

smite_bh_role() { echo ir; }
source modules/smite-tunnel-wizard.sh
smite_tw_clear() { :; }
smite_tw_pause() { :; }

test "$(smite_tw_role)" = ir
test "$(smite_tw_result ready)" = READY
test "$(smite_tw_result missing)" = "NOT FOUND"

ir_out="$(smite_tw_backhaul_overview ir)"
grep -Fq '127.0.0.1:3080' <<< "$ir_out"
grep -Fq 'XHTTP path from actual KH inbound.' <<< "$ir_out"
! grep -Fq '56053' <<< "$ir_out"
kh_out="$(smite_tw_backhaul_overview kh)"
grep -Fq '127.0.0.1:13080' <<< "$kh_out"
grep -Fq 'Configure Sanaei inbound first' <<< "$kh_out"
! grep -Fq '56053' <<< "$kh_out"
grep -Fq 'BLOCKED' <<< "$kh_out"

profile="$(smite_tw_backhaul_client)"
grep -Fq 'ALPN: http/1.1' <<< "$profile"
grep -Fq 'xPaddingBytes' <<< "$profile"
grep -Fq 'TLS: on' <<< "$profile"

# When custom KH Xray settings have actually been installed, the client screen
# must display THOSE values, never the old hard-coded /56053/www/ route.
smite_tw_backhaul_profile() { printf '%s\n' '45123 /assets/v1/connect'; }
custom_profile="$(smite_tw_backhaul_client kh)"
grep -Fq 'Installed KH Xray inbound port: 45123' <<< "$custom_profile"
grep -Fxq 'Path: /assets/v1/connect' <<< "$custom_profile"
if grep -Fq 'Legacy example ONLY' <<< "$custom_profile"; then
    echo 'ERROR: Real custom profile mislabeled as a legacy example' >&2
    exit 1
fi

steps="$(smite_tw_backhaul_steps ir)"
grep -Fq 'NOT production-approved' <<< "$steps"
grep -Fq 'NOT' <<< "$steps"
grep -Fq 'Rathole' modules/smite-tunnel-wizard.sh

good="$(smite_tw_rathole_plan ir 23333 45000)"
grep -Fq 'NO INSTALL' <<< "$good"
grep -Fq 'Do not assume Rathole uses Backhaul' <<< "$good"
grep -Fq 'IR: server' <<< "$good"

for pair in '443 45000' '3080 45000' '23333 23333' \
            'nope 45000' '65536 45000' '0000 45000'; do
    read -r control data <<< "$pair"
    if smite_tw_rathole_plan ir "$control" "$data" >/dev/null 2>&1; then
        echo "FAIL: unsafe Rathole ports accepted: $pair" >&2
        exit 1
    fi
done

# Test user-facing top menu routes without executing FRP install or network probes.
smite_frp_wizard_menu() { echo "FRP_DELEGATE_CALLED_ROLE:$1"; }
out="$(printf '2\n0\n' | smite_tw_menu)"
grep -Fq 'FRP_DELEGATE_CALLED_ROLE:ir' <<< "$out"
out="$(printf '1\n4\n5\n1\n0\n0\n0\n0\n' | smite_tw_menu)"
grep -Fq 'Backhaul v0.7.2' <<< "$out"
out="$(printf '3\n2\n23333\n45000\n0\n0\n' | smite_tw_menu)"
grep -Fq 'NO INSTALL' <<< "$out"

# Verify new primary and advanced routes without host inspection.
smite_tw_backhaul_readiness() { echo "READINESS_CALLED:$1:$2"; }
out="$(printf '1\n2\n2\n0\n0\n0\n' | smite_tw_menu)"
grep -Fq 'READINESS_CALLED:ir:existing' <<< "$out"
out="$(printf '1\n4\n1\n0\n0\n0\n' | smite_tw_menu)"
grep -Fq 'READINESS_CALLED:ir:new' <<< "$out"

# Simplified top-level Control Center route preserves FRP and Backhaul.
twcc_menu() { echo "TUNNEL_CENTER_ROLE:$1"; }
out="$(printf '4\n0\n' | smite_tw_menu)"
grep -Fq 'TUNNEL_CENTER_ROLE:ir' <<< "$out"

# Confirm the everyday client-profile action needs no expert-menu navigation.
out="$(printf '1\n3\n0\n0\n' | smite_tw_menu)"
grep -Fq 'Protocol: VLESS' <<< "$out"

smite_tw_backhaul_admission() { echo "ADMISSION_CHECK_FOR:$1"; }
out="$(printf '1\n4\n5\n5\n0\n0\n0\n0\n' | smite_tw_menu)"
grep -Fq 'ADMISSION_CHECK_FOR:ir' <<< "$out"

smite_tw_backhaul_live_trial() { echo "TRIAL_MENU_FOR:$1"; }
out="$(printf '1\n4\n3\n0\n0\n0\n' | smite_tw_menu)"
grep -Fq 'TRIAL_MENU_FOR:ir' <<< "$out"

# Guided path delegates to the new OFFLINE orchestrator, never the installer.
smite_tw_backhaul_guided_prepare() { echo "GUIDED_PAIR_PREP:$1"; }
out="$(printf '1\n4\n2\n0\n0\n0\n' | smite_tw_menu)"
grep -Fq 'GUIDED_PAIR_PREP:ir' <<< "$out"

# A trusted-SSH pairing entry is reachable from the test-host menu.
smite_tw_backhaul_secure_pair() { echo "TRUSTED_SSH_PAIR_ROUTE:$1"; }
out="$(printf '1\n4\n4\n0\n0\n0\n' | smite_tw_menu)"
grep -Fq 'TRUSTED_SSH_PAIR_ROUTE:ir' <<< "$out"

# New guided trial route must exist without invoking real Nginx/Docker actions.
smite_tw_backhaul_guided_trial_install() { echo "ONE_FLOW_TRIAL_FOR:$1"; }
out="$(printf '1\n4\n7\n0\n0\n0\n' | smite_tw_menu)"
grep -Fq 'ONE_FLOW_TRIAL_FOR:ir' <<< "$out"

# KH consent is a short hidden y/N step. Mistaken secret paste must neither
# reach the pairing helper NOR be echoed to captured output. The second prompt
# is owned by the Python getpass helper, never by the consent reader.
python3() { printf 'PAIR_HELPER_MODE=%s\n' "$3"; }
if out="$(printf 'A_SECRET_ENTERED_TOO_EARLY\n' | smite_tw_backhaul_paste_pair kh)"; then
    echo "ERROR: KH accepted a secret at the consent step" >&2; exit 1
fi
grep -Fq 'KH STEP 1/2:' <<< "$out"
grep -Fq 'No pairing code was accepted or saved' <<< "$out"
! grep -Fq 'A_SECRET_ENTERED_TOO_EARLY' <<< "$out"
! grep -Fq 'PAIR_HELPER_MODE=' <<< "$out"
out="$(printf 'y\n' | smite_tw_backhaul_paste_pair kh)"
grep -Fq 'KH STEP 2/2:' <<< "$out"
grep -Fq 'PAIR_HELPER_MODE=--paste-kh' <<< "$out"
unset -f python3

# Bitvise two-terminal pairing must be reachable without extra expert menus.
smite_tw_backhaul_paste_pair() { echo "BITVISE_COPY_PASTE_PAIR:$1"; }
out="$(printf '1\n4\n6\n0\n0\n0\n' | smite_tw_menu)"
grep -Fq 'BITVISE_COPY_PASTE_PAIR:ir' <<< "$out"


# First-class beginner route delegates to one-flow setup, without calling
# any real Docker/Nginx command in this hermetic test.
smite_tw_backhaul_quick_start() { echo "QUICK_START_ROLE:$1"; }
out="$(printf '1\n1\n0\n0\n' | smite_tw_menu)"
grep -Fq 'QUICK_START_ROLE:ir' <<< "$out"

# Role selection without Smite setup is explicit, never inferred from hostname/IP.
smite_bh_role() { return 1; }
out="$(printf '2\n0\n' | smite_tw_menu 2>/dev/null)"
grep -Fq 'host role: kh' <<< "$out"

# Opt-in IR pairing re-display is available in the same beginner flow;
# no code is emitted unless the operator types the exact consent phrase.
python3() { printf 'SAFE_MOCK_DISPLAY_MODE:%s\n' "$3"; }
out="$(printf '\n' | smite_tw_backhaul_offer_ir_code ir fresh)"
grep -Fq 'Private code hidden.' <<< "$out"
! grep -Fq 'SAFE_MOCK_DISPLAY_MODE:' <<< "$out"
out="$(printf 'DISPLAY-IR-PRIVATE-CODE\n' | smite_tw_backhaul_offer_ir_code ir fresh)"
grep -Fq 'SAFE_MOCK_DISPLAY_MODE:--show-ir' <<< "$out"
out="$(printf 'DISPLAY-IR-PRIVATE-CODE\n' | smite_tw_backhaul_offer_ir_code ir installed)"
grep -Fq 'SAFE_MOCK_DISPLAY_MODE:--show-installed-ir' <<< "$out"
out="$(smite_tw_backhaul_offer_ir_code kh fresh)"
! grep -Fq 'SAFE_MOCK_DISPLAY_MODE:' <<< "$out"
unset -f python3

# First-run Sidecar approval is a separately confirmed Step 0. The Python
# helper enforces trusted role and exclusive marker creation; never auto-approve.
id() { [ "${1:-}" = "-u" ] && printf '0\n'; }
APPROVAL_STATE=missing
python3() {
    case " $* " in
        *" --approval-status "*)
            if [ "$APPROVAL_STATE" = ready ]; then
                echo 'TEST_HOST_APPROVAL=READY'
                return 0
            fi
            echo 'TEST_HOST_APPROVAL=MISSING_OR_INVALID'
            return 2 ;;
        *" --approve-test-host "*)
            echo "APPROVE_COMMAND_CALLED"
            APPROVAL_STATE=ready
            return 0 ;;
        *) return 3 ;;
    esac
}
out="$(printf '\n' | smite_tw_backhaul_ensure_test_host_approval ir)" && {
    echo "ERROR: missing consent allowed Step 0"; exit 1
}
grep -Fq 'CANCELLED: No approval' <<< "$out"
! grep -Fq 'APPROVE_COMMAND_CALLED' <<< "$out"
out="$(printf 'I APPROVE DISPOSABLE BACKHAUL TEST HOST\n' | smite_tw_backhaul_ensure_test_host_approval ir)"
grep -Fq 'STEP 0: DISPOSABLE TEST HOST APPROVAL' <<< "$out"
grep -Fq 'APPROVE_COMMAND_CALLED' <<< "$out"
grep -Fq 'TEST_HOST_APPROVAL=READY' <<< "$out"
# Command-substitution tests run in separate subshells: persist the expected
# saved-marker condition explicitly in the parent fixture.
APPROVAL_STATE=ready
out="$(smite_tw_backhaul_ensure_test_host_approval ir)"
! grep -Fq 'STEP 0: DISPOSABLE TEST HOST APPROVAL' <<< "$out"
unset -f python3 id

# Sensitive material must not be printed or requested in the non-mutating wizard.
if grep -Eq 'cat .*\.token|cat .*\.toml|docker (update|run|rm|stop)|systemctl (reload|restart)|curl .*--insecure' modules/smite-tunnel-wizard.sh; then
    echo "FAIL: live mutation or sensitive credential exposure in wizard" >&2
    exit 1
fi

# Runtime regression: bash -n misses malformed [ ... ] commands.
# Exercise the real beginner quick-start with a synthetic existing journal,
# partial profile or installed Sidecar; do not access a real test VPS.
for scenario in journal journal_symlink profile container; do
    rc=0
    out="$(bash -c '
        source modules/smite-tunnel-wizard.sh
        SCENARIO="$1"
        # Intercept only our synthetic ownership probe; use the real
        # shell test builtin for every other check.
        function [() {
            if [[ "$#" == 3 && "$3" == "]" ]]; then
                if [[ "$SCENARIO" == "journal" && "$1" == "-e" &&
                      "$2" == "/var/lib/u-opti/backhaul-trial/kh" ]]; then
                    return 0
                fi
                if [[ "$SCENARIO" == "journal_symlink" && "$1" == "-L" &&
                      "$2" == "/var/lib/u-opti/backhaul-trial/kh" ]]; then
                    return 0
                fi
                if [[ "$SCENARIO" == "profile" && "$1" == "-e" &&
                      "$2" == "/etc/u-opti/backhaul-sidecar/kh.toml" ]]; then
                    return 0
                fi
            fi
            builtin [ "$@"
        }
        docker() {
            if [[ "$SCENARIO" == container && "$1" == container &&
                  "$2" == inspect && "$3" == uopti-backhaul-sidecar-kh ]]; then
                return 0
            fi
            return 1
        }
        smite_tw_backhaul_ensure_test_host_approval() {
            echo "BUG: existing host reached host approval"
            return 2
        }
        smite_tw_backhaul_quick_start kh
    ' bash "$scenario" 2>&1)" || rc=$?
    test "$rc" -eq 2
    grep -Fq 'HOLD: Sidecar trial/partial state detected' <<< "$out"
    ! grep -Fq 'BUG:' <<< "$out"
    ! grep -Fq 'missing ' <<< "$out"
done

echo 'PASS: Unified Tunnel Wizard roles, delegation, safe protocol guidance and packaging'
