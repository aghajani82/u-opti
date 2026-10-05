#!/usr/bin/env bash

# U-OPTI - 3x-UI Docker Multi-Instance Certificate Sync
# Experimental feature module for v0.15.1+
#
# Purpose:
# - Reuse an existing Let's Encrypt certificate for a registered 3x-UI instance.
# - Copy certificate material into that instance's existing /root/cert bind mount.
# - Keep the copy synchronized after Certbot renewal with a per-instance deploy hook.
# - Verify that the certificate remains private to the selected instance/container.
#
# This module intentionally does not issue certificates in Multi-Instance mode.
# The 3x-UI Nginx/SSL workflow is responsible for certificate issuance.

DOCKER_3XUI_MULTI_CERT_CONTAINER_DIR="/root/cert"
DOCKER_3XUI_MULTI_CERT_HOOK_DIR="/etc/letsencrypt/renewal-hooks/deploy"
DOCKER_3XUI_MULTI_CERT_HOOK_PREFIX="u-opti-3xui-instance-"


docker_3xui_multi_cert_pause() {
    echo
    read -r -p "Press Enter to return..." _
}


docker_3xui_multi_cert_require_environment() {
    if ! declare -F docker_3xui_instance_registered_ids >/dev/null 2>&1 ||
       ! declare -F docker_3xui_instance_load_state >/dev/null 2>&1; then
        echo "ERROR: 3x-UI Multi-Instance registry functions are not available."
        return 1
    fi

    if ! declare -F check_certbot >/dev/null 2>&1 || ! check_certbot; then
        return 1
    fi

    if ! command -v docker >/dev/null 2>&1; then
        echo "ERROR: Docker is not installed."
        return 1
    fi

    if ! command -v openssl >/dev/null 2>&1; then
        echo "ERROR: OpenSSL is required for certificate validation."
        return 1
    fi

    return 0
}


docker_3xui_multi_cert_has_instances() {
    local first=""
    first="$(docker_3xui_instance_registered_ids 2>/dev/null | head -n 1)"
    [[ -n "$first" ]]
}


docker_3xui_multi_cert_container_status() {
    local container="$1"

    if ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -Fxq "$container"; then
        printf '%s\n' "Missing"
        return 0
    fi

    if docker inspect "$container" --format '{{.State.Running}}' 2>/dev/null | grep -Fxq true; then
        printf '%s\n' "Running"
    else
        printf '%s\n' "Stopped"
    fi
}


