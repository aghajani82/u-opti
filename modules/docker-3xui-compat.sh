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
#   Subscription : prefer 2096, fallback to 2095
#   Metrics      : prefer 11111, fallback to 11112
#
# Subscription is kept on localhost and published through Nginx :443.
# Xray metrics are kept on localhost.
#
# These are library functions only. Nothing runs automatically when sourced.
# -----------------------------------------------------------------------------

DOCKER_3XUI_COMPAT_PANEL_PORT="2053"

DOCKER_3XUI_COMPAT_SUB_PRIMARY="2096"
DOCKER_3XUI_COMPAT_SUB_FALLBACK="2095"

DOCKER_3XUI_COMPAT_METRICS_PRIMARY="11111"
DOCKER_3XUI_COMPAT_METRICS_FALLBACK="11112"

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
    local PRIMARY="$DOCKER_3XUI_COMPAT_SUB_PRIMARY"
    local FALLBACK="$DOCKER_3XUI_COMPAT_SUB_FALLBACK"

    if ! docker_3xui_compat_port_is_in_use "$PRIMARY"; then
        DOCKER_3XUI_COMPAT_SUB_PORT="$PRIMARY"
        return 0
    fi

    if ! docker_3xui_compat_port_is_in_use "$FALLBACK"; then
        DOCKER_3XUI_COMPAT_SUB_PORT="$FALLBACK"
        return 0
    fi

    echo
    echo "ERROR: Both preferred 3x-UI Subscription ports are in use:"
    echo "  - $PRIMARY/tcp"
    echo "  - $FALLBACK/tcp"
    echo
    echo "U-OPTI will not change an existing service port automatically."
    return 1
}

docker_3xui_compat_select_metrics_port() {
    local PRIMARY="$DOCKER_3XUI_COMPAT_METRICS_PRIMARY"
    local FALLBACK="$DOCKER_3XUI_COMPAT_METRICS_FALLBACK"

    if ! docker_3xui_compat_port_is_in_use "$PRIMARY"; then
        DOCKER_3XUI_COMPAT_METRICS_PORT="$PRIMARY"
        return 0
    fi

    if ! docker_3xui_compat_port_is_in_use "$FALLBACK"; then
        DOCKER_3XUI_COMPAT_METRICS_PORT="$FALLBACK"
        return 0
    fi

    echo
    echo "ERROR: Both preferred Xray Metrics ports are in use:"
    echo "  - $PRIMARY/tcp"
    echo "  - $FALLBACK/tcp"
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

    sqlite3 "$DB_FILE" <<EOF
BEGIN;

INSERT OR REPLACE INTO settings (key, value)
VALUES ('subEnable', 'true');

INSERT OR REPLACE INTO settings (key, value)
VALUES ('subListen', '127.0.0.1');

INSERT OR REPLACE INTO settings (key, value)
VALUES ('subPort', '$SUB_PORT');

INSERT OR REPLACE INTO settings (key, value)
VALUES ('subPath', '/sub/');

INSERT OR REPLACE INTO settings (key, value)
VALUES ('subDomain', '$DOMAIN');

INSERT OR REPLACE INTO settings (key, value)
VALUES ('subURI', 'https://$DOMAIN/$SUB_PORT/sub/');

COMMIT;
EOF

    if [ "$?" -ne 0 ]; then
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
        "SELECT value FROM settings WHERE key='subEnable' LIMIT 1;" 2>/dev/null || true)

    ACTUAL_LISTEN=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subListen' LIMIT 1;" 2>/dev/null || true)

    ACTUAL_PORT=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subPort' LIMIT 1;" 2>/dev/null || true)

    ACTUAL_PATH=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subPath' LIMIT 1;" 2>/dev/null || true)

    ACTUAL_DOMAIN=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subDomain' LIMIT 1;" 2>/dev/null || true)

    ACTUAL_URI=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='subURI' LIMIT 1;" 2>/dev/null || true)

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
    local TEMP_FILE

    CURRENT_TEMPLATE=$(sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='xrayTemplateConfig' LIMIT 1;" \
        2>/dev/null || true)

    if [ -z "$CURRENT_TEMPLATE" ]; then
        echo "ERROR: xrayTemplateConfig was not found in the 3x-UI database."
        return 1
    fi

    if ! printf '%s\n' "$CURRENT_TEMPLATE" | jq empty >/dev/null 2>&1; then
        echo "ERROR: Existing xrayTemplateConfig is not valid JSON."
        return 1
    fi

    UPDATED_TEMPLATE=$(printf '%s\n' "$CURRENT_TEMPLATE" |
        jq --arg listen "127.0.0.1:$METRICS_PORT" \
            '.metrics = (.metrics // {}) | .metrics.listen = $listen | .metrics.tag = (.metrics.tag // "metrics_out")'
    )

    if [ -z "$UPDATED_TEMPLATE" ]; then
        echo "ERROR: Failed to generate the updated Xray template."
        return 1
    fi

    TEMP_FILE=$(mktemp)

    printf '%s\n' "$UPDATED_TEMPLATE" > "$TEMP_FILE"

    if ! sqlite3 "$DB_FILE" \
        "UPDATE settings SET value=$(printf '%s' "$UPDATED_TEMPLATE" | sqlite3 "$DB_FILE" '.quote' 2>/dev/null) WHERE key='xrayTemplateConfig';" \
        >/dev/null 2>&1; then

        # Fallback to a safer temporary SQL file when shell quoting is rejected.
        if ! sqlite3 "$DB_FILE" <<EOF
UPDATE settings
SET value = '$(printf '%s' "$UPDATED_TEMPLATE" | sed "s/'/''/g")'
WHERE key = 'xrayTemplateConfig';
EOF
        then
            rm -f "$TEMP_FILE"
            echo "ERROR: Failed to save the updated Xray template."
            return 1
        fi
    fi

    rm -f "$TEMP_FILE"

    return 0
}

docker_3xui_compat_get_metrics_port() {
    local DB_FILE="$1"

    if [ ! -f "$DB_FILE" ] || ! command -v sqlite3 >/dev/null 2>&1; then
        return 1
    fi

    sqlite3 "$DB_FILE" \
        "SELECT value FROM settings WHERE key='xrayTemplateConfig' LIMIT 1;" 2>/dev/null |
        jq -r '.metrics.listen // empty' 2>/dev/null |
        sed -n 's/.*://p' |
        head -n 1
}

# -----------------------------------------------------------------------------
# Final compatibility configuration
# -----------------------------------------------------------------------------

docker_3xui_compat_configure() {
    local DB_FILE="$1"
    local DOMAIN="$2"

    if [ -z "$DB_FILE" ] || [ -z "$DOMAIN" ]; then
        echo "ERROR: Missing arguments."
        echo "Usage: docker_3xui_compat_configure DB_FILE DOMAIN"
        return 1
    fi

    if [ -z "${DOCKER_3XUI_COMPAT_SUB_PORT:-}" ] ||
       [ -z "${DOCKER_3XUI_COMPAT_METRICS_PORT:-}" ]; then

        if ! docker_3xui_compat_prepare_ports; then
            return 1
        fi
    fi

    echo
    echo "Applying 3x-UI compatibility settings..."
    echo

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
    echo "Subscription     : $DOCKER_3XUI_COMPAT_SUB_PORT"
    echo "Metrics          : $DOCKER_3XUI_COMPAT_METRICS_PORT"
    echo "Subscription URI : https://$DOMAIN/$DOCKER_3XUI_COMPAT_SUB_PORT/sub/"
    echo

    return 0
}
