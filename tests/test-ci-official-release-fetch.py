#!/usr/bin/env python3
"""Offline CI guards for exact official release downloads and Stage24 source."""
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
fetch = (root / 'tests/ci-fetch-official-release.sh').read_text()
overlay = (root / 'tests/ci-stage24-release-transport.py').read_text()
lab = (root / 'tests/test-smite-stage24-compose-runtime.sh').read_text()
for literal in (
    'set -euo pipefail',
    '514042277', '514042211',
    '289712775', '289712774',
    '84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716',
    '57bf95c2eabeddb1152d2e94ac42f4310883ce0fb909ee2a57bd53503b2dabbc',
    'sha256sum -c -', 'api.github.com/repos/$api_repo/releases/assets/$asset_id',
    'Accept: application/octet-stream',
    'CI_OFFICIAL_RELEASE_URL_NOT_ALLOWLISTED',
):
    assert literal in fetch, 'CI_OFFICIAL_RELEASE_PIN_MISSING'
for literal in (
    'b08f375e4ed2cfe1dcbbe4c93ff18864ca833f66',
    'git', 'status', '--porcelain',
    '52ced8c5fdf772f48a9909da4c10c7568c061861946ac9af7a86eeaf14b7e6d5',
    'sha256sum -c -', 'STAGE24_PINNED_SOURCE_CHANGED',
):
    assert literal in overlay, 'STAGE24_SOURCE_OR_PIN_GATE_MISSING'
assert 'ci-stage24-release-transport.py' in lab
assert 'docker build -q -f "$lab/ci-stage24.Dockerfile"' in lab
assert 'ghproxy' not in fetch.lower() and 'skip-verify' not in fetch.lower()
failure = subprocess.run(
    ['bash', '-c',
     'source "$1"; ci_fetch_official_release https://example.invalid/unknown "$2"',
     '_', str(root / 'tests/ci-fetch-official-release.sh'), '/tmp/never-ci-unapproved'],
    capture_output=True, text=True, timeout=5)
assert failure.returncode != 0 and 'URL_NOT_ALLOWLISTED' in failure.stderr
print('CI_OFFICIAL_RELEASE_ALLOWLIST_AND_EXACT_SOURCE=PASS')
