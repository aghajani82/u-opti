#!/usr/bin/env python3
"""Offline installer download regression using the actual shell functions.

Mocks curl, GitHub tree and blob APIs. Never calls apt, connects to GitHub,
modifies a VPS, touches installed U-OPTI, or needs root privileges.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
BEGIN = "# BEGIN: U-OPTI installer bounded and verified GitHub downloads"
END = "# END: U-OPTI installer bounded and verified GitHub downloads"
PIN = "ab" * 20

FILES = {
    "VERSION": b"0.17.8\n",
    "u-opti": b"#!/bin/bash\necho trusted\n",
    "lib/common.sh": b"#!/bin/bash\n# trusted library\n",
    "modules/alpha.sh": b"#!/bin/bash\necho alpha\n",
}

MOCK_CURL = r'''#!/usr/bin/env python3
import base64, json, os, pathlib, sys
argv = sys.argv[1:]
url = next(x for x in argv if x.startswith("https://"))
out = pathlib.Path(argv[argv.index("-o") + 1])
with open(os.environ["MOCK_CALLS"], "a") as fp:
    fp.write(" ".join(argv) + "\n")
if "/git/trees/" in url:
    tree = json.loads(pathlib.Path(os.environ["MOCK_MANIFEST"]).read_text())
    if os.environ.get("MOCK_TREE") == "truncated":
        tree["truncated"] = True
    if os.environ.get("MOCK_TREE") == "missing":
        tree["tree"] = tree["tree"][:-1]
    out.write_text(json.dumps(tree))
    sys.exit(0)
if "/git/blobs/" in url:
    mode = os.environ.get("MOCK_API", "valid")
    if mode == "network":
        sys.exit(56)
    expected = url.rsplit("/", 1)[-1]
    data = pathlib.Path(os.environ["MOCK_PAYLOAD"]).read_bytes()
    if mode == "badsha":
        expected = "0" * 40
    content = base64.b64encode(data).decode()
    if mode == "badbase64":
        content = "#invalid base64!"
    out.write_text(json.dumps({
        "sha": expected, "encoding": "base64",
        "size": len(data), "content": content,
    }))
    sys.exit(0)
if "raw.githubusercontent.com/" not in url:
    sys.exit(22)
mode = os.environ.get("MOCK_RAW", "good")
attempt = pathlib.Path(os.environ["MOCK_RAW_COUNT"])
count = int(attempt.read_text()) + 1 if attempt.exists() else 1
attempt.write_text(str(count))
data = pathlib.Path(os.environ["MOCK_PAYLOAD"]).read_bytes()
if mode in ("timeout", "retry") and (mode == "timeout" or count == 1):
    out.write_bytes(data[:5])
    sys.exit(56)
if mode == "partial":
    out.write_bytes(data[:5])
    sys.exit(0)
if mode == "corrupt":
    out.write_bytes(data[:-1] + b"X")
    sys.exit(0)
out.write_bytes(data)
'''

def git_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def actual_installer_functions() -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    assert text.count(BEGIN) == text.count(END) == 1
    part = text[text.index(BEGIN):text.index(END) + len(END)]
    for guard in (
        "u_opti_install_prepare_tree()",
        "u_opti_install_verify_blob()",
        "u_opti_install_api_fallback()",
        "u_opti_install_download()",
        "--connect-timeout 8",
        "--max-time 30",
        "--max-time 40",
        "--speed-time 15",
        "git/trees/$SOURCE_SHA?recursive=1",
        "git/blobs/$blob_sha",
        "HOLD: Download failed after bounded retries",
    ):
        assert guard in part, f"Installer safeguard missing: {guard}"
    assert "?cb=" not in part
    return part


class InstallerDownloadTest(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory(prefix="uopti-install-fetch-test-")
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        curl = self.bin / "curl"
        curl.write_text(MOCK_CURL)
        curl.chmod(0o700)
        self.stage = self.root / "stage"
        self.stage.mkdir(mode=0o700)
        self.payload = self.root / "raw-content"
        self.calls = self.root / "calls"
        self.count = self.root / "raw-count"
        self.manifest = self.root / "manifest"
        self.manifest.write_text(json.dumps({
            "truncated": False,
            "sha": "f" * 40,
            "tree": [
                {"path": path, "mode": "100644", "type": "blob",
                 "size": len(content), "sha": git_sha(content)}
                for path, content in FILES.items()
            ],
        }))
        self.env = {**os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "MOCK_CALLS": str(self.calls),
            "MOCK_MANIFEST": str(self.manifest),
            "MOCK_RAW_COUNT": str(self.count),
            "MOCK_PAYLOAD": str(self.payload),
        }

    def run_case(self, *, source="u-opti", raw="good", api="valid",
                 tree="valid", dest="valid", timeout=12):
        self.payload.write_bytes(FILES.get(source, FILES["u-opti"]))
        self.env.update({"MOCK_RAW": raw, "MOCK_API": api, "MOCK_TREE": tree})
        target = self.stage / "u-opti"
        target.write_bytes(b"old-staged-bytes")
        destination = str(target if dest == "valid" else self.root / "unsafe")
        setup = (
            f"TEMP_DIR={str(self.stage)!r}\n"
            f"SOURCE_SHA={PIN}\n"
            f"BASE_URL=https://raw.githubusercontent.com/aghajani82/u-opti/{PIN}\n"
            "MODULES=(alpha.sh)\n"
        )
        code = (
            setup + actual_installer_functions() + "\n"
            "u_opti_install_prepare_tree || exit 21\n"
            f"u_opti_install_download {source!r} {destination!r}\n"
        )
        result = subprocess.run(
            ["bash", "-c", code], env=self.env, capture_output=True,
            text=True, timeout=timeout,
        )
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        return result, target.read_bytes(), calls

    def test_pinned_raw_success_verifies_and_stages(self):
        result, data, calls = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data, FILES["u-opti"])
        self.assertEqual(sum("/git/blobs/" in x for x in calls), 0)
        self.assertTrue(all("--connect-timeout 8" in x and "--max-time" in x
                            and " -4 " in " " + x + " " for x in calls))
        self.assertFalse(any("?cb=" in x for x in calls))

    def test_raw_timeout_falls_back_to_verified_api_blob(self):
        result, data, calls = self.run_case(raw="timeout")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data, FILES["u-opti"])
        self.assertEqual(sum("/git/blobs/" in x for x in calls), 1)
        self.assertEqual(sum("raw.githubusercontent.com/" in x for x in calls), 1)

    def test_raw_partial_200_never_accepted(self):
        result, data, calls = self.run_case(raw="partial", api="network")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(data, b"old-staged-bytes")
        self.assertIn("HOLD: Download failed", result.stderr)
        self.assertEqual(sum("raw.githubusercontent.com/" in x for x in calls), 2)

    def test_raw_corruption_is_rejected_even_with_http_success(self):
        result, data, _ = self.run_case(raw="corrupt", api="network")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(data, b"old-staged-bytes")

    def test_invalid_api_fallback_cannot_bypass_checksum(self):
        for mode in ("badsha", "badbase64"):
            with self.subTest(api=mode):
                result, data, _ = self.run_case(raw="timeout", api=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(data, b"old-staged-bytes")
                self.count.unlink(missing_ok=True)

    def test_second_raw_attempt_can_recover_after_api_failure(self):
        result, data, calls = self.run_case(raw="retry", api="network")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data, FILES["u-opti"])
        self.assertEqual(sum("raw.githubusercontent.com/" in x for x in calls), 2)

    def test_invalid_manifest_fails_closed_before_staging(self):
        for mode in ("truncated", "missing"):
            with self.subTest(tree=mode):
                result, data, calls = self.run_case(tree=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(data, b"old-staged-bytes")
                self.assertFalse(any("raw.githubusercontent.com/" in x for x in calls))

    def test_rejects_unsafe_download_destination(self):
        result, data, _ = self.run_case(dest="outside")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsafe installer download path", result.stderr)
        self.assertEqual(data, b"old-staged-bytes")
        self.assertFalse((self.root / "unsafe").exists())

    def test_installer_uses_verified_functions_for_each_staged_file(self):
        source = INSTALLER.read_text()
        for call in (
            'u_opti_install_download "VERSION" "$TEMP_DIR/VERSION"',
            'u_opti_install_download "u-opti" "$TEMP_DIR/u-opti"',
            'u_opti_install_download "lib/common.sh" "$TEMP_DIR/common.sh"',
            'u_opti_install_download "modules/$MODULE" "$TEMP_DIR/$MODULE"',
        ):
            self.assertIn(call, source)
        self.assertNotIn("CACHE_BUST", source)
        self.assertLess(source.index("if ! u_opti_install_prepare_tree; then"),
                        source.index('echo "Downloading VERSION..."'))
        self.assertLess(source.index('u_opti_install_download "u-opti"'),
                        source.index('echo "Preparing recoverable installation transaction..."'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
