#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source modules/smite-backhaul-standard.sh
ir="$(uopti_bh_render_ir_control 3080)"
cli="$(bash modules/smite-backhaul-standard.sh --render-ir-control 3080)"
[[ "$cli" = "$ir" ]]
kh="$(uopti_bh_render_kh_bridge ir.kolbe1.ir 13080)"
data="$(uopti_bh_render_ir_xhttp 56053 /56053/www kh.kolbe1.ir)"
cli_data="$(bash modules/smite-backhaul-standard.sh --render-ir-xhttp 56053 /56053/www kh.kolbe1.ir)"
[[ "$cli_data" = "$data" ]]
grep -Fq 'location = /channel {' <<< "$ir"
grep -Fq 'location ^~ /tunnel/ {' <<< "$ir"
! grep -Fq 'location = /tunnel {' <<< "$ir"
grep -Fq 'location ^~ /tunnel/ {' <<< "$kh"
[[ "$(grep -Fc 'proxy_pass http://127.0.0.1:3080;' <<< "$ir")" = 2 ]]
grep -Fq 'Authorization $http_authorization;' <<< "$ir"
! grep -Fq 'location = /~!frp' <<< "$ir"
grep -Fq 'listen 127.0.0.1:13080;' <<< "$kh"
[[ "$(grep -Fc 'proxy_pass https://ir.kolbe1.ir:443;' <<< "$kh")" = 2 ]]
[[ "$(grep -Fc 'proxy_ssl_verify on;' <<< "$kh")" = 2 ]]
[[ "$(grep -Fc 'proxy_ssl_server_name on;' <<< "$kh")" = 2 ]]
[[ "$(grep -Fc 'proxy_ssl_name ir.kolbe1.ir;' <<< "$kh")" = 2 ]]
[[ "$(grep -Fc 'proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;' <<< "$kh")" = 2 ]]
grep -Fq 'location / { return 404; }' <<< "$kh"
grep -Fq 'location = /56053/www {' <<< "$data"
grep -Fq 'location ^~ /56053/www/ {' <<< "$data"
grep -Fq 'proxy_pass http://127.0.0.1:56053/56053/www/;' <<< "$data"
grep -Fq 'proxy_pass http://127.0.0.1:56053;' <<< "$data"
[[ "$(grep -Fc 'proxy_set_header Host kh.kolbe1.ir;' <<< "$data")" = 2 ]]
[[ "$(grep -Fc 'proxy_set_header X-Forwarded-Host $host;' <<< "$data")" = 2 ]]
! grep -Fq '/56053/web' <<< "$data"
! grep -Fq 'return 30' <<< "$data"
! grep -Fq '/18476/web' <<< "$data"
if uopti_bh_render_kh_bridge 'bad.com;include' 13080 >/dev/null; then exit 1; fi
if uopti_bh_render_ir_control 443 >/dev/null; then exit 1; fi
if uopti_bh_render_ir_xhttp 18476 >/dev/null; then exit 1; fi
if uopti_bh_render_ir_xhttp 56053 /56053/web 'bad;host' >/dev/null; then exit 1; fi
if uopti_bh_render_ir_xhttp 56053 /18476/web kh.kolbe1.ir >/dev/null; then exit 1; fi
if uopti_bh_render_ir_xhttp 56053 /56053/www/ kh.kolbe1.ir >/dev/null; then exit 1; fi
if uopti_bh_render_ir_xhttp 56053 '/56053/www;evil' kh.kolbe1.ir >/dev/null; then exit 1; fi
grep -Fq 'smite_frp_xhttp_sync()' modules/smite-frp-xhttp.sh
echo 'Backhaul Standard render-only tests passed'
