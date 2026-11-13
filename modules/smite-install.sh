#!/bin/bash

# U-OPTI - Smite Installer / Lifecycle Management
# Controlled installer for the Smite version validated by U-OPTI.

SMITE_UPSTREAM_VERSION="${SMITE_UPSTREAM_VERSION:-0.1.7}"
SMITE_UPSTREAM_REF="${SMITE_UPSTREAM_REF:-v${SMITE_UPSTREAM_VERSION}}"
SMITE_UPSTREAM_RAW="https://raw.githubusercontent.com/zZedix/Smite/${SMITE_UPSTREAM_REF}"
SMITE_PANEL_REPO="ghcr.io/zzedix/smite-panel"
SMITE_NODE_REPO="ghcr.io/zzedix/smite-node"
SMITE_PANEL_DIGEST="sha256:67f98cba1f49658e651779ab6142290f7eb0906b54b386939fcdb867d18cb44f"
SMITE_NODE_DIGEST="sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e"
SMITE_PANEL_IMAGE="${SMITE_PANEL_REPO}@${SMITE_PANEL_DIGEST}"
SMITE_NODE_IMAGE="${SMITE_NODE_REPO}@${SMITE_NODE_DIGEST}"

# Clean reinstall profile is an EXPLICIT disposable-server experiment.
# Stable installed U-OPTI keeps using the historically validated v0.1.7
# images; the new Panel/Node artifact pair is never selected implicitly.
SMITE_INSTALL_PROFILE="${SMITE_INSTALL_PROFILE:-stable}"

# Exact, independently reviewed candidate used ONLY by the disposable-host
# Field Trial. The candidate remains a prerelease and is never promoted by
# this installer. Operator approval is separate from production approval.
SMITE_FIELD_TRIAL_SOURCE_SHA="289f99cae8c53ba7d5b8e427bca19e5c04ebba8a"
SMITE_FIELD_TRIAL_PUBLISH_REF="refs/tags/v2.0.0-rc.1"
SMITE_FIELD_TRIAL_VERSION="2.0.0-rc.1"
SMITE_FIELD_TRIAL_MANIFEST_SHA256="d364bd48ee12288ae67dc0e6c15fcc9d15e43ae73cf82c3c33da242890b4f65f"
SMITE_FIELD_TRIAL_COSIGN_SHA256="c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74"

SMITE_FIELD_TRIAL_PREVIOUS_VERSION="2.0.0-rc.0"
SMITE_FIELD_TRIAL_PREVIOUS_PANEL_IMAGE="ghcr.io/aghajani82/smite-panel@sha256:6cfaec4a961f1c03eb05c684b41c001ce73178ee20231517aafced1dc972aadb"
SMITE_FIELD_TRIAL_PREVIOUS_NODE_IMAGE="ghcr.io/aghajani82/smite-node@sha256:bb4992698fc637719a489ec6e9a8384a5c898e9afeb6cae16fcfc41a626b482c"

smite_install_clean_rc_signed_registry_selected() {
    [ "${SMITE_RC_SIGNED_REGISTRY:-0}" = "1" ]
}

smite_install_field_trial_verify_candidate() {
    local helper_dir verifier manifest cosign_path actual_cosign pair_result
    local -a candidate=() verify_root_args=()

    smite_install_clean_rc_signed_registry_selected || {
        echo "HOLD: Signed registry Field Trial was not selected" >&2
        return 1
    }
    [ "${SMITE_FIELD_TRIAL_APPROVED:-}" = "YES" ] || {
        echo "HOLD: Explicit disposable-host Field Trial approval required" >&2
        return 1
    }

    helper_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 1
    verifier="$helper_dir/smite-registry-pair-admission.py"
    manifest="$helper_dir/smite-field-trial-candidate.json"
    if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ]; then
        manifest="$helper_dir/smite-rc7-registry-pair.json"
    fi

    [ -f "$verifier" ] && [ ! -L "$verifier" ] &&
    [ -f "$manifest" ] && [ ! -L "$manifest" ] || {
        echo "HOLD: Signed Field Trial verifier/manifest is missing or unsafe" >&2
        return 1
    }

    if [ "$(sha256sum "$manifest" | awk '{print $1}')" != "$SMITE_FIELD_TRIAL_MANIFEST_SHA256" ]; then
        echo "HOLD: Signed Field Trial manifest hash mismatch" >&2
        return 1
    fi

    command -v cosign >/dev/null 2>&1 || {
        echo "HOLD: Pinned Cosign verifier is not installed" >&2
        return 1
    }
    cosign_path="$(command -v cosign)"
    [ -f "$cosign_path" ] && [ ! -L "$cosign_path" ] || {
        echo "HOLD: Cosign verifier path is not a regular non-symlink file" >&2
        return 1
    }
    actual_cosign="$(sha256sum "$cosign_path" | awk '{print $1}')"
    [ "$actual_cosign" = "$SMITE_FIELD_TRIAL_COSIGN_SHA256" ] || {
        echo "HOLD: Cosign binary does not match reviewed v3.0.6 amd64 asset" >&2
        return 1
    }

    # Only the explicitly selected RC7 fresh install supplies the reviewed,
    # SHA-pinned Sigstore trust snapshot. Historical candidates stay unchanged.
    if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ]; then
        [ -n "${SMITE_SELECTED_TRUSTED_ROOT:-}" ] || {
            echo 'HOLD: RC7 trusted root snapshot is required' >&2
            return 1
        }
        verify_root_args=(--trusted-root "$SMITE_SELECTED_TRUSTED_ROOT")
    fi
    pair_result="$(python3 -B "$verifier" \
        --manifest "$manifest" \
        --manifest-sha256 "$SMITE_FIELD_TRIAL_MANIFEST_SHA256" \
        --source-sha "$SMITE_FIELD_TRIAL_SOURCE_SHA" \
        --publish-ref "$SMITE_FIELD_TRIAL_PUBLISH_REF" \
        "${verify_root_args[@]}")" || return 1
    printf '%s\n' "$pair_result"

    mapfile -t candidate < <(python3 - "$manifest" <<'PY_SIGNED_RC'
import json, pathlib, sys
doc=json.loads(pathlib.Path(sys.argv[1]).read_text())
print(doc["images"]["panel"])
print(doc["images"]["node"])
print(doc["version"])
PY_SIGNED_RC
    )
    [ "${#candidate[@]}" -eq 3 ] || {
        echo "HOLD: Signed Field Trial manifest parse failed" >&2
        return 1
    }

    SMITE_PANEL_IMAGE="${candidate[0]}"
    SMITE_NODE_IMAGE="${candidate[1]}"
    SMITE_UPSTREAM_VERSION="${candidate[2]}"

    [ "$SMITE_UPSTREAM_VERSION" = "$SMITE_FIELD_TRIAL_VERSION" ] || {
        echo "HOLD: Signed Field Trial version mismatch" >&2
        return 1
    }

    echo "FIELD_TRIAL_SIGNED_REGISTRY=VERIFIED"
    echo "FIELD_TRIAL_OPERATOR_APPROVAL=YES"
    echo "PRODUCTION_RELEASE_APPROVAL=NO"
    return 0
}

smite_install_clean_rc_preflight() {
    local role="$1" mode="$2" helper_dir pair_result
    [ "$SMITE_INSTALL_PROFILE" = clean-rc ] || {
        echo "HOLD: Unexpected fresh Smite profile" >&2
        return 1
    }
    if [ "$role" != panel-iran ] && [ "$role" != foreign ]; then
        echo "HOLD: Unknown fresh-install server role" >&2
        return 1
    fi
    if [ "$mode" != standard ]; then
        echo "HOLD: Clean RC currently supports Standard mode only" >&2
        return 1
    fi
    # Never migrate old configurations, databases, tunnels or containers.
    if [ -e "$SMITE_STATE_FILE" ] || [ -L "$SMITE_STATE_FILE" ] ||
       [ -e "$SMITE_PANEL_COMPOSE" ] || [ -L "$SMITE_PANEL_COMPOSE" ] ||
       [ -e "$SMITE_NODE_COMPOSE" ] || [ -L "$SMITE_NODE_COMPOSE" ] ||
       [ -e "$SMITE_OVERLAY_DIR/panel/main.py" ] ||
       [ -e "$SMITE_OVERLAY_DIR/node/panel_client.py" ] ||
       smite_container_exists smite-panel || smite_container_exists smite-node; then
        echo "HOLD: Existing Smite installation detected. Clean RC is not an upgrader." >&2
        return 1
    fi
    if smite_install_clean_rc_signed_registry_selected; then
        smite_install_field_trial_verify_candidate || return 1
        echo "RC_IMAGE_PROVENANCE=SIGSTORE_VERIFIED_REGISTRY_DIGESTS"
        echo "RC_SIGNED_AUTH=PENDING_SECURE_PAIRING"
        return 0
    fi

    if [ -z "${SMITE_RC_BUNDLE_DIR:-}" ] ||
       [ -z "${SMITE_RC_SOURCE_SHA:-}" ] ||
       [ -z "${SMITE_RC_MANIFEST_SHA256:-}" ]; then
        echo "HOLD: Trusted artifact directory, source SHA and manifest SHA required" >&2
        return 1
    fi

    helper_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 1
    pair_result="$(python3 -B "$helper_dir/smite-clean-image-pair.py" \
        --folder "$SMITE_RC_BUNDLE_DIR" \
        --source-sha "$SMITE_RC_SOURCE_SHA" \
        --manifest-sha256 "$SMITE_RC_MANIFEST_SHA256")" || return 1
    printf '%s\n' "$pair_result"
    echo "RC_IMAGE_PROVENANCE=NOT_ATTESTED"
    echo "RC_SIGNED_AUTH=NOT_ACTIVE"
    # docker save archives carry exactly these two local preview tags.
    # Loading is a separate explicit step after local source preflight.
    SMITE_PANEL_IMAGE="smite-panel:stage15-local"
    SMITE_NODE_IMAGE="smite-node:stage15-local"
    # The v0.1.7 upstream Compose is used as a known layout template;
    # the application binaries are ONLY the paired offline RC images.
    SMITE_UPSTREAM_VERSION="2.0.0-rc.1"
    return 0
}

smite_install_clean_rc_load_images() {
    local role="$1" expected_panel expected_node loaded_panel loaded_node
    local verifier_dir
    verifier_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 1

    if smite_install_clean_rc_signed_registry_selected; then
        smite_install_field_trial_verify_candidate || return 1
        if [ "$role" = panel-iran ]; then
            echo "Pulling signed Panel candidate by immutable digest..."
            docker pull "$SMITE_PANEL_IMAGE" || return 1
            docker image inspect "$SMITE_PANEL_IMAGE" >/dev/null 2>&1 || {
                echo "HOLD: Signed Panel digest was not retained locally" >&2
                return 1
            }
        fi
        echo "Pulling signed Node candidate by immutable digest..."
        docker pull "$SMITE_NODE_IMAGE" || return 1
        docker image inspect "$SMITE_NODE_IMAGE" >/dev/null 2>&1 || {
            echo "HOLD: Signed Node digest was not retained locally" >&2
            return 1
        }
        echo "CLEAN_RC_IMAGES=SIGNED_REGISTRY_DIGESTS_VERIFIED"
        echo "CLEAN_RC_PRODUCTION_ACTIVATION=NOT_AUTHORIZED"
        echo "CLEAN_RC_FIELD_TRIAL_ACTIVATION=OPERATOR_APPROVED"
        return 0
    fi

    # Recheck bytes at time of loading, not only at UI confirmation.
    python3 -B "$verifier_dir/smite-clean-image-pair.py" \
        --folder "$SMITE_RC_BUNDLE_DIR" \
        --source-sha "$SMITE_RC_SOURCE_SHA" \
        --manifest-sha256 "$SMITE_RC_MANIFEST_SHA256" >/dev/null || return 1
    read -r expected_panel expected_node < <(
        python3 - "$SMITE_RC_BUNDLE_DIR" <<'PY_RC_IDS'
import json, pathlib, sys
data=json.loads((pathlib.Path(sys.argv[1]) / "stage15-images.json").read_text())
print(data["images"]["panel"]["local_image_id"], data["images"]["node"]["local_image_id"])
PY_RC_IDS
    )
    [ -n "$expected_panel" ] && [ -n "$expected_node" ] || return 1
    if [ "$role" = panel-iran ]; then
        ( set -o pipefail
          gzip -cd "$SMITE_RC_BUNDLE_DIR/smite-panel-stage15.docker.tar.gz" |
              docker load >/dev/null
        ) || return 1
        loaded_panel="$(docker image inspect "$SMITE_PANEL_IMAGE" --format '{{.Id}}' 2>/dev/null)" || return 1
        if [ "$loaded_panel" != "$expected_panel" ]; then
            echo "HOLD: Loaded Panel image ID differs from verified archive" >&2
            return 1
        fi
    fi
    ( set -o pipefail
      gzip -cd "$SMITE_RC_BUNDLE_DIR/smite-node-stage15.docker.tar.gz" |
          docker load >/dev/null
    ) || return 1
    loaded_node="$(docker image inspect "$SMITE_NODE_IMAGE" --format '{{.Id}}' 2>/dev/null)" || return 1
    if [ "$loaded_node" != "$expected_node" ]; then
        echo "HOLD: Loaded Node image ID differs from verified archive" >&2
        return 1
    fi
    echo "CLEAN_RC_IMAGES=LOCAL_IDS_MATCH_VERIFIED_ARCHIVES"
    echo "CLEAN_RC_PRODUCTION_ACTIVATION=NOT_AUTHORIZED"
    return 0
}
SMITE_STATE_DIR="${SMITE_STATE_DIR:-/etc/u-opti/smite}"
SMITE_STATE_FILE="$SMITE_STATE_DIR/state.env"


# Experimental FRP upgrade for Smite v0.1.7 pinned Docker images.
SMITE_FRP_VERSION="0.71.0"
SMITE_FRP_BIN_DIR="/opt/u-opti/smite-frp/v$SMITE_FRP_VERSION"

smite_frp_prepare_binaries() (
    local arch expected_sha archive archive_root url workdir binary actual
    case "$(uname -m)" in
        x86_64|amd64)
            arch="amd64"
            expected_sha="84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716"
            ;;
        aarch64|arm64)
            arch="arm64"
            expected_sha="f33c293c275d8fc68c654b6fba8f10b2551d6463d09a9fc9cffb7227eae82266"
            ;;
        *)
            echo "ERROR: Unsupported architecture for experimental Smite FRP $SMITE_FRP_VERSION."
            return 1
            ;;
    esac

    if [ -x "$SMITE_FRP_BIN_DIR/frpc" ] && [ -x "$SMITE_FRP_BIN_DIR/frps" ] &&
       [ "$("$SMITE_FRP_BIN_DIR/frpc" -v 2>/dev/null)" = "$SMITE_FRP_VERSION" ] &&
       [ "$("$SMITE_FRP_BIN_DIR/frps" -v 2>/dev/null)" = "$SMITE_FRP_VERSION" ]; then
        echo "FRP v$SMITE_FRP_VERSION already prepared."
        return 0
    fi

    for binary in curl tar sha256sum install mv; do
        command -v "$binary" >/dev/null 2>&1 || {
            echo "ERROR: FRP preparation requires $binary."
            return 1
        }
    done

    workdir="$(mktemp -d)" || return 1
    trap 'rm -rf "$workdir"' EXIT
    archive="frp_$SMITE_FRP_VERSION"_linux_"$arch".tar.gz
    archive_root="frp_$SMITE_FRP_VERSION"_linux_"$arch"
    url="https://github.com/fatedier/frp/releases/download/v$SMITE_FRP_VERSION/$archive"

    echo "Downloading official FRP v$SMITE_FRP_VERSION ($arch)..."
    curl -fsSL --retry 3 --proto '=https' --proto-redir '=https' "$url" -o "$workdir/$archive" || return 1
    if ! printf '%s  %s\n' "$expected_sha" "$workdir/$archive" | sha256sum -c - >/dev/null; then
        echo "ERROR: Official FRP release SHA256 verification failed."
        return 1
    fi
    tar -xzf "$workdir/$archive" -C "$workdir" \
        "$archive_root/frpc" "$archive_root/frps" || return 1
    for binary in frpc frps; do
        [ -x "$workdir/$archive_root/$binary" ] || {
            echo "ERROR: FRP archive is missing executable $binary."
            return 1
        }
        actual="$("$workdir/$archive_root/$binary" -v 2>/dev/null)" || return 1
        if [ "$actual" != "$SMITE_FRP_VERSION" ]; then
            echo "ERROR: $binary reports '$actual', expected '$SMITE_FRP_VERSION'."
            return 1
        fi
    done

    install -d -m 0755 "$SMITE_FRP_BIN_DIR" || return 1
    for binary in frpc frps; do
        install -m 0755 "$workdir/$archive_root/$binary" "$SMITE_FRP_BIN_DIR/$binary.new.$$" || return 1
        mv -f "$SMITE_FRP_BIN_DIR/$binary.new.$$" "$SMITE_FRP_BIN_DIR/$binary" || return 1
    done
    echo "Verified FRP v$SMITE_FRP_VERSION binaries at $SMITE_FRP_BIN_DIR"
)

