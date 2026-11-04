#!/usr/bin/env python3
"""Offline regression for the actual U-OPTI menu updater download functions.

No GitHub network, root, Docker, Smite, FRP, Backhaul, or installed files.
Run the real function definitions extracted from u-opti with a mocked curl.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
BEGIN = "            # The source SHA is immutable."
END = "            cleanup_update_temp() {"
PIN = "a17c2fe15a9ab66b3f37e3653e710dc9cea01f30"
DATA = b"#!/bin/bash\necho verified\n"


def actual_downloader() -> str:
    source = (ROOT / "u-opti").read_text(encoding="utf-8")
    start = source.index(BEGIN)
    end = source.index(END, start)
    part = source[start:end]
    for required in ("u_opti_prepare_source_tree()", "u_opti_verify_source_blob()",
                     "download_repo_file()", "--connect-timeout 10", "--max-time 90",
                     "HOLD: Download retries exhausted"):
        if required not in part:
            raise AssertionError(f"Missing update safeguard: {required}")
    return part


MOCK_CURL = r'''#!/usr/bin/env python3
import base64, json, os, pathlib, signal, sys, time
args = sys.argv[1:]
out = pathlib.Path(args[args.index("-o") + 1])
url = next(v for v in args if v.startswith("https://"))
log = pathlib.Path(os.environ["MOCK_CURL_LOG"])
with log.open("a", encoding="utf-8") as fp:
    fp.write(" ".join(args) + "\n")
if "/git/trees/" in url:
    out.write_bytes(pathlib.Path(os.environ["MOCK_MANIFEST"]).read_bytes())
    sys.exit(0)
if "/git/blobs/" in url:
    mode = os.environ.get("MOCK_API_MODE", "http403")
    if mode == "http403":
        sys.exit(22)
    if mode == "badjson":
        out.write_text("{not json")
        sys.exit(0)
    raw = pathlib.Path(os.environ["MOCK_CONTENT"]).read_bytes()
    sha = url.rsplit("/", 1)[-1]
    if mode == "badsha":
        sha = "0" * 40
    encoded = base64.b64encode(raw).decode()
    if mode == "badbase64":
        encoded = "$not-base64"
    out.write_text(json.dumps({"encoding": "base64", "sha": sha,
                               "size": len(raw), "content": encoded}))
    sys.exit(0)
counter = pathlib.Path(os.environ["MOCK_CURL_COUNT"])
attempt = int(counter.read_text() if counter.exists() else "0") + 1
counter.write_text(str(attempt))
data = pathlib.Path(os.environ["MOCK_CONTENT"]).read_bytes()
mode = os.environ.get("MOCK_MODE", "success")
if mode == "network":
    print("000", end="")
    sys.exit(7)
if mode == "http404":
    print("404", end="")
    sys.exit(22)
if mode == "timeout" or (mode == "retry" and attempt == 1):
    out.write_bytes(data[:5])
    print("200", end="")
    sys.exit(28)
if mode == "kill":
    out.write_bytes(data[:5])
    pathlib.Path(os.environ["MOCK_STARTED"]).write_text("started")
    time.sleep(60)
    sys.exit(28)
if mode == "partial":
    out.write_bytes(data[:5])
elif mode == "corrupt":
    out.write_bytes(data[:-1] + b"X")
elif mode == "empty":
    out.write_bytes(b"")
else:
    out.write_bytes(data)
print("200", end="")
'''


class DownloadReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="uopti-download-lab-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "bin").mkdir()
        curl = self.root / "bin" / "curl"
        curl.write_text(MOCK_CURL, encoding="utf-8")
        curl.chmod(0o700)
        self.temp = self.root / "stage"
        self.temp.mkdir(mode=0o700)
        self.target = self.temp / "u-opti"
        self.mock_content = self.root / "source-content"
        self.mock_content.write_bytes(DATA)
        self.manifest = self.root / "source-tree.json"
        self.manifest.write_text(json.dumps(self.valid_tree()), encoding="utf-8")
        self.env = {**os.environ,
                    "PATH": str(self.root / "bin") + os.pathsep + os.environ.get("PATH", ""),
                    "MOCK_CURL_LOG": str(self.root / "calls"),
                    "MOCK_CURL_COUNT": str(self.root / "attempts"),
                    "MOCK_CONTENT": str(self.mock_content),
                    "MOCK_MANIFEST": str(self.manifest),
                    "MOCK_STARTED": str(self.root / "started"),
                    "MOCK_SOURCE_SHA": PIN,
                    "MOCK_STAGE": str(self.temp),
                    "MOCK_TARGET": str(self.target)}

    @staticmethod
    def valid_tree():
        digest = hashlib.sha1(b"blob " + str(len(DATA)).encode() + b"\0" + DATA).hexdigest()
        return {"sha": "a" * 40, "truncated": False,
                "tree": [{"path": "u-opti", "type": "blob", "mode": "100644",
                          "size": len(DATA), "sha": digest}]}

    def run_download(self, mode="success", *, load_tree=False, api="http403", timeout=12):
        env = {**self.env, "MOCK_MODE": mode, "MOCK_API_MODE": api}
        prelude = (
            'TEMP_DIR="$MOCK_STAGE"\n'
            'SOURCE_SHA="$MOCK_SOURCE_SHA"\n'
            'UPDATE_TREE_MANIFEST="$MOCK_MANIFEST"\n'
            'UPDATE_RAW_BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$SOURCE_SHA"\n'
        )
        script = prelude + actual_downloader() + (
            '\nu_opti_prepare_source_tree' if load_tree
            else '\ndownload_repo_file "u-opti" "$MOCK_TARGET"'
        )
        return subprocess.run(["bash", "-c", script], env=env,
                              capture_output=True, text=True, timeout=timeout)

    def calls(self):
        path = self.root / "calls"
        return path.read_text().splitlines() if path.exists() else []

    def raw_calls(self):
        return [c for c in self.calls() if "raw.githubusercontent.com/" in c]

    def api_calls(self):
        return [c for c in self.calls() if "/git/blobs/" in c]

    def assert_unmodified(self):
        self.assertEqual(self.target.read_bytes(), b"old-installed-content")
        self.assertFalse(list(self.temp.glob(".uopti-download-*")))
        self.assertFalse(list(self.temp.glob(".uopti-blob-json-*")))

    def test_good_download_atomically_replaces_staged_file(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.target.read_bytes(), DATA)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn(PIN + "/u-opti", self.calls()[0])
        self.assertNotIn("?cb=", self.calls()[0])
        self.assertIn("--connect-timeout 10", self.calls()[0])
        self.assertIn("--max-time 90", self.calls()[0])
        self.assertFalse(list(self.temp.glob(".uopti-download-*")))

    def test_timeout_does_not_replace_original(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("timeout")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("curl=28", proc.stderr)
        self.assertIn("attempt 3/3", proc.stderr)
        self.assertEqual(len(self.raw_calls()), 3)
        self.assertEqual(len(self.api_calls()), 1)
        self.assert_unmodified()

    def test_failure_to_connect_has_bounded_retries(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("network")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("curl=7", proc.stderr)
        self.assertEqual(len(self.raw_calls()), 3)
        self.assertEqual(len(self.api_calls()), 1)
        self.assert_unmodified()

    def test_http_error_has_diagnostic(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("http404")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("HTTP=404", proc.stderr)
        self.assert_unmodified()

    def test_success_after_retry(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("retry")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.target.read_bytes(), DATA)
        self.assertIn("curl=28", proc.stderr)
        self.assertEqual(len(self.raw_calls()), 2)
        self.assertEqual(len(self.api_calls()), 1)

    def test_raw_timeout_recovers_via_pinned_api_blob(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("timeout", api="success")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.target.read_bytes(), DATA)
        self.assertIn("GitHub API fallback verified", proc.stderr)
        self.assertEqual(len(self.raw_calls()), 1)
        self.assertEqual(len(self.api_calls()), 1)
        self.assertIn("--max-time 75", self.api_calls()[0])
        self.assertIn(self.valid_tree()["tree"][0]["sha"], self.api_calls()[0])
        self.assertFalse(list(self.temp.glob(".uopti-blob-json-*")))

    def test_api_rate_limit_fails_closed_after_raw_retries(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("timeout", api="http403")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("fallback unavailable", proc.stderr)
        self.assertEqual(len(self.raw_calls()), 3)
        self.assertEqual(len(self.api_calls()), 1)
        self.assert_unmodified()

    def test_api_bad_json_cannot_publish(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("timeout", api="badjson")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("API blob response failed pinned integrity", proc.stderr)
        self.assert_unmodified()

    def test_api_wrong_sha_cannot_publish(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("timeout", api="badsha")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("API blob response failed pinned integrity", proc.stderr)
        self.assert_unmodified()

    def test_api_invalid_base64_cannot_publish(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("timeout", api="badbase64")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("API blob response failed pinned integrity", proc.stderr)
        self.assert_unmodified()

    def test_api_fallback_rejects_untrusted_tree_sha(self):
        self.target.write_bytes(b"old-installed-content")
        tree = self.valid_tree()
        tree["tree"][0]["sha"] = "f" * 40
        self.manifest.write_text(json.dumps(tree))
        proc = self.run_download("timeout", api="success")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Git blob SHA mismatch", proc.stderr) if "Git blob SHA mismatch" in proc.stderr else self.assertIn("API blob response failed pinned integrity", proc.stderr)
        self.assert_unmodified()

    def test_http_200_partial_payload_fails_integrity(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("partial")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("integrity verification failed", proc.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assert_unmodified()

    def test_same_size_corrupt_payload_fails_git_blob(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("corrupt")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Git blob SHA mismatch", proc.stderr)
        self.assert_unmodified()

    def test_empty_payload_is_not_accepted(self):
        self.target.write_bytes(b"old-installed-content")
        proc = self.run_download("empty")
        self.assertNotEqual(proc.returncode, 0)
        self.assert_unmodified()

    def test_duplicate_or_missing_manifest_path_fails_closed(self):
        for variant in ("duplicate", "missing", "truncated", "sha"):
            with self.subTest(variant=variant):
                tree = self.valid_tree()
                if variant == "duplicate":
                    tree["tree"].append(dict(tree["tree"][0]))
                elif variant == "missing":
                    tree["tree"][0]["path"] = "other"
                elif variant == "truncated":
                    tree["truncated"] = True
                else:
                    tree["tree"][0]["sha"] = "0" * 40
                self.manifest.write_text(json.dumps(tree))
                self.target.write_bytes(b"old-installed-content")
                proc = self.run_download()
                self.assertNotEqual(proc.returncode, 0)
                self.assert_unmodified()

    def test_tree_retrieval_rejects_truncated_or_invalid_json(self):
        for value in ('{"truncated":true,"sha":"' + "a"*40 + '","tree":[{}]}',
                      "not-json"):
            with self.subTest(value=value[:15]):
                self.manifest.write_text(value)
                proc = self.run_download(load_tree=True)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("HOLD: Invalid or truncated", proc.stderr)

    def test_symlink_destination_is_rejected(self):
        outside = self.root / "outside"
        outside.write_bytes(b"old-installed-content")
        self.target.symlink_to(outside)
        proc = self.run_download()
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(outside.read_bytes(), b"old-installed-content")
        self.assertFalse(self.calls())

    def test_sigkill_during_download_leaves_original_and_no_live_writes(self):
        self.target.write_bytes(b"old-installed-content")
        script = (
            'TEMP_DIR="$MOCK_STAGE"\n'
            'UPDATE_TREE_MANIFEST="$MOCK_MANIFEST"\n'
            'UPDATE_RAW_BASE_URL="https://raw.githubusercontent.com/aghajani82/u-opti/$MOCK_SOURCE_SHA"\n'
            + actual_downloader() + '\ndownload_repo_file "u-opti" "$MOCK_TARGET"'
        )
        proc = subprocess.Popen(["bash", "-c", script],
                                env={**self.env, "MOCK_MODE": "kill"},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        try:
            end = time.monotonic() + 8
            while not (self.root / "started").exists() and time.monotonic() < end:
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
            self.assertTrue((self.root / "started").exists(), "mock curl never began")
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=4)
            self.assertEqual(self.target.read_bytes(), b"old-installed-content")
            # SIGKILL cannot run a cleanup trap. Unpublished stage junk is safe.
            self.assertTrue(list(self.temp.glob(".uopti-download-*")))
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=4)
        # Existing temp-dir cleanup and transactional startup rescue are unchanged.
        for junk in self.temp.glob(".uopti-download-*"):
            junk.unlink()
        self.assertEqual(self.run_download("success").returncode, 0)
        self.assertEqual(self.target.read_bytes(), DATA)


if __name__ == "__main__":
    unittest.main(verbosity=2)
