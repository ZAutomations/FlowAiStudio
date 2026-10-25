"""Scene ranges and independent, resumable partial-video renders."""
import copy
import json
import shutil
from pathlib import Path
from ai_studio_pipeline import atomic_json, check_cancel, fingerprint, valid_image, valid_audio


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


def compile_part(adapter,q,config,animated=False):
    start,end=scene_range(config,len(adapter.zb_scenes))
    if start>=end:raise ValueError('Parse scenes first.')
    selected=adapter.zb_scenes[start:end]
    animated_count=0
    if animated:
        from ai_studio_animate_options import animation_count
        from ai_studio_animate_media import valid_video
        animated_count=animation_count(config,len(adapter.zb_scenes),adapter.zb_scenes)
    missing=[str(start+i+1) for i,scene in enumerate(selected)
             if not (valid_video(scene.get('video_path','')) if animated and start+i<animated_count
                     else valid_image(scene.get('image_path','')))]
    if missing:raise ValueError(('Cannot compile this part. Missing scene media: ' if animated else 'Cannot compile this part. Missing scene images: ')+', '.join(missing)+'. No scenes were skipped and no images generated.')
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
        if valid_image(scene.get('image_path','')) and (not target.exists() or target.read_bytes()!=Path(scene['image_path']).read_bytes()):shutil.copy2(scene['image_path'],target)
        row=copy.deepcopy(scene);row.update(source_scene_number=i,image_path=str(target))
        if animated and scene.get('video_path'):
            video=Path(scene['video_path']);out=folder/'clips'/f'source_{i:04d}{video.suffix}'
            if video.is_file():
                if not out.exists() or out.stat().st_size!=video.stat().st_size:shutil.copy2(video,out)
                row['video_path']=str(out)
        local=next((r for r in previous.get('scenes',[]) if r.get('source_scene_number')==i and r['narration']==row['narration']),None)
        if local and not valid_audio(row.get('audio_path','')) and (not scene.get('audio_key') or local.get('audio_key')==scene.get('audio_key')):
            for key in ('audio_path','audio_key','audio_status','voice_engine','word_timings','timing_source'):
                if key in local:
                    value=local[key]
                    if key=='audio_path' and value and not Path(value).is_absolute():value=str(folder/value)
                    row[key]=value
        if valid_audio(row.get('audio_path','')):
            source_audio=Path(row['audio_path'])
            audio_target=folder/'voice'/f'source_{i:04d}{source_audio.suffix}'
            if source_audio.resolve()!=audio_target.resolve() and (not audio_target.exists() or audio_target.read_bytes()!=source_audio.read_bytes()):
                shutil.copy2(source_audio,audio_target)
            row['audio_path']=str(audio_target)
        scenes.append(row)
    atomic_json(checkpoint,{'identity':identity,'source_project':str(root),'start':start+1,'end':end})
    child={**config,'project':str(folder),'title':f'{config["title"]} — scenes {start+1}–{end}',
        'script':'\n\n'.join(s['narration'] for s in scenes),'thumbnail_enabled':False,'thumbnail_paths':[],
        'scene_start':1,'scene_end':'','part_source_project':str(root),'part_scene_start':start+1,'part_scene_end':end}
    if animated:
        from ai_studio_animate_options import partial_options
        child.update(animation_mode='partial',partial_animation_unit='scenes',animate_count=max(0,min(end,animated_count)-start))
        if config.get('animation_mode','partial')=='partial' and partial_options(config)[0]=='seconds':
            from ai_studio_animate_options import scene_duration
            child.update(partial_animation_unit='seconds',animate_seconds=max(0,float(config.get('animate_seconds',80))-sum(scene_duration(s) for s in adapter.zb_scenes[:start])))
        child['output']=''
    parent_scenes,parent_video=adapter.zb_scenes,adapter.zb_last_video
    try:
        adapter.zb_scenes=scenes;adapter.zb_last_video=None
        adapter._zb_save_project(child)
        q.put(('log','info',f'Compiling scenes {start+1}–{end} only. Copied media into {folder}; checking saved narration before rendering.'))
        if all(valid_audio(s.get('audio_path','')) for s in scenes):
            q.put(('log','info','Reusing all saved scene narration and timing; no TTS request or alignment.'))
        elif config.get('audio_source')=='existing' or config.get('narration_mode')=='continuous' or (animated and config.get('animate_narration_mode')=='cinematic'):
            if any(not valid_audio(s.get('audio_path','')) for s in scenes):
                raise ValueError('Selected part has missing/invalid saved audio. Prepare narration in the full story first, then compile again; saved audio and media are retained.')
            q.put(('log','info','Reusing measured continuous narration; no replanning or new Gemini analysis.'))
        else:
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
