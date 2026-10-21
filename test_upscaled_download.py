import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from ai_studio_upscaled_download import choose_upscaled,download

class UpscaledDownloadTests(unittest.TestCase):
 def test_never_selects_original_or_disabled_or_ambiguous(self):
  self.assertEqual(choose_upscaled([dict(text='Original size',disabled=False),dict(text='720p Upscaled',disabled=False)]),'720p Upscaled')
  for items in [[dict(text='Original size')],[dict(text='Upscaled',disabled=True)],[dict(text='720p Upscaled'),dict(text='1080p Upscaled')]]:
   with self.assertRaises(RuntimeError):choose_upscaled(items)
 def test_exact_tile_upscaled_download_receipt_and_validation(self):
  with tempfile.TemporaryDirectory() as tmp:
   page=Mock();tile=page.locator.return_value;tile.count.return_value=1;tile.evaluate.return_value={'ok':True,'direct':True}
   client=page.context.browser.new_browser_cdp_session.return_value;handlers={};folder={}
   client.on.side_effect=lambda name,fn:handlers.update({name:fn})
   def command(name,args):
    if name=='Browser.setDownloadBehavior' and 'downloadPath' in args:folder['path']=Path(args['downloadPath'])
   client.send.side_effect=command
   def evaluate(script,*args):
    if not args:return [dict(text='Original size'),dict(text='Upscaled')]
    (folder['path']/'matched-guid').write_bytes(b'video')
    handlers['Browser.downloadWillBegin']({'guid':'matched-guid'})
    handlers['Browser.downloadProgress']({'guid':'matched-guid','state':'completed'})
    return True
   page.evaluate.side_effect=evaluate
   out=Path(tmp)/'scene_0001.mp4'
   with patch('ai_studio_animate_media.valid_video',return_value=True),patch('ai_studio_upscaled_download.probe',return_value=(8,[dict(codec_type='video',width=1280,height=720)])):
    result=download(page,'exact_asset',out,threading.Event(),lambda m:None)
   self.assertEqual(result['download_version'],'upscaled');self.assertTrue(out.exists())
   self.assertEqual(page.locator.call_args_list[0].args[0],'flow-video-tile[data-ai-studio-media="exact_asset"]')
   self.assertIn('[data-flow-download-choice="selected"]',[c.args[0] for c in page.locator.call_args_list])
   self.assertEqual(page.evaluate.call_args.args[1],'Upscaled')

if __name__=='__main__':unittest.main()
