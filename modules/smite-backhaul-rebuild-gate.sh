#!/usr/bin/env bash
# U-OPTI Backhaul two-host rebuild gate: READ ONLY.
# Does not verify Hetzner snapshots. No server mutation or secret printing.
# Intended for optional IR/KH check BEFORE destructive rebuild and AFTER base
# Smite/FRP/Xray/Nginx have been installed on the rebuilt host.
set -uo pipefail

bh_gate_role=""
bh_gate_phase=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --role) [ "$#" -ge 2 ] || exit 2; bh_gate_role="$2"; shift 2 ;;
        --phase) [ "$#" -ge 2 ] || exit 2; bh_gate_phase="$2"; shift 2 ;;
        *) echo "Usage: $0 --role ir|kh --phase before-rebuild|fresh-baseline" >&2; exit 2 ;;
    esac
done
case "$bh_gate_role" in ir|kh) ;; *) echo "HOLD: select IR or KH explicitly" >&2; exit 2 ;; esac
case "$bh_gate_phase" in before-rebuild|fresh-baseline) ;;
    *) echo "HOLD: select before-rebuild or fresh-baseline" >&2; exit 2 ;;
esac

bh_gate_holds=0
bh_gate_show() {
    printf '%-33s : %s\n' "$1" "$2"
}
bh_gate_cmd_status() {
    local cmd="$1"
    if command -v "$cmd" >/dev/null 2>&1; then
        bh_gate_show "$cmd" "found"
    else
        bh_gate_show "$cmd" "MISSING"
        bh_gate_holds=$((bh_gate_holds+1))
    fi
}
bh_gate_service() {
    local name="$1" value
    value="$(systemctl is-active "$name" 2>/dev/null)" || :
    case "$value" in
        active) bh_gate_show "$name" active ;;
        *) bh_gate_show "$name" "NOT ACTIVE"; bh_gate_holds=$((bh_gate_holds+1)) ;;
    esac
}

printf '\n===== U-OPTI BACKHAUL TWO-HOST REBUILD GATE =====\n'
printf 'Machine role: %s | phase: %s | READ-ONLY\n' "$bh_gate_role" "$bh_gate_phase"
echo 'NOTE: Check Hetzner snapshot readiness manually before any Rebuild.'
echo 'NOTE: This script cannot inspect provider snapshots or confirm rollback.'
echo 'NOTE: Do not run on the third, actively used production server.'
printf '\n--- Local prerequisites ---\n'
for cmd in nginx docker ss python3 systemctl; do bh_gate_cmd_status "$cmd"; done
if command -v systemctl >/dev/null 2>&1; then
    bh_gate_service nginx
    bh_gate_service docker
fi
if command -v nginx >/dev/null 2>&1; then
    if nginx -t >/dev/null 2>&1; then
        bh_gate_show "nginx -t" OK
    else
        bh_gate_show "nginx -t" FAILED
        bh_gate_holds=$((bh_gate_holds+1))
    fi
fi

printf '\n--- Sidecar role health ---\n'
bh_gate_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bh_gate_audit="$bh_gate_dir/smite-backhaul-sidecar-readiness.py"
if [ -s "$bh_gate_audit" ] && command -v python3 >/dev/null 2>&1; then
    if [ "$bh_gate_phase" = before-rebuild ]; then
        bh_gate_check=existing
    else
        bh_gate_check=new
    fi
    if python3 -B "$bh_gate_audit" --role "$bh_gate_role" --mode "$bh_gate_check"; then
        bh_gate_show "Local role audit" PASSED
    else
        bh_gate_show "Local role audit" "HOLD"
        bh_gate_holds=$((bh_gate_holds+1))
    fi
else
    bh_gate_show "Local role audit" "MISSING MODULE"
    bh_gate_holds=$((bh_gate_holds+1))
fi

echo
echo "--- Mandatory OPERATOR confirmations (NOT machine-verifiable) ---"
echo "[ ] A restorable Hetzner snapshot exists for THIS exact server."
echo "[ ] Restore path and Hetzner rescue/console access verified."
echo "[ ] SSH private key access + potential changed SSH host fingerprint understood."
echo "[ ] Any changes since snapshot can be lost safely."
echo "[ ] Required domains/DNS/TLS and credentials can be restored privately."
echo "[ ] Working third server is excluded from the rebuild."
echo "[ ] Expected VPN downtime is acceptable and a non-VPN access path exists."
echo "[ ] IR and KH will NEVER be rebuilt/restarted at the same time."
echo
if [ "$bh_gate_holds" -eq 0 ]; then
    echo "LOCAL CHECKS PASSED. NOT A PERMISSION OR SIGNAL TO REBUILD."
    echo "Provider snapshot verification and operator approval still required."
else
    printf 'LOCAL HOLD: %s failed/unverified checks. DO NOT REBUILD YET.\n' "$bh_gate_holds"
    exit 2
fi
