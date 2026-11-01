#!/usr/bin/env python3
"""Hermetic role and navigation tests; never contact Docker or a live host."""
import pathlib,subprocess,tempfile,unittest
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
 def test_next_back_status_no_apply_and_all_role_steps(self):
  for role,words in [('ir',['Panel','Gateway','FRPS Owner','Child','XHTTP']),('kh',['Smite Node','Sanaei','Inbound','FRPC','Signed KH Inventory'])]:
   out=self.shell("smite_tw_validate_host(){ :; }; smite_tw_pause(){ :; }; smite_tw_stage_status(){ echo PASS:mock-observation; }; docker(){ echo BUG; }; python3(){ echo BUG; }; printf 's\\nn\\nn\\nn\\nn\\nb\\nn\\n0\\n' | smite_tw_guided_frp "+role)
   for word in words:self.assertIn(word,out)
   self.assertNotIn('BUG',out);self.assertIn('No stage is automatically applied',out)
 def test_role_drift_while_open_blocks_next_action(self):
  out=self.shell("calls=0; smite_tw_validate_host(){ calls=$((calls+1)); [ $calls -eq 1 ]; }; smite_tw_stage_status(){ echo PASS; }; printf 'n\\ng\\n' | smite_tw_guided_frp ir; :")
  self.assertIn('1/5',out);self.assertNotIn('2/5',out)
 def test_kh_cannot_invoke_g(self):
  out=self.shell("smite_tw_validate_host(){ :; }; smite_tw_stage_status(){ echo PASS; }; python3(){ echo BUG; }; printf 'n\\nn\\nn\\nn\\ng\\n0\\n' | smite_tw_guided_frp kh")
  self.assertNotIn('BUG',out);self.assertIn('HOLD: G is an IR',out)
if __name__=='__main__':unittest.main()
