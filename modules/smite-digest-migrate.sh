#!/bin/bash

# U-OPTI - Smite Existing-Install Digest Migration
#
# Safely migrates existing Smite Compose image references from mutable tags
# to the exact image digests validated by U-OPTI.
#
# Safety policy:
#   - Never restarts or recreates a container.
#   - Verifies the running container already uses the validated image.
#   - Creates a timestamped Compose backup before modifying a file.
#   - Validates Docker Compose after the edit.
#   - Rolls the Compose file back automatically if validation fails.
#   - Verifies container ID / StartedAt / ImageID remain unchanged.
#   - Does not read, modify, or manage X-UI PRO / 3x-UI Docker resources.

SMITE_DIGEST_PANEL_REPO="${SMITE_DIGEST_PANEL_REPO:-ghcr.io/zzedix/smite-panel}"
SMITE_DIGEST_NODE_REPO="${SMITE_DIGEST_NODE_REPO:-ghcr.io/zzedix/smite-node}"

SMITE_DIGEST_PANEL_DIGEST="${SMITE_DIGEST_PANEL_DIGEST:-sha256:67f98cba1f49658e651779ab6142290f7eb0906b54b386939fcdb867d18cb44f}"
SMITE_DIGEST_NODE_DIGEST="${SMITE_DIGEST_NODE_DIGEST:-sha256:967c78b645a3367df4ae8413280cfca56dbe59c5f3897325313bc6cbf56e276e}"

SMITE_DIGEST_PANEL_IMAGE="${SMITE_DIGEST_PANEL_REPO}@${SMITE_DIGEST_PANEL_DIGEST}"
SMITE_DIGEST_NODE_IMAGE="${SMITE_DIGEST_NODE_REPO}@${SMITE_DIGEST_NODE_DIGEST}"

SMITE_DIGEST_PANEL_COMPOSE="${SMITE_PANEL_COMPOSE:-/opt/smite/docker-compose.yml}"
SMITE_DIGEST_NODE_COMPOSE="${SMITE_NODE_COMPOSE:-/opt/smite-node/docker-compose.yml}"

SMITE_DIGEST_STATE_DIR="${SMITE_STATE_DIR:-/etc/u-opti/smite}"
SMITE_DIGEST_BACKUP_ROOT="${SMITE_DIGEST_BACKUP_ROOT:-$SMITE_DIGEST_STATE_DIR/digest-backups}"

smite_digest_migrate_reference_status() {
    local compose_file="$1"
    local expected_repo="$2"
    local pinned_image="$3"

    python3 - "$compose_file" "$expected_repo" "$pinned_image" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
repo = sys.argv[2]
pinned = sys.argv[3]

try:
    text = path.read_text()
except Exception as exc:
    print(f"ERROR: Could not read Compose file: {exc}", file=sys.stderr)
    raise SystemExit(2)

pattern = re.compile(
    r"^(?P<prefix>\s*image:\s*)" + re.escape(repo) +
    r"(?P<ref>(?::[^\s#]+|@sha256:[0-9a-fA-F]{64}))\s*$",
    re.MULTILINE,
)

matches = list(pattern.finditer(text))
if len(matches) != 1:
    print(
        f"ERROR: Expected exactly one Compose image reference for {repo}; found {len(matches)}.",
        file=sys.stderr,
    )
    raise SystemExit(2)

current = repo + matches[0].group("ref")
print("pinned" if current == pinned else "unpinned")
PY
}

smite_digest_migrate_write_pin() {
    local compose_file="$1"
    local expected_repo="$2"
    local pinned_image="$3"

    python3 - "$compose_file" "$expected_repo" "$pinned_image" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
repo = sys.argv[2]
pinned = sys.argv[3]
text = path.read_text()

pattern = re.compile(
    r"^(?P<prefix>\s*image:\s*)" + re.escape(repo) +
    r"(?P<ref>(?::[^\s#]+|@sha256:[0-9a-fA-F]{64}))\s*$",
    re.MULTILINE,
)

matches = list(pattern.finditer(text))
if len(matches) != 1:
    print(
        f"ERROR: Expected exactly one Compose image reference for {repo}; found {len(matches)}. Refusing unsafe edit.",
        file=sys.stderr,
    )
    raise SystemExit(2)

match = matches[0]
current = repo + match.group("ref")
if current == pinned:
    print(f"Compose image already pinned: {pinned}")
    raise SystemExit(0)

replacement = match.group("prefix") + pinned
updated = text[:match.start()] + replacement + text[match.end():]
path.write_text(updated)
print(f"Pinned Compose image: {pinned}")
PY
}

