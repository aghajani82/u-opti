#!/usr/bin/env bash
# Disposable Actions runner. No host ports, network attachments or host service changes.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_ENVIRONMENT:-}" != github-hosted ]]; then
    echo 'This test requires a disposable GitHub-hosted Actions runner.' >&2
    exit 2
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
workspace="$(mktemp -d "${RUNNER_TEMP:?}/smite-panel-upgrade.XXXXXXXX")"
project="smite-upgrade-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
compose=(docker compose --project-name "$project" --project-directory "$workspace" -f "$workspace/compose.yml")
cleanup() {
    if "${compose[@]}" down --volumes --timeout 10 >/dev/null 2>&1; then
        rm -rf -- "$workspace"
    else
        echo 'Disposable Compose cleanup failed.' >&2
        return 1
    fi
}
trap cleanup EXIT

mapfile -t images < <(python3 - "$repo/modules" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
rc7 = json.loads((root / 'smite-rc7-registry-pair.json').read_text())
trial = json.loads((root / 'smite-unified-trial-registry-pair.json').read_text())
print(rc7['images']['panel'], rc7['images']['node'], trial['images']['panel'], sep='\n')
PY
)
old_panel="${images[0]}"
old_node="${images[1]}"
new_panel="${images[2]}"
for image in "$old_panel" "$old_node" "$new_panel"; do
    docker pull "$image" >/dev/null
done

