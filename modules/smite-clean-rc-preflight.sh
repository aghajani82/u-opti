#!/usr/bin/env bash
# Additive Clean-RC-only host gateway package preflight.
# The legacy Stable/Private Network installer remains unchanged.

smite_clean_rc_nginx_paths_ready() {
    [ -d /etc/nginx ] && [ ! -L /etc/nginx ] &&
        [ -d /var/log/nginx ] && command -v nginx >/dev/null 2>&1
}

smite_clean_rc_broker_code_ready() {
    local module_dir broker
    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    broker="$module_dir/smite-rc5-xhttp-broker-provision.py"
    [ -s "$broker" ] && [ ! -L "$broker" ] &&
        grep -Fq 'def _validate_nginx_config_dir' "$broker" &&
        grep -Fq 'ReadWritePaths=-/run/lock/u-opti-smite-engine.lock' "$broker" &&
        grep -Fq 'ReadWritePaths=-/run/lock/smite-xhttp-nginx-route.lock' "$broker" &&
        grep -Fq '_replace_existing_trusted_file(service, expected_unit, 0o644)' "$broker"
}

smite_clean_rc_prepare_gateway_packages() {
    [ "${SMITE_INSTALL_PROFILE:-stable}" = clean-rc ] || return 0

    smite_clean_rc_broker_code_ready || {
        echo "HOLD: Clean-RC broker modules are not at the required revision." >&2
        echo "Run Update U-OPTI again, then retry; no package or service change was made." >&2
        return 1
    }

    local module_dir confirm=""
    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if ! declare -F smite_gateway_ensure_packages >/dev/null 2>&1; then
        [ -s "$module_dir/smite-gateway.sh" ] && [ ! -L "$module_dir/smite-gateway.sh" ] || {
            echo "HOLD: Clean-RC Nginx gateway package helper is not staged." >&2
            return 1
        }
        # shellcheck source=/dev/null
        source "$module_dir/smite-gateway.sh" || return 1
    fi
    declare -F smite_gateway_ensure_packages >/dev/null 2>&1 || {
        echo "HOLD: Clean-RC Nginx gateway package helper is unavailable." >&2
        return 1
    }

    echo
    echo "Clean-RC Root Broker requires host Nginx before the Panel + Node install."
    echo "This prepares Nginx, Certbot and the stream module only; domain/TLS gateway"
    echo "configuration remains a separate step after the Panel is healthy."
    read -rp "Install/enable the host gateway packages now? [y/N]: " confirm
    case "$confirm" in
        y|Y|yes|YES) ;;
        *) echo "HOLD: Host gateway packages were not prepared; no Smite files were created." >&2; return 1 ;;
    esac

    smite_gateway_ensure_packages || {
        echo "HOLD: Host Nginx/Certbot/stream package preparation failed." >&2
        return 1
    }
    smite_clean_rc_nginx_paths_ready || {
        echo "HOLD: Nginx package preparation did not create the required host paths." >&2
        return 1
    }
    echo "CLEAN_RC_NGINX_PREREQUISITE=PASS"
}
