#!/usr/bin/env bash
# Regression: legacy 0.15.2 fixed-list updater must not omit Standard FRP helpers.
set -euo pipefail
grep -Fq '"smite-frp-wizard.sh"' install.sh
grep -Fq '"smite-frp-xhttp.sh"' install.sh
grep -Fq '"smite-frp-xhttp-paths.py"' install.sh
grep -Fq '"smite-frp-wizard.sh"' u-opti
grep -Fq '"smite-frp-xhttp.sh"' u-opti
grep -Fq '"smite-frp-xhttp-paths.py"' u-opti
grep -Fq 'u_opti_ensure_standard_frp_bundle()' u-opti
grep -Fq 'if ! u_opti_ensure_standard_frp_bundle; then' u-opti
bash -n u-opti
bash -n modules/smite-frp-wizard.sh
bash -n modules/smite-frp-xhttp.sh
python3 -B -c 'import ast; ast.parse(open("modules/smite-frp-xhttp-paths.py").read())'

test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
python3 - "$test_root/bootstrap.sh" <<'PY'
from pathlib import Path
import sys
script = Path("u-opti").read_text()
begin = "# BEGIN: U-OPTI legacy Standard FRP bundle upgrade compatibility"
end = "# END: U-OPTI legacy Standard FRP bundle upgrade compatibility"
assert script.count(begin) == 1 and script.count(end) == 1
Path(sys.argv[1]).write_text(script.split(begin, 1)[1].split(end, 1)[0])
PY
# Test on an empty install using a mock curl that serves the checked-out modules.
mkdir -p "$test_root/modules" "$test_root/bin"
cat > "$test_root/bin/curl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
dest='' url=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o) dest="$2"; shift 2 ;;
        *smite-frp-wizard.sh*|*smite-frp-xhttp.sh*|*smite-frp-xhttp-paths.py*) url="$1"; shift ;;
        *) shift ;;
    esac
done
[ -n "$dest" ] && [ -n "$url" ]
file="${url%%\?*}"
file="${file##*/}"
cp "$FRP_TEST_FIXTURES/$file" "$dest"
MOCK
chmod +x "$test_root/bin/curl"
export FRP_TEST_FIXTURES="$PWD/modules"
export PATH="$test_root/bin:$PATH"
MODULES_PATH="$test_root/modules"
BASE_URL="https://example.invalid"
# The extracted body contains no unrelated menu/bootstrap side effects.
source "$test_root/bootstrap.sh"
test -s "$MODULES_PATH/smite-frp-wizard.sh"
test -s "$MODULES_PATH/smite-frp-xhttp.sh"
test -s "$MODULES_PATH/smite-frp-xhttp-paths.py"
cmp -s "$MODULES_PATH/smite-frp-wizard.sh" modules/smite-frp-wizard.sh
cmp -s "$MODULES_PATH/smite-frp-xhttp.sh" modules/smite-frp-xhttp.sh
cmp -s "$MODULES_PATH/smite-frp-xhttp-paths.py" modules/smite-frp-xhttp-paths.py
# Idempotence: the complete bundle must work without contacting the network.
cat > "$test_root/bin/curl" <<'MOCK'
#!/usr/bin/env bash
exit 77
MOCK
chmod +x "$test_root/bin/curl"
u_opti_ensure_standard_frp_bundle
echo "Legacy Standard FRP updater bootstrap: PASS"
