"""Camera transition invariants and actual FFmpeg clock/audio integration."""
import json, tempfile, threading, unittest, wave, math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from ai_studio_camera_transitions import STYLES, frame, plan, apply, settings
from ai_studio_pipeline import probe, render_video, Cancelled
from ai_studio_animate_render import render_animated_video

class CameraTests(unittest.TestCase):
 def timeline(self,n=8):return [{'index':i,'start':float(i),'end':float(i+1),'duration':1.,'tail':0} for i in range(n)]
 def test_plan_clock_selection_and_short_scenes(self):
  opts={'camera_transitions_enabled':True,'camera_transition_duration':.45}
  events=plan(self.timeline(),opts)
  self.assertEqual([e['style'] for e in events],list(STYLES))
  self.assertEqual([e['cut'] for e in events],[float(i) for i in range(1,8)])
  self.assertEqual(plan(self.timeline(),{**opts,'camera_transition_style':'random'}),plan(self.timeline(),{**opts,'camera_transition_style':'random'}))
  self.assertEqual(len(plan(self.timeline(),{**opts,'camera_transition_every':2})),3)
  self.assertEqual(plan([{'start':0,'end':.04},{'start':.04,'end':.08}],opts),[])
  self.assertEqual(plan(self.timeline(),{}),[])
 def test_frames_have_exact_endpoints_and_distinct_peaks(self):
  a=Image.new('RGB',(160,90),'navy');ImageDraw.Draw(a).rectangle((20,10,65,80),fill='gold')
  b=Image.new('RGB',(160,90),'maroon');ImageDraw.Draw(b).ellipse((80,15,130,75),fill='white')
  peaks=[]
  for key in STYLES:
   self.assertEqual(frame(a,b,0,key).tobytes(),a.tobytes())
   self.assertEqual(frame(a,b,1,key).tobytes(),b.tobytes())
   out=frame(a,b,.44,key);self.assertEqual(out.size,a.size);peaks.append(out.tobytes())
  self.assertEqual(len(set(peaks)),7)
 def test_validation_and_cancellation(self):
  for opts in ({'camera_transition_duration':float('nan')},{'camera_transition_volume':101},{'camera_transition_style':'bad'}):
   with self.assertRaises(ValueError):settings(opts)
  stop=threading.Event();stop.set()
  with self.assertRaises(Cancelled):apply('unused',self.timeline(),{'camera_transitions_enabled':True},stop)
 def test_real_studio_and_animate_render_no_clock_drift(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   root=Path(tmp);scenes=[]
   for i in range(8):
    image=root/f'{i}.png';im=Image.new('RGB',(320,180),(30+i*20,40,100));d=ImageDraw.Draw(im);d.rectangle((20+i*7,30,100+i*7,140),fill=(230,170,40));d.text((130,50),str(i+1),fill='white');im.save(image)
    audio=root/f'{i}.wav';samples=np.sin(np.arange(48000)*2*math.pi*220/48000)*.12
    with wave.open(str(audio),'wb') as wav:wav.setparams((1,2,48000,0,'NONE','not compressed'));wav.writeframes((samples*32767).astype('<i2').tobytes())
    scenes.append({'narration':'A short test.','image_path':str(image),'audio_path':str(audio)})
   opts={'resolution':'320x180','motion':False,'captions':False,'use_captions_tab':False,'use_transitions_tab':True,'use_effects_tab':False,'thumbnail_enabled':False,'camera_transitions_enabled':True,'camera_transition_duration':.4,'camera_transition_sfx':True,'camera_transition_volume':35,'animation_mode':'partial','animate_count':0}
   for renderer,name in ((render_video,'studio'),(render_animated_video,'animate')):
    folder=root/name
    current={**opts,'bgm_file':str(scenes[0]['audio_path'])} if name=='animate' else opts
    out=renderer(scenes,folder,current,threading.Event())
    duration,streams=probe(out)
    self.assertLess(abs(duration-8),.12);self.assertEqual({s['codec_type'] for s in streams},{'video','audio'})
    report=json.loads((folder/'clips/camera_transitions.json').read_text())
    self.assertEqual(report['frames'],200);self.assertEqual(len(report['events']),7)
    self.assertTrue(report['sfx']);self.assertTrue((folder/'clips/camera_swooshes.mp3').is_file())
   silent_folder=root/'muted';silent_folder.mkdir()
   source=out
   _,sfx=apply(source,self.timeline(),{**opts,'camera_transition_sfx':False},threading.Event())
   self.assertIsNone(sfx)
if __name__=='__main__':unittest.main()
