#!/usr/bin/env bash

# U-OPTI - 3x-UI Docker Multi-Instance Registry
# v0.13.0

DOCKER_3XUI_BASE_DIR="/opt/3x-ui"
DOCKER_3XUI_INSTANCES_DIR="$DOCKER_3XUI_BASE_DIR/instances"
DOCKER_3XUI_REGISTRY_DIR="$DOCKER_3XUI_INSTANCES_DIR/registry"

DOCKER_3XUI_INSTANCE_ID=""
DOCKER_3XUI_INSTANCE_NAME=""
DOCKER_3XUI_INSTANCE_DIR=""
DOCKER_3XUI_INSTANCE_CONTAINER=""
DOCKER_3XUI_INSTANCE_COMPOSE=""
DOCKER_3XUI_INSTANCE_COMPAT_ENV=""
DOCKER_3XUI_INSTANCE_STATE_FILE=""

DOCKER_3XUI_REGISTRY_LOCK="$DOCKER_3XUI_REGISTRY_DIR/.lock"

docker_3xui_instance_validate_id() {
    [[ "$1" =~ ^[0-9]{2}$ ]]
}

docker_3xui_instance_set_context() {
    local INSTANCE_ID="$1"

    if ! docker_3xui_instance_validate_id "$INSTANCE_ID"; then
        echo "ERROR: Invalid 3x-UI Instance ID: $INSTANCE_ID"
        echo "Expected format: 01, 02, 03 ..."
        return 1
    fi

    DOCKER_3XUI_INSTANCE_ID="$INSTANCE_ID"
    DOCKER_3XUI_INSTANCE_NAME="3xui-$INSTANCE_ID"
    DOCKER_3XUI_INSTANCE_DIR="$DOCKER_3XUI_INSTANCES_DIR/$INSTANCE_ID"
    DOCKER_3XUI_INSTANCE_CONTAINER="$DOCKER_3XUI_INSTANCE_NAME"
    DOCKER_3XUI_INSTANCE_COMPOSE="$DOCKER_3XUI_INSTANCE_DIR/docker-compose.yml"
    DOCKER_3XUI_INSTANCE_COMPAT_ENV="$DOCKER_3XUI_INSTANCE_DIR/compat.env"
    DOCKER_3XUI_INSTANCE_STATE_FILE="$DOCKER_3XUI_INSTANCE_DIR/state.env"

    return 0
}

docker_3xui_instance_ensure_registry() {
    mkdir -p "$DOCKER_3XUI_INSTANCES_DIR" "$DOCKER_3XUI_REGISTRY_DIR" || return 1
    touch "$DOCKER_3XUI_REGISTRY_LOCK" || return 1
    chmod 600 "$DOCKER_3XUI_REGISTRY_LOCK" || return 1
}

docker_3xui_instance_with_lock() {
    local LOCKED_FUNCTION="$1"
    shift

    docker_3xui_instance_ensure_registry || return 1

    flock -x 200 || {
        echo "ERROR: Failed to acquire 3x-UI Instance Registry lock."
        return 1
    }

    "$LOCKED_FUNCTION" "$@"
    local RC=$?

    flock -u 200 || true

    return "$RC"
}

docker_3xui_instance_lock_open() {
    docker_3xui_instance_ensure_registry || return 1
    exec 200>"$DOCKER_3XUI_REGISTRY_LOCK" || {
        echo "ERROR: Failed to open 3x-UI Instance Registry lock."
        return 1
    }

    flock -x 200 || {
        echo "ERROR: Failed to acquire 3x-UI Instance Registry lock."
        exec 200>&-
        return 1
    }

    return 0
}

docker_3xui_instance_lock_close() {
    flock -u 200 2>/dev/null || true
    exec 200>&- 2>/dev/null || true
}