docker_3xui_multi_cert_select_instance() {
    local ids=()
    local id
    local idx=1
    local choice=""
    local status=""

    mapfile -t ids < <(docker_3xui_instance_registered_ids 2>/dev/null)

    if [[ "${#ids[@]}" -eq 0 ]]; then
        echo "No registered 3x-UI Multi-Instance installation was found."
        return 1
    fi

    echo "Available 3x-UI Instances"
    echo "--------------------------------------"

    for id in "${ids[@]}"; do
        if ! docker_3xui_instance_load_state "$id" >/dev/null 2>&1; then
            printf '%d) %s | state error\n' "$idx" "$id"
            idx=$((idx + 1))
            continue
        fi

        status="$(docker_3xui_multi_cert_container_status "$DOCKER_3XUI_INSTANCE_CONTAINER")"
        printf '%d) %s | %s | %s | %s\n' \
            "$idx" \
            "$DOCKER_3XUI_INSTANCE_ID" \
            "${DOCKER_3XUI_INSTANCE_DOMAIN:-no-domain}" \
            "$DOCKER_3XUI_INSTANCE_CONTAINER" \
            "$status"
        idx=$((idx + 1))
    done

    echo
    read -r -p "Select instance [1-${#ids[@]}] or 0 to go back: " choice

    if [[ "$choice" == "0" ]]; then
        return 2
    fi

    if [[ ! "$choice" =~ ^[0-9]+$ ]] ||
       (( choice < 1 || choice > ${#ids[@]} )); then
        echo "ERROR: Invalid selection."
        return 1
    fi

    DOCKER_3XUI_MULTI_CERT_SELECTED_ID="${ids[$((choice - 1))]}"

    if ! docker_3xui_instance_load_state "$DOCKER_3XUI_MULTI_CERT_SELECTED_ID" >/dev/null 2>&1; then
        echo "ERROR: Selected instance state could not be loaded."
        return 1
    fi

    return 0
}


docker_3xui_multi_cert_context() {
    local instance_id="$1"

    if ! docker_3xui_instance_load_state "$instance_id" >/dev/null 2>&1; then
        return 1
    fi

    DOCKER_3XUI_MULTI_CERT_INSTANCE_ID="$DOCKER_3XUI_INSTANCE_ID"
    DOCKER_3XUI_MULTI_CERT_DOMAIN="${DOCKER_3XUI_INSTANCE_DOMAIN:-}"
    DOCKER_3XUI_MULTI_CERT_CONTAINER="$DOCKER_3XUI_INSTANCE_CONTAINER"
    DOCKER_3XUI_MULTI_CERT_HOST_DIR="$DOCKER_3XUI_INSTANCE_DIR/cert"
    DOCKER_3XUI_MULTI_CERT_SOURCE_DIR="/etc/letsencrypt/live/$DOCKER_3XUI_MULTI_CERT_DOMAIN"
    DOCKER_3XUI_MULTI_CERT_SOURCE_CERT="$DOCKER_3XUI_MULTI_CERT_SOURCE_DIR/fullchain.pem"
    DOCKER_3XUI_MULTI_CERT_SOURCE_KEY="$DOCKER_3XUI_MULTI_CERT_SOURCE_DIR/privkey.pem"
    DOCKER_3XUI_MULTI_CERT_TARGET_CERT="$DOCKER_3XUI_MULTI_CERT_HOST_DIR/fullchain.pem"
    DOCKER_3XUI_MULTI_CERT_TARGET_KEY="$DOCKER_3XUI_MULTI_CERT_HOST_DIR/privkey.pem"
    DOCKER_3XUI_MULTI_CERT_HOOK_PATH="${DOCKER_3XUI_MULTI_CERT_HOOK_DIR}/${DOCKER_3XUI_MULTI_CERT_HOOK_PREFIX}${DOCKER_3XUI_MULTI_CERT_INSTANCE_ID}-${DOCKER_3XUI_MULTI_CERT_DOMAIN}.sh"

    [[ -n "$DOCKER_3XUI_MULTI_CERT_DOMAIN" ]] || {
        echo "ERROR: Instance $instance_id has no domain in its state."
        return 1
    }

    if declare -F validate_domain >/dev/null 2>&1 &&
       ! validate_domain "$DOCKER_3XUI_MULTI_CERT_DOMAIN"; then
        echo "ERROR: Invalid domain in Instance state: $DOCKER_3XUI_MULTI_CERT_DOMAIN"
        return 1
    fi

    return 0
}


docker_3xui_multi_cert_check_mount() {
    local mount_source=""
    local expected=""
    local actual=""

    if ! docker ps -a --format '{{.Names}}' 2>/dev/null |
        grep -Fxq "$DOCKER_3XUI_MULTI_CERT_CONTAINER"; then
        echo "ERROR: Container was not found: $DOCKER_3XUI_MULTI_CERT_CONTAINER"
        return 1
    fi

    mount_source="$(
        docker inspect "$DOCKER_3XUI_MULTI_CERT_CONTAINER" \
            --format '{{range .Mounts}}{{if eq .Destination "/root/cert"}}{{println .Source}}{{end}}{{end}}' \
            2>/dev/null | head -n 1
    )"

    if [[ -z "$mount_source" ]]; then
        echo "ERROR: The selected container does not expose /root/cert."
        return 1
    fi

    expected="$(readlink -m "$DOCKER_3XUI_MULTI_CERT_HOST_DIR")"
    actual="$(readlink -m "$mount_source")"

    if [[ "$actual" != "$expected" ]]; then
        echo "ERROR: Certificate mount does not match the selected Instance."
        echo "Expected: $expected -> $DOCKER_3XUI_MULTI_CERT_CONTAINER_DIR"
        echo "Actual  : $actual -> $DOCKER_3XUI_MULTI_CERT_CONTAINER_DIR"
        return 1
    fi

    return 0
}


docker_3xui_multi_cert_public_key_fingerprint() {
    local cert_or_key="$1"
    local type="$2"

    case "$type" in
        cert)
            openssl x509 -in "$cert_or_key" -pubkey -noout 2>/dev/null |
                openssl pkey -pubin -outform DER 2>/dev/null |
                sha256sum | awk '{print $1}'
            ;;
        key)
            openssl pkey -in "$cert_or_key" -pubout -outform DER 2>/dev/null |
                sha256sum | awk '{print $1}'
            ;;
        *)
            return 1
            ;;
    esac
}


