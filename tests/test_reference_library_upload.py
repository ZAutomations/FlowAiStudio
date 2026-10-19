import tempfile,threading,unittest,queue
from pathlib import Path
from unittest.mock import Mock,patch,MagicMock
from ai_studio_consistency import generate

class ReferenceLibraryUploadTests(unittest.TestCase):
    def test_reference_button_uploads_entire_library_without_generating_scenes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'studio_agent_images.json').write_text('{}')
            refs=[str(root/'DSP.png'),str(root/'UnusedUntilScene100.png'),str(root/'PoliceStation.png')]
            adapter=Mock();adapter.zb_scenes=[];adapter._zb_cancel=threading.Event()
            config={'project':directory,'provider':'flow','resolution':'1280x720','auto_cast':False,
                'flow_url':'https://flow.google.com/project/test','share_google_profile':True}
            with patch('ai_studio_animate_setup.ensure_references',return_value=refs),patch('zbot_browser_images.ZBotImageGenerator',MagicMock()),patch('ai_studio_animate_media.prepare_agent_prompt') as upload,patch('ai_studio_animate_media.generate_agent_media') as scenes:
                generate(adapter,queue.Queue(),config,references_only=True)
                scenes.assert_not_called();upload.assert_called_once()
                self.assertEqual(upload.call_args.args[2],refs)
                self.assertTrue(upload.call_args.args[0]['_upload_references_only'])
