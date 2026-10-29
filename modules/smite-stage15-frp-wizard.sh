#!/usr/bin/env bash
# Explicit disposable-host FRP flow. Core install never asks for tunnel ports.
smite_stage15_frp_wizard() {
    local dir role choice archive arch answer output stage peer
    dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 1
    role="$(hostname -s | tr '[:lower:]' '[:upper:]')"
    [[ "$EUID" == 0 && ( "$role" == IR || "$role" == KH ) ]] || { echo 'HOLD: Disposable IR/KH root only'; return 2; }
    while true; do
        echo "Stage15 FRP 0.71.0 — experimental — $role"
        echo '1) Install verified FRP engine (after Signed Pairing)'
        echo '2) Enable signed WSS runtime (after engine on BOTH hosts)'
        echo '3) IR: configure KH-only WSS/443 edge'
        echo '4) Verify signed WSS runtime'
        echo '5) Roll back WSS runtime (remove tunnels and IR edge first)'
        echo '6) IR: roll back WSS edge'
        echo '7) Recover interrupted WSS runtime'
        echo '8) IR: recover interrupted edge'
        echo '9) Roll back FRP engine (after WSS rollback)'
        echo 'G) IR: approve one XHTTP child grant (after signed owner/inbound review)'
        echo 'D) Download/verify reviewed Stage15 FRP071 images (no install)'
        echo 'U) Upgrade original Stage15 images before installing FRP'
        echo 'R) Roll back image upgrade (before FRP/WSS)'
        echo '0) Back'
        read -rp 'Choose: ' choice || return
        case "$choice" in
            1)
                case "$(uname -m)" in x86_64) arch=amd64;; aarch64) arch=arm64;; *) echo 'HOLD: Unsupported architecture'; continue;; esac
                archive="${UOPTI_FRP_ARCHIVE:-}"
                [[ -n "$archive" ]] || read -rp "Official frp_0.71.0_linux_${arch}.tar.gz path: " archive || return
                [[ "$archive" == /* && -f "$archive" && ! -L "$archive" ]] || { echo 'HOLD: Regular absolute archive path required'; continue; }
                echo 'Requires working Signed Pairing, provider snapshot and console. No tunnel or port will be created.'
                read -rp "Type INSTALL-STAGE15-FRP-$role to confirm snapshot/console and install: " answer || return
                [[ "$answer" == "INSTALL-STAGE15-FRP-$role" ]] || continue
                output="$(python3 -B "$dir/smite-managed-frp.py" prepare --archive "$archive" --arch "$arch")" || { echo "$output"; continue; }
                stage="$(printf '%s\n' "$output" | sed -n 's/^FRP_CANDIDATE_PREPARED=//p')"
                [[ "$stage" == /var/lib/u-opti/smite-engine-staging/frp-plan-* && "$stage" != *$'\n'* ]] || { echo 'HOLD: Invalid stage'; continue; }
                UOPTI_STAGE15_FRP_HOST_FIELD_TRIAL=YES python3 -B "$dir/smite-stage15-frp-host-executor.py" install --stage "$stage" --snapshot-confirm SNAPSHOTS-AND-CONSOLES-VERIFIED --role-confirm "$answer" || :
                ;;
            2) python3 -B "$dir/smite-stage15-wss.py" apply || :;;
            3)
                [[ "$role" == IR ]] || { echo 'Run this step on IR'; continue; }
                # Prepare the existing signed route bridge before cloning the TLS vhost.
                # A failed verification never permits the edge to bypass bridge admission.
                if ! python3 -B "$dir/smite-rc5-xhttp-bridge-install.py" verify; then
                    UOPTI_RC5_IR_XHTTP_BRIDGE_TRIAL=YES python3 -B "$dir/smite-rc5-xhttp-bridge-install.py" apply || continue
                fi
                read -rp 'Verified KH public egress IPv4: ' peer || return
                python3 -B "$dir/smite-stage15-wss-edge.py" apply --kh-ip "$peer" || :
                ;;
            4) python3 -B "$dir/smite-stage15-wss.py" verify || :;;
            5) python3 -B "$dir/smite-stage15-wss.py" rollback || :;;
            6) python3 -B "$dir/smite-stage15-wss-edge.py" rollback || :;;
            7) python3 -B "$dir/smite-stage15-wss.py" recover || :;;
            8) python3 -B "$dir/smite-stage15-wss-edge.py" recover || :;;
            9)
                read -rp "Type ROLLBACK-STAGE15-FRP-$role: " answer || return
                [[ "$answer" == "ROLLBACK-STAGE15-FRP-$role" ]] || continue
                UOPTI_STAGE15_FRP_HOST_FIELD_TRIAL=YES python3 -B "$dir/smite-stage15-frp-host-executor.py" rollback --role-confirm "$answer" || :
                ;;
            g|G)
                [[ "$role" == IR ]] || { echo 'Run root grant approval on IR'; continue; }
                python3 -B "$dir/smite-rc5-xhttp-broker-provision.py" --approve-grant --confirm-local-root || :;;
            d|D)
                echo 'Downloads only; no running Smite container, identity or Replay will be changed.'
                bash "$dir/smite-stage15-fetch-images.sh" || :;;
            u|U)
                archive="${SMITE_RC_BUNDLE_DIR:-}"
                if [[ -z "$archive" ]]; then
                    echo 'Checking pinned FRP071 prerelease asset cache / downloading once...'
                    bash "$dir/smite-stage15-fetch-images.sh" || continue
                    archive=/var/lib/u-opti/smite-stage15-frp071-images
                fi
                python3 -B "$dir/smite-stage15-upgrade.py" apply --images "$archive" || :;;
            r|R) python3 -B "$dir/smite-stage15-upgrade.py" rollback || :;;
            0) return;;
            *) echo 'Invalid choice';;
        esac
    done
}