docker_3xui_multi_cert_validate_pair() {
    local cert="$1"
    local key="$2"
    local domain="$3"
    local cert_fp=""
    local key_fp=""

    [[ -f "$cert" && -f "$key" ]] || return 1

    if ! openssl x509 -in "$cert" -noout >/dev/null 2>&1; then
        echo "ERROR: Invalid certificate file: $cert"
        return 1
    fi

    if ! openssl pkey -in "$key" -noout >/dev/null 2>&1; then
        echo "ERROR: Invalid private key file: $key"
        return 1
    fi

    if ! openssl x509 -in "$cert" -noout -checkhost "$domain" >/dev/null 2>&1; then
        echo "ERROR: Certificate does not validate for domain: $domain"
        return 1
    fi

    cert_fp="$(docker_3xui_multi_cert_public_key_fingerprint "$cert" cert)"
    key_fp="$(docker_3xui_multi_cert_public_key_fingerprint "$key" key)"

    if [[ -z "$cert_fp" || -z "$key_fp" || "$cert_fp" != "$key_fp" ]]; then
        echo "ERROR: Certificate and private key do not match."
        return 1
    fi

    return 0
}


docker_3xui_multi_cert_copy_atomic() {
    local tmp_cert=""
    local tmp_key=""

    mkdir -p "$DOCKER_3XUI_MULTI_CERT_HOST_DIR" || return 1
    chmod 755 "$DOCKER_3XUI_MULTI_CERT_HOST_DIR" || return 1

    tmp_cert="$DOCKER_3XUI_MULTI_CERT_HOST_DIR/.fullchain.pem.new.$$"
    tmp_key="$DOCKER_3XUI_MULTI_CERT_HOST_DIR/.privkey.pem.new.$$"

    rm -f "$tmp_cert" "$tmp_key"

    if ! install -m 0644 "$DOCKER_3XUI_MULTI_CERT_SOURCE_CERT" "$tmp_cert"; then
        rm -f "$tmp_cert" "$tmp_key"
        return 1
    fi

    if ! install -m 0600 "$DOCKER_3XUI_MULTI_CERT_SOURCE_KEY" "$tmp_key"; then
        rm -f "$tmp_cert" "$tmp_key"
        return 1
    fi

    chown root:root "$tmp_cert" "$tmp_key" || {
        rm -f "$tmp_cert" "$tmp_key"
        return 1
    }

    if ! docker_3xui_multi_cert_validate_pair \
        "$tmp_cert" "$tmp_key" "$DOCKER_3XUI_MULTI_CERT_DOMAIN"; then
        rm -f "$tmp_cert" "$tmp_key"
        return 1
    fi

    mv -f "$tmp_cert" "$DOCKER_3XUI_MULTI_CERT_TARGET_CERT" || {
        rm -f "$tmp_cert" "$tmp_key"
        return 1
    }

    mv -f "$tmp_key" "$DOCKER_3XUI_MULTI_CERT_TARGET_KEY" || {
        rm -f "$tmp_key"
        return 1
    }

    return 0
}


