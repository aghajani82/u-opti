#!/bin/bash

# U-OPTI - 3x-UI Docker Compatibility Helpers
# v0.13.0

# -----------------------------------------------------------------------------
# Purpose
# -----------------------------------------------------------------------------
# Keeps Sanaei 3x-UI Docker compatible with an existing X-UI PRO installation
# on the same server without modifying the PRO installation.
#
# Design:
#   Panel        : fixed at 2053
#   Subscription : prefer 2096, then 2095, then 2097-2099
#   Metrics      : prefer 11111, then 11112, then 11113-11115
#
# Subscription is kept on localhost and published through Nginx :443.
# Xray metrics are kept on localhost.
#
# These are library functions only. Nothing runs automatically when sourced.
# -----------------------------------------------------------------------------

DOCKER_3XUI_COMPAT_PANEL_PORT="2053"

DOCKER_3XUI_COMPAT_SUB_PRIMARY="2096"
DOCKER_3XUI_COMPAT_SUB_FALLBACK="2095"
DOCKER_3XUI_COMPAT_SUB_EXTRA_1="2097"
DOCKER_3XUI_COMPAT_SUB_EXTRA_2="2098"
DOCKER_3XUI_COMPAT_SUB_EXTRA_3="2099"

DOCKER_3XUI_COMPAT_METRICS_PRIMARY="11111"
DOCKER_3XUI_COMPAT_METRICS_FALLBACK="11112"
DOCKER_3XUI_COMPAT_METRICS_EXTRA_1="11113"
DOCKER_3XUI_COMPAT_METRICS_EXTRA_2="11114"
DOCKER_3XUI_COMPAT_METRICS_EXTRA_3="11115"