smite_frp_mount_compose() {
    local compose_file="$1" service="$2"
    # Alter only the target Smite service. The pinned images stay unchanged.
    python3 - "$compose_file" "$service" "$SMITE_FRP_BIN_DIR" <<'PY'
import sys
from pathlib import Path

compose = Path(sys.argv[1])
service = sys.argv[2]
host_dir = Path(sys.argv[3])
if service not in {"smite-panel", "smite-node"} or not host_dir.is_absolute():
    raise SystemExit("ERROR: Invalid Smite FRP Compose service/path.")

original = compose.read_text()
anchor = f"  {service}:\n"
if original.count(anchor) != 1:
    raise SystemExit(f"ERROR: Expected exactly one {service} service in {compose}.")
before, tail = original.split(anchor, 1)
lines = tail.splitlines(keepends=True)
end = len(lines)
for i, line in enumerate(lines):
    if line.strip() and not line.lstrip().startswith("#") and (
        not line.startswith((" ", "\t")) or
        (line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"))
    ):
        end = i
        break
block = "".join(lines[:end])
marker = "    volumes:\n"
if block.count(marker) != 1:
    raise SystemExit(f"ERROR: Expected exactly one volumes section in {service}.")

binaries = ("frps",) if service == "smite-panel" else ("frpc", "frps")
new_mounts = []
for name in binaries:
    target = f":/usr/local/bin/{name}"
    expected = f"      - {host_dir}/{name}:/usr/local/bin/{name}:ro"
    existing = [
        line.strip() for line in block.splitlines()
        if line.lstrip().startswith("- ") and target in line
    ]
    if existing and existing != [expected.strip()]:
        raise SystemExit(f"ERROR: Conflicting FRP mount for {name} in {service}.")
    if not existing:
        if not (host_dir / name).is_file():
            raise SystemExit(f"ERROR: Missing prepared FRP binary {host_dir / name}.")
        new_mounts.append(expected + "\n")

if new_mounts:
    block = block.replace(marker, marker + "".join(new_mounts), 1)
    compose.write_text(before + anchor + block + "".join(lines[end:]))
print(f"Smite FRP read-only mounts ready: {service}")
PY
}

# Core installation must not install an engine the operator did not select.
# Legacy/stable retains exactly the old pinned FRP workflow.
# Clean RC is only for disposable hosts and starts with NO host FRP files.
smite_install_core_optional_frp_prepare() {
    local compose_file="$1" service="$2"
    case "$SMITE_INSTALL_PROFILE" in
        stable)
            smite_frp_prepare_binaries || return 1
            smite_frp_mount_compose "$compose_file" "$service" || return 1
            ;;
        clean-rc)
            echo "SMITE_CORE_FRP_HOST_INSTALL=SKIPPED"
            ;;
        *)
            echo "HOLD: Unknown Smite install profile for core engine setup" >&2
            return 1
            ;;
    esac
}

smite_install_core_optional_frp_verify() {
    local container="$1"
    case "$SMITE_INSTALL_PROFILE" in
        stable) smite_frp_verify_container "$container" ;;
        clean-rc)
            echo "SMITE_CORE_FRP_VERSION_CHECK=NOT_REQUIRED"
            ;;
        *)
            echo "HOLD: Unknown Smite install profile for engine verification" >&2
            return 1
            ;;
    esac
}

smite_frp_verify_container() {
    local container="$1" binary actual
    case "$container" in
        smite-panel) set -- frps ;;
        smite-node) set -- frpc frps ;;
        *) echo "ERROR: Unknown Smite FRP container: $container"; return 1 ;;
    esac
    for binary in "$@"; do
        actual="$(docker exec "$container" "/usr/local/bin/$binary" -v 2>/dev/null)" || {
            echo "ERROR: Cannot check $binary in $container."
            return 1
        }
        if [ "$actual" != "$SMITE_FRP_VERSION" ]; then
            echo "ERROR: $container $binary reports '$actual', expected '$SMITE_FRP_VERSION'."
            return 1
        fi
        echo "Verified $container $binary v$actual"
    done
}

smite_install_pause() {
    # A freshly selected, already-approved option-2 installation must
    # continue through the existing Sanaei DB attachment without extra
    # menu-return prompts. The standalone option-4 behavior is unchanged.
    if [ "${UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER:-0}" = 1 ] &&
       [ "${SMITE_SELECTED_FRESH:-0}" = 1 ]; then
        return 0
    fi
    echo
    read -rp "Press Enter to return..."
}

smite_install_validate_domain() {
    local domain="$1"
    [[ "$domain" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]
}

smite_install_validate_name() {
    local name="$1"
    [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]]
}

smite_install_validate_ipv4() {
    local ip="$1"
    local IFS=.
    local -a octets
    local octet

    read -r -a octets <<< "$ip"

    [ "${#octets[@]}" -eq 4 ] || return 1

    for octet in "${octets[@]}"; do
        [[ "$octet" =~ ^[0-9]+$ ]] || return 1
        (( 10#$octet >= 0 && 10#$octet <= 255 )) || return 1
    done

    return 0
}

smite_install_require_tools() {
    local missing=()
    local cmd

    for cmd in curl openssl python3; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done

    if [ "${#missing[@]}" -gt 0 ]; then
        echo "ERROR: Required commands are missing: ${missing[*]}"
        echo "Install the missing packages and try again."
        return 1
    fi

    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "ERROR: sqlite3 is required by Smite management."
        echo "Reinstall/update U-OPTI or install sqlite3 first."
        return 1
    fi

    return 0
}

smite_install_ensure_docker() {
    local confirm=""

    if command -v docker >/dev/null 2>&1 && \
       systemctl is-active --quiet docker 2>/dev/null && \
       docker compose version >/dev/null 2>&1; then
        return 0
    fi

    echo "Docker Engine / Compose is not ready."
    if declare -F docker_install >/dev/null 2>&1; then
        echo
        read -rp "Run the U-OPTI Docker installer now? [y/N]: " confirm
        case "$confirm" in
            y|Y|yes|YES)
                docker_install
                ;;
            *)
                return 1
                ;;
        esac
    else
        echo "Install Docker from U-OPTI -> Docker Management -> Install Docker."
        return 1
    fi

    command -v docker >/dev/null 2>&1 && \
    systemctl is-active --quiet docker 2>/dev/null && \
    docker compose version >/dev/null 2>&1
}

smite_download_upstream() {
    local path="$1"
    local destination="$2"
    local cache_bust
    cache_bust="$(date +%s%N)"

    mkdir -p "$(dirname "$destination")" || return 1
    curl -fsSL --retry 3 \
        "${SMITE_UPSTREAM_RAW}/${path}?cb=${cache_bust}" \
        -o "$destination"
}

smite_install_pin_compose_image() {
    local compose_file="$1"
    local expected_repo="$2"
    local pinned_image="$3"

    python3 - "$compose_file" "$expected_repo" "$pinned_image" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
expected_repo = sys.argv[2]
pinned_image = sys.argv[3]

text = path.read_text()
needle = f"    image: {expected_repo}:${{SMITE_VERSION:-latest}}"
replacement = f"    image: {pinned_image}"

count = text.count(needle)
if count != 1:
    raise SystemExit(
        f"ERROR: Expected exactly one Compose image line for {expected_repo}; found {count}. Refusing unsafe pin."
    )

path.write_text(text.replace(needle, replacement, 1))
print(f"Pinned Compose image: {pinned_image}")
PY
}

smite_install_cli_tools() {
    echo "Installing Smite CLI tools..."

    if ! smite_download_upstream "cli/smite.py" "/usr/local/bin/smite"; then
        echo "ERROR: Failed to download the Smite panel CLI."
        return 1
    fi

    if ! smite_download_upstream "cli/smite-node.py" "/usr/local/bin/smite-node"; then
        echo "ERROR: Failed to download the Smite node CLI."
        return 1
    fi

    chmod 0755 /usr/local/bin/smite /usr/local/bin/smite-node || return 1
    return 0
}

smite_install_create_admin() {
    [ -x /usr/local/bin/smite ] || {
        echo "ERROR: Smite admin CLI is missing at /usr/local/bin/smite." >&2
        return 1
    }
    (cd "$SMITE_PANEL_DIR" && /usr/local/bin/smite admin create)
}

smite_write_state() {
    local role="$1"
    local panel_domain="$2"
    local node_name="$3"
    local foreign_domain="${4:-}"
    local connection_mode="${5:-standard}"
    local panel_private_ip="${6:-}"
    local foreign_private_ip="${7:-}"

    mkdir -p "$SMITE_STATE_DIR" || return 1
    chmod 0700 "$SMITE_STATE_DIR" || return 1

    cat > "$SMITE_STATE_FILE" <<EOF_STATE || return 1
# Managed by U-OPTI. No secrets are stored here.
SMITE_ROLE=$role
SMITE_CONNECTION_MODE=$connection_mode
SMITE_PANEL_DOMAIN=$panel_domain
SMITE_PANEL_PRIVATE_IP=$panel_private_ip
SMITE_NODE_NAME=$node_name
SMITE_FOREIGN_DOMAIN=$foreign_domain
SMITE_FOREIGN_PRIVATE_IP=$foreign_private_ip
SMITE_MANAGED_VERSION=$SMITE_UPSTREAM_VERSION
SMITE_UPSTREAM_REF=$SMITE_UPSTREAM_REF
EOF_STATE
    chmod 0600 "$SMITE_STATE_FILE" || return 1
}

smite_show_installation_state() {
    clear
    echo "======================================"
    echo "      Smite Installation State"
    echo "======================================"
    echo

    echo "Validated Smite version : $SMITE_UPSTREAM_VERSION"
    echo "Validated source ref    : $SMITE_UPSTREAM_REF"
    echo

    if [ -f "$SMITE_STATE_FILE" ]; then
        source "$SMITE_STATE_FILE"
        echo "Managed role            : ${SMITE_ROLE:-Unknown}"
        echo "Connection mode         : ${SMITE_CONNECTION_MODE:-standard}"
        echo "Panel domain            : ${SMITE_PANEL_DOMAIN:-Not set}"
        if [ -n "${SMITE_PANEL_PRIVATE_IP:-}" ]; then
            echo "Panel private IP        : $SMITE_PANEL_PRIVATE_IP"
        fi
        echo "Node name               : ${SMITE_NODE_NAME:-Not set}"
        if [ -n "${SMITE_FOREIGN_DOMAIN:-}" ]; then
            echo "Foreign domain          : $SMITE_FOREIGN_DOMAIN"
        fi
        if [ -n "${SMITE_FOREIGN_PRIVATE_IP:-}" ]; then
            echo "Foreign private IP      : $SMITE_FOREIGN_PRIVATE_IP"
        fi
        echo "Managed Smite version   : ${SMITE_MANAGED_VERSION:-Unknown}"
    else
        echo "Managed state           : Not created"
    fi

    echo
    if [ -f "$SMITE_PANEL_DIR/.env" ]; then
        echo "Panel configuration     : Present"
    else
        echo "Panel configuration     : Not present"
    fi
    if [ -f "$SMITE_NODE_DIR/.env" ]; then
        echo "Node configuration      : Present"
    else
        echo "Node configuration      : Not present"
    fi

    smite_install_pause
}

smite_install_panel_files() {
    local panel_domain="$1"
    local panel_host="${2:-127.0.0.1}"
    local secret_key
    secret_key="$(openssl rand -hex 32)" || return 1

    mkdir -p "$SMITE_PANEL_DIR/panel/data" "$SMITE_PANEL_DIR/panel/certs" || return 1

    if ! smite_download_upstream "docker-compose.yml" "$SMITE_PANEL_COMPOSE"; then
        echo "ERROR: Failed to download the validated Smite panel Compose file."
        return 1
    fi

    if ! smite_install_pin_compose_image "$SMITE_PANEL_COMPOSE" "$SMITE_PANEL_REPO" "$SMITE_PANEL_IMAGE"; then
        echo "ERROR: Failed to pin the validated Smite panel image digest."
        return 1
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        smite_install_clean_rc_broker_prepare || return 1
        smite_install_clean_rc_broker_panel_mount "$SMITE_PANEL_COMPOSE" || return 1
    fi

    smite_install_core_optional_frp_prepare "$SMITE_PANEL_COMPOSE" smite-panel || return 1

    cat > "$SMITE_PANEL_DIR/.env" <<EOF_ENV
PANEL_PORT=8000
PANEL_HOST=$panel_host
HTTPS_ENABLED=false
PANEL_DOMAIN=$panel_domain
SMITE_HTTP_PORT=80
SMITE_HTTPS_PORT=443
SMITE_SSL_DOMAIN=$panel_domain
DOCS_ENABLED=$([ "$SMITE_INSTALL_PROFILE" = clean-rc ] && echo false || echo true)
SMITE_VERSION=$SMITE_UPSTREAM_VERSION

DB_TYPE=sqlite
DB_PATH=./data/smite.db

SECRET_KEY=$secret_key
EOF_ENV
    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        # Secure from first boot. Never expose the legacy anonymous
        # POST /api/nodes machine registration API during IR setup.
        # The signed endpoints remain 503 until separately migrated,
        # provisioned and authorized; no implicit downgrade is allowed.
        cat >> "$SMITE_PANEL_DIR/.env" <<'EOF_RC_PANEL_AUTH'
SMITE_NODE_REGISTRATION_MODE=signed
SMITE_PANEL_AGENT_AUTH_MODE=signed
SMITE_NODE_PAIRING_PREVIEW_ENABLED=false
SMITE_ENGINE_MANAGEMENT_MODE=managed
EOF_RC_PANEL_AUTH
        cat >> "$SMITE_PANEL_DIR/.env" <<'EOF_RC_BROKER_KEY'
SMITE_UOPTI_ROUTE_BROKER_KEY_PATH=/run/secrets/smite-uopti-xhttp-broker.key
EOF_RC_BROKER_KEY
        echo "PANEL_RC_LEGACY_MACHINE_REGISTRATION=DISABLED"
    fi
    chmod 0600 "$SMITE_PANEL_DIR/.env" || return 1

    python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_PANEL_COMPOSE" config >/dev/null || {
        echo "ERROR: Downloaded panel Compose file failed validation."
        return 1
    }

    return 0
}

# The disposable IR install stages the dedicated Broker key for the Panel,
# while leaving the service inactive and all per-child TrustedGrants empty.
# Node reaches the UDS only after a later explicit activation/reconciliation.
smite_install_clean_rc_broker_prepare() {
    [ "$SMITE_INSTALL_PROFILE" = clean-rc ] || return 0
    local module_dir gid helper candidate
    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    helper="$module_dir/smite-rc5-xhttp-broker-provision.py"
    [ -f "$helper" ] && [ ! -L "$helper" ] || {
        echo "HOLD: Clean RC Broker provisioner is not staged." >&2
        return 1
    }
    gid=""
    # A fresh rollback retains the inert dedicated group. Reuse its exact GID
    # on retry; allocating a different one would fail the broker's own guard.
    if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ] && getent group u-opti-smite-peer >/dev/null 2>&1; then
        gid="$(getent group u-opti-smite-peer | awk -F: '$1 == "u-opti-smite-peer" && $3 ~ /^[0-9]+$/ && $4 == "" {print $3}')"
        [[ "$gid" =~ ^[0-9]+$ ]] && [ "$gid" -ge 1 ] && [ "$gid" -lt 65536 ] || return 1
    else
        for candidate in $(seq 39100 39999); do
            if ! getent group "$candidate" >/dev/null 2>&1; then
                gid="$candidate"
                break
            fi
        done
    fi
    [ -n "$gid" ] || { echo "HOLD: No dedicated Broker peer GID available." >&2; return 1; }
    python3 -B "$helper" --peer-gid "$gid" --confirm-local-root || return 1
    SMITE_UOPTI_BROKER_GID="$gid"
    echo "BROKER_PROVISIONING=PASS_INERT"
    echo "BROKER_SERVICE=NOT_ENABLED"
    echo "BROKER_TRUSTED_GRANTS=NONE"
    echo "NODE_BROKER_FORWARDING=DISABLED"
}