docker_3xui_multi_cert_install_hook() {
    local hook="$DOCKER_3XUI_MULTI_CERT_HOOK_PATH"

    mkdir -p "$DOCKER_3XUI_MULTI_CERT_HOOK_DIR" || return 1

    cat > "$hook" <<EOF_HOOK
#!/usr/bin/env bash
set -euo pipefail

SELECTED_DOMAIN="$DOCKER_3XUI_MULTI_CERT_DOMAIN"
CONTAINER="$DOCKER_3XUI_MULTI_CERT_CONTAINER"
TARGET_DIR="$DOCKER_3XUI_MULTI_CERT_HOST_DIR"
SOURCE_DIR="/etc/letsencrypt/live/\$SELECTED_DOMAIN"

if [[ "\${RENEWED_LINEAGE:-}" != "\$SOURCE_DIR" ]]; then
    case " \${RENEWED_DOMAINS:-} " in
        *" \$SELECTED_DOMAIN "*) ;;
        *) exit 0 ;;
    esac
fi

[[ -f "\$SOURCE_DIR/fullchain.pem" && -f "\$SOURCE_DIR/privkey.pem" ]] || exit 1
[[ -d "\$TARGET_DIR" ]] || mkdir -p "\$TARGET_DIR"
chmod 755 "\$TARGET_DIR"

TMP_CERT="\$TARGET_DIR/.fullchain.pem.new.\$\$"
TMP_KEY="\$TARGET_DIR/.privkey.pem.new.\$\$"
trap 'rm -f "\$TMP_CERT" "\$TMP_KEY"' EXIT

install -m 0644 "\$SOURCE_DIR/fullchain.pem" "\$TMP_CERT"
install -m 0600 "\$SOURCE_DIR/privkey.pem" "\$TMP_KEY"
chown root:root "\$TMP_CERT" "\$TMP_KEY"
mv -f "\$TMP_CERT" "\$TARGET_DIR/fullchain.pem"
mv -f "\$TMP_KEY" "\$TARGET_DIR/privkey.pem"
trap - EXIT

if command -v docker >/dev/null 2>&1 &&
   docker ps --format '{{.Names}}' 2>/dev/null | grep -Fxq "\$CONTAINER"; then
    docker restart "\$CONTAINER" >/dev/null 2>&1 || true
fi

exit 0
EOF_HOOK

    chmod 700 "$hook" || return 1

    if ! bash -n "$hook" >/dev/null 2>&1; then
        echo "ERROR: Generated Certbot deploy hook failed Bash syntax validation."
        rm -f "$hook"
        return 1
    fi

    return 0
}


docker_3xui_multi_cert_verify_container_files() {
    if ! docker inspect "$DOCKER_3XUI_MULTI_CERT_CONTAINER" \
        --format '{{.State.Running}}' 2>/dev/null | grep -Fxq true; then
        echo "ERROR: Container is not running: $DOCKER_3XUI_MULTI_CERT_CONTAINER"
        return 1
    fi

    if ! docker exec "$DOCKER_3XUI_MULTI_CERT_CONTAINER" sh -lc \
        'test -r /root/cert/fullchain.pem && test -r /root/cert/privkey.pem'; then
        echo "ERROR: Certificate files are not readable inside the container."
        return 1
    fi

    if ! docker exec "$DOCKER_3XUI_MULTI_CERT_CONTAINER" \
        cat /root/cert/fullchain.pem 2>/dev/null |
        cmp -s - "$DOCKER_3XUI_MULTI_CERT_TARGET_CERT"; then
        echo "ERROR: Container certificate does not match the host Instance copy."
        return 1
    fi

    if ! docker exec "$DOCKER_3XUI_MULTI_CERT_CONTAINER" \
        cat /root/cert/privkey.pem 2>/dev/null |
        cmp -s - "$DOCKER_3XUI_MULTI_CERT_TARGET_KEY"; then
        echo "ERROR: Container private key does not match the host Instance copy."
        return 1
    fi

    return 0
}