docker_3xui_compat_port_is_in_use() {
    local PORT="$1"

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

docker_3xui_compat_require_free_port() {
    local PORT="$1"
    local LABEL="$2"

    if docker_3xui_compat_port_is_in_use "$PORT"; then
        echo
        echo "ERROR: $LABEL port $PORT/tcp is already in use."
        echo
        echo "Current listener:"
        ss -lntp 2>/dev/null | grep ":$PORT " || true
        return 1
    fi

    return 0
}

docker_3xui_compat_select_subscription_port() {
    local CANDIDATE
    local CANDIDATES=(
        "$DOCKER_3XUI_COMPAT_SUB_PRIMARY"
        "$DOCKER_3XUI_COMPAT_SUB_FALLBACK"
        "$DOCKER_3XUI_COMPAT_SUB_EXTRA_1"
        "$DOCKER_3XUI_COMPAT_SUB_EXTRA_2"
        "$DOCKER_3XUI_COMPAT_SUB_EXTRA_3"
    )

    unset DOCKER_3XUI_COMPAT_SUB_PORT

    for CANDIDATE in "${CANDIDATES[@]}"; do
        if ! docker_3xui_compat_port_is_in_use "$CANDIDATE"; then
            DOCKER_3XUI_COMPAT_SUB_PORT="$CANDIDATE"
            return 0
        fi
    done

    echo
    echo "ERROR: No preferred 3x-UI Subscription port is available."
    echo
    echo "Checked:"
    printf '  - %s/tcp\n' "${CANDIDATES[@]}"
    echo
    echo "U-OPTI will not change an existing service port automatically."
    return 1
}

docker_3xui_compat_select_metrics_port() {
    local CANDIDATE
    local CANDIDATES=(
        "$DOCKER_3XUI_COMPAT_METRICS_PRIMARY"
        "$DOCKER_3XUI_COMPAT_METRICS_FALLBACK"
        "$DOCKER_3XUI_COMPAT_METRICS_EXTRA_1"
        "$DOCKER_3XUI_COMPAT_METRICS_EXTRA_2"
        "$DOCKER_3XUI_COMPAT_METRICS_EXTRA_3"
    )

    unset DOCKER_3XUI_COMPAT_METRICS_PORT

    for CANDIDATE in "${CANDIDATES[@]}"; do
        if ! docker_3xui_compat_port_is_in_use "$CANDIDATE"; then
            DOCKER_3XUI_COMPAT_METRICS_PORT="$CANDIDATE"
            return 0
        fi
    done

    echo
    echo "ERROR: No preferred Xray Metrics port is available."
    echo
    echo "Checked:"
    printf '  - %s/tcp\n' "${CANDIDATES[@]}"
    echo
    echo "U-OPTI will not change an existing service port automatically."
    return 1
}

docker_3xui_compat_check_panel_port() {
    local PORT="$DOCKER_3XUI_COMPAT_PANEL_PORT"

    if docker_3xui_compat_port_is_in_use "$PORT"; then
        echo
        echo "ERROR: 3x-UI Docker panel port $PORT/tcp is already in use."
        echo
        echo "This usually means another 3x-UI/X-UI installation is already"
        echo "using the standard Sanaei panel port."
        echo
        echo "Current listener:"
        ss -lntp 2>/dev/null | grep ":$PORT " || true
        return 1
    fi

    return 0
}

docker_3xui_compat_show_port_plan() {
    echo
    echo "3x-UI Docker compatibility plan:"
    echo
    echo "Panel Port       : $DOCKER_3XUI_COMPAT_PANEL_PORT"

    if [ -n "${DOCKER_3XUI_COMPAT_SUB_PORT:-}" ]; then
        echo "Subscription     : $DOCKER_3XUI_COMPAT_SUB_PORT"
    else
        echo "Subscription     : Not selected yet"
    fi

    if [ -n "${DOCKER_3XUI_COMPAT_METRICS_PORT:-}" ]; then
        echo "Metrics          : $DOCKER_3XUI_COMPAT_METRICS_PORT"
    else
        echo "Metrics          : Not selected yet"
    fi

    echo
}

docker_3xui_compat_prepare_ports() {
    unset DOCKER_3XUI_COMPAT_SUB_PORT
    unset DOCKER_3XUI_COMPAT_METRICS_PORT

    if ! docker_3xui_compat_check_panel_port; then
        return 1
    fi

    if ! docker_3xui_compat_select_subscription_port; then
        return 1
    fi

    if ! docker_3xui_compat_select_metrics_port; then
        return 1
    fi

    docker_3xui_compat_show_port_plan

    return 0
}

# -----------------------------------------------------------------------------
# Subscription configuration
# -----------------------------------------------------------------------------

docker_3xui_compat_configure_subscription() {
    local DB_FILE="$1"
    local DOMAIN="$2"
    local SUB_PORT="$3"

    if [ -z "$DB_FILE" ] || [ -z "$DOMAIN" ] || [ -z "$SUB_PORT" ]; then
        echo "ERROR: Missing arguments for Subscription configuration."
        echo "Usage: docker_3xui_compat_configure_subscription DB_FILE DOMAIN PORT"
        return 1
    fi

    if [ ! -f "$DB_FILE" ]; then
        echo "ERROR: 3x-UI database was not found:"
        echo "$DB_FILE"
        return 1
    fi

    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "ERROR: sqlite3 is required for 3x-UI configuration."
        return 1
    fi

    local DOMAIN_SQL
    DOMAIN_SQL=$(printf '%s' "$DOMAIN" | sed "s/'/''/g")

    if ! sqlite3 "$DB_FILE" <<EOF
BEGIN;

DELETE FROM settings
WHERE key IN (
    'subEnable',
    'subListen',
    'subPort',
    'subPath',
    'subDomain',
    'subURI'
);

INSERT INTO settings (key, value)
VALUES ('subEnable', 'true');

INSERT INTO settings (key, value)
VALUES ('subListen', '127.0.0.1');

INSERT INTO settings (key, value)
VALUES ('subPort', '$SUB_PORT');

INSERT INTO settings (key, value)
VALUES ('subPath', '/sub/');

INSERT INTO settings (key, value)
VALUES ('subDomain', '$DOMAIN_SQL');

INSERT INTO settings (key, value)
VALUES ('subURI', 'https://$DOMAIN_SQL/$SUB_PORT/sub/');

COMMIT;
EOF
    then
        echo "ERROR: Failed to save 3x-UI Subscription settings."
        return 1
    fi

    return 0
}

docker_3xui_compat_verify_subscription() {
    local DB_FILE="$1"
    local EXPECTED_DOMAIN="$2"
    local EXPECTED_PORT="$3"

    if [ ! -f "$DB_FILE" ]; then
        echo "ERROR: 3x-UI database was not found:"
        echo "$DB_FILE"
        return 1
    fi

    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "ERROR: sqlite3 is required."
        return 1
    fi

    local ACTUAL_ENABLE
    local ACTUAL_LISTEN
    local ACTUAL_PORT
    local ACTUAL_PATH
    local ACTUAL_DOMAIN
    local ACTUAL_URI

    ACTUAL_ENABLE=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subEnable' LIMIT 1;" \
        2>/dev/null || true)

    ACTUAL_LISTEN=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subListen' LIMIT 1;" \
        2>/dev/null || true)

    ACTUAL_PORT=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subPort' LIMIT 1;" \
        2>/dev/null || true)

    ACTUAL_PATH=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subPath' LIMIT 1;" \
        2>/dev/null || true)

    ACTUAL_DOMAIN=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subDomain' LIMIT 1;" \
        2>/dev/null || true)

    ACTUAL_URI=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subURI' LIMIT 1;" \
        2>/dev/null || true)

    [ "$ACTUAL_ENABLE" = "true" ] || return 1
    [ "$ACTUAL_LISTEN" = "127.0.0.1" ] || return 1
    [ "$ACTUAL_PORT" = "$EXPECTED_PORT" ] || return 1
    [ "$ACTUAL_PATH" = "/sub/" ] || return 1
    [ "$ACTUAL_DOMAIN" = "$EXPECTED_DOMAIN" ] || return 1
    [ "$ACTUAL_URI" = "https://$EXPECTED_DOMAIN/$EXPECTED_PORT/sub/" ] || return 1

    return 0
}

# -----------------------------------------------------------------------------
# Xray Metrics configuration
# -----------------------------------------------------------------------------
# 3x-UI stores its Xray template in the xrayTemplateConfig setting.
# We update only the metrics.listen value and preserve the rest of the template.
#
# This is intentionally conservative:
# - No other Xray template fields are changed.
# - No existing PRO database is touched.
# -----------------------------------------------------------------------------

docker_3xui_compat_configure_metrics() {
    local DB_FILE="$1"
    local METRICS_PORT="$2"

    if [ -z "$DB_FILE" ] || [ -z "$METRICS_PORT" ]; then
        echo "ERROR: Missing arguments for Metrics configuration."
        echo "Usage: docker_3xui_compat_configure_metrics DB_FILE PORT"
        return 1
    fi

    if [ ! -f "$DB_FILE" ]; then
        echo "ERROR: 3x-UI database was not found:"
        echo "$DB_FILE"
        return 1
    fi

    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "ERROR: sqlite3 is required for Xray Metrics configuration."
        return 1
    fi

    if ! command -v jq >/dev/null 2>&1; then
        echo "ERROR: jq is required for Xray Metrics configuration."
        return 1
    fi

    local CURRENT_TEMPLATE
    local UPDATED_TEMPLATE
    local ESCAPED_TEMPLATE

    CURRENT_TEMPLATE=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='xrayTemplateConfig' LIMIT 1;" \
        2>/dev/null || true)

    # On a fresh Sanaei 3x-UI installation, xrayTemplateConfig is not
    # necessarily stored in the database. The official panel keeps the
    # factory template embedded in the /app/x-ui binary and exposes it via
    # the authenticated getDefaultJsonConfig API.
    #
    # The installer has no authenticated panel session yet, so the helper
    # uses the official factory template shipped with the Sanaei panel and
    # changes only metrics.listen. This preserves the expected API, routing,
    # outbound, policy, and metrics defaults on a fresh installation.
    if [ -z "$CURRENT_TEMPLATE" ]; then
        CURRENT_TEMPLATE='{
  "api": {
    "services": [
      "HandlerService",
      "LoggerService",
      "StatsService",
      "RoutingService"
    ],
    "tag": "api"
  },
  "inbounds": [{
    "listen": "127.0.0.1",
    "port": 62789,
    "protocol": "tunnel",
    "settings": {
      "rewriteAddress": "127.0.0.1"
    },
    "tag": "api"
  }],
  "log": {
    "access": "none",
    "dnsLog": false,
    "error": "",
    "loglevel": "warning",
    "maskAddress": ""
  },
  "metrics": {
    "listen": "127.0.0.1:11111",
    "tag": "metrics_out"
  },
  "outbounds": [{
      "protocol": "freedom",
      "settings": {
        "domainStrategy": "AsIs",
        "finalRules": [
          { "action": "block", "ip": ["geoip:private"] },
          { "action": "allow" }
        ]
      },
      "tag": "direct"
    },
    {
      "protocol": "blackhole",
      "settings": {},
      "tag": "blocked"
    }
  ],
  "policy": {
    "levels": {
      "0": {
        "statsUserDownlink": true,
        "statsUserUplink": true
      }
    },
    "system": {
      "statsInboundDownlink": true,
      "statsInboundUplink": true,
      "statsOutboundDownlink": false,
      "statsOutboundUplink": false
    }
  },
  "routing": {
    "domainStrategy": "AsIs",
    "rules": [{
        "inboundTag": [
          "api"
        ],
        "outboundTag": "api",
        "type": "field"
      },
      {
        "ip": [
          "geoip:private"
        ],
        "outboundTag": "blocked",
        "type": "field"
      },
      {
        "outboundTag": "blocked",
        "protocol": [
          "bittorrent"
        ],
        "type": "field"
      }
    ]
  },
  "stats": {}
}'
    fi

    if ! printf '%s\n' "$CURRENT_TEMPLATE" | jq empty >/dev/null 2>&1; then
        echo "ERROR: Existing xrayTemplateConfig is not valid JSON."
        return 1
    fi

    UPDATED_TEMPLATE=$(
        printf '%s\n' "$CURRENT_TEMPLATE" |
            jq --arg listen "127.0.0.1:$METRICS_PORT" \
                '.metrics = (.metrics // {})
                 | .metrics.listen = $listen
                 | .metrics.tag = (.metrics.tag // "metrics_out")'
    )

    if [ -z "$UPDATED_TEMPLATE" ]; then
        echo "ERROR: Failed to generate the updated Xray template."
        return 1
    fi

    if ! printf '%s\n' "$UPDATED_TEMPLATE" | jq empty >/dev/null 2>&1; then
        echo "ERROR: Generated xrayTemplateConfig is invalid JSON."
        return 1
    fi

    ESCAPED_TEMPLATE=$(printf '%s' "$UPDATED_TEMPLATE" | sed "s/'/''/g")

    if ! sqlite3 "$DB_FILE" <<EOF
BEGIN;

DELETE FROM settings
WHERE key = 'xrayTemplateConfig';

INSERT INTO settings (key, value)
VALUES ('xrayTemplateConfig', '$ESCAPED_TEMPLATE');

COMMIT;
EOF
    then
        echo "ERROR: Failed to save the updated Xray template."
        return 1
    fi

    return 0
}

docker_3xui_compat_get_metrics_port() {
    local DB_FILE="$1"

    if [ ! -f "$DB_FILE" ] ||
       ! command -v sqlite3 >/dev/null 2>&1 ||
       ! command -v jq >/dev/null 2>&1; then
        return 1
    fi

    sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='xrayTemplateConfig' LIMIT 1;" \
        2>/dev/null |
        jq -r '.metrics.listen // empty' 2>/dev/null |
        sed -n 's/.*://p' |
        head -n 1
}

# -----------------------------------------------------------------------------
# Final compatibility configuration
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# Xray API configuration
# -----------------------------------------------------------------------------

docker_3xui_compat_configure_api() {
    local DB_FILE="$1"
    local API_PORT="$2"

    if [ -z "$DB_FILE" ] || [ -z "$API_PORT" ]; then
        echo "ERROR: Missing arguments for Xray API configuration."
        echo "Usage: docker_3xui_compat_configure_api DB_FILE PORT"
        return 1
    fi

    if [ ! -f "$DB_FILE" ]; then
        echo "ERROR: 3x-UI database was not found:"
        echo "$DB_FILE"
        return 1
    fi

    if ! [[ "$API_PORT" =~ ^[0-9]+$ ]] ||
       (( API_PORT < 1 || API_PORT > 65535 )); then
        echo "ERROR: Invalid Xray API port: $API_PORT"
        return 1
    fi

    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "ERROR: sqlite3 is required for Xray API configuration."
        return 1
    fi

    if ! command -v jq >/dev/null 2>&1; then
        echo "ERROR: jq is required for Xray API configuration."
        return 1
    fi

    local CURRENT_TEMPLATE
    local UPDATED_TEMPLATE
    local ESCAPED_TEMPLATE

    CURRENT_TEMPLATE=$(
        sqlite3 "$DB_FILE" \
            "SELECT value FROM settings WHERE key='xrayTemplateConfig' LIMIT 1;" \
            2>/dev/null || true
    )

    # Fresh Sanaei installations may not have xrayTemplateConfig yet.
    # Use the same factory-compatible template already used by the
    # Metrics compatibility helper.
    if [ -z "$CURRENT_TEMPLATE" ]; then
        CURRENT_TEMPLATE='{
  "api": {
    "services": [
      "HandlerService",
      "LoggerService",
      "StatsService",
      "RoutingService"
    ],
    "tag": "api"
  },
  "inbounds": [{
    "listen": "127.0.0.1",
    "port": 62789,
    "protocol": "tunnel",
    "settings": {
      "rewriteAddress": "127.0.0.1"
    },
    "tag": "api"
  }],
  "log": {
    "access": "none",
    "dnsLog": false,
    "error": "",
    "loglevel": "warning",
    "maskAddress": ""
  },
  "metrics": {
    "listen": "127.0.0.1:11111",
    "tag": "metrics_out"
  },
  "outbounds": [{
      "protocol": "freedom",
      "settings": {
        "domainStrategy": "AsIs",
        "finalRules": [
          { "action": "block", "ip": ["geoip:private"] },
          { "action": "allow" }
        ]
      },
      "tag": "direct"
    },
    {
      "protocol": "blackhole",
      "settings": {},
      "tag": "blocked"
    }
  ],
  "policy": {
    "levels": {
      "0": {
        "statsUserDownlink": true,
        "statsUserUplink": true
      }
    }
  },
  "routing": {
    "domainStrategy": "AsIs",
    "rules": [
      {
        "inboundTag": [
          "api"
        ],
        "outboundTag": "api",
        "type": "field"
      },
      {
        "outboundTag": "blocked",
        "protocol": [
          "bittorrent"
        ],
        "type": "field"
      }
    ]
  },
  "stats": {}
}'
    fi

    if ! printf '%s\n' "$CURRENT_TEMPLATE" | jq empty >/dev/null 2>&1; then
        echo "ERROR: Existing xrayTemplateConfig is not valid JSON."
        return 1
    fi

    UPDATED_TEMPLATE=$(
        printf '%s\n' "$CURRENT_TEMPLATE" |
            jq --argjson api_port "$API_PORT" '
                if any(.inbounds[]?; .tag == "api")
                then
                    .inbounds |= map(
                        if .tag == "api"
                        then
                            .listen = (.listen // "127.0.0.1")
                            | .port = $api_port
                        else
                            .
                        end
                    )
                else
                    .inbounds += [{
                        "listen": "127.0.0.1",
                        "port": $api_port,
                        "protocol": "tunnel",
                        "settings": {
                            "rewriteAddress": "127.0.0.1"
                        },
                        "tag": "api"
                    }]
                end
            '
    )

    if [ -z "$UPDATED_TEMPLATE" ]; then
        echo "ERROR: Failed to generate the updated Xray API template."
        return 1
    fi

    if ! printf '%s\n' "$UPDATED_TEMPLATE" | jq empty >/dev/null 2>&1; then
        echo "ERROR: Generated Xray API template is invalid JSON."
        return 1
    fi

    ESCAPED_TEMPLATE=$(printf '%s' "$UPDATED_TEMPLATE" | sed "s/'/''/g")

    if ! sqlite3 "$DB_FILE" <<EOF
BEGIN;

DELETE FROM settings
WHERE key = 'xrayTemplateConfig';

INSERT INTO settings (key, value)
VALUES ('xrayTemplateConfig', '$ESCAPED_TEMPLATE');

COMMIT;
EOF
    then
        echo "ERROR: Failed to save the updated Xray API template."
        return 1
    fi

    return 0
}

docker_3xui_compat_get_api_port() {
    local DB_FILE="$1"

    if [ ! -f "$DB_FILE" ] ||
       ! command -v sqlite3 >/dev/null 2>&1 ||
       ! command -v jq >/dev/null 2>&1; then
        return 1
    fi

    sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='xrayTemplateConfig' LIMIT 1;" \
        2>/dev/null |
        jq -r '
            .inbounds[]?
            | select(.tag == "api")
            | .port
        ' 2>/dev/null |
        head -n 1
}

docker_3xui_compat_verify_api() {
    local DB_FILE="$1"
    local EXPECTED_PORT="$2"
    local ACTUAL_PORT

    if [ -z "$DB_FILE" ] || [ -z "$EXPECTED_PORT" ]; then
        echo "ERROR: Missing arguments for Xray API verification."
        echo "Usage: docker_3xui_compat_verify_api DB_FILE PORT"
        return 1
    fi

    ACTUAL_PORT="$(docker_3xui_compat_get_api_port "$DB_FILE" || true)"

    if [ "$ACTUAL_PORT" != "$EXPECTED_PORT" ]; then
        echo "ERROR: Xray API configuration verification failed."
        echo "Expected: 127.0.0.1:$EXPECTED_PORT"
        echo "Detected : ${ACTUAL_PORT:-Not detected}"
        return 1
    fi

    return 0
}


docker_3xui_compat_configure_panel() {
    local DB_FILE="$1"
    local PORT="$2"

    if [ -z "$DB_FILE" ] || [ -z "$PORT" ]; then
        echo "ERROR: Missing arguments for panel configuration."
        echo "Usage: docker_3xui_compat_configure_panel DB_FILE PORT"
        return 1
    fi

    if [ ! -f "$DB_FILE" ]; then
        echo "ERROR: X-UI database not found: $DB_FILE"
        return 1
    fi

    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "ERROR: sqlite3 is required."
        return 1
    fi

    if ! sqlite3 "$DB_FILE" <<SQL
BEGIN;
DELETE FROM settings WHERE key='webPort';
INSERT INTO settings(key,value) VALUES ('webPort','$PORT');
COMMIT;
SQL
    then
        echo "ERROR: Failed to configure panel webPort."
        return 1
    fi

    return 0
}


docker_3xui_compat_verify_panel() {
    local DB_FILE="$1"
    local EXPECTED_PORT="$2"
    local ACTUAL_PORT

    if [ -z "$DB_FILE" ] || [ -z "$EXPECTED_PORT" ]; then
        echo "ERROR: Missing arguments for panel verification."
        echo "Usage: docker_3xui_compat_verify_panel DB_FILE PORT"
        return 1
    fi

    ACTUAL_PORT="$(
        sqlite3 "$DB_FILE" \
            "SELECT value FROM settings WHERE key='webPort' LIMIT 1;" \
            2>/dev/null || true
    )"

    if [ "$ACTUAL_PORT" != "$EXPECTED_PORT" ]; then
        echo "ERROR: Panel port configuration verification failed."
        echo "Expected: $EXPECTED_PORT"
        echo "Detected : ${ACTUAL_PORT:-Not detected}"
        return 1
    fi

    return 0
}

