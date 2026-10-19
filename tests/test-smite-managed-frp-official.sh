#!/usr/bin/env bash
# Official upstream v0.71.0 FRP role-binary verification, GitHub PR lab only.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != "true" || "${GITHUB_EVENT_NAME:-}" != "pull_request" ||
      "${GITHUB_REPOSITORY:-}" != "aghajani82/u-opti" || -z "${RUNNER_TEMP:-}" ]]; then
  echo "HOLD: official FRP artifact test requires disposable PR CI" >&2
  exit 2
fi
arch="${1:?architecture required}"
case "$arch" in
  amd64) expected="84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716" ;;
  arm64) expected="f33c293c275d8fc68c654b6fba8f10b2551d6463d09a9fc9cffb7227eae82266" ;;
  *) echo "HOLD: unexpected architecture" >&2; exit 2 ;;
esac
lab="$(mktemp -d "$RUNNER_TEMP/uopti-official-frp-XXXXXXXX")"
chmod 0700 "$lab"
trap 'rm -rf -- "$lab"' EXIT
mkdir -m 0700 "$lab/node" "$lab/node/config" "$lab/stages"
cat > "$lab/node/.env" <<'EOF_ENV'
NODE_ROLE=foreign
SMITE_AGENT_AUTH_MODE=strict
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_ENGINE_INVENTORY_MODE=managed
EOF_ENV
chmod 0600 "$lab/node/.env"
cat > "$lab/node/docker-compose.yml" <<'EOF_COMPOSE'
services:
  smite-node:
    image: smite-node:offline-fixture
    network_mode: host
    volumes:
      - ./config:/etc/smite-node
EOF_COMPOSE
chmod 0600 "$lab/node/docker-compose.yml"
asset="frp_0.71.0_linux_${arch}.tar.gz"
url="https://github.com/fatedier/frp/releases/download/v0.71.0/$asset"
curl --fail --silent --show-error --location --retry 3 --retry-delay 2 \
  --max-time 120 --output "$lab/$asset" "$url"
printf '%s  %s\n' "$expected" "$lab/$asset" | sha256sum --check --status
python3 -B - "$PWD" "$lab" "$arch" <<'PY'
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
repo, lab, arch = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
spec = importlib.util.spec_from_file_location("frp_official_ci", repo / "modules/smite-managed-frp.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
original = (lab / "node/docker-compose.yml").read_bytes()
archive = lab / f"frp_0.71.0_linux_{arch}.tar.gz"
stage = mod.prepare(lab / "node", archive, lab / "stages", arch=arch)
assert mod.verify(stage)
manifest = json.loads((stage / "engines.candidate.json").read_text())
expected = manifest["engines"]["frp"]
assert expected["sha256"] == hashlib.sha256((stage / "frpc.bin").read_bytes()).hexdigest()
assert expected["server_sha256"] == hashlib.sha256((stage / "frps.bin").read_bytes()).hexdigest()
assert not (lab / "node/config/engine-state/engines.json").exists()
assert (lab / "node/docker-compose.yml").read_bytes() == original
assert "backhaul" not in manifest["engines"]
assert "PORT_OR_TUNNEL_INPUT=NOT_REQUIRED" in (stage / "summary.txt").read_text()
print("OFFICIAL_FRP_ARCHIVE_SHA256=PASS")
print("OFFICIAL_FRPC_FRPS_ELF_PAIR=PASS")
print("FRP_ONLY_NO_BACKHAUL_PORT_OR_HOST_MUTATION=PASS")
PY
