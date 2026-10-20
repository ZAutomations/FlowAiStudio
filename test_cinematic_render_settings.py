import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ai_studio_animate_render import render_animated_video

class CinematicRenderSettingsTests(unittest.TestCase):
 def test_enabled_and_disabled_render_controls_keep_voice_clock(self):
  for camera,tab,captions in [(False,True,True),(True,False,True),(False,False,False)]:
   with self.subTest(camera=camera,tab=tab,captions=captions),tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);commands=[]
    scenes=[dict(narration='Test.',audio_path='voice.wav',image_path='image.png',cinematic_start=0)]
    timeline=[dict(index=0,start=0,duration=8,end=8,tail=0)]
    options=dict(animate_narration_mode='cinematic',animation_mode='partial',animate_count=0,resolution='320x180',transition='Cut',captions=captions,use_captions_tab=True,use_transitions_tab=tab,use_effects_tab=False,camera_transitions_enabled=camera,settings={'clipper_captions_enabled':captions,'transition_slide_in':True})
    def ffmpeg(args,*a,**kw):
     commands.append(args);Path(args[-1]).write_bytes(b'test media')
    with patch('ai_studio_animate_render.valid_audio',return_value=True),patch('ai_studio_animate_render.build_timeline',return_value=timeline),patch('ai_studio_animate_render.run_ffmpeg',side_effect=ffmpeg),patch('ai_studio_animate_render.probe',return_value=(8,[{'codec_type':'video'},{'codec_type':'audio'}])),patch('ai_studio_animate_render.write_subtitles',return_value=[]),patch('ai_studio_camera_transitions.settings'),patch('ai_studio_camera_transitions.apply',side_effect=lambda source,t,o,*a:(source,None)) as apply_camera,patch('ai_studio_tab_render.render_tab_visuals',side_effect=lambda source,*a:(source,None)) as apply_tab:
     render_animated_video(scenes,root,options)
    self.assertEqual(apply_tab.called,tab)
    self.assertEqual(apply_camera.call_args.args[2]['camera_transitions_enabled'],camera)
    data=json.loads((root/'timeline.json').read_text())
    self.assertEqual(data['captions_burned'],captions)
    self.assertEqual(data['narration_duration'],8)
    self.assertEqual(data['use_transitions_tab'],tab)
    self.assertEqual(any('-vf' in c and any('ass=captions.ass' in str(x) for x in c) for c in commands),captions)

if __name__=='__main__':unittest.main()
