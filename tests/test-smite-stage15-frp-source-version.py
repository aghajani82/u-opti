#!/usr/bin/env python3
"""Pin the *declared* FRP version inside the independently reviewed Stage15 Dockerfile.

This checks source provenance, not binary byte provenance. Stage15 downloads an
unpinned upstream FRP archive during the disposable CI image build. No host
activation, Docker execution, network or secrets are involved here.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / ".stage15-foreign-source/node/Dockerfile"


class Stage15FrpDockerBuildContract(unittest.TestCase):
    def test_pinned_stage15_source_still_bundles_legacy_frp_065(self):
        source = DOCKERFILE.read_text()
        versions = re.findall(r'(?m)^\s*FRP_VERSION="(v[0-9]+\.[0-9]+\.[0-9]+)";\s*\\$', source)
        self.assertEqual(versions, ["v0.65.0"])
        for name in ("frpc", "frps"):
            self.assertEqual(
                source.count(
                    f"COPY --from=rathole-bin /usr/local/bin/{name} /usr/local/bin/{name}"
                ), 1,
            )

    def test_unattested_legacy_archive_must_never_be_called_managed_frp(self):
        source = DOCKERFILE.read_text()
        self.assertIn('FRP_URL="https://github.com/fatedier/frp/releases/download/', source)
        self.assertIn('curl -fsSL "$FRP_URL" -o "$FRP_TMP/frp.tar.gz";', source)
        self.assertNotIn('sha256sum -c', source[source.index('echo "Fetching FRP release"'):source.index('rm -rf "$FRP_TMP"')])
        control = (ROOT / "modules/smite-managed-frp-control.py").read_text()
        self.assertIn('STAGE15_BUNDLED_0_65_0', control)
        self.assertIn('FRP_0_71_MANAGED_MATCH', control)
        self.assertIn('HOST_FRP_INSTALL', control)


if __name__ == "__main__":
    unittest.main(verbosity=2)
