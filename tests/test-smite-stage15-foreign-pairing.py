#!/usr/bin/env python3
"""Real U-OPTI foreign admission; fake Docker/HTTP, private temporary state."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pairing', ROOT / 'modules/smite-node-pairing.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class ForeignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.node = self.root / 'node'
        self.node.mkdir()
        self.compose = self.node / 'docker-compose.yml'
        self.compose.write_text('services:\n  smite-node:\n    image: smite-node:stage15-local\n')
        self.url = 'https://kh.example.net/smite-node/0123456789abcdef'
        self.env = {
            'SMITE_NODE_PANEL_AUTH_MODE': 'paused', 'SMITE_AGENT_AUTH_MODE': 'strict',
            'SMITE_ENGINE_INVENTORY_MODE': 'managed', 'PANEL_ADDRESS': '02ir.kolbe1.ir:443',
            'SMITE_CONTROL_ADDRESS': self.url,
        }
        self.gateway = {
            'SMITE_FOREIGN_GATEWAY_DOMAIN': 'kh.example.net',
            'SMITE_FOREIGN_PANEL_DOMAIN': '02ir.kolbe1.ir',
            'SMITE_FOREIGN_PANEL_SOURCE_IPV4': '192.0.2.1',
            'SMITE_FOREIGN_CONTROL_PATH': '/smite-node/0123456789abcdef',
            'SMITE_FOREIGN_GATEWAY_PUBLIC_PORT': '443',
            'SMITE_FOREIGN_GATEWAY_MODE': 'https-control-path',
        }
        for path, data in ((self.node / '.env', self.env),
                           (self.root / 'foreign-gateway.env', self.gateway)):
            path.write_text(''.join(f'{k}={v}\n' for k, v in data.items()))
            path.chmod(0o600)
        self.current = {'SMITE_ROLE': 'foreign', 'SMITE_MANAGED_VERSION': '2.0.0-rc.1',
                        'SMITE_CONNECTION_MODE': 'standard', 'SMITE_PANEL_DOMAIN': '02ir.kolbe1.ir'}
        self.service = {
            'image': 'smite-node:stage15-local', 'network_mode': 'host',
            'command': ['uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8888'],
            'environment': self.env.copy(),
        }
        self.config_image = 'smite-node:stage15-local'
        self.running_id = p._STAGE15_IMAGE_IDS['node']
        self.tag_id = self.running_id
        self.health = 'healthy'
        self.calls = []
        self.failure = None
        for name, value in (('STATE', self.root / 'state.env'), ('NODE_DIR', self.node),
                            ('NODE_COMPOSE', self.compose)):
            ctx = patch.object(p, name, value)
            ctx.start(); self.addCleanup(ctx.stop)
        ctx = patch.object(p, '_run', side_effect=self.fake_run)
        ctx.start(); self.addCleanup(ctx.stop)

    def fake_run(self, command, **kwargs):
        self.calls.append(command)
        if self.failure and self.failure in command:
            raise p.WizardHold('fixture inspection unavailable')
        if '{{.Config.Image}}' in command: return self.config_image
        if '{{.Image}}' in command: return self.running_id
        if '{{.Id}}' in command: return self.tag_id
        if '{{.State.Health.Status}}' in command: return self.health
        if command[:2] == ['docker', 'compose']:
            self.assertIn('config', command)
            return json.dumps({'services': {'smite-node': self.service}})
        if command[0] == 'curl':
            self.assertNotIn('-k', command)
            self.assertNotIn('--insecure', command)
            self.assertIn('--resolve', command)
            self.assertEqual(command[-1], self.url + '/')
            return '{"status":"ok","service":"smite-node"}'
        if command[:2] == ['docker', 'exec']:
            self.assertEqual(command[2], 'smite-panel')
            self.assertIn('gateway_control_url', command[-1])
            return 'PANEL_FOREIGN_HMAC_GATEWAY=READY'
        raise AssertionError(command)

    def test_stage15_foreign_preflight_is_read_only_and_uses_verified_tls(self):
        self.assertEqual(p._foreign_gateway_preflight(self.current),
                         ('02ir.kolbe1.ir', 'kh.example.net', self.url))
        self.assertEqual(len(self.calls), 6)
        self.assertFalse(any('up' in c or 'run' in c for c in self.calls))

    def test_foreign_rejects_changed_id_tag_unknown_image_and_failed_inspection(self):
        for field in ('running_id', 'tag_id', 'config_image'):
            original = getattr(self, field)
            for value in ('', 'sha256:' + 'f' * 64, 'smite-node:unverified'):
                setattr(self, field, value)
                with self.subTest(field=field, value=value), self.assertRaises(p.WizardHold):
                    p._foreign_gateway_preflight(self.current)
            setattr(self, field, original)
        self.failure = '{{.Id}}'
        with self.assertRaises(p.WizardHold): p._foreign_gateway_preflight(self.current)
        self.assertFalse(any('up' in c or 'run' in c for c in self.calls))

    def test_effective_compose_drift_holds(self):
        original = copy.deepcopy(self.service)
        cases = [dict(image='unknown'), dict(network_mode='bridge'), dict(privileged=True),
                 dict(ports=[{'published': 8888}]), dict(command=['uvicorn', 'main:app']),
                 dict(command=['uvicorn','main:app','--host','0.0.0.0','--port','8888'])]
        for key in self.env:
            env = self.env.copy(); env[key] = 'unsafe'
            cases.append(dict(environment=env))
        cases.append(dict(environment=[]))
        for case in cases:
            self.service = {**copy.deepcopy(original), **case}
            with self.subTest(case=case), self.assertRaises(p.WizardHold):
                p._foreign_gateway_preflight(self.current)
        self.service = original
        self.health = 'unhealthy'
        with self.assertRaises(p.WizardHold): p._foreign_gateway_preflight(self.current)

    def test_rc2_lane_does_not_accept_stage15_as_substitute(self):
        with self.assertRaises(p.WizardHold):
            p._foreign_gateway_preflight(self.current, expected_image=p._FOREIGN_NODE_IMAGE_RC2)

    def test_stage15_panel_requires_identity_and_runtime_capability(self):
        self.config_image = 'smite-panel:stage15-local'
        self.running_id = self.tag_id = p._STAGE15_IMAGE_IDS['panel']
        p._require_panel_foreign_transport()
        self.assertEqual(len(self.calls), 4)
        for field in ('running_id', 'tag_id'):
            original = getattr(self, field)
            setattr(self, field, p._STAGE15_IMAGE_IDS['node'])
            with self.assertRaises(p.WizardHold): p._require_panel_foreign_transport()
            setattr(self, field, original)
        self.failure = 'exec'
        with self.assertRaises(p.WizardHold): p._require_panel_foreign_transport()

    def test_unknown_panel_denied_and_existing_rc2_capability_check_preserved(self):
        for image in ('smite-panel:latest', p._STAGE15_IMAGE_IDS['panel'], ''):
            self.config_image = image
            with self.assertRaises(p.WizardHold): p._require_panel_foreign_transport()
        self.config_image = p._FOREIGN_PANEL_IMAGE_RC2
        p._require_panel_foreign_transport()


class InstallOrderTests(unittest.TestCase):
    def invoke(self, disk='paused', runtime='paused', identity=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'state.env'
            state.write_text('SMITE_ROLE=foreign\n')
            node = root / 'node'; node.mkdir()
            (node / '.env').write_text('SMITE_NODE_PANEL_AUTH_MODE=' + disk + '\nSMITE_AGENT_AUTH_MODE=strict\n')
            if identity:
                (root / 'identities').mkdir()
                (root / 'identities/node-identity.json').write_text('{}')
            # Root-owned temporary paths; no Docker, service, network or host mutation.
            script = '''
source "$1/modules/smite-install.sh"
SMITE_INSTALL_PROFILE=clean-rc
SMITE_STATE_DIR="$2"
SMITE_STATE_FILE="$2/state.env"
SMITE_NODE_DIR="$2/node"
clear() { :; }
smite_install_pause() { :; }
docker() { printf 'SMITE_NODE_PANEL_AUTH_MODE=%s\\nSMITE_AGENT_AUTH_MODE=strict\\n' "$3"; }
docker_3xui_install() { echo UNEXPECTED_INSTALL; }
smite_install_sanaei_foreign
'''.replace('"$3"', '"' + runtime + '"')
            return subprocess.run(['bash', '-c', script, '_', str(ROOT), str(root)],
                                  capture_output=True, text=True, check=True)

    def test_sanaei_rejects_signed_runtime_even_if_env_is_paused(self):
        result = self.invoke(runtime='signed')
        self.assertIn('HOLD: KH runtime is not confirmed paused', result.stderr)
        self.assertNotIn('UNEXPECTED_INSTALL', result.stdout)

    def test_sanaei_rejects_signed_env_or_staged_identity(self):
        for args in (dict(disk='signed'), dict(identity=True)):
            result = self.invoke(**args)
            self.assertIn('HOLD: Install/attach Sanaei before pairing', result.stderr)
            self.assertNotIn('UNEXPECTED_INSTALL', result.stdout)

    def test_paused_runtime_passes_guard_but_missing_compose_still_holds(self):
        result = self.invoke()
        self.assertIn('HOLD: Clean-RC Foreign Node Compose and environment', result.stderr)
        self.assertNotIn('runtime is not confirmed', result.stderr)

    def test_gateway_available_from_install_wizard_and_order_documented(self):
        text = (ROOT / 'modules/smite-install.sh').read_text()
        self.assertIn('6) smite_foreign_gateway_configure ;;', text)
        self.assertIn('Install/attach Sanaei (option 4)', text)


if __name__ == '__main__': unittest.main()
