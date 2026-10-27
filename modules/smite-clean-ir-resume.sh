#!/usr/bin/env bash
# Guarded recovery for the explicitly authorized IR clean-RC field trial.
smite_install_resume_clean_ir() {
    local SMITE_INSTALL_PROFILE=clean-rc
    local SMITE_UPSTREAM_VERSION="2.0.0-rc.1"
    local bundle="${SMITE_RC_BUNDLE_DIR:-/opt/smite-stage15-bundle}"
    local manifest_sha="${SMITE_RC_MANIFEST_SHA256:-fe32c9c54714cfdb482f27112829eba13d5188e9e1e7e26c7266d8d54e85462a}"
    local source_sha="${SMITE_RC_SOURCE_SHA:-4e16633a304db6c03f7f2911cc7d77213b0c4ec1}"
    local module_dir helper panel_domain node_name peer_gid panel_id node_id answer backup preflight
    local -a summary=()

    clear
    echo "=============================================="
    echo " Resume interrupted clean-RC IR installation"
    echo "=============================================="
    echo
    echo "Read-only checks run first. No registration, grants or routes are created."
    echo

    [ "$(id -u)" -eq 0 ] || {
        echo "HOLD: Root is required."
        smite_install_pause
        return
    }
    [ "$(hostname -s 2>/dev/null | tr '[:upper:]' '[:lower:]')" = "ir" ] || {
        echo "HOLD: This recovery is restricted to the IR test host."
        smite_install_pause
        return
    }
    if [ -e "$SMITE_STATE_FILE" ] || [ -L "$SMITE_STATE_FILE" ]; then
        echo "HOLD: Managed state already exists; use the normal status/upgrade path."
        smite_install_pause
        return
    fi
    if ! smite_container_exists smite-panel ||
       ! smite_container_running smite-panel ||
       ! smite_wait_healthy smite-panel 10; then
        echo "HOLD: A healthy Panel container is required."
        smite_install_pause
        return
    fi
    [ "$(docker inspect -f '{{.Config.Image}}' smite-panel 2>/dev/null)" = "smite-panel:stage15-local" ] || {
        echo "HOLD: The running Panel is not the reviewed local Field Trial image."
        smite_install_pause
        return
    }
    if smite_container_exists smite-node; then
        [ "$(docker inspect -f '{{.Config.Image}}' smite-node 2>/dev/null)" = "smite-node:stage15-local" ] &&
        smite_container_running smite-node && smite_wait_healthy smite-node 10 || {
            echo "HOLD: Existing Node is not the expected healthy local test image."
            smite_install_pause
            return
        }
    fi
    [ -f "$SMITE_PANEL_COMPOSE" ] && [ ! -L "$SMITE_PANEL_COMPOSE" ] &&
    [ -f "$SMITE_NODE_COMPOSE" ] && [ ! -L "$SMITE_NODE_COMPOSE" ] || {
        echo "HOLD: Expected regular Panel and Node Compose files are not present."
        smite_install_pause
        return
    }

    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || {
        echo "HOLD: Could not resolve U-OPTI module directory."
        smite_install_pause
        return
    }
    helper="$module_dir/smite-clean-image-pair.py"
    [ -f "$helper" ] && [ ! -L "$helper" ] || {
        echo "HOLD: Image-pair verifier is not installed."
        smite_install_pause
        return
    }
    python3 -B "$helper" --folder "$bundle" --source-sha "$source_sha" \
        --manifest-sha256 "$manifest_sha" || {
        echo "HOLD: The local Field Trial archive/manifest no longer verifies."
        smite_install_pause
        return
    }
    if ! preflight="$(python3 - "$SMITE_PANEL_DIR" "$SMITE_NODE_DIR" "$bundle" "$manifest_sha" <<'PY_RESUME_PREFLIGHT'
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

panel_dir = Path(sys.argv[1])
node_dir = Path(sys.argv[2])
bundle = Path(sys.argv[3])
expected_manifest = sys.argv[4]

def checked_file(path, mode=None):
    try:
        st = path.lstat()
    except OSError as exc:
        raise SystemExit("EXPECTED_FILE_MISSING") from exc
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1
            or st.st_mode & 0o022 or (mode is not None and stat.S_IMODE(st.st_mode) != mode)):
        raise SystemExit("UNTRUSTED_FILE_MODE_OR_OWNER")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
            raise SystemExit("FILE_CHANGED_DURING_PREFLIGHT")
        raw = os.read(fd, st.st_size + 1)
    finally:
        os.close(fd)
    if len(raw) != st.st_size:
        raise SystemExit("FILE_CHANGED_DURING_PREFLIGHT")
    return raw.decode("utf-8")

def env(path):
    result = {}
    for line in checked_file(path, 0o600).splitlines():
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if (not sep or not re.fullmatch(r"[A-Z0-9_]+", key) or key in result
                or "\n" in value or "\r" in value):
            raise SystemExit("UNREVIEWED_ENV_FORMAT")
        result[key] = value
    return result

