#!/usr/bin/env bash
# Regression: one-pass upgrades from a fixed-file updater must self-heal the
# newly introduced inert signed Field Trial verifier+manifest on next exec.
set -euo pipefail

grep -Fq '"smite-registry-pair-admission.py"' install.sh
grep -Fq '"smite-field-trial-candidate.json"' install.sh
grep -Fq '"smite-registry-pair-admission.py"' u-opti
grep -Fq '"smite-field-trial-candidate.json"' u-opti
grep -Fq 'u_opti_ensure_signed_field_trial_bundle()' u-opti
grep -Fq 'if ! u_opti_ensure_signed_field_trial_bundle; then' u-opti
bash -n u-opti
python3 -B -c 'import ast; ast.parse(open("modules/smite-registry-pair-admission.py").read())'

test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
python3 - "$test_root/bootstrap.sh" <<'PY'
from pathlib import Path
import sys
script = Path("u-opti").read_text()
begin = "# BEGIN: U-OPTI signed Field Trial bundle upgrade compatibility"
end = "# END: U-OPTI signed Field Trial bundle upgrade compatibility"
assert script.count(begin) == 1 and script.count(end) == 1
Path(sys.argv[1]).write_text(script.split(begin, 1)[1].split(end, 1)[0])
PY

mkdir -p "$test_root/modules" "$test_root/bin"
cat > "$test_root/bin/curl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
dest='' url=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o) dest="$2"; shift 2 ;;
        *smite-registry-pair-admission.py*|*smite-field-trial-candidate.json*) url="$1"; shift ;;
        *) shift ;;
    esac
done
[ -n "$dest" ] && [ -n "$url" ]
file="${url%%\?*}"
file="${file##*/}"
cp "$SIGNED_TEST_FIXTURES/$file" "$dest"
MOCK
chmod +x "$test_root/bin/curl"

export SIGNED_TEST_FIXTURES="$PWD/modules"
export PATH="$test_root/bin:$PATH"
MODULES_PATH="$test_root/modules"
BRANCH="066b5a8b29fb23f869390bb3df783274e797a6d7"
BASE_URL="https://example.invalid/$BRANCH"

# Sourcing the extracted compatibility body simulates the first restart after
# an older updater installed the new u-opti executable but omitted new files.
source "$test_root/bootstrap.sh"

test -s "$MODULES_PATH/smite-registry-pair-admission.py"
test -s "$MODULES_PATH/smite-field-trial-candidate.json"
cmp -s "$MODULES_PATH/smite-registry-pair-admission.py" modules/smite-registry-pair-admission.py
cmp -s "$MODULES_PATH/smite-field-trial-candidate.json" modules/smite-field-trial-candidate.json
[ "$(sha256sum "$MODULES_PATH/smite-field-trial-candidate.json" | awk '{print $1}')" = \
  "d364bd48ee12288ae67dc0e6c15fcc9d15e43ae73cf82c3c33da242890b4f65f" ]

# Idempotence: once complete, restart must not contact the network.
cat > "$test_root/bin/curl" <<'MOCK'
#!/usr/bin/env bash
exit 77
MOCK
chmod +x "$test_root/bin/curl"
u_opti_ensure_signed_field_trial_bundle

# If repair is needed, a mutable ref is never trusted.
rm -f "$MODULES_PATH/smite-field-trial-candidate.json"
BRANCH=main
BASE_URL="https://example.invalid/main"
if u_opti_ensure_signed_field_trial_bundle >/dev/null 2>&1; then
    echo "FAIL: mutable ref accepted for signed Field Trial bootstrap" >&2
    exit 1
fi

echo "Signed Field Trial legacy updater bootstrap: PASS"
