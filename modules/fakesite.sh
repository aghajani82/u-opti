#!/usr/bin/env bash

# U-OPTI - Default Website / FakeSite Management
# v0.13.0

FAKESITE_ROOT="/var/www/u-opti-default"
FAKESITE_INDEX="$FAKESITE_ROOT/index.html"

FAKESITE_CACHE_ROOT="/var/lib/u-opti/fakesite"
FAKESITE_REPO_DIR="$FAKESITE_CACHE_ROOT/randomfakehtml"
FAKESITE_REPO_URL="https://github.com/aghajani82/randomfakehtml.git"
FAKESITE_DEFAULT_TEMPLATE="avenger-multi-purpose-responsive-html5-bootstrap-template"
FAKESITE_TEMPLATE_NAME="$FAKESITE_DEFAULT_TEMPLATE"

FAKESITE_CONFIG_ROOT="/etc/u-opti"
FAKESITE_CONFIG="$FAKESITE_CONFIG_ROOT/fakesite.conf"

FAKESITE_SYSTEMD_SERVICE="/etc/systemd/system/u-opti-fakesite-random.service"
FAKESITE_SYSTEMD_TIMER="/etc/systemd/system/u-opti-fakesite-random.timer"
FAKESITE_LOCK="/var/lock/u-opti-fakesite.lock"
FAKESITE_RANDOM_TIME="03:00:00"


fakesite_ensure_root() {
    mkdir -p "$FAKESITE_ROOT"
}


fakesite_load_selection() {
    FAKESITE_TEMPLATE_NAME="$FAKESITE_DEFAULT_TEMPLATE"

    if [[ -f "$FAKESITE_CONFIG" ]]; then
        # shellcheck disable=SC1090
        source "$FAKESITE_CONFIG"

        if [[ -z "$FAKESITE_TEMPLATE_NAME" ]]; then
            FAKESITE_TEMPLATE_NAME="$FAKESITE_DEFAULT_TEMPLATE"
        fi
    fi
}


fakesite_save_selection() {
    local template="$1"

    mkdir -p "$FAKESITE_CONFIG_ROOT" || {
        echo "ERROR: Failed to create FakeSite configuration directory."
        return 1
    }

    cat > "$FAKESITE_CONFIG" <<EOF
FAKESITE_TEMPLATE_NAME=$(printf '%q' "$template")
EOF

    chmod 600 "$FAKESITE_CONFIG"
}


fakesite_get_template_list() {
    [[ -d "$FAKESITE_REPO_DIR/.git" ]] || return 1

    git -C "$FAKESITE_REPO_DIR" ls-tree -d --name-only HEAD 2>/dev/null |
    while IFS= read -r template; do
        [[ -z "$template" ]] && continue

        if git -C "$FAKESITE_REPO_DIR" cat-file -e \
            "HEAD:$template/index.html" 2>/dev/null; then
            printf '%s\n' "$template"
        fi
    done
}


fakesite_ensure_repository() {
    mkdir -p "$FAKESITE_CACHE_ROOT" || {
        echo "ERROR: Failed to create FakeSite cache directory."
        return 1
    }

    if [[ ! -d "$FAKESITE_REPO_DIR/.git" ]]; then
        echo "Downloading template repository..."
        rm -rf "$FAKESITE_REPO_DIR"

        if ! git clone \
            --filter=blob:none \
            --no-checkout \
            --depth 1 \
            "$FAKESITE_REPO_URL" \
            "$FAKESITE_REPO_DIR"; then
            echo "ERROR: Failed to download FakeSite template repository."
            rm -rf "$FAKESITE_REPO_DIR"
            return 1
        fi
    else
        echo "Updating template repository..."

        if ! git -C "$FAKESITE_REPO_DIR" fetch --depth 1 origin master; then
            echo "ERROR: Failed to update FakeSite template repository."
            return 1
        fi

        if ! git -C "$FAKESITE_REPO_DIR" reset --hard FETCH_HEAD >/dev/null 2>&1; then
            echo "ERROR: Failed to reset template repository."
            return 1
        fi
    fi
}


