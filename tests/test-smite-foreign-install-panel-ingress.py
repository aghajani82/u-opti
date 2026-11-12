"""Offline Nginx ingress rendering: preserve existing FRP, do not activate."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "foreign_ingress_trial", ROOT / "modules" / "smite-foreign-install-panel-ingress.py")
ingress = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ingress
spec.loader.exec_module(ingress)


def baseline(domain="panel.example.com"):
    return ("""# Managed by U-OPTI - Smite Panel TLS backend
server {
    listen 127.0.0.1:8443 ssl;
    server_name """ + domain + """;

    ssl_certificate /etc/letsencrypt/live/panel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/panel.example.com/privkey.pem;

    # BEGIN U-OPTI SMITE SIGNED PAIRING REDEEM
    location = /api/node-pairing/redeem {
        limit_except POST { deny all; }
        include /etc/nginx/u-opti-smite-pairing-secret.conf;
        proxy_pass http://127.0.0.1:8000;
    }
    # END U-OPTI SMITE SIGNED PAIRING REDEEM

    # BEGIN U-OPTI STANDARD FRP WSS
    location = /~!frp {
        proxy_pass http://127.0.0.1:7000;
        proxy_http_version 1.1;
    }
    # END U-OPTI STANDARD FRP WSS

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}
""").encode()


class Ingress(unittest.TestCase):
    def setUp(self):
        self.base = baseline()
        self.after = ingress.render(self.base, "panel.example.com").decode()

    def test_exact_post_only_routes_and_secret_ingress(self):
        self.assertEqual(self.after.count("location = /api/foreign-install/redeem {"), 1)
        self.assertEqual(self.after.count("location = /api/node-control/installation-status {"), 1)
        grant = self.after.split(ingress.BEGIN_REDEEM)[1].split(ingress.END_REDEEM)[0]
        proof = self.after.split(ingress.BEGIN_PROOF)[1].split(ingress.END_PROOF)[0]
        root = self.after.split("    location / {")[1].split("    }")[0]
        for block in (grant, proof):
            self.assertIn("limit_except POST { deny all; }",block)
            self.assertIn("client_max_body_size 8k;",block)
            self.assertIn("proxy_pass http://127.0.0.1:8000;",block)
            self.assertIn("access_log off;",block)
            self.assertIn('add_header Cache-Control "no-store" always;',block)
        self.assertIn(ingress.SECRET,grant)
        self.assertNotIn(ingress.SECRET,proof)
        self.assertIn(ingress.STRIP,proof)
        self.assertIn(ingress.STRIP,root)
        self.assertNotIn(ingress.SECRET,root)

    def test_existing_frp_and_pairing_preserved_byte_for_byte(self):
        paired = self.base.decode().split("    # BEGIN U-OPTI SMITE SIGNED PAIRING REDEEM")[1].split("    # END U-OPTI SMITE SIGNED PAIRING REDEEM")[0]
        frp = self.base.decode().split("    # BEGIN U-OPTI STANDARD FRP WSS")[1].split("    # END U-OPTI STANDARD FRP WSS")[0]
        self.assertIn(paired,self.after)
        self.assertIn(frp,self.after)

    def test_idempotent(self):
        self.assertEqual(ingress.render(self.after.encode(),"panel.example.com"),self.after.encode())

    def test_wrong_domain_and_unmanaged_backend_denied(self):
        for raw,domain in [
            (self.base,"other.example.com"),
            (self.base,"bad;root"),
            (self.base.replace(b"Managed by U-OPTI",b"Not managed"),"panel.example.com"),
            (self.base.replace(b"    location / {\n",b""),"panel.example.com"),
        ]:
            with self.subTest(domain=domain), self.assertRaises(ingress.IngressHold):
                ingress.render(raw,domain)

    def test_missing_or_mutated_signed_pairing_refused(self):
        for raw in (
            self.base.replace(ingress.SECRET.encode(),b""),
            self.base.replace(b"    # END U-OPTI SMITE SIGNED PAIRING REDEEM",b"    # END UNREVIEWED"),
            self.base.replace(b"    location = /api/node-pairing/redeem",b"    location /api/node-pairing/redeem"),
        ):
            with self.assertRaises(ingress.IngressHold): ingress.render(raw,"panel.example.com")

    def test_root_spoofable_header_refused(self):
        raw = self.base.replace(b"    location / {\n",b'    location / {\n        proxy_set_header X-Smite-Pairing-Ingress "$http_x_smite_pairing_ingress";\n')
        with self.assertRaises(ingress.IngressHold): ingress.render(raw,"panel.example.com")

    def test_existing_path_collision_denied(self):
        for path in ("/api/node-control/installation-status", "/api/foreign-install/redeem"):
            raw=self.base.replace(b"    location / {\n",f"    location = {path} {{\n    }}\n    location / {{\n".encode())
            with self.assertRaises(ingress.IngressHold): ingress.render(raw,"panel.example.com")

    def test_mixed_checkpoint_and_partial_marker_refused(self):
        for raw in (
            self.after.replace(ingress.END_REDEEM,""),
            self.after.replace(ingress.BEGIN_PROOF,""),
            self.after.replace("        client_max_body_size 8k;","        client_max_body_size 90m;",1),
            self.after.replace('proxy_set_header X-Smite-Pairing-Ingress "";', 'proxy_set_header X-Smite-Pairing-Ingress "$http_x_smite_pairing_ingress";'),
        ):
            with self.assertRaises(ingress.IngressHold):
                ingress.render(raw.encode(),"panel.example.com")

    def test_no_fallback_status_prefix_or_tls_bypass(self):
        self.assertNotIn("proxy_ssl_verify off",self.after)
        self.assertNotIn("location /api/foreign-install/redeem",self.after)
        self.assertNotIn("location /api/node-control/installation-status",self.after)
        self.assertIn("listen 127.0.0.1:8443 ssl",self.after)

    def test_no_modify_on_bad_utf8_or_large_config(self):
        for raw in (b"\xff" + self.base, self.base * 400):
            with self.assertRaises(ingress.IngressHold):
                ingress.render(raw,"panel.example.com")


if __name__=="__main__":
    unittest.main()
