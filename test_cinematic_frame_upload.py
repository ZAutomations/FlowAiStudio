import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from ai_studio_animate_media import prepare_batch_prompt

class ContinuationUploadTests(unittest.TestCase):
    def test_new_frame_uploaded_before_reuse_only_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            frame=Path(directory)/'PreviousClip0005.png'
            Image.new('RGB',(64,64)).save(frame)
            config={'references':['DSP.png',str(frame)],'cinematic_previous_frame':frame.stem,'_agent_cdp_port':10320}
            with patch('ai_studio_animate_media.prepare_agent_prompt') as prepare:
                prepare_batch_prompt(config,Path('batch.txt'),None,lambda text:None)
            first,second=prepare.call_args_list
            self.assertTrue(first.args[0]['_upload_references_only'])
            self.assertEqual(first.args[2],[str(frame)])
            self.assertFalse(second.args[0]['_upload_references_only'])
            self.assertEqual(second.args[2],config['references'])
            self.assertEqual(first.args[0]['_agent_cdp_port'],10320)

    def test_missing_frame_stops_before_preparation(self):
        with patch('ai_studio_animate_media.prepare_agent_prompt') as prepare:
            with self.assertRaisesRegex(RuntimeError,'Continuation frame'):
                prepare_batch_prompt({'references':[],'cinematic_previous_frame':'PreviousClip0005'},None,None,print)
            prepare.assert_not_called()

    def test_ordinary_batch_only_reuses_library(self):
        with patch('ai_studio_animate_media.prepare_agent_prompt') as prepare:
            prepare_batch_prompt({'references':['DSP.png']},None,None,print)
            self.assertEqual(prepare.call_count,1)
            self.assertFalse(prepare.call_args.args[0]['_upload_references_only'])

if __name__=='__main__':unittest.main()
