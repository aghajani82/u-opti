#!/usr/bin/env bash
# Download the exact reviewed FRP 0.71.0 Stage15 image pair from a durable
# public Smite prerelease. No Docker run/load, Compose edits or server activation.
# The historical local ZIP/old FRP 0.65.0 images are deliberately not selected.
set -euo pipefail

UOPTI_STAGE15_CACHE=/var/lib/u-opti/smite-stage15-frp071-images
UOPTI_STAGE15_SOURCE=6981bd91b43811fad8847da9abd81ef99a921003
UOPTI_STAGE15_MANIFEST_SHA=0b34ee3fbd9174e6bf7ef6ddf145f7ebcd606c9bbeae176bb3d6a38b8a2a7840
UOPTI_STAGE15_TAG=stage15-frp071-6981bd91
UOPTI_STAGE15_RELEASE=https://github.com/aghajani82/Smite/releases/download/${UOPTI_STAGE15_TAG}

uopti_stage15_image_hold() {
    printf 'HOLD: %s\n' "$1" >&2
    return 2
}

uopti_stage15_verify_file() {
    local target="$1" expected_sha="$2" expected_size="$3" actual
    [[ -f "$target" && ! -L "$target" ]] || { uopti_stage15_image_hold 'Image asset is missing or symlinked'; return 2; }
    [[ "$(stat -c '%u' "$target")" == 0 &&
       $(( 8#$(stat -c '%a' "$target") & 8#022 )) == 0 ]] || {
        uopti_stage15_image_hold 'Image asset ownership or mode is unsafe'; return 2;
    }
    [[ "$(stat -c '%s' "$target")" == "$expected_size" ]] || {
        uopti_stage15_image_hold 'Image asset size differs from reviewed artifact'; return 2;
    }
    actual="$(sha256sum "$target" | awk '{print $1}')" || return 2
    [[ "$actual" == "$expected_sha" ]] || {
        uopti_stage15_image_hold 'Image asset SHA256 differs from reviewed artifact'; return 2;
    }
}

uopti_stage15_fetch_images() {
    local dir="$UOPTI_STAGE15_CACHE" file sha bytes target temp part
    local module_dir
    module_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 2
    [[ $EUID -eq 0 ]] || { uopti_stage15_image_hold 'Root is required'; return 2; }
    [[ "$(hostname -s | tr '[:lower:]' '[:upper:]')" =~ ^(IR|KH)$ ]] || {
        uopti_stage15_image_hold 'Only disposable IR/KH hosts are admitted'; return 2;
    }
    [[ "$(uname -m)" == x86_64 ]] || {
        uopti_stage15_image_hold 'Reviewed Stage15 image pair is amd64-only'; return 2;
    }
    for dir in /var /var/lib /var/lib/u-opti; do
        if [[ -e "$dir" || -L "$dir" ]]; then
            [[ -d "$dir" && ! -L "$dir" && "$(stat -c '%u' "$dir")" == 0 &&
               $(( 8#$(stat -c '%a' "$dir") & 8#022 )) == 0 ]] || {
                uopti_stage15_image_hold 'Untrusted image-cache parent'; return 2;
            }
        fi
    done
    dir="$UOPTI_STAGE15_CACHE"
    [[ ! -L "$dir" ]] || { uopti_stage15_image_hold 'Symlinked image cache'; return 2; }
    install -d -m 0700 -o 0 -g 0 "$dir" || return 2
    [[ -d "$dir" && ! -L "$dir" && "$(stat -c '%u:%a' "$dir")" == '0:700' ]] || {
        uopti_stage15_image_hold 'Untrusted image cache directory'; return 2;
    }
    umask 077
    [[ ! -L "$dir/.download.lock" ]] || { uopti_stage15_image_hold 'Symlinked cache lock'; return 2; }
    exec 9>"$dir/.download.lock"
    flock -x 9 || return 2
    # Manifest first, then individually verifiable compressed Docker images.
    # Both images are fetched even on KH because the existing signed admission
    # verifies the complete paired artifact before any install/upgrade.
    while read -r file sha bytes; do
        target="$dir/$file"
        if [[ -e "$target" || -L "$target" ]]; then
            uopti_stage15_verify_file "$target" "$sha" "$bytes" || return 2
            continue
        fi
        temp="$(mktemp "$dir/.incoming.XXXXXXXX")" || return 2
        if ! curl --fail --silent --show-error --location \
                 --proto '=https' --proto-redir '=https' \
                 --retry 3 --connect-timeout 20 --max-time 1200 \
                 --output "$temp" "$UOPTI_STAGE15_RELEASE/$file"; then
            rm -f -- "$temp"
            uopti_stage15_image_hold 'Pinned GitHub prerelease is unavailable'; return 2
        fi
        chmod 0600 "$temp" || { rm -f -- "$temp"; return 2; }
        if ! uopti_stage15_verify_file "$temp" "$sha" "$bytes"; then
            rm -f -- "$temp"
            return 2
        fi
        mv -T -- "$temp" "$target" || return 2
        sync -f "$target" || return 2
    done <<'REVIEWED_ASSETS'
stage15-images.json 0b34ee3fbd9174e6bf7ef6ddf145f7ebcd606c9bbeae176bb3d6a38b8a2a7840 953
smite-panel-stage15.docker.tar.gz 87627cd74ecb4e6d062eb45fd16ef128f10a4cc11f6a94c7e46b01fb4f595488 201672485
smite-node-stage15.docker.tar.gz e62717ac06e08d11730fd25a20a58b2f5470ff29b86cad02b310984b24fe96c7 171451224
REVIEWED_ASSETS
    [[ -f "$module_dir/smite-clean-image-pair.py" &&
       ! -L "$module_dir/smite-clean-image-pair.py" ]] || {
        uopti_stage15_image_hold 'Pair verifier is missing'; return 2;
    }
    python3 -B "$module_dir/smite-clean-image-pair.py" \
        --folder "$dir" --source-sha "$UOPTI_STAGE15_SOURCE" \
        --manifest-sha256 "$UOPTI_STAGE15_MANIFEST_SHA" || return 2
    printf 'STAGE15_VERIFIED_IMAGE_CACHE=%s\n' "$dir"
    printf '%s\n' 'AUTO_DOWNLOAD_ONLY=YES' 'DOCKER_LOAD=NO' 'LIVE_CHANGES=NONE'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    uopti_stage15_fetch_images "$@"
fi
