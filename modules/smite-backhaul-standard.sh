#!/usr/bin/env bash
# Safe design prototype only. Does not install, modify files or reload services.
uopti_bh_valid_port() {
    local p="$1"
    [[ "$p" =~ ^[0-9]{1,5}$ ]] || return 1
    (( 10#$p >= 1024 && 10#$p <= 65535 )) || return 1
    case "$p" in 443|7000|8000|8443|8888|18476) return 1 ;; esac
}
uopti_bh_valid_domain() {
    local d="$1"
    [[ "$d" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$ && "$d" == *.* && "$d" != *..* ]] || return 1
}
uopti_bh_render_ir_control() {
    local p="$1" path
    [ -n "$p" ] || p=3080
    uopti_bh_valid_port "$p" || return 1
    echo "# IR: Include within existing HTTPS backend; Backhaul WS must bind 127.0.0.1:$p"
    for path in '/channel' '/tunnel/'; do
        if [ "$path" = /channel ]; then echo "    location = $path {"; else echo "    location ^~ $path {"; fi
        cat <<EOF
        proxy_pass http://127.0.0.1:$p;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Authorization \$http_authorization;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
EOF
    done
}
uopti_bh_render_kh_bridge() {
    local domain="$1" p="$2" path
    [ -n "$p" ] || p=13080
    uopti_bh_valid_domain "$domain" && uopti_bh_valid_port "$p" || return 1
    cat <<EOF
# KH: Backhaul client uses WS on loopback; Nginx verifies HTTPS certificate of IR.
server {
    listen 127.0.0.1:$p;
    server_name localhost;
EOF
    for path in '/channel' '/tunnel/'; do
        if [ "$path" = /channel ]; then echo "    location = $path {"; else echo "    location ^~ $path {"; fi
        cat <<EOF
        proxy_pass https://$domain:443;
        proxy_http_version 1.1;
        proxy_ssl_server_name on;
        proxy_ssl_name $domain;
        proxy_ssl_verify on;
        proxy_ssl_verify_depth 4;
        proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
        proxy_set_header Host $domain;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Authorization \$http_authorization;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
EOF
    done
    printf '%s\n' '    location / { return 404; }' '}'
}
uopti_bh_render_ir_xhttp() {
    local p="$1" typ
    [ -n "$p" ] || p=56053
    uopti_bh_valid_port "$p" || return 1
    echo "# IR: add only AFTER Backhaul data listener 127.0.0.1:$p is verified."
    for typ in exact prefix; do
        if [ "$typ" = exact ]; then echo "    location = /$p/web {"; else echo "    location ^~ /$p/web/ {"; fi
        cat <<EOF
        proxy_pass http://127.0.0.1:$p;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
EOF
    done
}
if [[ "$0" == "${BASH_SOURCE[0]}" ]]; then
    case "$1" in
        --render-ir-control) uopti_bh_render_ir_control "$2" ;;
        --render-kh-bridge) uopti_bh_render_kh_bridge "$2" "$3" ;;
        --render-ir-xhttp) uopti_bh_render_ir_xhttp "$2" ;;
        *) echo "Usage: $0 --render-ir-control [3080] | --render-kh-bridge IR_DOMAIN [13080] | --render-ir-xhttp [56053]" >&2; exit 2 ;;
    esac
fi
