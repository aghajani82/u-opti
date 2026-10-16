#!/usr/bin/env bash
# Test the two-host rebuild gate with hermetic mocked services/ports.
# Never calls real Docker, systemctl, Nginx, or a production host.
set -euo pipefail
cd "$(dirname "$0")/.."
bash -n modules/smite-backhaul-rebuild-gate.sh
root="$(mktemp -d)"
trap 'rm -rf -- "$root"' EXIT
mkdir -p "$root/bin"
cat > "$root/bin/python3" <<'MOCK'
#!/bin/bash
case "$*" in
    *smite-backhaul-sidecar-readiness.py*--role*--mode*)
        if [ "${MOCK_READINESS_FAIL:-0}" = 1 ]; then exit 2; fi
        echo 'MOCK LOCAL AUDIT OK'; exit 0 ;;
    *) exit 3 ;;
esac
MOCK
cat > "$root/bin/nginx" <<'MOCK'
#!/bin/bash
[ "$*" = "-t" ] || exit 2
[ "${MOCK_NGINX_FAIL:-0}" != 1 ]
MOCK
cat > "$root/bin/systemctl" <<'MOCK'
#!/bin/bash
[ "$1" = is-active ] || exit 2
if [ "${MOCK_SERVICE_FAIL:-0}" = 1 ]; then
    echo inactive; exit 3
fi
echo active
MOCK
for c in ss docker; do
    cat > "$root/bin/$c" <<'MOCK'
#!/bin/bash
echo 'MOCK ONLY'
MOCK
done
chmod 700 "$root/bin/"*
mock_path="$root/bin:$PATH"

out="$(env PATH="$mock_path" bash modules/smite-backhaul-rebuild-gate.sh --role ir --phase before-rebuild)"
grep -Fq 'Machine role: ir | phase: before-rebuild' <<< "$out"
grep -Fq 'LOCAL CHECKS PASSED. NOT A PERMISSION OR SIGNAL TO REBUILD.' <<< "$out"
grep -Fq 'Hetzner snapshot' <<< "$out"
grep -Fq 'third server' <<< "$out"
out="$(env PATH="$mock_path" bash modules/smite-backhaul-rebuild-gate.sh --role kh --phase fresh-baseline)"
grep -Fq 'Machine role: kh | phase: fresh-baseline' <<< "$out"
grep -Fq 'NOT A PERMISSION OR SIGNAL TO REBUILD' <<< "$out"

for bad in \
    '--role unknown --phase before-rebuild' \
    '--role ir --phase wrong' \
    '--phase before-rebuild'; do
    # Intentional splitting into arguments for these static test strings.
    if env PATH="$mock_path" bash modules/smite-backhaul-rebuild-gate.sh $bad > /dev/null 2>&1; then
        echo "Gate accepted invalid arguments: $bad" >&2
        exit 1
    fi
done
if env MOCK_NGINX_FAIL=1 PATH="$mock_path" bash modules/smite-backhaul-rebuild-gate.sh --role ir --phase before-rebuild > "$root/output"; then
    echo 'Gate accepted invalid Nginx' >&2; exit 1
fi
grep -Fq 'DO NOT REBUILD YET' "$root/output"
if env MOCK_READINESS_FAIL=1 PATH="$mock_path" bash modules/smite-backhaul-rebuild-gate.sh --role kh --phase fresh-baseline > "$root/output"; then
    echo 'Gate accepted missing sidecar baseline' >&2; exit 1
fi
grep -Fq 'LOCAL HOLD' "$root/output"
if env MOCK_SERVICE_FAIL=1 PATH="$mock_path" bash modules/smite-backhaul-rebuild-gate.sh --role ir --phase before-rebuild > "$root/output"; then
    echo 'Gate accepted inactive services' >&2; exit 1
fi
echo 'PASS: Rebuild gate only reports local health; provider snapshot consent always manual'