smite_install_clean_rc_broker_panel_mount() {
    local compose_file="$1" module_dir="" helper=""
    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    helper="$module_dir/smite-rc5-xhttp-broker-compose.py"
    [ -f "$helper" ] && [ ! -L "$helper" ] || {
        echo "HOLD: Clean RC Broker Compose helper is not staged." >&2
        return 1
    }
    [ -n "${SMITE_UOPTI_BROKER_GID:-}" ] || {
        echo "HOLD: Clean RC Broker GID was not prepared." >&2
        return 1
    }
    python3 -B "$helper" panel "$compose_file" --peer-gid "$SMITE_UOPTI_BROKER_GID"
}

smite_install_clean_rc_broker_start_node_forwarding() {
    [ "$SMITE_INSTALL_PROFILE" = clean-rc ] || return 0
    local module_dir helper activation_output
    [ -n "${SMITE_UOPTI_BROKER_GID:-}" ] || {
        echo "HOLD: IR Broker peer GID was not prepared." >&2
        return 1
    }
    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    helper="$module_dir/smite-rc5-xhttp-broker-provision.py"
    [ -f "$helper" ] && [ ! -L "$helper" ] || {
        echo "HOLD: Root Broker activation helper is not staged." >&2
        return 1
    }
    if ! activation_output="$(python3 -B "$helper" --activate-existing --confirm-local-root 2>&1)" ||
       ! grep -qx 'SERVICE_ACTIVATION=PASS_ACTIVE_PERSISTENT' <<< "$activation_output" ||
       ! grep -qx 'TRUSTED_GRANTS=UNCHANGED' <<< "$activation_output" ||
       ! grep -qx 'LIVE_ROUTE_CHANGE=NO' <<< "$activation_output"; then
        echo "HOLD: Root Broker activation did not pass its systemd/socket checks." >&2
        # The provisioner emits HOLD_REASON (no '='); do not hide its actual failure code.
        # Keep diagnostics restricted to structured status fields (never print secrets).
        grep -E '^(HOLD_[A-Z0-9_]+$|SERVICE_[A-Z0-9_]+=|BROKER_SOCKET=|TRUSTED_GRANTS=|LIVE_ROUTE_CHANGE=)' <<< "$activation_output" >&2 || true
        return 1
    fi
    echo "$activation_output"

    helper="$module_dir/smite-rc5-xhttp-broker-compose.py"
    [ -f "$helper" ] && [ ! -L "$helper" ] || return 1
    python3 -B "$helper" node-env "$SMITE_NODE_DIR/.env" --enabled true || return 1
    if ! python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" config >/dev/null ||
       ! python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node ||
       ! smite_wait_healthy smite-node 90 ||
       ! docker exec smite-node python -c 'import os,socket,stat; p="/run/u-opti/smite/xhttp-broker.sock"; g=int(os.environ["SMITE_UOPTI_BROKER_GID"]); s=os.stat(p); assert os.environ["SMITE_UOPTI_ROUTE_BROKER_ENABLED"]=="true"; assert os.geteuid()==0 and os.getegid()==g; assert stat.S_ISSOCK(s.st_mode) and s.st_uid==0 and s.st_gid==g and stat.S_IMODE(s.st_mode)==0o660; c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); c.settimeout(2); c.connect(p); c.close()'; then
        echo "HOLD: Broker socket forwarding verification failed; pausing Node forwarding." >&2
        python3 -B "$helper" node-env "$SMITE_NODE_DIR/.env" --enabled false >/dev/null 2>&1 || {
            echo "CRITICAL: Could not disable Node Broker forwarding; manual review required." >&2
            return 1
        }
        if ! python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node ||
           ! smite_wait_healthy smite-node 90; then
            echo "CRITICAL: Node rollback health is unconfirmed; Broker forwarding is disabled on disk." >&2
            return 1
        fi
        return 1
    fi
    echo "NODE_BROKER_FORWARDING=PASS_SOCKET_PEER_ATTESTED"
    echo "BROKER_TRUSTED_GRANTS=NONE_ROUTE_APPLY_HOLD"
    return 0
}


# A fresh Foreign Node is intentionally started without any Panel
# registration until per-Node HMAC identity + TLS/443 gateway are admitted.
# This prevents legacy mode from silently using HTTP/8000 over the Internet.
smite_install_clean_rc_pause_foreign_compose() {
    local compose_file="$1"
    [ "$SMITE_INSTALL_PROFILE" = clean-rc ] || return 1
    python3 - "$compose_file" <<'PY_RC_PAUSE'
from pathlib import Path
import sys

path = Path(sys.argv[1])
if path.is_symlink() or not path.is_file():
    raise SystemExit("HOLD: Unsafe Foreign Compose path")
text = path.read_text()
if text.count("  smite-node:\n") != 1 or text.count("    healthcheck:\n") != 1:
    raise SystemExit("HOLD: Unexpected Node Compose healthcheck layout")
reviewed = '      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen(\'http://127.0.0.1:${NODE_API_PORT:-8888}/healthz\')"]'
legacy = '      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen(\'http://localhost:${NODE_API_PORT:-8888}/api/agent/status\')"]'
if text.count(reviewed) == 1:
    print("FOREIGN_RC_HEALTHCHECK=REVIEWED_LOCAL_HEALTHZ")
elif text.count(legacy) == 1:
    # clean-rc uses the reviewed v0.1.7 Compose only as a layout template.
    # The signed RC Node has strict HMAC Agent auth, so its Docker healthcheck
    # must use the dedicated loopback-only /healthz readiness route instead.
    text = text.replace(legacy, reviewed, 1)
    path.write_text(text)
    print("FOREIGN_RC_HEALTHCHECK=MIGRATED_LEGACY_TO_LOCAL_HEALTHZ")
else:
    # Never rewrite an unknown probe/layout.
    raise SystemExit("HOLD: Reviewed local /healthz required for strict Node pairing")
print("FOREIGN_RC_AGENT_AUTH=STRICT_UNTIL_PAIRED")
PY_RC_PAUSE
}

smite_install_node_files() {
    local node_name="$1"
    local node_role="$2"
    local panel_address="$3"
    local ca_source="$4"
    local control_address="${5:-}"
    local backhaul_address="${6:-}"
    local connection_mode="${7:-standard}"
    local broker_compose_helper=""
    local empty_sanaei_dir="$SMITE_NODE_DIR/.sanaei-empty"

    mkdir -p "$SMITE_NODE_DIR/certs" "$SMITE_NODE_DIR/config" || return 1

    if ! smite_download_upstream "node/docker-compose.yml" "$SMITE_NODE_COMPOSE"; then
        echo "ERROR: Failed to download the validated Smite node Compose file."
        return 1
    fi

    if ! smite_install_pin_compose_image "$SMITE_NODE_COMPOSE" "$SMITE_NODE_REPO" "$SMITE_NODE_IMAGE"; then
        echo "ERROR: Failed to pin the validated Smite node image digest."
        return 1
    fi

    if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ]; then
        # A fresh retry must never adopt a retained previous Node identity volume.
        [[ "${COMPOSE_PROJECT_NAME:-}" =~ ^uopti_rc6_[0-9a-f]{32}$ ]] || return 1
        [ "$(grep -c '^    name: smite-node-data$' "$SMITE_NODE_COMPOSE")" = 1 ] || return 1
        sed -i "s/^    name: smite-node-data$/    name: ${COMPOSE_PROJECT_NAME}_node-data/" "$SMITE_NODE_COMPOSE" || return 1
    fi
    smite_install_core_optional_frp_prepare "$SMITE_NODE_COMPOSE" smite-node || return 1

    if [ "$connection_mode" = standard ]; then
        python3 -B "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/smite-node-local-bind.py" \
            "$SMITE_NODE_COMPOSE" --mode standard || return 1
    elif [ "$connection_mode" = private ]; then
        echo "Private Network node API bind unchanged; requires separate private transport migration."
    else
        echo "HOLD: Unknown node connection mode: $connection_mode" >&2
        return 1
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        # Both local IR and remote KH Nodes must start paused + strict:
        # even the first IR Node must NOT post unsigned registration.
        smite_install_clean_rc_pause_foreign_compose "$SMITE_NODE_COMPOSE" || return 1
        echo "NODE_RC_REGISTRATION=PAUSED_UNTIL_SIGNED_PAIRING"
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ] && [ "$node_role" = foreign ]; then
        # Signed mode uses the system TLS trust store, not legacy Panel CA.
        # No unauthenticated CA download or unpaired registration on KH.
        echo "FOREIGN_RC_CA_DOWNLOAD=DEFERRED_UNTIL_SECURE_ADMISSION"
    else
        if [ "$ca_source" != "$SMITE_NODE_DIR/certs/ca.crt" ]; then
            cp -f "$ca_source" "$SMITE_NODE_DIR/certs/ca.crt" || return 1
        fi
        chmod 0644 "$SMITE_NODE_DIR/certs/ca.crt" || return 1
    fi

    cat > "$SMITE_NODE_DIR/.env" <<EOF_ENV
NODE_API_PORT=8888
NODE_NAME=$node_name
NODE_ROLE=$node_role
SMITE_VERSION=$SMITE_UPSTREAM_VERSION

PANEL_CA_PATH=/etc/smite-node/certs/ca.crt
PANEL_ADDRESS=$panel_address
PANEL_API_PORT=8000
EOF_ENV

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        # Both roles fail closed: no unsigned HTTP/8000 registration or
        # unauthenticated Agent commands before admin-approved pairing.
        cat >> "$SMITE_NODE_DIR/.env" <<'EOF_RC_AUTH'
SMITE_NODE_PANEL_AUTH_MODE=paused
SMITE_AGENT_AUTH_MODE=strict
SMITE_ENGINE_INVENTORY_MODE=managed
EOF_RC_AUTH
        if [ "$node_role" = iran ]; then
            [ -n "${SMITE_UOPTI_BROKER_GID:-}" ] || {
                echo "HOLD: IR Broker peer GID was not prepared." >&2
                return 1
            }
            cat >> "$SMITE_NODE_DIR/.env" <<EOF_RC_IR_BROKER
SMITE_UOPTI_BROKER_GID=$SMITE_UOPTI_BROKER_GID
SMITE_UOPTI_ROUTE_BROKER_ENABLED=false
SMITE_UOPTI_ROUTE_BROKER_SOCKET=/run/u-opti/smite/xhttp-broker.sock
EOF_RC_IR_BROKER
            broker_compose_helper="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/smite-rc5-xhttp-broker-compose.py"
            [ -f "$broker_compose_helper" ] && [ ! -L "$broker_compose_helper" ] || return 1
            python3 -B "$broker_compose_helper" node-prepare "$SMITE_NODE_COMPOSE" \
                --peer-gid "$SMITE_UOPTI_BROKER_GID" || return 1
        elif [ "$node_role" = foreign ]; then
            mkdir -p "$(dirname "$empty_sanaei_dir")" || return 1
            if [ -e "$empty_sanaei_dir" ] || [ -L "$empty_sanaei_dir" ]; then
                [ -d "$empty_sanaei_dir" ] && [ ! -L "$empty_sanaei_dir" ] &&
                [ "$(stat -c '%u:%a' "$empty_sanaei_dir" 2>/dev/null)" = "0:700" ] &&
                [ -z "$(find "$empty_sanaei_dir" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ] || {
                    echo "HOLD: Default empty Sanaei mount directory is unsafe or not empty." >&2
                    return 1
                }
            else
                mkdir -m 0700 "$empty_sanaei_dir" || return 1
                chown 0:0 "$empty_sanaei_dir" || return 1
            fi
            cat >> "$SMITE_NODE_DIR/.env" <<EOF_RC_KH_SANAEI
SMITE_SANAEI_DB_HOST_PATH=$empty_sanaei_dir
SMITE_SANAEI_INVENTORY_ENABLED=false
EOF_RC_KH_SANAEI
        fi
        echo "NODE_RC_PAIRING=PENDING_NO_OUTBOUND_REGISTRATION"
        if [ "$node_role" = foreign ]; then
            echo "FOREIGN_RC_PAIRING=PENDING_NO_OUTBOUND_REGISTRATION"
        fi
    fi

    if [ -n "$control_address" ]; then
        printf 'SMITE_CONTROL_ADDRESS=%s\n' "$control_address" >> "$SMITE_NODE_DIR/.env"
    fi

    if [ -n "$backhaul_address" ]; then
        printf 'SMITE_BACKHAUL_ADDRESS=%s\n' "$backhaul_address" >> "$SMITE_NODE_DIR/.env"
    fi

    chmod 0600 "$SMITE_NODE_DIR/.env" || return 1

    python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" config >/dev/null || {
        echo "ERROR: Downloaded node Compose file failed validation."
        return 1
    }

    return 0
}

smite_install_pull_images() {
    local need_panel="${1:-false}"
    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        local role=foreign
        [ "$need_panel" = true ] && role=panel-iran
        smite_install_clean_rc_load_images "$role"
        return $?
    fi
    if [ "$SMITE_INSTALL_PROFILE" != stable ]; then
        echo "HOLD: Unknown Smite installation profile" >&2
        return 1
    fi

    if [ "$need_panel" = "true" ]; then
        echo "Pulling $SMITE_PANEL_IMAGE ..."
        docker pull "$SMITE_PANEL_IMAGE" || return 1
    fi

    echo "Pulling $SMITE_NODE_IMAGE ..."
    docker pull "$SMITE_NODE_IMAGE" || return 1
}

smite_wait_panel_api() {
    local tries=0
    while [ "$tries" -lt 30 ]; do
        if curl -fsS --max-time 3 http://127.0.0.1:8000/api/status >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        tries=$((tries + 1))
    done
    return 1
}

smite_wait_node_registration_local() {
    local node_name="$1"
    local tries=0
    local escaped_name
    escaped_name="${node_name//\'/\'\'}"

    while [ "$tries" -lt 45 ]; do
        if [ -f "$SMITE_PANEL_DIR/panel/data/smite.db" ]; then
            if sqlite3 "$SMITE_PANEL_DIR/panel/data/smite.db" \
                "SELECT count(*) FROM nodes WHERE json_extract(metadata,'$.node_name')='$escaped_name' AND status='active';" 2>/dev/null | grep -q '^1$'; then
                return 0
            fi
        fi
        sleep 2
        tries=$((tries + 1))
    done
    return 1
}

smite_set_local_control_address() {
    local node_name="$1"
    local db="$SMITE_PANEL_DIR/panel/data/smite.db"
    local escaped_name
    escaped_name="${node_name//\'/\'\'}"

    [ -f "$db" ] || return 1

    sqlite3 "$db" <<SQL
UPDATE nodes
SET metadata = json_set(COALESCE(metadata, '{}'), '$.control_address', 'http://127.0.0.1:8888')
WHERE json_extract(metadata, '$.node_name') = '$escaped_name'
  AND json_extract(metadata, '$.role') = 'iran';
SQL
}

smite_recreate_with_overlays_noninteractive() {
    if smite_container_exists smite-panel && [ -f "$SMITE_PANEL_COMPOSE" ]; then
        echo "Recreating smite-panel with persistent compatibility overlays..."
        python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_PANEL_COMPOSE" up -d --no-build --force-recreate smite-panel || return 1
        smite_wait_healthy smite-panel 90 || return 1
    fi

    if smite_container_exists smite-node && [ -f "$SMITE_NODE_COMPOSE" ]; then
        echo "Recreating smite-node with persistent compatibility overlays..."
        python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node || return 1
        smite_wait_healthy smite-node 90 || return 1
    fi

    return 0
}

smite_install_apply_compatibility() {
    # New security image source already contains the validated FRP/Backhaul
    # modules. Never graft v0.1.7 host Python patches onto clean RC images:
    # that would mask new signed HMAC routers and might require a second
    # container recreation. Existing stable v0.1.7 flow is unchanged.
    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        echo "CLEAN_RC_LEGACY_HOST_OVERLAYS=SKIPPED"
        echo "CLEAN_RC_SECOND_CONTAINER_RECREATE=SKIPPED"
        return 0
    fi
    echo
    echo "Preparing the tested U-OPTI Smite compatibility layer..."
    smite_prepare_overlays || return 1
    smite_patch_compose_mounts || return 1
    smite_recreate_with_overlays_noninteractive || return 1
}

