#!/bin/bash

# U-OPTI - Smite Gateway ACME local probe hardening for clean-install testing.
# This override keeps the existing gateway flow intact while making the local
# webroot readiness check independent of proxy environment variables and a bit
# more tolerant of fresh Nginx package/reload timing.

smite_gateway_prepare_acme() {
    local domain="$1"
    local acme_conf="/etc/nginx/conf.d/u-opti-acme-${domain}.conf"
    local acme_test_file="$SMITE_GATEWAY_ACME_ROOT/.well-known/acme-challenge/u-opti-smite-test"
    local attempt
    local validated=false

    mkdir -p "$SMITE_GATEWAY_ACME_ROOT/.well-known/acme-challenge" || return 1
    chmod 0755 "$SMITE_GATEWAY_ACME_ROOT" \
        "$SMITE_GATEWAY_ACME_ROOT/.well-known" \
        "$SMITE_GATEWAY_ACME_ROOT/.well-known/acme-challenge" || return 1

    cat > "$acme_conf" <<EOF_ACME
# U-OPTI Smite ACME webroot
server {
    listen 80;
    listen [::]:80;
    server_name $domain;

    location ^~ /.well-known/acme-challenge/ {
        root $SMITE_GATEWAY_ACME_ROOT;
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        return 404;
    }
}
EOF_ACME

    nginx -t || return 1
    systemctl reload nginx || return 1

    printf '%s\n' 'u-opti-smite-acme-test' > "$acme_test_file" || return 1

    # Force the readiness probe to stay local even if the shell has HTTP(S)
    # proxy variables. Fresh Nginx package installs can also take a short time
    # to settle, so allow a longer bounded retry window and reload once midway.
    for attempt in $(seq 1 30); do
        if curl --noproxy '*' -4 -fsS \
            --connect-timeout 2 --max-time 5 \
            -H "Host: $domain" \
            http://127.0.0.1/.well-known/acme-challenge/u-opti-smite-test \
            2>/dev/null | grep -qx 'u-opti-smite-acme-test'; then
            validated=true
            break
        fi

        if [ "$attempt" -eq 10 ]; then
            systemctl reload nginx >/dev/null 2>&1 || true
        fi

        sleep 1
    done

    rm -f "$acme_test_file"

    if [ "$validated" != "true" ]; then
        echo "ERROR: Local ACME webroot validation failed after retries."
        echo "Diagnostic: Nginx config is valid, but the local challenge file was not served."
        echo "Check: curl --noproxy '*' -4 -H 'Host: $domain' http://127.0.0.1/.well-known/acme-challenge/..."
        return 1
    fi
}