smite_digest_migrate_ensure_image() {
    local pinned_image="$1"

    if docker image inspect "$pinned_image" >/dev/null 2>&1; then
        return 0
    fi

    echo "Validated image is not available locally. Pulling exact digest..."
    docker pull "$pinned_image" || return 1
}

smite_digest_migrate_one() {
    local label="$1"
    local container="$2"
    local compose_file="$3"
    local expected_repo="$4"
    local pinned_image="$5"

    local expected_image_id=""
    local before_id=""
    local before_started=""
    local before_image_id=""
    local after_id=""
    local after_started=""
    local after_image_id=""
    local reference_status=""
    local timestamp=""
    local backup_dir=""
    local backup_file=""

    echo
    echo "--------------------------------------"
    echo "$label"
    echo "--------------------------------------"
    echo "Container : $container"
    echo "Compose   : $compose_file"
    echo

    if [ ! -f "$compose_file" ]; then
        echo "ERROR: Compose file was not found."
        return 1
    fi

    if ! docker inspect "$container" >/dev/null 2>&1; then
        echo "ERROR: Container was not found: $container"
        return 1
    fi

    if ! smite_digest_migrate_ensure_image "$pinned_image"; then
        echo "ERROR: Validated digest image could not be prepared."
        return 1
    fi

    expected_image_id="$(docker image inspect "$pinned_image" -f '{{.Id}}' 2>/dev/null)"
    before_id="$(docker inspect "$container" -f '{{.Id}}' 2>/dev/null)"
    before_started="$(docker inspect "$container" -f '{{.State.StartedAt}}' 2>/dev/null)"
    before_image_id="$(docker inspect "$container" -f '{{.Image}}' 2>/dev/null)"

    if [ -z "$expected_image_id" ] || [ -z "$before_id" ] || [ -z "$before_image_id" ]; then
        echo "ERROR: Could not read Docker image/container identity."
        return 1
    fi

    echo "Running ImageID  : $before_image_id"
    echo "Validated ImageID: $expected_image_id"

    if [ "$before_image_id" != "$expected_image_id" ]; then
        echo
        echo "ERROR: Running $container does not use the U-OPTI validated image."
        echo "No Compose change was made."
        return 1
    fi

    reference_status="$(smite_digest_migrate_reference_status "$compose_file" "$expected_repo" "$pinned_image")" || {
        echo "ERROR: Compose image reference could not be classified safely."
        return 1
    }

    if [ "$reference_status" = "pinned" ]; then
        if ! docker compose -f "$compose_file" config >/dev/null; then
            echo "ERROR: Compose is already digest-pinned but validation failed."
            return 1
        fi

        after_id="$(docker inspect "$container" -f '{{.Id}}' 2>/dev/null)"
        after_started="$(docker inspect "$container" -f '{{.State.StartedAt}}' 2>/dev/null)"
        after_image_id="$(docker inspect "$container" -f '{{.Image}}' 2>/dev/null)"

        if [ "$before_id" != "$after_id" ] ||
           [ "$before_started" != "$after_started" ] ||
           [ "$before_image_id" != "$after_image_id" ]; then
            echo "ERROR: Container identity changed unexpectedly during no-op verification."
            return 1
        fi

        echo "Compose digest pin : already correct"
        echo "Compose validation : OK"
        echo "Container restart  : No"
        echo "Result             : No changes required"
        return 0
    fi

    timestamp="$(date '+%Y%m%d-%H%M%S-%N')"
    backup_dir="$SMITE_DIGEST_BACKUP_ROOT/$timestamp-$container"
    backup_file="$backup_dir/docker-compose.yml"

    mkdir -p "$backup_dir" || {
        echo "ERROR: Failed to create backup directory."
        return 1
    }
    chmod 700 "$SMITE_DIGEST_BACKUP_ROOT" "$backup_dir" 2>/dev/null || true

    if ! cp -a "$compose_file" "$backup_file"; then
        echo "ERROR: Failed to back up Compose file."
        rm -rf "$backup_dir"
        return 1
    fi
    chmod 600 "$backup_file" 2>/dev/null || true

    echo "Backup             : $backup_file"

    if ! smite_digest_migrate_write_pin "$compose_file" "$expected_repo" "$pinned_image"; then
        echo "ERROR: Failed to write digest pin. Restoring backup..."
        cp -a "$backup_file" "$compose_file" || true
        return 1
    fi

    if ! docker compose -f "$compose_file" config >/dev/null; then
        echo "ERROR: Compose validation failed after digest pin."
        echo "Restoring previous Compose file..."
        cp -a "$backup_file" "$compose_file" || {
            echo "CRITICAL: Automatic Compose rollback failed."
            echo "Safety backup remains at: $backup_file"
            return 1
        }

        if docker compose -f "$compose_file" config >/dev/null; then
            echo "Rollback validation: OK"
        else
            echo "CRITICAL: Restored Compose file also failed validation."
        fi
        return 1
    fi

    after_id="$(docker inspect "$container" -f '{{.Id}}' 2>/dev/null)"
    after_started="$(docker inspect "$container" -f '{{.State.StartedAt}}' 2>/dev/null)"
    after_image_id="$(docker inspect "$container" -f '{{.Image}}' 2>/dev/null)"

    if [ "$before_id" != "$after_id" ] ||
       [ "$before_started" != "$after_started" ] ||
       [ "$before_image_id" != "$after_image_id" ]; then
        echo "ERROR: Container identity changed unexpectedly."
        echo "The Compose file remains digest-pinned, but investigate before continuing."
        return 1
    fi

    echo "Compose validation : OK"
    echo "Container restart  : No"
    echo "Container ID       : unchanged"
    echo "StartedAt          : unchanged"
    echo "ImageID            : unchanged"
    echo "Result             : Digest migration complete"
    return 0
}

