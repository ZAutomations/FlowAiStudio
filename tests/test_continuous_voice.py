import json
import math
import queue
import struct
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock

from ai_studio_continuous_voice import align, generate, groups, tokens


class ContinuousVoiceTests(unittest.TestCase):
    def test_next_voice_request_runs_during_current_alignment(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            adapter=Mock();adapter.zb_scenes=[{'narration':'First sentence.'},{'narration':'Second sentence.'}];adapter._zb_cancel=threading.Event()
            second_started=threading.Event();calls=[]
            def synth(text,path,settings):
                calls.append(text)
                if text.startswith('Second'):second_started.set()
                with wave.open(str(path),'wb') as stream:
                    stream.setparams((1,2,48000,0,'NONE','not compressed'));stream.writeframes(b'\x01\x00'*48000)
                return True,[]
            def recognize(path,model,cancel):
                first='0001' in str(path)
                if first:self.assertTrue(second_started.wait(5),'Next synthesis must overlap first alignment')
                words=['First','sentence'] if first else ['Second','sentence']
                return [{'word':w,'offset':i*.4,'duration':.3} for i,w in enumerate(words)]
            with patch('ai_studio_continuous_voice.groups',return_value=[[0],[1]]):
                generate(adapter,queue.Queue(),{'project':tmp,'voice_engine':'piper','settings':{}},synth,recognize)
            self.assertEqual(calls,['First sentence.','Second sentence.'])
    def test_word_alignment_not_equal_scene_lengths(self):
        scenes = [{'narration':'One two.'},{'narration':'Three four.'}]
        words = [{'word':w,'offset':s,'duration':.3} for w,s in [('one',.2),('two',.7),('three',3),('four',3.5)]]
        self.assertEqual(align(scenes, words, 4), [0,2,4])
        self.assertEqual(tokens('کِتاب كِتاب'), ['کتاب','کتاب'])

    def test_uncertain_alignment_fails_instead_of_guessing(self):
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):
            align([{'narration':'This is the original full story.'}], [{'word':'unrelated','offset':0,'duration':1}], 2)

    def test_large_chunks_preserve_every_scene(self):
        scenes = [{'narration':'a'*800} for _ in range(7)]
        result = groups(scenes)
        self.assertEqual([i for row in result for i in row], list(range(7)))
        self.assertEqual(result, [[0,1],[2,3],[4,5],[6]])

    def test_continuous_audio_roundtrip_resume_and_style_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = Mock(); adapter.zb_scenes = [{'narration':'One two.'},{'narration':'Three four.'}]
            adapter._zb_cancel = threading.Event()
            config = {'project':tmp,'voice_engine':'google_cloud','settings':{},'narration_style':'storytelling'}
            def synth(text, path, settings):
                self.assertEqual(text, 'One two.\n\nThree four.')
                with wave.open(str(path),'wb') as out:
                    out.setnchannels(1);out.setsampwidth(2);out.setframerate(48000)
                    out.writeframes(b''.join(struct.pack('<h',int(math.sin(i/20)*10000)) for i in range(192000)))
                return True, []
            tts = Mock(side_effect=synth)
            recognize = Mock(return_value=[{'word':w,'offset':s,'duration':.3} for w,s in [('one',.2),('two',.7),('three',3),('four',3.5)]])
            generate(adapter,queue.Queue(),config,tts,recognize)
            tts.assert_called_once();recognize.assert_called_once()
            paths = [Path(s['audio_path']) for s in adapter.zb_scenes]
            master = paths[0].parent/'narration.wav'
            with wave.open(str(master),'rb') as src: original = src.readframes(src.getnframes())
            parts = []
            for path in paths:
                with wave.open(str(path),'rb') as src: parts.append(src.readframes(src.getnframes()))
            self.assertEqual(b''.join(parts),original)
            self.assertEqual(adapter.zb_scenes[1]['word_timings'][0]['offset'],1)
            from PIL import Image
            from ai_studio_pipeline import render_video, probe
            for i, scene in enumerate(adapter.zb_scenes):
                image=Path(tmp)/f'image_{i}.png';Image.new('RGB',(160,90),'navy' if i==0 else 'gold').save(image)
                scene['image_path']=str(image)
            output=render_video(adapter.zb_scenes,Path(tmp)/'render',{
                'resolution':'160x90','motion':False,'transition':'Cut','captions':False,
                'use_captions_tab':False,'use_transitions_tab':False,'use_effects_tab':False,
                'thumbnail_enabled':False},adapter._zb_cancel)
            self.assertAlmostEqual(probe(output)[0],4,delta=.12)
            timeline=json.loads((Path(tmp)/'render/timeline.json').read_text())
            self.assertEqual([r['duration'] for r in timeline['scenes']],[2,2])
            generate(adapter,queue.Queue(),config,tts,recognize)
            tts.assert_called_once();recognize.assert_called_once()
            generate(adapter,queue.Queue(),{**config,'narration_style':'suspense'},tts,recognize)
            self.assertEqual(tts.call_count,2)
            self.assertTrue(master.exists())

    def test_alignment_failure_keeps_existing_scene_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter=Mock();adapter.zb_scenes=[{'narration':'Original narration stays intact','audio_path':'old.wav'}]
            adapter._zb_cancel=threading.Event()
            def synth(text,path,settings):
                with wave.open(str(path),'wb') as out:
                    out.setparams((1,2,48000,0,'NONE','not compressed'));out.writeframes(b'\x01\x00'*48000)
                return True,[]
            with self.assertRaisesRegex(RuntimeError,'uncertain'):
                generate(adapter,queue.Queue(),{'project':tmp,'voice_engine':'piper','settings':{}},synth,lambda *a:[])
            self.assertEqual(adapter.zb_scenes[0]['audio_path'],'old.wav')
            self.assertTrue(list(Path(tmp).rglob('chunk_0001.mp3')))


if __name__ == '__main__': unittest.main()