docker_3xui_multi_cert_show_paths() {
    echo
    echo "Sanaei / Xray TLS paths for Instance $DOCKER_3XUI_MULTI_CERT_INSTANCE_ID:"
    echo
    echo "Certificate : $DOCKER_3XUI_MULTI_CERT_CONTAINER_DIR/fullchain.pem"
    echo "Private Key : $DOCKER_3XUI_MULTI_CERT_CONTAINER_DIR/privkey.pem"
    echo
    echo "Domain / SNI: $DOCKER_3XUI_MULTI_CERT_DOMAIN"
    echo "Container   : $DOCKER_3XUI_MULTI_CERT_CONTAINER"
    echo "Host copy   : $DOCKER_3XUI_MULTI_CERT_HOST_DIR"
}


docker_3xui_multi_cert_sync() {
    clear
    echo "======================================"
    echo "   3x-UI Instance Certificate Sync"
    echo "======================================"
    echo

    if ! docker_3xui_multi_cert_require_environment; then
        docker_3xui_multi_cert_pause
        return 1
    fi

    docker_3xui_multi_cert_select_instance
    case $? in
        0) ;;
        2) return 0 ;;
        *) docker_3xui_multi_cert_pause; return 1 ;;
    esac

    if ! docker_3xui_multi_cert_context "$DOCKER_3XUI_MULTI_CERT_SELECTED_ID"; then
        docker_3xui_multi_cert_pause
        return 1
    fi

    echo
    echo "Selected Instance"
    echo "--------------------------------------"
    echo "ID        : $DOCKER_3XUI_MULTI_CERT_INSTANCE_ID"
    echo "Domain    : $DOCKER_3XUI_MULTI_CERT_DOMAIN"
    echo "Container : $DOCKER_3XUI_MULTI_CERT_CONTAINER"
    echo

    if [[ ! -f "$DOCKER_3XUI_MULTI_CERT_SOURCE_CERT" ||
          ! -f "$DOCKER_3XUI_MULTI_CERT_SOURCE_KEY" ]]; then
        echo "ERROR: Existing Let's Encrypt certificate was not found."
        echo "Expected:"
        echo "$DOCKER_3XUI_MULTI_CERT_SOURCE_CERT"
        echo "$DOCKER_3XUI_MULTI_CERT_SOURCE_KEY"
        echo
        echo "Configure Nginx / SSL for this 3x-UI Instance first."
        docker_3xui_multi_cert_pause
        return 1
    fi

    if ! docker_3xui_multi_cert_validate_pair \
        "$DOCKER_3XUI_MULTI_CERT_SOURCE_CERT" \
        "$DOCKER_3XUI_MULTI_CERT_SOURCE_KEY" \
        "$DOCKER_3XUI_MULTI_CERT_DOMAIN"; then
        docker_3xui_multi_cert_pause
        return 1
    fi

    if ! docker_3xui_multi_cert_check_mount; then
        docker_3xui_multi_cert_pause
        return 1
    fi

    echo "U-OPTI will:"
    echo "  1. Reuse the existing Let's Encrypt certificate."
    echo "  2. Sync it to this Instance's /root/cert bind mount."
    echo "  3. Install a per-Instance Certbot deploy hook."
    echo "  4. Restart only this Instance after future successful renewals."
    echo
    read -r -p "Continue? [y/N]: " confirm

    [[ "$confirm" =~ ^[Yy]$ ]] || {
        echo
        echo "Certificate synchronization cancelled."
        docker_3xui_multi_cert_pause
        return 0
    }

    echo
    echo "Synchronizing certificate files..."

    if ! docker_3xui_multi_cert_copy_atomic; then
        echo "ERROR: Certificate synchronization failed."
        docker_3xui_multi_cert_pause
        return 1
    fi

    echo "Installing Certbot deploy hook..."

    if ! docker_3xui_multi_cert_install_hook; then
        echo "ERROR: Certificate files were synchronized, but the renewal hook failed."
        docker_3xui_multi_cert_pause
        return 1
    fi

    if ! docker_3xui_multi_cert_validate_pair \
        "$DOCKER_3XUI_MULTI_CERT_TARGET_CERT" \
        "$DOCKER_3XUI_MULTI_CERT_TARGET_KEY" \
        "$DOCKER_3XUI_MULTI_CERT_DOMAIN"; then
        echo "ERROR: Synchronized certificate failed final validation."
        docker_3xui_multi_cert_pause
        return 1
    fi

    if ! docker_3xui_multi_cert_verify_container_files; then
        echo "ERROR: Certificate sync completed on the host but container verification failed."
        docker_3xui_multi_cert_pause
        return 1
    fi

    docker_3xui_multi_cert_show_paths
    echo
    echo "Certificate synchronization completed successfully."
    echo "Future Certbot renewals will update this Instance automatically."
    echo
    echo "For a TLS inbound, keep the Xray listener on loopback and use the paths above."

    docker_3xui_multi_cert_pause
}


