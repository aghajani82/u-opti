"""Release policy: the selected runtime must contain only console root approval."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class ConsoleOnly(unittest.TestCase):
 def test_rejected_modules_are_absent(self):
  for pattern in ('smite-stage15-passkey*','smite-stage15-web-*','smite-stage15-approval-*','smite-stage15-*observer*','smite-stage15-live-evidence*'):
   self.assertEqual(list((ROOT/'modules').glob(pattern)),[],pattern)
 def test_installer_and_broker_cannot_enable_web_approval(self):
  for name in ('install.sh','u-opti','modules/smite-rc5-xhttp-root-broker.py','modules/smite-stage15-frp-wizard.sh','modules/smite-backhaul-management.sh'):
   data=(ROOT/name).read_text().lower()
   for marker in ('web-approval','passkey','approval-queue','web_mode_marker'):
    self.assertNotIn(marker,data,name)
 def test_console_grant_and_no_legacy_upgrade_with_active_runtime(self):
  data=(ROOT/'modules/smite-stage15-frp-wizard.sh').read_text()
  self.assertIn('smite-stage15-root-review.py',data)
  self.assertEqual(data.count('Legacy image upgrade/rollback forbidden with existing FRP/WSS state.'),2)
  self.assertIn('1', (ROOT/'modules/smite-stage15-root-review.py').read_text())
if __name__=='__main__':unittest.main()