docker_3xui_instance_state_path() {
    local INSTANCE_ID="$1"

    if ! docker_3xui_instance_validate_id "$INSTANCE_ID"; then
        return 1
    fi

    printf '%s\n' "$DOCKER_3XUI_INSTANCES_DIR/$INSTANCE_ID/state.env"
}

docker_3xui_instance_is_registered() {
    local INSTANCE_ID="$1"
    local STATE_FILE

    STATE_FILE="$(docker_3xui_instance_state_path "$INSTANCE_ID")" || return 1

    [[ -s "$STATE_FILE" ]]
}

docker_3xui_instance_next_id() {
    local INSTANCE_ID

    docker_3xui_instance_ensure_registry || return 1

    for INSTANCE_ID in $(seq -w 1 99); do
        if ! docker_3xui_instance_is_registered "$INSTANCE_ID"; then
            printf '%s\n' "$INSTANCE_ID"
            return 0
        fi
    done

    echo "ERROR: No free 3x-UI Instance ID is available." >&2
    return 1
}

docker_3xui_instance_save_state() {
    local INSTANCE_ID="$1"
    local DOMAIN="$2"
    local PANEL_PORT="$3"
    local API_PORT="$4"
    local SUB_PORT="$5"
    local METRICS_PORT="$6"

    if ! docker_3xui_instance_set_context "$INSTANCE_ID"; then
        return 1
    fi

    if [[ -z "$DOMAIN" ||
          -z "$PANEL_PORT" ||
          -z "$API_PORT" ||
          -z "$SUB_PORT" ||
          -z "$METRICS_PORT" ]]; then
        echo "ERROR: Missing Instance state information."
        return 1
    fi

    mkdir -p "$DOCKER_3XUI_INSTANCE_DIR" || return 1

    cat > "$DOCKER_3XUI_INSTANCE_STATE_FILE" <<EOF_STATE
INSTANCE_ID=$DOCKER_3XUI_INSTANCE_ID
INSTANCE_NAME=$DOCKER_3XUI_INSTANCE_NAME
CONTAINER_NAME=$DOCKER_3XUI_INSTANCE_CONTAINER
DOMAIN=$DOMAIN
DATA_DIR=$DOCKER_3XUI_INSTANCE_DIR
COMPOSE_FILE=$DOCKER_3XUI_INSTANCE_COMPOSE
PANEL_PORT=$PANEL_PORT
API_PORT=$API_PORT
SUBSCRIPTION_PORT=$SUB_PORT
METRICS_PORT=$METRICS_PORT
EOF_STATE

    chmod 600 "$DOCKER_3XUI_INSTANCE_STATE_FILE"
}

docker_3xui_instance_load_state() {
    local INSTANCE_ID="$1"

    if ! docker_3xui_instance_set_context "$INSTANCE_ID"; then
        return 1
    fi

    if [[ ! -s "$DOCKER_3XUI_INSTANCE_STATE_FILE" ]]; then
        echo "ERROR: Instance $INSTANCE_ID state was not found:"
        echo "$DOCKER_3XUI_INSTANCE_STATE_FILE"
        return 1
    fi

    # shellcheck disable=SC1090
    source "$DOCKER_3XUI_INSTANCE_STATE_FILE"

    # Restore canonical Instance Context.
    DOCKER_3XUI_INSTANCE_ID="${INSTANCE_ID}"
    DOCKER_3XUI_INSTANCE_NAME="${CONTAINER_NAME:-3xui-$INSTANCE_ID}"
    DOCKER_3XUI_INSTANCE_CONTAINER="${CONTAINER_NAME:-3xui-$INSTANCE_ID}"
    DOCKER_3XUI_INSTANCE_DIR="${DATA_DIR:-$DOCKER_3XUI_INSTANCES_DIR/$INSTANCE_ID}"
    DOCKER_3XUI_INSTANCE_COMPOSE="${COMPOSE_FILE:-$DOCKER_3XUI_INSTANCE_DIR/docker-compose.yml}"
    DOCKER_3XUI_INSTANCE_COMPAT_ENV="${DOCKER_3XUI_INSTANCE_DIR}/compat.env"
    DOCKER_3XUI_INSTANCE_STATE_FILE="${DOCKER_3XUI_INSTANCE_DIR}/state.env"

    DOCKER_3XUI_INSTANCE_DOMAIN="${DOMAIN:-}"
    DOCKER_3XUI_INSTANCE_PANEL_PORT="${PANEL_PORT:-}"
    DOCKER_3XUI_INSTANCE_API_PORT="${API_PORT:-}"
    DOCKER_3XUI_INSTANCE_SUB_PORT="${SUBSCRIPTION_PORT:-}"
    DOCKER_3XUI_INSTANCE_METRICS_PORT="${METRICS_PORT:-}"

    return 0
}