docker_3xui_multi_cert_status() {
    clear
    echo "======================================"
    echo "   3x-UI Instance Certificate Status"
    echo "======================================"
    echo

    if ! docker_3xui_multi_cert_require_environment; then
        docker_3xui_multi_cert_pause
        return 1
    fi

    local ids=()
    local id
    local container_state=""
    local mapping=""
    local hook_state=""
    local expiry=""

    mapfile -t ids < <(docker_3xui_instance_registered_ids 2>/dev/null)

    if [[ "${#ids[@]}" -eq 0 ]]; then
        echo "No registered 3x-UI Multi-Instance installation was found."
        docker_3xui_multi_cert_pause
        return 0
    fi

    for id in "${ids[@]}"; do
        if ! docker_3xui_multi_cert_context "$id"; then
            echo "Instance $id: state error"
            echo "--------------------------------------"
            continue
        fi

        container_state="$(docker_3xui_multi_cert_container_status "$DOCKER_3XUI_MULTI_CERT_CONTAINER")"
        mapping="Not installed"
        hook_state="Missing"
        expiry="N/A"

        if [[ -f "$DOCKER_3XUI_MULTI_CERT_SOURCE_CERT" ]]; then
            expiry="$(openssl x509 -in "$DOCKER_3XUI_MULTI_CERT_SOURCE_CERT" -noout -enddate 2>/dev/null | sed 's/^notAfter=//' || true)"
        fi

        if [[ -f "$DOCKER_3XUI_MULTI_CERT_TARGET_CERT" &&
              -f "$DOCKER_3XUI_MULTI_CERT_TARGET_KEY" ]]; then
            if [[ -f "$DOCKER_3XUI_MULTI_CERT_SOURCE_CERT" &&
                  -f "$DOCKER_3XUI_MULTI_CERT_SOURCE_KEY" ]] &&
               cmp -s "$DOCKER_3XUI_MULTI_CERT_SOURCE_CERT" "$DOCKER_3XUI_MULTI_CERT_TARGET_CERT" &&
               cmp -s "$DOCKER_3XUI_MULTI_CERT_SOURCE_KEY" "$DOCKER_3XUI_MULTI_CERT_TARGET_KEY"; then
                mapping="Synced"
            else
                mapping="Present / needs sync"
            fi
        fi

        [[ -x "$DOCKER_3XUI_MULTI_CERT_HOOK_PATH" ]] && hook_state="Installed"

        echo "Instance  : $DOCKER_3XUI_MULTI_CERT_INSTANCE_ID"
        echo "Domain    : $DOCKER_3XUI_MULTI_CERT_DOMAIN"
        echo "Container : $DOCKER_3XUI_MULTI_CERT_CONTAINER ($container_state)"
        echo "Mapping   : $mapping"
        echo "Renew Hook: $hook_state"
        echo "Expires   : ${expiry:-Unknown}"
        echo "TLS Cert  : $DOCKER_3XUI_MULTI_CERT_CONTAINER_DIR/fullchain.pem"
        echo "TLS Key   : $DOCKER_3XUI_MULTI_CERT_CONTAINER_DIR/privkey.pem"
        echo "--------------------------------------"
    done

    docker_3xui_multi_cert_pause
}