smite_install_panel_iran() {
    clear
    echo "======================================"
    echo "     Install Smite Panel + Iran"
    echo "======================================"
    echo
    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        if smite_install_clean_rc_signed_registry_selected; then
            echo "FIELD TRIAL ONLY: signed Smite RC from immutable registry digests."
        else
            echo "PREVIEW ONLY: clean Smite RC from verified local Panel/Node images."
        fi
        echo "Not a production release; no live tunneling is configured here."
    else
        echo "This installs the Smite version validated by U-OPTI: $SMITE_UPSTREAM_VERSION"
    fi
    echo "Panel API bind address depends on the selected connection mode."
    echo "The Iran node always bootstraps against the local panel endpoint."
    if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ]; then
        echo "HTTPS/443 and secure local IR enrollment are included before admin creation."
    else
        echo "TCP/443 gateway configuration is handled as a separate step."
    fi
    echo

    smite_install_require_tools || { smite_install_pause; return "${SMITE_INSTALL_FAILURE_CODE:-0}"; }
    smite_install_ensure_docker || { echo "Docker is required."; smite_install_pause; return "${SMITE_INSTALL_FAILURE_CODE:-0}"; }

    if smite_container_exists smite-panel || smite_container_exists smite-node || \
       [ -f "$SMITE_PANEL_COMPOSE" ] || [ -f "$SMITE_NODE_COMPOSE" ]; then
        echo "ERROR: An existing Smite installation was detected."
        echo "Use Status/Repair instead of the fresh installer."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    local panel_domain node_name
    local connection_choice="" confirm="" create_admin=""
    local connection_mode="standard"
    local panel_private_ip=""
    local panel_host="127.0.0.1"

    read -rp "Panel domain (example: ir.example.com): " panel_domain
    panel_domain="${panel_domain,,}"
    if ! smite_install_validate_domain "$panel_domain"; then
        echo "ERROR: Invalid panel domain."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    read -rp "Iran node name [node-ir]: " node_name
    node_name="${node_name:-node-ir}"
    if ! smite_install_validate_name "$node_name"; then
        echo "ERROR: Invalid node name. Use letters, numbers, dot, dash, or underscore."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        # The disposable clean profile has exactly one supported mode.
        # Do not ask beginners to select an option that will be rejected.
        connection_choice=1
        echo "Connection mode: Standard (automatic for clean install)"
    else
        echo
        echo "Connection mode:"
        echo "1) Standard / Local"
        echo "2) Private Network"
        echo
        read -rp "Please enter your selection [1-2]: " connection_choice
        connection_choice="${connection_choice#"${connection_choice%%[![:space:]]*}"}"
        connection_choice="${connection_choice%"${connection_choice##*[![:space:]]}"}"
    fi

    if [ "$SMITE_FRP_TRIAL_ONLY" = 1 ] && [ "$connection_choice" != 1 ]; then
        echo "ERROR: The FRP trial guide requires Standard mode (option 1)."
        echo "No Private Network installation was started."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    case "$connection_choice" in
        1)
            connection_mode="standard"
            panel_host="127.0.0.1"
            ;;
        2)
            connection_mode="private"

            read -rp "Iran Private IPv4 address: " panel_private_ip
            panel_private_ip="${panel_private_ip//[[:space:]]/}"

            if ! smite_install_validate_ipv4 "$panel_private_ip"; then
                echo "ERROR: Invalid Private IPv4 address."
                smite_install_pause
                return "${SMITE_INSTALL_FAILURE_CODE:-0}"
            fi

            if ! ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1 | grep -Fxq "$panel_private_ip"; then
                echo "ERROR: Private IPv4 address is not configured on this server:"
                echo "       $panel_private_ip"
                smite_install_pause
                return "${SMITE_INSTALL_FAILURE_CODE:-0}"
            fi

            panel_host="0.0.0.0"
            ;;
        *)
            echo "ERROR: Invalid connection mode."
            smite_install_pause
            return "${SMITE_INSTALL_FAILURE_CODE:-0}"
            ;;
    esac

    echo
    echo "Panel domain : $panel_domain"
    echo "Iran node    : $node_name"
    echo "Connection   : $connection_mode"
    if [ "$connection_mode" = "private" ]; then
        echo "Private IP   : $panel_private_ip"
    fi
    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        if smite_install_clean_rc_signed_registry_selected; then
            echo "Smite profile: clean-rc signed-registry Field Trial"
        else
            echo "Smite profile: clean-rc (unpublished preview)"
        fi
    else
        echo "Smite version: $SMITE_UPSTREAM_VERSION"
    fi
    echo
    # Selected fresh option 1 was already explicitly approved before core
    # installation began. Retain this prompt for independent/manual calls.
    if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ] &&
       [ "${SMITE_INSTALL_PROFILE:-}" = clean-rc ]; then
        echo 'IR_CORE_CONSENT=INHERITED_FROM_SELECTED_OPTION_1'
    else
        read -rp "Install Smite Panel + Iran Node? [y/N]: " confirm || return "${SMITE_INSTALL_FAILURE_CODE:-0}"
        case "$confirm" in
            y|Y|yes|YES) ;;
            *) echo "Installation cancelled."; sleep 1; return "${SMITE_INSTALL_FAILURE_CODE:-0}" ;;
        esac
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        if ! smite_install_clean_rc_preflight "panel-iran" "$connection_mode"; then
            echo "HOLD: Clean RC prerequisites not met; no service started."
            smite_install_pause
            return "${SMITE_INSTALL_FAILURE_CODE:-0}"
        fi
    elif [ "$SMITE_INSTALL_PROFILE" != stable ]; then
        echo "HOLD: Unknown Smite install profile."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    mkdir -p "$SMITE_PANEL_DIR" "$SMITE_NODE_DIR" || {
        echo "ERROR: Failed to create Smite directories."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    }

    if ! smite_install_panel_files "$panel_domain" "$panel_host"; then
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_install_cli_tools; then
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_install_pull_images true; then
        echo "ERROR: Failed to pull the validated Smite images."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    echo
    echo "Starting Smite Panel on ${panel_host}:8000..."
    if ! python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_PANEL_COMPOSE" up -d --no-build smite-panel; then
        echo "ERROR: Failed to start Smite Panel."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_wait_healthy smite-panel 90 || ! smite_wait_panel_api; then
        echo "ERROR: Smite Panel did not become healthy."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_install_core_optional_frp_verify smite-panel; then
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    mkdir -p "$SMITE_NODE_DIR/certs" || {
        echo "ERROR: Failed to create the Smite node certificate directory."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    }

    echo "Downloading the Iran-node CA certificate from the local panel..."
    if ! curl -fsS --retry 5 \
        http://127.0.0.1:8000/api/panel/ca \
        -o "$SMITE_NODE_DIR/certs/ca.crt"; then
        echo "ERROR: Failed to obtain the Iran-node CA certificate."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! grep -q "BEGIN CERTIFICATE" "$SMITE_NODE_DIR/certs/ca.crt"; then
        echo "ERROR: The panel returned an invalid CA certificate."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_install_node_files \
        "$node_name" \
        "iran" \
        "127.0.0.1:8000" \
        "$SMITE_NODE_DIR/certs/ca.crt" \
        "" \
        "$panel_private_ip" \
        "$connection_mode"; then
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    echo "Starting Iran Smite Node..."
    if ! python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" up -d --no-build smite-node; then
        echo "ERROR: Failed to start Smite Node."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_wait_healthy smite-node 90; then
        echo "ERROR: Smite Node did not become healthy."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_install_core_optional_frp_verify smite-node; then
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        if ! smite_install_clean_rc_broker_start_node_forwarding; then
            echo "ERROR: Root Broker/Node channel did not pass verification."
            smite_install_pause
            return "${SMITE_INSTALL_FAILURE_CODE:-0}"
        fi
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        echo "IR_RC_PAIRING=PENDING_SIGNED_ADMIN_APPROVAL"
        echo "IR_RC_LEGACY_REGISTRATION_WAIT=SKIPPED"
    elif ! smite_wait_node_registration_local "$node_name"; then
        echo "ERROR: The Iran node did not register with the local panel."
        echo "Check: docker logs smite-node"
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_install_apply_compatibility; then
        echo "ERROR: U-OPTI compatibility preparation failed."
        echo "The expected upstream source blocks may have changed."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        # A not-yet-registered Node has no approved row to update.
        # Never write a guessed control address or fake Connected status.
        echo "IR_RC_CONTROL_ORIGIN=DEFERRED_UNTIL_SECURE_PAIRING"
    else
        if ! smite_wait_node_registration_local "$node_name"; then
            echo "ERROR: Node registration was not restored after compatibility activation."
            smite_install_pause
            return "${SMITE_INSTALL_FAILURE_CODE:-0}"
        fi
        if smite_set_local_control_address "$node_name"; then
            echo "Panel control address set to local node API (127.0.0.1:8888)."
        else
            echo "WARNING: Could not set the local panel control address automatically."
        fi
    fi

    smite_write_state \
        "panel-iran" \
        "$panel_domain" \
        "$node_name" \
        "" \
        "$connection_mode" \
        "$panel_private_ip" \
        "" || {
        echo "WARNING: Smite installed, but U-OPTI state could not be saved."
        if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ]; then return 2; fi
    }

    # The selected installer owns the remaining gateway, enrollment and admin
    # steps. Do not announce completion or ask for credentials before those.
    if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ]; then
        echo 'IR_CORE=READY; continuing HTTPS and secure local enrollment...'
        return 0
    fi

    echo
    echo "======================================"
    echo "      Smite Core Install Complete"
    echo "======================================"
    echo
    if [ "$connection_mode" = "private" ]; then
        echo "Panel       : running on 0.0.0.0:8000"
        echo "Private API : http://${panel_private_ip}:8000"
        echo "Backhaul IP : $panel_private_ip"
    else
        echo "Panel       : running on 127.0.0.1:8000"
    fi
    echo "Iran Node   : running on port 8888"
    echo "Panel Domain: $panel_domain"
    echo "Connection  : $connection_mode"
    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        echo "Compatibility overlays: skipped (features are in RC images)"
    else
        echo "Compatibility overlays: active"
    fi
    echo
    echo "IMPORTANT: TCP/443 gateway is not configured by this installer step yet."
    if [ "$connection_mode" = "private" ]; then
        echo "Keep public ports 8000 and 8888 blocked at the firewall/provider level."
        echo "Port 8000 is intended for the private network only."
    else
        echo "Keep public ports 8000 and 8888 blocked at the firewall/provider level."
    fi
    echo
    read -rp "Create a Smite admin account now? [y/N]: " create_admin
    case "$create_admin" in
        y|Y|yes|YES)
            smite_install_create_admin || {
                echo "HOLD: Smite admin account was not created."
                if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ]; then return 2; fi
            }
            ;;
    esac

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        echo
        echo "===== IR Node enrollment (required after core install) ====="
        echo "IR_NODE_CONTAINER=HEALTHY_NOT_YET_PAIRED"
        echo "IR_PANEL_NODE_REGISTRATION=PENDING_ADMIN_APPROVAL"
        echo "The Iran Node is installed, but will NOT appear in the Panel's"
        echo "Iran Nodes list until an administrator reserves and securely pairs it."
        echo "Do NOT run Install Panel + Iran Node again to register it."
        echo "1. Verify/configure the Panel's HTTPS/443 gateway first."
        echo "2. U-OPTI -> Docker Management -> Smite Management ->"
        echo "   Advanced -> Signed Pairing: check status, then enable Panel pairing."
        echo "3. Panel -> Iran Nodes -> Add Iran Server: reserve NAME $node_name."
        echo "   This creates a pending Panel record, NOT another Docker Node."
        echo "4. Issue a one-time pairing code in the Panel, redeem in Advanced,"
        echo "   then activate signed IR runtime and verify authenticated check-in."
        echo "PAIRING_ACTIVATION=OPERATOR_APPROVAL_REQUIRED"
        echo "PRODUCTION_ACTIVATION=NO"
    fi
    smite_install_pause
}