smite_digest_migrate_existing() {
    local found=0
    local failed=0

    echo "======================================"
    echo "     Smite Digest Migration"
    echo "======================================"
    echo
    echo "This operation only updates existing Smite Compose image references."
    echo "It does NOT restart or recreate Smite containers."
    echo "It does NOT modify X-UI PRO or 3x-UI Docker."

    if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
        echo
        echo "ERROR: Docker Engine / Compose is not available."
        return 1
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        echo
        echo "ERROR: python3 is required."
        return 1
    fi

    mkdir -p "$SMITE_DIGEST_BACKUP_ROOT" || return 1
    chmod 700 "$SMITE_DIGEST_STATE_DIR" "$SMITE_DIGEST_BACKUP_ROOT" 2>/dev/null || true

    if [ -f "$SMITE_DIGEST_PANEL_COMPOSE" ] || docker inspect smite-panel >/dev/null 2>&1; then
        found=1
        smite_digest_migrate_one \
            "Smite Panel" \
            "smite-panel" \
            "$SMITE_DIGEST_PANEL_COMPOSE" \
            "$SMITE_DIGEST_PANEL_REPO" \
            "$SMITE_DIGEST_PANEL_IMAGE" || failed=1
    fi

    if [ -f "$SMITE_DIGEST_NODE_COMPOSE" ] || docker inspect smite-node >/dev/null 2>&1; then
        found=1
        smite_digest_migrate_one \
            "Smite Node" \
            "smite-node" \
            "$SMITE_DIGEST_NODE_COMPOSE" \
            "$SMITE_DIGEST_NODE_REPO" \
            "$SMITE_DIGEST_NODE_IMAGE" || failed=1
    fi

    echo
    if [ "$found" -eq 0 ]; then
        echo "No existing Smite Panel/Node installation was detected."
        return 1
    fi

    if [ "$failed" -ne 0 ]; then
        echo "Digest migration finished with one or more errors."
        echo "Review the messages above."
        return 1
    fi

    echo "======================================"
    echo "   Smite Digest Migration Complete"
    echo "======================================"
    echo
    echo "All detected Smite Compose files are pinned to validated digests."
    echo "No Smite container was restarted or recreated."
    return 0
}
