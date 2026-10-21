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

# Signed-registry Field Trial: exact vendored manifest + real admission helper,
# with Cosign mocked only inside this isolated regression.
grep -q 'smite-registry-pair-admission.py' "$ROOT/u-opti"
grep -q 'smite-field-trial-candidate.json' "$ROOT/u-opti"
grep -q 'smite-registry-pair-admission.py' "$ROOT/install.sh"
grep -q 'smite-field-trial-candidate.json' "$ROOT/install.sh"
[ "$(/usr/bin/sha256sum "$ROOT/modules/smite-field-trial-candidate.json" | awk '{print $1}')" = \
  "7044e417e6a6cb2b87dfd0271cec70dcf23cf01d47412a3f604fed8130c30986" ]

mkdir -p "$TMP/bin"
cat > "$TMP/bin/cosign" <<'PY_COSIGN'
#!/usr/bin/env python3
import json, sys
args=sys.argv[1:]
ref=args[-1]
role="panel" if "smite-panel@" in ref else "node"
digest=ref.split("@",1)[1]
source=next(x.split("=",1)[1] for x in args if x.startswith("smite_source_sha="))
print(json.dumps([{
    "critical":{"type":"cosign container image signature",
                "image":{"docker-manifest-digest":digest}},
    "optional":{"smite_source_sha":source,"smite_role":role}
}]))
PY_COSIGN
chmod 0700 "$TMP/bin/cosign"
OLD_PATH="$PATH"
PATH="$TMP/bin:$PATH"
sha256sum() {
    if [ "$1" = "$TMP/bin/cosign" ]; then
        printf '%s  %s\n' "$SMITE_FIELD_TRIAL_COSIGN_SHA256" "$1"
    else
        /usr/bin/sha256sum "$@"
    fi
}
SMITE_RC_SIGNED_REGISTRY=1
SMITE_FIELD_TRIAL_APPROVED=YES
MOCK_WRONG_PANEL_ID=0
# Signed registry is a separate source path. It must NOT inherit or require
# the old Stage15 local bundle/source/manifest variables.
unset SMITE_RC_BUNDLE_DIR SMITE_RC_SOURCE_SHA SMITE_RC_MANIFEST_SHA256
: > "$TMP/docker-calls.log"
smite_install_clean_rc_preflight panel-iran standard >"$TMP/signed-preflight.log"
grep -q 'PANEL_NODE_IMMUTABLE_DIGEST_SIGNATURES=VERIFIED' "$TMP/signed-preflight.log"
grep -q 'FIELD_TRIAL_SIGNED_REGISTRY=VERIFIED' "$TMP/signed-preflight.log"
[ "$SMITE_PANEL_IMAGE" = "ghcr.io/aghajani82/smite-panel@sha256:6cfaec4a961f1c03eb05c684b41c001ce73178ee20231517aafced1dc972aadb" ]
[ "$SMITE_NODE_IMAGE" = "ghcr.io/aghajani82/smite-node@sha256:bb4992698fc637719a489ec6e9a8384a5c898e9afeb6cae16fcfc41a626b482c" ]
smite_install_pull_images true >"$TMP/signed-pull.log"
grep -Fq "pull $SMITE_PANEL_IMAGE" "$TMP/docker-calls.log"
grep -Fq "pull $SMITE_NODE_IMAGE" "$TMP/docker-calls.log"
! grep -q '^load$' "$TMP/docker-calls.log"
grep -q 'CLEAN_RC_IMAGES=SIGNED_REGISTRY_DIGESTS_VERIFIED' "$TMP/signed-pull.log"

SMITE_FIELD_TRIAL_APPROVED=NO
if smite_install_clean_rc_preflight foreign standard >/dev/null 2>&1; then
    echo "FAIL: signed Field Trial accepted without explicit approval" >&2; exit 1
fi
SMITE_FIELD_TRIAL_APPROVED=YES
SMITE_RC_SIGNED_REGISTRY=0
unset -f sha256sum
PATH="$OLD_PATH"

SMITE_INSTALL_PROFILE=stable
SMITE_NODE_IMAGE="ghcr.io/zzedix/smite-node@sha256:$(python3 -c 'print("b"*64)')"
: > "$TMP/docker-calls.log"
smite_install_pull_images false >/dev/null
grep -q '^pull ghcr.io/zzedix/smite-node' "$TMP/docker-calls.log"
smite_install_apply_compatibility >/dev/null
[ "$(wc -l < "$TMP/overlay-calls")" = 3 ]
# Exercise the real interactive selection flow with all side-effectful steps
# replaced by inert functions. A 3/4-line input must reach confirmation:
# there must be NO connection-mode question in the clean RC profile.
SMITE_INSTALL_PROFILE=clean-rc
SMITE_FRP_TRIAL_ONLY=0
smite_install_require_tools() { :; }
smite_install_ensure_docker() { :; }
smite_install_validate_domain() { return 0; }
smite_install_validate_name() { return 0; }
smite_install_pause() { :; }
clear() { :; }
smite_install_clean_rc_preflight() {
    echo "$1:$2" >> "$TMP/mode-preflight.log"
    return 1  # Stop before any directories, Docker, or network calls.
}
printf 'ir.example.com\nnode-ir\ny\n' |
    smite_install_panel_iran >"$TMP/ir-selection.log" 2>&1
grep -qx 'panel-iran:standard' "$TMP/mode-preflight.log"
grep -q 'Connection mode: Standard (automatic for clean install)' "$TMP/ir-selection.log"
grep -q 'Smite profile: clean-rc (unpublished preview)' "$TMP/ir-selection.log"
grep -q 'PREVIEW ONLY:' "$TMP/ir-selection.log"
printf 'ir.example.com\nkh.example.com\nnode-kh\ny\n' |
    smite_install_foreign_node >"$TMP/kh-selection.log" 2>&1
grep -qx 'foreign:standard' "$TMP/mode-preflight.log"
grep -q 'Connection mode: Standard / HTTPS (automatic for clean install)' "$TMP/kh-selection.log"
grep -q 'PREVIEW ONLY:' "$TMP/kh-selection.log"
[ "$(wc -l < "$TMP/mode-preflight.log")" = 2 ]

# Stable profile retains the explicit mode selection. Abort on an invalid
# answer before a live install step; it must not silently select Standard.
SMITE_INSTALL_PROFILE=stable
printf 'ir.example.com\nnode-ir\n9\n' |
    smite_install_panel_iran >"$TMP/stable-ir.log" 2>&1
grep -q 'Invalid connection mode' "$TMP/stable-ir.log"
printf 'ir.example.com\nkh.example.com\nnode-kh\n9\n' |
    smite_install_foreign_node >"$TMP/stable-kh.log" 2>&1
grep -q 'Invalid connection mode' "$TMP/stable-kh.log"
[ "$(wc -l < "$TMP/mode-preflight.log")" = 2 ]
[ ! -e "$SMITE_STATE_FILE" ]
[ ! -e "$SMITE_PANEL_COMPOSE" ]
[ ! -e "$SMITE_NODE_COMPOSE" ]
echo "CLEAN_FRESH_PROFILE_TESTS=PASSED"