panel = env(panel_dir / ".env")
node = env(node_dir / ".env")
panel_compose = checked_file(panel_dir / "docker-compose.yml")
node_compose = checked_file(node_dir / "docker-compose.yml")
if (panel.get("PANEL_DOMAIN", "") == "" or panel.get("PANEL_HOST") != "127.0.0.1"
        or panel.get("SMITE_VERSION") != "2.0.0-rc.1"
        or panel.get("SMITE_NODE_REGISTRATION_MODE") != "signed"
        or panel.get("SMITE_PANEL_AGENT_AUTH_MODE") != "signed"
        or panel.get("SMITE_NODE_PAIRING_PREVIEW_ENABLED") != "false"
        or panel.get("SMITE_ENGINE_MANAGEMENT_MODE") != "managed"
        or not re.fullmatch(r"[0-9a-f]{64}", panel.get("SECRET_KEY", ""))):
    raise SystemExit("PANEL_ENV_NOT_EXACT_CLEAN_RC")
if (not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", panel["PANEL_DOMAIN"])
        or "." not in panel["PANEL_DOMAIN"]):
    raise SystemExit("PANEL_DOMAIN_INVALID")
if (node.get("NODE_ROLE") != "iran" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", node.get("NODE_NAME", ""))
        or node.get("SMITE_VERSION") != "2.0.0-rc.1"
        or node.get("PANEL_ADDRESS") != "127.0.0.1:8000"
        or node.get("SMITE_NODE_PANEL_AUTH_MODE") != "paused"
        or node.get("SMITE_AGENT_AUTH_MODE") != "strict"
        or node.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"
        or node.get("SMITE_UOPTI_ROUTE_BROKER_ENABLED") not in {"false", "true"}
        or node.get("SMITE_UOPTI_ROUTE_BROKER_SOCKET") != "/run/u-opti/smite/xhttp-broker.sock"):
    raise SystemExit("NODE_ENV_NOT_EXACT_CLEAN_RC")
gid = node.get("SMITE_UOPTI_BROKER_GID", "")
if not gid.isascii() or not gid.isdecimal() or not 1 <= int(gid) < 65536:
    raise SystemExit("BROKER_GID_INVALID")
if panel_compose.count("image: smite-panel:stage15-local") != 1 or node_compose.count("image: smite-node:stage15-local") != 1:
    raise SystemExit("COMPOSE_IMAGES_NOT_EXACT_LOCAL_PAIR")
if "  smite-panel:\n" not in panel_compose or "  smite-node:\n" not in node_compose:
    raise SystemExit("COMPOSE_SERVICES_UNREVIEWED")
manifest_path = bundle / "stage15-images.json"
manifest_raw = checked_file(manifest_path).encode("utf-8")
if hashlib.sha256(manifest_raw).hexdigest() != expected_manifest:
    raise SystemExit("MANIFEST_HASH_MISMATCH")
