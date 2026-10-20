import json
import queue
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from ai_studio_parts import compile_part,scene_range
from ai_studio_pipeline import atomic_json,probe,render_video


class PartTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'images').mkdir()
        self.scenes=[]
        for i in range(4):
            path=self.root/'images'/f'scene_{i+1:04d}.png'
            Image.new('RGB',(64,64),('red','green','blue','yellow')[i]).save(path)
            self.scenes.append(dict(narration=f'Scene {i+1}.',visual_prompt='A village.',image_path=str(path)))
        self.config=dict(project=str(self.root),title='Case',script='Original full script',scene_start=2,scene_end=3,
            resolution='320x180',captions=False,motion=False,transition='Cut',settings={'zb_fps':10},thumbnail_enabled=True)
        class Adapter:
            _zb_cancel=threading.Event()
            zb_last_video='parent-final.mp4'
            def _zb_save_project(self,c):
                atomic_json(Path(c['project'])/'project.json',{'scenes':self.zb_scenes,'script':c['script'],'last_video':self.zb_last_video})
            def _zb_voice_pass(self,q,c):
                for i,scene in enumerate(self.zb_scenes):
                    path=Path(c['project'])/'voice'/f'scene_{i+1:04d}.wav'
                    with wave.open(str(path),'wb') as audio:
                        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\0\0'*4800)
                    scene['audio_path']=str(path);self._zb_save_project(c)
            def _zb_render_pass(self,q,c):
                self.zb_last_video=str(render_video(self.zb_scenes,c['project'],c,self._zb_cancel))
                self._zb_save_project(c)
        self.adapter=Adapter();self.adapter.zb_scenes=self.scenes;self.q=queue.Queue()

    def test_partial_render_is_independent_and_restores_full_project(self):
        result=compile_part(self.adapter,self.q,self.config)
        duration,streams=probe(result['video'])
        self.assertGreater(duration,.4);self.assertLess(duration,2)
        self.assertTrue(any(s['codec_type']=='audio' for s in streams))
        self.assertIs(self.adapter.zb_scenes,self.scenes)
        self.assertEqual(self.adapter.zb_last_video,'parent-final.mp4')
        self.assertEqual(self.config['script'],'Original full script')
        child=json.loads(Path(result['project']).read_text('utf-8'))
        self.assertEqual([s['source_scene_number'] for s in child['scenes']],[2,3])
        for scene in self.scenes:Path(scene['image_path']).unlink()
        self.assertTrue(all(Path(s['image_path']).is_file() for s in child['scenes']))
        self.assertTrue(Path(result['video']).is_file())

    def test_missing_image_blocks_part_without_skipping_or_voice_calls(self):
        Path(self.scenes[1]['image_path']).unlink()
        self.adapter._zb_voice_pass=Mock()
        with self.assertRaisesRegex(ValueError,'Missing scene images: 2'):
            compile_part(self.adapter,self.q,self.config)
        self.adapter._zb_voice_pass.assert_not_called()
        self.assertFalse((self.root/'parts').exists())

    def test_failure_restores_parent_and_preserves_child_checkpoint(self):
        self.adapter._zb_voice_pass=Mock(side_effect=RuntimeError('temporary TTS outage'))
        with self.assertRaisesRegex(RuntimeError,'TTS outage'):
            compile_part(self.adapter,self.q,self.config)
        self.assertIs(self.adapter.zb_scenes,self.scenes)
        self.assertEqual(self.adapter.zb_last_video,'parent-final.mp4')
        self.assertTrue((self.root/'parts/part_0002-0003/project.json').exists())

    def test_scene_ranges_are_one_based_and_validated(self):
        self.assertEqual(scene_range({},200),(0,200))
        self.assertEqual(scene_range({'scene_start':101,'scene_end':''},200),(100,200))
        for config in ({'scene_start':0},{'scene_start':201},{'scene_start':2,'scene_end':1},{'scene_end':2.5}):
            with self.assertRaises(ValueError):scene_range(config,200)

    def test_animate_part_preserves_original_animation_boundary(self):
        self.config.update(animation_mode='partial',animate_count=2,partial_animation_unit='scenes')
        self.scenes[1]['video_path']=str(self.root/'clip.mp4')
        Path(self.scenes[1]['video_path']).write_bytes(b'clip fixture')
        from unittest.mock import patch
        self.adapter._zb_render_pass=Mock()
        with patch('ai_studio_animate_media.valid_video',return_value=True):
            compile_part(self.adapter,self.q,self.config,animated=True)
        options=self.adapter._zb_render_pass.call_args.args[1]
        self.assertEqual(options['animate_count'],1)
        self.assertEqual(options['partial_animation_unit'],'scenes')
        self.assertIs(self.adapter.zb_scenes,self.scenes)

    def test_cinematic_part_reuses_audio_without_planning(self):
        (self.root/'voice').mkdir()
        self.adapter._zb_voice_pass(self.q,self.config)
        self.config.update(animate_narration_mode='cinematic',animation_mode='partial',animate_count=0)
        self.adapter._zb_voice_pass=Mock(side_effect=AssertionError('must not replan'))
        self.adapter._zb_render_pass=Mock()
        compile_part(self.adapter,self.q,self.config,animated=True)
        self.adapter._zb_voice_pass.assert_not_called()
        self.adapter._zb_render_pass.assert_called_once()
