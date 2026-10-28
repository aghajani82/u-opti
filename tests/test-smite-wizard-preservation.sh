#!/usr/bin/env bash
# Existing non-Smite wizard/Private Network sources stay pinned. The user
# explicitly selected fresh IR/KH rebuilds over legacy migration. The Smite
# installer now has reviewed clean-RC broker/mount integration paths; pin its
# accepted full source blob below so later wizard drift still fails closed.
# The pinned installer also auto-selects Standard *only* in clean-rc mode.
# 2026-10-27: re-pin to the current reviewed main installer after its
# clean-RC broker/admin-helper integrations; no installer bytes change here.
# Stable image pull/overlay isolation is checked separately by
# tests/test-smite-clean-install.sh. During the final Field Trial, the only
# reviewed changes to docker.sh and smite-install.sh include numeric menu
# input normalization. On 2026-10-28 only the sanitized Broker HOLD diagnostic
# in smite-install.sh was deliberately changed and its entire reviewed blob
# was re-pinned; all other wizard sources remain pinned against drift.
# 2026-10-28 PR #65: re-pin the reviewed installer after the isolated KH-only
# paused/strict Sanaei attachment guard and its explicit Foreign Gateway menu
# entry. Existing independent/private setup wizard blobs remain unchanged.
# The Clean-RC safety and signed KH compatibility suites test behavior.
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
f843733acece4afe2d3c86e6e454470caf4241c3 modules/smite-install.sh
6c1caec04219f420c554ad3cc1cde4a998ffbf09 modules/smite-private-network.sh
0d2d12f759ee8e2bc18e67d17606b63cb353bef1 modules/smite-easytier.sh
de089fe29f3225cf8afe4f284444e683c9502689 modules/smite-setup-progress.sh
a9188a6996710da0887b6415afa8e6ddc261c362 modules/smite-setup-progress-flow.sh
d2c9f5a799545179e74e0edba1816d9751eec8ac modules/smite-setup-progress-actions.sh
57a5430c925c3cd0f9993926be33f0ba0beacca5 modules/smite-setup-progress-ui.sh
1ae5f900a0018170658a8f69220e316ff9faf80a modules/smite-setup-progress-compact-ui.sh
BASELINE
if ! grep -Fq 'export U_OPTI_BRANCH="$BRANCH"' u-opti; then
    echo "ERROR: Installed source ref is not propagated to lazily fetched wizard modules." >&2
    exit 1
fi
echo 'PASS: Installed U-OPTI source ref is inherited by the Smite setup wizard'
echo 'PASS: Existing independent wizards pinned; reviewed Field Trial menu-normalization blobs accepted'