docker_3xui_instance_apply_runtime_context() {
    local INSTANCE_ID="$1"

    if ! docker_3xui_instance_load_state "$INSTANCE_ID"; then
        return 1
    fi

    DOCKER_3XUI_CONTAINER="$DOCKER_3XUI_INSTANCE_CONTAINER"
    DOCKER_3XUI_DIR="$DOCKER_3XUI_INSTANCE_DIR"
    DOCKER_3XUI_COMPOSE_FILE="$DOCKER_3XUI_INSTANCE_COMPOSE"
    DOCKER_3XUI_COMPAT_ENV="$DOCKER_3XUI_INSTANCE_COMPAT_ENV"
    DOCKER_3XUI_PANEL_PORT="$DOCKER_3XUI_INSTANCE_PANEL_PORT"

    DOCKER_3XUI_DOMAIN="$DOCKER_3XUI_INSTANCE_DOMAIN"
    DOCKER_3XUI_API_PORT="$DOCKER_3XUI_INSTANCE_API_PORT"
    DOCKER_3XUI_SUBSCRIPTION_PORT="$DOCKER_3XUI_INSTANCE_SUB_PORT"
    DOCKER_3XUI_METRICS_PORT="$DOCKER_3XUI_INSTANCE_METRICS_PORT"

    return 0
}


docker_3xui_instance_apply_compat_context() {
    local INSTANCE_ID="$1"

    if ! docker_3xui_instance_apply_runtime_context "$INSTANCE_ID"; then
        return 1
    fi

    DOCKER_3XUI_COMPAT_PANEL_PORT="$DOCKER_3XUI_INSTANCE_PANEL_PORT"
    DOCKER_3XUI_COMPAT_API_PORT="$DOCKER_3XUI_INSTANCE_API_PORT"
    DOCKER_3XUI_COMPAT_SUB_PORT="$DOCKER_3XUI_INSTANCE_SUB_PORT"
    DOCKER_3XUI_COMPAT_METRICS_PORT="$DOCKER_3XUI_INSTANCE_METRICS_PORT"

    return 0
}


docker_3xui_instance_validate_reservation() {
    local INSTANCE_ID="$1"
    local EXPECTED_DOMAIN="${2:-}"

    if ! docker_3xui_instance_load_state "$INSTANCE_ID"; then
        echo "ERROR: Instance $INSTANCE_ID reservation could not be loaded."
        return 1
    fi

    if [[ -z "$DOCKER_3XUI_INSTANCE_DOMAIN" ]]; then
        echo "ERROR: Instance $INSTANCE_ID has no domain in its reservation."
        return 1
    fi

    if [[ -n "$EXPECTED_DOMAIN" &&
          "$DOCKER_3XUI_INSTANCE_DOMAIN" != "$EXPECTED_DOMAIN" ]]; then
        echo "ERROR: Instance $INSTANCE_ID domain does not match the reservation."
        echo "Reserved : $DOCKER_3XUI_INSTANCE_DOMAIN"
        echo "Expected : $EXPECTED_DOMAIN"
        return 1
    fi

    local REQUIRED_VALUE
    local REQUIRED_NAME

    for REQUIRED_NAME in         DOCKER_3XUI_INSTANCE_PANEL_PORT         DOCKER_3XUI_INSTANCE_API_PORT         DOCKER_3XUI_INSTANCE_SUB_PORT         DOCKER_3XUI_INSTANCE_METRICS_PORT
    do
        REQUIRED_VALUE="${!REQUIRED_NAME:-}"

        if [[ -z "$REQUIRED_VALUE" ||
              ! "$REQUIRED_VALUE" =~ ^[0-9]+$ ||
              "$REQUIRED_VALUE" -lt 1 ||
              "$REQUIRED_VALUE" -gt 65535 ]]; then
            echo "ERROR: Invalid reserved value for $REQUIRED_NAME."
            return 1
        fi
    done

    return 0
}


