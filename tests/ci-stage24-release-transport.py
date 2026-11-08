#!/usr/bin/env python3
"""Only for the pinned legacy Stage24 CI image: change release transport.

Keep the exact reviewed Smite checkout completely unmodified. Writes a
throwaway Dockerfile with ONLY official GitHub Releases API fallback clauses;
FRP v0.65.0 archive SHA verification is added, never removed. No real VPS.
"""
from pathlib import Path
import argparse
import subprocess
import sys

EXACT_SOURCE = "b08f375e4ed2cfe1dcbbe4c93ff18864ca833f66"


def generate(source: Path, output: Path) -> None:
    if subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            text=True).strip() != EXACT_SOURCE:
        raise ValueError("HOLD: STAGE24_REVIEWED_SOURCE_DRIFT")
    if subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain", "--", "node/Dockerfile"],
            text=True).strip():
        raise ValueError("HOLD: STAGE24_DOCKERFILE_IS_DIRTY")
    data = (source / "node/Dockerfile").read_text()
    original = data
    opts = "--retry 3 --retry-delay 2 --connect-timeout 15 --max-time 120"
    edits = [
      ('x86_64) ARCH="amd64"; RATHOLE_ARCH="x86_64" ;;',
       'x86_64) ARCH="amd64"; RATHOLE_ARCH="x86_64"; RATHOLE_ASSET=128547246; GOST_ASSET=198232929; CHISEL_ASSET=292957248; FRP_ASSET=297151368; FRP_SHA=52ced8c5fdf772f48a9909da4c10c7568c061861946ac9af7a86eeaf14b7e6d5 ;;'),
      ('aarch64) ARCH="arm64"; RATHOLE_ARCH="aarch64" ;;',
       'aarch64) ARCH="arm64"; RATHOLE_ARCH="aarch64"; RATHOLE_ASSET=""; GOST_ASSET=198232917; CHISEL_ASSET=292957219; FRP_ASSET=297151384; FRP_SHA=d3e2be696d70b8e8dc475a81b8b5e4089f3a2acde5e42e47d6fc020fe3ddb180 ;;'),
      ('curl -fsSL "$RATHOLE_URL" -o "$TMP_DIR/rathole.zip";',
       f'curl -fsSL {opts} "$RATHOLE_URL" -o "$TMP_DIR/rathole.zip" || {{ test -n "$RATHOLE_ASSET" && curl -fsSL {opts} -H "Accept: application/octet-stream" "https://api.github.com/repos/rathole-org/rathole/releases/assets/$RATHOLE_ASSET" -o "$TMP_DIR/rathole.zip"; }};'),
      ('curl -fsSL "$GOST_URL" -o "$GOST_TMP/gost.tar.gz";',
       f'curl -fsSL {opts} "$GOST_URL" -o "$GOST_TMP/gost.tar.gz" || curl -fsSL {opts} -H "Accept: application/octet-stream" "https://api.github.com/repos/ginuerzh/gost/releases/assets/$GOST_ASSET" -o "$GOST_TMP/gost.tar.gz";'),
      ('curl -fsSL "$CHISEL_URL" -o "$CHISEL_TMP/chisel.gz";',
       f'curl -fsSL {opts} "$CHISEL_URL" -o "$CHISEL_TMP/chisel.gz" || curl -fsSL {opts} -H "Accept: application/octet-stream" "https://api.github.com/repos/jpillora/chisel/releases/assets/$CHISEL_ASSET" -o "$CHISEL_TMP/chisel.gz";'),
      ('curl -fsSL "$FRP_URL" -o "$FRP_TMP/frp.tar.gz";',
       f'curl -fsSL {opts} "$FRP_URL" -o "$FRP_TMP/frp.tar.gz" || curl -fsSL {opts} -H "Accept: application/octet-stream" "https://api.github.com/repos/fatedier/frp/releases/assets/$FRP_ASSET" -o "$FRP_TMP/frp.tar.gz"; echo "$FRP_SHA  $FRP_TMP/frp.tar.gz" | sha256sum -c -;'),
      ('x86_64|amd64) PLATFORM="amd64"; EXPECTED_SHA="$BACKHAUL_SHA256_AMD64" ;;',
       'x86_64|amd64) PLATFORM="amd64"; EXPECTED_SHA="$BACKHAUL_SHA256_AMD64"; BACKHAUL_ASSET=289712775 ;;'),
      ('aarch64|arm64) PLATFORM="arm64"; EXPECTED_SHA="$BACKHAUL_SHA256_ARM64" ;;',
       'aarch64|arm64) PLATFORM="arm64"; EXPECTED_SHA="$BACKHAUL_SHA256_ARM64"; BACKHAUL_ASSET=289712774 ;;'),
      ('curl -fsSL "$ASSET_URL" -o "$TMP_DIR/backhaul.tar.gz";',
       f'curl -fsSL {opts} "$ASSET_URL" -o "$TMP_DIR/backhaul.tar.gz" || curl -fsSL {opts} -H "Accept: application/octet-stream" "https://api.github.com/repos/Musixal/Backhaul/releases/assets/$BACKHAUL_ASSET" -o "$TMP_DIR/backhaul.tar.gz";'),
    ]
    for before, after in edits:
        if data.count(before) != 1:
            raise ValueError("HOLD: STAGE24_TRANSPORT_ANCHOR_DRIFT")
        data = data.replace(before, after, 1)
    if original.count('sha256sum -c -') != 1 or data.count('sha256sum -c -') != 2:
        raise ValueError("HOLD: STAGE24_DIGEST_GATE_DRIFT")
    output.write_text(data)
    if (source / "node/Dockerfile").read_text() != original:
        raise ValueError("HOLD: STAGE24_PINNED_SOURCE_CHANGED")
    print("STAGE24_EXACT_SOURCE_AND_OFFICIAL_ASSET_TRANSPORT_ONLY=PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    generate(args.source, args.output)
