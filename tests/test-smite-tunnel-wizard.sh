#!/usr/bin/env bash
# Safe, hermetic shell tests: no live host actions and no Docker calls.
set -euo pipefail
cd "$(dirname "$0")/.."

bash -n modules/smite-tunnel-wizard.sh
grep -Fq '"smite-tunnel-wizard.sh"' install.sh
grep -Fq '"smite-tunnel-wizard.sh"' u-opti
grep -Fq '"smite-backhaul-sidecar.py"' install.sh
grep -Fq '"smite-backhaul-sidecar.py"' u-opti
grep -Fq 'smite_tw_backhaul_prepare()' modules/smite-tunnel-wizard.sh
grep -Fq 'smite_tw_backhaul_readiness()' modules/smite-tunnel-wizard.sh
grep -Fq '"smite-backhaul-sidecar-readiness.py"' install.sh
grep -Fq '"smite-backhaul-sidecar-readiness.py"' u-opti
grep -Fq 'IR HTTPS domain (required)' modules/smite-tunnel-wizard.sh
grep -Fq 'KH upstream/Xray Host domain (required)' modules/smite-tunnel-wizard.sh
grep -Fq '["smite-tunnel-wizard.sh"]="$BASE_URL/modules/smite-tunnel-wizard.sh"' u-opti
grep -Fq '["smite-tunnel-wizard.sh"]="$TEMP_DIR/smite-tunnel-wizard.sh"' u-opti
grep -Fq 'smite_tw_menu()' modules/smite-tunnel-wizard.sh
grep -Fq 'source "$SMITE_BH_DIR/smite-tunnel-wizard.sh"' modules/smite-backhaul-management.sh
grep -Fq '5) Tunnel Setup Wizard' modules/smite-backhaul-management.sh

smite_bh_role() { echo ir; }
source modules/smite-tunnel-wizard.sh
smite_tw_clear() { :; }
smite_tw_pause() { :; }

test "$(smite_tw_role)" = ir
test "$(smite_tw_result ready)" = READY
test "$(smite_tw_result missing)" = "NOT FOUND"

ir_out="$(smite_tw_backhaul_overview ir)"
grep -Fq '127.0.0.1:3080' <<< "$ir_out"
grep -Fq '/56053/www/' <<< "$ir_out"
kh_out="$(smite_tw_backhaul_overview kh)"
grep -Fq '127.0.0.1:13080' <<< "$kh_out"
grep -Fq 'BLOCKED' <<< "$kh_out"

profile="$(smite_tw_backhaul_client)"
grep -Fq 'ALPN: http/1.1' <<< "$profile"
grep -Fq 'xPaddingBytes' <<< "$profile"
grep -Fq 'TLS: on' <<< "$profile"

steps="$(smite_tw_backhaul_steps ir)"
grep -Fq 'REVIEW ONLY' <<< "$steps"
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
smite_frp_wizard_menu() { echo FRP_DELEGATE_CALLED; }
out="$(printf '2\n0\n' | smite_tw_menu)"
grep -Fq FRP_DELEGATE_CALLED <<< "$out"
out="$(printf '1\n1\n0\n0\n' | smite_tw_menu)"
grep -Fq 'Backhaul v0.7.2' <<< "$out"
out="$(printf '3\n2\n23333\n45000\n0\n0\n' | smite_tw_menu)"
grep -Fq 'NO INSTALL' <<< "$out"

# Unit-test the new menu routes without ever calling host inspection.
smite_tw_backhaul_readiness() { echo "READINESS_CALLED:$1:$2"; }
out="$(printf '1\n6\n0\n0\n' | smite_tw_menu)"
grep -Fq 'READINESS_CALLED:ir:existing' <<< "$out"
out="$(printf '1\n7\n0\n0\n' | smite_tw_menu)"
grep -Fq 'READINESS_CALLED:ir:new' <<< "$out"

# Role selection without Smite setup is explicit, never inferred from hostname/IP.
smite_bh_role() { return 1; }
out="$(printf '2\n0\n' | smite_tw_menu 2>/dev/null)"
grep -Fq 'host role: kh' <<< "$out"

# Sensitive material must not be printed or requested in the non-mutating wizard.
if grep -Eq 'cat .*\.token|cat .*\.toml|docker (update|run|rm|stop)|systemctl (reload|restart)|curl .*--insecure' modules/smite-tunnel-wizard.sh; then
    echo "FAIL: live mutation or sensitive credential exposure in wizard" >&2
    exit 1
fi

echo 'PASS: Unified Tunnel Wizard roles, delegation, safe protocol guidance and packaging'
