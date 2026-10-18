#!/usr/bin/env bash
# Simulated clean install, no real Docker or network calls.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bundle" "$TMP/fresh" "$TMP/overlay"
export SMITE_INSTALL_PROFILE=clean-rc
export SMITE_RC_BUNDLE_DIR="$TMP/bundle"
export SMITE_RC_SOURCE_SHA="eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
export SMITE_STATE_DIR="$TMP/fresh"
export SMITE_OVERLAY_DIR="$TMP/overlay"
python3 - "$TMP/bundle" <<'PY'
import gzip, hashlib, json, pathlib, sys
root=pathlib.Path(sys.argv[1]); images={}
for role in ("panel","node"):
    name=f"smite-{role}-stage15.docker.tar.gz"
    body=gzip.compress(("UNIT-TEST-"+role).encode())
    (root/name).write_bytes(body)
    images[role]={"file":name,"archive_sha256":hashlib.sha256(body).hexdigest(),
                  "bytes":len(body),
                  "local_image_id":"sha256:"+("a" if role=="panel" else "b")*64}
m={"schema":1,"kind":"smite_offline_preview_images",
   "source_repo":"aghajani82/Smite", "source_commit":"e"*40,
   "proposed_version":"2.0.0-rc.0","image_format":"docker-save-gzip",
   "images":images,"signed":False,"registry_digest_verified":False,
   "runtime_security_verified":False,"activation_allowed":False}
(root/"stage15-images.json").write_text(json.dumps(m))
PY
export SMITE_RC_MANIFEST_SHA256
SMITE_RC_MANIFEST_SHA256="$(sha256sum "$SMITE_RC_BUNDLE_DIR/stage15-images.json" | cut -d' ' -f1)"
source "$ROOT/modules/smite-install.sh"
SMITE_PANEL_DIR="$TMP/fresh/panel"
SMITE_NODE_DIR="$TMP/fresh/node"
SMITE_PANEL_COMPOSE="$SMITE_PANEL_DIR/docker-compose.yml"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"
SMITE_STATE_FILE="$TMP/fresh/state.env"
MOCK_WRONG_PANEL_ID=0
smite_container_exists() { return 1; }
docker() {
    echo "$*" >> "$TMP/docker-calls.log"
    if [ "$1" = image ] && [ "$2" = inspect ]; then
        if [ "$3" = smite-panel:stage15-local ]; then
            if [ "$MOCK_WRONG_PANEL_ID" = 1 ]; then
                python3 -c 'print("sha256:"+"c"*64)'
            else
                python3 -c 'print("sha256:"+"a"*64)'
            fi
        else
            python3 -c 'print("sha256:"+"b"*64)'
        fi
    elif [ "$1" = load ]; then
        cat >/dev/null
    elif [ "$1" = pull ]; then
        :
    else
        echo "Unexpected Docker call: $*" >&2; return 1
    fi
}
smite_prepare_overlays() { echo prepare >> "$TMP/overlay-calls"; }
smite_patch_compose_mounts() { echo patch >> "$TMP/overlay-calls"; }
smite_recreate_with_overlays_noninteractive() { echo restart >> "$TMP/overlay-calls"; }

smite_install_clean_rc_preflight panel-iran standard >/dev/null
[ "$SMITE_PANEL_IMAGE" = smite-panel:stage15-local ]
[ "$SMITE_NODE_IMAGE" = smite-node:stage15-local ]
smite_install_pull_images true >/dev/null
smite_install_apply_compatibility > "$TMP/rc-compat.txt"
grep -q 'CLEAN_RC_SECOND_CONTAINER_RECREATE=SKIPPED' "$TMP/rc-compat.txt"
[ ! -e "$TMP/overlay-calls" ]
[ "$(grep -c '^load$' "$TMP/docker-calls.log")" = 2 ]
! grep -q '^pull ' "$TMP/docker-calls.log"

: > "$TMP/docker-calls.log"
smite_install_clean_rc_preflight foreign standard >/dev/null
smite_install_pull_images false >/dev/null
[ "$(grep -c '^load$' "$TMP/docker-calls.log")" = 1 ]

echo 'SMITE_ROLE=foreign' > "$SMITE_STATE_FILE"
if smite_install_clean_rc_preflight foreign standard >/dev/null 2>&1; then
    echo "FAIL: accepted old state" >&2; exit 1
fi
rm "$SMITE_STATE_FILE"
if smite_install_clean_rc_preflight foreign private >/dev/null 2>&1; then
    echo "FAIL: private mode accepted" >&2; exit 1
fi
MOCK_WRONG_PANEL_ID=1
if smite_install_pull_images true >/dev/null 2>&1; then
    echo "FAIL: accepted wrong loaded image ID" >&2; exit 1
fi
SMITE_RC_MANIFEST_SHA256="$(python3 -c 'print("0"*64)')"
if smite_install_clean_rc_preflight foreign standard >/dev/null 2>&1; then
    echo "FAIL: accepted wrong expected manifest SHA" >&2; exit 1
fi

SMITE_INSTALL_PROFILE=stable
SMITE_NODE_IMAGE="ghcr.io/zzedix/smite-node@sha256:$(python3 -c 'print("b"*64)')"
: > "$TMP/docker-calls.log"
smite_install_pull_images false >/dev/null
grep -q '^pull ghcr.io/zzedix/smite-node' "$TMP/docker-calls.log"
smite_install_apply_compatibility >/dev/null
[ "$(wc -l < "$TMP/overlay-calls")" = 3 ]
echo "CLEAN_FRESH_PROFILE_TESTS=PASSED"
