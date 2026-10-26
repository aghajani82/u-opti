#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
files=(smite-backhaul-management.sh smite-backhaul-standard.sh smite-backhaul-spec.py smite-backhaul-node-patch.py smite-backhaul-panel-patch.py)
for f in "${files[@]}"; do
    test -s "modules/$f"
    grep -Fq "\"$f\"" install.sh
    grep -Fq "\"$f\"" u-opti
    grep -Fq "[\"$f\"]=\"\$BASE_URL/modules/$f\"" u-opti
    grep -Fq "[\"$f\"]=\"\$TEMP_DIR/$f\"" u-opti
    case "$f" in
        *.py) python3 -m py_compile "modules/$f" ;;
        *) bash -n "modules/$f" ;;
    esac
done
grep -Fq 'source "$MODULES_PATH/smite-backhaul-management.sh"' u-opti
grep -Fq 'smite_bh_management_menu()' modules/smite-backhaul-management.sh
# INSTALL_REF is now the fourth standard persistent backup target.
grep -Fq '4 + ${#BACKUP_FILES[@]}' u-opti
grep -Fq '"$BACKUP_DIR/INSTALL_REF"' u-opti
grep -Fq -- '--source-ref "$BRANCH"' u-opti
grep -Fq 'smite-backhaul-*' u-opti
grep -Fq '"smite-frp-xhttp.sh"' u-opti
grep -Fq '"smite-frp-wizard.sh"' u-opti
grep -Fq 'smite-frp-*' u-opti
grep -Fq '*.py|smite-xhttp-nginx-route) python3 -m py_compile' install.sh
grep -Fq '"$TEMP_DIR/"*.py)' u-opti
! grep -Fq 'smite_bh_activate()' modules/smite-backhaul-management.sh
! grep -Fq 'systemctl reload nginx' modules/smite-backhaul-management.sh
! grep -Fq 'docker compose up' modules/smite-backhaul-management.sh
echo 'Backhaul preparation-only packaging + updater backup guards: PASS'