smite_install_foreign_node() {
    clear
    echo "======================================"
    echo "       Install Foreign Smite Node"
    echo "======================================"
    echo
    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        if smite_install_clean_rc_signed_registry_selected; then
            echo "FIELD TRIAL ONLY: signed Smite Node from an immutable registry digest."
        else
            echo "PREVIEW ONLY: clean Smite Node from a verified local RC image."
        fi
        echo "Set the real 3x-UI inbound and tunnel only after both servers install."
    else
        echo "This installs the validated Smite node image: $SMITE_UPSTREAM_VERSION"
    fi
    echo "Choose Standard HTTPS or Private Network transport."
    echo

    smite_install_require_tools || { smite_install_pause; return "${SMITE_INSTALL_FAILURE_CODE:-0}"; }
    smite_install_ensure_docker || { echo "Docker is required."; smite_install_pause; return "${SMITE_INSTALL_FAILURE_CODE:-0}"; }

    if smite_container_exists smite-node || [ -f "$SMITE_NODE_COMPOSE" ]; then
        echo "ERROR: An existing Smite node installation was detected."
        echo "Use Status/Repair instead of the fresh installer."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    local panel_domain foreign_domain node_name temp_ca
    local connection_choice="" confirm=""
    local connection_mode="standard"
    local panel_private_ip=""
    local foreign_private_ip=""
    local panel_address=""
    local control_address=""
    local ca_url=""

    # When the private Iran-Panel packet has already been captured by the
    # one-choice coordinator, use its exact nonsecret scope. Never ask
    # the operator to retype three values that the Panel already issued.
    # This branch is internal/trial only: public option 2 does not yet
    # capture the packet or enable signed trial runtime activation.
    if [ -n "${UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE:-}" ]; then
        if [ "${SMITE_SELECTED_FRESH:-0}" != 1 ] ||
           [ "${SMITE_INSTALL_PROFILE:-}" != clean-rc ]; then
            echo 'HOLD: Foreign Panel packet is not approved for standalone installation.' >&2
            return 2
        fi
        local module_dir core_fields
        local -a issued_fields=()
        module_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || return 2
        core_fields="$(python3 -B "$module_dir/smite-unified-foreign-gateway-plan.py" \
            --packet-file "$UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE" \
            --precore-fields)" || {
            echo 'HOLD: Panel-issued Foreign information is invalid or expired.' >&2
            return 2
        }
        mapfile -t issued_fields <<< "$core_fields"
        [ "${#issued_fields[@]}" -eq 4 ] || return 2
        panel_domain="${issued_fields[0]}"
        foreign_domain="${issued_fields[1]}"
        node_name="${issued_fields[2]}"
        # The existing smite_install_node_files already accepts this
        # address as its fifth parameter. Bind the Panel-issued path
        # BEFORE the first paused Node boot; do not recreate it at Gateway.
        control_address="${issued_fields[3]}"
        [[ "$control_address" =~ ^https://[a-z0-9.-]+:443/smite-node/[a-f0-9]{32}$ ]] &&
        [ "${control_address#https://${foreign_domain}:443/smite-node/}" != "$control_address" ] &&
        smite_install_validate_domain "$panel_domain" &&
        smite_install_validate_domain "$foreign_domain" &&
        smite_install_validate_name "$node_name" || return 2
        echo 'FOREIGN_CORE_INPUT=VERIFIED_PANEL_PACKET'
    else
        read -rp "Panel domain (example: ir.example.com): " panel_domain
        panel_domain="${panel_domain,,}"
        if ! smite_install_validate_domain "$panel_domain"; then
            echo "ERROR: Invalid panel domain."
            smite_install_pause
            return "${SMITE_INSTALL_FAILURE_CODE:-0}"
        fi

        read -rp "This foreign server domain (example: kh.example.com): " foreign_domain
        foreign_domain="${foreign_domain,,}"
        if ! smite_install_validate_domain "$foreign_domain"; then
            echo "ERROR: Invalid foreign-server domain."
            smite_install_pause
            return "${SMITE_INSTALL_FAILURE_CODE:-0}"
        fi

        read -rp "Foreign node name [node-kh]: " node_name
        node_name="${node_name:-node-kh}"
        if ! smite_install_validate_name "$node_name"; then
            echo "ERROR: Invalid node name."
            smite_install_pause
            return "${SMITE_INSTALL_FAILURE_CODE:-0}"
        fi
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        connection_choice=1
        echo "Connection mode: Standard / HTTPS (automatic for clean install)"
    else
        echo
        echo "Connection mode:"
        echo "1) Standard / HTTPS"
        echo "2) Private Network"
        echo
        read -rp "Please enter your selection [1-2]: " connection_choice
        connection_choice="${connection_choice#"${connection_choice%%[![:space:]]*}"}"
        connection_choice="${connection_choice%"${connection_choice##*[![:space:]]}"}"
    fi

    if [ "$SMITE_FRP_TRIAL_ONLY" = 1 ] && [ "$connection_choice" != 1 ]; then
        echo "ERROR: The FRP trial guide requires Standard mode (option 1)."
        echo "No Private Network installation was started."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    case "$connection_choice" in
        1)
            connection_mode="standard"
            panel_address="${panel_domain}:443"
            ca_url="https://${panel_domain}/api/panel/ca/server"
            ;;

        2)
            connection_mode="private"

            read -rp "Iran Panel Private IPv4 address: " panel_private_ip
            panel_private_ip="${panel_private_ip//[[:space:]]/}"

            if ! smite_install_validate_ipv4 "$panel_private_ip"; then
                echo "ERROR: Invalid Iran Panel Private IPv4 address."
                smite_install_pause
                return "${SMITE_INSTALL_FAILURE_CODE:-0}"
            fi

            read -rp "This Foreign server Private IPv4 address: " foreign_private_ip
            foreign_private_ip="${foreign_private_ip//[[:space:]]/}"

            if ! smite_install_validate_ipv4 "$foreign_private_ip"; then
                echo "ERROR: Invalid Foreign Private IPv4 address."
                smite_install_pause
                return "${SMITE_INSTALL_FAILURE_CODE:-0}"
            fi

            if ! ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1 | grep -Fxq "$foreign_private_ip"; then
                echo "ERROR: Foreign Private IPv4 address is not configured on this server:"
                echo "       $foreign_private_ip"
                smite_install_pause
                return "${SMITE_INSTALL_FAILURE_CODE:-0}"
            fi

            panel_address="${panel_private_ip}:8000"
            control_address="http://${foreign_private_ip}:8888"
            ca_url="http://${panel_address}/api/panel/ca/server"
            ;;

        *)
            echo "ERROR: Invalid connection mode."
            smite_install_pause
            return "${SMITE_INSTALL_FAILURE_CODE:-0}"
            ;;
    esac

    echo
    echo "Panel domain   : $panel_domain"
    echo "Foreign domain : $foreign_domain"
    echo "Node name      : $node_name"
    echo "Connection     : $connection_mode"

    if [ "$connection_mode" = "private" ]; then
        echo "Panel private  : $panel_private_ip"
        echo "Foreign private : $foreign_private_ip"
        echo "Panel transport: http://$panel_address"
        echo "Node control   : $control_address"
    else
        echo "Panel transport: https://$panel_address"
    fi

    echo
    # The one-choice option-2 entry already received explicit fresh-install
    # approval. Do not ask a second approval for this same core stage.
    # Standalone/legacy Foreign installation keeps its original confirmation.
    if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ] &&
       [ "${SMITE_INSTALL_PROFILE:-}" = clean-rc ]; then
        echo 'FOREIGN_CORE_CONSENT=INHERITED_FROM_SELECTED_OPTION_2'
    else
        read -rp "Install the Foreign Smite Node? [y/N]: " confirm || return "${SMITE_INSTALL_FAILURE_CODE:-0}"
        case "$confirm" in
            y|Y|yes|YES) ;;
            *) echo "Installation cancelled."; sleep 1; return "${SMITE_INSTALL_FAILURE_CODE:-0}" ;;
        esac
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        if ! smite_install_clean_rc_preflight "foreign" "$connection_mode"; then
            echo "HOLD: Clean RC prerequisites not met; no service started."
            smite_install_pause
            return "${SMITE_INSTALL_FAILURE_CODE:-0}"
        fi
    elif [ "$SMITE_INSTALL_PROFILE" != stable ]; then
        echo "HOLD: Unknown Smite install profile."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    mkdir -p "$SMITE_NODE_DIR/certs" "$SMITE_NODE_DIR/config" || {
        echo "ERROR: Failed to create Smite node directories."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    }

    temp_ca="$(mktemp)" || {
        echo "ERROR: Failed to create temporary CA file."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    }

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        echo "Foreign RC: HTTPS/443 CA download deferred; Node will boot paused."
        echo "Pairing and gateway setup happen after IR and KH core installation."
    elif ! curl -fsS --retry 5 \
        "$ca_url" \
        -o "$temp_ca"; then

        rm -f "$temp_ca"

        if [ "$connection_mode" = "private" ]; then
            echo "ERROR: Could not reach the Panel over the Private Network."
            echo "Check:"
            echo "  - Private Network connectivity"
            echo "  - Panel Private IP"
            echo "  - Panel TCP/8000 availability"
        else
            echo "ERROR: Could not reach the Panel CA endpoint over HTTPS/443."
            echo "Configure the IR Panel 443 gateway before installing a Foreign node."
        fi

        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if [ "$SMITE_INSTALL_PROFILE" != clean-rc ] && ! grep -q "BEGIN CERTIFICATE" "$temp_ca"; then
        rm -f "$temp_ca"
        echo "ERROR: The panel returned an invalid Foreign-node CA certificate."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_install_node_files \
        "$node_name" \
        "foreign" \
        "$panel_address" \
        "$temp_ca" \
        "$control_address" \
        "" \
        "$connection_mode"; then

        rm -f "$temp_ca"
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    rm -f "$temp_ca"

    if ! smite_install_cli_tools; then
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_install_pull_images false; then
        echo "ERROR: Failed to pull the validated Smite node image."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    echo "Starting Foreign Smite Node..."
    if ! python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" up -d --no-build smite-node; then
        echo "ERROR: Failed to start the Foreign Smite Node."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_wait_healthy smite-node 90; then
        echo "ERROR: Foreign Smite Node did not become healthy."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_install_core_optional_frp_verify smite-node; then
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if ! smite_install_apply_compatibility; then
        echo "ERROR: U-OPTI compatibility preparation failed."
        smite_install_pause
        return "${SMITE_INSTALL_FAILURE_CODE:-0}"
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        echo "Foreign node: installed and running locally; pairing is still REQUIRED."
        echo "FOREIGN_RC_CONNECTED=NO"
        echo "FOREIGN_RC_REINSTALL_REQUIRED=NO"
    else
        sleep 3
        if ! docker logs --since 2m smite-node 2>&1 | grep -q 'Node registered successfully'; then
            echo "WARNING: Node registration success was not found in the recent logs."
            echo "Check: docker logs smite-node"
        else
            echo "Foreign node registration: OK"
        fi
    fi

    smite_write_state \
        "foreign" \
        "$panel_domain" \
        "$node_name" \
        "$foreign_domain" \
        "$connection_mode" \
        "$panel_private_ip" \
        "$foreign_private_ip" || {
        echo "WARNING: Smite installed, but U-OPTI state could not be saved."
        if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ]; then return 2; fi
    }

    # Selected option 2 is a continuous transaction, NOT a successful
    # Foreign installation after core alone. Resume at Sanaei/Gateway/
    # Panel-issued enrollment when the signed trial activation gate permits.
    # Never present the standalone "Install Complete" banner here.
    if [ "${SMITE_SELECTED_FRESH:-0}" = 1 ]; then
        echo 'FOREIGN_CORE=READY_PAUSED_FOR_UNIFIED_CONTINUATION'
        echo 'FOREIGN_CONNECTED=NOT_PROVEN'
        return 0
    fi

    echo
    echo "======================================"
    echo "     Foreign Node Install Complete"
    echo "======================================"
    echo
    echo "Node          : $node_name"
    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        echo "Status        : Installed / Waiting for secure pairing"
    fi
    echo "Panel domain  : $panel_domain"
    echo "Foreign domain: $foreign_domain"
    echo "Connection    : $connection_mode"

    if [ "$connection_mode" = "private" ]; then
        echo "Panel private : $panel_private_ip"
        echo "Foreign private : $foreign_private_ip"
        echo "Panel transport: http://$panel_address"
        echo "Node control  : $control_address"
    else
        echo "Panel         : https://$panel_domain:443"
    fi

    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        echo "Compatibility overlays: skipped (features are in RC images)"
    else
        echo "Compatibility overlays: active"
    fi
    echo

    if [ "$connection_mode" = "private" ]; then
        echo "Private Network mode is active."
        echo "Keep public ports 8000 and 8888 blocked at the firewall/provider level."
        echo "Machine-to-machine control traffic uses the private network."
    elif [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        echo "NEXT: Install/attach Sanaei (option 4), configure KH Gateway (option 6), then Signed Pairing."
        echo "DO NOT enable legacy Panel registration or open port 8000/8888."
        echo "No second Smite installation should be required."
    else
        echo "IMPORTANT: Panel -> Foreign Node control over 443 is configured in the gateway step."
        echo "Keep public port 8888 blocked at the firewall/provider level."
    fi

    smite_install_pause
}

# Result contract for unified installation: 0 = verified attachment (signed
# lane), 2 = failure/cancelled, 3 = Sanaei installed but attachment still pending.
# The legacy non-signed lane continues returning its original installer result.
smite_install_sanaei_foreign() {
    local current_role="" helper selected="" backup="" choice="" index="" runtime_env=""
    local signed_foreign=0 compose_project="" compose_service="" compose_files=""
    local staged_identity=0 staged_identity_sha="" staged_identity_file=""
    local pairing_helper="" recover_confirmation=""
    local -a instance_ids=() usable_ids=()

    # Preserve the same visible progress stream during one-choice
    # fresh installation instead of clearing its terminal output.
    if [ "${UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER:-0}" != 1 ] ||
       [ "${SMITE_SELECTED_FRESH:-0}" != 1 ]; then
        clear
    fi
    echo "======================================"
    echo "    Sanaei 3x-UI for Smite Foreign"
    echo "======================================"
    echo

    if [ ! -f "$SMITE_STATE_FILE" ]; then
        echo "ERROR: Smite managed state was not found."
        echo
        echo "Install the Smite Foreign Node first."
        smite_install_pause
        return 2
    fi

    # shellcheck disable=SC1090
    source "$SMITE_STATE_FILE" || return 2
    current_role="${SMITE_ROLE:-}"

    if [ "$current_role" != "foreign" ]; then
        echo "ERROR: This option is available only on a Smite Foreign Node."
        echo
        echo "Detected role: ${current_role:-Unknown}"
        smite_install_pause
        return 2
    fi

    # A fresh RC7 install is selected inside an installer subshell. On the
    # next menu visit SMITE_INSTALL_PROFILE is once again "stable"; its
    # persisted managed version, not that transient variable, decides whether
    # existing Sanaei must be ATTACHED instead of installed again.
    case "${SMITE_MANAGED_VERSION:-}" in
        2.0.0-rc.1|2.0.0-rc.7) signed_foreign=1 ;;
    esac
    if [ "$SMITE_MANAGED_VERSION" = "2.0.0-rc.7" ]; then
        compose_project="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' smite-node 2>/dev/null)" || compose_project=""
        compose_service="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' smite-node 2>/dev/null)" || compose_service=""
        compose_files="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' smite-node 2>/dev/null)" || compose_files=""
        if [[ ! "$compose_project" =~ ^uopti_rc6_[0-9a-f]{32}$ ]] ||
           [ "$compose_service" != smite-node ] || [ "$compose_files" != "$SMITE_NODE_COMPOSE" ]; then
            echo "HOLD: RC7 Foreign Node Compose ownership is not the verified fresh transaction." >&2
            smite_install_pause
            return 2
        fi
    fi

    # Normal order remains Sanaei -> Gateway -> Pairing. Narrow exception:
    # a previously redeemed but NOT activated RC7 KH identity may attach the
    # already installed Sanaei database after exact read-only admission.
    # Never remove/replace the identity, replay DB or signed runtime overlay.
    if [ "$signed_foreign" -eq 1 ]; then
        staged_identity_file="$SMITE_STATE_DIR/identities/node-identity.json"
        if [ -e "$staged_identity_file" ] || [ -L "$staged_identity_file" ]; then
            pairing_helper="$(dirname "${BASH_SOURCE[0]}")/smite-node-pairing.py"
            if [ "$SMITE_MANAGED_VERSION" != "2.0.0-rc.7" ] ||
               [ ! -f "$staged_identity_file" ] || [ -L "$staged_identity_file" ] ||
               [ ! -f "$pairing_helper" ] || [ -L "$pairing_helper" ]; then
                echo "HOLD: Install/attach Sanaei before pairing while KH is paused + strict. (RC7-only staged identity recovery)" >&2
                smite_install_pause
                return 2
            fi
            if UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES python3 -B "$pairing_helper" \
                 --verify-staged-foreign-sanaei >/dev/null 2>&1; then
                echo "KH_SANAEI_INVENTORY=ALREADY_ATTACHED_VERIFIED"
                echo "PAIRING_IDENTITY=PRESERVED"
                smite_install_pause
                return 0
            fi
            if ! UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES python3 -B "$pairing_helper" \
                 --admit-staged-foreign-sanaei; then
                echo "HOLD: Staged pairing Sanaei recovery admission refused; no Node changes." >&2
                smite_install_pause
                return 2
            fi
            echo "RC7 KH only: attach existing Sanaei DB read-only to paused Node."
            echo "This recreates ONLY smite-node; pairing key, Gateway and FRP are retained."
            read -r -p "Type ATTACH-STAGED-KH-SANAEI to proceed: " recover_confirmation || return 2
            if [ "$recover_confirmation" != "ATTACH-STAGED-KH-SANAEI" ]; then
                echo "Cancelled; no changes."
                return 2
            fi
            staged_identity_sha="$(sha256sum "$staged_identity_file" | awk '{print $1}')" || return 2
            [[ "$staged_identity_sha" =~ ^[a-f0-9]{64}$ ]] || {
                echo "HOLD: Could not pin staged pairing identity before recovery." >&2
                return 2
            }
            staged_identity=1
        fi
        if ! grep -qx 'SMITE_NODE_PANEL_AUTH_MODE=paused' "$SMITE_NODE_DIR/.env" ||
           ! grep -qx 'SMITE_AGENT_AUTH_MODE=strict' "$SMITE_NODE_DIR/.env"; then
            echo "HOLD: Install/attach Sanaei before pairing while KH is paused + strict." >&2
            smite_install_pause
            return 2
        fi
        if ! runtime_env="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' smite-node 2>/dev/null)" ||
           [ "$(printf '%s\n' "$runtime_env" | grep '^SMITE_NODE_PANEL_AUTH_MODE=')" != 'SMITE_NODE_PANEL_AUTH_MODE=paused' ] ||
           [ "$(printf '%s\n' "$runtime_env" | grep '^SMITE_AGENT_AUTH_MODE=')" != 'SMITE_AGENT_AUTH_MODE=strict' ]; then
            echo "HOLD: KH runtime is not confirmed paused; Sanaei attachment cancelled." >&2
            smite_install_pause
            return 2
        fi
    fi

    if ! declare -F docker_3xui_install >/dev/null 2>&1; then
        echo "ERROR: U-OPTI 3x-UI Docker installer is not available."
        echo
        echo "The existing Docker 3x-UI module must be loaded."
        smite_install_pause
        return 2
    fi

    if [ "$signed_foreign" -ne 1 ]; then
        echo "Smite Foreign Node detected."
        echo
        echo "Launching the existing U-OPTI 3x-UI Multi-Instance installer..."
        echo
        echo "The normal U-OPTI rules remain active:"
        echo "  - Multi-instance allocation"
        echo "  - Nginx / SSL"
        echo "  - Hidden Web Base Path"
        echo "  - Panel Listen IP: 127.0.0.1"
        echo "  - Subscription / API / Metrics compatibility"
        echo
        sleep 2
        docker_3xui_install
        return $?
    fi

    if [ ! -f "$SMITE_NODE_COMPOSE" ] || [ -L "$SMITE_NODE_COMPOSE" ] ||
       [ ! -f "$SMITE_NODE_DIR/.env" ] || [ -L "$SMITE_NODE_DIR/.env" ]; then
        echo "HOLD: Clean-RC Foreign Node Compose and environment are required." >&2
        smite_install_pause
        return 2
    fi

    # The existing Sanaei installer relaunches U-OPTI when it completes.
    # On the next visit this same action discovers the registered instance and
    # installs the approved read-only database mount into the KH Node.
    if ! declare -F docker_3xui_load_instance >/dev/null 2>&1 ||
       ! docker_3xui_load_instance >/dev/null 2>&1; then
        echo "HOLD: U-OPTI multi-instance registry is unavailable." >&2
        smite_install_pause
        return 2
    fi
    mapfile -t instance_ids < <(docker_3xui_instance_registered_ids 2>/dev/null || true)
    for index in "${instance_ids[@]}"; do
        if docker_3xui_instance_load_state "$index" >/dev/null 2>&1 &&
           [ -s "$DOCKER_3XUI_INSTANCE_DIR/db/x-ui.db" ] &&
           [ ! -L "$DOCKER_3XUI_INSTANCE_DIR/db/x-ui.db" ]; then
            usable_ids+=("$index")
        fi
    done

    if [ "${#usable_ids[@]}" -eq 0 ]; then
        if [ "$staged_identity" -eq 1 ]; then
            echo "HOLD: Staged identity recovery requires an existing registered Sanaei database." >&2
            smite_install_pause
            return 2
        fi
        echo "No registered Sanaei database was found for this KH Node."
        echo "Launching the existing U-OPTI Sanaei installer."
        echo "After installation returns to U-OPTI, open this option again to"
        echo "connect its database to the read-only Smite inventory mount."
        smite_install_pause
        docker_3xui_install || return 2
        # Sanaei installation alone does not complete the Node DB attachment.
        return 3
    fi

    if [ "${#usable_ids[@]}" -eq 1 ]; then
        selected="${usable_ids[0]}"
    else
        echo "Registered Sanaei instances with an available database:"
        for index in "${!usable_ids[@]}"; do
            printf '%s) Instance %s\n' "$((index + 1))" "${usable_ids[$index]}"
        done
        read -r -p "Select the Sanaei instance for this KH Node: " choice
        [[ "$choice" =~ ^[0-9]+$ ]] &&
        [ "$choice" -ge 1 ] && [ "$choice" -le "${#usable_ids[@]}" ] || {
            echo "HOLD: Invalid Sanaei instance selection." >&2
            smite_install_pause
            return 2
        }
        selected="${usable_ids[$((choice - 1))]}"
    fi

    if ! docker_3xui_instance_load_state "$selected" >/dev/null 2>&1; then
        echo "HOLD: Selected Sanaei instance state is unavailable." >&2
        smite_install_pause
        return 2
    fi
    helper="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/smite-rc5-xhttp-sanaei-mount.py"
    [ -f "$helper" ] && [ ! -L "$helper" ] || {
        echo "HOLD: Sanaei mount verifier is not staged." >&2
        smite_install_pause
        return 2
    }
    backup="$SMITE_NODE_DIR/.env.pre-sanaei-mount-$(date +%Y%m%d%H%M%S).bak"
    cp -a "$SMITE_NODE_DIR/.env" "$backup" || {
        echo "HOLD: Could not retain the Node environment rollback copy." >&2
        smite_install_pause
        return 2
    }
    if ! python3 -B "$helper" \
        --instance-id "$selected" \
        --node-env "$SMITE_NODE_DIR/.env" \
        --node-compose "$SMITE_NODE_COMPOSE" \
        --confirm-foreign-node; then
        rm -f "$backup"
        smite_install_pause
        return 2
    fi

    if ! COMPOSE_PROJECT_NAME="$compose_project" python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" config >/dev/null ||
       ! COMPOSE_PROJECT_NAME="$compose_project" python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node ||
       ! smite_wait_healthy smite-node 90 ||
       ! docker exec smite-node python -c 'import os,sqlite3,stat,urllib.parse; p="/run/smite-sanaei-ro/x-ui.db"; d="/run/smite-sanaei-ro"; s=os.stat(p); assert stat.S_ISREG(s.st_mode); target=urllib.parse.quote(d,safe="/"); rows=[x.split() for x in open("/proc/self/mountinfo") if len(x.split()) > 5]; assert any(urllib.parse.unquote(x[4])==target and "ro" in x[5].split(",") for x in rows); c=sqlite3.connect("file:"+p+"?mode=ro",uri=True,timeout=1); c.execute("PRAGMA query_only=ON"); cols={r[1] for r in c.execute("PRAGMA table_info(inbounds)")}; assert {"port","listen","protocol","stream_settings","enable"} <= cols' ||
       { [ "$staged_identity" -eq 1 ] &&
         { [ "$(sha256sum "$staged_identity_file" | awk '{print $1}')" != "$staged_identity_sha" ] ||
           ! UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES python3 -B "$pairing_helper" \
             --verify-staged-foreign-sanaei; }; }; then
        echo "HOLD: Read-only Sanaei mount did not pass container verification; restoring Node configuration." >&2
        cp -a "$backup" "$SMITE_NODE_DIR/.env" || {
            echo "CRITICAL: Restore failed; backup retained at $backup" >&2
            smite_install_pause
            return 2
        }
        if ! COMPOSE_PROJECT_NAME="$compose_project" python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node ||
           ! smite_wait_healthy smite-node 90; then
            echo "CRITICAL: Node rollback health is unconfirmed; backup retained at $backup" >&2
            smite_install_pause
            return 2
        fi
        rm -f "$backup"
        smite_install_pause
        return 2
    fi
    rm -f "$backup"
    echo "KH_SANAEI_INVENTORY=PASS_READ_ONLY_SCHEMA"
    if [ "$staged_identity" -eq 1 ]; then
        echo "KH_STAGED_PAIRING_IDENTITY=UNCHANGED"
        echo "KH_GATEWAY_CONTROL=VERIFIED"
    fi
    echo "KH_NODE_RECREATE=PASS_HEALTHY"
    echo "KH_CLIENT_IDENTIFIERS=NOT_READ"
    smite_install_pause
    return 0
}