manifest = json.loads(manifest_raw)
panel_id = manifest["images"]["panel"]["local_image_id"]
node_id = manifest["images"]["node"]["local_image_id"]
if not isinstance(panel_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", panel_id):
    raise SystemExit("PANEL_IMAGE_ID_INVALID")
if not isinstance(node_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", node_id):
    raise SystemExit("NODE_IMAGE_ID_INVALID")
print(panel["PANEL_DOMAIN"])
print(node["NODE_NAME"])
print(gid)
print(panel_id)
print(node_id)
PY_RESUME_PREFLIGHT
    )"; then
        echo "HOLD: Partial-install files do not match the reviewed clean-RC layout."
        smite_install_pause
        return
    fi
    mapfile -t summary <<< "$preflight"
    [ "${#summary[@]}" -eq 5 ] || {
        echo "HOLD: Clean-RC recovery summary is incomplete."
        smite_install_pause
        return
    }
    panel_domain="${summary[0]}"
    node_name="${summary[1]}"
    peer_gid="${summary[2]}"
    panel_id="${summary[3]}"
    node_id="${summary[4]}"
    [ "$(docker image inspect smite-panel:stage15-local --format '{{.Id}}' 2>/dev/null)" = "$panel_id" ] &&
    [ "$(docker image inspect smite-node:stage15-local --format '{{.Id}}' 2>/dev/null)" = "$node_id" ] &&
    [ "$(docker inspect -f '{{.Config.Image}}' smite-panel 2>/dev/null)" = "smite-panel:stage15-local" ] || {
        echo "HOLD: Local image IDs do not match the pinned offline manifest."
        smite_install_pause
        return
    }
    docker compose -f "$SMITE_PANEL_COMPOSE" config >/dev/null &&
    docker compose -f "$SMITE_NODE_COMPOSE" config >/dev/null &&
    curl -fsS --max-time 5 http://127.0.0.1:8000/api/status >/dev/null || {
        echo "HOLD: Existing Panel or Compose preflight failed."
        smite_install_pause
        return
    }

    echo "Panel domain : $panel_domain"
    echo "Iran node    : $node_name"
    echo "Images       : exact IDs in verified local manifest"
    echo "Broker GID   : $peer_gid"
    echo "Pairing      : remains pending"
    echo "Trusted grants: remain empty"
    echo "Live routes  : unchanged"
    echo
    read -r -p "Type RESUME-CLEAN-IR-FIELD-TRIAL to continue this partial test install: " answer
    [ "$answer" = "RESUME-CLEAN-IR-FIELD-TRIAL" ] || {
        echo "Cancelled; no changes were made."
        smite_install_pause
        return
    }

    if ! declare -F smite_clean_rc_prepare_gateway_packages >/dev/null 2>&1; then
        module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        [ -s "$module_dir/smite-clean-rc-preflight.sh" ] &&
            [ ! -L "$module_dir/smite-clean-rc-preflight.sh" ] || {
                echo "HOLD: Clean-RC Nginx package preflight module is missing or unsafe."
                smite_install_pause
                return
            }
        # shellcheck source=/dev/null
        source "$module_dir/smite-clean-rc-preflight.sh" || {
            smite_install_pause
            return
        }
    fi
    if ! smite_clean_rc_prepare_gateway_packages; then
        echo "HOLD: Host Nginx prerequisite is not ready; broker activation was not attempted."
        smite_install_pause
        return
    fi

    backup="$(mktemp -d /var/backups/u-opti-smite-ir-resume.XXXXXX)" || {
        echo "HOLD: Could not create a recovery snapshot."
        smite_install_pause
        return
    }
    chmod 0700 "$backup" || { rm -rf -- "$backup"; smite_install_pause; return; }
    cp -a "$SMITE_PANEL_COMPOSE" "$backup/panel-compose.yml" &&
    cp -a "$SMITE_NODE_COMPOSE" "$backup/node-compose.yml" &&
    cp -a "$SMITE_PANEL_DIR/.env" "$backup/panel.env" &&
    cp -a "$SMITE_NODE_DIR/.env" "$backup/node.env" || {
        echo "HOLD: Could not create a complete recovery snapshot."
        rm -rf -- "$backup"
        smite_install_pause
        return
    }
    echo "Recovery snapshot: $backup"

    helper="$module_dir/smite-rc5-xhttp-broker-compose.py"
    if ! python3 -B "$helper" panel "$SMITE_PANEL_COMPOSE" --peer-gid "$peer_gid" ||
       ! python3 -B "$helper" node-prepare "$SMITE_NODE_COMPOSE" --peer-gid "$peer_gid" ||
       ! docker compose -f "$SMITE_PANEL_COMPOSE" config >/dev/null ||
       ! docker compose -f "$SMITE_NODE_COMPOSE" config >/dev/null; then
        echo "HOLD: Broker mount preparation failed. Recovery snapshot retained at $backup"
        smite_install_pause
        return
    fi

    SMITE_UOPTI_BROKER_GID="$peer_gid"
    if ! docker compose -f "$SMITE_NODE_COMPOSE" up -d --no-build smite-node ||
       ! smite_wait_healthy smite-node 90 ||
       ! smite_install_clean_rc_broker_start_node_forwarding ||
       ! docker exec smite-node python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8888/healthz",timeout=3)' ||
       ! smite_write_state "panel-iran" "$panel_domain" "$node_name" "" standard "" ""; then
        echo "HOLD: Resume did not complete; recovery snapshot retained at $backup"
        smite_install_pause
        return
    fi
    echo
    echo "The interrupted installer did not reach Smite admin setup."
    echo "Create the Panel administrator now; the password is entered privately."
    local create_admin=""
    read -r -p "Create a Smite admin account now? [Y/n]: " create_admin
    case "$create_admin" in
        n|N|no|NO)
            echo "HOLD: Panel administrator account remains uncreated."
            echo "Create it later with: cd /opt/smite && /usr/local/bin/smite admin create"
            smite_install_pause
            return 1
            ;;
    esac
    if ! smite_install_create_admin; then
        echo "HOLD: Smite admin account creation failed."
        echo "Retry later with: cd /opt/smite && /usr/local/bin/smite admin create"
        smite_install_pause
        return 1
    fi
    echo "PANEL_ADMIN_ACCOUNT=CREATED"
    rm -rf -- "$backup"
    echo
    echo "CLEAN_RC_IR_RESUME=PASS"
    echo "IR_RC_PAIRING=PENDING_SIGNED_ADMIN_APPROVAL"
    echo "TRUSTED_GRANTS=NONE"
    echo "LIVE_ROUTE_CHANGE=NO"
    echo "U-OPTI state saved for panel-iran / $node_name"
    smite_install_pause
}

