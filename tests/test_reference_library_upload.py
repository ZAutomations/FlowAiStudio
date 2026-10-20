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

    def test_upload_uses_live_selected_browser_port_before_session_detaches(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from ai_studio_consistency import upload_reference_library
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            active=[]
            @contextmanager
            def session(**kwargs):
                active.append(True)
                try:yield object()
                finally:active.clear()
            browser=SimpleNamespace(_session=session,_batch_page=lambda ctx:None,cdp_port=12306,browser_label='Microsoft Edge')
            config=dict(project=directory,flow_url='https://flow.google.com/project/test',browser_type='edge',references=['DSP.png'])
            def upload(c,*args):
                self.assertTrue(active);self.assertEqual(c['_agent_cdp_port'],12306)
                self.assertTrue(c['_upload_references_only'])
            with patch('zbot_browser_images.ZBotImageGenerator',return_value=browser),patch('desktop.browser_accounts.browser_options',return_value={'cdp_port':12306,'browser_type':'edge'}) as options,patch('ai_studio_animate_media.prepare_agent_prompt',side_effect=upload):
                upload_reference_library(SimpleNamespace(_zb_cancel=threading.Event()),config,lambda m:None)
            self.assertFalse(active);self.assertTrue(options.call_args.args[0]['share_google_profile'])
