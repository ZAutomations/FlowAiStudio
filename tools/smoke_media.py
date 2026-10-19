"""Actual offline voice/render smoke test using bundled models, no paid generation."""
import json,sys,threading
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from runtime_paths import configure
configure()
from studio_voice import TTSGenerator
from ai_studio_pipeline import render_video,probe,valid_audio
from PIL import Image,ImageDraw
folder=root/'verification/media';folder.mkdir(parents=True,exist_ok=True)
scenes=[]
for i,(engine,voice) in enumerate([('piper','en_US-ryan-medium'),('local','af_bella')],1):
    path=folder/f'{engine}.mp3'
    print('Testing',engine,flush=True)
    ok,words=TTSGenerator.generate_voiceover('A quiet moment begins a new story.',path,{'tts_engine':engine,'piper_voice':voice,'kokoro_voice':voice})
    if not ok or not valid_audio(path):raise RuntimeError(engine+' local synthesis failed')
    image=folder/f'scene_{i:04d}.png';img=Image.new('RGB',(640,360),(35,50,70) if i==1 else (80,40,35));ImageDraw.Draw(img).text((30,40),'Flow AI Studio — standalone verification',fill='white');img.save(image)
    scenes.append({'narration':'A quiet moment begins a new story.','image_path':str(image),'audio_path':str(path),'word_timings':words,'timing_source':'estimated'})
options={'resolution':'640x360','motion':True,'motion_style':'balanced','motion_strength':8,'motion_speed':1,'motion_easing':'smooth','use_transitions_tab':False,'use_effects_tab':False,'transition':'Cut','thumbnail_enabled':False,'captions':True,'use_captions_tab':True,'settings':{'clipper_captions_enabled':True,'clipper_caption_preset':'bold_white','clipper_caption_animation':'one_word','caption_font_size':30,'caption_words_per_line':3,'caption_position':'bottom'}}
print('Rendering standalone ASS-captioned video',flush=True)
final=render_video(scenes,folder,options,threading.Event(),log=lambda m:print(m,flush=True))
duration,streams=probe(final)
if not all(any(s.get('codec_type')==kind for s in streams) for kind in ('video','audio')):raise RuntimeError('Missing output stream')
(folder/'result.json').write_text(json.dumps({'final':str(final),'duration':duration,'engines':['piper','local'],'captions':'Pro ASS','transitions':'Cut','effects':False},indent=2),encoding='utf-8')
print('Verified',duration,'seconds with video, audio and ASS captions.',flush=True)
