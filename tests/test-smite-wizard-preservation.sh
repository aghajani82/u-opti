#!/usr/bin/env bash
# Existing non-Smite wizard/Private Network sources stay pinned. The user
# explicitly selected fresh IR/KH rebuilds over legacy migration, so the
# Smite installer now has one reviewed, default-OFF clean-rc addition.
# The pinned installer also auto-selects Standard *only* in clean-rc mode.
# Stable image pull/overlay isolation is checked separately by
# tests/test-smite-clean-install.sh. During the final Field Trial, the only
# intentional changes to docker.sh and smite-install.sh are numeric menu-input
# normalization (CR/whitespace trimming); their reviewed blob SHAs are pinned
# here so any further wizard drift still fails closed.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
while read -r expected file; do
    [[ -z "${expected:-}" || "${expected:0:1}" == '#' ]] && continue
    if [ ! -f "$file" ]; then
        echo "ERROR: Existing Smite wizard file missing: $file" >&2
        exit 1
    fi
    actual="$(git hash-object "$file")"
    if [ "$actual" != "$expected" ]; then
        echo "ERROR: Existing guided setup changed unexpectedly: $file" >&2
        echo "Expected $expected, got $actual" >&2
        echo "This experimental PR must not rewrite the user's existing wizard." >&2
        exit 1
    fi
    echo "PRESERVED: $file"
done <<'BASELINE'
9061db13973f677cbeb78a45796d038d8eff0389 modules/docker.sh
cc89de17ff50cc6b82f27283235d846576b51ac8 modules/smite-install.sh
6c1caec04219f420c554ad3cc1cde4a998ffbf09 modules/smite-private-network.sh
0d2d12f759ee8e2bc18e67d17606b63cb353bef1 modules/smite-easytier.sh
de089fe29f3225cf8afe4f284444e683c9502689 modules/smite-setup-progress.sh
a9188a6996710da0887b6415afa8e6ddc261c362 modules/smite-setup-progress-flow.sh
d2c9f5a799545179e74e0edba1816d9751eec8ac modules/smite-setup-progress-actions.sh
57a5430c925c3cd0f9993926be33f0ba0beacca5 modules/smite-setup-progress-ui.sh
1ae5f900a0018170658a8f69220e316ff9faf80a modules/smite-setup-progress-compact-ui.sh
BASELINE
echo 'PASS: Existing independent wizards pinned; reviewed Field Trial menu-normalization blobs accepted'
