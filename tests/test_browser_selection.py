import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from desktop.browser_accounts import add,browser_options
from zbot_browser_images import ZBotImageGenerator
class BrowserSelectionTests(unittest.TestCase):
 def test_existing_chrome_profile_unchanged(self):
  g=ZBotImageGenerator('flow',share_google_profile=True)
  self.assertEqual(g.cdp_port,10312)
  self.assertEqual(g._profile_path.name,'profile_gemini')
  self.assertEqual(browser_options({}),{})
 def test_edge_isolated_for_default_and_named_account(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);account=add('Work',root)
   for account_id in ('',account['id']):
    config={'provider':'flow','share_google_profile':True,'browser_account':account_id}
    chrome=ZBotImageGenerator('flow',share_google_profile=True,**browser_options(config,root))
    opts=browser_options({**config,'browser_type':'edge'},root)
    edge=ZBotImageGenerator('flow',share_google_profile=True,**opts)
    self.assertEqual(edge.cdp_port,chrome.cdp_port+3000)
    self.assertEqual(edge.cdp_port,opts['cdp_port']) # Agent's Node driver gets the same port
    self.assertNotEqual(edge._profile_path,chrome._profile_path)
    self.assertIn('edge',edge._profile_path.parts)
 def test_edge_launch_channel_and_no_silent_fallback(self):
  g=ZBotImageGenerator(browser_type='edge')
  with patch.object(g,'find_edge',return_value='edge.exe'):
   self.assertEqual(g._launch_options(False)['channel'],'msedge')
  with patch.object(g,'find_edge',return_value=None):
   with self.assertRaisesRegex(RuntimeError,'Edge not found'):g._launch_options(False)
 def test_edge_handover_targets_only_exact_dedicated_profile(self):
  import base64
  from types import SimpleNamespace
  g=ZBotImageGenerator('flow',browser_type='edge',share_google_profile=True)
  with patch('zbot_browser_images.os.name','nt'), patch.object(g,'_cdp_alive',return_value=False), patch('zbot_browser_images.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='1')) as run:
   g._handover_edge_login()
  script=base64.b64decode(run.call_args.args[0][-1]).decode('utf-16le')
  self.assertIn(str(g._profile_path.resolve()),script)
  self.assertIn('OrdinalIgnoreCase',script)
  self.assertIn('--remote-debugging-port=',script)
  self.assertIn('CloseMainWindow()',script)
 def test_handover_does_not_close_connected_edge_or_chrome(self):
  for browser in ('edge','chrome'):
   g=ZBotImageGenerator(browser_type=browser)
   with patch.object(g,'_cdp_alive',return_value=True), patch('zbot_browser_images.subprocess.run') as run:
    g._handover_edge_login()
    run.assert_not_called()
 def test_invalid_browser_rejected(self):
  with self.assertRaises(ValueError):browser_options({'browser_type':'bad'})
  with self.assertRaises(ValueError):ZBotImageGenerator(browser_type='bad')
if __name__=='__main__':unittest.main()