# -----------------------------------------------------------------------------
# Web Base Path configuration
# -----------------------------------------------------------------------------
# Sanaei manages Web Base Path through the official x-ui setting command.
# Do not modify the SQLite database directly for this setting.
# -----------------------------------------------------------------------------

docker_3xui_compat_configure_web_base_path() {
    local CONTAINER="$1"
    local BASE_PATH="$2"

    if [ -z "$CONTAINER" ] || [ -z "$BASE_PATH" ]; then
        echo "ERROR: Missing arguments for Web Base Path configuration."
        echo "Usage: docker_3xui_compat_configure_web_base_path CONTAINER BASE_PATH"
        return 1
    fi

    if [ "$BASE_PATH" != "/" ] &&
       [[ ! "$BASE_PATH" =~ ^/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*/$ ]]; then
        echo "ERROR: Invalid Web Base Path: $BASE_PATH"
        return 1
    fi

    local XUI_MAIN_FOLDER=""
    local XUI_BINARY=""

    XUI_MAIN_FOLDER="$(
        docker exec "$CONTAINER" sh -c             'printf "%s" "${XUI_MAIN_FOLDER:-/app}"'             2>/dev/null || true
    )"

    if [ -z "$XUI_MAIN_FOLDER" ]; then
        XUI_MAIN_FOLDER="/app"
    fi

    XUI_BINARY="${XUI_MAIN_FOLDER%/}/x-ui"

    if ! docker exec "$CONTAINER" sh -c         '[ -x "$1" ]'         sh "$XUI_BINARY"; then
        echo "ERROR: Sanaei X-UI binary was not found or is not executable:"
        echo "$XUI_BINARY"
        return 1
    fi

    if ! docker exec "$CONTAINER" sh -c         '"$1" setting -webBasePath "$2"'         sh "$XUI_BINARY" "$BASE_PATH"; then
        echo "ERROR: Failed to configure Web Base Path in Sanaei 3x-UI."
        echo "X-UI binary:"
        echo "$XUI_BINARY"
        return 1
    fi

    return 0
}


