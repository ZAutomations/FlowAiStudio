"""Scene ranges and independent, resumable partial-video renders."""
import copy
import json
import shutil
from pathlib import Path
from ai_studio_pipeline import atomic_json, check_cancel, fingerprint, valid_image


def scene_range(config,count):
    def number(key,default):
        value=config.get(key)
        if value in (None,''):return default
        try:
            result=int(value)
            if isinstance(value,bool) or float(value)!=result or result<1:raise ValueError()
            return result
        except (ValueError,TypeError,OverflowError):raise ValueError(f'{key.replace("_"," ").capitalize()} must be a positive whole scene number.')
    start=number('scene_start',1);end=number('scene_end',count)
    if count and not 1<=start<=end<=count:raise ValueError(f'Choose a scene range from 1 to {count}, with start no greater than end.')
    return start-1,end


def compile_part(adapter,q,config):
    start,end=scene_range(config,len(adapter.zb_scenes))
    if start>=end:raise ValueError('Parse scenes first.')
    selected=adapter.zb_scenes[start:end]
    missing=[str(start+i+1) for i,scene in enumerate(selected) if not valid_image(scene.get('image_path',''))]
    if missing:raise ValueError('Cannot compile this part. Missing scene images: '+', '.join(missing)+'. No scenes were skipped and no images generated.')
    root=Path(config['project']);folder=root/'parts'/f'part_{start+1:04d}-{end:04d}'
    identity=fingerprint('part-v1',[(start+i,scene['narration'],scene.get('visual_prompt','')) for i,scene in enumerate(selected)])
    checkpoint=folder/'part_source.json'
    if checkpoint.exists() and json.loads(checkpoint.read_text('utf-8'))['identity']!=identity:
        folder=folder/identity[:12];checkpoint=folder/'part_source.json'
    (folder/'images').mkdir(parents=True,exist_ok=True)
    for sub in ('voice','clips'):(folder/sub).mkdir(exist_ok=True)
    previous={}
    if (folder/'project.json').exists():previous=json.loads((folder/'project.json').read_text('utf-8'))
    scenes=[]
    for i,scene in enumerate(selected,start+1):
        check_cancel(adapter._zb_cancel)
        target=folder/'images'/f'scene_{i:04d}.png'
        if not target.exists() or target.read_bytes()!=Path(scene['image_path']).read_bytes():shutil.copy2(scene['image_path'],target)
        row=copy.deepcopy(scene);row.update(source_scene_number=i,image_path=str(target))
        local=next((r for r in previous.get('scenes',[]) if r.get('source_scene_number')==i and r['narration']==row['narration']),None)
        if local:
            for key in ('audio_path','audio_key','audio_status','voice_engine','word_timings','timing_source'):
                if key in local:
                    value=local[key]
                    if key=='audio_path' and value and not Path(value).is_absolute():value=str(folder/value)
                    row[key]=value
        scenes.append(row)
    atomic_json(checkpoint,{'identity':identity,'source_project':str(root),'start':start+1,'end':end})
    child={**config,'project':str(folder),'title':f'{config["title"]} — scenes {start+1}–{end}',
        'script':'\n\n'.join(s['narration'] for s in scenes),'thumbnail_enabled':False,'thumbnail_paths':[],
        'scene_start':1,'scene_end':'','part_source_project':str(root),'part_scene_start':start+1,'part_scene_end':end}
    parent_scenes,parent_video=adapter.zb_scenes,adapter.zb_last_video
    try:
        adapter.zb_scenes=scenes;adapter.zb_last_video=None
        adapter._zb_save_project(child)
        q.put(('log','info',f'Compiling scenes {start+1}–{end} only. Copied images into {folder}; generating narration, then rendering.'))
        adapter._zb_voice_pass(q,child)
        adapter._zb_render_pass(q,child)
        result={'start':start+1,'end':end,'project':str(folder/'project.json'),'video':adapter.zb_last_video}
        config['_part_result']=result
        exports=config.setdefault('part_exports',[])
        exports[:]=[r for r in exports if r.get('project')!=result['project']]+[result]
        q.put(('log','success','Part saved: '+str(result['video'])))
        return result
    finally:
        adapter.zb_scenes=parent_scenes;adapter.zb_last_video=parent_video
