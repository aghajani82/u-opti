#!/usr/bin/env bash
# Shared PR-only CI release transport: exact official GitHub asset IDs and
# SHA-256 pins. No third-party mirrors, mutable tags, or digest bypass.
ci_fetch_official_release() (
  set -euo pipefail
  local url="$1" dest="$2" asset_id="" digest="" api_repo=""
  case "$url" in
    https://github.com/fatedier/frp/releases/download/v0.71.0/frp_0.71.0_linux_amd64.tar.gz)
      api_repo=fatedier/frp
      asset_id=514042277
      digest=84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716 ;;
    https://github.com/fatedier/frp/releases/download/v0.71.0/frp_0.71.0_linux_arm64.tar.gz)
      api_repo=fatedier/frp
      asset_id=514042211
      digest=f33c293c275d8fc68c654b6fba8f10b2551d6463d09a9fc9cffb7227eae82266 ;;
    https://github.com/Musixal/Backhaul/releases/download/v0.7.2/backhaul_linux_amd64.tar.gz)
      api_repo=Musixal/Backhaul
      asset_id=289712775
      digest=57bf95c2eabeddb1152d2e94ac42f4310883ce0fb909ee2a57bd53503b2dabbc ;;
    https://github.com/Musixal/Backhaul/releases/download/v0.7.2/backhaul_linux_arm64.tar.gz)
      api_repo=Musixal/Backhaul
      asset_id=289712774
      digest=9a424c97ff16fc3f682e8314c418790d2b5bf3136e008edbb6cd402ea00999f6 ;;
    *) echo 'HOLD: CI_OFFICIAL_RELEASE_URL_NOT_ALLOWLISTED' >&2; exit 2 ;;
  esac
  local tmp
  tmp="$(mktemp "$dest.ci-XXXXXXXX")"
  trap 'rm -f -- "$tmp"' EXIT
  if ! curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 15 \
      --max-time 120 --proto '=https' --proto-redir '=https' "$url" -o "$tmp"; then
    curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 15 \
      --max-time 120 --proto '=https' --proto-redir '=https' \
      -H 'Accept: application/octet-stream' \
      "https://api.github.com/repos/$api_repo/releases/assets/$asset_id" -o "$tmp"
  fi
  printf '%s  %s\n' "$digest" "$tmp" | sha256sum -c - >/dev/null
  mv -f -- "$tmp" "$dest"
  echo 'CI_PINNED_OFFICIAL_RELEASE_SHA256=PASS'
)
