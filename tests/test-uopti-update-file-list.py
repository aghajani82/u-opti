#!/usr/bin/env python3
"""Regression: critical Smite broker files must participate in U-OPTI updates."""
from __future__ import annotations

import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "u-opti"

CRITICAL_BROKER_FILES = {
    "smite-clean-rc-preflight.sh",
    "smite-xhttp-nginx-route",
    "smite_xhttp_nginx_plan.py",
    "smite-rc5-xhttp-root-broker.py",
    "smite-rc5-xhttp-broker-provision.py",
    "smite-rc5-xhttp-nonce-ledger.py",
    "smite-rc5-xhttp-signed-intent.py",
    "smite-rc5-xhttp-bridge-install.py",
    "smite-rc5-xhttp-bridge-admission.py",
}


def array_body(source: str, name: str) -> str:
    match = re.search(rf"\b{name}\s*=\((.*?)^\s*\)", source, re.M | re.S)
    if not match:
        raise AssertionError(f"Could not find updater array {name}")
    return match.group(1)


def quoted_names(body: str) -> set[str]:
    return set(re.findall(r'"([^"\n]+)"', body))


class UpdaterFileListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = UPDATER.read_text()

    def test_broker_modules_are_downloaded_compared_and_backed_up(self):
        names = {
            "UPDATE_FILE_NAMES": quoted_names(array_body(self.source, "UPDATE_FILE_NAMES")),
            "UPDATE_URLS": quoted_names(array_body(self.source, "UPDATE_URLS")),
            "UPDATE_TARGETS": quoted_names(array_body(self.source, "UPDATE_TARGETS")),
            "BACKUP_FILES": quoted_names(array_body(self.source, "BACKUP_FILES")),
        }
        for array, items in names.items():
            with self.subTest(array=array):
                self.assertTrue(
                    CRITICAL_BROKER_FILES.issubset(items),
                    f"{array} missing: {sorted(CRITICAL_BROKER_FILES - items)}",
                )


    def test_extensionless_xhttp_route_is_checked_as_python(self):
        """Prevent the updater from running bash -n on a Python helper."""
        helper = ROOT / "modules/smite-xhttp-nginx-route"
        source = helper.read_text()
        self.assertTrue(source.startswith("#!/usr/bin/env python3"))
        compile(source, str(helper), "exec")
        self.assertIn("smite-xhttp-nginx-route", quoted_names(array_body(self.source, "UPDATE_FILE_NAMES")))
        self.assertIn(
            '"$TEMP_DIR/"*.py|"$TEMP_DIR/smite-xhttp-nginx-route")',
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