docker_3xui_instance_prepare_for_install() {
    local INSTANCE_ID="${1:-}"
    local DOMAIN="${2:-}"

    if [[ -z "$INSTANCE_ID" ]]; then
        echo "ERROR: Instance ID is required."
        return 1
    fi

    if ! docker_3xui_instance_validate_id "$INSTANCE_ID"; then
        echo "ERROR: Invalid 3x-UI Instance ID: $INSTANCE_ID"
        return 1
    fi

    if [[ -n "$DOMAIN" && ! "$DOMAIN" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$ ]]; then
        echo "ERROR: Invalid domain format: $DOMAIN"
        return 1
    fi

    if docker_3xui_instance_is_registered "$INSTANCE_ID"; then
        echo "Using existing reservation for Instance $INSTANCE_ID."

        if ! docker_3xui_instance_validate_reservation "$INSTANCE_ID" "$DOMAIN"; then
            return 1
        fi
    else
        if [[ -z "$DOMAIN" ]]; then
            echo "ERROR: Domain is required when creating a new Instance reservation."
            return 1
        fi

        echo "Creating reservation for Instance $INSTANCE_ID..."

        if ! docker_3xui_instance_reserve_ports "$INSTANCE_ID" "$DOMAIN"; then
            return 1
        fi

        if ! docker_3xui_instance_validate_reservation "$INSTANCE_ID" "$DOMAIN"; then
            echo "ERROR: Newly created reservation failed validation."

            docker_3xui_instance_release_reservation "$INSTANCE_ID" || true
            return 1
        fi
    fi

    if ! docker_3xui_instance_apply_compat_context "$INSTANCE_ID"; then
        echo "ERROR: Failed to apply Instance $INSTANCE_ID runtime context."
        return 1
    fi

    return 0
}

docker_3xui_instance_registered_ids() {
    local INSTANCE_ID
    local STATE_FILE

    docker_3xui_instance_ensure_registry || return 1

    for INSTANCE_ID in $(seq -w 1 99); do
        STATE_FILE="$DOCKER_3XUI_INSTANCES_DIR/$INSTANCE_ID/state.env"

        if [[ -s "$STATE_FILE" ]]; then
            printf '%s\n' "$INSTANCE_ID"
        fi
    done
}

docker_3xui_instance_port_listening() {
    local PORT="$1"

    [[ "$PORT" =~ ^[0-9]+$ ]] || return 1

    ss -lntp 2>/dev/null |
        awk -v port=":$PORT" '
            NR > 1 && $4 ~ port "$" {
                found=1
            }
            END {
                exit(found ? 0 : 1)
            }
        '
}

