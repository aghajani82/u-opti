#!/usr/bin/env python3
"""Fail-closed immutable source SHA pin regression for U-OPTI install/update.

Uses exactly the Bash resolver from both install.sh and u-opti, a mocked
curl in private PATH and no external network, root, VPS, or live writes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BEGIN = "# BEGIN: U-OPTI immutable per-operation source pin"
END = "# END: U-OPTI immutable per-operation source pin"
GOOD = "0123456789abcdef" * 2 + "12345678"


def resolver(source_file: str) -> str:
    text = (ROOT / source_file).read_text()
    begin = text.find(BEGIN)
    end = text.find(END, begin)
    if begin < 0 or end < 0:
        raise AssertionError(f"{source_file}: shared source pin resolver missing")
    result = text[begin:end + len(END)]
    if text.count(BEGIN) != 1:
        raise AssertionError("Multiple version resolution implementations")
    return result


class SourcePinTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="uopti-source-pin-lab-")
        self.addCleanup(self.sandbox.cleanup)
        root = Path(self.sandbox.name)
        binary = root / "bin"
        binary.mkdir()
        self.log = root / "curl-argv.log"
        curl = binary / "curl"
        curl.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$*" >> "$MOCK_CURL_LOG"\n'
            '[ "${MOCK_HTTP_FAIL:-0}" = "0" ] || exit 22\n'
            'printf "%s" "$MOCK_HTTP_JSON"\n'
        )
        curl.chmod(0o700)
        self.env = {**os.environ, "PATH": str(binary) + os.pathsep
                    + os.environ.get("PATH", ""),
                    "MOCK_CURL_LOG": str(self.log)}

    def run_resolve(self, ref, *, payload=None, http_fail=False):
        env = {**self.env,
               "MOCK_HTTP_JSON": payload if payload is not None
               else json.dumps({"sha": GOOD}),
               "MOCK_HTTP_FAIL": "1" if http_fail else "0"}
        return subprocess.run(
            ["bash", "-c",
             resolver("install.sh") + '\nu_opti_resolve_source_sha "$1"',
             "source-lock-lab", ref],
            env=env, capture_output=True, text=True, timeout=10,
        )

    def test_both_entrypoints_use_identical_resolver(self):
        self.assertEqual(resolver("install.sh"), resolver("u-opti"))

    def test_ref_is_resolved_once_to_immutable_sha(self):
        result = self.run_resolve("feature/closeout-ref")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), GOOD)
        calls = self.log.read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertIn(
            "https://api.github.com/repos/aghajani82/u-opti/commits/feature/closeout-ref",
            calls[0],
        )

    def test_invalid_or_failed_resolution_holds(self):
        for ref in ("../main", "/refs/heads/main", "main?z=1", "bad ref"):
            with self.subTest(ref=ref):
                result = self.run_resolve(ref)
                self.assertNotEqual(result.returncode, 0)
        with self.subTest("network-failure"):
            self.assertNotEqual(self.run_resolve("main", http_fail=True).returncode, 0)
        for invalid in (
            "{}", "not json", '{"sha":"123"}',
            json.dumps({"sha": "A" * 40}),
            json.dumps({"sha": GOOD + "9"}),
        ):
            with self.subTest(invalid=invalid[:25]):
                self.assertNotEqual(
                    self.run_resolve("main", payload=invalid).returncode, 0
                )

    def test_install_and_update_download_from_resolved_sha_not_live_branch(self):
        install = (ROOT / "install.sh").read_text()
        updater = (ROOT / "u-opti").read_text()
        marker = 'SOURCE_SHA="$(u_opti_resolve_source_sha "$BRANCH")"'
        self.assertEqual(install.count(marker), 1)
        self.assertEqual(updater.count(marker), 1)
        self.assertIn(
            'BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$SOURCE_SHA"',
            install,
        )
        self.assertIn(
            'UPDATE_RAW_BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$SOURCE_SHA"',
            updater,
        )
        self.assertIn(
            '"${UPDATE_RAW_BASE_URL}/${REPO_PATH}?cb=${CACHE_BUST}"',
            updater,
        )
        self.assertNotIn('"${BASE_URL}/${REPO_PATH}?ref=${BRANCH}', updater)
        self.assertLess(install.index(marker), install.index('echo "Downloading VERSION..."'))
        self.assertLess(
            updater.index(marker), updater.index('echo "Downloading VERSION..."')
        )
        # The selected ref is now included in the SAME crash-safe journal
        # as the source-locked executable and VERSION, not written later.
        for script in (install, updater):
            self.assertIn('--source-ref "$BRANCH"', script)
            self.assertNotIn('"$LIB_PATH/INSTALL_REF.new"', script)
        transaction = (ROOT / "modules/u-opti-update-transaction.py").read_text()
        self.assertIn('items["INSTALL_REF"] = lib / "INSTALL_REF"', transaction)



if __name__ == "__main__":
    unittest.main(verbosity=2)
