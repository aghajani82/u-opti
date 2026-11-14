#!/bin/bash

set -e

# U-OPTI installer requires root privileges.
if [ "$EUID" -ne 0 ]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "Error: Root privileges are required, but sudo is not installed."
        exit 1
    fi
    exec sudo -E bash "$0" "$@"
fi

BRANCH="${U_OPTI_BRANCH:-main}"
if [[ ! "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || [[ "$BRANCH" == *".."* ]] || [[ "$BRANCH" == /* ]]; then
    echo "ERROR: Invalid U-OPTI source branch/ref."
    exit 1
fi
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$BRANCH"
# BEGIN: U-OPTI immutable per-operation source pin
# Resolve once; never download a mixture of mutable branch revisions.
u_opti_resolve_source_sha() {
    local ref="$1" response
    if [[ ! "$ref" =~ ^[A-Za-z0-9._/-]+$ ]] ||
       [[ "$ref" == *".."* ]] || [[ "$ref" == /* ]]; then
        return 1
    fi
    response="$(curl -fsSL --retry 2 --connect-timeout 10 --max-time 30 \
        -H 'Accept: application/vnd.github+json' \
        -H 'X-GitHub-Api-Version: 2022-11-28' \
        "https://api.github.com/repos/aghajani82/u-opti/commits/$ref")" || return 1
    printf '%s' "$response" | python3 -c '
import json
import re
import sys
data = json.load(sys.stdin)
sha = data.get("sha") if isinstance(data, dict) else None
if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
    sys.exit("UNTRUSTED_SOURCE_SHA")
print(sha)
'
}
# END: U-OPTI immutable per-operation source pin

INSTALL_PATH="/usr/local/bin/u-opti"
LIB_PATH="/usr/local/lib/u-opti"
MODULES_PATH="$LIB_PATH/modules"

# Resume/rollback a previous interrupted install/update BEFORE new downloads
# or package operations. Bundled rescue is not sourced through new modules.
if [ -e "$LIB_PATH/.uopti-update-pending" ] || [ -L "$LIB_PATH/.uopti-update-pending" ]; then
    RESCUE="$LIB_PATH/.uopti-update-pending/rescue.py"
    if [ ! -f "$RESCUE" ] || [ -L "$RESCUE" ] ||
       ! command -v python3 >/dev/null 2>&1 ||
       ! python3 -B "$RESCUE" recover; then
        echo "HOLD: Prior interrupted U-OPTI transaction requires recovery; installer stopped." >&2
        exit 1
    fi
    echo "Previous interrupted U-OPTI transaction restored before installation."
fi

MODULES=(
    "system.sh"
    "security-monitor.sh"
    "security-monitor.py"
    "time.sh"
    "swap.sh"
    "bbr.sh"
    "storage.sh"
    "ssh.sh"
    "ssh-access.sh"
    "firewall.sh"
    "fail2ban.sh"
    "xui-pro.sh"
    "certificate.sh"
    "backup.sh"
    "docker.sh"
    "smite.sh"
    "smite-node-local-bind.py"
    "smite-node-pairing.py"
    "smite-node-auth-candidate.py"
    "smite-node-replay-mount-admission.py"
    "smite-auth-image-overlay-audit.py"
    "smite-stage11-overlay-review.py"
    "smite-stage12-nginx-hmac-plan.py"
    "smite-stage19-pairing-443-plan.py"
    "smite-stage13-preflight.py"
    "smite-panel-auth-overlay.py"
    "smite-stage15-bundle-verify.py"
    "smite-clean-image-pair.py"
    "smite-registry-pair-admission.py"
    "smite-field-trial-candidate.json"
    "smite-rc6-install-journal.py"
    "smite-selected-candidate.json"
    "smite-rc7-registry-pair.json"
    "smite-unified-trial-registry-pair.json"
    "smite-unified-trial-pair-admission.py"
    "smite-foreign-install-panel-ingress.py"
    "smite-unified-panel-stage.py"
    "smite-unified-panel-transaction.py"
    "smite-unified-panel-cutover.py"
    "smite-foreign-install-client.py"
    "smite-foreign-install-promotion.py"
    "smite-unified-foreign-packet-intake.py"
    "smite-unified-foreign-gateway-plan.py"
    "smite-rc7-sigstore-trusted-root.json"
    "smite-panel-ui.py"
    "smite-panel-ui.json"
    "u-opti-update-transaction.py"
    "smite-foreign-gateway-signed-check.py"
    "smite-node-pairing-wizard.sh"
    "smite-digest-migrate.sh"
    "smite-install.sh"
    "smite-gateway.sh"
    "smite-frp-xhttp.sh"
    "smite-frp-xhttp-paths.py"
    # Exact reviewed Smite worker inputs, copied from feature HEAD 5540799300cab7dff89a81a1bfbde7d777c87d85.
    "smite-xhttp-nginx-route"
    "smite_xhttp_nginx_plan.py"
    "smite-rc5-xhttp-root-broker.py"
    "smite-rc5-xhttp-broker-provision.py"
    "smite-rc5-xhttp-broker-compose.py"
    "smite-rc5-xhttp-sanaei-mount.py"
    "smite-rc5-xhttp-nonce-ledger.py"
    "smite-rc5-xhttp-signed-intent.py"
    "smite-rc5-xhttp-bridge-install.py"
    "smite-rc5-xhttp-bridge-admission.py"
    "smite-frp-rc2-guided-publish.py"
    "smite-frp-wizard.sh"
    "smite-profile-first.py"
    "smite-profile-first-menu.sh"
    "smite-backhaul-management.sh"
    # Clean-RC host Nginx/Certbot preflight must be present on FIRST install,
    # not only after the first U-OPTI updater run.
    "smite-clean-rc-preflight.sh"
    "smite-clean-ir-resume.sh"
    "smite-tunnel-wizard.sh"
    "smite-tunnel-control-center.sh"
    "smite-managed-backhaul.py"
    "smite-managed-frp.py"
    "smite-managed-frp-transaction.py"
    "smite-stage15-frp-compose-plan.py"
    "smite-stage15-frp-host-executor.py"
    "smite-compose-safe.py"
    "smite-stage15-wss.py"
    "smite-rc7-wss-preflight.py"
    "smite-rc7-wss-runtime.py"
    "smite-rc7-wss-edge.py"
    "smite-rc7-frp-enrollment.py"
    "smite-stage15-active-runtime.py"
    "smite-stage15-kh-inventory.py"
    "smite-stage15-upgrade.py"
    "smite-stage15-wss-edge.py" "smite-stage15-xhttp-bridge.py" "smite-stage15-root-review.py"
    "smite-stage15-frp-wizard.sh"
    "smite-stage15-fetch-images.sh"
    "smite-rc2-frp-wss-edge-plan.py"
    "smite-managed-frp-control.py"
    "smite-managed-frp-menu.sh"
    "smite-managed-backhaul-control.py"
    "smite-managed-backhaul-menu.sh"
    "smite-managed-backhaul-host-gate.py"
    "smite-managed-backhaul-host-executor.py"
    "smite-managed-engine-host-admission.py"
    "smite-managed-engine-host-plan.py"
    "smite-managed-backhaul-pair-review.py"
    "smite-managed-backhaul-lifecycle.py"
    "smite-managed-backhaul-transaction.py"
    "smite-backhaul-sidecar.py"
    "smite-backhaul-sidecar-readiness.py"
    "smite-backhaul-sidecar-guided-prep.py"
    "smite-backhaul-sidecar-guided-trial.py"
    "smite-backhaul-sidecar-ssh-pair.py"
    "smite-backhaul-sidecar-paste-pair.py"
    "smite-backhaul-sidecar-admission.py"
    "smite-backhaul-sidecar-token.py"
    "smite-backhaul-sidecar-live-trial.py"
    "smite-backhaul-sidecar-reconcile.py"
    "smite-backhaul-rebuild-gate.sh"
    "smite-backhaul-sidecar-nginx-plan.py"
    "smite-backhaul-standard.sh"
    "smite-backhaul-spec.py"
    "smite-backhaul-node-patch.py"
    "smite-backhaul-panel-patch.py"
    "smite-foreign-gateway.sh"
    "smite-private-network.sh"
    "smite-easytier.sh"
    "docker-3xui.sh"
    "docker-3xui-instance.sh"
    "docker-3xui-certificate-multi.sh"
    "docker-3xui-compat.sh"
    "docker-3xui-nginx.sh"
    "docker-3xui-xhttp-guard.py"
    "fakesite.sh"
)

# Gate legacy adoption and uncertain partially installed states BEFORE
# the package-manager preflight or any download. Recheck after staging too.
if [ -L "$INSTALL_PATH" ] || [ -L "$LIB_PATH" ] || [ -L "$MODULES_PATH" ]; then
    echo "HOLD: Unsafe U-OPTI installation path (symlink)." >&2
    exit 1
fi
if [ -e "$INSTALL_PATH" ]; then
    if [ "${U_OPTI_ADOPT_EXISTING:-NO}" != "YES" ]; then
        echo "HOLD: Existing U-OPTI requires explicit migration approval." >&2
        echo "Use the normal Update menu for an already-supported version." >&2
        exit 1
    fi
elif [ -e "$LIB_PATH/common.sh" ] || [ -e "$LIB_PATH/VERSION" ]; then
    echo "HOLD: Incomplete prior install with no executable; review first." >&2
    exit 1
fi

echo "======================================"
echo "          Installing U-OPTI"
echo "======================================"
echo

if ! command -v curl >/dev/null 2>&1; then
    echo "Error: curl is required but is not installed."
    echo "Install it with: apt install curl"
    exit 1
fi

# BEGIN: U-OPTI installer activity indicator
# Keep actual work in the foreground: its exit status and errexit behavior
# must never depend on the animation. Non-terminal logs remain plain text.
INSTALL_ACTIVITY_PID=""
TEMP_DIR=""
u_opti_activity_stop() {
    if [ -n "$INSTALL_ACTIVITY_PID" ]; then
        kill "$INSTALL_ACTIVITY_PID" 2>/dev/null || true
        wait "$INSTALL_ACTIVITY_PID" 2>/dev/null || true
        INSTALL_ACTIVITY_PID=""
        printf '\n' >&2
    fi
}
u_opti_activity_start() {
    u_opti_activity_stop
    local label="$1"
    printf '%s...\n' "$label" >&2
    if [ -t 2 ] && [ "${TERM:-dumb}" != dumb ]; then
        (
            trap - EXIT INT TERM
            local frame=0 started=$SECONDS dots
            while :; do
                case $((frame % 3)) in
                    0) dots='.' ;;
                    1) dots='..' ;;
                    2) dots='...' ;;
                esac
                printf '\r  Working%-3s (%ds) ' "$dots" "$((SECONDS - started))" >&2
                frame=$((frame + 1))
                sleep 0.5
            done
        ) &
        INSTALL_ACTIVITY_PID=$!
    fi
}
cleanup() {
    u_opti_activity_stop
    if [ -n "$TEMP_DIR" ]; then
        rm -rf -- "$TEMP_DIR"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# END: U-OPTI installer activity indicator

echo "Checking required system packages..."

REQUIRED_PACKAGES=(
    "python3"
    "ca-certificates"
    "sqlite3"
    "jq"
)

MISSING_PACKAGES=()

for PACKAGE in "${REQUIRED_PACKAGES[@]}"; do
    if ! dpkg -s "$PACKAGE" >/dev/null 2>&1; then
        MISSING_PACKAGES+=("$PACKAGE")
    fi
done

if [ "${#MISSING_PACKAGES[@]}" -gt 0 ]; then
    if [ "${U_OPTI_ADOPT_EXISTING:-NO}" = "YES" ] && [ -f "$INSTALL_PATH" ]; then
        # A one-time migration updates ONLY U-OPTI files. It must not
        # install or upgrade host packages before the recoverable backup.
        # Package prerequisites can be reviewed separately after adoption.
        echo "Legacy U-OPTI adoption: skipping package changes."
        echo "Missing packages (not installed): ${MISSING_PACKAGES[*]}"
    else
        echo "Missing required packages: ${MISSING_PACKAGES[*]}"
        echo "Installing required system packages..."
        u_opti_activity_start "Refreshing system package lists"
        apt-get -qq -o DPkg::Lock::Timeout=300 update
        u_opti_activity_stop
        DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get -q -o DPkg::Lock::Timeout=300 install -y "${MISSING_PACKAGES[@]}"
    fi
fi

echo "System package preflight complete."
echo

TEMP_DIR=$(mktemp -d)

# Fail closed BEFORE downloading/committing any installation files.
u_opti_activity_start "Resolving verified source revision"
if ! SOURCE_SHA="$(u_opti_resolve_source_sha "$BRANCH")"; then
    u_opti_activity_stop
    echo "HOLD: GitHub source revision could not be verified; install cancelled." >&2
    exit 1
fi
u_opti_activity_stop
BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$SOURCE_SHA"
echo "Source revision locked for this installation: $SOURCE_SHA"

# BEGIN: U-OPTI installer bounded and verified GitHub downloads
# All files come from the single pinned commit. No live targets are modified
# until every staged byte has passed Git blob integrity and syntax checks.
u_opti_install_prepare_tree() {
    INSTALL_TREE_MANIFEST="$TEMP_DIR/.uopti-source-tree.json"
    if ! curl -4 -fsSL --retry 2 --retry-all-errors --retry-delay 1 \
        --connect-timeout 8 --max-time 35 --speed-limit 100 --speed-time 15 \
        -H 'Accept: application/vnd.github+json' \
        -H 'X-GitHub-Api-Version: 2022-11-28' \
        "https://api.github.com/repos/aghajani82/u-opti/git/trees/$SOURCE_SHA?recursive=1" \
        -o "$INSTALL_TREE_MANIFEST"; then
        echo "HOLD: Pinned GitHub source manifest could not be downloaded." >&2
        return 1
    fi
    python3 -B - "$INSTALL_TREE_MANIFEST" "${MODULES[@]}" <<'PY_INSTALL_TREE'
import json, pathlib, re, sys
try:
    tree = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    if (not isinstance(tree, dict) or tree.get("truncated") is not False
            or not re.fullmatch(r"[0-9a-f]{40}", str(tree.get("sha", "")))
            or not isinstance(tree.get("tree"), list)):
        raise ValueError("invalid or truncated Git tree")
    required = {"VERSION", "u-opti", "lib/common.sh"}
    required.update("modules/" + name for name in sys.argv[2:])
    seen = set()
    for item in tree["tree"]:
        if not isinstance(item, dict) or item.get("path") not in required:
            continue
        path = item["path"]
        if (path in seen or item.get("type") != "blob"
                or item.get("mode") not in ("100644", "100755")
                or type(item.get("size")) is not int
                or not 0 < item["size"] <= 10485760
                or not re.fullmatch(r"[0-9a-f]{40}", str(item.get("sha", "")))):
            raise ValueError("invalid or duplicate pinned file: " + path)
        seen.add(path)
    if seen != required:
        raise ValueError("pinned tree missing required files: " +
                         ", ".join(sorted(required - seen)))
except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
    sys.exit("HOLD: Untrusted GitHub source manifest: " + str(exc))
PY_INSTALL_TREE
}

# Prefer one immutable archive over hundreds of individual HTTP requests.
# Read selected regular files only; never extract archive paths or permissions.
u_opti_install_prepare_bundle() {
    local archive="$TEMP_DIR/.uopti-source.tar.gz"
    INSTALL_BUNDLE_DIR=""
    if ! curl -4 -fsSL --retry 0 --connect-timeout 8 --max-time 60 \
        --speed-limit 100 --speed-time 15 --max-filesize 33554432 \
        "https://codeload.github.com/aghajani82/u-opti/tar.gz/$SOURCE_SHA" \
        -o "$archive" 2>"$TEMP_DIR/.bundle-error"; then
        rm -f -- "$archive"
        return 1
    fi
    if ! python3 -B - "$INSTALL_TREE_MANIFEST" "$archive" "$TEMP_DIR/.bundle" "$SOURCE_SHA" "${MODULES[@]}" <<'PY_INSTALL_BUNDLE'
import hashlib, json, pathlib, sys, tarfile
try:
    manifest, archive, target, pin = sys.argv[1:5]
    required = {"VERSION", "u-opti", "lib/common.sh"}
    required.update("modules/" + name for name in sys.argv[5:])
    tree = json.loads(pathlib.Path(manifest).read_text())
    meta = {e["path"]: e for e in tree["tree"] if e.get("path") in required}
    if tree.get("truncated") is not False or set(meta) != required:
        raise ValueError("incomplete manifest")
    prefix = "u-opti-" + pin + "/"
    contents = {}
    expanded = 0
    with tarfile.open(archive, "r|gz") as bundle:
        for count, member in enumerate(bundle, 1):
            expanded += max(0, member.size)
            if count > 20000 or expanded > 134217728:
                raise ValueError("archive exceeds limits")
            if member.name == prefix.rstrip("/") and member.isdir():
                continue
            if not member.name.startswith(prefix):
                raise ValueError("unexpected archive root")
            name = member.name[len(prefix):]
            if name not in required:
                continue
            entry = meta[name]
            if (name in contents or not member.isfile()
                    or member.size != entry["size"] or not 0 < member.size <= 10485760):
                raise ValueError("invalid archive member: " + name)
            with bundle.extractfile(member) as stream:
                raw = stream.read(member.size + 1)
            digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if len(raw) != entry["size"] or digest != entry["sha"]:
                raise ValueError("archive checksum mismatch: " + name)
            contents[name] = raw
    if set(contents) != required:
        raise ValueError("archive missing required files")
    # Publish the cache only after the entire archive passes validation.
    root = pathlib.Path(target)
    root.mkdir(mode=0o700)
    for name, raw in contents.items():
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
except (OSError, ValueError, KeyError, TypeError, EOFError, tarfile.TarError) as exc:
    sys.exit("Bundle unavailable: " + str(exc))
PY_INSTALL_BUNDLE
    then
        rm -rf -- "$TEMP_DIR/.bundle"
        rm -f -- "$archive"
        return 1
    fi
    rm -f -- "$archive"
    INSTALL_BUNDLE_DIR="$TEMP_DIR/.bundle"
}

u_opti_install_verify_blob() {
    python3 -B - "$INSTALL_TREE_MANIFEST" "$1" "$2" <<'PY_INSTALL_CHECK'
import hashlib, json, pathlib, re, sys
try:
    manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    path, local_path = sys.argv[2:]
    if manifest.get("truncated") is not False:
        raise ValueError("untrusted pinned tree")
    entries = [entry for entry in manifest["tree"]
               if isinstance(entry, dict) and entry.get("path") == path]
    if len(entries) != 1:
        raise ValueError("missing or duplicated pinned path")
    meta = entries[0]
    expected, size = meta.get("sha"), meta.get("size")
    if (meta.get("type") != "blob" or meta.get("mode") not in ("100644", "100755")
            or type(size) is not int or not 0 < size <= 10485760
            or not isinstance(expected, str)
            or re.fullmatch(r"[0-9a-f]{40}", expected) is None):
        raise ValueError("invalid pinned blob metadata")
    raw = pathlib.Path(local_path).read_bytes()
    if len(raw) != size:
        raise ValueError("incomplete download")
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != expected:
        raise ValueError("pinned Git blob SHA mismatch")
except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
    sys.exit("HOLD: Download integrity check failed: " + str(exc))
PY_INSTALL_CHECK
}

u_opti_install_api_fallback() {
    local repo_path="$1" staged="$2" blob_sha="" response=""
    blob_sha="$(python3 -B - "$INSTALL_TREE_MANIFEST" "$repo_path" <<'PY_INSTALL_SHA'
import json, pathlib, re, sys
try:
    tree = json.loads(pathlib.Path(sys.argv[1]).read_text())
    entries = [entry for entry in tree["tree"]
               if isinstance(entry, dict) and entry.get("path") == sys.argv[2]]
    if len(entries) != 1 or not re.fullmatch(r"[0-9a-f]{40}", str(entries[0].get("sha", ""))):
        raise ValueError("invalid pinned blob")
    print(entries[0]["sha"])
except (OSError, ValueError, TypeError, KeyError) as exc:
    sys.exit("HOLD: No trusted GitHub fallback blob: " + str(exc))
PY_INSTALL_SHA
    )" || return 1
    response="$(mktemp "$TEMP_DIR/.uopti-api-XXXXXXXX")" || return 1
    if ! curl -4 -fsSL --retry 1 --retry-all-errors --retry-delay 1 \
        --connect-timeout 8 --max-time 40 --speed-limit 100 --speed-time 15 \
        -H 'Accept: application/vnd.github+json' \
        -H 'X-GitHub-Api-Version: 2022-11-28' \
        "https://api.github.com/repos/aghajani82/u-opti/git/blobs/$blob_sha" \
        -o "$response"; then
        rm -f -- "$response"
        return 1
    fi
    if ! python3 -B - "$response" "$blob_sha" "$staged" <<'PY_INSTALL_DECODE'
import base64, binascii, hashlib, json, pathlib, re, sys
try:
    value = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    expected = sys.argv[2]
    if (not isinstance(value, dict)
            or not re.fullmatch(r"[0-9a-f]{40}", expected)
            or value.get("sha") != expected
            or value.get("encoding") != "base64"
            or type(value.get("size")) is not int
            or not 0 < value["size"] <= 10485760
            or not isinstance(value.get("content"), str)):
        raise ValueError("invalid GitHub blob response")
    raw = base64.b64decode("".join(value["content"].split()), validate=True)
    if len(raw) != value["size"]:
        raise ValueError("incomplete fallback blob")
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != expected:
        raise ValueError("fallback blob checksum mismatch")
    pathlib.Path(sys.argv[3]).write_bytes(raw)
except (OSError, UnicodeError, ValueError, TypeError, KeyError,
        binascii.Error) as exc:
    sys.exit("HOLD: Invalid GitHub API fallback: " + str(exc))
PY_INSTALL_DECODE
    then
        rm -f -- "$response"
        return 1
    fi
    rm -f -- "$response"
    u_opti_install_verify_blob "$repo_path" "$staged"
}

u_opti_install_download() {
    local repo_path="$1" destination="$2" staged="" attempt
    if [[ ! "$repo_path" =~ ^(VERSION|u-opti|lib/common\.sh|modules/[a-zA-Z0-9._-]+)$ ]] ||
       [[ "$repo_path" == *".."* ]] ||
       [[ "$destination" != "$TEMP_DIR/"* ]] ||
       [ -L "$destination" ]; then
        echo "HOLD: Unsafe installer download path." >&2
        return 1
    fi
    if [ -n "${INSTALL_BUNDLE_DIR:-}" ]; then
        cp -- "$INSTALL_BUNDLE_DIR/$repo_path" "$destination" || return 1
        return 0
    fi
    staged="$(mktemp "$TEMP_DIR/.uopti-fetch-XXXXXXXX")" || return 1
    for attempt in 1 2; do
        if curl -4 -fsSL --retry 0 \
            --connect-timeout 8 --max-time 30 --speed-limit 100 --speed-time 15 \
            "$BASE_URL/$repo_path" -o "$staged" &&
           u_opti_install_verify_blob "$repo_path" "$staged"; then
            mv -f -- "$staged" "$destination" && return 0
            rm -f -- "$staged"
            return 1
        fi
        if [ "$attempt" -eq 1 ]; then
            echo "  Raw download unavailable; trying verified GitHub API: $repo_path" >&2
            if u_opti_install_api_fallback "$repo_path" "$staged"; then
                mv -f -- "$staged" "$destination" && return 0
                rm -f -- "$staged"
                return 1
            fi
            echo "  Verified API fallback unavailable; retrying raw once." >&2
        fi
        : > "$staged" || { rm -f -- "$staged"; return 1; }
    done
    rm -f -- "$staged"
    echo "HOLD: Download failed after bounded retries and verified fallback: $repo_path" >&2
    return 1
}
# END: U-OPTI installer bounded and verified GitHub downloads

u_opti_activity_start "Fetching and checking source manifest"
if ! u_opti_install_prepare_tree; then
    u_opti_activity_stop
    echo "Installation stopped before changing installed files." >&2
    exit 1
fi

u_opti_activity_stop

u_opti_activity_start "Downloading and verifying installation bundle"
if u_opti_install_prepare_bundle; then
    u_opti_activity_stop
    echo "Installation bundle verified (${#MODULES[@]} modules)."
else
    u_opti_activity_stop
    echo "Bundle unavailable; continuing with verified individual downloads."
fi

if [ -n "${INSTALL_BUNDLE_DIR:-}" ]; then
    echo "Preparing VERSION from verified bundle..."
else
    echo "Downloading VERSION..."
fi
u_opti_install_download "VERSION" "$TEMP_DIR/VERSION" || { echo "Failed to download VERSION."; exit 1; }
REMOTE_VERSION=$(tr -d '[:space:]' < "$TEMP_DIR/VERSION")
[ -n "$REMOTE_VERSION" ] || { echo "Error: Unable to determine U-OPTI version."; exit 1; }
echo "Remote Version: $REMOTE_VERSION"
echo

if [ -n "${INSTALL_BUNDLE_DIR:-}" ]; then
    echo "Preparing U-OPTI from verified bundle..."
else
    echo "Downloading U-OPTI..."
fi
u_opti_install_download "u-opti" "$TEMP_DIR/u-opti" || { echo "Failed to download u-opti."; exit 1; }

if [ -n "${INSTALL_BUNDLE_DIR:-}" ]; then
    echo "Preparing common library from verified bundle..."
else
    echo "Downloading common library..."
fi
u_opti_install_download "lib/common.sh" "$TEMP_DIR/common.sh" || { echo "Failed to download common.sh."; exit 1; }

DOWNLOAD_INDEX=0
for MODULE in "${MODULES[@]}"; do
    case "$MODULE" in
        system.sh) LABEL="System Information" ;;
        security-monitor.sh) LABEL="Security Monitoring Menu" ;;
        security-monitor.py) LABEL="Security Monitoring Engine" ;;
        time.sh) LABEL="Time & Date" ;;
        swap.sh) LABEL="Swap Management" ;;
        bbr.sh) LABEL="BBR Management" ;;
        storage.sh) LABEL="Storage Management" ;;
        ssh.sh) LABEL="SSH Management" ;;
        ssh-access.sh) LABEL="SSH Access Management" ;;
        firewall.sh) LABEL="Firewall Management" ;;
        fail2ban.sh) LABEL="Fail2Ban Management" ;;
        xui-pro.sh) LABEL="X-UI PRO Management" ;;
        certificate.sh) LABEL="Certificate Management" ;;
        backup.sh) LABEL="Backup & Restore" ;;
        docker.sh) LABEL="Docker Management" ;;
        smite.sh) LABEL="Smite Compatibility Management" ;;
        smite-digest-migrate.sh) LABEL="Smite Digest Migration" ;;
        smite-install.sh) LABEL="Smite Installer / Lifecycle" ;;
        smite-gateway.sh) LABEL="Smite 443 Gateway" ;;
        smite-frp-xhttp.sh) LABEL="Smite Standard FRP XHTTP Automatic Routes" ;;
        smite-frp-xhttp-paths.py) LABEL="Smite FRP Custom XHTTP Path Registry" ;;
        smite-xhttp-nginx-route) LABEL="Pinned Smite XHTTP route worker" ;;
        smite_xhttp_nginx_plan.py) LABEL="Pinned Smite XHTTP route planner" ;;
        smite-rc5-xhttp-root-broker.py) LABEL="Smite XHTTP local broker (staged only)" ;;
        smite-rc5-xhttp-broker-provision.py) LABEL="Smite XHTTP broker provision/activation helper (staged)" ;;
        smite-rc5-xhttp-broker-compose.py) LABEL="Smite XHTTP clean-install Compose admission helper" ;;
        smite-rc5-xhttp-sanaei-mount.py) LABEL="Smite KH Sanaei read-only inventory mount helper" ;;
        smite-rc5-xhttp-nonce-ledger.py) LABEL="Smite XHTTP durable replay ledger" ;;
        smite-rc5-xhttp-signed-intent.py) LABEL="Smite XHTTP signed intent contract" ;;
        smite-rc5-xhttp-bridge-install.py) LABEL="Smite XHTTP bridge verifier" ;;
        smite-rc5-xhttp-bridge-admission.py) LABEL="Smite XHTTP bridge admission verifier" ;;
        smite-frp-rc2-guided-publish.py) LABEL="Signed RC2 FRP XHTTP Guided Publisher" ;;
        smite-backhaul-management.sh) LABEL="Smite Tunnel Management & Backhaul (experimental)" ;;
        smite-clean-rc-preflight.sh) LABEL="Smite clean-RC Nginx/Certbot prerequisite" ;;
        smite-clean-ir-resume.sh) LABEL="Smite clean IR recovery" ;;
        smite-tunnel-wizard.sh) LABEL="Smite Tunnel Wizard (experimental test-host install)" ;;
        smite-tunnel-control-center.sh) LABEL="Smite Tunnel Control Center (read-only dashboard)" ;;
        smite-foreign-gateway.sh) LABEL="Smite Foreign 443 Gateway" ;;
        smite-private-network.sh) LABEL="Smite Private Network Entry Point" ;;
        smite-easytier.sh) LABEL="Smite EasyTier Private Network" ;;
        docker-3xui.sh) LABEL="3x-UI Docker Management" ;;
        docker-3xui-instance.sh) LABEL="3x-UI Instance Management" ;;
        docker-3xui-certificate-multi.sh) LABEL="3x-UI Multi-Instance TLS Certificates" ;;
        docker-3xui-compat.sh) LABEL="3x-UI Compatibility Helpers" ;;
        docker-3xui-nginx.sh) LABEL="3x-UI Nginx / SSL Integration" ;;
        fakesite.sh) LABEL="Default Website / FakeSite" ;;
        *) LABEL="$MODULE" ;;
    esac
    if [ -z "${INSTALL_BUNDLE_DIR:-}" ]; then
        printf '[%d/%d] Downloading %s...\n' "$((++DOWNLOAD_INDEX))" "${#MODULES[@]}" "$LABEL"
    fi
    u_opti_install_download "modules/$MODULE" "$TEMP_DIR/$MODULE" || { echo "Failed to download $MODULE."; exit 1; }
done

echo
echo "Checking downloaded files..."
REQUIRED_FILES=("$TEMP_DIR/VERSION" "$TEMP_DIR/u-opti" "$TEMP_DIR/common.sh")
for MODULE in "${MODULES[@]}"; do
    REQUIRED_FILES+=("$TEMP_DIR/$MODULE")
done

for FILE in "${REQUIRED_FILES[@]}"; do
    if [ ! -s "$FILE" ]; then
        echo "Error: Required file is missing or empty:"
        echo "$FILE"
        exit 1
    fi
done
echo "All required files are present."

if ! grep -q 'echo "6) Hostname Management"' "$TEMP_DIR/u-opti" || \
   ! grep -q 'show_hostname_menu' "$TEMP_DIR/u-opti" || \
   ! grep -q 'show_hostname_menu()' "$TEMP_DIR/system.sh" || \
   ! grep -q 'u_opti_security_monitor_menu()' "$TEMP_DIR/security-monitor.sh" || \
   ! grep -q '7) Security Monitoring' "$TEMP_DIR/u-opti" || \
   ! grep -q 'echo "5) Smite Management"' "$TEMP_DIR/docker.sh" || \
   ! grep -q 'docker_smite_management_menu' "$TEMP_DIR/docker.sh" || \
   ! grep -q 'docker_smite_compatibility_menu' "$TEMP_DIR/docker.sh" || \
   ! grep -q 'docker_smite_ensure_digest_module' "$TEMP_DIR/docker.sh" || \
   ! grep -q 'smite_digest_migrate_existing()' "$TEMP_DIR/smite-digest-migrate.sh" || \
   ! grep -q 'show_smite_install_menu()' "$TEMP_DIR/smite-install.sh" || \
   ! grep -q 'show_smite_gateway_menu()' "$TEMP_DIR/smite-gateway.sh" || \
   ! grep -q 'smite_frp_wizard_menu()' "$TEMP_DIR/smite-frp-wizard.sh" || \
   ! grep -q 'def render(' "$TEMP_DIR/smite-frp-xhttp-paths.py" || \
   ! grep -q 'def inspection(' "$TEMP_DIR/smite-frp-rc2-guided-publish.py" || \
   ! grep -q 'smite_bh_management_menu()' "$TEMP_DIR/smite-backhaul-management.sh" || \
   ! grep -Fq 'smite_clean_rc_prepare_gateway_packages()' "$TEMP_DIR/smite-clean-rc-preflight.sh" || \
   ! grep -q 'smite_tw_menu()' "$TEMP_DIR/smite-tunnel-wizard.sh" || \
   ! grep -q 'def validate(' "$TEMP_DIR/smite-profile-first.py" || \
   ! grep -q 'PROFILE FIRST' "$TEMP_DIR/smite-profile-first-menu.sh" || \
   ! grep -q 'twcc_menu()' "$TEMP_DIR/smite-tunnel-control-center.sh" || \
   ! grep -q 'show_smite_foreign_gateway_menu()' "$TEMP_DIR/smite-foreign-gateway.sh" || \
   ! grep -q 'show_smite_private_network_menu()' "$TEMP_DIR/smite-private-network.sh" || \
   ! grep -q 'show_smite_easytier_menu()' "$TEMP_DIR/smite-easytier.sh" || \
   ! grep -q 'docker_3xui_multi_certificate_menu()' "$TEMP_DIR/docker-3xui-certificate-multi.sh" || \
   ! grep -q 'show_smite_menu()' "$TEMP_DIR/smite.sh"; then
    echo
    echo "ERROR: Downloaded U-OPTI files failed feature verification."
    echo "The downloaded files are inconsistent or stale."
    echo "Installation cancelled."
    exit 1
fi

echo "Feature verification passed."

echo
u_opti_activity_start "Checking Bash, Python and JSON syntax"
bash -n "$TEMP_DIR/u-opti"
bash -n "$TEMP_DIR/common.sh"
for MODULE in "${MODULES[@]}"; do
    case "$MODULE" in
        *.py|smite-xhttp-nginx-route) python3 -m py_compile "$TEMP_DIR/$MODULE" || exit 1 ;;
        *.json) python3 -c 'import json, sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$TEMP_DIR/$MODULE" || exit 1 ;;
        *) bash -n "$TEMP_DIR/$MODULE" || exit 1 ;;
    esac
done
u_opti_activity_stop
echo "Bash/Python/JSON syntax checks passed."

echo
echo "Preparing recoverable installation transaction..."
# A new installation and the first intentional migration from an old
# U-OPTI installation use the SAME durable backup+journal protocol. Do
# not overwrite a pre-existing installation without explicit consent.
if [ -e "$INSTALL_PATH" ] || [ -L "$INSTALL_PATH" ]; then
    if [ "${U_OPTI_ADOPT_EXISTING:-NO}" != "YES" ]; then
        echo "HOLD: Existing U-OPTI installation found. Use its regular Update menu." >&2
        echo "Legacy first adoption requires separate backup/review and explicit opt-in." >&2
        exit 1
    fi
    echo "Explicit legacy-adoption mode selected; original bytes will be journal-backed."
elif [ -e "$LIB_PATH/VERSION" ] || [ -L "$LIB_PATH/VERSION" ] ||
     [ -e "$LIB_PATH/common.sh" ] || [ -L "$LIB_PATH/common.sh" ]; then
    echo "HOLD: Incomplete existing installation without executable; manual review required." >&2
    exit 1
fi

if [ -L "$LIB_PATH" ] || [ -L "$MODULES_PATH" ]; then
    echo "HOLD: Unsafe U-OPTI installation directory." >&2
    exit 1
fi
mkdir -p "$LIB_PATH" "$MODULES_PATH"
# Persistent private backup, not volatile /tmp; all old-file bytes are saved
# before calling apply. Missing files are represented by explicit markers.
BACKUP_DIR="$(mktemp -d "$LIB_PATH/.uopti-backup-XXXXXXXX")"
backup_ok=true
backup_items=(u-opti common.sh VERSION INSTALL_REF "${MODULES[@]}")
for name in "${backup_items[@]}"; do
    case "$name" in
        u-opti) original="$INSTALL_PATH" ;;
        common.sh) original="$LIB_PATH/common.sh" ;;
        VERSION) original="$LIB_PATH/VERSION" ;;
        INSTALL_REF) original="$LIB_PATH/INSTALL_REF" ;;
        *) original="$MODULES_PATH/$name" ;;
    esac
    if [ -L "$original" ]; then
        backup_ok=false
        echo "HOLD: Unsafe symlink at $original" >&2
        break
    elif [ -f "$original" ]; then
        if [ ! -O "$original" ] || [ "$(stat -c %h "$original")" -ne 1 ] ||
           ! cp -- "$original" "$BACKUP_DIR/$name"; then
            backup_ok=false
            break
        fi
        chmod 0600 "$BACKUP_DIR/$name"
    elif [ ! -e "$original" ]; then
        : > "$BACKUP_DIR/.$name-was-missing"
        chmod 0600 "$BACKUP_DIR/.$name-was-missing"
    else
        backup_ok=false
        echo "HOLD: Unexpected non-file installation target: $original" >&2
        break
    fi
done

if [ "$backup_ok" != true ]; then
    echo "HOLD: Could not secure installation backup; NO live files changed." >&2
    echo "Review preserved backup: $BACKUP_DIR" >&2
    exit 1
fi
# Exact same already-downloaded, syntax-checked and SHA-pinned candidates.
# The helper records its own rescue copy before changing the first target.
echo "Applying staged, journal-backed installation..."
if ! python3 -B "$TEMP_DIR/u-opti-update-transaction.py" apply \
          "$TEMP_DIR" "$BACKUP_DIR" --source-ref "$BRANCH" "${MODULES[@]}"; then
    echo "HOLD: Transaction incomplete; attempting safely journaled rollback." >&2
    RESCUE="$LIB_PATH/.uopti-update-pending/rescue.py"
    if [ -f "$RESCUE" ] && [ ! -L "$RESCUE" ] &&
       python3 -B "$RESCUE" recover; then
        echo "Original U-OPTI files restored; backup retained at $BACKUP_DIR" >&2
    else
        echo "HOLD: Recovery needs operator review; backup retained at $BACKUP_DIR" >&2
    fi
    exit 1
fi

echo "======================================"
echo "       Installation completed"
echo "======================================"
echo
echo "Installed Version: $REMOTE_VERSION"
echo "Verified revision: $SOURCE_SHA"
echo "Command: u-opti"
echo "Files: $LIB_PATH"
echo "Recovery backup: $BACKUP_DIR"
echo

"$INSTALL_PATH"
