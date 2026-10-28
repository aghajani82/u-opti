#!/usr/bin/env python3
"""Build a deterministic REVIEW/HOLD bundle; never download, install or deploy.

Inputs must be exact git commits plus independently verified existing artifacts.
This is not an offline Ubuntu/Sanaei distribution or a production release.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

STAGE15 = '4e16633a304db6c03f7f2911cc7d77213b0c4ec1'
MANIFEST = 'fe32c9c54714cfdb482f27112829eba13d5188e9e1e7e26c7266d8d54e85462a'
ROOT = Path(__file__).resolve().parents[1]

def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'modules' / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])

def snapshot(repo, sha):
    if not re.fullmatch('[a-f0-9]{40}', sha):
        raise ValueError('Exact commit required')
    if git(repo, 'rev-parse', sha + '^{commit}').decode().strip() != sha:
        raise ValueError('Commit mismatch')
    with tarfile.open(fileobj=io.BytesIO(git(repo, 'archive', sha))) as tar:
        for member in tar:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk():
                raise ValueError('Unsafe source archive entry')
            if member.isfile():
                yield member.name, tar.extractfile(member).read(), member.mode

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--uopti-sha', required=True)
    ap.add_argument('--smite-repo', type=Path, required=True)
    ap.add_argument('--smite-sha', required=True)
    ap.add_argument('--images', type=Path, required=True)
    ap.add_argument('--frp-dir', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    verifier = module('bundle_verify', 'smite-stage15-bundle-verify.py')
    doc = verifier.verify(folder=args.images, source_sha=STAGE15, manifest_sha=MANIFEST)
    frp = module('frp_bundle', 'smite-managed-frp.py')
    deps = []
    for arch, sha in frp.OFFICIAL_TAR_SHA256.items():
        path = args.frp_dir / f'frp_0.71.0_linux_{arch}.tar.gz'
        frp.unpack(path, arch=arch, trusted_sha=sha)
        deps.append(path)
    # Never package an arbitrary working tree, .git credentials or live state.
    files = {}
    for prefix, repo, sha in (
        ('u-opti', ROOT, args.uopti_sha),
        ('Smite-current-source', args.smite_repo, args.smite_sha),
        ('Smite-stage15-build-source', args.smite_repo, STAGE15),
    ):
        for name, data, mode in snapshot(repo, sha):
            files[prefix + '/' + name] = (data, mode)
    versions = {
        'status': 'HOLD_WITH_BLOCKERS', 'production_release': False,
        'uopti_commit': args.uopti_sha, 'smite_current_source': args.smite_sha,
        'stage15_image_source': STAGE15, 'stage15_manifest_sha256': MANIFEST,
        'stage15_images': doc['images'], 'frp_archive_sha256': frp.OFFICIAL_TAR_SHA256,
        'online_dependencies': ['Ubuntu apt packages', 'Docker Engine and Compose plugin',
                                'Nginx and Certbot', 'Sanaei image and installer'],
        'not_completed': ['Stage15 WSS transaction', 'two-host FRP/XHTTP traffic',
                          'reboot acceptance', 'replacement images with FRPS log fix'],
    }
    files['VERSIONS.json'] = ((json.dumps(versions, indent=2) + '\n').encode(), 0o644)
    files['README-FA.md'] = (files['u-opti/docs/SMITE-INTEGRATED-BUNDLE-FA.md'][0], 0o644)
    launch = '''#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(readlink -f -- "$0")")"
[[ "${1:-}" == IR || "${1:-}" == KH ]] || { echo 'Usage: bash start.sh IR|KH'; exit 2; }
[[ "$EUID" == 0 ]] || { echo 'HOLD: root required'; exit 2; }
[[ "$(hostname -s | tr '[:lower:]' '[:upper:]')" == "$1" ]] || { echo 'HOLD: disposable IR/KH only'; exit 2; }
[[ "$(uname -m)" == x86_64 ]] || { echo 'HOLD: Stage15 image pair is amd64 only'; exit 2; }
sha256sum --check --strict --quiet SHA256SUMS
export U_OPTI_BRANCH='UOPTI_COMMIT'
export SMITE_RC_BUNDLE_DIR="$PWD/images"
export SMITE_RC_SOURCE_SHA='SMITE_COMMIT'
export SMITE_RC_MANIFEST_SHA256='MANIFEST_HASH'
if [[ -e /usr/local/bin/u-opti ]]; then
    [[ ! -L /usr/local/lib/u-opti/INSTALL_REF && "$(cat /usr/local/lib/u-opti/INSTALL_REF)" == "$U_OPTI_BRANCH" ]] || {
        echo 'HOLD: update existing U-OPTI to VERSIONS.json commit through its Update menu first.'; exit 2;
    }
else
    bash ./u-opti/install.sh
fi
echo 'Core wizard only. FRP/WSS/XHTTP acceptance remains HOLD. Read README-FA.md.'
exec /usr/local/bin/u-opti --smite-clean-rc
'''.replace('UOPTI_COMMIT', args.uopti_sha).replace('SMITE_COMMIT', STAGE15).replace('MANIFEST_HASH', MANIFEST)
    files['start.sh'] = (launch.encode(), 0o755)
    external = [(f'images/{name}', args.images / name) for name in
                ['stage15-images.json', *verifier.FILES.values()]]
    external += [('dependencies/' + p.name, p) for p in deps]
    # Fixed timestamps and order produce the same ZIP from the same inputs.
    checks = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'x', allowZip64=True) as z:
        def put(name, data, mode):
            info = zipfile.ZipInfo(name, (2026, 10, 28, 0, 0, 0))
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_STORED if name.endswith('.gz') else zipfile.ZIP_DEFLATED
            z.writestr(info, data)
            checks.append(hashlib.sha256(data).hexdigest() + '  ' + name + '\n')
        for name, (data, mode) in sorted(files.items()):
            put(name, data, mode)
        for name, path in sorted(external):
            put(name, path.read_bytes(), 0o644)
        put('SHA256SUMS', ''.join(checks).encode(), 0o644)
    with args.output.open('rb') as f:
        checksum = hashlib.file_digest(f, 'sha256').hexdigest()
    args.output.with_suffix('.zip.sha256').write_text(checksum + '  ' + args.output.name + '\n')
    print(checksum + '  ' + args.output.name)

if __name__ == '__main__':
    main()