docker_3xui_instance_port_reserved_in_states() {
    local PORT="$1"
    local INSTANCE_ID
    local STATE_FILE
    local VALUE

    docker_3xui_instance_ensure_registry || return 1

    for INSTANCE_ID in $(seq -w 1 99); do
        STATE_FILE="$DOCKER_3XUI_INSTANCES_DIR/$INSTANCE_ID/state.env"

        [[ -s "$STATE_FILE" ]] || continue

        while IFS='=' read -r KEY VALUE; do
            case "$KEY" in
                PANEL_PORT|API_PORT|SUBSCRIPTION_PORT|METRICS_PORT)
                    if [[ "$VALUE" == "$PORT" ]]; then
                        return 0
                    fi
                    ;;
            esac
        done < "$STATE_FILE"
    done

    return 1
}

docker_3xui_instance_port_reserved_legacy() {
    local PORT="$1"
    local LEGACY_ENV="$DOCKER_3XUI_BASE_DIR/compat.env"
    local KEY
    local VALUE

    if [[ -f "$LEGACY_ENV" ]]; then
        while IFS='=' read -r KEY VALUE; do
            case "$KEY" in
                PANEL_PORT|API_PORT|SUBSCRIPTION_PORT|METRICS_PORT)
                    [[ "$VALUE" == "$PORT" ]] && return 0
                    ;;
            esac
        done < "$LEGACY_ENV"
    fi

    # Legacy 04 predates API_PORT in compat.env.
    # Read its actual Xray API port from its database when possible.
    local LEGACY_DB="$DOCKER_3XUI_BASE_DIR/db/x-ui.db"
    local TEMPLATE_JSON
    local API_PORT

    if [[ -f "$LEGACY_DB" ]] && command -v sqlite3 >/dev/null 2>&1; then
        TEMPLATE_JSON="$(
            sqlite3 "$LEGACY_DB" \
                "SELECT value FROM settings WHERE key='xrayTemplateConfig' LIMIT 1;" \
                2>/dev/null || true
        )"

        if [[ -n "$TEMPLATE_JSON" ]]; then
            API_PORT="$(
                printf '%s' "$TEMPLATE_JSON" |
                    python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
    for inbound in data.get("inbounds", []):
        if inbound.get("tag") == "api":
            port = inbound.get("port")
            if isinstance(port, int):
                print(port)
                break
except Exception:
    pass
' 2>/dev/null || true
            )"

            [[ "$API_PORT" == "$PORT" ]] && return 0
        fi
    fi

    return 1
}

docker_3xui_instance_port_reserved_pro() {
    local PORT="$1"
    local PRO_DB="/etc/x-ui/x-ui.db"
    local PRO_CONFIG="/usr/local/x-ui/bin/config.json"
    local VALUE
    local TEMPLATE_JSON

    # X-UI PRO panel and subscription ports stored in the database.
    if [[ -f "$PRO_DB" ]] && command -v sqlite3 >/dev/null 2>&1; then
        VALUE="$(
            sqlite3 "$PRO_DB" \
                "SELECT value FROM settings WHERE key='webPort' LIMIT 1;" \
                2>/dev/null || true
        )"

        [[ "$VALUE" == "$PORT" ]] && return 0

        VALUE="$(
            sqlite3 "$PRO_DB" \
                "SELECT value FROM settings WHERE key='subPort' LIMIT 1;" \
                2>/dev/null || true
        )"

        [[ "$VALUE" == "$PORT" ]] && return 0
    fi

    # X-UI PRO real Xray runtime config.
    # Check both API and Metrics listeners from the live config file.
    if [[ -f "$PRO_CONFIG" ]] && command -v python3 >/dev/null 2>&1; then
        VALUE="$(
            python3 - "$PRO_CONFIG" <<'PYTHON'
import json
import sys

path = sys.argv[1]

try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    for inbound in data.get("inbounds", []):
        if inbound.get("tag") == "api":
            port = inbound.get("port")
            if isinstance(port, int):
                print(port)
                break

    metrics = data.get("metrics")
    if isinstance(metrics, dict):
        listen = metrics.get("listen")
        if isinstance(listen, str):
            if ":" in listen:
                port = listen.rsplit(":", 1)[1]
            else:
                port = listen

            if port.isdigit():
                print(f"METRICS:{port}")