# Internal continuation for the existing selected Foreign option 2.
# Uses this same fresh transaction's temporary workspace and the existing
# hidden-TTY packet reader and Gateway scope parser. NOT yet dispatched by
# the public menu while signed trial runtime activation remains forbidden.
smite_install_unified_foreign_capture_packet() {
    local workspace="${1:-}" module_dir packet
    [ "${SMITE_SELECTED_FRESH:-0}" = 1 ] &&
    [ "${SMITE_INSTALL_PROFILE:-}" = clean-rc ] || {
        echo 'HOLD: Foreign input belongs only to the selected fresh install.' >&2
        return 2
    }
    [ -n "$workspace" ] && [ -d "$workspace" ] && [ ! -L "$workspace" ] &&
    [ "$(stat -c '%a:%u' "$workspace" 2>/dev/null)" = "700:$(id -u)" ] || {
        echo 'HOLD: A private installer-owned workspace is required.' >&2
        return 2
    }
    module_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || return 2
    [ -f "$module_dir/smite-unified-foreign-packet-intake.py" ] &&
    [ ! -L "$module_dir/smite-unified-foreign-packet-intake.py" ] &&
    [ -f "$module_dir/smite-unified-foreign-gateway-plan.py" ] &&
    [ ! -L "$module_dir/smite-unified-foreign-gateway-plan.py" ] || return 2
    mkdir -m 0700 -p -- "$workspace/foreign-fixture/foreign-staging" || return 2
    packet="$workspace/foreign-fixture/foreign-staging/foreign-install-packet.json"
    [ ! -e "$packet" ] && [ ! -L "$packet" ] || {
        echo 'HOLD: Previously staged Panel information cannot be replaced.' >&2
        return 2
    }
    python3 -B "$module_dir/smite-unified-foreign-packet-intake.py" \
        --capture-selected-foreign "$workspace" || return 2
    # The same immutable one-use packet supplies the core's three values.
    python3 -B "$module_dir/smite-unified-foreign-gateway-plan.py" \
        --packet-file "$packet" --precore-fields >/dev/null || return 2
    echo 'FOREIGN_ONE_CHOICE_INPUT=VERIFIED_PRIVATE_PANEL_PACKET'
    return 0
}

# Unified option-2 building block: reuse the existing Sanaei installer and
# exact read-only DB attachment, without sending the caller back to the menu.
# The complete Foreign enrollment/Gateway orchestration must explicitly call
# this from its signed, fresh-host-only transaction AFTER the core install and
# BEFORE any Foreign identity activation. This helper is not yet menu-wired.
smite_install_unified_foreign_sanaei() {
    local result=0

    if [ "${SMITE_SELECTED_FRESH:-0}" != 1 ] ||
       [ ! -f "$SMITE_STATE_FILE" ] ||
       [ -L "$SMITE_STATE_FILE" ] ||
       ! grep -qx 'SMITE_ROLE=foreign' "$SMITE_STATE_FILE" ||
       ! grep -qx 'SMITE_MANAGED_VERSION=2.0.0-rc.7' "$SMITE_STATE_FILE"; then
        echo 'HOLD: One-choice Sanaei continuation requires an owned fresh RC7 Foreign installation.' >&2
        return 2
    fi

    # First call: 0 means previously attached/verified; 3 means new Sanaei
    # installed and the *same* action must now attach its registered DB.
    # A status of 2 or anything unknown is never considered success.
    UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER=1 smite_install_sanaei_foreign || result=$?
    case "$result" in
        0) ;;
        3)
            echo 'UNIFIED_FOREIGN_SANAEI=INSTALLED_CONTINUE_READ_ONLY_ATTACHMENT'
            result=0
            UOPTI_SMITE_UNIFIED_RETURN_TO_CALLER=1 smite_install_sanaei_foreign || result=$?
            [ "$result" -eq 0 ] || {
                echo 'HOLD: Sanaei installed but verified read-only attachment is incomplete. Retain state.' >&2
                return 2
            }
            ;;
        *)
            echo 'HOLD: Sanaei installation/attachment did not succeed. Retain Node state.' >&2
            return 2
            ;;
    esac

    echo 'UNIFIED_FOREIGN_SANAEI=PASS_ATTACHED_READ_ONLY'
    return 0
}

# Option 2 unified-install composition boundary (trial branch ONLY).
# Reuses the existing signed Pairing RELEASE gate, Sanaei and Gateway.
# NOT connected to the public menu: the immutable trial image manifest
# explicitly says host_activation_allowed=false, so this guard must HOLD
# before either Sanaei or Gateway can change the Foreign host.
smite_install_unified_signed_pair_review() {
    local module_dir verifier manifest trust_root actual_cosign
    module_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || return 2
    verifier="$module_dir/smite-unified-trial-pair-admission.py"
    manifest="$module_dir/smite-unified-trial-registry-pair.json"
    trust_root="$module_dir/smite-rc7-sigstore-trusted-root.json"
    for item in "$verifier" "$manifest" "$trust_root"; do
        [ -f "$item" ] && [ ! -L "$item" ] || {
            echo 'HOLD: Unified signed trial verification inputs missing.' >&2
            return 2
        }
    done
    command -v cosign >/dev/null 2>&1 || {
        echo 'HOLD: Unified trial image signature verifier missing.' >&2
        return 2
    }
    actual_cosign="$(command -v cosign)" || return 2
    [ -f "$actual_cosign" ] && [ ! -L "$actual_cosign" ] || return 2
    [ "$(sha256sum "$actual_cosign" | awk '{print $1}')" = \
      'c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74' ] || {
        echo 'HOLD: Unified trial requires the exact reviewed Cosign v3.0.6 binary.' >&2
        return 2
    }
    # Reuse the EXISTING signed Pairing release admission. The old code
    # only proved genuine TRIAL signatures and then allowed Sanaei/Gateway
    # changes, even though the immutable trial manifest says activation is
    # forbidden. The single Pairing gate verifies both signatures AND the
    # explicit release decision before any Foreign host mutation.
    local pairing="$module_dir/smite-node-pairing.py"
    [ -f "$pairing" ] && [ ! -L "$pairing" ] || return 2
    python3 -B - "$pairing" <<'PY_UNIFIED_FOREIGN_RELEASE' || return 2
import importlib.util
from pathlib import Path
import sys
path=Path(sys.argv[1])
if path.is_symlink() or not path.is_file():
    raise SystemExit(2)
try:
    spec=importlib.util.spec_from_file_location(
        "uopti_selected_existing_pairing_release",path)
    if spec is None or spec.loader is None:
        raise ValueError("Missing approved Pairing controller")
    pairing=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=pairing
    spec.loader.exec_module(pairing)
    pairing._require_unified_foreign_release()
except Exception:
    # No raw manifest, secrets, certificate evidence or user token in logs.
    print("HOLD: Unified Smite signed pair not approved for host activation",
          file=sys.stderr)
    raise SystemExit(2)
PY_UNIFIED_FOREIGN_RELEASE
    echo 'UNIFIED_FOREIGN_IMAGE_PAIR=SIGNED_RELEASE_APPROVED'
}

smite_install_unified_foreign_node_image_review() {
    local image running_id pinned_id
    # Exact immutable reference AND effective running image ID must match.
    image='ghcr.io/aghajani82/smite-node@sha256:587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483'
    if [ "$(docker inspect -f '{{.Config.Image}}' smite-node 2>/dev/null)" != "$image" ]; then
        echo 'HOLD: Foreign Node does not use the exact signed trial digest.' >&2
        return 2
    fi
    running_id="$(docker inspect -f '{{.Image}}' smite-node 2>/dev/null)" || return 2
    pinned_id="$(docker image inspect -f '{{.Id}}' "$image" 2>/dev/null)" || return 2
    if [[ ! "$running_id" =~ ^sha256:[a-f0-9]{64}$ ]] || [ "$running_id" != "$pinned_id" ]; then
        echo 'HOLD: Effective running Node image ID differs from the signed digest.' >&2
        return 2
    fi
    echo 'UNIFIED_FOREIGN_NODE_IMAGE=EXACT_SIGNED_DIGEST_AND_RUNTIME_ID'
}