docker_3xui_multi_cert_verify() {
    clear
    echo "======================================"
    echo "   Verify 3x-UI TLS Certificate Map"
    echo "======================================"
    echo

    if ! docker_3xui_multi_cert_require_environment; then
        docker_3xui_multi_cert_pause
        return 1
    fi

    docker_3xui_multi_cert_select_instance
    case $? in
        0) ;;
        2) return 0 ;;
        *) docker_3xui_multi_cert_pause; return 1 ;;
    esac

    if ! docker_3xui_multi_cert_context "$DOCKER_3XUI_MULTI_CERT_SELECTED_ID"; then
        docker_3xui_multi_cert_pause
        return 1
    fi

    local failures=0

    if docker_3xui_multi_cert_check_mount; then
        echo "[OK] /root/cert bind mount"
    else
        failures=$((failures + 1))
    fi

    if docker_3xui_multi_cert_validate_pair \
        "$DOCKER_3XUI_MULTI_CERT_TARGET_CERT" \
        "$DOCKER_3XUI_MULTI_CERT_TARGET_KEY" \
        "$DOCKER_3XUI_MULTI_CERT_DOMAIN"; then
        echo "[OK] Certificate domain and private key"
    else
        failures=$((failures + 1))
    fi

    if [[ -f "$DOCKER_3XUI_MULTI_CERT_SOURCE_CERT" &&
          -f "$DOCKER_3XUI_MULTI_CERT_SOURCE_KEY" ]] &&
       cmp -s "$DOCKER_3XUI_MULTI_CERT_SOURCE_CERT" "$DOCKER_3XUI_MULTI_CERT_TARGET_CERT" &&
       cmp -s "$DOCKER_3XUI_MULTI_CERT_SOURCE_KEY" "$DOCKER_3XUI_MULTI_CERT_TARGET_KEY"; then
        echo "[OK] Copy matches current Let's Encrypt certificate"
    else
        echo "ERROR: Instance copy is not synchronized with the current Let's Encrypt certificate."
        failures=$((failures + 1))
    fi

    if docker_3xui_multi_cert_verify_container_files; then
        echo "[OK] Certificate files are readable inside $DOCKER_3XUI_MULTI_CERT_CONTAINER"
    else
        failures=$((failures + 1))
    fi

    if [[ -x "$DOCKER_3XUI_MULTI_CERT_HOOK_PATH" ]] &&
       bash -n "$DOCKER_3XUI_MULTI_CERT_HOOK_PATH" >/dev/null 2>&1; then
        echo "[OK] Certbot renewal deploy hook"
    else
        echo "ERROR: Certbot renewal deploy hook is missing or invalid."
        failures=$((failures + 1))
    fi

    echo
    docker_3xui_multi_cert_show_paths
    echo

    if (( failures == 0 )); then
        echo "Certificate mapping verification: PASSED"
    else
        echo "Certificate mapping verification: FAILED ($failures check(s))"
    fi

    docker_3xui_multi_cert_pause
    (( failures == 0 ))
}


