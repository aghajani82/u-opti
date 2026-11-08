#!/usr/bin/env bash
# PR-only CI bootstrap from the exact official Sigstore release assets.
# Mirrors sigstore/cosign-installer v4.1.0's pinned v3.0.5 bootstrap,
# v3.0.6 keyless and KMS signature verification. Never skip a gate.
set -euo pipefail
: "$RUNNER_TEMP"
work="$(mktemp -d "$RUNNER_TEMP/uopti-cosign.XXXXXX")"
trap 'rm -rf "$work"' EXIT
cd "$work"
fetch_verified() {
  local tag="$1" name="$2" asset_id="$3" digest="$4" target="$5"
  local official="https://github.com/sigstore/cosign/releases/download/$tag/$name"
  local api="https://api.github.com/repos/sigstore/cosign/releases/assets/$asset_id"
  if ! curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 180 "$official" -o "$target"; then
    curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 180 \
      -H 'Accept: application/octet-stream' "$api" -o "$target"
  fi
  printf '%s  %s\n' "$digest" "$target" | sha256sum -c - >/dev/null
}
# Official sigstore/cosign-installer@v4.1.0 bootstrap checksum and release ID.
fetch_verified v3.0.5 cosign-linux-amd64 358750885 \
  db15cc99e6e4837daabab023742aaddc3841ce57f193d11b7c3e06c8003642b2 bootstrap
chmod 700 bootstrap
# Release v3.0.6 exact immutable asset IDs and official Release API SHA256.
fetch_verified v3.0.6 cosign-linux-amd64 390331694 \
  c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74 desired
fetch_verified v3.0.6 cosign-linux-amd64.sigstore.json 390332772 \
  b3a04913f3a3f4a38e4a7a42b8d590834b8791de99ddeaad66c608b6aa8e02a4 keyless.sigstore.json
fetch_verified v3.0.6 cosign-linux-amd64-kms.sigstore.json 390332714 \
  9f2728c7876e82561d1f4d2837e2a14180ff0fba1aeffd59163c48aea68cd519 kms.sigstore.json
# Same pinned upstream public key SHA used by cosign-installer v4.1.0.
curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 30 \
  https://raw.githubusercontent.com/sigstore/cosign/v3.0.6/release/release-cosign.pub -o release-cosign.pub
printf '%s  %s\n' f4cea466e5e887a45da5031757fa1d32655d83420639dc1758749b744179f126 release-cosign.pub | sha256sum -c - >/dev/null
# Require BOTH independent upstream verification paths, not just hashes.
./bootstrap verify-blob \
  --certificate-identity=keyless@projectsigstore.iam.gserviceaccount.com \
  --certificate-oidc-issuer=https://accounts.google.com \
  --bundle keyless.sigstore.json desired
./bootstrap verify-blob --key release-cosign.pub --bundle kms.sigstore.json desired
install -d -m 0700 "$RUNNER_TEMP/uopti-verified-cosign"
install -m 0755 desired "$RUNNER_TEMP/uopti-verified-cosign/cosign"
"$RUNNER_TEMP/uopti-verified-cosign/cosign" version 2>&1 | grep -F 'v3.0.6' >/dev/null
printf '%s\n' "$RUNNER_TEMP/uopti-verified-cosign" >> "$GITHUB_PATH"
echo 'CI_COSIGN_OFFICIAL_SHA256_KEYLESS_KMS=PASS'
