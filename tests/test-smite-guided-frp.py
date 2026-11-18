#!/usr/bin/env python3
"""Hermetic role and navigation tests; never contact Docker or a live host."""
import pathlib,shlex,subprocess,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'modules/smite-tunnel-wizard.sh').read_text()
class GuidedTests(unittest.TestCase):
 def role(self,body,selected='ir',mode=0o600,symlink=False,hostname='ir'):
  with tempfile.TemporaryDirectory(dir='/root') as tmp:
   p=pathlib.Path(tmp)/'state.env';p.write_text(body);p.chmod(mode)
   if symlink:
    q=p.with_name('link');q.symlink_to(p);p=q
   code=SOURCE.split("<<'PYROLE'\n",1)[1].split('\nPYROLE',1)[0].replace('/etc/u-opti/smite/state.env',str(p))
   import os,sys
   with patch.object(sys,'argv',['role',selected]),patch.object(os,'uname',return_value=type('Host',(),{'nodename':hostname})()):
    try:exec(compile(code,'role-check','exec'),{});return 0
    except SystemExit as e:return e.code
 def test_trusted_roles(self):
  self.assertEqual(self.role('SMITE_ROLE=panel-iran\nSMITE_CONNECTION_MODE=standard\n'),0)
  self.assertEqual(self.role('SMITE_ROLE=foreign\nSMITE_CONNECTION_MODE=standard\n','kh',hostname='kh'),0)
 def test_mismatch_duplicate_permissions_symlink_fail_closed(self):
  b='SMITE_ROLE=panel-iran\nSMITE_CONNECTION_MODE=standard\n'
  for args in ({'selected':'kh'},{'hostname':'kh'},{'mode':0o666},{'symlink':True}):
   self.assertEqual(self.role(b,**args),2)
  self.assertEqual(self.role(b+'SMITE_ROLE=foreign\n'),2)
  self.assertEqual(self.role('SMITE_ROLE=panel-iran\n'),2)
 def shell(self,script):
  return subprocess.check_output(['bash','-c','source modules/smite-tunnel-wizard.sh\n'+script],cwd=ROOT,stderr=subprocess.STDOUT,text=True)
 def test_role_is_always_first_and_invalid_role_never_delegates(self):
  out=self.shell("smite_bh_role(){ echo ir; }; smite_tw_validate_host(){ echo HOLD; return 2; }; smite_frp_wizard_menu(){ echo BUG; }; printf '2\\n6\\n' | smite_tw_menu; :")
  self.assertIn('STEP 0',out);self.assertNotIn('BUG',out)
 def test_engine_install_and_route_approval_have_distinct_menu_entries(self):
  for version, expected in [(0, ['INSTALL ir', 'STATUS ir']), (1, ['STATUS ir', 'LEGACY ir'])]:
   out=self.shell(f"""
smite_tw_choose_role() {{ echo ir; }}
smite_tw_validate_host() {{ :; }}
smite_tw_pause() {{ :; }}
grep() {{ return {version}; }}
smite_tw_rc9_frp_setup() {{ echo "INSTALL $1"; }}
smite_tw_guided_frp() {{ echo "STATUS $1"; }}
smite_frp_wizard_menu() {{ echo "LEGACY $1"; }}
printf '2\\n6\\n0\\n' | smite_tw_menu
""")
   self.assertEqual([line for line in out.splitlines() if line.split(' ')[0] in
                     ('INSTALL', 'STATUS', 'LEGACY')], expected)
   if version == 0:
    self.assertIn('2) FRP — Install signed FRP engine (RC9)', out)
    self.assertIn('6) FRP — Check status / approve XHTTP routes', out)
 def test_backhaul_has_one_top_level_entry(self):
  for version in (0, 1):
   out=self.shell(f"""
smite_tw_choose_role() {{ echo ir; }}
smite_tw_validate_host() {{ :; }}
smite_tw_pause() {{ :; }}
grep() {{ return {version}; }}
smite_tw_backhaul_menu() {{ echo "SIDECAR $1"; }}
smite_tw_rc9_backhaul_setup() {{ echo "ENGINE $1"; }}
smite_tw_rc9_backhaul_tunnel() {{ echo "TUNNEL $1"; }}
if [ {version} = 0 ]; then
    printf '1\n 1 \r\n1\n 2 \r\n7\n0\n' | smite_tw_menu
else
    printf '1\n7\n0\n' | smite_tw_menu
fi
""")
   if version == 0:
    self.assertIn('1) Backhaul — Set up signed engine, HTTPS/443 and Smite publishing (RC9)',out)
    self.assertNotIn('7) Backhaul',out)
    self.assertIn('ENGINE ir',out)
    self.assertIn('Invalid choice',out)
    self.assertEqual(out.splitlines().count('TUNNEL ir'),1)
    self.assertNotIn('SIDECAR ir',out)
   else:
    self.assertIn('SIDECAR ir',out)
    self.assertNotIn('TUNNEL ir',out)
 def test_backhaul_foreign_has_engine_setup_only(self):
  out=self.shell("""
smite_tw_rc9_backhaul_setup() { echo "ENGINE $1"; }
smite_tw_rc9_backhaul_tunnel() { echo "TUNNEL $1"; }
smite_tw_rc9_backhaul_menu kh
""")
  self.assertEqual(out.strip(),'ENGINE kh')
 def test_backhaul_publisher_runs_only_after_iran_ingress(self):
  fixture=SOURCE.replace('[ "$EUID" = 0 ] && [ -t 0 ]', 'true')
  for role, status, enter in [('ir', 0, ''), ('kh', 0, ''), ('ir', 2, 'n\n')]:
   script=r'''
SMITE_TW_DIR="$PWD/modules"
smite_tw_validate_host() { :; }
python3() {
    case "$2" in
        *backhaul-ingress.py) echo INGRESS; return "$ingress_status" ;;
        *retained-panel.py) echo "PANEL $3" ;;
    esac
}
'''
   command=f'ingress_status={status}\nprintf %s {shlex.quote(enter)} | smite_tw_rc9_backhaul_setup {role}\n'
   result=subprocess.run(['bash','-c',fixture+'\n'+script+command],
                         cwd=ROOT,stderr=subprocess.STDOUT,stdout=subprocess.PIPE,text=True)
   out=result.stdout
   self.assertEqual(result.returncode,0,out)
   self.assertIn('INGRESS',out)
   self.assertEqual('PANEL setup' in out,role=='ir' and status==0)
   if 'PANEL setup' in out:
    self.assertLess(out.index('INGRESS'),out.index('PANEL setup'))
    self.assertIn('Tunnels → Create Tunnel → Backhaul',out)
 def test_next_back_status_no_apply_and_all_role_steps(self):
  for role,words in [('ir',['Panel','Gateway','FRPS Owner','Child','XHTTP']),('kh',['Smite Node','Sanaei','Inbound','FRPC','Signed KH Inventory'])]:
   out=self.shell("smite_tw_validate_host(){ :; }; smite_tw_pause(){ :; }; smite_tw_stage_status(){ echo PASS:mock-observation; }; docker(){ echo BUG; }; python3(){ echo BUG; }; printf 's\\nn\\nn\\nn\\nn\\nb\\nn\\n0\\n' | smite_tw_guided_frp "+role)
   for word in words:self.assertIn(word,out)
   self.assertNotIn('BUG',out);self.assertIn('No stage is automatically applied',out)
 def test_role_drift_while_open_blocks_next_action(self):
  out=self.shell("calls=0; smite_tw_validate_host(){ calls=$((calls+1)); [ $calls -eq 1 ]; }; smite_tw_stage_status(){ echo PASS; }; printf 'n\\ng\\n' | smite_tw_guided_frp ir; :")
  self.assertIn('1/5',out);self.assertNotIn('2/5',out)
 def test_ir_without_frps_cannot_invoke_g_as_installer(self):
  out=self.shell("smite_tw_validate_host(){ :; }; smite_tw_stage_status(){ echo 'HOLD: no FRPS process'; }; python3(){ echo BUG_REVIEWER; }; printf 'n\\nn\\nn\\nn\\ng\\n0\\n' | smite_tw_guided_frp ir")
  self.assertIn('HOLD: FRPS owner not observed',out)
  self.assertIn('This is a status/approval GUIDE, not an FRP engine installer.',out)
  self.assertNotIn('BUG_REVIEWER',out)
 def test_ir_owner_observed_still_uses_independent_signed_reviewer(self):
  out=self.shell("smite_tw_validate_host(){ :; }; smite_tw_stage_status(){ echo 'PASS: frps process present; keep it running, do not reapply'; }; python3(){ echo SIGNED_REVIEW_ONLY; }; printf 'n\\nn\\nn\\nn\\ng\\n0\\n' | smite_tw_guided_frp ir")
  self.assertIn('SIGNED_REVIEW_ONLY',out)
  self.assertIn('approval',out.lower())
 def test_kh_cannot_invoke_g(self):
  out=self.shell("smite_tw_validate_host(){ :; }; smite_tw_stage_status(){ echo PASS; }; python3(){ echo BUG; }; printf 'n\\nn\\nn\\nn\\ng\\n0\\n' | smite_tw_guided_frp kh")
  self.assertNotIn('BUG',out);self.assertIn('HOLD: G is an IR',out)
 def test_rc9_stage_verifies_completed_operation_and_applies_only_with_consent(self):
  with tempfile.TemporaryDirectory() as tmp:
   journal=shlex.quote(tmp)
   out=self.shell("python3(){ printf '%s\n' \"$*\"; }; "
                  f"smite_tw_rc9_frp_stage WSS {journal} helper --rc9; "
                  f"printf 'n\\n' | smite_tw_rc9_frp_stage FRP {journal}/missing helper --rc9; "
                  f"printf 'y\\n' | smite_tw_rc9_frp_stage Edge {journal}/missing helper --rc9")
   actions=[line for line in out.splitlines() if line.startswith('-B ')]
   self.assertEqual(len(actions),2)
   self.assertTrue(actions[0].endswith('helper verify --rc9'))
   self.assertTrue(actions[1].endswith('helper apply --rc9 --snapshot-confirm SNAPSHOTS-CONSOLES-VERIFIED'))
if __name__=='__main__':unittest.main()
