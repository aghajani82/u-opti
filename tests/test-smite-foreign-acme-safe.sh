#!/usr/bin/env bash
# Foreign option-2 ACME preparation, tested against isolated paths.
# No host Nginx, certificate, Docker, network, apt or live service changes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
source "$ROOT/modules/smite-foreign-gateway.sh"
mkdir -p "$TMP/nginx" "$TMP/acme"
SMITE_FOREIGN_ACME_ROOT="$TMP/acme"
DOMAIN=kh.example.org
SITE="$TMP/nginx/u-opti-acme-$DOMAIN.conf"
smite_foreign_gateway_acme_conf_path() {
    printf '%s/nginx/u-opti-acme-%s.conf\n' "$TMP" "$1"
}
nginx() { [ "$*" = "-t" ]; }
systemctl() { [ "$*" = "reload nginx" ]; }
curl() { printf 'u-opti-smite-foreign-acme-test\n'; }
sleep() { :; }

# A complete, identical managed file is safe to reuse on next option-2
# invocation after an interruption. It must never be written in-place.
smite_foreign_gateway_prepare_acme "$DOMAIN"
[ -f "$SITE" ] && [ ! -L "$SITE" ]
[ "$(stat -c %a "$SITE")" = 644 ]
smite_foreign_gateway_render_acme "$DOMAIN" | cmp -s - "$SITE"
before="$(sha256sum "$SITE" | cut -d' ' -f1)"
smite_foreign_gateway_prepare_acme "$DOMAIN"
[ "$(sha256sum "$SITE" | cut -d' ' -f1)" = "$before" ]
[ "$(find "$TMP/nginx" -name '.u-opti-foreign-acme.*' | wc -l)" -eq 0 ]
[ ! -e "$SMITE_FOREIGN_ACME_ROOT/.well-known/acme-challenge/u-opti-smite-foreign-test" ]

# Reject unrelated/conflicting Nginx config BEFORE reloading or
# overwriting a shared site.
printf '# independent vhost\n' > "$SITE"
if smite_foreign_gateway_prepare_acme "$DOMAIN" > "$TMP/conflict-log" 2>&1; then
    echo 'FAIL: independent ACME vhost was overwritten'; exit 1
fi
grep -q 'Existing Foreign ACME Nginx site' "$TMP/conflict-log"
grep -qx '# independent vhost' "$SITE"
rm -f "$SITE"

# Reject symlink even when it appears to contain the candidate.
protected="$TMP/protected"
printf '# independent protected config\n' > "$protected"
ln -s "$protected" "$SITE"
if smite_foreign_gateway_prepare_acme "$DOMAIN" > "$TMP/symlink-log" 2>&1; then
    echo 'FAIL: symlink ACME site was adopted'; exit 1
fi
grep -qx '# independent protected config' "$protected"
[ -L "$SITE" ]
rm -f "$SITE"

# Failed rendering before commit leaves NO managed conf, no temp file.
(
    smite_foreign_gateway_render_acme() {
        printf '# interrupted while rendering\n'
        return 9
    }
    if smite_foreign_gateway_prepare_acme "$DOMAIN" > "$TMP/render-log" 2>&1; then
        echo 'FAIL: interrupted render accepted'; exit 1
    fi
)
[ ! -e "$SITE" ]
[ "$(find "$TMP/nginx" -name '.u-opti-foreign-acme.*' | wc -l)" -eq 0 ]

# Atomic exclusive link must refuse a failed publish without dropping
# an unfinished file into the live nginx include directory.
(
    ln() { return 1; }
    if smite_foreign_gateway_prepare_acme "$DOMAIN" > "$TMP/link-log" 2>&1; then
        echo 'FAIL: failed exclusive publish accepted'; exit 1
    fi
)
[ ! -e "$SITE" ]
[ "$(find "$TMP/nginx" -name '.u-opti-foreign-acme.*' | wc -l)" -eq 0 ]

# If Nginx validation stops AFTER a full publish, the next invocation
# verifies EXACT same bytes and resumes; it never rewrites/rotates.
(
    nginx() { return 1; }
    if smite_foreign_gateway_prepare_acme "$DOMAIN" > "$TMP/nginx-fail" 2>&1; then
        echo 'FAIL: failed nginx validation accepted'; exit 1
    fi
)
[ -f "$SITE" ]
smite_foreign_gateway_render_acme "$DOMAIN" | cmp -s - "$SITE"
smite_foreign_gateway_prepare_acme "$DOMAIN"

# Even a matching but permission-drifted candidate is NOT adopted.
chmod 0600 "$SITE"
if smite_foreign_gateway_prepare_acme "$DOMAIN" > "$TMP/mode-fail" 2>&1; then
    echo 'FAIL: permission-drifted candidate accepted'; exit 1
fi
chmod 0644 "$SITE"

# Never accept malformed traversal or hostname strings as ACME files.
for bad in '../etc/passwd' '-invalid.example.org' 'kh.example.org/other'; do
    if smite_foreign_gateway_prepare_acme "$bad" > "$TMP/bad-domain" 2>&1; then
        echo 'FAIL: unsafe foreign ACME domain accepted'; exit 1
    fi
done
echo 'FOREIGN_ACME_NO_CLOBBER_ATOMIC_AND_RETRY=PASS'