docker_3xui_multi_cert_remove() {
    clear
    echo "======================================"
    echo " Remove 3x-UI Instance Cert Mapping"
    echo "======================================"
    echo

    if ! docker_3xui_multi_cert_require_environment; then
        docker_3xui_multi_cert_pause
        return 1
    fi

    docker_3xui_multi_cert_select_instance
    case $? in
        0) ;;
        2) return 0 ;;
        *) docker_3xui_multi_cert_pause; return 1 ;;
    esac

    if ! docker_3xui_multi_cert_context "$DOCKER_3XUI_MULTI_CERT_SELECTED_ID"; then
        docker_3xui_multi_cert_pause
        return 1
    fi

    echo
    echo "Instance : $DOCKER_3XUI_MULTI_CERT_INSTANCE_ID"
    echo "Domain   : $DOCKER_3XUI_MULTI_CERT_DOMAIN"
    echo
    echo "WARNING: Any Xray inbound that references these TLS files will fail after"
    echo "the files are removed and Xray/container is reloaded."
    echo
    echo "The Let's Encrypt source certificate will NOT be deleted."
    echo
    read -r -p "Remove this Instance certificate mapping? [y/N]: " confirm

    [[ "$confirm" =~ ^[Yy]$ ]] || {
        echo
        echo "Removal cancelled."
        docker_3xui_multi_cert_pause
        return 0
    }

    rm -f \
        "$DOCKER_3XUI_MULTI_CERT_TARGET_CERT" \
        "$DOCKER_3XUI_MULTI_CERT_TARGET_KEY" \
        "$DOCKER_3XUI_MULTI_CERT_HOOK_PATH"

    echo
    echo "Instance certificate mapping removed."
    echo "Let's Encrypt certificate retained at:"
    echo "$DOCKER_3XUI_MULTI_CERT_SOURCE_DIR"

    docker_3xui_multi_cert_pause
}


docker_3xui_multi_certificate_menu() {
    while true; do
        clear
        echo "======================================"
        echo "   3x-UI Docker TLS Certificates"
        echo "======================================"
        echo
        echo "1) Install / Sync Certificate to Instance"
        echo "2) Certificate Mapping Status"
        echo "3) Verify Certificate Inside Container"
        echo "4) Remove Certificate Mapping"
        echo
        echo "0) Back"
        echo

        read -r -p "Please enter your selection [0-4]: " choice

        case "$choice" in
            1) docker_3xui_multi_cert_sync ;;
            2) docker_3xui_multi_cert_status ;;
            3) docker_3xui_multi_cert_verify ;;
            4) docker_3xui_multi_cert_remove ;;
            0) return 0 ;;
            *) echo; echo "Invalid selection."; sleep 1 ;;
        esac
    done
}


docker_3xui_certificate_entry() {
    if docker_3xui_multi_cert_has_instances; then
        docker_3xui_multi_certificate_menu
        return
    fi

    if command -v docker >/dev/null 2>&1 &&
       docker ps -a --format '{{.Names}}' 2>/dev/null | grep -Fxq "3xui" &&
       declare -F docker_3xui_certificate_issue >/dev/null 2>&1; then
        docker_3xui_certificate_issue
        return
    fi

    clear
    echo "======================================"
    echo "      3x-UI Docker Certificate"
    echo "======================================"
    echo
    echo "No registered 3x-UI Docker Instance was found."
    echo "Install 3x-UI from Docker Management first."
    docker_3xui_multi_cert_pause
}


# Override Certificate Management after certificate.sh has been loaded.
# Options 1-5 retain their existing behavior; option 6 becomes Instance-aware.
show_certificate_menu() {
    while true; do
        clear
        echo "======================================"
        echo "       Certificate Management"
        echo "======================================"
        echo
        echo "1) Install Certbot"
        echo "2) Certificate Status"
        echo "3) Issue Certificate"
        echo "4) Renew Certificates"
        echo "5) Remove Certificate"
        echo "6) 3x-UI Docker TLS Certificate"
        echo
        echo "0) Back"
        echo
        read -r -p "Please enter your selection [0-6]: " choice

        case "$choice" in
            1) install_certbot ;;
            2) certificate_status ;;
            3) issue_certificate ;;
            4) renew_certificates ;;
            5) remove_certificate ;;
            6) docker_3xui_certificate_entry ;;
            0) return 0 ;;
            *) echo; echo "Invalid selection."; sleep 1 ;;
        esac
    done
}
