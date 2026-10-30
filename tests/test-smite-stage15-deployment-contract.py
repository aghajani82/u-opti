"""Deployment contract: no public Root admin port, socket ACL isolation.

This test statically checks templates and launch guards on the PR worktree.
It does NOT install Nginx/systemd, open ports or contact IR/KH.
"""
from pathlib import Path
import importlib.util
import re
import stat
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
EXAMPLE=ROOT/"docs/examples"
MODULES=ROOT/"modules"


class DeployContractTests(unittest.TestCase):
    def test_root_uds_and_nginx_target_are_exactly_same(self):
        vhost=(EXAMPLE/"stage15-web-approval.nginx.conf.example").read_text()
        unit=(EXAMPLE/"u-opti-smite-web-approval.service.example").read_text()
        launcher=(MODULES/"smite-stage15-web-launcher.py").read_text()
        expected="/run/u-opti-smite-review/web-approval.sock"
        self.assertIn("proxy_pass http://unix:"+expected+":;",vhost)
        self.assertIn('c["socket_path"]!="'+expected+'"',launcher)
        self.assertIn("RuntimeDirectory=u-opti-smite-review",unit)
        self.assertIn("ReadWritePaths=/run/u-opti-smite-review",unit)
        self.assertNotIn("RuntimeDirectory=u-opti/smite-review",unit)
        self.assertNotIn("listen 80",vhost)
        self.assertNotIn("listen 8080",vhost)
        self.assertIn("listen 443 ssl;",vhost)
        self.assertNotIn("default_server",vhost)
        self.assertIn("server_name REVIEW_HOSTNAME_REQUIRES_OPERATOR_APPROVAL;",vhost)

    def test_unix_socket_acl_does_not_expose_root_secrets(self):
        unit=(EXAMPLE/"u-opti-smite-web-approval.service.example").read_text()
        launcher=(MODULES/"smite-stage15-web-launcher.py").read_text()
        self.assertIn('os.chown(parent,0,c["socket_gid"])',launcher)
        self.assertIn("os.chmod(parent,0o750)",launcher)
        self.assertIn('os.chown(c["socket_path"],0,c["socket_gid"])',launcher)
        self.assertIn('os.chmod(c["socket_path"],0o660)',launcher)
        self.assertIn("UMask=0077",unit)
        self.assertIn("User=root",unit)
        self.assertIn("Group=root",unit)
        self.assertIn("Restart=no",unit)
        self.assertIn("ProtectSystem=strict",unit)
        self.assertNotIn("ReadWritePaths=/etc/u-opti/smite",unit)
        self.assertIn("ReadWritePaths=/etc/u-opti/smite/route-grants",unit)

    def test_production_lease_requires_live_file_not_snapshot_export(self):
        launcher=(MODULES/"smite-stage15-web-launcher.py").read_text()
        collector=(MODULES/"smite-stage15-live-evidence.py").read_text()
        self.assertIn('"panel_live_db_path"',launcher)
        self.assertNotIn('"panel_snapshot_path"',launcher)
        for required in ('"PRAGMA query_only=ON"','"BEGIN"',
            '"PRAGMA quick_check(1)"','"PRAGMA database_list"',
            'LEASE_SOURCE_REPLACED_DURING_READ','LIVE_LEASE_READ_TOO_OLD'):
            self.assertIn(required,collector)

    def test_nginx_does_not_inherit_forwarded_auth_or_pass_panel_cookies_to_root(self):
        vhost=(EXAMPLE/"stage15-web-approval.nginx.conf.example").read_text()
        service=(MODULES/"smite-stage15-web-service.py").read_text()
        for header in ("X-Forwarded-Host","X-Forwarded-For","X-Forwarded-Proto"):
            self.assertRegex(vhost,re.escape("proxy_set_header "+header+' "";'))
            self.assertIn(header,service)
        self.assertIn('self.headers.get("Cookie")',service)
        self.assertIn('self.headers.get("Origin") != origin',service)
        self.assertIn('"X-Frame-Options": "DENY"',service)


if __name__=="__main__":
    unittest.main()
