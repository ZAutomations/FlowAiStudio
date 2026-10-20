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
   page.evaluate.side_effect=[[dict(text='Original size'),dict(text='Upscaled')],True]
   transfer=Mock();transfer.save_as.side_effect=lambda p:Path(p).write_bytes(b'video')
   page.expect_download.return_value.__enter__=Mock(return_value=Mock(value=transfer));page.expect_download.return_value.__exit__=Mock(return_value=False)
   out=Path(tmp)/'scene_0001.mp4'
   with patch('ai_studio_animate_media.valid_video',return_value=True),patch('ai_studio_upscaled_download.probe',return_value=(8,[dict(codec_type='video',width=1280,height=720)])):
    result=download(page,'exact_asset',out,threading.Event(),lambda m:None)
   self.assertEqual(result['download_version'],'upscaled');self.assertTrue(out.exists())
   page.locator.assert_called_once_with('flow-video-tile[data-ai-studio-media="exact_asset"]')
   self.assertEqual(page.evaluate.call_args.args[1],'Upscaled')

if __name__=='__main__':unittest.main()
