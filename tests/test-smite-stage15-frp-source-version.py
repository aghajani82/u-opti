#!/usr/bin/env python3
"""Pin the *declared* FRP version inside the independently reviewed Stage15 Dockerfile.

This checks source provenance, not binary byte provenance. Stage15 downloads an
unpinned upstream FRP archive during the disposable CI image build. No host
activation, Docker execution, network or secrets are involved here.
"""
import ast
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
        # PR #73 accepts only the two independently reviewed local Stage15
        # image IDs; the old source is still 0.65.0 and the PR #39 image
        # is 0.71.0. This is NOT a production attestation or an install grant.
        assignments = {}
        for statement in ast.parse(control).body:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = statement.value
        expected_ids = {
            'STAGE15_NODE_ID': 'sha256:a417e8c28426da5eaf16d59925d5c89b52dbf7849ca560dfa9a765a1266b3991',
            'STAGE15_FRP071_NODE_ID': 'sha256:cf0f3b12fc2c31cb0847fd5206304837661019d8f604853a8e956448c2576265',
        }
        for key, value in expected_ids.items():
            self.assertIn(key, assignments)
            self.assertIsInstance(assignments[key], ast.Constant)
            self.assertEqual(assignments[key].value, value)
        version_map = assignments['STAGE15_NODE_VERSIONS']
        self.assertIsInstance(version_map, ast.Dict)
        self.assertEqual(len(version_map.keys), 2)
        self.assertEqual(
            {
                key.id: value.value
                for key, value in zip(version_map.keys, version_map.values)
                if isinstance(key, ast.Name) and isinstance(value, ast.Constant)
            },
            {'STAGE15_NODE_ID': '0.65.0', 'STAGE15_FRP071_NODE_ID': '0.71.0'},
        )
        # Unknown IDs are rejected and the running image, local tag and
        # bundled executable version must agree before readiness is reported.
        self.assertIn('runtime["Image"] not in STAGE15_NODE_VERSIONS', control)
        self.assertIn('!= runtime["Image"]', control)
        self.assertIn('STAGE15_NODE_VERSIONS[runtime["Image"]]', control)
        self.assertIn('"STAGE15_BUNDLED_" + STAGE15_NODE_VERSIONS', control)
        self.assertIn('"FRP_0_71_MANAGED_MATCH": "NO"', control)
        self.assertIn('"FRP_ENGINE_ENROLLED": "NO"', control)
        self.assertIn('"HOST_FRP_INSTALL": "HOLD_VERSION_AND_SIGNED_WSS_ADMISSION"', control)


if __name__ == "__main__":
    unittest.main(verbosity=2)