fakesite_checkout_template() {
    local template="$1"

    if ! git -C "$FAKESITE_REPO_DIR" checkout \
        --force \
        HEAD \
        -- "$template"; then
        echo "ERROR: Failed to checkout selected template:"
        echo "$template"
        return 1
    fi
}


fakesite_select_template() {
    local selected
    local i=1
    local choice
    local install_choice
    local templates=()

    echo
    echo "Preparing template list..."
    echo

    fakesite_ensure_repository || return 1

    while IFS= read -r selected; do
        [[ -n "$selected" ]] && templates+=("$selected")
    done < <(fakesite_get_template_list | sort)

    if [[ ${#templates[@]} -eq 0 ]]; then
        echo "ERROR: No valid templates were found."
        return 1
    fi

    echo "Available Templates:"
    echo

    for selected in "${templates[@]}"; do
        echo "$i) $selected"
        ((i++))
    done

    echo
    read -r -p "Select template [1-${#templates[@]}]: " choice

    if ! [[ "$choice" =~ ^[0-9]+$ ]] ||
       (( choice < 1 || choice > ${#templates[@]} )); then
        echo
        echo "ERROR: Invalid template selection."
        return 1
    fi

    selected="${templates[$((choice - 1))]}"

    if ! fakesite_save_selection "$selected"; then
        return 1
    fi

    FAKESITE_TEMPLATE_NAME="$selected"

    echo
    echo "Template selected successfully."
    echo "Selected: $FAKESITE_TEMPLATE_NAME"
    echo

    read -r -p "Install this template now? [Y/n]: " install_choice

    case "$install_choice" in
        n|N)
            echo
            echo "Template selection saved. Current website was not changed."
            ;;
        *)
            echo
            fakesite_install_template
            ;;
    esac
}



fakesite_random_template() {
    local selected
    local previous=""
    local random_template
    local templates=()

    fakesite_load_selection
    previous="$FAKESITE_TEMPLATE_NAME"

    echo
    echo "Selecting a random template..."
    echo

    fakesite_ensure_repository || return 1

    while IFS= read -r selected; do
        [[ -n "$selected" ]] && templates+=("$selected")
    done < <(fakesite_get_template_list | sort)

    if [[ ${#templates[@]} -eq 0 ]]; then
        echo "ERROR: No valid templates were found."
        return 1
    fi

    if (( ${#templates[@]} > 1 )); then
        while true; do
            random_template="${templates[RANDOM % ${#templates[@]}]}"
            [[ "$random_template" != "$previous" ]] && break
        done
    else
        random_template="${templates[0]}"
    fi

    if ! fakesite_save_selection "$random_template"; then
        return 1
    fi

    FAKESITE_TEMPLATE_NAME="$random_template"

    echo "Random template selected:"
    echo "$FAKESITE_TEMPLATE_NAME"
    echo
}


fakesite_daily_random_run() {
    exec 9>"$FAKESITE_LOCK"

    if ! flock -n 9; then
        echo "FakeSite random update is already running."
        return 1
    fi

    fakesite_random_template || return 1
    fakesite_install_template
}


fakesite_schedule_status() {
    echo
    echo "======================================"
    echo "   Daily Random Template Schedule"
    echo "======================================"
    echo

    echo "Service : $FAKESITE_SYSTEMD_SERVICE"
    echo "Timer   : $FAKESITE_SYSTEMD_TIMER"
    echo "Time    : Daily at $FAKESITE_RANDOM_TIME"
    echo

    if systemctl is-enabled --quiet u-opti-fakesite-random.timer 2>/dev/null; then
        echo "Status  : Enabled"
    else
        echo "Status  : Disabled"
    fi

    echo

    if systemctl is-active --quiet u-opti-fakesite-random.timer 2>/dev/null; then
        echo "Timer   : Active"
    else
        echo "Timer   : Inactive"
    fi

    echo

    systemctl list-timers --all u-opti-fakesite-random.timer \
        --no-pager 2>/dev/null || true

    echo
}


fakesite_schedule_enable() {
    mkdir -p "$FAKESITE_CONFIG_ROOT"

    cat > "$FAKESITE_SYSTEMD_SERVICE" <<EOF
[Unit]
Description=U-OPTI Daily Random FakeSite Template
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=root
ExecStart=/bin/bash -c 'source /usr/local/lib/u-opti/modules/fakesite.sh; fakesite_daily_random_run'
EOF

    cat > "$FAKESITE_SYSTEMD_TIMER" <<EOF
[Unit]
Description=U-OPTI Daily Random FakeSite Template Timer

[Timer]
OnCalendar=*-*-* $FAKESITE_RANDOM_TIME
Persistent=true
RandomizedDelaySec=5min
Unit=u-opti-fakesite-random.service

[Install]
WantedBy=timers.target
EOF

    chmod 644 "$FAKESITE_SYSTEMD_SERVICE" "$FAKESITE_SYSTEMD_TIMER"

    systemctl daemon-reload || {
        echo "ERROR: systemd daemon-reload failed."
        return 1
    }

    if ! systemctl enable --now u-opti-fakesite-random.timer; then
        echo "ERROR: Failed to enable FakeSite random timer."
        return 1
    fi

    echo
    echo "Daily Random Template schedule enabled."
    echo "Run time: Daily at $FAKESITE_RANDOM_TIME"
    echo
}


fakesite_schedule_disable() {
    systemctl disable --now u-opti-fakesite-random.timer 2>/dev/null || true

    rm -f "$FAKESITE_SYSTEMD_TIMER" "$FAKESITE_SYSTEMD_SERVICE"

    systemctl daemon-reload || true

    echo
    echo "Daily Random Template schedule disabled."
    echo
}


fakesite_schedule_menu() {
    while true; do
        clear

        echo "======================================"
        echo "   Daily Random Template Schedule"
        echo "======================================"
        echo
        echo "1) Enable Daily Random"
        echo "2) Disable Daily Random"
        echo "3) Schedule Status"
        echo "4) Run Random Template Now"
        echo
        echo "0) Back"
        echo

        read -r -p "Please enter your selection [0-4]: " SCHEDULE_CHOICE

        case "$SCHEDULE_CHOICE" in
            1)
                fakesite_schedule_enable
                read -r -p "Press Enter to return..."
                ;;
            2)
                fakesite_schedule_disable
                read -r -p "Press Enter to return..."
                ;;
            3)
                fakesite_schedule_status
                read -r -p "Press Enter to return..."
                ;;
            4)
                fakesite_daily_random_run
                read -r -p "Press Enter to return..."
                ;;
            0)
                return 0
                ;;
            *)
                echo
                echo "Invalid selection."
                sleep 1
                ;;
        esac
    done
}


fakesite_status() {
    echo
    echo "======================================"
    echo "      Default Website / FakeSite"
    echo "======================================"
    echo
    echo "Template Root : $FAKESITE_ROOT"

    if [[ -d "$FAKESITE_ROOT" ]]; then
        echo "Root Status   : Installed"
    else
        echo "Root Status   : Not Installed"
        return 0
    fi

    if [[ -f "$FAKESITE_INDEX" ]]; then
        echo "Index         : Present"

        local file_count
        file_count="$(find "$FAKESITE_ROOT" -type f 2>/dev/null | wc -l)"
        echo "Files         : $file_count"
    else
        echo "Index         : Missing"
    fi

    echo
}


fakesite_test() {
    echo
    echo "Testing FakeSite..."
    echo

    if [[ ! -d "$FAKESITE_ROOT" ]]; then
        echo "ERROR: FakeSite root does not exist:"
        echo "$FAKESITE_ROOT"
        return 1
    fi

    if [[ ! -f "$FAKESITE_INDEX" ]]; then
        echo "ERROR: FakeSite index.html does not exist:"
        echo "$FAKESITE_INDEX"
        return 1
    fi

    if ! grep -q '<html' "$FAKESITE_INDEX" 2>/dev/null; then
        echo "ERROR: index.html does not appear to be valid HTML."
        return 1
    fi

    echo "FakeSite root : OK"
    echo "index.html    : OK"
    echo "HTML check    : OK"
    echo

    return 0
}


fakesite_install_template() {
    local template_dir
    local work_dir
    local backup_dir

    fakesite_load_selection

    echo
    echo "Install / Update Default Template"
    echo
    echo "Template: $FAKESITE_TEMPLATE_NAME"
    echo


    fakesite_ensure_repository || return 1

    if ! fakesite_checkout_template "$FAKESITE_TEMPLATE_NAME"; then
        return 1
    fi

    template_dir="$FAKESITE_REPO_DIR/$FAKESITE_TEMPLATE_NAME"

    if [[ ! -f "$template_dir/index.html" ]]; then
        echo "ERROR: Selected template does not contain index.html."
        echo "$template_dir"
        return 1
    fi

    work_dir="${FAKESITE_ROOT}.new.$$"
    backup_dir="${FAKESITE_ROOT}.backup-$(date +%Y%m%d-%H%M%S)"

    rm -rf "$work_dir"

    if ! mkdir -p "$work_dir"; then
        echo "ERROR: Failed to create temporary FakeSite directory."
        return 1
    fi

    if ! cp -a "$template_dir/." "$work_dir/"; then
        echo "ERROR: Failed to stage the selected template."
        rm -rf "$work_dir"
        return 1
    fi

    find "$work_dir" -type d -exec chmod 755 {} \;
    find "$work_dir" -type f -exec chmod 644 {} \;

    chown -R root:root "$work_dir"

    if [[ -d "$FAKESITE_ROOT" ]]; then
        mv "$FAKESITE_ROOT" "$backup_dir" || {
            echo "ERROR: Failed to create FakeSite backup."
            rm -rf "$work_dir"
            return 1
        }
    fi

    if ! mv "$work_dir" "$FAKESITE_ROOT"; then
        echo "ERROR: Failed to activate new FakeSite."

        if [[ -d "$backup_dir" ]]; then
            mv "$backup_dir" "$FAKESITE_ROOT" || true
        fi

        rm -rf "$work_dir"
        return 1
    fi

    echo
    echo "Default template installed successfully."
    echo "Template Root : $FAKESITE_ROOT"
    echo "Template Name : $FAKESITE_TEMPLATE_NAME"
    echo "Backup        : $backup_dir"
    echo

    fakesite_test
}



fakesite_menu() {
    while true; do
        clear

        fakesite_load_selection

        echo "======================================"
        echo "      Default Website / FakeSite"
        echo "======================================"
        echo
        echo "Current Template:"
        echo "$FAKESITE_TEMPLATE_NAME"
        echo
        echo "1) Install / Update Default Template"
        echo "2) Select Template"
        echo "3) Random Template"
        echo "4) Preview / Test Template"
        echo "5) Template Status"
        echo "6) Daily Random Template Schedule"
        echo
        echo "0) Back"
        echo

        read -r -p "Please enter your selection [0-6]: " FAKESITE_CHOICE

        case "$FAKESITE_CHOICE" in
            1)
                fakesite_install_template
                echo
                read -r -p "Press Enter to return..."
                ;;
            2)
                fakesite_select_template
                echo
                read -r -p "Press Enter to return..."
                ;;
            3)
                fakesite_random_template && fakesite_install_template
                echo
                read -r -p "Press Enter to return..."
                ;;
            4)
                fakesite_test
                echo
                read -r -p "Press Enter to return..."
                ;;
            5)
                fakesite_status
                echo
                read -r -p "Press Enter to return..."
                ;;
            6)
                fakesite_schedule_menu
                ;;
            0)
                return 0
                ;;
            *)
                echo
                echo "Invalid selection."
                sleep 1
                ;;
        esac
    done
}
