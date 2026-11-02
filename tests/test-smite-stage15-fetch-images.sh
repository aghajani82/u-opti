#!/usr/bin/env bash
# Offline, root-owned negative tests for the Stage15 immutable prerelease fetch.
# No internet requests, Docker, servers or real image downloads are involved.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
bash -n "$root/modules/smite-stage15-fetch-images.sh"
grep -Fq 'UOPTI_STAGE15_SOURCE=6981bd91b43811fad8847da9abd81ef99a921003' "$root/modules/smite-stage15-fetch-images.sh"
grep -Fq 'UOPTI_STAGE15_MANIFEST_SHA=0b34ee3fbd9174e6bf7ef6ddf145f7ebcd606c9bbeae176bb3d6a38b8a2a7840' "$root/modules/smite-stage15-fetch-images.sh"
grep -Fq 'stage15-frp071-6981bd91' "$root/modules/smite-stage15-fetch-images.sh"
grep -Fq '"smite-stage15-fetch-images.sh"' "$root/install.sh"
grep -Fq '["smite-stage15-fetch-images.sh"]="$BASE_URL/modules/smite-stage15-fetch-images.sh"' "$root/u-opti"
grep -Fq '["smite-stage15-fetch-images.sh"]="$TEMP_DIR/smite-stage15-fetch-images.sh"' "$root/u-opti"
grep -Fq 'bash "$image_fetcher"' "$root/u-opti"
grep -Fq 'archive=/var/lib/u-opti/smite-stage15-frp071-images' "$root/modules/smite-stage15-frp-wizard.sh"

# The integration must not accidentally accept the old uploaded rc.0 source,
# and must leave the helper inert until a typed user-initiated install.
python3 - "$root" <<'PY_CHECK'
from pathlib import Path
import sys
root=Path(sys.argv[1])
script=(root/'modules/smite-stage15-fetch-images.sh').read_text()
assert '4e16633a304db6c03f7f2911cc7d77213b0c4ec1' not in script
assert 'smite-clean-image-pair.py' in script
assert 'sha256sum' in script and 'sync -f' in script
assert "curl --fail --silent --show-error --location" in script
assert '--proto-redir' in script and "'=https'" in script
assert 'docker load' not in script.lower() and 'docker compose' not in script.lower()
entry=(root/'u-opti').read_text()
assert entry.index('! bash "$image_fetcher"') < entry.index('SMITE_INSTALL_PROFILE=clean-rc',entry.index('if [ "${1:-}" = "--smite-clean-rc" ]; then'))
PY_CHECK

if [[ $EUID != 0 ]]; then
    echo 'HOLD: root test fixture required' >&2
    exit 2
fi
tmp="$(mktemp -d /root/smite-fetch-test-XXXXXXXX)"
trap 'rm -rf -- "$tmp"' EXIT
source "$root/modules/smite-stage15-fetch-images.sh"
UOPTI_STAGE15_CACHE="$tmp/cache"
hostname() { printf 'ir\n'; }
uname() { printf 'x86_64\n'; }

# Network failure must fail closed with no installed assets or Docker action.
curl() { return 22; }
if uopti_stage15_fetch_images >/dev/null 2>&1; then
    echo 'ERROR: missing release was accepted' >&2
    exit 1
fi
test ! -f "$UOPTI_STAGE15_CACHE/stage15-images.json"

# A successful HTTP response carrying forged bytes also has to fail.
curl() {
    local p=''
    while (($#)); do
        if [[ "$1" == --output ]]; then p="$2";shift 2;else shift;fi
    done
    test -n "$p"
    printf 'untrusted-old-image\n' > "$p"
}
if uopti_stage15_fetch_images >/dev/null 2>&1; then
    echo 'ERROR: invalid prerelease checksum was accepted' >&2
    exit 1
fi
test ! -f "$UOPTI_STAGE15_CACHE/stage15-images.json"
test -z "$(find "$UOPTI_STAGE15_CACHE" -name '.incoming.*' -print -quit)"

# A corrupt cached file must not be silently replaced by a later download.
printf 'tampered\n' > "$UOPTI_STAGE15_CACHE/stage15-images.json"
chmod 0600 "$UOPTI_STAGE15_CACHE/stage15-images.json"
curl() { echo 'ERROR: unexpected refetch of untrusted cached file' >&2;return 10; }
if uopti_stage15_fetch_images >/dev/null 2>&1; then
    echo 'ERROR: tampered cached manifest was accepted' >&2
    exit 1
fi
grep -Fq tampered "$UOPTI_STAGE15_CACHE/stage15-images.json"
echo 'PASS: pinned Stage15 automatic image download fails closed on missing, forged and tampered release assets'
