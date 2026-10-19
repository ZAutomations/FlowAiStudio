import json,tempfile,threading,unittest,wave,math
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from ai_studio_animate_options import animation_count,active_video_seconds
from ai_studio_animate_prompts import parse_ready,master_prompt
from ai_studio_animate_media import media_plan
from desktop.worker import studio
from ai_studio_pipeline import probe,run_ffmpeg
from ai_studio_animate_render import render_animated_video
class OpeningTests(unittest.TestCase):
 def test_counts_and_measured_seconds(self):
  self.assertEqual(animation_count({'animate_count':10},30),10)
  scenes=[{'narration':'text'} for _ in range(30)]
  with patch('ai_studio_animate_options.scene_duration',return_value=5):
   self.assertEqual(animation_count({'partial_animation_unit':'seconds','animate_seconds':80},30,scenes),16)
   self.assertEqual(animation_count({'partial_animation_unit':'seconds','animate_seconds':81},30,scenes),17)
  self.assertEqual(active_video_seconds({'partial_animation_unit':'seconds','animate_seconds':80},{'start':78,'duration':5}),2)
  self.assertEqual(animation_count({'animation_mode':'full'},30,scenes),30)
 def ready(self):return {'version':1,'title':'Ready story','script':'A quiet day. Then rain came.','animation':{'animation_mode':'partial','partial_animation_unit':'seconds','animate_seconds':80},'scenes':[{'scene':1,'narration':'A quiet day.','visual_prompt':'Silent rural courtyard.'},{'scene':2,'narration':'Then rain came.','visual_prompt':'Rain falls over the same courtyard.'}]}
 def test_ready_import_worker_and_locked_narration(self):
  data=self.ready();self.assertEqual(len(parse_ready(json.dumps(data))['scenes']),2)
  bad=self.ready();bad['scenes'][1]['narration']='Changed.'
  with self.assertRaises(ValueError):parse_ready(json.dumps(bad))
  for mode in ('partial','full'):self.assertIn('NARRATION IS LOCKED',master_prompt(mode))
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   result=studio({'project':tmp,'script':data['script'],'voice_engine':'piper','action':'import-ready-animation','animation_ready':json.dumps(data)}, {},threading.Event(),animated=True,emit=lambda **e:None)
   saved=json.loads((Path(tmp)/'project.json').read_text('utf-8'))
   self.assertEqual(result['scenes'],2);self.assertEqual(saved['scenes'][0]['visual_prompt'],'Silent rural courtyard.')
   self.assertEqual(saved['options']['animate_seconds'],80);self.assertNotIn('animation_ready',saved['options'])
   # Existing media must not be overwritten by a new import.
   saved['scenes'][0]['image_path']='image.png';(Path(tmp)/'project.json').write_text(json.dumps(saved),encoding='utf-8')
   with self.assertRaisesRegex(ValueError,'new empty'):studio({'project':tmp,'script':data['script'],'action':'import-ready-animation','animation_ready':json.dumps(data)}, {},threading.Event(),animated=True,emit=lambda **e:None)
 def test_one_clip_contains_multiple_timed_shots_not_multiple_requests(self):
  data=self.ready();data['animation'].update(animate_clip_seconds=8,animate_multishot=True)
  data['scenes'][0]['shots']=[{'start':0,'end':3,'visual_prompt':'Wide establishing view.'},{'start':3,'end':6,'visual_prompt':'Close detail of the same action.'},{'start':6,'end':8,'visual_prompt':'Silent reaction.'}]
  ready=parse_ready(json.dumps(data));config={**ready['options'],'project':'unused','resolution':'1920x1080','style':'Handpainted','style_name':'handpanted relationship','references':[],'animate_count':1,'partial_animation_unit':'scenes'}
  records=media_plan(ready['scenes'],config)
  self.assertEqual([r['kind'] for r in records],['video','image'])
  self.assertIn('TIMED SHOTS INSIDE THIS SINGLE CLIP',records[0]['prompt'])
  self.assertIn('8-second',records[0]['prompt']);self.assertNotIn('One continuous scene',records[0]['prompt'])
  self.assertNotIn('TIMED SHOTS',records[1]['prompt'])
  from ai_studio_animate_media import batch_prompt
  text=batch_prompt(records,{**config,'animate_model':'Veo 3.1 - Lite'})
  self.assertIn('Duration exactly 8 seconds',text)
  self.assertIn('not separate outputs',records[0]['prompt'])
  data['scenes'][0]['shots'][1]['start']=4
  with self.assertRaisesRegex(ValueError,'contiguous'):parse_ready(json.dumps(data))
 def test_seconds_render_freezes_crossing_scene_without_time_loss(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   root=Path(tmp);audio=root/'voice.wav';image=root/'still.png';video=root/'motion.mp4';Image.new('RGB',(160,90),'navy').save(image)
   with wave.open(str(audio),'wb') as wav:wav.setparams((1,2,48000,0,'NONE','not compressed'));wav.writeframes(bytes(96000))
   run_ffmpeg(['-f','lavfi','-i','testsrc2=size=160x90:rate=25:duration=1','-c:v','libx264','-pix_fmt','yuv420p',video])
   scenes=[{'narration':'Short passage.','audio_path':str(audio),'image_path':str(image),'video_path':str(video)},{'narration':'Another passage.','audio_path':str(audio),'image_path':str(image)}]
   out=render_animated_video(scenes,root/'render',{'resolution':'160x90','captions':False,'transition':'Cut','animation_mode':'partial','partial_animation_unit':'seconds','animate_seconds':.5},threading.Event())
   self.assertAlmostEqual(probe(out)[0],2,delta=.1)
   frames=[]
   for t in (.2,.65,.85):
    path=root/f'{t}.png';run_ffmpeg(['-ss',str(t),'-i',root/'render/clips/shot_0000.mp4','-frames:v','1',path]);frames.append(Image.open(path).convert('RGB').tobytes())
   import numpy as np
   pixels=[np.frombuffer(frame,dtype=np.uint8).astype(float) for frame in frames]
   self.assertGreater(np.abs(pixels[0]-pixels[1]).mean(),1)
   self.assertLess(np.abs(pixels[1]-pixels[2]).mean(),1)
if __name__=='__main__':unittest.main()
