#!/usr/bin/env bash
# User constraint: the existing guided IR/KH and Private Network flow must
# remain unchanged while developing experimental FRP / shared-domain support.
# All originally pinned wizard files remain unchanged except the explicitly
# reviewed Smite Node local-only API bind addition to smite-install.sh.
# This SHA pins that intentional Standard-mode change; other baselines stay fixed.
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
f71a00a9f465e5beb9ac5eedd86f175caaeeb80d modules/docker.sh
200f513b91eed567e4fe45c9fbb3e34565177b50 modules/smite-install.sh
6c1caec04219f420c554ad3cc1cde4a998ffbf09 modules/smite-private-network.sh
0d2d12f759ee8e2bc18e67d17606b63cb353bef1 modules/smite-easytier.sh
de089fe29f3225cf8afe4f284444e683c9502689 modules/smite-setup-progress.sh
a9188a6996710da0887b6415afa8e6ddc261c362 modules/smite-setup-progress-flow.sh
d2c9f5a799545179e74e0edba1816d9751eec8ac modules/smite-setup-progress-actions.sh
57a5430c925c3cd0f9993926be33f0ba0beacca5 modules/smite-setup-progress-ui.sh
1ae5f900a0018170658a8f69220e316ff9faf80a modules/smite-setup-progress-compact-ui.sh
BASELINE
echo 'PASS: All original Smite setup, IR/KH role steps, and Private Wizard files unchanged'