except Exception:
    pass
PYTHON
        )"

        while IFS= read -r VALUE; do
            case "$VALUE" in
                METRICS:*)
                    [[ "${VALUE#METRICS:}" == "$PORT" ]] && return 0
                    ;;
                *)
                    [[ "$VALUE" == "$PORT" ]] && return 0
                    ;;
            esac
        done <<< "$VALUE"
    fi

    # Optional fallback: X-UI PRO template config stored in the database.
    if [[ -f "$PRO_DB" ]] &&
       command -v sqlite3 >/dev/null 2>&1 &&
       command -v python3 >/dev/null 2>&1; then

        TEMPLATE_JSON="$(
            sqlite3 "$PRO_DB" \
                "SELECT value FROM settings WHERE key='xrayTemplateConfig' LIMIT 1;" \
                2>/dev/null || true
        )"

        if [[ -n "$TEMPLATE_JSON" ]]; then
            VALUE="$(
                printf '%s' "$TEMPLATE_JSON" |
                    python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)

    for inbound in data.get("inbounds", []):
        if inbound.get("tag") == "api":
            port = inbound.get("port")
            if isinstance(port, int):
                print(port)

    metrics = data.get("metrics")
    if isinstance(metrics, dict):
        listen = metrics.get("listen")
        if isinstance(listen, str):
            port = listen.rsplit(":", 1)[-1]
            if port.isdigit():
                print(f"METRICS:{port}")
except Exception:
    pass
' 2>/dev/null || true
            )"

            while IFS= read -r VALUE; do
                case "$VALUE" in
                    METRICS:*)
                        [[ "${VALUE#METRICS:}" == "$PORT" ]] && return 0
                        ;;
                    *)
                        [[ "$VALUE" == "$PORT" ]] && return 0
                        ;;
                esac
            done <<< "$VALUE"
        fi
    fi

    return 1
}


docker_3xui_instance_port_available() {
    local PORT="$1"

    docker_3xui_instance_port_listening "$PORT" && return 1
    docker_3xui_instance_port_reserved_in_states "$PORT" && return 1
    docker_3xui_instance_port_reserved_legacy "$PORT" && return 1
    docker_3xui_instance_port_reserved_pro "$PORT" && return 1

    return 0
}

docker_3xui_instance_select_port() {
    local VARIABLE="$1"
    local LABEL="$2"
    local START="$3"
    local END="$4"
    local PORT

    unset "$VARIABLE"

    for ((PORT=START; PORT<=END; PORT++)); do
        if docker_3xui_instance_port_available "$PORT"; then
            printf -v "$VARIABLE" '%s' "$PORT"
            return 0
        fi
    done

    echo
    echo "ERROR: No free $LABEL port is available."
    echo "Checked range: $START-$END"
    echo

    return 1
}

docker_3xui_instance_allocate_ports() {
    local PANEL_PORT
    local API_PORT
    local SUB_PORT
    local METRICS_PORT

    if ! docker_3xui_instance_select_port \
        PANEL_PORT \
        "3x-UI Panel" \
        2053 \
        2094; then
        return 1
    fi

    if ! docker_3xui_instance_select_port \
        API_PORT \
        "Xray API" \
        62789 \
        62850; then
        return 1
    fi

    if ! docker_3xui_instance_select_port \
        SUB_PORT \
        "Subscription" \
        2095 \
        2120; then
        return 1
    fi

    if ! docker_3xui_instance_select_port \
        METRICS_PORT \
        "Xray Metrics" \
        11111 \
        11130; then
        return 1
    fi

    DOCKER_3XUI_INSTANCE_PANEL_PORT="$PANEL_PORT"
    DOCKER_3XUI_INSTANCE_API_PORT="$API_PORT"
    DOCKER_3XUI_INSTANCE_SUB_PORT="$SUB_PORT"
    DOCKER_3XUI_INSTANCE_METRICS_PORT="$METRICS_PORT"

    return 0
}

