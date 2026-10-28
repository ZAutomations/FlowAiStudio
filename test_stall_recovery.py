import json,queue,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from ai_studio_stall_recovery import recover,generic_error

class StallRecoveryTests(unittest.TestCase):
 def test_restrictions_never_count_as_generic(self):
  self.assertTrue(generic_error('Something went wrong. Please try again.'))
  for reason in ['unusual activity','usage limit','quota','policies','captcha','permission denied']:
   self.assertFalse(generic_error('Something went wrong '+reason))
 def fixture(self,root):
  image=root/'image.png';Image.new('RGB',(64,64),'red').save(image)
  config=dict(project=str(root),account_fallback=True,provider='flow',character_consistency=True,action='images',browser_account='old',flow_url='https://flow.google.com/project/old',share_google_profile=True)
  adapter=SimpleNamespace(zb_scenes=[{'image_path':str(image)},{'image_path':''}],_zb_cancel=threading.Event(),_zb_save_project=lambda c:None)
  return adapter,config
 def test_five_minutes_compile_then_switch_upload_resume(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);adapter,c=self.fixture(root);q=queue.Queue();calls=[]
   (root/'profile_gemini').mkdir()
   with self.assertRaisesRegex(RuntimeError,'0/300s'):recover(adapter,q,c,RuntimeError('Something went wrong'),now=10)
   with self.assertRaisesRegex(RuntimeError,'299/300s'):recover(adapter,q,c,RuntimeError('ACTION REQUIRED: Existing submission remains unresolved'),now=309)
   def compile(*args,**kw):calls.append('compile');self.assertEqual(args[2]['scene_end'],1);return {'video':'saved.mp4'}
   def switch(target,previous,*args):calls.append('switch');target['flow_url']='https://flow.google.com/project/new'
   with patch('ai_studio_account_rotation.account_order',return_value=['old','next']),patch('desktop.browser_accounts.browser_options',return_value={'profile_dir':root}),patch('ai_studio_parts.compile_part',side_effect=compile),patch('ai_studio_account_rotation.select_account',side_effect=switch),patch('ai_studio_consistency.ensure_uploaded_reference_library',side_effect=lambda *a:calls.append('upload')):
    self.assertTrue(recover(adapter,q,c,RuntimeError('Something went wrong'),now=310))
   self.assertEqual(calls,['compile','switch','upload']);self.assertEqual(c['browser_account'],'next')
 def test_progress_resets_timer_and_off_is_respected(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);a,c=self.fixture(root)
   with self.assertRaisesRegex(RuntimeError,'0/300s'):recover(a,queue.Queue(),c,RuntimeError('Something went wrong'),now=10)
   a.zb_scenes[1]['image_path']=a.zb_scenes[0]['image_path']
   with self.assertRaisesRegex(RuntimeError,'0/300s'):recover(a,queue.Queue(),c,RuntimeError('Something went wrong'),now=600)
   c['account_fallback']=False;self.assertFalse(recover(a,queue.Queue(),c,RuntimeError('Something went wrong'),now=1000))
 def test_compile_failure_never_switches(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);a,c=self.fixture(root);(root/'profile_gemini').mkdir()
   with self.assertRaises(RuntimeError):recover(a,queue.Queue(),c,RuntimeError('Something went wrong'),now=0)
   with patch('ai_studio_account_rotation.account_order',return_value=['next']),patch('desktop.browser_accounts.browser_options',return_value={'profile_dir':root}),patch('ai_studio_parts.compile_part',side_effect=RuntimeError('render failed')),patch('ai_studio_account_rotation.select_account') as switch:
    with self.assertRaisesRegex(RuntimeError,'render failed'):recover(a,queue.Queue(),c,RuntimeError('Something went wrong'),now=300)
    switch.assert_not_called()
if __name__=='__main__':unittest.main()