umask 077
cat > "$workspace/.env" <<EOF
PANEL_IMAGE=$old_panel
NODE_IMAGE=$old_node
SMITE_FOREIGN_INSTALL_ENABLED=false
SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED=false
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
SMITE_NODE_PAIRING_MASTER_KEY=$(python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')
EOF
cat > "$workspace/compose.yml" <<'YAML'
services:
  smite-panel:
    image: ${PANEL_IMAGE:?}
    network_mode: none
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    tmpfs: [/tmp]
    volumes:
      - panel-data:/app/data
      - panel-certs:/app/certs
    env_file: .env
    environment:
      PANEL_HOST: 127.0.0.1
      DB_TYPE: sqlite
      DB_PATH: ./data/smite.db
      SMITE_NODE_REGISTRATION_MODE: signed
      SMITE_PANEL_AGENT_AUTH_MODE: signed
      SMITE_NODE_PAIRING_PREVIEW_ENABLED: 'true'
      SMITE_FOREIGN_INSTALL_ENABLED: ${SMITE_FOREIGN_INSTALL_ENABLED:?}
      SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED: ${SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED:?}
      NODE_CERT_PATH: /app/certs/ca.crt
      NODE_KEY_PATH: /app/certs/ca.key
      NODE_SERVER_CERT_PATH: /app/certs/ca-server.crt
      NODE_SERVER_KEY_PATH: /app/certs/ca-server.key
  smite-node:
    image: ${NODE_IMAGE:?}
    network_mode: none
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    tmpfs: [/tmp, /var/lib/smite-node, /etc/smite-node]
    environment:
      SMITE_NODE_PANEL_AUTH_MODE: paused
      SMITE_AGENT_AUTH_MODE: strict
      PANEL_ADDRESS: panel.example.com:443
volumes:
  panel-data:
  panel-certs:
YAML

wait_panel() {
    local version="$1" attempt
    for attempt in {1..45}; do
        if "${compose[@]}" exec -T smite-panel python3 -c '
import json, sys, urllib.request
base = "http://127.0.0.1:8000/api/status"
with urllib.request.urlopen(base, timeout=3) as r:
    assert r.status == 200
with urllib.request.urlopen(base + "/version", timeout=3) as r:
    assert json.load(r)["version"] == sys.argv[1]
' "$version" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    echo "Panel did not become ready at expected version $version." >&2
    return 1
}

"${compose[@]}" up -d --no-build --pull never
wait_panel 2.0.0-rc.7
node_id="$("${compose[@]}" ps -q smite-node)"
[[ -n "$node_id" ]]
node_started="$(docker inspect -f '{{.State.StartedAt}}' "$node_id")"
seed_panel_id="$("${compose[@]}" ps -q smite-panel)"
"${compose[@]}" exec -T smite-panel python3 - <<'PY'
import sqlite3
from app.node_pairing_store import initialize_schema
from app.signed_node_registration import initialize_replay_schema

path = './data/smite.db'
initialize_schema(path)
initialize_replay_schema(path)
with sqlite3.connect(path) as db:
    db.execute("INSERT INTO nodes(id,name,fingerprint,status,metadata) VALUES(?,?,?,?,?)",
               ('ci-iran-node', 'node-ir', 'ci-retained', 'active',
                '{"role":"iran","provisioning":"signed_checkin"}'))
    db.execute("INSERT INTO smite_node_identities VALUES(?,?,?,?,?)",
               ('ci-iran-node', 'iran', 'fixture-ciphertext', 1, None))
PY

# Keep the old process stopped during SQLite migration and the new flags off
# until the additive migration has been proven against this retained volume.
"${compose[@]}" stop smite-panel
PANEL_IMAGE="$new_panel" "${compose[@]}" run --rm --no-deps -T smite-panel \
    python3 -m app.foreign_install_migration --migrate --confirm PREPARE-FOREIGN-INSTALL-TRIAL-SCHEMA
PANEL_IMAGE="$new_panel" SMITE_FOREIGN_INSTALL_ENABLED=true \
    SMITE_FOREIGN_INSTALL_ORIGIN_TRUST_ENABLED=true \
    "${compose[@]}" up -d --no-deps --no-build --pull never smite-panel
wait_panel 2.0.0-unified-install-trial
candidate_id="$("${compose[@]}" ps -q smite-panel)"
[[ -n "$candidate_id" && "$candidate_id" != "$seed_panel_id" ]]
[[ "$(docker inspect -f '{{.Image}}' "$candidate_id")" == "$(docker image inspect -f '{{.Id}}' "$new_panel")" ]]

# Check the application sees the upgraded schema and rejects callers without
# an admin session. The existing ASGI suite separately exercises grant issuance.
"${compose[@]}" exec -T smite-panel python3 - <<'PY'
import asyncio
import urllib.error
import urllib.request
from app.config import settings
from app.routers.foreign_install import require_installation

assert settings.smite_foreign_install_origin_trust_enabled
assert asyncio.run(require_installation())
try:
    urllib.request.urlopen('http://127.0.0.1:8000/api/foreign-install/capabilities', timeout=5)
except urllib.error.HTTPError as exc:
    assert exc.code == 401
else:
    raise AssertionError('Foreign capabilities unexpectedly accessible without an admin session')
PY

# Restore only Panel runtime config. Reuse the same database and retained Node.
"${compose[@]}" up -d --no-deps --no-build --pull never smite-panel
wait_panel 2.0.0-rc.7
[[ "$("${compose[@]}" ps -q smite-node)" == "$node_id" ]]
[[ "$(docker inspect -f '{{.State.StartedAt}}' "$node_id")" == "$node_started" ]]
"${compose[@]}" exec -T smite-panel python3 - <<'PY'
from pathlib import Path
import sqlite3

with sqlite3.connect('file:/app/data/smite.db?mode=ro', uri=True) as db:
    assert db.execute('SELECT node_id,node_role,encrypted_secret FROM smite_node_identities').fetchall() == [
        ('ci-iran-node', 'iran', 'fixture-ciphertext')]
    assert db.execute("SELECT count(*) FROM smite_foreign_install_grants").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM smite_foreign_install_origins").fetchone() == (0,)
backup = Path('/app/data/smite.db.u-opti-pre-foreign-install-v1.bak')
assert backup.stat().st_mode & 0o777 == 0o600
with sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True) as db:
    assert db.execute('SELECT node_id FROM smite_node_identities').fetchall() == [('ci-iran-node',)]
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='smite_foreign_install_grants'").fetchone()
PY
echo 'DISPOSABLE_PANEL_COMPOSE_UPGRADE_AND_ROLLBACK=PASS'
echo 'RETAINED_NODE_CONTAINER_AND_START_TIME=PASS'
