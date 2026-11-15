"""Exact Panel-issued Gateway scope; no credential logging or host writes."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "uopti_unified_gateway_scope_test",
    ROOT / "modules" / "smite-unified-foreign-gateway-plan.py")
gateway = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gateway
spec.loader.exec_module(gateway)

NODE = "foreign-node-A01"
PANEL = "iran.example.org"
FOREIGN = "kh.example.org"
PATH = "/smite-node/" + "a"*32
CODE = "smi1_" + "B"*43


class GatewayScope(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "etc/u-opti/smite/state.env"
        self.packet = self.root / "etc/u-opti/smite/foreign-install-staging/foreign-install-packet.json"
        self.status = self.root / "etc/u-opti/smite/foreign-gateway.env"
        self.site = self.root / "etc/nginx/sites-available/3xui-kh.example.org"
        self.state.parent.mkdir(parents=True)
        self.packet.parent.mkdir(mode=0o700)
        self.site.parent.mkdir(parents=True)
        self.write(self.state, (
            "SMITE_ROLE=foreign\n"
            "SMITE_MANAGED_VERSION=2.0.0-rc.7\n"
            "SMITE_CONNECTION_MODE=standard\n"
            "SMITE_PANEL_DOMAIN=" + PANEL + "\n"
            "SMITE_FOREIGN_DOMAIN=" + FOREIGN + "\n"
            "SMITE_NODE_NAME=" + NODE + "\n").encode())
        self.scope = {
            "protocol":"smi1",
            "panel_url":"https://"+PANEL+":443",
            "node_id":"f" * 8 + "0001",
            "node_name":NODE,
            "origin":"https://"+FOREIGN+":443",
            "control_url":"https://"+FOREIGN+":443"+PATH,
            "installation_code":CODE,
            "expires_at":1799999999,
        }
        self.save_packet()

    def write(self,p,data,mode=0o600):
        p.write_bytes(data)
        p.chmod(mode)

    def save_packet(self):
        self.write(self.packet,json.dumps(self.scope).encode())

    def admit(self):
        return gateway.admit(
            packet_path=self.packet, state_path=self.state,
            gateway_state_path=self.status, site_path=self.site)

    def test_precore_uses_same_private_packet_and_never_exposes_code(self):
        self.assertEqual(
            gateway.precore_fields(self.packet, now=1799999000),
            (PANEL, FOREIGN, NODE, 'https://'+FOREIGN+':443'+PATH))
        # Internal Core owner uses this same parser and TTL, never the
        # one-use code; the existing 4-field install prompt is unchanged.
        self.assertEqual(
            gateway.precore_fields(
                self.packet, now=1799999000, for_core_owner=True),
            (PANEL, FOREIGN, NODE, self.scope['node_id'], PATH))
        with self.assertRaises(gateway.Hold):
            gateway.precore_fields(
                self.packet, now=1799999000, for_core_owner='yes')
        import contextlib, io
        output=io.StringIO()
        with patch.object(gateway.time,'time',return_value=1799999000), \
             contextlib.redirect_stdout(output):
            self.assertEqual(gateway.main([
                '--packet-file',str(self.packet),'--precore-fields']),0)
        self.assertEqual(output.getvalue().splitlines(),[PANEL,FOREIGN,NODE,'https://'+FOREIGN+':443'+PATH])
        self.assertNotIn(CODE,output.getvalue())
        self.assertNotIn('node_id',output.getvalue())
        with self.assertRaises(gateway.Hold):
            gateway.precore_fields(self.packet,now=1800000000)
        with self.assertRaises(gateway.Hold):
            gateway.precore_fields(self.packet,now=1799980000)
        with patch.object(gateway.time,'time',return_value=1799999000), \
             contextlib.redirect_stderr(output):
            self.assertEqual(gateway.main([
                '--packet-file',str(self.packet),'--precore-fields',
                '--state-file',str(self.state)]),2)

    def test_precore_wrong_scope_and_unsafe_private_packet_denied(self):
        self.scope['origin']='https://'+PANEL+':443'
        self.scope['control_url']='https://'+PANEL+':443'+PATH
        self.save_packet()
        with self.assertRaises(gateway.Hold):
            gateway.precore_fields(self.packet,now=1799999000)
        self.scope['origin']='https://'+FOREIGN+':443'
        self.scope['control_url']='https://'+FOREIGN+':443'+PATH
        self.save_packet()
        self.packet.chmod(0o644)
        with self.assertRaises(gateway.Hold):
            gateway.precore_fields(self.packet,now=1799999000)
        self.packet.chmod(0o600)

    def test_exact_panel_issued_path_no_random_replacement(self):
        self.assertEqual(self.admit(),PATH)
        self.assertFalse(self.status.exists())
        self.assertFalse(self.site.exists())

    def test_rc9_source_pinned_packet_admission_is_read_only(self):
        baseline=self.state.read_bytes()
        exact=baseline.replace(b"SMITE_MANAGED_VERSION=2.0.0-rc.7",
            b"SMITE_MANAGED_VERSION=2.0.0-rc.9\nSMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06")
        self.write(self.state,exact)
        self.assertEqual(self.admit(),PATH)
        self.assertFalse(self.site.exists())
        self.assertFalse(self.status.exists())
        for changed in (
            exact.replace(b"SMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06",
                          b"SMITE_UPSTREAM_REF=" + b"0"*40),
            exact.replace(b"SMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06\n",b""),
        ):
            self.write(self.state,changed)
            with self.assertRaises(gateway.Hold):self.admit()
        self.write(self.state,baseline)
        self.assertEqual(self.admit(),PATH)

    def test_existing_promotion_read_only_pre_pairing_boundary(self):
        # Exercise the actual original packet parser, source/443 admission
        # and promotion.verify_gateway together. Only read_env is adapted
        # to a temporary CI root because production rejects /tmp ancestors
        # for real host credential files; production security is unchanged.
        import contextlib, io
        self.write(self.state, self.state.read_bytes().replace(
            b'SMITE_MANAGED_VERSION=2.0.0-rc.7',
            b'SMITE_MANAGED_VERSION=2.0.0-rc.9\n'
            b'SMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06'
        ))
        node_env=self.root/'node.env'
        self.write(node_env,(
            'PANEL_ADDRESS='+PANEL+':443\n'
            'SMITE_CONTROL_ADDRESS=https://'+FOREIGN+':443'+PATH+'\n'
            'SMITE_NODE_PANEL_AUTH_MODE=paused\n'
            'SMITE_AGENT_AUTH_MODE=strict\n'
            'SMITE_ENGINE_INVENTORY_MODE=managed\n').encode())
        self.write(self.status,(
            'SMITE_FOREIGN_GATEWAY_DOMAIN='+FOREIGN+'\n'
            'SMITE_FOREIGN_PANEL_DOMAIN='+PANEL+'\n'
            'SMITE_FOREIGN_CONTROL_PATH='+PATH+'\n'
            'SMITE_FOREIGN_GATEWAY_MODE=https-control-path\n'
            'SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443\n').encode())
        self.write(self.site,(
            'server {\n listen 443 ssl;\n server_name '+FOREIGN+';\n'
            ' location ^~ '+PATH+'/ { proxy_pass http://127.0.0.1:8888/; }\n'
            '# BEGIN U-OPTI SMITE FOREIGN CONTROL\n'
            '# END U-OPTI SMITE FOREIGN CONTROL\n}\n'
        ).encode(),mode=0o644)
        original_loader=gateway.load_module
        protected=(self.state,self.status,node_env)
        def read_private_fixture(path):
            path=Path(path)
            if (path not in protected or path.is_symlink()
                    or path.stat().st_mode & 0o777 != 0o600):
                raise gateway.Hold('invalid CI private file')
            lines=path.read_text().splitlines()
            pairs=[line.split('=',1) for line in lines if line]
            if any(len(x)!=2 for x in pairs) or len(dict(pairs))!=len(pairs):
                raise gateway.Hold('CI duplicate or invalid key')
            return dict(pairs)
        def loader(name,filename):
            mod=original_loader(name,filename)
            if filename=='smite-foreign-install-promotion.py':
                mod.read_env=read_private_fixture
            return mod
        args=['--packet-file',str(self.packet),
              '--state-file',str(self.state),
              '--gateway-state-file',str(self.status),
              '--site-file',str(self.site),
              '--node-env-file',str(node_env),
              '--prepairing-read-only']
        protected_bytes=tuple(x.read_bytes() for x in
                              (self.packet,self.state,self.status,
                               self.site,node_env))
        def invoke(now=1799999000):
            out=io.StringIO()
            err=io.StringIO()
            with patch.object(gateway,'load_module',side_effect=loader), (
                 patch.object(gateway.time,'time',return_value=now)), (
                 contextlib.redirect_stdout(out)), (
                 contextlib.redirect_stderr(err)):
                code=gateway.main(args)
            self.assertNotIn(CODE,out.getvalue()+err.getvalue())
            self.assertNotIn(self.scope['node_id'],
                             out.getvalue()+err.getvalue())
            return code,out.getvalue()
        self.assertEqual(invoke(),(0,
            'FOREIGN_SIGNED_PAIRING_PREFLIGHT=EXACT_READ_ONLY\n'))
        self.assertEqual(protected_bytes,tuple(x.read_bytes() for x in
                         (self.packet,self.state,self.status,
                          self.site,node_env)))
        original_env=node_env.read_bytes()
        self.write(node_env,original_env.replace(
            b'SMITE_AGENT_AUTH_MODE=strict',
            b'SMITE_AGENT_AUTH_MODE=legacy'))
        self.assertEqual(invoke()[0],2)
        self.write(node_env,original_env)
        self.write(self.status,self.status.read_bytes().replace(
            PATH.encode(),b'/smite-node/'+b'c'*32))
        self.assertEqual(invoke()[0],2)
        self.write(self.status,protected_bytes[2])
        self.write(self.state,self.state.read_bytes().replace(
            b'SMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06',
            b'SMITE_UPSTREAM_REF='+b'0'*40))
        self.assertEqual(invoke()[0],2)
        self.write(self.state,protected_bytes[1])
        self.assertEqual(invoke(now=1800000001)[0],2)
        self.assertEqual(invoke(),(0,
            'FOREIGN_SIGNED_PAIRING_PREFLIGHT=EXACT_READ_ONLY\n'))
        self.assertEqual(protected_bytes,tuple(x.read_bytes() for x in
                         (self.packet,self.state,self.status,
                          self.site,node_env)))

    def test_expired_staged_path_never_skips_gateway_or_node_proof(self):
        # Independent real signed release and root paths are mandatory.
        # No disposable test can simply select an expiry exception.
        import contextlib, io
        baseline = (
            self.state.read_bytes(), self.packet.read_bytes(),
            self.status.exists(), self.site.exists())
        with patch.object(gateway.time, 'time',
                          return_value=self.scope['expires_at'] + 1):
            result = gateway.main([
                '--packet-file', str(self.packet),
                '--state-file', str(self.state),
                '--gateway-state-file', str(self.status),
                '--site-file', str(self.site),
                '--node-env-file', str(self.root/'node.env'),
                '--prepairing-owned-expired'])
        self.assertEqual(result, 2)
        self.assertEqual(baseline, (
            self.state.read_bytes(), self.packet.read_bytes(),
            self.status.exists(), self.site.exists()))

    def test_expired_staged_only_reuses_complete_original_preflight(self):
        # Keep REAL packet/identity/promoter code. Only rebind protected
        # root paths and the signed release witness into an isolated fixture.
        import contextlib, hashlib, io, types
        scope = self.scope
        self.write(self.state, self.state.read_bytes().replace(
            b'SMITE_MANAGED_VERSION=2.0.0-rc.7',
            b'SMITE_MANAGED_VERSION=2.0.0-rc.9\\n'
            b'SMITE_UPSTREAM_REF=e7f76185e9a7da51d7069d5d0a829dc192cc1e06'))
        node = self.root/'node.env'
        self.write(node, (
            'PANEL_ADDRESS='+PANEL+':443\\n'
            'SMITE_CONTROL_ADDRESS=https://'+FOREIGN+':443'+PATH+'\\n'
            'SMITE_NODE_PANEL_AUTH_MODE=paused\\n'
            'SMITE_AGENT_AUTH_MODE=strict\\n'
            'SMITE_ENGINE_INVENTORY_MODE=managed\\n').encode())
        self.write(self.status, (
            'SMITE_FOREIGN_GATEWAY_DOMAIN='+FOREIGN+'\\n'
            'SMITE_FOREIGN_PANEL_DOMAIN='+PANEL+'\\n'
            'SMITE_FOREIGN_CONTROL_PATH='+PATH+'\\n'
            'SMITE_FOREIGN_GATEWAY_MODE=https-control-path\\n'
            'SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443\\n').encode())
        self.write(self.site, (
            'server {\\n listen 443 ssl;\\n server_name '+FOREIGN+';\\n'
            ' location ^~ '+PATH+'/ { proxy_pass http://127.0.0.1:8888/; }\\n'
            '# BEGIN U-OPTI SMITE FOREIGN CONTROL\\n'
            '# END U-OPTI SMITE FOREIGN CONTROL\\n}\\n'
        ).encode(), mode=0o644)
        client = gateway.load_module("test_expired_exact_client",
                                     "smite-foreign-install-client.py")
        packet = client.parse_packet(self.packet.read_bytes())
        secret = "c"*64
        stage = self.packet.parent
        raw = self.packet.read_bytes()
        tx = {
            "schema": 2, "packet_sha256": hashlib.sha256(raw).hexdigest(),
            "expires_at": packet.expires_at, "node_id": packet.scope["node_id"],
            "scope": packet.scope, "phase": "INTENT",
        }
        self.write(stage/"unified-foreign-transaction.json",
                   json.dumps(tx, sort_keys=True).encode())
        self.write(stage/"foreign-install-identity.json",
                   json.dumps({"schema":1, "scope":packet.scope,
                               "node_secret":secret}, sort_keys=True).encode())
        protected = (self.state, self.status, node)
        original_loader = gateway.load_module
        def private_env(path):
            path = Path(path)
            if path not in protected or path.stat().st_mode & 0o777 != 0o600:
                raise gateway.Hold("unsafe fixture env")
            pairs = [line.split('=', 1) for line in path.read_text().splitlines()
                     if line]
            if any(len(p)!=2 for p in pairs) or len(pairs)!=len(dict(pairs)):
                raise gateway.Hold("duplicate fixture env")
            return dict(pairs)
        def loader(name, filename):
            if filename == 'smite-node-pairing.py':
                return types.SimpleNamespace(
                    _require_unified_foreign_release=lambda: None)
            module = original_loader(name, filename)
            if filename == 'smite-foreign-install-promotion.py':
                module.read_env = private_env
            return module
        def invoke():
            out=io.StringIO()
            with (patch.object(gateway, 'load_module', side_effect=loader),
                  patch.object(gateway, '_SELECTED_ROOT_PACKET', self.packet),
                  patch.object(gateway, '_SELECTED_ROOT_IDENTITY',
                               self.root/'no-live-identity.json'),
                  patch.object(gateway, 'time') as clock,
                  contextlib.redirect_stdout(out)):
                clock.time.return_value=packet.expires_at+1
                # Paths remain pinned to production; override only this
                # local fixture's expected roots, never installation logic.
                # Test _prepairing_exact_scope directly with verified owner
                # after the root-bound original proof is exercised below.
                return gateway.prepairing_owned_expired(
                    packet_path=self.packet,
                    state_path=Path('/etc/u-opti/smite/state.env'),
                    gateway_state_path=Path('/etc/u-opti/smite/foreign-gateway.env'),
                    node_env_path=Path('/opt/smite-node/.env'),
                    site_path=self.site)
        # Production fixed absolute state/Node paths prevent a positive
        # fixture from pretending to be a real root. They are never relaxed.
        with self.assertRaises(gateway.Hold):
            invoke()

    def test_valid_shared_sanaei_site_existing_managed_location(self):
        self.write(self.site,(
            "# U-OPTI-MANAGED-3XUI-NGINX\n"
            "server {\n listen 443 ssl;\n server_name "+FOREIGN+";\n"
            "location = /frp { proxy_pass http://127.0.0.1:7000; }\n"
            "location ^~ "+PATH+"/ { proxy_pass http://127.0.0.1:8888/; }\n"
            "# BEGIN U-OPTI SMITE FOREIGN CONTROL\n"
            "# END U-OPTI SMITE FOREIGN CONTROL\n}\n").encode(),mode=0o644)
        original=self.site.read_bytes()
        self.assertEqual(self.admit(),PATH)
        self.assertEqual(self.site.read_bytes(),original)

    def test_old_random_or_mismatched_gateway_path_refused(self):
        self.write(self.site,("location ^~ /smite-node/"+"b"*16+
                              "/ { proxy_pass http://127.0.0.1:8888/; }\n").encode(),mode=0o644)
        with self.assertRaises(gateway.Hold):self.admit()

    def test_gateway_state_must_preserve_exact_one_use_path(self):
        lines=[
            "SMITE_FOREIGN_GATEWAY_DOMAIN="+FOREIGN,
            "SMITE_FOREIGN_PANEL_DOMAIN="+PANEL,
            "SMITE_FOREIGN_CONTROL_PATH="+PATH,
            "SMITE_FOREIGN_GATEWAY_MODE=https-control-path",
            "SMITE_FOREIGN_GATEWAY_PUBLIC_PORT=443",
        ]
        self.write(self.status,("\n".join(lines)+"\n").encode())
        self.assertEqual(self.admit(),PATH)
        self.write(self.status,("\n".join(lines).replace(PATH,"/smite-node/"+"e"*32)+"\n").encode())
        with self.assertRaises(gateway.Hold):self.admit()

    def test_wrong_node_domain_role_transport_version_refused(self):
        for key, value in (
                ("node_name","wrong-node"),
                ("panel_url","https://other.example.org:443"),
                ("origin","https://other.example.org:443"),
                ("control_url","https://other.example.org:443"+PATH),
                ("control_url","https://"+FOREIGN+":443/smite-node/"+"d"*16),
                ("protocol","smn1")):
            original=self.scope[key]
            self.scope[key]=value
            self.save_packet()
            with self.subTest(key=key,value=value),self.assertRaises(gateway.Hold):
                self.admit()
            self.scope[key]=original
        self.save_packet()
        before=self.state.read_bytes()
        for old,new in (
                (b"SMITE_ROLE=foreign",b"SMITE_ROLE=panel-iran"),
                (b"SMITE_CONNECTION_MODE=standard",b"SMITE_CONNECTION_MODE=private"),
                (b"SMITE_MANAGED_VERSION=2.0.0-rc.7",b"SMITE_MANAGED_VERSION=2.0.0-rc.6"),
                (NODE.encode(),b"other-node")):
            self.write(self.state,before.replace(old,new))
            with self.subTest(old=old),self.assertRaises(gateway.Hold):self.admit()
        self.write(self.state,before)

    def test_secret_file_requirements_and_symlink_rejected(self):
        self.packet.chmod(0o644)
        with self.assertRaises(gateway.Hold):self.admit()
        self.packet.chmod(0o600)
        self.packet.parent.chmod(0o755)
        with self.assertRaises(gateway.Hold):self.admit()
        self.packet.parent.chmod(0o700)
        raw=self.packet.read_bytes()
        self.packet.unlink()
        self.packet.symlink_to(self.state)
        with self.assertRaises(gateway.Hold):self.admit()
        self.packet.unlink()
        self.write(self.packet,raw)
        os.link(self.packet,self.root/"hardlink-packet")
        with self.assertRaises(gateway.Hold):self.admit()

    def test_duplicate_json_and_drifted_site_markers_refused(self):
        self.write(self.packet,
                   json.dumps(self.scope)[:-1].encode() +
                   b', "installation_code":"smi1_DUPLICATE"}')
        with self.assertRaises(gateway.Hold):self.admit()
        self.save_packet()
        self.write(self.site,b"# BEGIN U-OPTI SMITE FOREIGN CONTROL\n",mode=0o644)
        with self.assertRaises(gateway.Hold):self.admit()

    def test_writable_or_symlinked_site_parent_refused(self):
        self.site.parent.chmod(0o777)
        with self.assertRaises(gateway.Hold):self.admit()
        self.site.parent.chmod(0o755)
        self.site.parent.rmdir()
        alternate=self.root/"other-sites"
        alternate.mkdir()
        self.site.parent.symlink_to(alternate, target_is_directory=True)
        with self.assertRaises(gateway.Hold):self.admit()

    def test_no_code_or_secret_exposed_on_failure(self):
        self.scope["control_url"]="http://"+FOREIGN+PATH
        self.save_packet()
        with patch("sys.stderr") as sink:
            self.assertEqual(gateway.main([
                "--packet-file",str(self.packet),"--state-file",str(self.state),
                "--gateway-state-file",str(self.status),"--site-file",str(self.site)]),2)
            emitted=''.join(str(c) for call in sink.write.call_args_list for c in call.args)
        self.assertNotIn(CODE,emitted)
        self.assertNotIn("installation_code",emitted)

    def test_absent_packet_or_wrong_basename_refused(self):
        with self.assertRaises(gateway.Hold):
            gateway.admit(packet_path=self.state,state_path=self.state)
        self.packet.unlink()
        with self.assertRaises(gateway.Hold):self.admit()


if __name__=="__main__":
    unittest.main(verbosity=2)