# Internal phase composition for future single-choice Foreign option 2.
# Must never be called with an older RC7 image, a partially recovered node,
# or from an existing host. Packet is a private 0600 file previously retained
# from the Panel-issued install instructions, never passed as a secret argv.
# No installed/connected success message is emitted here.
smite_install_unified_foreign_after_core() {
    local packet="$1" helper_dir admitted="" recorded=""
    if [ "${SMITE_SELECTED_FRESH:-0}" != 1 ] ||
       [ "${SMITE_INSTALL_PROFILE:-}" != clean-rc ] ||
       [ ! -f "$SMITE_STATE_FILE" ] || [ -L "$SMITE_STATE_FILE" ] ||
       ! grep -qx 'SMITE_ROLE=foreign' "$SMITE_STATE_FILE" ||
       ! grep -qx 'SMITE_MANAGED_VERSION=2.0.0-rc.7' "$SMITE_STATE_FILE"; then
        echo 'HOLD: Unified Foreign post-core requires a fresh reviewed RC7 transaction.' >&2
        return 2
    fi
    [ -n "$packet" ] || {
        echo 'HOLD: Private, Panel-issued Foreign installation packet required.' >&2
        return 2
    }
    helper_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || return 2
    [ -f "$helper_dir/smite-unified-foreign-gateway-plan.py" ] &&
    [ ! -L "$helper_dir/smite-unified-foreign-gateway-plan.py" ] || return 2
    for required in smite_foreign_gateway_configure \
        smite_foreign_gateway_require_rc_paused smite_foreign_gateway_rc7_compose; do
        declare -F "$required" >/dev/null 2>&1 || {
            echo 'HOLD: Existing signed Foreign Gateway or Compose helper unavailable.' >&2
            return 2
        }
    done

    # All security review occurs before running Sanaei or touching Nginx.
    # The same pre-core validator must also check the Panel grant TTL here:
    # Sanaei setup can take time, and a stale/unconsumed one-use code must
    # not trigger later Gateway changes that cannot be enrolled.
    smite_install_unified_signed_pair_review || return 2
    python3 -B "$helper_dir/smite-unified-foreign-gateway-plan.py" \
        --packet-file "$packet" --precore-fields >/dev/null || {
        echo 'HOLD: Foreign Panel grant expired or changed before post-core setup. Request a fresh code for the SAME reserved Node; do not reinstall.' >&2
        return 2
    }
    smite_install_unified_foreign_node_image_review || return 2
    smite_foreign_gateway_require_rc_paused || return 2
    smite_foreign_gateway_rc7_compose config --quiet || return 2
    admitted="$(python3 -B "$helper_dir/smite-unified-foreign-gateway-plan.py" \
        --packet-file "$packet" \
        --state-file "$SMITE_STATE_FILE" \
        --gateway-state-file "$SMITE_STATE_DIR/foreign-gateway.env")" || {
        echo 'HOLD: Foreign installation packet is not bound to this fresh Node.' >&2
        return 2
    }
    [[ "$admitted" =~ ^/smite-node/[0-9a-f]{32}$ ]] || return 2

    # The existing option-4 Sanaei installer returns to this invocation and
    # attaches its verified read-only database; no standalone menu reload.
    smite_install_unified_foreign_sanaei || {
        echo 'HOLD: Sanaei and Node inventory were not both verified.' >&2
        return 2
    }
    UOPTI_SMITE_UNIFIED_FOREIGN_PACKET_FILE="$packet"       smite_foreign_gateway_configure || {
        echo 'HOLD: Foreign SSL/443 Gateway incomplete; retain reviewed state.' >&2
        return 2
    }
    # Do not declare Gateway readiness unless the persisted control path
    # still matches the exact Panel issue; this never exposes the raw code.
    recorded="$(smite_foreign_gateway_state_value         SMITE_FOREIGN_CONTROL_PATH "$SMITE_STATE_DIR/foreign-gateway.env")" || return 2
    [ "$recorded" = "$admitted" ] || {
        echo 'HOLD: Foreign Gateway path differs from the Panel-issued grant.' >&2
        return 2
    }
    # The existing Gateway may recreate the paused Node to apply its
    # control address. Never advance from this phase based on an old
    # pre-Gateway image/Compose check or a successful Nginx reload alone.
    # Reuse the SAME signed-image, paused and Compose checks already
    # performed before installing Sanaei/Gateway; no extra installer.
    smite_install_unified_foreign_node_image_review || {
        echo 'HOLD: Foreign Node image/runtime changed during Gateway setup.' >&2
        return 2
    }
    smite_foreign_gateway_require_rc_paused || {
        echo 'HOLD: Foreign Node is no longer paused/strict after Gateway setup.' >&2
        return 2
    }
    smite_foreign_gateway_rc7_compose config --quiet || {
        echo 'HOLD: Foreign Node Compose ownership changed during Gateway setup.' >&2
        return 2
    }
    echo 'UNIFIED_FOREIGN_SANAEI_GATEWAY=PREPARED_FOR_SIGNED_ENROLLMENT'
    echo 'UNIFIED_FOREIGN_CONNECTED=NOT_YET_VERIFIED'
    return 0
}

smite_install_field_trial_patch_compose_image() {
    local compose_file="$1" old_image="$2" new_image="$3"
    python3 - "$compose_file" "$old_image" "$new_image" <<'PY_RC_UPGRADE_COMPOSE'
from pathlib import Path
import os, stat, sys, tempfile
path=Path(sys.argv[1]); old=sys.argv[2]; new=sys.argv[3]
if path.is_symlink() or not path.is_file():
    raise SystemExit("HOLD: Unsafe Smite Compose path")
st=path.stat(); text=path.read_text()
needle=f"    image: {old}"; replacement=f"    image: {new}"
if text.count(needle) != 1:
    raise SystemExit("HOLD: Existing Compose is not the exact admitted previous candidate")
fd,tmp=tempfile.mkstemp(prefix=".uopti-rc-upgrade-",dir=path.parent)
try:
    with os.fdopen(fd,"w") as out:
        out.write(text.replace(needle,replacement,1)); out.flush(); os.fsync(out.fileno())
    os.chmod(tmp,stat.S_IMODE(st.st_mode)); os.replace(tmp,path)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
PY_RC_UPGRADE_COMPOSE
}

smite_install_upgrade_signed_field_trial() {
    local answer role mode version domain panel_current node_current
    local backup panel_bak node_bak state_bak db_bak db
    local SMITE_INSTALL_PROFILE=clean-rc
    local SMITE_RC_SIGNED_REGISTRY=1
    local SMITE_FIELD_TRIAL_APPROVED=YES

    clear
    echo "======================================"
    echo "   Upgrade Signed Smite Field Trial"
    echo "======================================"
    echo
    echo "Disposable Field Trial only."
    echo "Admitted transition: $SMITE_FIELD_TRIAL_PREVIOUS_VERSION -> $SMITE_FIELD_TRIAL_VERSION"
    echo "Admin/2FA data, Gateway and Node configuration are preserved."
    echo

    [ "$(id -u)" -eq 0 ] || { echo "HOLD: Root required."; smite_install_pause; return; }
    [ -f "$SMITE_STATE_FILE" ] && [ ! -L "$SMITE_STATE_FILE" ] ||
        { echo "HOLD: Managed state missing/unsafe."; smite_install_pause; return; }
    [ -f "$SMITE_PANEL_COMPOSE" ] && [ ! -L "$SMITE_PANEL_COMPOSE" ] &&
    [ -f "$SMITE_NODE_COMPOSE" ] && [ ! -L "$SMITE_NODE_COMPOSE" ] ||
        { echo "HOLD: Managed Compose files missing/unsafe."; smite_install_pause; return; }

    role="$(grep -m1 '^SMITE_ROLE=' "$SMITE_STATE_FILE" | cut -d= -f2-)"
    mode="$(grep -m1 '^SMITE_CONNECTION_MODE=' "$SMITE_STATE_FILE" | cut -d= -f2-)"
    version="$(grep -m1 '^SMITE_MANAGED_VERSION=' "$SMITE_STATE_FILE" | cut -d= -f2-)"
    domain="$(grep -m1 '^SMITE_PANEL_DOMAIN=' "$SMITE_STATE_FILE" | cut -d= -f2-)"
    [ "$role" = panel-iran ] && [ "$mode" = standard ] &&
    [ "$version" = "$SMITE_FIELD_TRIAL_PREVIOUS_VERSION" ] && [ -n "$domain" ] ||
        { echo "HOLD: Install is not the exact rc.0 Panel+Iran Standard baseline."; smite_install_pause; return; }

    panel_current="$(docker inspect -f '{{.Config.Image}}' smite-panel 2>/dev/null || true)"
    node_current="$(docker inspect -f '{{.Config.Image}}' smite-node 2>/dev/null || true)"
    [ "$panel_current" = "$SMITE_FIELD_TRIAL_PREVIOUS_PANEL_IMAGE" ] &&
    [ "$node_current" = "$SMITE_FIELD_TRIAL_PREVIOUS_NODE_IMAGE" ] ||
        { echo "HOLD: Running images are not the exact rc.0 immutable pair."; smite_install_pause; return; }
    smite_wait_healthy smite-panel 15 && smite_wait_healthy smite-node 15 ||
        { echo "HOLD: Existing rc.0 containers are not healthy."; smite_install_pause; return; }

    db="$SMITE_PANEL_DIR/panel/data/smite.db"
    [ -f "$db" ] && [ ! -L "$db" ] && command -v sqlite3 >/dev/null 2>&1 ||
        { echo "HOLD: Safe Panel DB snapshot is unavailable."; smite_install_pause; return; }

    echo "Re-verifying rc.1 manifest and both immutable signatures..."
    smite_install_field_trial_verify_candidate ||
        { echo "HOLD: rc.1 candidate verification failed."; smite_install_pause; return; }

    echo "Target Panel: $SMITE_PANEL_IMAGE"
    echo "Target Node : $SMITE_NODE_IMAGE"
    read -rp "Upgrade this disposable IR Field Trial to rc.1? [y/N]: " answer
    case "$answer" in y|Y|yes|YES) ;; *) echo "Cancelled; no changes."; smite_install_pause; return ;; esac

    smite_install_clean_rc_load_images panel-iran ||
        { echo "HOLD: rc.1 pull/verification failed before changes."; smite_install_pause; return; }

    backup="$(mktemp -d /var/tmp/uopti-smite-rc-upgrade.XXXXXX)" ||
        { echo "HOLD: Rollback workspace creation failed."; smite_install_pause; return; }
    chmod 0700 "$backup"
    panel_bak="$backup/panel.yml"; node_bak="$backup/node.yml"
    state_bak="$backup/state.env"; db_bak="$backup/smite.db"
    cp -a "$SMITE_PANEL_COMPOSE" "$panel_bak" &&
    cp -a "$SMITE_NODE_COMPOSE" "$node_bak" &&
    cp -a "$SMITE_STATE_FILE" "$state_bak" &&
    sqlite3 "$db" ".backup '$db_bak'" ||
        { echo "HOLD: Complete rollback snapshot failed."; rm -rf "$backup"; smite_install_pause; return; }

    if smite_install_field_trial_patch_compose_image "$SMITE_PANEL_COMPOSE" "$SMITE_FIELD_TRIAL_PREVIOUS_PANEL_IMAGE" "$SMITE_PANEL_IMAGE" &&
       smite_install_field_trial_patch_compose_image "$SMITE_NODE_COMPOSE" "$SMITE_FIELD_TRIAL_PREVIOUS_NODE_IMAGE" "$SMITE_NODE_IMAGE" &&
       python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_PANEL_COMPOSE" config >/dev/null &&
       python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" config >/dev/null &&
       python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_PANEL_COMPOSE" up -d --no-build --force-recreate smite-panel &&
       smite_wait_healthy smite-panel 90 &&
       python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node &&
       smite_wait_healthy smite-node 90 &&
       [ "$(docker inspect -f '{{.Config.Image}}' smite-panel 2>/dev/null)" = "$SMITE_PANEL_IMAGE" ] &&
       [ "$(docker inspect -f '{{.Config.Image}}' smite-node 2>/dev/null)" = "$SMITE_NODE_IMAGE" ] &&
       curl -fsS --max-time 10 http://127.0.0.1:8000/api/status >/dev/null &&
       curl -fsS --max-time 10 http://127.0.0.1:8888/healthz >/dev/null &&
       curl -fsS --max-time 15 "https://$domain/api/status" >/dev/null; then
        sed -i "s/^SMITE_MANAGED_VERSION=$SMITE_FIELD_TRIAL_PREVIOUS_VERSION$/SMITE_MANAGED_VERSION=$SMITE_FIELD_TRIAL_VERSION/" "$SMITE_STATE_FILE"
        if grep -Fxq "SMITE_MANAGED_VERSION=$SMITE_FIELD_TRIAL_VERSION" "$SMITE_STATE_FILE"; then
            rm -rf "$backup"
            echo
            echo "SIGNED_FIELD_TRIAL_UPGRADE=PASS"
            echo "ADMIN_2FA_DATA=PRESERVED"
            echo "HTTPS_443_GATEWAY=PRESERVED"
            echo "NODE_RUNTIME=PAUSED_STRICT_PENDING_PAIRING"
            echo "PRODUCTION_ACTIVATION=NO"
            smite_install_pause
            return
        fi
    fi

    echo "ROLLBACK: restoring rc.0 Compose and Panel DB..."
    python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_PANEL_COMPOSE" stop smite-panel >/dev/null 2>&1 || true
    cp -a "$panel_bak" "$SMITE_PANEL_COMPOSE"
    cp -a "$node_bak" "$SMITE_NODE_COMPOSE"
    cp -a "$state_bak" "$SMITE_STATE_FILE"
    cp -a "$db_bak" "$db"
    rm -f "$db-wal" "$db-shm"
    python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_PANEL_COMPOSE" up -d --no-build --force-recreate smite-panel >/dev/null 2>&1 || true
    python3 -B "$(dirname "${BASH_SOURCE[0]}")/smite-compose-safe.py" "$SMITE_NODE_COMPOSE" up -d --no-build --force-recreate smite-node >/dev/null 2>&1 || true
    smite_wait_healthy smite-panel 90 >/dev/null 2>&1 || true
    smite_wait_healthy smite-node 90 >/dev/null 2>&1 || true
    rm -rf "$backup"
    echo "HOLD: rc.1 upgrade failed; rc.0 rollback was attempted."
    smite_install_pause
}

# Selected fresh-host entry. Subshell scope prevents candidate settings from leaking
# into historical recovery/upgrade operations in this same management session.
smite_install_selected_paths() {
    [ "$SMITE_PANEL_DIR" = /opt/smite ] &&
    [ "$SMITE_NODE_DIR" = /opt/smite-node ] &&
    [ "$SMITE_OVERLAY_DIR" = /opt/u-opti-smite ] &&
    [ "$SMITE_STATE_FILE" = /etc/u-opti/smite/state.env ] &&
    [ "$SMITE_PANEL_COMPOSE" = /opt/smite/docker-compose.yml ] &&
    [ "$SMITE_NODE_COMPOSE" = /opt/smite-node/docker-compose.yml ]
}

# Check that the chosen signed RC7 Panel/Node source matches the ORIGINAL
# fresh-install rollback journal before Docker or any install transaction.
# The separately signed unified trial is NOT an admitted release.
smite_install_selected_pair_journal_review() {
    local module_dir="$1"
    python3 -B - "$module_dir/smite-rc6-install-journal.py" \
        "$module_dir/smite-rc7-registry-pair.json" \
        "$module_dir/smite-unified-trial-registry-pair.json" \
        "$SMITE_FIELD_TRIAL_SOURCE_SHA" "$SMITE_FIELD_TRIAL_VERSION" \
        "$SMITE_FIELD_TRIAL_PUBLISH_REF" "$SMITE_FIELD_TRIAL_MANIFEST_SHA256" <<'PY_SOURCE_JOURNAL'
import hashlib, importlib.util, json, pathlib, re, sys

def hold():
    raise ValueError("signed selected source/rollback journal mismatch")

def unique(items):
    result={}
    for key,value in items:
        if key in result: hold()
        result[key]=value
    return result

try:
    journal, official, trial = map(pathlib.Path,sys.argv[1:4])
    source, version, ref, pin = sys.argv[4:8]
    for path in (journal,official,trial):
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 150000:
            hold()
    raw_official=official.read_bytes()
    raw_trial=trial.read_bytes()
    if (not re.fullmatch("[a-f0-9]{40}",source)
            or not re.fullmatch("[a-f0-9]{64}",pin)
            or hashlib.sha256(raw_official).hexdigest()!=pin
            or hashlib.sha256(raw_trial).hexdigest()!=
                "e13f0708b1de5eef112b955f4b6efe4e1efa5520d404458646bb6e1e76c96608"):
        hold()
    expected=json.loads(raw_official,object_pairs_hook=unique)
    separate=json.loads(raw_trial,object_pairs_hook=unique)
    spec=importlib.util.spec_from_file_location(
        "uopti_rc7_existing_install_journal_review",journal)
    if spec is None or spec.loader is None: hold()
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if (source!="9a1270b31e8d44f13d09b71ab6b9798410b09c12"
            or version!="2.0.0-rc.7" or ref!="refs/tags/v2.0.0-rc.7"
            or expected.get("source_repo")!="aghajani82/Smite"
            or expected.get("kind")!="smite_signed_registry_pair_candidate"
            or expected.get("source_commit")!=source
            or expected.get("version")!=version or expected.get("publish_ref")!=ref
            or expected.get("activation_allowed") is not False
            or expected.get("release_approved") is not False
            or not isinstance(expected.get("images"),dict)
            or set(expected["images"])!={"panel","node"}
            or mod.SOURCE!=source or mod.VERSION!=version
            or mod.IMAGES!={"smite-panel":expected["images"]["panel"],
                            "smite-node":expected["images"]["node"]}
            or mod.CANDIDATES.get(source)!=(version,mod.IMAGES)):
        hold()
    if (separate.get("source_commit")!="b865be93e22153c60769f6329e6e55e781494ded"
            or separate.get("kind")!="smite_unified_install_signed_trial_candidate"
            or separate.get("publish_ref")!="refs/heads/trial/unified-smite-install"
            or separate.get("release_approved") is not False
            or separate.get("activation_allowed") is not False
            or not isinstance(separate.get("images"),dict)
            or set(separate["images"])!={"panel","node"}
            or separate["images"]==expected["images"]
            or separate["source_commit"] in mod.CANDIDATES):
        hold()
except (OSError,ValueError,TypeError,AttributeError,KeyError,ImportError):
    print("HOLD: Signed Smite source and existing rollback journal disagree",
          file=sys.stderr)
    sys.exit(2)
print("SELECTED_RC7_PAIR_JOURNAL=EXACT_MATCH")
print("UNIFIED_TRIAL_JOURNAL=SEPARATE_NOT_ADMITTED")
PY_SOURCE_JOURNAL
}

