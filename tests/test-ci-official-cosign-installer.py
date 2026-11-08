#!/usr/bin/env python3
"""CI-only guard: official Cosign transport fallback must keep both signatures."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
script = (root / "tests/ci-install-official-cosign.sh").read_text()
workflow = (root / ".github/workflows/ci.yml").read_text()
assert 'set -euo pipefail' in script
assert 'https://github.com/sigstore/cosign/releases/download/' in script
assert 'https://api.github.com/repos/sigstore/cosign/releases/assets/' in script
assert 'Accept: application/octet-stream' in script
for required in (
    'v3.0.5 cosign-linux-amd64 358750885',
    'db15cc99e6e4837daabab023742aaddc3841ce57f193d11b7c3e06c8003642b2',
    'v3.0.6 cosign-linux-amd64 390331694',
    'c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74',
    'v3.0.6 cosign-linux-amd64.sigstore.json 390332772',
    'b3a04913f3a3f4a38e4a7a42b8d590834b8791de99ddeaad66c608b6aa8e02a4',
    'v3.0.6 cosign-linux-amd64-kms.sigstore.json 390332714',
    '9f2728c7876e82561d1f4d2837e2a14180ff0fba1aeffd59163c48aea68cd519',
    'f4cea466e5e887a45da5031757fa1d32655d83420639dc1758749b744179f126',
    '--certificate-identity=keyless@projectsigstore.iam.gserviceaccount.com',
    '--certificate-oidc-issuer=https://accounts.google.com',
    '--bundle keyless.sigstore.json desired',
    '--key release-cosign.pub --bundle kms.sigstore.json desired',
    "'CI_COSIGN_OFFICIAL_SHA256_KEYLESS_KMS=PASS'",
):
    assert required in script, f"CI_COSIGN_VERIFICATION_MISSING:{required[:30]}"
assert script.count('./bootstrap verify-blob') == 2
assert 'sha256sum -c -' in script
assert 'skip-verification' not in script and 'insecure' not in script
assert 'bash tests/ci-install-official-cosign.sh' in workflow
assert 'bash -n tests/ci-install-official-cosign.sh' in workflow
print('CI_COSIGN_OFFICIAL_DUAL_SIGNATURE_FAIL_CLOSED=PASS')
