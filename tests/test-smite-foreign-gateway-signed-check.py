"""Offline verification of paired-only U-OPTI Foreign gateway readiness."""
import hashlib
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "modules/smite-foreign-gateway-signed-check.py"
spec = importlib.util.spec_from_file_location("signed_gateway_check", PATH)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class ForeignGatewaySignedTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        parent = Path(self.work.name) / "identities"
        parent.mkdir(mode=0o700)
        self.file = parent / "node-identity.json"
        self.node_id = "bbbbbbbb-1111-2222-3333-444444444444"
        self.secret = "a" * 64
        self.file.write_text(json.dumps({
            "version": 1, "node_id": self.node_id, "node_secret": self.secret
        }))
        self.file.chmod(0o600)
        self.domain = "panel.example.org"
        self.control = "https://node.example.org/private-control/"

    def build(self, **kwargs):
        opts = dict(
            domain=self.domain, node_name="node-kh", control_url=self.control,
            identity=self.file, moment=1850000000, nonce="b" * 32
        )
        opts.update(kwargs)
        return gateway.build_signed_request(**opts)

    def test_canonical_signature_and_scoped_body(self):
        req = self.build()
        self.assertEqual(req.full_url, "https://panel.example.org/api/node-control/gateway-check")
        body = json.loads(req.data)
        self.assertEqual(body, {
            "node_id": self.node_id,
            "node_name": "node-kh",
            "control_url": self.control.rstrip("/")
        })
        self.assertNotIn(self.secret.encode(), req.data)
        headers = {k.lower(): v for k, v in req.headers.items()}
        expected = hmac.new(
            self.secret.encode(),
            "\n".join((
                "smite-node-hmac-v1", self.node_id, "POST",
                "/api/node-control/gateway-check", "1850000000",
                "b" * 32, hashlib.sha256(req.data).hexdigest()
            )).encode(), "sha256"
        ).hexdigest()
        self.assertEqual(headers["x-smite-signature"], expected)
        self.assertEqual(headers["x-smite-node-id"], self.node_id)
        self.assertEqual(headers["x-smite-nonce"], "b" * 32)

    def test_reject_invalid_endpoint_and_permission(self):
        for bad in ("127.0.0.1", "panel.example.org:8000", "localhost", "", "bad domain"):
            with self.subTest(bad=bad), self.assertRaises(gateway.GatewayHold):
                self.build(domain=bad)
        for bad in ("http://node.example.org/path", "https://node.example.org:8000/path",
                    "https://user:pw@node.example.org/path", "https://node.example.org/"):
            with self.subTest(control=bad), self.assertRaises(gateway.GatewayHold):
                self.build(control_url=bad)
        self.file.chmod(0o644)
        with self.assertRaises(gateway.GatewayHold):
            self.build()
        self.file.chmod(0o600)
        self.file.parent.chmod(0o755)
        with self.assertRaises(gateway.GatewayHold):
            self.build()

    def test_response_only_boolean_and_verified_https(self):
        self_test = self
        observed = []
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, count):
                self_test.assertEqual(count, 4097)
                return json.dumps({"status": "ok", "gateway_ready": True}).encode()

        class Opener:
            def open(self, req, timeout):
                observed.append((req, timeout))
                return Response()

        with patch.object(gateway.request, "build_opener", return_value=Opener()) as create:
            with patch.object(gateway.ssl, "create_default_context", return_value=object()) as tls:
                with patch("sys.stdout", io.StringIO()) as stdout:
                    ready = gateway.verify_gateway(
                        domain=self.domain, node_name="node-kh",
                        control_url=self.control, identity=self.file,
                    )
                self.assertTrue(ready)
                self.assertEqual(stdout.getvalue(), "")
                tls.assert_called_once()
                handlers = create.call_args.args
                self.assertEqual(handlers[0].proxies, {})
                self.assertIsInstance(handlers[2], gateway.NoRedirect)
                self.assertEqual(observed[0][1], 15)

    def test_stage8_fails_closed_to_signed_mode_when_identity_present(self):
        source = (ROOT / "modules/smite-foreign-gateway.sh").read_text()
        section = source.split("smite_foreign_gateway_verify_panel() {", 1)[1].split(
            "\nsmite_foreign_gateway_write_state() {", 1
        )[0]
        self.assertIn('[ -e "$identity" ] || [ -L "$identity" ]', section)
        self.assertIn("smite-foreign-gateway-signed-check.py", section)
        self.assertIn("python3 -B", section)
        self.assertIn("curl -fsS", section)
        self.assertLess(section.index('if [ -e "$identity" ]'), section.index('curl -fsS'))

        installer = (ROOT / "install.sh").read_text()
        updater = (ROOT / "u-opti").read_text()
        name = "smite-foreign-gateway-signed-check.py"
        self.assertIn('    "' + name + '"', installer)
        self.assertEqual(updater.count('                "' + name + '"'), 2)
        self.assertIn('["' + name + '"]="$BASE_URL/modules/' + name + '"', updater)
        self.assertIn('["' + name + '"]="$TEMP_DIR/' + name + '"', updater)


if __name__ == "__main__":
    unittest.main()