docker_3xui_compat_verify_web_base_path() {
    local CONTAINER="$1"
    local EXPECTED_PATH="$2"
    local ACTUAL_PATH=""

    if [ -z "$CONTAINER" ] || [ -z "$EXPECTED_PATH" ]; then
        echo "ERROR: Missing arguments for Web Base Path verification."
        echo "Usage: docker_3xui_compat_verify_web_base_path CONTAINER BASE_PATH"
        return 1
    fi

    ACTUAL_PATH="$(
        docker exec "$CONTAINER" sh -c \
            'x-ui settings' 2>/dev/null |
            sed -n 's/^webBasePath:[[:space:]]*//p' |
            sed $'s/\033\\[[0-9;]*[[:alpha:]]//g' |
            sed 's/[[:space:]]*$//' |
            head -n 1
    )"

    if [ "$ACTUAL_PATH" != "$EXPECTED_PATH" ]; then
        echo "ERROR: Web Base Path configuration verification failed."
        echo "Expected: $EXPECTED_PATH"
        echo "Detected : ${ACTUAL_PATH:-Not detected}"
        return 1
    fi

    return 0
}


docker_3xui_compat_configure() {
    local DB_FILE="$1"
    local DOMAIN="$2"
    local WEB_BASE_PATH="${3:-/}"
    local CONTAINER="${4:-${DOCKER_3XUI_CONTAINER:-}}"

    if [ -z "$DB_FILE" ] || [ -z "$DOMAIN" ] ||
       [ -z "$WEB_BASE_PATH" ] || [ -z "$CONTAINER" ]; then
        echo "ERROR: Missing arguments."
        echo "Usage: docker_3xui_compat_configure DB_FILE DOMAIN WEB_BASE_PATH CONTAINER"
        return 1
    fi

    if [ -z "${DOCKER_3XUI_COMPAT_SUB_PORT:-}" ] ||
       [ -z "${DOCKER_3XUI_COMPAT_METRICS_PORT:-}" ]; then

        if ! docker_3xui_compat_prepare_ports; then
            return 1
        fi
    fi

    if [ -z "${DOCKER_3XUI_COMPAT_API_PORT:-}" ]; then
        echo "ERROR: Xray API port was not supplied."
        echo "Set DOCKER_3XUI_COMPAT_API_PORT before calling configure()."
        return 1
    fi

    echo
    echo "Applying 3x-UI compatibility settings..."
    echo

    if [ -z "${DOCKER_3XUI_COMPAT_PANEL_PORT:-}" ]; then
        echo "ERROR: Panel port was not supplied."
        echo "Set DOCKER_3XUI_COMPAT_PANEL_PORT before calling configure()."
        return 1
    fi

    echo "Panel:"
    echo "  Listen        : 127.0.0.1:$DOCKER_3XUI_COMPAT_PANEL_PORT"
    echo

    if ! docker_3xui_compat_configure_panel         "$DB_FILE"         "$DOCKER_3XUI_COMPAT_PANEL_PORT"; then

        echo "ERROR: Panel webPort configuration failed."
        return 1
    fi

    echo "Web Base Path:"
    echo "  Path          : $WEB_BASE_PATH"
    echo

    if ! docker_3xui_compat_configure_web_base_path \
        "$CONTAINER" \
        "$WEB_BASE_PATH"; then

        echo "ERROR: Web Base Path configuration failed."
        return 1
    fi

    echo "Xray API:"
    echo "  Listen        : 127.0.0.1:$DOCKER_3XUI_COMPAT_API_PORT"
    echo

    if ! docker_3xui_compat_configure_api \
        "$DB_FILE" \
        "$DOCKER_3XUI_COMPAT_API_PORT"; then

        echo "ERROR: Xray API configuration failed."
        return 1
    fi

    echo "Subscription:"
    echo "  Listen Domain : $DOMAIN"
    echo "  Listen IP     : 127.0.0.1"
    echo "  Port          : $DOCKER_3XUI_COMPAT_SUB_PORT"
    echo "  Path          : /sub/"
    echo "  Public URI    : https://$DOMAIN/$DOCKER_3XUI_COMPAT_SUB_PORT/sub/"
    echo

    if ! docker_3xui_compat_configure_subscription \
        "$DB_FILE" \
        "$DOMAIN" \
        "$DOCKER_3XUI_COMPAT_SUB_PORT"; then

        echo "ERROR: Subscription configuration failed."
        return 1
    fi

    echo "Xray Metrics:"
    echo "  Listen        : 127.0.0.1:$DOCKER_3XUI_COMPAT_METRICS_PORT"
    echo

    if ! docker_3xui_compat_configure_metrics \
        "$DB_FILE" \
        "$DOCKER_3XUI_COMPAT_METRICS_PORT"; then

        echo "ERROR: Metrics configuration failed."
        return 1
    fi

    if ! docker_3xui_compat_verify_panel \
        "$DB_FILE" \
        "$DOCKER_3XUI_COMPAT_PANEL_PORT"; then

        echo "ERROR: Panel configuration verification failed."
        return 1
    fi

    if ! docker_3xui_compat_verify_web_base_path \
        "$CONTAINER" \
        "$WEB_BASE_PATH"; then

        return 1
    fi

    if ! docker_3xui_compat_verify_api \
        "$DB_FILE" \
        "$DOCKER_3XUI_COMPAT_API_PORT"; then

        return 1
    fi

    if ! docker_3xui_compat_verify_subscription \
        "$DB_FILE" \
        "$DOMAIN" \
        "$DOCKER_3XUI_COMPAT_SUB_PORT"; then

        echo "ERROR: Subscription configuration verification failed."
        return 1
    fi

    echo
    echo "======================================"
    echo "   3x-UI Compatibility Configuration"
    echo "             Successful"
    echo "======================================"
    echo

    echo "Panel Port       : $DOCKER_3XUI_COMPAT_PANEL_PORT"
    echo "Web Base Path    : $WEB_BASE_PATH"
    echo "Xray API Port    : $DOCKER_3XUI_COMPAT_API_PORT"
    echo "Subscription     : $DOCKER_3XUI_COMPAT_SUB_PORT"
    echo "Metrics          : $DOCKER_3XUI_COMPAT_METRICS_PORT"
    echo "Subscription URI : https://$DOMAIN/$DOCKER_3XUI_COMPAT_SUB_PORT/sub/"
    echo

    return 0
}
