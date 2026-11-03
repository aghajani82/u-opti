#!/usr/bin/env python3
"""Offline tests for RC7 transaction Compose project detection and journal binding."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules/smite-gateway.sh"


def run_journal_validator(journal: Path, project: str):
    source = SOURCE.read_text()
    match = re.search(r"<<'PY_RC7_GATEWAY_JOURNAL'\n(.*?)\nPY_RC7_GATEWAY_JOURNAL", source, re.S)
    assert match, "Real gateway journal validation not found"
    script = match.group(1).replace(
        'Path("/var/lib/u-opti/rc6-install-journal/current.json")',
        "Path(" + repr(str(journal)) + ")",
    )
    return subprocess.run(
        ["python3", "-B", "-", project],
        input=script, text=True, capture_output=True, timeout=10,
    )


class GatewayComposeOwnerTest(unittest.TestCase):
    def test_node_recreation_all_paths_use_verified_project(self):
        source = SOURCE.read_text()
        self.assertIn('node_project="$(smite_gateway_node_compose_project)" || return 1', source)
        self.assertEqual(source.count(
            'docker compose --project-name "$node_project" -f "$compose_file" up -d --no-build --force-recreate smite-node'
        ), 3)
        self.assertNotIn('docker compose -f "$compose_file" up -d --no-build --force-recreate smite-node', source)
        self.assertLess(source.index('node_project="$(smite_gateway_node_compose_project)"'),
                        source.index('sed -i "s|^PANEL_ADDRESS='))

    def test_rc7_committed_owner_and_private_file_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "current.json"
            project = "uopti_rc6_" + "a" * 32
            path.write_text('{"id":"' + project + '","state":"COMMITTED","role":"panel-iran"}')
            path.chmod(0o600)
            # Sandbox user is not necessarily root: owner check deliberately
            # makes valid fixtures pass only in root-run CI if root.
            if os.geteuid() == 0:
                self.assertEqual(run_journal_validator(path, project).returncode, 0)
            else:
                self.assertIn("HOLD:", run_journal_validator(path, project).stderr)
            for contents in (
                '{"id":"' + project + '","state":"INSTALLING","role":"panel-iran"}',
                '{"id":"' + project + '","state":"COMMITTED","role":"foreign"}',
                '{"id":"uopti_rc6_' + "b" * 32 + '","state":"COMMITTED","role":"panel-iran"}',
                "not json",
            ):
                path.write_text(contents)
                path.chmod(0o600)
                self.assertNotEqual(run_journal_validator(path, project).returncode, 0)
            path.write_text('{"id":"' + project + '","state":"COMMITTED","role":"panel-iran"}')
            path.chmod(0o644)
            self.assertNotEqual(run_journal_validator(path, project).returncode, 0)
            path.chmod(0o600)
            link = Path(tmp) / "link.json"
            link.symlink_to(path)
            self.assertNotEqual(run_journal_validator(link, project).returncode, 0)

    def test_rc7_foreign_gateway_is_signed_and_legacy_is_unchanged(self):
        source = (ROOT / "modules/smite-foreign-gateway.sh").read_text()
        script = source[source.index("smite_foreign_gateway_is_clean_rc() {"):
                        source.index("smite_foreign_gateway_require_rc_paused() {")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.env"
            for version, expected in (
                ("2.0.0-rc.1", 0), ("2.0.0-rc.7", 0),
                ("0.1.7", 1), ("2.0.0-rc.6", 1),
            ):
                path.write_text("SMITE_MANAGED_VERSION=" + version + "\n")
                cmd = 'smite_foreign_gateway_state_value() { sed -n "s/^$1=//p" "$2"; }; '
                cmd += script + '\nsmite_foreign_gateway_is_clean_rc'
                result = subprocess.run(
                    ["bash", "-c", cmd], text=True, capture_output=True,
                    env={**os.environ, "SMITE_STATE_FILE": str(path)}, timeout=10,
                )
                self.assertEqual(result.returncode, expected, (version, result.stderr))

    def test_rc7_foreign_gateway_and_sanaei_preserve_transaction(self):
        gateway = (ROOT / "modules/smite-foreign-gateway.sh").read_text()
        installer = (ROOT / "modules/smite-install.sh").read_text()
        self.assertIn('smite_foreign_gateway_rc7_compose up -d --no-build --force-recreate smite-node', gateway)
        self.assertIn('COMPOSE_PROJECT_NAME="$project" python3 -B "$helper" "$SMITE_NODE_COMPOSE" "$@"', gateway)
        self.assertIn('if [[ ! "$project" =~ ^uopti_rc6_[0-9a-f]{32}$ ]]', gateway)
        self.assertIn('[ "$files" != "$SMITE_NODE_COMPOSE" ]', gateway)
        body = installer.split("smite_install_sanaei_foreign() {", 1)[1].split(
            "\nsmite_install_upgrade_signed_field_trial()", 1
        )[0]
        self.assertIn('2.0.0-rc.1|2.0.0-rc.7) signed_foreign=1', body)
        self.assertNotIn('"$SMITE_INSTALL_PROFILE"', body)
        self.assertEqual(body.count('COMPOSE_PROJECT_NAME="$compose_project" python3 -B'), 3)
        self.assertIn('HOLD: RC7 Foreign Node Compose ownership', body)

    def test_local_compose_label_trust_gate_offline(self):
        source = SOURCE.read_text()
        script = source[source.index("smite_gateway_node_compose_project() {"):
                        source.index("smite_gateway_switch_local_node_to_443() {")]
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp)
            docker = bindir / "docker"
            docker.write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                '  *smite-node*)\n'
                '    case "$*" in\n'
                '      *com.docker.compose.project*) printf "%s\\n" "$MOCK_NODE_PROJECT" ;;\n'
                '      *com.docker.compose.service*) printf "%s\\n" "$MOCK_NODE_SERVICE" ;;\n'
                '    esac ;;\n'
                '  *smite-panel*) printf "%s\\n" "$MOCK_PANEL_PROJECT" ;;\n'
                'esac\n'
            )
            docker.chmod(0o700)
            env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
                   "MOCK_NODE_PROJECT": "smite-node", "MOCK_NODE_SERVICE": "smite-node",
                   "MOCK_PANEL_PROJECT": "smite-node"}
            cmd = ["bash", "-c", script + "\nsmite_gateway_node_compose_project"]
            good = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(good.stdout.strip(), "smite-node")
            for project, service in (("bad name", "smite-node"), ("", "smite-node"),
                                     ("smite-node", "wrong-service"),
                                     ("uopti_rc6_invalid", "smite-node")):
                env["MOCK_NODE_PROJECT"] = project
                env["MOCK_NODE_SERVICE"] = service
                result = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
