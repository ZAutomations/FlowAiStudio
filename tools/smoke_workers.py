import json,sys,subprocess,shutil,threading
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from runtime_paths import configure
configure()
from ai_studio_pipeline import probe

def worker(kind,payload):
    request={'kind':kind,'payload':payload,'settings':{'clipper_captions_enabled':True,'clipper_caption_preset':'bold_white','clipper_caption_animation':'one_word','piper_voice':'en_US-ryan-medium'},'cancel':str(root/'verification/unused.cancel')}
    p=subprocess.run([sys.executable,'-X','utf8','-m','desktop.worker'],input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',cwd=root,timeout=150)
    print(p.stdout,flush=True)
    if p.returncode:raise RuntimeError(p.stderr or p.stdout)
    events=[json.loads(s[9:]) for s in p.stdout.splitlines() if s.startswith('@desktop:')]
    return next(e['result'] for e in reversed(events) if 'result' in e)

for kind in ('studio','animate'):
    folder=root/'verification'/('worker_'+kind)
    payload={'project':str(folder),'title':'Standalone worker verification','script':'A quiet moment begins a new story.','action':'plan','voice_engine':'piper','voice':'en_US-ryan-medium','resolution':'640x360','captions':True,'motion':False,'thumbnail_enabled':False,'character_consistency':False,'animation_mode':'full' if kind=='animate' else 'partial','animate_count':1}
    result=worker(kind,payload)
    data=json.loads((folder/'project.json').read_text('utf-8'))
    assert len(data['scenes'])==1,data['scenes']
    data['scenes'][0]['image_path']=str(root/'verification/media/scene_0001.png')
    if kind=='animate':data['scenes'][0]['video_path']=str(root/'verification/media/final.mp4')
    (folder/'project.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    worker(kind,{**payload,'action':'voice'})
    result=worker(kind,{**payload,'action':'render'})
    duration,streams=probe(result['video'])
    assert duration>0 and all(any(s.get('codec_type')==k for s in streams) for k in ('video','audio'))
    print(kind,'worker verified',duration,flush=True)
print('Both standalone worker processes verified; no browser or paid requests submitted.')