# Selected RC7 needs the exact official v3.0.6 Cosign asset before any
# host transaction. A blocked github.com release URL must never hang silently:
# both official retrieval paths are bounded and every candidate is SHA-pinned.
smite_install_rc7_verified_cosign() {
    local target="$1" expected_sha="$2" source url actual
    local official="https://github.com/sigstore/cosign/releases/download/v3.0.6/cosign-linux-amd64"
    # Immutable official release-asset ID from the reviewed CI bootstrap.
    local api="https://api.github.com/repos/sigstore/cosign/releases/assets/390331694"
    for source in release api; do
        if [ "$source" = release ]; then
            url="$official"
            echo 'RC7_COSIGN_DOWNLOAD=OFFICIAL_RELEASE (visible, bounded)'
        else
            url="$api"
            echo 'RC7_COSIGN_DOWNLOAD=OFFICIAL_GITHUB_API_FALLBACK (visible, bounded)'
        fi
        local -a headers=()
        if [ "$source" = api ]; then
            headers=(-H 'Accept: application/octet-stream')
        fi
        if curl -fL --progress-bar --proto '=https' --proto-redir '=https' \
                --connect-timeout 10 --max-time 180 \
                --retry 2 --retry-delay 2 --retry-max-time 240 \
                --speed-time 30 --speed-limit 1024 \
                "${headers[@]}" "$url" -o "$target"; then
            actual="$(sha256sum "$target" | awk '{print $1}')" || return 2
            if [ "$actual" = "$expected_sha" ]; then
                echo 'RC7_COSIGN_SHA256=VERIFIED'
                return 0
            fi
            echo "HOLD: RC7 Cosign $source download did not match the pinned SHA-256." >&2
        else
            echo "HOLD: RC7 Cosign $source download failed or timed out." >&2
        fi
        # Never reuse bytes from a failed transport/hash check in fallback.
        rm -f -- "$target" || return 2
    done
    echo 'HOLD_RC7_COSIGN_VERIFIER_UNAVAILABLE: both official URLs failed or were untrusted. No Smite install transaction started.' >&2
    return 2
}

smite_install_selected_fresh() (
    local role="$1" module_dir workdir containers path confirm
    case "$role" in panel-iran|foreign) ;; *) return 2 ;; esac
    # Preserve the explicitly requested historical offline entry unchanged.
    if [ "$SMITE_INSTALL_PROFILE" = clean-rc ]; then
        if [ "$role" = panel-iran ]; then smite_install_panel_iran; else smite_install_foreign_node; fi
        return
    fi
    # The current public Foreign choice still selects the *old* official
    # RC7 image. The signed unified pair is READ-ONLY and has
    # activation_allowed=false: starting a new Node here would leave a
    # stranded, incomplete installation with an expiring Panel grant.
    # Fail BEFORE Docker, package changes, prompting, journaling or writing
    # any host installation files. Keep this explicit until the existing
    # signed runtime/rollback and complete one-choice transaction are
    # released and tested. Iran option 1 remains unaffected.
    if [ "$role" = foreign ]; then
        echo 'HOLD: Signed unified Foreign runtime activation is not yet released; no installation started.'
        echo 'FOREIGN_ONE_CHOICE_INSTALL=HOLD_BEFORE_HOST_CHANGES'
        echo 'FOREIGN_CONNECTED=NOT_PROVEN'
        return 2
    fi
    smite_install_selected_paths || { echo 'HOLD: Selected recovery requires standard managed paths'; return 2; }
    [ "$EUID" = 0 ] || { echo 'HOLD: root required'; return 2; }
    [ "$(uname -m)" = x86_64 ] || { echo 'HOLD: selected RC7 images qualify amd64 only'; return 2; }
    unset DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS_VERIFY DOCKER_CERT_PATH DOCKER_CONFIG COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME COMPOSE_ENV_FILES
    # The guarded Compose helper chooses the local socket itself and rejects
    # all ambient Docker overrides. Read-only inventory below pins it too.
    # Even an incomplete installation is preserved. This is not an upgrader.
    for path in "$SMITE_STATE_FILE" "$SMITE_PANEL_DIR" "$SMITE_NODE_DIR" "$SMITE_OVERLAY_DIR"; do
        if [ -e "$path" ] || [ -L "$path" ]; then
            echo 'HOLD: existing/partial Smite state; use reviewed recovery, never reinstall'
            return 2
        fi
    done
    echo 'Selected Smite 2.0.0-rc.7: fresh-host qualification candidate, not yet stable.'
    echo 'Existing installations and live tunnels are not migrated by this entry.'
    read -rp 'Prepare verified RC7 fresh installation? [y/N]: ' confirm || return 2
    case "$confirm" in y|Y|yes|YES) ;; *) return 2 ;; esac
    local SMITE_INSTALL_PROFILE=clean-rc SMITE_SELECTED_FRESH=1
    local SMITE_INSTALL_FAILURE_CODE=2
    local SMITE_RC_SIGNED_REGISTRY=1 SMITE_FIELD_TRIAL_APPROVED=YES
    local SMITE_FIELD_TRIAL_SOURCE_SHA=9a1270b31e8d44f13d09b71ab6b9798410b09c12
    local SMITE_FIELD_TRIAL_PUBLISH_REF=refs/tags/v2.0.0-rc.7
    local SMITE_FIELD_TRIAL_VERSION=2.0.0-rc.7
    local SMITE_FIELD_TRIAL_MANIFEST_SHA256=58bebfc605a5c1a64cf02ce38e6397dbcdae5f1c3289a01952f361b6a8aa660e
    local SMITE_FIELD_TRIAL_COSIGN_SHA256=c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74
    # Templates and CLI are from the very same immutable application source.
    # Template image names stay upstream-shaped until strict digest replacement.
    local SMITE_UPSTREAM_RAW="https://raw.githubusercontent.com/aghajani82/Smite/$SMITE_FIELD_TRIAL_SOURCE_SHA"
    local SMITE_UPSTREAM_REF="$SMITE_FIELD_TRIAL_SOURCE_SHA"
    local SMITE_UPSTREAM_VERSION=2.0.0-rc.7
    local SMITE_PANEL_IMAGE SMITE_NODE_IMAGE
    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 2
    smite_install_selected_pair_journal_review "$module_dir" || return 2
    smite_install_require_tools || return 2
    smite_install_ensure_docker || return 2
    containers="$(docker --host unix:///var/run/docker.sock container ls -a --format '{{.Names}}')" || {
        echo 'HOLD: local Docker state unavailable'; return 2;
    }
    if printf '%s\n' "$containers" | grep -Eq '^smite-(panel|node)$'; then
        echo 'HOLD: existing Smite container; fresh installation refused'; return 2
    fi
    docker() { command docker --host unix:///var/run/docker.sock "$@"; }
    umask 077
    workdir="$(mktemp -d)" || return 2
    trap 'rm -rf -- "$workdir"' EXIT
    # Private verifier only. No install proceeds before exact digest validation.
    smite_install_rc7_verified_cosign "$workdir/cosign" "$SMITE_FIELD_TRIAL_COSIGN_SHA256" || return 2
    chmod 0700 "$workdir/cosign" || return 2
    # Reviewed Sigstore public-good TrustedRoot snapshot, pinned in this U-OPTI
    # release. The normal TUF CDN returns HTTP 403 on some Iranian networks.
    # This is an explicit, SHA-pinned trust anchor, NOT online TUF validation.
    local SMITE_SELECTED_TRUSTED_ROOT="$workdir/trusted_root.json"
    echo 'RC7: downloading reviewed Sigstore trusted-root snapshot...'
    curl -fsSL --proto '=https' --proto-redir '=https' \
        --connect-timeout 10 --max-time 60 --retry 2 \
        "https://raw.githubusercontent.com/sigstore/root-signing/c9aa2600c1492365922f1b3f351a208aa17d0e64/targets/trusted_root.json" \
        -o "$SMITE_SELECTED_TRUSTED_ROOT" || {
            echo 'HOLD: reviewed Sigstore trusted-root download failed' >&2
            return 2
        }
    [ "$(sha256sum "$SMITE_SELECTED_TRUSTED_ROOT" | awk '{print $1}')" = "6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66" ] || {
        echo 'HOLD: reviewed Sigstore trusted-root SHA256 mismatch' >&2
        return 2
    }
    echo 'RC7_TRUSTED_ROOT=PINNED_SHA256_VERIFIED'
    local PATH="$workdir:$PATH"
    smite_install_clean_rc_preflight "$role" standard || return 2
    if [ "$role" = panel-iran ]; then
        [ -f "$module_dir/smite-clean-rc-preflight.sh" ] && [ ! -L "$module_dir/smite-clean-rc-preflight.sh" ] || return 2
        source "$module_dir/smite-clean-rc-preflight.sh" || return 2
        if ! smite_clean_rc_nginx_paths_ready; then
            smite_clean_rc_prepare_gateway_packages || return 2
        fi
    fi
    local installer_pid="$BASHPID" transaction
    transaction="$(python3 -B "$module_dir/smite-rc6-install-journal.py" begin --role "$role" --installer-pid "$installer_pid")" || return 2
    [[ "$transaction" =~ ^uopti_rc6_[0-9a-f]{32}$ ]] || return 2
    # Inherited lock stays held by installer children if the menu shell dies.
    local rc6_lock
    exec {rc6_lock}> /var/lib/u-opti/rc6-install-journal/operation.lock || return 2
    flock -n "$rc6_lock" || return 2
    export COMPOSE_PROJECT_NAME="$transaction"
    if [ "$role" = panel-iran ]; then
        smite_install_panel_iran || return 2
    else
        smite_install_foreign_node || return 2
    fi
    python3 -B "$module_dir/smite-rc6-install-journal.py" commit || return 2
    if [ "$role" = panel-iran ]; then
        # Core signed enrollment and administrator credentials are the
        # installation transaction; static appearance cannot leave them
        # half-applied. Apply UI only AFTER both are verified.
        smite_install_finish_local_ir || return 2
    else
        # The official RC7 core is not the independently signed unified
        # trial pair. Do not silently run trial post-core operations on it,
        # or return success/Connected before Sanaei, SSL/443, identity,
        # replay and bidirectional signed checks are integrated and proven.
        echo 'HOLD: Foreign Node core is paused. One-choice Sanaei, Gateway and signed enrollment are not yet wired to the admitted runtime.'
        echo 'FOREIGN_ONE_CHOICE_INSTALL=INCOMPLETE_RETAIN_CORE'
        echo 'FOREIGN_CONNECTED=NOT_PROVEN'
        return 2
    fi
)

# Core transaction is committed before enrollment: fresh-install rollback must
# never delete a paired identity. Each enrollment stage keeps its own recovery.
smite_install_finish_local_ir() {
    local module_dir domain
    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 2
    local SMITE_GATEWAY_INSTALL_FLOW=1
    declare -F smite_gateway_configure_panel >/dev/null || {
        echo 'HOLD: HTTPS gateway module is unavailable'; return 2;
    }
    echo 'Preparing Panel HTTPS/443 and secure Iran Node enrollment...'
    smite_gateway_configure_panel || return 2
    domain="$(smite_gateway_panel_domain)" || return 2
    smite_gateway_verify_443 "$domain" || return 2
    UOPTI_SMITE_PAIRING_FIELD_TRIAL=YES python3 -B \
        "$module_dir/smite-node-pairing.py" --complete-local-ir-install || {
        echo 'HOLD: local Iran enrollment incomplete; retain installation and identity. Do not reinstall.'
        return 2
    }
    echo 'Iran Node verified active. Create the Panel administrator account:'
    smite_install_create_admin || return 2
    # Cosmetic UI is independent of signed Node identity and Gateway.
    # Its own existing private backup/rollback remains available at
    # menu 8/9; a static update issue cannot undo verified pairing.
    if smite_install_ui_action apply; then
        echo 'IR_PANEL_STATIC_UI=APPLIED'
    else
        echo 'IR_PANEL_STATIC_UI=REVIEW_OPTION_8'
        echo 'NOTICE: Panel and Iran Node are connected. Optional appearance update remains pending; do not reinstall.'
    fi
    echo 'PANEL_AND_IR_INSTALL=COMPLETE'
    echo "Panel URL: https://$domain"
    echo 'Sign in: Iran Nodes contains the authenticated local Node.'
    smite_install_pause
    return 0
}

smite_install_selected_rollback() (
    unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS_VERIFY DOCKER_CERT_PATH
    local module_dir answer
    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 2
    python3 -B "$module_dir/smite-rc6-install-journal.py" status || return 2
    echo 'Only an interrupted fresh RC6/RC7 install can be rolled back.'
    echo 'Completed installs, pairing, grants, routes and foreign containers are refused.'
    echo 'Files, containers and volumes are retained. Packages/images are not uninstalled.'
    read -rp 'Type ROLLBACK-RC6 to quarantine the interrupted install: ' answer || return 2
    [ "$answer" = ROLLBACK-RC6 ] || return 2
    python3 -B "$module_dir/smite-rc6-install-journal.py" rollback --confirm "$answer" || return 2
    echo 'Rollback complete. Retry Install Components 1 (IR) or 2 (KH).'
    smite_install_pause
)

# The reviewed static UI is bundled with U-OPTI; never fetch mutable UI assets.
smite_install_ui_action() {
    local action="$1" module_dir
    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 2
    [ -f "$module_dir/smite-panel-ui.py" ] && [ ! -L "$module_dir/smite-panel-ui.py" ] || {
        echo 'HOLD: update U-OPTI first; UI helper is missing'; return 2;
    }
    python3 -B "$module_dir/smite-panel-ui.py" "$action"
}

smite_install_ui_menu_action() {
    local action="$1" answer
    echo 'Static Panel UI only. Backend, nodes, pairing and tunnels stay unchanged. No restart.'
    echo 'A private durable backup is retained for rollback. Update U-OPTI first to obtain the newest reviewed UI.'
    if [ "$action" = rollback ]; then
        read -rp 'Restore the previous Panel UI? [y/N]: ' answer || return 2
    else
        read -rp 'Back up and apply the bundled reviewed Panel UI? [y/N]: ' answer || return 2
    fi
    case "$answer" in y|Y|yes|YES) ;; *) return 2 ;; esac
    smite_install_ui_action "$action" || { echo 'HOLD: UI operation incomplete; backup retained.'; smite_install_pause; return 2; }
    echo 'Refresh the Panel with Ctrl+F5.'
    smite_install_pause
}

show_smite_install_menu() {
    while true; do
        clear
        echo "======================================"
        echo "      Smite Install / Lifecycle"
        echo "======================================"
        echo
        echo "1) Install Panel + Iran Node"
        echo "2) Install Foreign Node"
        echo "3) Installation State"
        echo "4) Install Sanaei 3x-UI on Foreign Node"
        echo "5) Upgrade signed Field Trial candidate (existing IR)"
        echo "6) Configure Foreign HTTPS/443 Gateway (before pairing)"
        echo
        echo "7) Recover interrupted RC6/RC7 install (retain data / rollback)"
        echo "8) Update Panel appearance (UI only / backup first)"
        echo "9) Roll back previous Panel appearance (UI only)"
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-9]: " smite_install_choice
        smite_install_choice="${smite_install_choice#"${smite_install_choice%%[![:space:]]*}"}"
        smite_install_choice="${smite_install_choice%"${smite_install_choice##*[![:space:]]}"}"
        case "$smite_install_choice" in
            1)
                if ! smite_install_selected_fresh panel-iran; then
                    echo 'HOLD: Panel + Iran Node installation did not complete. Review error above.'
                    smite_install_pause
                fi
                ;;
            2)
                if ! smite_install_selected_fresh foreign; then
                    echo 'HOLD: Foreign Node installation did not complete. Review error above.'
                    smite_install_pause
                fi
                ;;
            3) smite_show_installation_state ;;
            4) smite_install_sanaei_foreign ;;
            5) smite_install_upgrade_signed_field_trial ;;
            6) smite_foreign_gateway_configure ;;
            7) smite_install_selected_rollback ;;
            8) smite_install_ui_menu_action apply ;;
            9) smite_install_ui_menu_action rollback ;;
            0) break ;;
            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}