docker_3xui_instance_reserve_ports() {
    local INSTANCE_ID="$1"
    local DOMAIN="$2"

    if ! docker_3xui_instance_validate_id "$INSTANCE_ID"; then
        echo "ERROR: Invalid Instance ID: $INSTANCE_ID"
        return 1
    fi

    if [[ -z "$DOMAIN" ]]; then
        echo "ERROR: Domain is required."
        return 1
    fi

    if docker_3xui_instance_is_registered "$INSTANCE_ID"; then
        echo "ERROR: Instance $INSTANCE_ID is already registered."
        return 1
    fi

    if ! docker_3xui_instance_lock_open; then
        return 1
    fi

    if docker_3xui_instance_is_registered "$INSTANCE_ID"; then
        echo "ERROR: Instance $INSTANCE_ID became registered while acquiring lock."
        docker_3xui_instance_lock_close
        return 1
    fi

    if ! docker_3xui_instance_allocate_ports; then
        docker_3xui_instance_lock_close
        return 1
    fi

    if ! docker_3xui_instance_save_state         "$INSTANCE_ID"         "$DOMAIN"         "$DOCKER_3XUI_INSTANCE_PANEL_PORT"         "$DOCKER_3XUI_INSTANCE_API_PORT"         "$DOCKER_3XUI_INSTANCE_SUB_PORT"         "$DOCKER_3XUI_INSTANCE_METRICS_PORT"; then

        echo "ERROR: Failed to reserve Instance state."
        docker_3xui_instance_lock_close
        return 1
    fi

    docker_3xui_instance_lock_close
    return 0
}

docker_3xui_instance_release_reservation() {
    local INSTANCE_ID="$1"

    if ! docker_3xui_instance_set_context "$INSTANCE_ID"; then
        return 1
    fi

    if ! docker_3xui_instance_lock_open; then
        return 1
    fi

    if [[ -f "$DOCKER_3XUI_INSTANCE_STATE_FILE" ]]; then
        rm -f "$DOCKER_3XUI_INSTANCE_STATE_FILE"
    fi

    # Remove empty instance directory only.
    if [[ -d "$DOCKER_3XUI_INSTANCE_DIR" ]] &&
       [[ -z "$(find "$DOCKER_3XUI_INSTANCE_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
        rmdir "$DOCKER_3XUI_INSTANCE_DIR" 2>/dev/null || true
    fi

    docker_3xui_instance_lock_close
    return 0
}

docker_3xui_instance_show_port_plan() {
    echo
    echo "3x-UI Instance Port Plan:"
    echo
    echo "Panel Port       : ${DOCKER_3XUI_INSTANCE_PANEL_PORT:-N/A}"
    echo "Xray API Port    : ${DOCKER_3XUI_INSTANCE_API_PORT:-N/A}"
    echo "Subscription     : ${DOCKER_3XUI_INSTANCE_SUB_PORT:-N/A}"
    echo "Metrics          : ${DOCKER_3XUI_INSTANCE_METRICS_PORT:-N/A}"
    echo
}

docker_3xui_instance_show_context() {
    echo
    echo "3x-UI Instance:"
    echo "  ID         : ${DOCKER_3XUI_INSTANCE_ID:-N/A}"
    echo "  Name       : ${DOCKER_3XUI_INSTANCE_NAME:-N/A}"
    echo "  Directory  : ${DOCKER_3XUI_INSTANCE_DIR:-N/A}"
    echo "  Container  : ${DOCKER_3XUI_INSTANCE_CONTAINER:-N/A}"
    echo "  Compose    : ${DOCKER_3XUI_INSTANCE_COMPOSE:-N/A}"
    echo "  State      : ${DOCKER_3XUI_INSTANCE_STATE_FILE:-N/A}"
    echo
}
